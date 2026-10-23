"""
Scan git history for secrets that were committed and later "removed".

Deleting a key from .env does not delete it from history. This walks the last
N commits, replays the added lines through the detection engine, and reports
what is still recoverable with `git show`.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .detect import HIGH, SEVERITY_RANK, AllowList, Finding, scan_text

COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
DIFF_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Paths worth replaying; everything else is skipped to keep the walk fast.
INTERESTING = re.compile(
    r"(\.env|\.envrc|\.npmrc|\.pypirc|\.netrc|secrets?\.(ya?ml|json|toml|txt)|"
    r"credentials|\.pem$|\.key$|\.pfx$|id_(rsa|ed25519|ecdsa))",
    re.IGNORECASE,
)


@dataclass
class HistoryFinding:
    commit: str
    author: str
    date: str
    path: str
    line: int
    rule: str
    severity: str
    value: str = ""

    def to_dict(self) -> Dict[str, object]:
        from .redact import mask_value

        return {
            "commit": self.commit,
            "author": self.author,
            "date": self.date,
            "path": self.path,
            "line": self.line,
            "rule": self.rule,
            "severity": self.severity,
            "match": mask_value(self.value),
        }


def _git(root: Path, *args: str, timeout: int = 120) -> Optional[str]:
    try:
        result = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                                text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def is_repo(root: Path) -> bool:
    return _git(Path(root), "rev-parse", "--is-inside-work-tree") is not None


def scan_history(
    root: Path,
    depth: int = 100,
    allowlist: Optional[AllowList] = None,
    min_severity: str = HIGH,
    include_all_files: bool = False,
) -> List[HistoryFinding]:
    """Scan the added lines of the last ``depth`` commits on all branches."""
    root = Path(root)
    threshold = SEVERITY_RANK.get(min_severity, 0)
    log = _git(
        root, "log", "--all", f"-n{depth}", "--pretty=format:COMMIT\t%H\t%an\t%ad",
        "--date=short", "-p", "--unified=0", "--no-color", "--no-ext-diff",
    )
    if not log:
        return []

    findings: List[HistoryFinding] = []
    commit = author = date = ""
    path = ""
    line_no = 0

    for raw in log.splitlines():
        if raw.startswith("COMMIT\t"):
            parts = raw.split("\t")
            commit = parts[1][:10]
            author = parts[2] if len(parts) > 2 else ""
            date = parts[3] if len(parts) > 3 else ""
            path = ""
            continue

        file_match = DIFF_FILE_RE.match(raw)
        if file_match:
            path = file_match.group(1)
            continue
        if raw.startswith("+++ /dev/null"):
            path = ""
            continue

        hunk = HUNK_RE.match(raw)
        if hunk:
            line_no = int(hunk.group(1))
            continue

        if not raw.startswith("+") or raw.startswith("+++"):
            continue
        current_line = line_no
        line_no += 1

        if not path:
            continue
        if not include_all_files and not INTERESTING.search(path):
            continue

        content = raw[1:]
        for finding in scan_text(content, path=path, is_env_file=path.endswith(".env")):
            if SEVERITY_RANK.get(finding.severity, 0) < threshold:
                continue
            if allowlist and allowlist.allows(finding):
                continue
            findings.append(HistoryFinding(
                commit=commit, author=author, date=date, path=path,
                line=current_line, rule=finding.rule, severity=finding.severity,
                value=finding.value,
            ))
        if len(findings) > 5000:  # pragma: no cover - safety valve
            break

    return findings


def env_files_in_history(root: Path, depth: int = 200) -> List[str]:
    """Paths of env-like files that were ever committed."""
    out = _git(root, "log", "--all", f"-n{depth}", "--pretty=format:", "--name-only",
               "--diff-filter=A")
    if not out:
        return []
    seen = []
    for line in out.splitlines():
        line = line.strip()
        if line and INTERESTING.search(line) and line not in seen:
            seen.append(line)
    return seen
