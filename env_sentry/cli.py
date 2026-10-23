"""
env-sentry
A tiny, zero-dependency CLI that keeps your .env setup safe and sane.

Commands:
    env-sentry init    Scaffold .env.example and make sure .env is git-ignored
    env-sentry check   Compare .env against .env.example and flag drift
    env-sentry sync    Regenerate .env.example from .env (values redacted)
    env-sentry scan    Walk the repo looking for hardcoded secrets
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

import json

from . import audit as audit_mod
from . import badge as badge_mod
from . import cicd
from . import completions as completions_mod
from . import config as config_mod
from . import doctor as doctor_mod
from . import history as history_mod
from . import hooks as hooks_mod
from . import merge as merge_mod
from . import stats as stats_mod
from . import templates as templates_mod
from . import watch as watch_mod
from . import detect, diffing, exporters, gensecrets, lint, report, usage as usage_mod
from .detect import AllowList, looks_like_secret
from .envfile import EnvFile, is_placeholder
from .gitignore import GitIgnore
from .scanner import staged_files
from .ui import UI, ui
from . import __author__ as AUTHOR, __version__ as VERSION


# ----------------------------------------------------------------------
# .env parsing helpers
# ----------------------------------------------------------------------

_KV_RE = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$""")


# ----------------------------------------------------------------------
# check / sync / init
# ----------------------------------------------------------------------

def cmd_check(args: argparse.Namespace) -> int:
    if getattr(args, "format", "text") == "json":
        ui.quiet = True  # keep stdout machine-readable
    env_path = Path(args.env)
    example_path = Path(args.example)

    env = EnvFile.load(env_path)
    example = EnvFile.load(example_path)
    env_vars, example_vars = env.values(), example.values()

    exit_code = 0
    warnings = 0
    report_data = {
        "env": str(env_path),
        "example": str(example_path),
        "missing_in_example": [],
        "missing_in_env": [],
        "suspicious_example": [],
        "duplicates": {},
        "empty_values": [],
        "gitignored": True,
    }

    if not env_path.exists():
        ui.warn(f"{env_path} not found (nothing to compare against).")
    if not example_path.exists():
        ui.warn(f"{example_path} not found. Run `env-sentry sync` to create it.")
        exit_code = 1

    missing_in_example = sorted(set(env_vars) - set(example_vars))
    missing_in_env = sorted(set(example_vars) - set(env_vars)) if env_path.exists() else []
    report_data["missing_in_example"] = missing_in_example
    report_data["missing_in_env"] = missing_in_env

    if missing_in_example:
        exit_code = 1
        ui.error(f"Keys in {env_path} but missing from {example_path}:")
        for key in missing_in_example:
            ui.bullet(key, "red")
        ui.detail("Run `env-sentry sync` to add them to the template.")

    if missing_in_env:
        warnings += 1
        ui.info(f"Keys in {example_path} but not set in {env_path}:")
        for key in missing_in_env:
            ui.bullet(key)
        ui.detail("Add them to your .env, or run `env-sentry merge "
                  f"{example_path} {env_path}`.")
        if args.strict:
            exit_code = 1

    # Duplicate keys silently override each other.
    duplicates = env.duplicates()
    report_data["duplicates"] = duplicates
    if duplicates:
        warnings += 1
        ui.warn(f"Duplicate keys in {env_path} (the last value wins):")
        for key, lines in duplicates.items():
            ui.bullet(f"{key} — lines {', '.join(str(line) for line in lines)}", "yellow")
        if args.strict:
            exit_code = 1

    # Keys defined but left empty: a classic "why is my app using defaults" bug.
    empty = env.empty_keys()
    report_data["empty_values"] = empty
    if empty:
        warnings += 1
        ui.warn(f"{len(empty)} key(s) in {env_path} have no value:")
        for key in empty:
            ui.bullet(key, "yellow")

    # Warn if .env.example contains what looks like a real secret
    suspicious = [key for key, value in example_vars.items() if looks_like_secret(key, value)]
    report_data["suspicious_example"] = suspicious
    if suspicious:
        exit_code = 1
        ui.error(f"{example_path} may contain REAL secret values, not placeholders:")
        for key in suspicious:
            ui.bullet(key, "red")
        ui.detail("Replace these with placeholders like `your_api_key_here` before committing.")

    # Warn if the env file is not gitignored
    if not is_gitignored_path(env_path):
        report_data["gitignored"] = False
        exit_code = 1
        ui.error(f"'{env_path.name}' does not appear to be listed in .gitignore!")
        ui.detail("Anyone who commits will leak real secrets. Run `env-sentry init` to fix this.")

    if args.strict and warnings and exit_code == 0:
        ui.error("Strict mode: warnings are treated as failures.")
        exit_code = 1

    if args.format == "json":
        payload = dict(report_data)
        payload["exit_code"] = exit_code
        ui.write(json.dumps(payload, indent=2), force=True)
        return exit_code

    if exit_code == 0 and env_path.exists():
        ui.ok(f"{env_path} and {example_path} are in sync. {env_path.name} is git-ignored. Looking good.")
    elif exit_code == 0 and not env_path.exists():
        ui.info(f"No {env_path} yet — nothing to check. Create one when you're ready.")

    return exit_code


SYNC_HEADER = "# Auto-generated by env-sentry — fill in real values in your own .env"


def cmd_sync(args: argparse.Namespace) -> int:
    env_path = Path(args.env)
    example_path = Path(args.example)

    if not env_path.exists():
        ui.error(f"{env_path} not found, nothing to sync from.")
        return 1

    env = EnvFile.load(env_path)
    if not len(env) and not getattr(args, "force", False):
        ui.warn(f"{env_path} has no KEY=value pairs; leaving {example_path} untouched.")
        ui.detail("Add keys first, or pass --force to overwrite the template anyway.")
        return 1

    header = "" if args.no_header else SYNC_HEADER
    rendered = env.render_placeholders(header=header)

    if args.merge and example_path.exists():
        existing = EnvFile.load(example_path)
        extra = [(key, value) for key, value in existing.values().items() if key not in env]
        if extra:
            rendered = rendered.rstrip("\n") + "\n"
            for key, value in extra:
                rendered += f"{key}={value}\n"
            ui.info(f"Kept {len(extra)} existing key(s) from {example_path}: "
                    + ", ".join(key for key, _ in extra[:5])
                    + ("…" if len(extra) > 5 else ""))

    previous = example_path.read_text() if example_path.exists() else None
    unchanged = previous == rendered

    if args.check:
        if unchanged:
            ui.ok(f"{example_path} is already up to date ({len(env)} keys).")
            return 0
        ui.error(f"{example_path} is stale — run `env-sentry sync` to refresh it.")
        if previous is not None:
            old_keys = set(EnvFile.parse(previous).keys())
            for key in sorted(set(env.keys()) - old_keys):
                ui.bullet(f"missing: {key}", "red")
        return 1

    if args.dry_run:
        ui.write(rendered, force=True)
        ui.info(f"Dry run: {example_path} not modified.")
        return 0

    example_path.write_text(rendered)
    if unchanged:
        ui.ok(f"{example_path} already up to date ({len(env)} placeholder keys).")
    else:
        ui.ok(f"Wrote {len(env)} placeholder keys to {example_path}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    exit_code = 0
    example_path = Path(args.example)

    if args.list_templates:
        ui.header("Available templates")
        for name in templates_mod.names():
            ui.write(f"  {name.ljust(10)} {templates_mod.describe(name)}")
        return 0

    if not example_path.exists() or args.force:
        try:
            content = templates_mod.render(args.template) if args.template else \
                "# Copy this file to .env and fill in real values\n"
        except ValueError as exc:
            ui.error(str(exc))
            return 2
        example_path.write_text(content)
        action = "Overwrote" if example_path.exists() and args.force else "Created"
        ui.ok(f"{action} {example_path}"
              + (f" from the '{args.template}' template" if args.template else ""))
    else:
        ui.info(f"{example_path} already exists, leaving it alone (use --force to replace).")

    if not args.no_gitignore:
        added = ensure_gitignored(args.env, example_path)
        if added:
            ui.ok("Added " + ", ".join(added) + " to .gitignore")
        else:
            ui.info(f"'{args.env}' is already git-ignored.")

    if args.create_env and not Path(args.env).exists():
        Path(args.env).write_text(
            "# Local secrets. Never commit this file.\n"
            "# Generated by env-sentry — fill in real values.\n"
        )
        try:
            Path(args.env).chmod(0o600)
        except OSError:  # pragma: no cover
            pass
        ui.ok(f"Created empty {args.env} (mode 600)")

    return exit_code


def ensure_gitignored(env_name: str, example_path: Path) -> list[str]:
    """Add the env file (and common variants) to .gitignore. Returns added lines."""
    gitignore_path = Path(".gitignore")
    existing = gitignore_path.read_text().splitlines() if gitignore_path.exists() else []
    patterns = {line.strip() for line in existing if line.strip() and not line.strip().startswith("#")}

    gitignore = GitIgnore.load(Path.cwd())
    try:
        rel = Path(env_name).resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        rel = env_name
    if gitignore.is_ignored(rel):
        return []

    candidates = [env_name, ".env.local", ".env.*.local", ".env.production", ".env.staging"]
    lines: list[str] = []
    for candidate in candidates:
        if candidate in patterns or candidate in lines:
            continue
        if candidate == example_path.name or candidate.endswith(".example"):
            continue
        lines.append(candidate)

    with gitignore_path.open("a") as handle:
        if existing and existing[-1].strip():
            handle.write("\n")
        elif not existing:
            handle.write("# secrets — never commit\n")
        for line in lines:
            handle.write(f"{line}\n")
    return lines


def is_gitignored(name: str) -> bool:
    """Is ``name`` (a path relative to cwd) ignored by this repo's .gitignore?"""
    return is_gitignored_path(Path(name))


def is_gitignored_path(path: Path) -> bool:
    """Full .gitignore matching (globs, negation, nested files) for ``path``."""
    path = Path(path)
    root = Path.cwd()
    gitignore = GitIgnore.load(root)
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.as_posix()
    return gitignore.is_ignored(rel, is_dir=path.is_dir())


# ----------------------------------------------------------------------
# secret detection
# ----------------------------------------------------------------------

def _load_allowlist(root: Path, explicit: str = "") -> AllowList:
    candidates = [Path(explicit)] if explicit else [
        Path.cwd() / ".env-sentry-allow",
        Path(root) / ".env-sentry-allow",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return AllowList.load(candidate)
    return AllowList([])


def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        ui.error(f"{root} does not exist.")
        return 1

    allowlist = _load_allowlist(root, getattr(args, "allowlist", ""))

    if getattr(args, "staged", False):
        paths = staged_files(root)
        if not paths:
            ui.ok("Nothing staged to scan.")
            return 0
        findings = detect.scan_files(paths, allowlist=allowlist,
                                     min_severity=args.min_severity)
    else:
        findings = detect.scan_path(
            root,
            allowlist=allowlist,
            min_severity=args.min_severity,
            extensions=[e.strip() for e in args.extensions.split(",") if e.strip()] or None,
            exclude=[e.strip() for e in args.exclude.split(",") if e.strip()],
        )
    findings.sort(key=lambda finding: finding.sort_key())

    output = getattr(args, "output", "") or ""
    fmt = getattr(args, "format", "text")

    if fmt == "text":
        if findings:
            report.render_text(findings, ui, show_severity=True)
            ui.error(report.summary_line(findings) + " Review before committing/pushing.")
        else:
            ui.ok("No obvious hardcoded secrets found.")
        if output:
            Path(output).write_text(report.to_json(findings, VERSION, str(root)) + "\n")
    else:
        if fmt == "json":
            payload = report.to_json(findings, VERSION, str(root))
        elif fmt == "sarif":
            payload = report.to_sarif(findings, VERSION)
        else:
            payload = report.to_github(findings)
        if output:
            Path(output).write_text(payload + "\n")
            ui.ok(f"Wrote {len(findings)} finding(s) to {output}")
        elif payload:
            ui.write(payload, force=True)

    fail_on = getattr(args, "fail_on", "any")
    return 1 if report.should_fail(findings, fail_on) else 0


# ----------------------------------------------------------------------
# lint
# ----------------------------------------------------------------------

LEVEL_COLORS = {lint.ERROR: "red", lint.WARNING: "yellow", lint.INFO: "grey"}


def _lint_targets(args: argparse.Namespace) -> list[Path]:
    if args.all:
        return sorted(Path.cwd().glob(".env*")) or [Path(args.file)]
    return [Path(args.file)]


def cmd_lint(args: argparse.Namespace) -> int:
    all_issues = {}
    for target in _lint_targets(args):
        all_issues[str(target)] = lint.lint_file(target)

    total = [issue for issues in all_issues.values() for issue in issues]

    if args.format == "json":
        payload = {
            "files": {
                str(path): [issue.to_dict() for issue in issues]
                for path, issues in all_issues.items()
            },
            "summary": lint.summarize(total),
        }
        output = json.dumps(payload, indent=2)
        if args.output:
            Path(args.output).write_text(output + "\n")
            ui.ok(f"Wrote lint results to {args.output}")
        else:
            ui.write(output, force=True)
    else:
        for path, issues in all_issues.items():
            if len(all_issues) > 1:
                ui.header(f"{path}")
            for issue in issues:
                label = ui.paint(f"{issue.level.upper():7}", LEVEL_COLORS.get(issue.level, ""))
                ui.write(f"  {label} line {issue.line:<4} {issue.message}  {ui.paint('[' + issue.code + ']', 'grey')}")
        if not total:
            ui.ok("No lint problems found.")
        else:
            colour = "red" if lint.has_errors(total) else "yellow"
            ui.write(ui.paint(f"{lint.summarize(total)} in {len(all_issues)} file(s)", colour))

    if lint.has_errors(total):
        return 1
    if args.strict and lint.has_warnings(total):
        return 1
    return 0


# ----------------------------------------------------------------------
# diff
# ----------------------------------------------------------------------

DIFF_COLORS = {diffing.ADDED: "green", diffing.REMOVED: "red",
               diffing.CHANGED: "yellow", diffing.SAME: "grey"}


def cmd_diff(args: argparse.Namespace) -> int:
    left_path, right_path = Path(args.left), Path(args.right)
    for path in (left_path, right_path):
        if not path.exists():
            ui.error(f"{path} not found.")
            return 2

    left = EnvFile.load(left_path)
    right = EnvFile.load(right_path)
    changes = diffing.compare(left, right, include_same=args.show_same)
    if not args.show_same:
        changes = diffing.only_differences(changes)

    if args.format == "json":
        payload = {
            "left": str(left_path),
            "right": str(right_path),
            "counts": diffing.counts(changes),
            "changes": [change.to_dict(show_values=args.show_values) for change in changes],
        }
        payload_text = json.dumps(payload, indent=2)
        if args.output:
            Path(args.output).write_text(payload_text + "\n")
            ui.ok(f"Wrote diff to {args.output}")
        else:
            ui.write(payload_text, force=True)
    else:
        ui.header(f"--- {left_path}")
        ui.header(f"+++ {right_path}")
        if args.keys_only:
            for change in changes:
                line = f"{diffing.SYMBOLS[change.kind]} {change.key}"
                ui.write(ui.paint(line, DIFF_COLORS.get(change.kind, "")))
        else:
            width = max([len(change.key) for change in changes] + [12]) + 2
            for change in changes:
                line = change.render(show_values=args.show_values, width=width)
                ui.write(ui.paint(line, DIFF_COLORS.get(change.kind, "")))
        if not changes:
            ui.ok("No differences.")
        else:
            ui.write(ui.paint(f"\n{diffing.summary(changes)}", "cyan"))
            if not args.show_values:
                ui.detail("values are masked; pass --show-values to reveal them")

    if args.fail_on_diff and any(change.kind != diffing.SAME for change in changes):
        return 1
    return 0


# ----------------------------------------------------------------------
# export
# ----------------------------------------------------------------------

def cmd_export(args: argparse.Namespace) -> int:
    env_path = Path(args.env)
    if not env_path.exists():
        ui.error(f"{env_path} not found.")
        return 2

    env = EnvFile.load(env_path)
    try:
        rendered = exporters.export_env(
            env,
            fmt=args.format,
            redact=args.redact,
            include=[p.strip() for p in args.include.split(",") if p.strip()],
            exclude=[p.strip() for p in args.exclude.split(",") if p.strip()],
            prefix=args.prefix,
            name=args.name,
            namespace=args.namespace,
            service=args.service,
            section=args.section,
        )
    except ValueError as exc:
        ui.error(str(exc))
        return 2

    if args.output:
        Path(args.output).write_text(rendered)
        note = " (values masked)" if args.redact else ""
        ui.ok(f"Wrote {len(env)} key(s) as {args.format}{note} to {args.output}")
    else:
        ui.write(rendered, force=True)
    return 0


# ----------------------------------------------------------------------
# generate secrets
# ----------------------------------------------------------------------

def _gen_targets(env: EnvFile, keys: list[str], force: bool, all_keys: bool = False
                 ) -> tuple[list[str], list[str]]:
    """Return (keys to generate, keys skipped because they are not secrets)."""
    if keys:
        return keys, []
    if force:
        return [entry.key for entry in env.entries], []
    candidates = [
        entry.key for entry in env.entries
        if entry.value == "" or is_placeholder(entry.value)
    ]
    if all_keys:
        return candidates, []
    targets = [key for key in candidates if gensecrets.is_secret_key(key)]
    skipped = [key for key in candidates if key not in targets]
    return targets, skipped


def cmd_generate(args: argparse.Namespace) -> int:
    env_path = Path(args.env)

    if args.passphrase and args.length < 4:
        ui.error("--length must be at least 4")
        return 2

    seeded = False
    if not env_path.exists():
        example_path = Path(args.example)
        if example_path.exists() and not args.keys:
            env = EnvFile.load(example_path)
            seeded = True
            ui.info(f"{env_path} not found; seeding it from {example_path}.")
        elif not args.keys:
            ui.error(f"{env_path} not found. Create it with `env-sentry init`, "
                     "or pass --key NAME to print a standalone value.")
            return 2
        else:
            env = EnvFile([], path=env_path, exists=False)
    else:
        env = EnvFile.load(env_path)

    targets, skipped = _gen_targets(env, args.keys, args.force, all_keys=args.all_keys)
    if skipped:
        ui.detail("Not secret-shaped, left as-is: " + ", ".join(skipped[:6])
                  + ("…" if len(skipped) > 6 else ""))
    if not targets:
        ui.ok("Nothing to generate: no empty or placeholder secrets found "
              "(use --force to overwrite existing values, or --all-keys).")
        return 0

    generated = {}
    for key in targets:
        if args.passphrase:
            value = gensecrets.passphrase(words=args.words)
        else:
            value = gensecrets.generate_for_key(
                key, length=args.length, charset=args.charset, prefix=args.prefix
            )
        generated[key] = value

    if args.dry_run:
        for key, value in generated.items():
            ui.write(f"{key}={value}")
        ui.info(f"Dry run: would write {len(generated)} value(s) to {env_path}.")
        return 0

    if env.exists or seeded:
        for entry in env.entries:
            if entry.key in generated:
                entry.value = generated[entry.key]
                entry.quote = '"' if any(ch in entry.value for ch in " #\\") else ""
        env_path.write_text(env.render())
    else:
        lines = [f"{key}={value}" for key, value in generated.items()]
        env_path.write_text("\n".join(lines) + "\n")

    try:  # keep secrets out of other users' reach
        env_path.chmod(0o600)
    except OSError:  # pragma: no cover - exotic filesystems
        pass

    for key, value in generated.items():
        score = gensecrets.strength(value)
        label = ui.paint(f"{score:3d}/100", "green" if score >= 70 else "yellow")
        ui.ok(f"{key} = {value if args.print else '<generated>'}  {label}")

    ui.info(f"Generated {len(generated)} secret(s) in {env_path} "
            "(file permissions set to 600).")
    return 0


# ----------------------------------------------------------------------
# audit
# ----------------------------------------------------------------------

STATUS_STYLE = {
    audit_mod.PASS: ("✅", "green"),
    audit_mod.WARN: ("⚠️ ", "yellow"),
    audit_mod.FAIL: ("❌", "red"),
}


def _print_audit(result: audit_mod.AuditResult, title: str = "") -> None:
    if title:
        ui.header(title)
    for check in result.checks:
        symbol, colour = STATUS_STYLE[check.status]
        line = f"{symbol} {check.title.ljust(34)} {check.message}"
        ui.write(ui.paint(line, colour))
        if check.status != audit_mod.PASS and check.fix:
            ui.detail(f"↳ {check.fix}")
    colour = "green" if result.score >= 90 else "yellow" if result.score >= 70 else "red"
    ui.write("")
    ui.write(ui.paint(
        f"Health score: {result.score}/100  grade {result.grade}  "
        f"[{audit_mod.bar(result.score)}]",
        colour, bold=True,
    ))


def cmd_audit(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.exists():
        ui.error(f"{root} does not exist.")
        return 2

    allowlist = _load_allowlist(root, getattr(args, "allowlist", ""))
    env_path = Path(args.env) if args.env else None
    example_path = Path(args.example) if args.example else None

    if args.all:
        results = audit_mod.audit_envs(root, allowlist=allowlist)
    else:
        results = {"": audit_mod.audit(root, env_path, example_path, allowlist=allowlist)}

    if args.format == "json":
        payload = {
            name or "audit": result.to_dict() for name, result in results.items()
        }
        output = json.dumps(payload, indent=2)
        if args.output:
            Path(args.output).write_text(output + "\n")
            ui.ok(f"Wrote audit to {args.output}")
        else:
            ui.write(output, force=True)
    else:
        for name, result in results.items():
            _print_audit(result, title=name)
            if name != list(results)[-1]:
                ui.write("")

    worst = min(result.score for result in results.values())
    if args.min_score and worst < args.min_score:
        ui.error(f"Score {worst} is below the required {args.min_score}.")
        return 1
    return 0


# ----------------------------------------------------------------------
# usage
# ----------------------------------------------------------------------

def cmd_usage(args: argparse.Namespace) -> int:
    root = Path(args.path)
    env_path = Path(args.env)
    if not root.exists():
        ui.error(f"{root} does not exist.")
        return 2
    if not env_path.exists():
        ui.error(f"{env_path} not found.")
        return 2

    ignore = set(args.ignore_keys.split(",")) if args.ignore_keys else set()
    report_obj = usage_mod.analyse(
        root,
        env_path,
        ignore=ignore,
        exclude=[e.strip() for e in args.exclude.split(",") if e.strip()],
    )

    used = report_obj.used_keys()
    unused = report_obj.unused_keys()
    undefined = report_obj.undefined_keys()

    if args.format == "json":
        payload = json.dumps(usage_mod.to_dict(report_obj), indent=2)
        if args.output:
            Path(args.output).write_text(payload + "\n")
            ui.ok(f"Wrote usage report to {args.output}")
        else:
            ui.write(payload, force=True)
    else:
        ui.header(f"{len(report_obj.env_keys)} key(s) in {env_path}")
        if args.list_used:
            for key in sorted(used):
                ui.write(f"  {ui.paint(key, 'green')}  {report_obj.reference_count(key)} reference(s)")
        if unused:
            ui.warn(f"{len(unused)} key(s) defined but never referenced in code:")
            for key in unused:
                ui.bullet(key, "yellow")
            ui.detail("Consider removing them, or add them to --ignore-keys / .env-sentry-allow")
        else:
            ui.ok("Every key is referenced somewhere in the codebase.")
        if undefined:
            ui.error(f"{len(undefined)} key(s) referenced in code but missing from {env_path}:")
            for key in undefined:
                ui.bullet(key, "red")
        else:
            ui.ok("No undefined environment references found.")

    if args.fail_on == "unused" and unused:
        return 1
    if args.fail_on == "undefined" and undefined:
        return 1
    if args.fail_on == "any" and (unused or undefined):
        return 1
    return 0


# ----------------------------------------------------------------------
# badge
# ----------------------------------------------------------------------

def cmd_badge(args: argparse.Namespace) -> int:
    score = args.score
    if score is None:
        root = Path(args.path)
        result = audit_mod.audit(root, allowlist=_load_allowlist(root))
        score = result.score

    svg = badge_mod.write(args.output, score, label=args.label, style=args.style)
    ui.ok(f"Wrote badge for score {score}/100 to {args.output}")
    ui.detail(f"README snippet: {badge_mod.markdown(args.output)}")
    if args.print:
        ui.write(svg, force=True)
    return 0


# ----------------------------------------------------------------------
# git hooks
# ----------------------------------------------------------------------

def cmd_hooks(args: argparse.Namespace) -> int:
    root = hooks_mod.repo_root(Path(args.path))
    if root is None:
        ui.error("Not inside a git repository.")
        return 2

    if args.action == "status":
        state = hooks_mod.status(root)
        for hook_type, installed in state.items():
            if installed:
                ui.ok(f"{hook_type}: env-sentry hook installed")
            else:
                ui.info(f"{hook_type}: not installed")
        return 0

    if args.action == "uninstall":
        removed = hooks_mod.uninstall(root, args.type)
        if removed:
            ui.ok(f"Removed env-sentry block from {args.type}.")
        else:
            ui.info(f"No env-sentry block found in {args.type}.")
        return 0

    commands = [c.strip() for c in args.commands.split(",") if c.strip()] if args.commands else None
    try:
        path = hooks_mod.install(root, args.type, commands=commands, version=VERSION,
                                 force=args.force)
    except FileExistsError as exc:
        ui.error(str(exc))
        return 1
    except RuntimeError as exc:
        ui.error(str(exc))
        return 2

    ui.ok(f"Installed {args.type} hook at {path}")
    ui.detail("Runs: " + (", ".join(commands) if commands else ", ".join(
        hooks_mod.DEFAULT_COMMANDS.get(args.type, ("scan",)))))
    ui.detail("Bypass once with: git commit --no-verify")
    return 0


# ----------------------------------------------------------------------
# merge / prune
# ----------------------------------------------------------------------

def cmd_merge(args: argparse.Namespace) -> int:
    source, target = Path(args.source), Path(args.target)
    if not target.exists() and not args.create:
        ui.error(f"{target} not found (pass --create to start from {source}).")
        return 2

    try:
        plan = merge_mod.merge_files(
            target,
            source,
            overwrite=args.overwrite,
            with_values=args.with_values,
            only=[p.strip() for p in args.only.split(",") if p.strip()],
            skip=[p.strip() for p in args.skip.split(",") if p.strip()],
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        ui.error(str(exc))
        return 2

    for key in plan.added:
        ui.write(ui.paint(f"+ {key}", "green"))
    for key in plan.overwritten:
        ui.write(ui.paint(f"~ {key}", "yellow"))

    if not plan.changed:
        ui.ok(f"Nothing to merge; {target} already has every key from {source}.")
        return 0

    if args.dry_run:
        ui.info(f"Dry run: would update {target} ({plan.summary()}).")
        return 0

    ui.ok(f"Updated {target} ({plan.summary()}).")
    if not args.with_values:
        ui.detail("values were replaced with placeholders; pass --with-values to copy them")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    env_path = Path(args.env)
    if not env_path.exists():
        ui.error(f"{env_path} not found.")
        return 2

    if args.from_example:
        keep = EnvFile.load(Path(args.example)).keys()
        source = args.example
    else:
        from . import usage as usage_mod

        report_obj = usage_mod.analyse(Path(args.path), env_path)
        keep = report_obj.used_keys()
        source = "code references"

    plan, backup = merge_mod.prune(
        env_path,
        keep_keys=keep,
        keep_patterns=[p.strip() for p in args.keep.split(",") if p.strip()],
        dry_run=not args.write,
        backup=not args.no_backup,
    )

    if not plan.removed:
        ui.ok(f"Nothing to prune: every key in {env_path} is still used.")
        return 0

    ui.warn(f"{len(plan.removed)} key(s) not found in {source}:")
    for key in plan.removed:
        ui.bullet(key, "red")

    if not args.write:
        ui.info("Dry run only. Re-run with --write to remove them.")
        return 0

    ui.ok(f"Removed {len(plan.removed)} key(s) from {env_path}.")
    if backup:
        ui.detail(f"Backup written to {backup}")
    return 0


# ----------------------------------------------------------------------
# stats
# ----------------------------------------------------------------------

def cmd_stats(args: argparse.Namespace) -> int:
    env_path = Path(args.env)
    if not env_path.exists():
        ui.error(f"{env_path} not found.")
        return 2

    text = env_path.read_text(errors="ignore")
    env = EnvFile.parse(text)
    result = stats_mod.analyse(env, str(env_path), text)

    if args.format == "json":
        payload = json.dumps(result.to_dict(), indent=2)
        if args.output:
            Path(args.output).write_text(payload + "\n")
            ui.ok(f"Wrote stats to {args.output}")
        else:
            ui.write(payload, force=True)
        return 0

    ui.header(f"{env_path} — {result.keys} key(s), {result.bytes} bytes")
    rows = [
        ("comments", result.comments),
        ("blank lines", result.blank_lines),
        ("empty values", result.empty_values),
        ("placeholders", result.placeholders),
        ("duplicate keys", result.duplicates),
        ("avg value length", f"{result.avg_length:.1f} chars"),
        ("median length", f"{result.median_length:.1f} chars"),
        ("longest value", f"{result.max_length} chars"),
        ("avg entropy", f"{result.entropy_avg:.2f} bits/char"),
    ]
    for label, value in rows:
        ui.write(f"  {label.ljust(20)} {value}")

    if result.categories:
        ui.write("")
        ui.header("Keys by category")
        for name, count in sorted(result.categories.items(), key=lambda item: -item[1]):
            bar = "▇" * min(count, 40)
            ui.write(f"  {name.ljust(16)} {bar} {count}")

    if result.repeated_values:
        ui.write("")
        ui.warn("The same value is reused under multiple keys:")
        for keys in result.repeated_values:
            ui.bullet(" = ".join(keys), "yellow")

    if result.weak_keys:
        ui.write("")
        ui.warn("Short values for security-sensitive keys:")
        for key in result.weak_keys:
            ui.bullet(key, "red")

    return 0


# ----------------------------------------------------------------------
# config
# ----------------------------------------------------------------------

def cmd_config(args: argparse.Namespace) -> int:
    if args.init:
        target = Path(args.output or config_mod.FILENAMES[0])
        if target.exists() and not args.force:
            ui.error(f"{target} already exists (use --force to overwrite).")
            return 1
        config_mod.Config({}).write(target)
        ui.ok(f"Wrote starter config to {target}")
        return 0

    cfg = config_mod.Config.load(Path.cwd())
    if args.format == "json":
        ui.write(json.dumps(cfg.to_dict(), indent=2), force=True)
        return 0

    if cfg.path:
        ui.header(f"Config: {cfg.path}")
        for key in sorted(cfg.data):
            value = cfg.data[key]
            rendered = ", ".join(value) if isinstance(value, list) else value
            ui.write(f"  {key.ljust(14)} {rendered}")
    else:
        ui.info("No .env-sentry.json found; built-in defaults are in effect.")
        ui.detail("Create one with: env-sentry config --init")
        ui.header("Built-in / configurable keys")
        for key in sorted(config_mod.KNOWN_KEYS):
            ui.write(f"  {key.ljust(14)} {config_mod.KNOWN_KEYS[key].__name__}")

    warnings = cfg.warnings()
    for message in warnings:
        ui.warn(message)

    if cfg.path and cfg.data:
        ui.write("")
        ui.detail(f"CLI flags always win over values in {cfg.path.name}.")
    return 0


# ----------------------------------------------------------------------
# ci scaffolding
# ----------------------------------------------------------------------

def cmd_ci(args: argparse.Namespace) -> int:
    if args.write:
        try:
            target = cicd.write(args.provider, args.output, force=args.force)
        except FileExistsError as exc:
            ui.error(str(exc))
            return 1
        ui.ok(f"Wrote {args.provider} configuration to {target}")
        ui.detail("Commit it, then push — secrets are now checked on every run.")
        return 0

    ui.write(cicd.render(args.provider), force=True)
    ui.detail(f"Suggested location: {cicd.DEFAULT_PATHS[args.provider]}")
    return 0


# ----------------------------------------------------------------------
# shell completions
# ----------------------------------------------------------------------

def cmd_completions(args: argparse.Namespace) -> int:
    try:
        script = completions_mod.render(args.shell, build_parser(), "env-sentry")
    except ValueError as exc:
        ui.error(str(exc))
        return 2

    if args.output:
        Path(args.output).write_text(script)
        ui.ok(f"Wrote {args.shell} completion to {args.output}")
        ui.detail(completions_mod.INSTALL_HINTS[args.shell])
    else:
        ui.write(script, force=True)
    return 0


# ----------------------------------------------------------------------
# git history scan
# ----------------------------------------------------------------------

def cmd_history(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not history_mod.is_repo(root):
        ui.error("Not inside a git repository.")
        return 2

    allowlist = _load_allowlist(root, getattr(args, "allowlist", ""))
    findings = history_mod.scan_history(
        root,
        depth=args.depth,
        allowlist=allowlist,
        min_severity=args.min_severity,
        include_all_files=args.all_files,
    )

    files = history_mod.env_files_in_history(root, depth=max(args.depth, 50))

    if args.format == "json":
        payload = json.dumps({
            "depth": args.depth,
            "env_files_in_history": files,
            "findings": [finding.to_dict() for finding in findings],
        }, indent=2)
        if args.output:
            Path(args.output).write_text(payload + "\n")
            ui.ok(f"Wrote history scan to {args.output}")
        else:
            ui.write(payload, force=True)
    else:
        if args.list_files:
            if files:
                ui.warn("Env-like files that were committed at some point:")
                for name in files:
                    ui.bullet(name, "yellow")
            else:
                ui.ok("No env/credential files found in the scanned history.")
        for finding in findings:
            colour = "red" if finding.severity == detect.CRITICAL else "yellow"
            ui.write(
                f"{ui.paint(finding.commit, 'cyan')}  {finding.date}  "
                f"{finding.path}:{finding.line}  {ui.paint(finding.rule, colour)}  "
                f"{ui.paint('(' + finding.author + ')', 'grey')}"
            )
        if findings:
            ui.error(f"{len(findings)} secret(s) found in git history.")
            ui.detail("Rotate the credentials — they are recoverable with `git show`.")
        else:
            ui.ok(f"No secrets found in the last {args.depth} commits.")

    if findings:
        return 1
    return 0


# ----------------------------------------------------------------------
# watch
# ----------------------------------------------------------------------

def _watch_pass(args: argparse.Namespace) -> int:
    stamp = datetime.datetime.now().strftime("%H:%M:%S")
    ui.header(f"[{stamp}] checking {args.env}")
    code = cmd_check(argparse.Namespace(env=args.env, example=args.example,
                                        strict=args.strict, format="text"))
    if args.scan:
        scan_args = argparse.Namespace(
            path=".", format="text", output="", min_severity=detect.HIGH,
            fail_on="high", allowlist="", exclude="", extensions="",
        )
        code |= cmd_scan(scan_args)
    return code


def cmd_watch(args: argparse.Namespace) -> int:
    if not Path(args.env).exists() and not Path(args.example).exists():
        ui.error(f"Neither {args.env} nor {args.example} exists here.")
        return 2

    paths = watch_mod.files_to_watch(Path.cwd())
    ui.info(f"Watching {len(paths)} file(s): " + ", ".join(path.name for path in paths))
    ui.detail("Press Ctrl+C to stop.")

    _watch_pass(args)
    if args.once:
        return 0

    try:
        while True:
            changed = watch_mod.wait_for_change(
                lambda: watch_mod.files_to_watch(Path.cwd()), interval=args.interval
            )
            if changed:
                names = ", ".join(path.name for path in changed)
                ui.write("")
                ui.info(f"changed: {names}")
                _watch_pass(args)
    except KeyboardInterrupt:
        ui.write("")
        ui.info("Stopped watching.")
        return 0


# ----------------------------------------------------------------------
# doctor
# ----------------------------------------------------------------------

DOCTOR_STYLE = {doctor_mod.OK: ("✅", "green"), doctor_mod.WARN: ("⚠️ ", "yellow"),
                doctor_mod.INFO: ("• ", "grey")}


def cmd_doctor(args: argparse.Namespace) -> int:
    root = Path(args.path)
    facts = doctor_mod.diagnose(root, VERSION)

    if args.format == "json":
        payload = json.dumps({"facts": [fact.to_dict() for fact in facts],
                              "suggestions": doctor_mod.suggestions(facts)}, indent=2)
        if args.output:
            Path(args.output).write_text(payload + "\n")
            ui.ok(f"Wrote diagnostics to {args.output}")
        else:
            ui.write(payload, force=True)
        return 0

    ui.header(f"env-sentry doctor — {root}")
    for fact in facts:
        symbol, colour = DOCTOR_STYLE.get(fact.status, ("• ", "grey"))
        ui.write(f"{symbol} {ui.paint(fact.label.ljust(18), 'cyan')} {fact.value}")
        if fact.hint and fact.status == doctor_mod.WARN:
            ui.detail(f"↳ {fact.hint}")

    advice = doctor_mod.suggestions(facts)
    if advice:
        ui.write("")
        ui.warn(f"{len(advice)} suggestion(s):")
        for item in advice:
            ui.bullet(item, "yellow")
    else:
        ui.write("")
        ui.ok("Everything looks healthy.")
    return 0


# ----------------------------------------------------------------------
# entrypoint
# ----------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="env-sentry",
        description="Keep your .env setup safe and in sync. Zero dependencies.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"env-sentry {VERSION} — built by {AUTHOR}",
    )
    parser.add_argument(
        "--color", choices=["auto", "always", "never"], default="auto",
        help="Colourise output (default: auto — only when stdout is a TTY)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Only print warnings and errors",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser(
        "init",
        help="Scaffold .env.example and git-ignore .env",
        description="Create .env.example if it doesn't exist yet, and make sure "
        "'.env' is listed in .gitignore so real secrets never get committed.",
    )
    p_init.add_argument(
        "--example", default=".env.example",
        help="Path to the example file to create (default: .env.example)",
    )
    p_init.add_argument(
        "--env", default=".env",
        help="Path to the env file to git-ignore (default: .env)",
    )
    p_init.add_argument(
        "--template", default="",
        help="Start from a stack template (see --list-templates)",
    )
    p_init.add_argument(
        "--list-templates", action="store_true",
        help="List the available stack templates and exit",
    )
    p_init.add_argument(
        "--create-env", action="store_true",
        help="Also create an empty, mode-600 .env file",
    )
    p_init.add_argument(
        "--no-gitignore", action="store_true",
        help="Do not touch .gitignore",
    )
    p_init.add_argument(
        "--force", action="store_true",
        help="Overwrite an existing example file",
    )
    p_init.set_defaults(func=cmd_init)

    p_check = subparsers.add_parser(
        "check",
        help="Compare .env against .env.example",
        description="Diff .env against .env.example, flag any real secret values "
        "left in the example file, and confirm .env is git-ignored. "
        "Exits non-zero if anything looks wrong (safe to use in CI).",
    )
    p_check.add_argument(
        "--env", default=".env",
        help="Path to your real env file (default: .env)",
    )
    p_check.add_argument(
        "--example", default=".env.example",
        help="Path to the example/template file to compare against (default: .env.example)",
    )
    p_check.add_argument(
        "--strict", "--ci", dest="strict", action="store_true",
        help="Also fail on warnings (missing local keys, duplicates) — use in CI",
    )
    p_check.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )
    p_check.set_defaults(func=cmd_check)

    p_sync = subparsers.add_parser(
        "sync",
        help="Regenerate .env.example from .env (values redacted)",
        description="Rewrite .env.example using the keys from .env, but with every "
        "value replaced by a placeholder — your real secrets are never copied.",
    )
    p_sync.add_argument(
        "--env", default=".env",
        help="Path to your real env file to read keys from (default: .env)",
    )
    p_sync.add_argument(
        "--example", default=".env.example",
        help="Path to the example file to write (default: .env.example)",
    )
    p_sync.add_argument(
        "--merge", action="store_true",
        help="Keep keys that already exist in the example file but not in .env",
    )
    p_sync.add_argument(
        "--check", action="store_true",
        help="Exit non-zero if the example file is out of date (do not write)",
    )
    p_sync.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be written instead of writing it",
    )
    p_sync.add_argument(
        "--no-header", action="store_true",
        help="Skip the auto-generated header comment",
    )
    p_sync.add_argument(
        "--force", action="store_true",
        help="Overwrite the template even when .env has no keys",
    )
    p_sync.set_defaults(func=cmd_sync)

    p_scan = subparsers.add_parser(
        "scan",
        help="Scan the repo for hardcoded secrets",
        description="Recursively scan source files for AWS/GitHub/Slack/Stripe keys, "
        "private key blocks, JWTs, and suspicious KEY=value pairs. "
        "Exits non-zero if anything is found (safe to use as a pre-commit hook).",
    )
    p_scan.add_argument(
        "path", nargs="?", default=".",
        help="Directory to scan (default: current directory)",
    )
    p_scan.add_argument(
        "--format", choices=list(report.FORMATS), default="text",
        help="Output format: text (default), json, sarif or github",
    )
    p_scan.add_argument(
        "--output", "-o", default="",
        help="Write results to a file instead of stdout (json/sarif/github)",
    )
    p_scan.add_argument(
        "--min-severity", default=detect.LOW,
        choices=[detect.LOW, detect.MEDIUM, detect.HIGH, detect.CRITICAL],
        help="Only report findings at or above this severity (default: low)",
    )
    p_scan.add_argument(
        "--fail-on", default="any",
        choices=["any", detect.CRITICAL, detect.HIGH, detect.MEDIUM, detect.LOW, "never"],
        help="Exit non-zero only for findings at or above this severity (default: any)",
    )
    p_scan.add_argument(
        "--allowlist", default="",
        help="Path to an allowlist file (default: ./.env-sentry-allow if present)",
    )
    p_scan.add_argument(
        "--exclude", default="",
        help="Comma-separated glob patterns to skip, e.g. 'tests/*,docs/*'",
    )
    p_scan.add_argument(
        "--staged", action="store_true",
        help="Only scan files staged for commit (fast pre-commit mode)",
    )
    p_scan.add_argument(
        "--extensions", default="",
        help="Comma-separated file extensions to scan, e.g. '.py,.ts' (default: all supported)",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_lint = subparsers.add_parser(
        "lint",
        help="Validate .env syntax and style",
        description="Catch malformed .env files: stray text, duplicate keys, "
        "unquoted spaces, unterminated quotes, CRLF endings, BOMs and more.",
    )
    p_lint.add_argument(
        "file", nargs="?", default=".env",
        help="Env file to lint (default: .env)",
    )
    p_lint.add_argument(
        "--all", action="store_true",
        help="Lint every .env* file in the current directory",
    )
    p_lint.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as failures too",
    )
    p_lint.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )
    p_lint.add_argument("--output", "-o", default="", help="Write results to a file")
    p_lint.set_defaults(func=cmd_lint)

    p_diff = subparsers.add_parser(
        "diff",
        help="Compare two env files (values masked by default)",
        description="Show keys that were added, removed or changed between two "
        "env files. Values are masked so the output is safe to paste in a PR.",
    )
    p_diff.add_argument("left", help="The 'before' file, e.g. .env")
    p_diff.add_argument("right", help="The 'after' file, e.g. .env.production")
    p_diff.add_argument("--keys-only", action="store_true",
                        help="Only show which keys differ, no values at all")
    p_diff.add_argument("--show-values", action="store_true",
                        help="Reveal real values (be careful where this output goes)")
    p_diff.add_argument("--show-same", action="store_true",
                        help="Also list unchanged keys")
    p_diff.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    p_diff.add_argument("--output", "-o", default="", help="Write results to a file")
    p_diff.add_argument("--fail-on-diff", action="store_true",
                        help="Exit non-zero when the files differ (useful in CI)")
    p_diff.set_defaults(func=cmd_diff)

    p_export = subparsers.add_parser(
        "export",
        help="Convert .env into json/yaml/shell/compose/k8s/...",
        description="Render your env file in whatever format the next tool needs.",
    )
    p_export.add_argument("--env", default=".env", help="Env file to read (default: .env)")
    p_export.add_argument("--format", default="dotenv", choices=list(exporters.FORMATS),
                          help="Output format (default: dotenv)")
    p_export.add_argument("--output", "-o", default="", help="Write to a file instead of stdout")
    p_export.add_argument("--redact", action="store_true",
                          help="Mask every value in the output")
    p_export.add_argument("--include", default="", help="Comma-separated key globs to include")
    p_export.add_argument("--exclude", default="", help="Comma-separated key globs to exclude")
    p_export.add_argument("--prefix", default="", help="Prefix added to every key")
    p_export.add_argument("--name", default="app-secrets", help="Secret name (k8s format)")
    p_export.add_argument("--namespace", default="default", help="Namespace (k8s format)")
    p_export.add_argument("--service", default="app", help="Service name (compose format)")
    p_export.add_argument("--section", default="settings", help="INI section name")
    p_export.set_defaults(func=cmd_export)

    p_gen = subparsers.add_parser(
        "gen",
        help="Generate strong random values for empty/placeholder secrets",
        description="Fill in secure random values for keys that are missing or "
        "still say 'your_api_key_here'. Uses secrets module CSPRNG.",
    )
    p_gen.add_argument("--env", default=".env", help="Env file to update (default: .env)")
    p_gen.add_argument("--example", default=".env.example",
                       help="Seed .env from this file when it does not exist yet")
    p_gen.add_argument("--all-keys", action="store_true",
                       help="Generate for every empty key, not just secret-shaped ones")
    p_gen.add_argument("--key", dest="keys", action="append", default=[],
                       help="Only (re)generate this key; repeatable")
    p_gen.add_argument("--length", type=int, default=32, help="Value length (default: 32)")
    p_gen.add_argument("--charset", default="alnum", choices=sorted(gensecrets.CHARSETS),
                       help="Character set to use (default: alnum)")
    p_gen.add_argument("--prefix", default="", help="Prefix for generated values")
    p_gen.add_argument("--passphrase", action="store_true",
                       help="Generate memorable word-based values instead of random strings")
    p_gen.add_argument("--words", type=int, default=4,
                       help="Word count for --passphrase (default: 4)")
    p_gen.add_argument("--force", action="store_true",
                       help="Overwrite existing placeholder values and unknown keys")
    p_gen.add_argument("--dry-run", action="store_true",
                       help="Print what would be generated without writing")
    p_gen.add_argument("--print", dest="print", action="store_true",
                       help="Print generated values in the summary (careful in CI logs)")
    p_gen.set_defaults(func=cmd_generate)

    p_audit = subparsers.add_parser(
        "audit",
        help="Score your .env hygiene from 0-100",
        description="Run eleven weighted checks (gitignore, tracking, git history, "
        "permissions, key parity, placeholders, syntax, secret leakage) and "
        "report a health score with a letter grade.",
    )
    p_audit.add_argument("path", nargs="?", default=".",
                         help="Repository root to audit (default: .)")
    p_audit.add_argument("--env", default="", help="Env file to audit (default: .env)")
    p_audit.add_argument("--example", default="", help="Example file (default: .env.example)")
    p_audit.add_argument("--all", action="store_true",
                         help="Audit every .env* file with a matching .example")
    p_audit.add_argument("--allowlist", default="", help="Allowlist file for secret scanning")
    p_audit.add_argument("--min-score", type=int, default=0,
                         help="Exit non-zero if the score is below this value")
    p_audit.add_argument("--format", choices=["text", "json"], default="text",
                         help="Output format (default: text)")
    p_audit.add_argument("--output", "-o", default="", help="Write results to a file")
    p_audit.set_defaults(func=cmd_audit)

    p_usage = subparsers.add_parser(
        "usage",
        help="Find unused keys and undefined env references",
        description="Cross-reference .env against the code: which keys are never "
        "read, and which environment variables the code expects but you never "
        "defined.",
    )
    p_usage.add_argument("path", nargs="?", default=".", help="Code root to scan (default: .)")
    p_usage.add_argument("--env", default=".env", help="Env file (default: .env)")
    p_usage.add_argument("--exclude", default="", help="Comma-separated globs to skip")
    p_usage.add_argument("--ignore-keys", default="",
                         help="Comma-separated keys to always treat as known")
    p_usage.add_argument("--list-used", action="store_true",
                         help="Also list the keys that are referenced, with counts")
    p_usage.add_argument("--fail-on", choices=["none", "unused", "undefined", "any"],
                         default="none",
                         help="Exit non-zero on unused/undefined keys (default: none)")
    p_usage.add_argument("--format", choices=["text", "json"], default="text",
                         help="Output format (default: text)")
    p_usage.add_argument("--output", "-o", default="", help="Write results to a file")
    p_usage.set_defaults(func=cmd_usage)

    p_badge = subparsers.add_parser(
        "badge",
        help="Generate an SVG health badge for your README",
        description="Run the audit and render the score as a shields-style SVG "
        "badge, commit it, and show off (or shame) your .env hygiene.",
    )
    p_badge.add_argument("path", nargs="?", default=".", help="Repository root (default: .)")
    p_badge.add_argument("--output", "-o", default=".env-sentry-badge.svg",
                         help="Badge file to write (default: .env-sentry-badge.svg)")
    p_badge.add_argument("--label", default="env-sentry", help="Left-hand label text")
    p_badge.add_argument("--style", choices=["flat", "flat-square"], default="flat",
                         help="Badge shape (default: flat)")
    p_badge.add_argument("--score", type=int, default=None,
                         help="Use this score instead of running the audit")
    p_badge.add_argument("--print", dest="print", action="store_true",
                         help="Also print the SVG to stdout")
    p_badge.set_defaults(func=cmd_badge)

    p_hooks = subparsers.add_parser(
        "hooks",
        help="Install/uninstall a git pre-commit or pre-push hook",
        description="Add a clearly marked env-sentry block to your git hooks so "
        "leaked secrets never make it into a commit or push.",
    )
    p_hooks.add_argument("action", nargs="?", default="status",
                         choices=["install", "uninstall", "status"],
                         help="What to do (default: status)")
    p_hooks.add_argument("--type", default="pre-commit", choices=list(hooks_mod.HOOK_TYPES),
                         help="Hook to manage (default: pre-commit)")
    p_hooks.add_argument("--commands", default="",
                         help="Comma-separated commands to run, e.g. 'check,scan,audit'")
    p_hooks.add_argument("--force", action="store_true",
                         help="Append to an existing hook instead of aborting")
    p_hooks.add_argument("--path", default=".", help="Directory inside the repo (default: .)")
    p_hooks.set_defaults(func=cmd_hooks)

    p_merge = subparsers.add_parser(
        "merge",
        help="Add missing keys from another env file",
        description="Fold another env file (typically .env.example) into one of "
        "yours. Comments and ordering are preserved; values become placeholders "
        "unless --with-values is passed.",
    )
    p_merge.add_argument("source", help="File to read keys from, e.g. .env.example")
    p_merge.add_argument("target", nargs="?", default=".env", help="File to update (default: .env)")
    p_merge.add_argument("--overwrite", action="store_true",
                         help="Also overwrite values of keys that already exist")
    p_merge.add_argument("--with-values", action="store_true",
                         help="Copy real values instead of placeholders")
    p_merge.add_argument("--only", default="", help="Comma-separated key globs to merge")
    p_merge.add_argument("--skip", default="", help="Comma-separated key globs to ignore")
    p_merge.add_argument("--create", action="store_true", help="Create the target if missing")
    p_merge.add_argument("--dry-run", action="store_true", help="Show what would change")
    p_merge.set_defaults(func=cmd_merge)

    p_prune = subparsers.add_parser(
        "prune",
        help="Remove keys that nothing references anymore",
        description="Delete dead keys from .env, either those missing from the "
        "template or those no code reads. Dry run unless --write is passed.",
    )
    p_prune.add_argument("--env", default=".env", help="Env file to prune (default: .env)")
    p_prune.add_argument("--from-example", action="store_true",
                         help="Keep only keys present in the example file")
    p_prune.add_argument("--example", default=".env.example", help="Example file to trust")
    p_prune.add_argument("--path", default=".", help="Code root for usage detection (default: .)")
    p_prune.add_argument("--keep", default="", help="Comma-separated key globs to always keep")
    p_prune.add_argument("--write", action="store_true", help="Actually rewrite the file")
    p_prune.add_argument("--no-backup", action="store_true", help="Do not write .env.bak")
    p_prune.set_defaults(func=cmd_prune)

    p_stats = subparsers.add_parser(
        "stats",
        help="Show env file statistics and category breakdown",
        description="Key counts by category, value length and entropy "
        "distribution, placeholder debt, repeated values and weak secrets.",
    )
    p_stats.add_argument("--env", default=".env", help="Env file to analyse (default: .env)")
    p_stats.add_argument("--format", choices=["text", "json"], default="text",
                         help="Output format (default: text)")
    p_stats.add_argument("--output", "-o", default="", help="Write results to a file")
    p_stats.set_defaults(func=cmd_stats)

    p_config = subparsers.add_parser(
        "config",
        help="Show or create .env-sentry.json defaults",
        description="Inspect the project config that supplies defaults for "
        "--env, --example, --exclude, --min-severity, --fail-on and friends.",
    )
    p_config.add_argument("--init", action="store_true", help="Write a starter config")
    p_config.add_argument("--force", action="store_true", help="Overwrite an existing config")
    p_config.add_argument("--output", "-o", default="", help="Config path for --init")
    p_config.add_argument("--format", choices=["text", "json"], default="text",
                          help="Output format (default: text)")
    p_config.set_defaults(func=cmd_config)

    p_ci = subparsers.add_parser(
        "ci",
        help="Print or write a CI config that runs env-sentry",
        description="Generate a GitHub Actions workflow (with SARIF upload), a "
        "GitLab CI job or a pre-commit config entry.",
    )
    p_ci.add_argument("--provider", choices=list(cicd.PROVIDERS), default="github",
                      help="CI provider (default: github)")
    p_ci.add_argument("--write", action="store_true",
                      help="Write the file instead of printing it")
    p_ci.add_argument("--output", "-o", default="", help="Custom output path")
    p_ci.add_argument("--force", action="store_true", help="Overwrite an existing file")
    p_ci.set_defaults(func=cmd_ci)

    p_comp = subparsers.add_parser(
        "completions",
        help="Print a shell completion script",
        description="Generate bash/zsh/fish completions straight from the CLI "
        "definition, so they never go stale.",
    )
    p_comp.add_argument("shell", nargs="?", default="bash",
                        choices=list(completions_mod.SHELLS),
                        help="Shell to generate for (default: bash)")
    p_comp.add_argument("--output", "-o", default="",
                        help="Write the script to a file instead of stdout")
    p_comp.set_defaults(func=cmd_completions)

    p_history = subparsers.add_parser(
        "history",
        help="Scan git history for secrets that were committed",
        description="Replay the added lines of recent commits through the "
        "detection engine. Deleting a secret from .env does not delete it "
        "from history — this finds what is still recoverable.",
    )
    p_history.add_argument("path", nargs="?", default=".", help="Repository path (default: .)")
    p_history.add_argument("--depth", type=int, default=100,
                           help="How many commits to scan (default: 100)")
    p_history.add_argument("--min-severity", default=detect.HIGH,
                           choices=[detect.LOW, detect.MEDIUM, detect.HIGH, detect.CRITICAL],
                           help="Minimum severity to report (default: high)")
    p_history.add_argument("--all-files", action="store_true",
                           help="Scan every file, not just env/credential-looking ones")
    p_history.add_argument("--list-files", action="store_true",
                           help="List env-like files that were committed at some point")
    p_history.add_argument("--allowlist", default="", help="Allowlist file")
    p_history.add_argument("--format", choices=["text", "json"], default="text",
                           help="Output format (default: text)")
    p_history.add_argument("--output", "-o", default="", help="Write results to a file")
    p_history.set_defaults(func=cmd_history)

    p_watch = subparsers.add_parser(
        "watch",
        help="Re-run checks whenever an env file changes",
        description="Poll .env* files and re-run `check` (plus an optional "
        "high-severity scan) on every change. Ideal while editing secrets.",
    )
    p_watch.add_argument("--env", default=".env", help="Env file to watch (default: .env)")
    p_watch.add_argument("--example", default=".env.example", help="Example file to compare")
    p_watch.add_argument("--interval", type=float, default=1.0,
                         help="Poll interval in seconds (default: 1.0)")
    p_watch.add_argument("--strict", action="store_true", help="Use strict check mode")
    p_watch.add_argument("--no-scan", dest="scan", action="store_false",
                         help="Skip the secret scan on each change")
    p_watch.add_argument("--once", action="store_true",
                         help="Run a single check pass and exit")
    p_watch.set_defaults(func=cmd_watch, scan=True)

    p_doctor = subparsers.add_parser(
        "doctor",
        help="Diagnose your local setup",
        description="Print the facts that explain why a check or hook behaves "
        "the way it does: python, git, hooks, config, permissions and CI wiring.",
    )
    p_doctor.add_argument("path", nargs="?", default=".", help="Project root (default: .)")
    p_doctor.add_argument("--format", choices=["text", "json"], default="text",
                          help="Output format (default: text)")
    p_doctor.add_argument("--output", "-o", default="", help="Write results to a file")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def _configure_ui(args: argparse.Namespace) -> None:
    ui.color = UI(color=None if args.color == "auto" else args.color == "always").color
    ui.quiet = args.quiet


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    if args.command != "config":
        config_mod.apply(args, config_mod.Config.load(Path.cwd()), argv)
    _configure_ui(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
