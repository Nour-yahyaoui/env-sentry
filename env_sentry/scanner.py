"""
Filesystem walking for the scanner.

Kept separate from the detection rules so both stay readable. Handles the
boring-but-important parts: skipping vendor/build directories, skipping
binaries and huge files, honouring .gitignore (except for the ``.env*`` files
you actually want checked), and never following symlinks out of the tree.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

from .gitignore import GitIgnore

DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "env", ".env.d",
    "__pycache__", "dist", "build", "target", "vendor", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", ".nox", ".next", ".nuxt", ".svelte-kit",
    ".idea", ".vscode", "coverage", "htmlcov", ".DS_Store", "Pods", ".terraform",
    ".gradle", ".cache",
}

DEFAULT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".rb", ".go", ".java", ".kt", ".kts", ".swift", ".php", ".cs", ".rs", ".scala",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat",
    ".yml", ".yaml", ".json", ".json5", ".toml", ".ini", ".cfg", ".conf", ".properties",
    ".xml", ".html", ".htm", ".sql", ".tf", ".tfvars", ".gradle", ".dockerfile",
    ".txt", ".md", ".rst", ".env", ".pem", ".key", ".crt", ".lock",
    ".ipynb", ".plist", ".xcconfig", ".pbxproj", ".csv",
}

MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB
BINARY_SNIFF_BYTES = 8192


def is_env_name(name: str) -> bool:
    """``.env``, ``.env.local``, ``production.env`` — all env files to us."""
    return name.startswith(".env") or name.endswith(".env") or ".env." in name


def is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(BINARY_SNIFF_BYTES)
    except OSError:
        return True
    if b"\0" in chunk:
        return True
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        # Allow mostly-text files with a few bad bytes.
        non_text = sum(1 for byte in chunk if byte < 9 or 13 < byte < 32)
        return non_text > len(chunk) * 0.1
    return False


def is_scannable(path: Path, extensions: Optional[Sequence[str]] = None) -> bool:
    if is_env_name(path.name):
        return True
    allowed = set(extensions) if extensions else DEFAULT_EXTENSIONS
    if path.suffix.lower() in allowed:
        return True
    # extension-less files such as Dockerfile, Makefile, .npmrc
    return path.suffix == "" and path.name.lower() in {
        "dockerfile", "makefile", ".npmrc", ".pypirc", ".netrc", ".htpasswd",
    }


def staged_files(root: Path) -> List[Path]:
    """Files staged for commit (added/copied/modified), relative to ``root``."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=str(root), capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    paths = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        candidate = Path(root) / line
        if candidate.is_file() and not any(part in DEFAULT_IGNORE_DIRS for part in candidate.parts):
            paths.append(candidate)
    return paths


def iter_files(
    root: Path,
    extensions: Optional[Sequence[str]] = None,
    exclude: Sequence[str] = (),
    respect_gitignore: bool = True,
    include_ignored: bool = False,
    max_bytes: int = MAX_FILE_BYTES,
) -> Iterator[Path]:
    """Yield candidate files under ``root`` in a stable order."""
    root = Path(root)
    if root.is_file():
        yield root
        return

    gitignore = GitIgnore.load(root) if respect_gitignore else None
    excludes = [pattern.strip() for pattern in exclude if pattern.strip()]

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir

        kept: List[str] = []
        for name in sorted(dirnames):
            if name in DEFAULT_IGNORE_DIRS or name.startswith(".git"):
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if any(Path(rel).match(pattern) for pattern in excludes):
                continue
            if gitignore and gitignore.is_ignored(rel, is_dir=True):
                continue
            kept.append(name)
        dirnames[:] = kept

        for filename in sorted(filenames):
            file_path = current / filename
            rel = f"{rel_dir}/{filename}" if rel_dir else filename
            if file_path.is_symlink():
                continue
            if any(Path(rel).match(pattern) for pattern in excludes):
                continue
            if not is_scannable(file_path, extensions):
                continue
            if gitignore and not include_ignored and gitignore.is_ignored(rel):
                # Ignored files cannot be committed, so scanning them only
                # produces noise — unless the user explicitly asks for them.
                continue
            try:
                if file_path.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            if is_binary(file_path):
                continue
            yield file_path
