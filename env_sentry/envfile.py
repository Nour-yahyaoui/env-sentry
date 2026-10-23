"""
A small, dependency-free model of a ``.env`` file.

Unlike a naive ````KEY=value`` string split, this keeps:

* comments, blank lines and **ordering** (so `sync`/`format` never mangle a file)
* ``export KEY=value`` prefixes
* single- and double-quoted values, including multi-line values
* inline comments (``KEY=value # note``)
* duplicate keys (reported, never silently swallowed)

Public API:
    EnvFile.load(path) / EnvFile.parse(text)  -> EnvFile
    parse_env_file(path) -> dict[str, str]    (backwards-compatible helper)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

KEY_VALUE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_EXPORT_RE = re.compile(r"^\s*export\s+")

# Values that are obviously placeholders rather than real credentials.
PLACEHOLDER_RE = re.compile(
    r"""^(?:your|my|example|placeholder|sample|xxx+|changeme|change-me|todo|tbd|
        <.*>|\$\{.*\}|\$[A-Za-z_][A-Za-z0-9_]*|
        test|fake|dummy|none|null|true|false|yes|no|on|off|
        \d+|\.\.\.)""",
    re.IGNORECASE | re.VERBOSE,
)


class Entry:
    """One ``KEY=value`` line (possibly spanning several physical lines)."""

    __slots__ = ("key", "value", "line_no", "raw", "quote", "inline_comment", "export")

    def __init__(
        self,
        key: str,
        value: str,
        line_no: int,
        raw: str,
        quote: str = "",
        inline_comment: str = "",
        export: bool = False,
    ) -> None:
        self.key = key
        self.value = value
        self.line_no = line_no
        self.raw = raw
        self.quote = quote
        self.inline_comment = inline_comment
        self.export = export

    @property
    def is_empty(self) -> bool:
        return self.value == ""

    def format(self, value: Optional[str] = None) -> str:
        """Render this entry back to a .env line, preserving its style."""
        val = self.value if value is None else value
        prefix = "export " if self.export else ""
        if self.quote:
            escaped = val.replace("\\", "\\\\").replace(self.quote, "\\" + self.quote)
            escaped = escaped.replace("\n", "\\n")
            rendered = f"{self.quote}{escaped}{self.quote}"
        elif val == "":
            rendered = ""
        elif re.search(r"\s#|^\s|\s$", val):
            rendered = f'"{val}"'
        else:
            rendered = val
        suffix = f" {self.inline_comment}" if self.inline_comment else ""
        return f"{prefix}{self.key}={rendered}{suffix}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Entry({self.key!r}, line={self.line_no}, value={'*' * 3 if self.value else ''!r})"


def _find_closing_quote(text: str, quote: str) -> int:
    """Index of the closing quote in ``text`` (which starts with ``quote``)."""
    escaped = False
    for index, char in enumerate(text[1:], start=1):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char == quote:
            return index
    return -1


_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "0": "\0"}


def _unescape_double(text: str) -> str:
    out: List[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            nxt = text[index + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _split_inline_comment(text: str) -> Tuple[str, str]:
    """Split ``value # comment`` while respecting quoted sections."""
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote and text[index - 1:index] != "\\":
                quote = ""
            continue
        if char in ("'", '"'):
            quote = char
            continue
        if char == "#" and index > 0 and text[index - 1] in " \t":
            return text[:index].rstrip(), text[index:]
    return text.strip(), ""


def _parse_value(raw: str) -> Tuple[str, str, str]:
    """Return (value, quote_char, inline_comment) for the right-hand side."""
    if raw[:1] in ("'", '"'):
        quote = raw[0]
        close = _find_closing_quote(raw, quote)
        if close != -1:
            body = raw[1:close]
            if quote == '"':
                body = _unescape_double(body)
            rest = raw[close + 1:].strip()
            comment = rest if rest.startswith("#") else ""
            return body, quote, comment
        # Unterminated quote: treat the whole thing as a literal value.
        return raw[1:], quote, ""
    body, comment = _split_inline_comment(raw)
    return body, "", comment


class EnvFile:
    """An ordered, comment-preserving view of a .env file."""

    def __init__(self, lines: Optional[List[object]] = None, path: Optional[Path] = None,
                 exists: bool = True) -> None:
        self.lines: List[object] = lines if lines is not None else []
        self.path = Path(path) if path is not None else None
        self.exists = exists

    # -- construction -------------------------------------------------
    @classmethod
    def parse(cls, text: str, path: Optional[Path] = None) -> "EnvFile":
        physical = text.splitlines()
        lines: List[object] = []
        index = 0
        while index < len(physical):
            line = physical[index]
            lineno = index + 1
            if not line.strip() or line.lstrip().startswith("#"):
                lines.append(line)
                index += 1
                continue
            match = KEY_VALUE_RE.match(line)
            if not match:
                lines.append(line)
                index += 1
                continue

            rest = match.group(2)
            consumed = 1
            # Multi-line quoted values: keep swallowing lines until the quote closes.
            if rest[:1] in ("'", '"') and _find_closing_quote(rest, rest[0]) == -1:
                while index + consumed < len(physical):
                    rest += "\n" + physical[index + consumed]
                    consumed += 1
                    if _find_closing_quote(rest, rest[0]) != -1:
                        break

            value, quote, comment = _parse_value(rest)
            entry = Entry(
                key=match.group(1),
                value=value,
                line_no=lineno,
                raw="\n".join(physical[index:index + consumed]),
                quote=quote,
                inline_comment=comment,
                export=bool(_EXPORT_RE.match(line)),
            )
            lines.append(entry)
            index += consumed
        return cls(lines, path=path, exists=True)

    @classmethod
    def load(cls, path: Path) -> "EnvFile":
        path = Path(path)
        if not path.exists():
            return cls([], path=path, exists=False)
        return cls.parse(path.read_text(errors="ignore"), path=path)

    # -- access -------------------------------------------------------
    @property
    def entries(self) -> List[Entry]:
        return [line for line in self.lines if isinstance(line, Entry)]

    def keys(self) -> List[str]:
        return [entry.key for entry in self.entries]

    def values(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for entry in self.entries:
            out.setdefault(entry.key, entry.value)
        return out

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        for entry in self.entries:
            if entry.key == key:
                return entry.value
        return default

    def __contains__(self, key: object) -> bool:
        return any(entry.key == key for entry in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def duplicates(self) -> Dict[str, List[int]]:
        seen: Dict[str, List[int]] = {}
        for entry in self.entries:
            seen.setdefault(entry.key, []).append(entry.line_no)
        return {key: line_nos for key, line_nos in seen.items() if len(line_nos) > 1}

    def empty_keys(self) -> List[str]:
        return [entry.key for entry in self.entries if entry.is_empty]

    # -- rendering ----------------------------------------------------
    def render(self) -> str:
        out: List[str] = []
        for line in self.lines:
            out.append(line.format() if isinstance(line, Entry) else line)
        text = "\n".join(out)
        return text + "\n" if text else ""

    def render_placeholders(self, header: Optional[str] = None) -> str:
        """Render a redacted template: comments kept, every value scrubbed."""
        out: List[str] = []
        if header:
            out.append(header.rstrip("\n"))
        for line in self.lines:
            if isinstance(line, Entry):
                out.append(f"{entry_prefix(line)}{line.key}={placeholder_for(line.key, line.value)}")
            else:
                out.append(line)
        text = "\n".join(out)
        return text + "\n" if text else ""


def entry_prefix(entry: Entry) -> str:
    return "export " if entry.export else ""


def placeholder_for(key: str, value: str = "") -> str:
    """A safe, obvious placeholder derived from the key name."""
    lowered = key.lower()
    if any(token in lowered for token in ("port", "timeout", "retries", "ttl", "count")):
        return value if value.isdigit() else "0"
    if any(token in lowered for token in ("debug", "enabled", "verbose")):
        return "false"
    if any(token in lowered for token in ("url", "uri", "dsn", "endpoint", "host")):
        return "https://example.com"
    if any(token in lowered for token in ("email", "mail")):
        return "you@example.com"
    if any(token in lowered for token in ("path", "dir", "file")):
        return "/path/to/your/file"
    return f"your_{lowered}_here"


def is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_RE.match(value.strip()))


def parse_env_text(text: str) -> Dict[str, str]:
    return EnvFile.parse(text).values()


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse a .env-style file into a dict of key -> value."""
    return EnvFile.load(Path(path)).values()


def key_diff(left: List[str], right: List[str]) -> Tuple[List[str], List[str]]:
    """Return (keys only in left, keys only in right), preserving order."""
    left_set, right_set = set(left), set(right)
    only_left = [k for k in dict.fromkeys(left) if k not in right_set]
    only_right = [k for k in dict.fromkeys(right) if k not in left_set]
    return only_left, only_right
