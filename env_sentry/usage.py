"""
Find the two kinds of drift `check` can't see.

* **Unused keys** — defined in ``.env`` but never read by any code. Dead
  credentials are still credentials: they deserve deletion.
* **Undefined keys** — read by code but missing from ``.env``. That's the
  ``KeyError: 'STRIPE_KEY'`` waiting for your next deploy.

References are found for Python, Node/Deno/Bun, Go, Ruby, PHP, Java/Kotlin,
Rust, C#, shell scripts and docker-compose style ``${VAR}`` interpolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

from .envfile import EnvFile
from .scanner import iter_files

CODE_EXTENSIONS = {
    ".py", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".go", ".rb", ".php", ".java", ".kt", ".kts", ".scala", ".cs", ".rs", ".swift",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".pl", ".ex", ".exs", ".dart", ".lua",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".tf", ".tfvars", ".dockerfile",
    ".env.example", ".md",
}

REFERENCE_PATTERNS: List[re.Pattern] = [
    # Python
    re.compile(r"""os\.environ(?:\.get)?\s*[\[(]\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""os\.environ\.([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()"""),
    re.compile(r"""(?:os\.)?getenv\s*\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""environ\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
    # Node / bundlers
    re.compile(r"""process\.env\.([A-Za-z_][A-Za-z0-9_]*)"""),
    re.compile(r"""process\.env\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
    re.compile(r"""import\.meta\.env\.([A-Za-z_][A-Za-z0-9_]*)"""),
    re.compile(r"""(?:Bun|Deno)\.env\.(?:get\()?\s*['"]?([A-Za-z_][A-Za-z0-9_]*)"""),
    # Go
    re.compile(r"""os\.(?:Getenv|LookupEnv|Unsetenv)\s*\(\s*"([A-Za-z_][A-Za-z0-9_]*)\""""),
    # Ruby
    re.compile(r"""ENV(?:\.fetch)?\s*[\[(]\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""ENV\.([A-Z][A-Z0-9_]*)"""),
    # PHP
    re.compile(r"""getenv\s*\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]"""),
    re.compile(r"""\$_ENV\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]"""),
    # Java / Kotlin / C#
    re.compile(r"""System\.getenv\s*\(\s*"([A-Za-z_][A-Za-z0-9_]*)\""""),
    re.compile(r"""Environment\.GetEnvironmentVariable\s*\(\s*"([A-Za-z_][A-Za-z0-9_]*)\""""),
    # Rust
    re.compile(r"""env::var\s*\(\s*"([A-Za-z_][A-Za-z0-9_]*)\""""),
    re.compile(r"""std::env::var\s*\(\s*"([A-Za-z_][A-Za-z0-9_]*)\""""),
    # Shell / compose interpolation: ${VAR} and ${VAR:-default}
    re.compile(r"""\$\{([A-Z_][A-Za-z0-9_]*)(?::?-[^}]*)?\}"""),
]

SHELL_BARE_RE = re.compile(r"(?<![\w$])\$([A-Z][A-Z0-9_]{2,})\b")

# Shell built-ins and boilerplate that are not project variables.
SHELL_NOISE = {
    "PATH", "HOME", "PWD", "OLDPWD", "USER", "SHELL", "TERM", "LANG", "LC_ALL",
    "TMPDIR", "HOSTNAME", "UID", "GID", "RANDOM", "SECONDS", "LINENO", "IFS",
    "BASH_SOURCE", "BASH_VERSION", "FUNCNAME", "PS1", "EDITOR", "PAGER",
}

# Files where a "reference" is really documentation, not code.
DOC_SUFFIXES = {".md", ".rst", ".txt"}


@dataclass
class UsageReport:
    env_keys: List[str] = field(default_factory=list)
    references: Dict[str, List[str]] = field(default_factory=dict)
    ignore: Set[str] = field(default_factory=set)

    def used_keys(self) -> List[str]:
        return [key for key in self.env_keys if key in self.references]

    def unused_keys(self) -> List[str]:
        return [key for key in self.env_keys if key not in self.references]

    def undefined_keys(self) -> List[str]:
        known = set(self.env_keys)
        found = {
            key for key in set(self.references) - known - SHELL_NOISE - self.ignore
            if re.fullmatch(r"[A-Z][A-Z0-9_]{1,}", key)
        }
        return sorted(found)

    def reference_count(self, key: str) -> int:
        return len(self.references.get(key, []))


def scan_references(paths: Sequence[Path], skip: Optional[Set[str]] = None) -> Dict[str, List[str]]:
    references: Dict[str, List[str]] = {}
    skip = skip or set()
    for path in paths:
        if path.name.startswith(".env"):
            continue
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        is_doc = path.suffix in DOC_SUFFIXES
        found: Set[str] = set()
        for pattern in REFERENCE_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(1)
                if value in SHELL_NOISE or value in skip:
                    continue
                # Inside docs, only trust explicit ${VAR} / os.environ forms.
                if is_doc and not re.search(r"[{$]", match.group(0)):
                    continue
                found.add(value)
        for pattern in ([] if is_doc else [SHELL_BARE_RE]):
            for match in pattern.finditer(text):
                value = match.group(1)
                if value not in SHELL_NOISE and value not in skip:
                    found.add(value)
        for key in found:
            references.setdefault(key, []).append(str(path))
    return references


def analyse(
    root: Path,
    env_path: Optional[Path] = None,
    ignore: Optional[Set[str]] = None,
    exclude: Sequence[str] = (),
) -> UsageReport:
    root = Path(root)
    env_path = Path(env_path) if env_path else root / ".env"
    env = EnvFile.load(env_path)
    report = UsageReport(env_keys=env.keys(), ignore=set(ignore or ()))

    files = [
        path for path in iter_files(root, extensions=CODE_EXTENSIONS, exclude=exclude)
        if not path.name.startswith(".env")
    ]
    report.references = scan_references(files, skip=report.ignore)
    return report


def to_dict(report: UsageReport) -> Dict[str, object]:
    return {
        "env_keys": report.env_keys,
        "used": report.used_keys(),
        "unused": report.unused_keys(),
        "undefined": report.undefined_keys(),
        "references": {key: len(paths) for key, paths in sorted(report.references.items())
                       if key in report.env_keys},
    }
