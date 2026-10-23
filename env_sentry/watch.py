"""
Tiny polling watcher used by `env-sentry watch`.

No inotify dependency, no threads: just mtime + size snapshots on a short
interval, which is plenty for a handful of .env files.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

Snapshot = Dict[str, Tuple[int, int]]


def files_to_watch(root: Path) -> List[Path]:
    """All env files in ``root`` (``.env``, ``.env.*``, ``*.env``)."""
    root = Path(root)
    seen: List[Path] = []
    for pattern in (".env", ".env.*", "*.env"):
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path not in seen and not path.name.endswith(".bak"):
                seen.append(path)
    return seen


def snapshot(paths: Iterable[Path]) -> Snapshot:
    snap: Snapshot = {}
    for path in paths:
        candidate = path if hasattr(path, "stat") else Path(path)
        try:
            stat = candidate.stat()
        except OSError:
            continue
        snap[str(path)] = (stat.st_mtime_ns, stat.st_size)
    return snap


def diff_snapshots(before: Snapshot, after: Snapshot) -> List[Path]:
    """Paths added, modified or deleted between two snapshots."""
    changed = [
        Path(name) for name, meta in after.items() if before.get(name) != meta
    ]
    changed.extend(Path(name) for name in before if name not in after)
    return changed


def wait_for_change(
    paths_factory: Callable[[], List[Path]],
    interval: float = 1.0,
    timeout: Optional[float] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Optional[List[Path]]:
    """Block until the watched files change.

    Returns the list of changed paths, or ``None`` when ``timeout`` elapsed.
    """
    before = snapshot(paths_factory())
    started = clock()

    while True:
        if timeout is not None and clock() - started > timeout:
            return None
        sleep(interval)
        after = snapshot(paths_factory())
        if after != before:
            return diff_snapshots(before, after)
