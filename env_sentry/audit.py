"""
Repository health audit.

`check` answers one question. `audit` asks eleven, weighs the answers and
gives you a 0-100 score with a letter grade — the thing you put in a README
badge or a CI gate.
"""

from __future__ import annotations

import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import lint
from .detect import AllowList, looks_like_secret, scan_file
from .envfile import EnvFile, is_placeholder
from .gitignore import GitIgnore

PASS = "pass"
WARN = "warn"
FAIL = "fail"

LEVEL_WEIGHT = {FAIL: 15, WARN: 5, PASS: 0}


@dataclass
class Check:
    ident: str
    title: str
    status: str
    message: str
    fix: str = ""
    weight: int = 15

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.ident,
            "title": self.title,
            "status": self.status,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class AuditResult:
    checks: List[Check] = field(default_factory=list)

    @property
    def score(self) -> int:
        penalty = 0
        possible = 0
        for check in self.checks:
            possible += check.weight
            if check.status == FAIL:
                penalty += check.weight
            elif check.status == WARN:
                penalty += max(3, check.weight // 3)
        if possible == 0:
            return 100
        return max(0, round(100 * (1 - penalty / possible)))

    @property
    def grade(self) -> str:
        score = self.score
        if score >= 95:
            return "A+"
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"

    @property
    def counts(self) -> Dict[str, int]:
        tally = {PASS: 0, WARN: 0, FAIL: 0}
        for check in self.checks:
            tally[check.status] += 1
        return tally

    def failures(self) -> List[Check]:
        return [check for check in self.checks if check.status == FAIL]

    def to_dict(self) -> Dict[str, object]:
        return {
            "score": self.score,
            "grade": self.grade,
            "counts": self.counts,
            "checks": [check.to_dict() for check in self.checks],
        }


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def is_git_repo(root: Path) -> bool:
    return _git(root, "rev-parse", "--is-inside-work-tree") is not None


def _git_tracked(root: Path, path: Path) -> bool:
    try:
        rel = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(path)
    out = _git(root, "ls-files", "--error-unmatch", rel)
    return out is not None


def _git_history_has(root: Path, path: Path) -> bool:
    try:
        rel = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(path)
    out = _git(root, "log", "--all", "--format=%H", "-n", "1", "--", rel)
    return bool(out and out.strip())


def audit(
    root: Path,
    env_path: Optional[Path] = None,
    example_path: Optional[Path] = None,
    allowlist: Optional[AllowList] = None,
) -> AuditResult:
    root = Path(root)
    env_path = Path(env_path) if env_path else root / ".env"
    example_path = Path(example_path) if example_path else root / ".env.example"
    result = AuditResult()
    add = result.checks.append

    git = is_git_repo(root)
    gitignore = GitIgnore.load(root) if git else GitIgnore([])

    # 1. .env exists
    env = EnvFile.load(env_path)
    if env.exists:
        add(Check("env-exists", ".env exists", PASS,
                    f"{env_path.name} found with {len(env)} key(s)"))
    else:
        add(Check("env-exists", ".env exists", WARN,
                    f"{env_path.name} not found in {root}",
                    "Create it with `env-sentry init`"))

    # 2. .env.example exists
    example = EnvFile.load(example_path)
    if example.exists:
        add(Check("example-exists", ".env.example exists", PASS, f"{example_path.name} found", weight=10))
    else:
        add(Check("example-exists", ".env.example exists", FAIL,
                    f"{example_path.name} is missing — teammates can't onboard",
                    "Run `env-sentry sync` to generate it from .env"))

    # 3. key parity
    if env.exists and example.exists:
        missing = [key for key in env.keys() if key not in example]
        extra = [key for key in example.keys() if key not in env]
        if missing:
            add(Check("example-in-sync", "Template covers every key", FAIL,
                        f"{len(missing)} key(s) in {env_path.name} missing from "
                        f"{example_path.name}: {', '.join(missing[:5])}",
                        "Run `env-sentry sync` to regenerate the template"))
        elif extra:
            add(Check("example-in-sync", "Template covers every key", WARN,
                        f"{len(extra)} key(s) in {example_path.name} are not set locally: "
                        f"{', '.join(extra[:5])}",
                        "Add them to your .env, or remove them from the template"))
        else:
            add(Check("example-in-sync", "Template covers every key", PASS,
                        "template and local keys match"))

    # 4. gitignored
    try:
        rel_env = env_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel_env = env_path.name
    if git:
        if gitignore.is_ignored(rel_env):
            add(Check("env-ignored", ".env is git-ignored", PASS,
                        f"{rel_env} matches .gitignore"))
        else:
            add(Check("env-ignored", ".env is git-ignored", FAIL,
                        f"{rel_env} is NOT ignored — one `git add .` from a leak",
                        "Run `env-sentry init` to add it to .gitignore"))

        # 5. gitignored but still tracked
        if _git_tracked(root, env_path):
            add(Check("env-tracked", ".env is not tracked by git", FAIL,
                        f"{rel_env} is committed to the repository",
                        f"git rm --cached {rel_env} then commit the removal"))
        else:
            add(Check("env-tracked", ".env is not tracked by git", PASS,
                        "no tracked env file"))

        # 6. ever committed (history leak)
        if _git_history_has(root, env_path):
            add(Check("env-history", ".env never reached git history", FAIL,
                        f"{rel_env} appears in git history — assume the secrets are burned",
                        "Rotate every credential, then purge history with git-filter-repo"))
        else:
            add(Check("env-history", ".env never reached git history", PASS,
                        "no .env commits found"))
    else:
        add(Check("env-ignored", ".env is git-ignored", WARN,
                    "not a git repository, cannot verify ignore/tracking rules",
                    "Run this inside your project's git checkout"))
        add(Check("env-tracked", ".env is not tracked by git", PASS, "skipped (no git)", weight=25))
        add(Check("env-history", ".env never reached git history", PASS, "skipped (no git)", weight=25))

    # 7. permissions
    if env.exists:
        try:
            mode = env_path.stat().st_mode
        except OSError:
            mode = 0
        if mode and (mode & (stat.S_IRGRP | stat.S_IROTH)):
            add(Check("env-permissions", ".env is private", WARN,
                        f"{env_path.name} is readable by other users "
                        f"(mode {stat.S_IMODE(mode):o})",
                        f"chmod 600 {env_path.name}"))
        else:
            add(Check("env-permissions", ".env is private", PASS, "owner-only permissions", weight=5))

    # 8. duplicates
    if env.exists:
        duplicates = env.duplicates()
        if duplicates:
            add(Check("env-duplicates", "No duplicate keys", WARN,
                        "duplicate keys: " + ", ".join(duplicates),
                        "Remove the older definition; the last one wins"))
        else:
            add(Check("env-duplicates", "No duplicate keys", PASS, "keys are unique", weight=5))

    # 9. empty secret values
    if env.exists:
        empty = [
            entry.key for entry in env.entries
            if entry.value == "" or is_placeholder(entry.value)
        ]
        if empty:
            add(Check("env-filled", "Secrets are filled in", WARN,
                        f"{len(empty)} key(s) are empty or still placeholders: "
                        f"{', '.join(empty[:5])}",
                        "Run `env-sentry gen` to create strong values"))
        else:
            add(Check("env-filled", "Secrets are filled in", PASS,
                        "every key has a value"))

    # 10. template has no real secrets
    if not example.exists:
        add(Check("example-clean", ".env.example holds no real secrets", PASS,
                  "skipped (no template)"))
    else:
        suspicious = [key for key, value in example.values().items()
                      if looks_like_secret(key, value)]
        findings = scan_file(example_path, allowlist=allowlist) if example.exists else []
        if suspicious or findings:
            detail = ", ".join(suspicious[:5]) or ", ".join(
                sorted({finding.rule for finding in findings})[:5]
            )
            add(Check("example-clean", ".env.example holds no real secrets", FAIL,
                        f"the template looks like it contains real credentials ({detail})",
                        "Replace them with placeholders — the values are already committed"))
        else:
            add(Check("example-clean", ".env.example holds no real secrets", PASS,
                        "template only contains placeholders"))

    # 11. syntax lint
    if env.exists:
        issues = lint.lint_file(env_path)
        errors = [issue for issue in issues if issue.level == lint.ERROR]
        warnings = [issue for issue in issues if issue.level == lint.WARNING]
        if errors:
            add(Check("env-lint", ".env is well formed", FAIL,
                        f"{len(errors)} syntax error(s): {errors[0].message}",
                        "Run `env-sentry lint` for the full list"))
        elif warnings:
            add(Check("env-lint", ".env is well formed", WARN,
                        f"{len(warnings)} warning(s): {warnings[0].message}",
                        "Run `env-sentry lint` for the full list", weight=8))
        else:
            add(Check("env-lint", ".env is well formed", PASS, "no syntax issues", weight=10))

    return result


def audit_envs(root: Path, allowlist: Optional[AllowList] = None) -> Dict[str, AuditResult]:
    """Audit every .env* file in ``root`` that has an example counterpart."""
    results: Dict[str, AuditResult] = {}
    for env_path in sorted(Path(root).glob(".env*")):
        if env_path.name.endswith(".example") or env_path.is_dir():
            continue
        example = env_path.with_name(env_path.name + ".example")
        results[env_path.name] = audit(root, env_path, example if example.exists() else None,
                                       allowlist=allowlist)
    return results


def bar(score: int, width: int = 20) -> str:
    filled = round(width * score / 100)
    return "█" * filled + "░" * (width - filled)
