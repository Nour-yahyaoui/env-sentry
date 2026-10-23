"""
Compare two .env files — safely.

`diff` is the command you actually want when handing .env files to a teammate
or comparing local vs production: values are masked by default, so the output
can live in a PR comment. Add ``--show-values`` when you really mean it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .envfile import EnvFile
from .redact import mask_value

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"
SAME = "same"

SYMBOLS = {ADDED: "+", REMOVED: "-", CHANGED: "~", SAME: "="}


@dataclass
class Change:
    key: str
    kind: str
    old: Optional[str] = None
    new: Optional[str] = None
    old_line: int = 0
    new_line: int = 0

    def render(self, show_values: bool = False, width: int = 28) -> str:
        label = f"{SYMBOLS[self.kind]} {self.key.ljust(width)}"
        if self.kind == ADDED:
            return f"{label} {self._show(self.new, show_values)}"
        if self.kind == REMOVED:
            return f"{label} {self._show(self.old, show_values)}"
        return (f"{label} {self._show(self.old, show_values)} → "
                f"{self._show(self.new, show_values)}")

    @staticmethod
    def _show(value: Optional[str], show_values: bool) -> str:
        if value is None:
            return ""
        if value == "":
            return "(empty)"
        return value if show_values else mask_value(value)

    def to_dict(self, show_values: bool = False) -> Dict[str, object]:
        def value(raw: Optional[str]) -> Optional[str]:
            if raw is None or show_values:
                return raw
            return mask_value(raw)

        return {"key": self.key, "kind": self.kind, "old": value(self.old), "new": value(self.new)}


def compare(left: EnvFile, right: EnvFile, include_same: bool = False) -> List[Change]:
    """Changes needed to turn ``left`` into ``right``."""
    left_first: Dict[str, object] = {}
    for entry in left.entries:
        left_first.setdefault(entry.key, entry)
    right_first: Dict[str, object] = {}
    for entry in right.entries:
        right_first.setdefault(entry.key, entry)

    changes: List[Change] = []
    for key, entry in right_first.items():
        if key not in left_first:
            changes.append(Change(key, ADDED, new=entry.value, new_line=entry.line_no))
            continue
        old_entry = left_first[key]
        if old_entry.value != entry.value:
            changes.append(Change(key, CHANGED, old=old_entry.value, new=entry.value,
                                  old_line=old_entry.line_no, new_line=entry.line_no))
        elif include_same:
            changes.append(Change(key, SAME, old=old_entry.value, new=entry.value,
                                  old_line=old_entry.line_no, new_line=entry.line_no))
    for key, entry in left_first.items():
        if key not in right_first:
            changes.append(Change(key, REMOVED, old=entry.value, old_line=entry.line_no))

    order = {key: index for index, key in enumerate(
        dict.fromkeys(list(left_first) + list(right_first)))}
    changes.sort(key=lambda change: (order.get(change.key, 10 ** 6), change.key))
    return changes


def counts(changes: List[Change]) -> Dict[str, int]:
    tally = {ADDED: 0, REMOVED: 0, CHANGED: 0, SAME: 0}
    for change in changes:
        tally[change.kind] = tally.get(change.kind, 0) + 1
    return tally


def summary(changes: List[Change]) -> str:
    tally = counts(changes)
    parts = [f"{tally[ADDED]} added", f"{tally[REMOVED]} removed", f"{tally[CHANGED]} changed"]
    if tally[SAME]:
        parts.append(f"{tally[SAME]} unchanged")
    return ", ".join(parts)


def only_differences(changes: List[Change]) -> List[Change]:
    return [change for change in changes if change.kind != SAME]
