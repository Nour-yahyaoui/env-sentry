"""
Merge one env file into another without destroying comments or order.

Typical uses:

* pull new keys from a teammate's ``.env.example`` into your ``.env``
* fold a stack-specific template into an existing file
* remove dead keys that no longer exist anywhere else (`prune`)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .envfile import EnvFile, Entry, placeholder_for


@dataclass
class MergePlan:
    added: List[str] = field(default_factory=list)
    overwritten: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.overwritten)

    def summary(self) -> str:
        return (f"{len(self.added)} added, {len(self.overwritten)} overwritten, "
                f"{len(self.skipped)} left alone")


def _matches(key: str, patterns: Sequence[str]) -> bool:
    return not patterns or any(fnmatch(key, pattern) for pattern in patterns)


def plan_merge(
    target: EnvFile,
    source: EnvFile,
    overwrite: bool = False,
    with_values: bool = False,
    only: Sequence[str] = (),
    skip: Sequence[str] = (),
) -> MergePlan:
    plan = MergePlan()
    existing = set(target.keys())
    for entry in source.entries:
        key = entry.key
        if not _matches(key, only):
            continue
        if skip and any(fnmatch(key, pattern) for pattern in skip):
            continue
        value = entry.value if with_values else placeholder_for(key, entry.value)
        if key not in existing:
            target.lines.append(Entry(key=key, value=value, line_no=0, raw=""))
            plan.added.append(key)
        elif overwrite:
            for target_entry in target.entries:
                if target_entry.key == key:
                    target_entry.value = value
                    break
            plan.overwritten.append(key)
        else:
            plan.skipped.append(key)
    return plan


def merge_files(
    target_path: Path,
    source_path: Path,
    overwrite: bool = False,
    with_values: bool = False,
    only: Sequence[str] = (),
    skip: Sequence[str] = (),
    dry_run: bool = False,
) -> MergePlan:
    target_path = Path(target_path)
    source_path = Path(source_path)

    target = EnvFile.load(target_path)
    source = EnvFile.load(source_path)
    if not source.exists:
        raise FileNotFoundError(f"{source_path} not found")

    plan = plan_merge(target, source, overwrite=overwrite, with_values=with_values,
                      only=only, skip=skip)
    if plan.changed and not dry_run:
        target_path.write_text(target.render())
    return plan


@dataclass
class PrunePlan:
    removed: List[str] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"{len(self.removed)} removed, {len(self.kept)} kept"


def prune(
    env_path: Path,
    keep_keys: Sequence[str],
    keep_patterns: Sequence[str] = (),
    dry_run: bool = True,
    backup: bool = True,
) -> Tuple[PrunePlan, Optional[Path]]:
    """Remove keys from ``env_path`` that are not in ``keep_keys``."""
    env_path = Path(env_path)
    env = EnvFile.load(env_path)
    keep = set(keep_keys)
    plan = PrunePlan()
    surviving = []

    for line in env.lines:
        if isinstance(line, Entry):
            if line.key in keep or any(fnmatch(line.key, pattern) for pattern in keep_patterns):
                plan.kept.append(line.key)
                surviving.append(line)
            else:
                plan.removed.append(line.key)
        else:
            surviving.append(line)

    backup_path = None
    if plan.removed and not dry_run:
        if backup:
            backup_path = env_path.with_suffix(env_path.suffix + ".bak")
            backup_path.write_text(env_path.read_text())
        env.lines = surviving
        env_path.write_text(env.render())

    return plan, backup_path
