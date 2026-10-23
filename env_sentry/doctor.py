"""
Environment diagnostics.

When something feels wrong ("why doesn't the hook fire?", "why is CI green?"),
`env-sentry doctor` prints the facts: python version, git state, hooks, config,
which env files exist, and whether a CI job actually runs env-sentry.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from . import hooks as hooks_mod
from .config import Config
from .envfile import EnvFile
from .gitignore import GitIgnore

OK = "ok"
WARN = "warn"
INFO = "info"


@dataclass
class Fact:
    label: str
    value: str
    status: str = INFO
    hint: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"label": self.label, "value": self.value, "status": self.status,
                "hint": self.hint}


def _git(root: Path, *args: str) -> Optional[str]:
    if not shutil.which("git"):
        return None
    try:
        result = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                                text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def ci_runs_env_sentry(root: Path) -> Optional[str]:
    """Return the CI file that mentions env-sentry, if any."""
    candidates: List[Path] = list(root.glob(".github/workflows/*.yml"))
    candidates += list(root.glob(".github/workflows/*.yaml"))
    candidates += [root / ".gitlab-ci.yml", root / ".pre-commit-config.yaml",
                   root / ".circleci" / "config.yml"]
    for path in candidates:
        try:
            if path.is_file() and "env-sentry" in path.read_text(errors="ignore"):
                return str(path.relative_to(root))
        except OSError:
            continue
    return None


def diagnose(root: Path, version: str = "") -> List[Fact]:
    root = Path(root)
    facts: List[Fact] = []

    facts.append(Fact("python", platform.python_version(),
                      OK if sys.version_info >= (3, 8) else WARN,
                      "" if sys.version_info >= (3, 8) else "Python 3.8+ is required"))
    facts.append(Fact("platform", f"{platform.system()} {platform.machine()}"))
    facts.append(Fact("env-sentry", version or "dev", OK))
    console = shutil.which("env-sentry")
    facts.append(Fact(
        "console script", console or "not on PATH", OK if console else WARN,
        "" if console else "use `python -m env_sentry.cli` in scripts and hooks",
    ))

    git_version = _git(root, "--version")
    facts.append(Fact("git", git_version or "not installed", OK if git_version else WARN))
    repo = hooks_mod.repo_root(root) if git_version else None
    facts.append(Fact("repository", str(repo) if repo else "not a git repository",
                      OK if repo else WARN,
                      "" if repo else "secret checks cannot verify ignore/tracking rules"))

    if repo:
        state = hooks_mod.status(repo)
        installed = [name for name, on in state.items() if on]
        facts.append(Fact("git hooks", ", ".join(installed) if installed else "none",
                          OK if installed else INFO,
                          "" if installed else "install one with `env-sentry hooks install`"))
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        facts.append(Fact("branch", branch or "unknown"))

    cfg = Config.load(root)
    facts.append(Fact("config", str(cfg.path) if cfg.path else "none (defaults)", INFO,
                      "" if cfg.path else "create one with `env-sentry config --init`"))

    env_files = [path for path in sorted(root.glob(".env*"))
                 if path.is_file() and not path.suffix == ".svg"]
    total_keys = sum(len(EnvFile.load(path)) for path in env_files)
    facts.append(Fact("env files", f"{len(env_files)} ({', '.join(p.name for p in env_files[:5])})"
                      if env_files else "none", OK if env_files else INFO))
    facts.append(Fact("total keys", str(total_keys)))

    private = [
        path.name for path in env_files
        if not path.name.endswith(".example")
        and (path.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH))
    ]
    facts.append(Fact("permissions", "owner-only" if not private else "group/world readable",
                      WARN if private else OK,
                      f"chmod 600 {' '.join(private)}" if private else ""))

    gitignore = GitIgnore.load(root)
    covered = gitignore.is_ignored(".env")
    facts.append(Fact(".env ignored", "yes" if covered else "no", OK if covered else WARN,
                      "" if covered else "run `env-sentry init`"))

    allowlist = (root / ".env-sentry-allow").is_file()
    facts.append(Fact("allowlist", "present" if allowlist else "none", INFO))

    ci = ci_runs_env_sentry(root) if root.is_dir() else None
    facts.append(Fact("CI integration", ci or "not configured", OK if ci else WARN,
                      "" if ci else "run `env-sentry ci --write` to add a workflow"))

    scanner_ok = os.access(root, os.R_OK)
    facts.append(Fact("readable workspace", "yes" if scanner_ok else "no",
                      OK if scanner_ok else WARN))

    return facts


def suggestions(facts: List[Fact]) -> List[str]:
    return [fact.hint for fact in facts if fact.hint and fact.status == WARN]
