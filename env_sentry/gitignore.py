"""
Real ``.gitignore`` matching, without shelling out to git.

The old implementation only checked for an exact line match, so a project
with ``*.env`` or ``.env*`` or ``/secrets/`` in its ``.gitignore`` was told
its secrets were unprotected even though git was ignoring them fine. This
module implements the pattern rules described in ``gitignore(5)``:

* ``#`` comments and blank lines
* ``!`` negation (last matching pattern wins)
* trailing ``/`` matches directories only
* a leading ``/`` anchors the pattern to the .gitignore's own directory
* ``*`` and ``?`` never cross ``/``; ``**`` does
* nested ``.gitignore`` files apply to their own subtree
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


class Pattern:
    """A single compiled .gitignore pattern."""

    __slots__ = ("raw", "negated", "dir_only", "regex", "base")

    def __init__(self, raw: str, base: str = "") -> None:
        self.raw = raw
        self.base = base
        self.negated = raw.startswith("!")
        body = raw[1:] if self.negated else raw
        body = body.rstrip()
        self.dir_only = body.endswith("/")
        body = body.rstrip("/")
        self.regex = self._compile(body)

    @staticmethod
    def _compile(body: str) -> Optional[re.Pattern]:
        if not body:
            return None
        anchored = body.startswith("/") or "/" in body.rstrip("/")
        body = body.lstrip("/")
        out: List[str] = []
        index = 0
        while index < len(body):
            char = body[index]
            if char == "*":
                if body[index:index + 2] == "**":
                    after = body[index + 2:index + 3]
                    if after == "/":
                        out.append("(?:.*/)?")
                        index += 3
                        continue
                    out.append(".*")
                    index += 2
                    continue
                out.append("[^/]*")
            elif char == "?":
                out.append("[^/]")
            elif char == "[":
                close = body.find("]", index + 1)
                if close == -1:
                    out.append(re.escape(char))
                else:
                    inner = body[index + 1:close]
                    if inner.startswith("!"):
                        inner = "^" + inner[1:]
                    out.append(f"[{inner}]")
                    index = close
            elif char == "\\" and index + 1 < len(body):
                index += 1
                out.append(re.escape(body[index]))
            else:
                out.append(re.escape(char))
            index += 1
        prefix = "" if anchored else "(?:.*/)?"
        return re.compile(f"^{prefix}{''.join(out)}$")

    def matches(self, rel_path: str, is_dir: bool) -> bool:
        if self.regex is None:
            return False
        if self.dir_only and not is_dir:
            # A directory-only pattern still ignores files inside that dir;
            # callers pass the ancestor directory as well, so this is fine.
            return False
        return bool(self.regex.match(rel_path))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Pattern({self.raw!r})"


class GitIgnore:
    """A stack of patterns loaded from one or more .gitignore files."""

    def __init__(self, patterns: Optional[Sequence[Pattern]] = None) -> None:
        self.patterns: List[Pattern] = list(patterns or [])

    @classmethod
    def load(cls, root: Path, extra_files: Iterable[Path] = ()) -> "GitIgnore":
        root = Path(root)
        patterns: List[Pattern] = []
        files = list(extra_files)
        if root.is_dir():
            files.insert(0, root / ".gitignore")
            files.extend(_nested_gitignores(root))
        for file_path in files:
            file_path = Path(file_path)
            if not file_path.is_file():
                continue
            try:
                base = file_path.parent.relative_to(root).as_posix()
            except ValueError:
                base = ""
            base = "" if base == "." else base
            for line in file_path.read_text(errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(Pattern(_strip_trailing_spaces(line), base=base))
        return cls(patterns)

    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool:
        """Return True if ``rel_path`` (relative, posix) is ignored."""
        rel_path = rel_path.replace("\\", "/")
        while rel_path.startswith("./"):
            rel_path = rel_path[2:]
        rel_path = rel_path.lstrip("/")
        if not rel_path:
            return False
        parts = rel_path.split("/")
        # Check the path itself plus every ancestor directory, so that
        # ``build/`` also ignores ``build/secret.env``.
        candidates: List[Tuple[str, bool]] = []
        for index in range(1, len(parts) + 1):
            sub = "/".join(parts[:index])
            candidates.append((sub, index < len(parts) or is_dir))

        ignored = False
        for candidate, candidate_is_dir in candidates:
            for pattern in self.patterns:
                path_for_pattern = candidate
                if pattern.base:
                    prefix = pattern.base + "/"
                    if not candidate.startswith(prefix):
                        continue
                    path_for_pattern = candidate[len(prefix):]
                if pattern.matches(path_for_pattern, candidate_is_dir):
                    ignored = not pattern.negated
        return ignored

    def __len__(self) -> int:
        return len(self.patterns)


SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build"}


def _nested_gitignores(root: Path) -> List[Path]:
    """Every .gitignore below ``root`` (root file itself excluded)."""
    found: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        if Path(dirpath) == root:
            continue
        if ".gitignore" in filenames:
            found.append(Path(dirpath) / ".gitignore")
    return found


def _strip_trailing_spaces(line: str) -> str:
    """Remove unescaped trailing spaces, as git does."""
    while line.endswith(" ") and not line.endswith("\\ "):
        line = line[:-1]
    return line.replace("\\ ", " ").replace("\\#", "#").replace("\\!", "!")


def is_ignored(path: Path, root: Path, gitignore: Optional[GitIgnore] = None) -> bool:
    """Convenience wrapper: is ``path`` ignored by ``root``'s gitignore rules?"""
    root = Path(root)
    gitignore = gitignore or GitIgnore.load(root)
    path = Path(path)
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    return gitignore.is_ignored(rel, is_dir=path.is_dir())
