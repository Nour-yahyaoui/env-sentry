"""
Statistics about an env file.

Mostly for the "wait, how big did this file get?" moment: key counts by
category, value length and entropy distribution, placeholder debt, and
duplicated values hidden behind different key names.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .detect import SECRET_KEY_HINTS, shannon_entropy
from .envfile import EnvFile, is_placeholder

CATEGORIES: List[Tuple[str, Tuple[str, ...]]] = [
    ("database", ("db_", "database", "postgres", "mysql", "mongo", "redis", "sqlite", "dsn")),
    ("cloud", ("aws", "gcp", "google", "azure", "s3", "bucket", "cloud", "digitalocean")),
    ("auth", ("auth", "jwt", "oauth", "session", "sso", "cognito", "clerk")),
    ("payments", ("stripe", "paypal", "square", "braintree", "billing", "price")),
    ("email", ("smtp", "mail", "sendgrid", "postmark", "email")),
    ("ai", ("openai", "anthropic", "gemini", "hugging", "groq", "mistral", "llm")),
    ("observability", ("sentry", "datadog", "newrelic", "otel", "telemetry", "log")),
    ("frontend", ("vite", "next_public", "react_app", "public_", "cdn", "frontend")),
    ("infra", ("port", "host", "url", "endpoint", "domain", "region", "env", "debug")),
]


@dataclass
class EnvStats:
    path: str = ""
    keys: int = 0
    comments: int = 0
    blank_lines: int = 0
    empty_values: int = 0
    placeholders: int = 0
    duplicates: int = 0
    bytes: int = 0
    avg_length: float = 0.0
    median_length: float = 0.0
    max_length: int = 0
    entropy_avg: float = 0.0
    categories: Dict[str, int] = field(default_factory=dict)
    weak_keys: List[str] = field(default_factory=list)
    repeated_values: List[List[str]] = field(default_factory=list)
    longest_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "keys": self.keys,
            "comments": self.comments,
            "blank_lines": self.blank_lines,
            "empty_values": self.empty_values,
            "placeholders": self.placeholders,
            "duplicates": self.duplicates,
            "bytes": self.bytes,
            "avg_length": round(self.avg_length, 1),
            "median_length": round(self.median_length, 1),
            "max_length": self.max_length,
            "entropy_avg": round(self.entropy_avg, 2),
            "categories": self.categories,
            "weak_keys": self.weak_keys,
            "repeated_values": self.repeated_values,
            "longest_keys": self.longest_keys,
        }


def category_for(key: str) -> str:
    lowered = key.lower()
    for name, hints in CATEGORIES:
        if any(hint in lowered for hint in hints):
            return name
    return "other"


def analyse(env: EnvFile, path: str = "", text: str = "") -> EnvStats:
    stats = EnvStats(path=path)
    stats.keys = len(env)
    stats.comments = sum(
        1 for line in env.lines if isinstance(line, str) and line.strip().startswith("#")
    )
    stats.blank_lines = sum(
        1 for line in env.lines if isinstance(line, str) and not line.strip()
    )
    stats.duplicates = sum(len(lines) - 1 for lines in env.duplicates().values())
    stats.bytes = len(text.encode()) if text else len(env.render().encode())

    lengths: List[int] = []
    entropies: List[float] = []
    values_seen: Dict[str, List[str]] = {}

    for entry in env.entries:
        value = entry.value
        lengths.append(len(value))
        if value:
            entropies.append(shannon_entropy(value))
        else:
            stats.empty_values += 1
        if is_placeholder(value):
            stats.placeholders += 1
        if value and not is_placeholder(value) and len(value) > 3:
            values_seen.setdefault(value, []).append(entry.key)
        stats.categories[category_for(entry.key)] = stats.categories.get(category_for(entry.key), 0) + 1

    if lengths:
        stats.avg_length = statistics.fmean(lengths)
        stats.median_length = statistics.median(lengths)
        stats.max_length = max(lengths)
    if entropies:
        stats.entropy_avg = statistics.fmean(entropies)

    weak = [
        entry.key for entry in env.entries
        if entry.value and len(entry.value) < 12 and not is_placeholder(entry.value)
        and not entry.value.isdigit() and SECRET_KEY_HINTS.search(entry.key)
        and category_for(entry.key) != "infra"
    ]
    stats.weak_keys = weak
    stats.longest_keys = [
        entry.key for entry in sorted(env.entries, key=lambda item: len(item.value), reverse=True)[:5]
        if entry.value
    ]
    stats.repeated_values = [
        keys for keys in values_seen.values() if len(keys) > 1
    ]
    return stats
