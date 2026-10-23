"""
Lint a .env file for syntax and style problems.

`check` answers "is my setup consistent?". `lint` answers "is this file even
well-formed?" — the things that silently break parsers: stray text, duplicate
keys, unquoted spaces, CRLF endings, a BOM, missing final newline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .envfile import EnvFile, _find_closing_quote

ERROR = "error"
WARNING = "warning"
INFO = "info"

LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
VALID_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SUSPICIOUS_KEY_CHARS = re.compile(r"[^A-Za-z0-9_]")
MAX_VALUE_LENGTH = 4096


@dataclass
class Issue:
    line: int
    level: str
    code: str
    message: str

    def to_dict(self) -> Dict[str, object]:
        return {"line": self.line, "level": self.level, "code": self.code,
                "message": self.message}

    def __str__(self) -> str:
        return f"{self.level.upper():7} line {self.line}: {self.message}  [{self.code}]"


def lint_text(text: str) -> List[Issue]:
    issues: List[Issue] = []

    if text.startswith("\ufeff"):
        issues.append(Issue(1, WARNING, "bom", "file starts with a UTF-8 BOM; some parsers include it in the first key"))
    if "\r\n" in text:
        line = text[:text.index("\r\n")].count("\n") + 1
        issues.append(Issue(line, WARNING, "crlf",
                            "CRLF line endings found; use LF so Docker/CI parsers agree"))
    if text and not text.endswith("\n"):
        issues.append(Issue(text.count("\n") + 1, WARNING, "eof-newline",
                            "file does not end with a newline"))

    seen: Dict[str, int] = {}
    phys = text.splitlines()
    index = 0
    while index < len(phys):
        raw = phys[index]
        lineno = index + 1
        stripped = raw.strip()

        if not stripped or stripped.startswith("#"):
            if raw != raw.rstrip():
                issues.append(Issue(lineno, INFO, "trailing-space",
                                    "trailing whitespace after a comment"))
            index += 1
            continue

        match = LINE_RE.match(raw)
        if not match:
            issues.append(Issue(lineno, ERROR, "syntax",
                                "not a KEY=value line (quote values that contain spaces)"))
            index += 1
            continue

        key, rest = match.group(1), match.group(2)
        consumed = 1
        if rest[:1] in ("'", '"') and _find_closing_quote(rest, rest[0]) == -1:
            # multi-line value; verify it eventually closes
            probe = rest
            while index + consumed < len(phys) and _find_closing_quote(probe, rest[0]) == -1:
                probe += "\n" + phys[index + consumed]
                consumed += 1
            if _find_closing_quote(probe, rest[0]) == -1:
                issues.append(Issue(lineno, ERROR, "unterminated-quote",
                                    f"value for {key} opens a {rest[0]} quote that is never closed"))

        if key in seen:
            issues.append(Issue(lineno, ERROR, "duplicate-key",
                                f"{key} already defined on line {seen[key]}; the last value wins"))
        else:
            seen[key] = lineno

        if not VALID_KEY_RE.match(key):
            issues.append(Issue(lineno, WARNING, "key-style",
                                f"{key} is not SCREAMING_SNAKE_CASE (recommended for env vars)"))
        if SUSPICIOUS_KEY_CHARS.search(key):
            issues.append(Issue(lineno, ERROR, "key-chars",
                                f"{key} contains characters that shells may reject"))

        value = rest
        if value[:1] not in ("'", '"'):
            body = value.split(" #")[0].rstrip()
            if re.search(r"\s", body):
                issues.append(Issue(lineno, ERROR, "unquoted-space",
                                    f"value for {key} contains whitespace and is not quoted"))
            if "#" in body and not body.startswith("#"):
                issues.append(Issue(lineno, WARNING, "inline-hash",
                                    f"value for {key} contains '#'; quote it or parsers will truncate it"))

        if len(rest) > MAX_VALUE_LENGTH:
            issues.append(Issue(lineno, WARNING, "long-value",
                                f"value for {key} is longer than {MAX_VALUE_LENGTH} characters"))

        if re.match(r"^\s+", raw):
            issues.append(Issue(lineno, INFO, "indent", "line is indented; .env files are usually flush left"))

        index += consumed

    if not EnvFile.parse(text).entries and text.strip():
        issues.append(Issue(1, WARNING, "no-keys",
                            "no KEY=value pairs found (a fresh .env is fine, this is just a heads-up)"))

    return issues


def lint_file(path: Path) -> List[Issue]:
    path = Path(path)
    if not path.exists():
        return [Issue(0, ERROR, "missing-file", f"{path} not found")]
    try:
        text = path.read_text(errors="ignore")
    except OSError as exc:
        return [Issue(0, ERROR, "unreadable", f"cannot read {path}: {exc}")]
    return lint_text(text)


def has_errors(issues: List[Issue]) -> bool:
    return any(issue.level == ERROR for issue in issues)


def has_warnings(issues: List[Issue]) -> bool:
    return any(issue.level in (ERROR, WARNING) for issue in issues)


def summarize(issues: List[Issue]) -> str:
    counts = {ERROR: 0, WARNING: 0, INFO: 0}
    for issue in issues:
        counts[issue.level] = counts.get(issue.level, 0) + 1
    return f"{counts[ERROR]} error(s), {counts[WARNING]} warning(s), {counts[INFO]} note(s)"


def parse_issue_dicts(issues: List[Issue]) -> List[Optional[Dict[str, object]]]:
    return [issue.to_dict() for issue in issues]
