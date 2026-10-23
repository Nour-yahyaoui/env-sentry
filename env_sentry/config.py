"""
Project configuration: ``.env-sentry.json``.

Zero dependencies means no TOML parser on Python 3.8-3.10, so JSON it is.
The file is optional; when present it supplies defaults for flags you would
otherwise repeat in every CI step.

Example ``.env-sentry.json``::

    {
      "env": ".env.local",
      "example": ".env.example",
      "exclude": ["tests/fixtures/*", "docs/*"],
      "min_severity": "medium",
      "fail_on": "high",
      "ignore_keys": ["NODE_ENV", "CI"],
      "allowlist": ".env-sentry-allow"
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

FILENAMES = (".env-sentry.json", "env-sentry.json")

KNOWN_KEYS = {
    "env": str,
    "example": str,
    "exclude": list,
    "min_severity": str,
    "fail_on": str,
    "allowlist": str,
    "ignore_keys": list,
    "color": str,
}

# config key -> CLI flag that overrides it
FLAG_FOR_KEY = {
    "env": "--env",
    "example": "--example",
    "exclude": "--exclude",
    "min_severity": "--min-severity",
    "fail_on": "--fail-on",
    "allowlist": "--allowlist",
    "ignore_keys": "--ignore-keys",
    "color": "--color",
}

# config key -> argparse attribute
ATTR_FOR_KEY = {
    "env": "env",
    "example": "example",
    "exclude": "exclude",
    "min_severity": "min_severity",
    "fail_on": "fail_on",
    "allowlist": "allowlist",
    "ignore_keys": "ignore_keys",
    "color": "color",
}

TEMPLATE: Dict[str, Any] = {
    "env": ".env",
    "example": ".env.example",
    "exclude": ["node_modules/*", "dist/*"],
    "min_severity": "medium",
    "fail_on": "high",
    "ignore_keys": ["NODE_ENV", "CI"],
}


@dataclass
class Config:
    data: Dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    @classmethod
    def load(cls, start: Optional[Path] = None) -> "Config":
        """Find the nearest config file, walking up to the filesystem root."""
        current = Path(start or Path.cwd()).resolve()
        for directory in (current, *current.parents):
            for filename in FILENAMES:
                candidate = directory / filename
                if candidate.is_file():
                    try:
                        data = json.loads(candidate.read_text())
                    except (OSError, json.JSONDecodeError):
                        return cls({}, candidate)
                    if not isinstance(data, dict):
                        return cls({}, candidate)
                    return cls(data, candidate)
        return cls({}, None)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def as_list(self, key: str) -> List[str]:
        value = self.data.get(key, [])
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    def as_csv(self, key: str) -> str:
        return ",".join(self.as_list(key))

    def warnings(self) -> List[str]:
        messages = []
        for key, value in self.data.items():
            if key not in KNOWN_KEYS:
                messages.append(f"unknown key '{key}' ignored")
                continue
            expected = KNOWN_KEYS[key]
            if not isinstance(value, expected):
                messages.append(f"'{key}' should be {expected.__name__}, got {type(value).__name__}")
        return messages

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path) if self.path else None,
            "config": self.data,
        }

    def write(self, path: Path, data: Optional[Dict[str, Any]] = None) -> Path:
        path = Path(path)
        path.write_text(json.dumps(data or self.data or TEMPLATE, indent=2) + "\n")
        return path


def _explicit_flags(argv: Sequence[str]) -> set:
    flags = set()
    for token in argv:
        if token.startswith("--"):
            flags.add(token.split("=", 1)[0])
    return flags


def apply(args: Any, config: Config, argv: Sequence[str]) -> None:
    """Fill argparse defaults from config unless the flag was passed explicitly."""
    if not config.data:
        return
    explicit = _explicit_flags(argv)
    for key, attr in ATTR_FOR_KEY.items():
        if not hasattr(args, attr):
            continue
        if FLAG_FOR_KEY[key] in explicit:
            continue
        if key not in config.data:
            continue
        value = config.data[key]
        if isinstance(value, list):
            setattr(args, attr, ",".join(str(item) for item in value))
        else:
            setattr(args, attr, value)
