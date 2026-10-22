"""
Install env-sentry as a git hook.

The hook only ever touches a clearly marked block, so an existing
pre-commit script (husky, pre-commit framework, homegrown) keeps working and
`uninstall` removes exactly what we added.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Dict, Optional, Sequence

BEGIN = "# >>> env-sentry >>>"
END = "# <<< env-sentry <<<"

HOOK_BODY = """{begin}
# Installed by env-sentry {version}. Remove with: env-sentry hooks uninstall
_run_env_sentry() {{
    if command -v env-sentry >/dev/null 2>&1; then
        env-sentry "$@"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -m env_sentry.cli "$@"
    else
        echo "env-sentry: not installed; skipping hook" >&2
        return 0
    fi
}}
{commands}
{end}
"""

DEFAULT_COMMANDS: Dict[str, Sequence[str]] = {
    "pre-commit": ("scan",),
    "pre-push": ("check", "scan"),
}

HOOK_TYPES = ("pre-commit", "pre-push")


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                                text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """The git worktree root, or None when not inside a repository."""
    out = _git(Path(start or Path.cwd()), "rev-parse", "--show-toplevel")
    return Path(out) if out else None


def hooks_dir(root: Optional[Path] = None) -> Optional[Path]:
    root = Path(root or repo_root() or Path.cwd())
    out = _git(root, "rev-parse", "--git-path", "hooks")
    if not out:
        return None
    path = Path(out)
    return path if path.is_absolute() else root / path


def render_hook(hook_type: str = "pre-commit", commands: Optional[Sequence[str]] = None,
                version: str = "0.0.0") -> str:
    commands = tuple(commands or DEFAULT_COMMANDS.get(hook_type, ("scan",)))
    lines = []
    for command in commands:
        parts = command.split()
        if command == "scan":
            lines.append('_run_env_sentry scan . --fail-on high || exit 1')
        elif command == "check":
            lines.append('_run_env_sentry check || exit 1')
        elif command == "audit":
            lines.append('_run_env_sentry audit --min-score 80 || exit 1')
        else:
            lines.append(f'_run_env_sentry {" ".join(parts)} || exit 1')
    return HOOK_BODY.format(begin=BEGIN, end=END, commands="\n".join(lines), version=version)


def _strip_block(text: str) -> str:
    if BEGIN not in text:
        return text
    lines = text.splitlines()
    out, inside = [], False
    for line in lines:
        if line.strip() == BEGIN:
            inside = True
            continue
        if line.strip() == END:
            inside = False
            continue
        if not inside:
            out.append(line)
    return "\n".join(out).rstrip() + "\n" if out else ""


def install(root: Optional[Path] = None, hook_type: str = "pre-commit",
            commands: Optional[Sequence[str]] = None, version: str = "0.0.0",
            force: bool = False) -> Path:
    """Install (or update) our block inside the hook. Returns the hook path."""
    base = hooks_dir(root)
    if base is None:
        raise RuntimeError("not inside a git repository")
    base.mkdir(parents=True, exist_ok=True)
    hook_path = base / hook_type

    existing = hook_path.read_text() if hook_path.exists() else ""
    if hook_path.exists() and BEGIN not in existing and not force:
        backup = hook_path.with_suffix(hook_path.suffix + ".env-sentry.bak")
        backup.write_text(existing)
        raise FileExistsError(
            f"{hook_path} already exists and is not managed by env-sentry "
            f"(backed up to {backup.name}); re-run with --force to append our block"
        )

    block = render_hook(hook_type, commands, version)
    if BEGIN in existing:
        body = _strip_block(existing)
        content = body + ("\n" if body.strip() else "") + block
    else:
        content = existing
        if content and not content.endswith("\n"):
            content += "\n"
        content += block

    if not content.startswith("#!"):
        content = "#!/bin/sh\n" + content

    hook_path.write_text(content)
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook_path


def uninstall(root: Optional[Path] = None, hook_type: str = "pre-commit") -> bool:
    """Remove our block. Returns True if something was removed."""
    base = hooks_dir(root)
    if base is None:
        raise RuntimeError("not inside a git repository")
    hook_path = base / hook_type
    if not hook_path.exists():
        return False
    existing = hook_path.read_text()
    if BEGIN not in existing:
        return False
    remaining = _strip_block(existing)
    if remaining.strip() in ("", "#!/bin/sh"):
        hook_path.unlink()
    else:
        hook_path.write_text(remaining)
    return True


def status(root: Optional[Path] = None) -> Dict[str, bool]:
    base = hooks_dir(root)
    result = {}
    for hook_type in HOOK_TYPES:
        hook_path = (base / hook_type) if base else None
        result[hook_type] = bool(
            hook_path and hook_path.exists() and BEGIN in hook_path.read_text()
        )
    return result
