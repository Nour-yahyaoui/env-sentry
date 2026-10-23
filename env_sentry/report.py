"""
Output formats for scan results.

``text`` is the human default, ``json`` is for scripts, ``sarif`` uploads to
GitHub code scanning, and ``github`` emits workflow annotations
(``::error file=…,line=…::…``) so findings show up inline on the diff.
"""

from __future__ import annotations

import json
from typing import Dict, Iterable, List

from . import detect
from .detect import SEVERITY_RANK, Finding

FORMATS = ("text", "json", "sarif", "github")

SEVERITY_COLORS = {
    detect.CRITICAL: "red",
    detect.HIGH: "red",
    detect.MEDIUM: "yellow",
    detect.LOW: "grey",
}

_SARIF_LEVEL = {
    detect.CRITICAL: "error",
    detect.HIGH: "error",
    detect.MEDIUM: "warning",
    detect.LOW: "note",
}


def counts(findings: Iterable[Finding]) -> Dict[str, int]:
    tally = {severity: 0 for severity in SEVERITY_RANK}
    for finding in findings:
        tally[finding.severity] = tally.get(finding.severity, 0) + 1
    return tally


def summary_line(findings: List[Finding]) -> str:
    tally = counts(findings)
    parts = [
        f"{tally[sev]} {sev}"
        for sev in (detect.CRITICAL, detect.HIGH, detect.MEDIUM, detect.LOW)
        if tally.get(sev)
    ]
    return f"{len(findings)} potential secret(s) found ({', '.join(parts)})."


def render_text(findings: List[Finding], ui, show_severity: bool = True) -> None:
    for finding in findings:
        location = ui.paint(f"{finding.path}:{finding.line}", "cyan")
        label = ui.paint(finding.severity.upper().ljust(8), SEVERITY_COLORS.get(finding.severity, ""))
        preview = finding.redacted()
        suffix = f"  {ui.paint('(' + preview + ')', 'grey')}" if preview else ""
        prefix = f"{label} " if show_severity else ""
        ui.write(f"{location}  {prefix}{finding.rule}{suffix}")


def to_json(findings: List[Finding], tool_version: str = "", root: str = "") -> str:
    payload = {
        "tool": "env-sentry",
        "version": tool_version,
        "root": root,
        "counts": counts(findings),
        "findings": [finding.to_dict() for finding in findings],
    }
    return json.dumps(payload, indent=2, sort_keys=False)


def to_github(findings: List[Finding]) -> str:
    lines = []
    for finding in findings:
        level = "error" if finding.severity in (detect.CRITICAL, detect.HIGH) else "warning"
        message = f"{finding.rule} ({finding.severity})"
        preview = finding.redacted()
        if preview:
            message += f": {preview}"
        message = message.replace("%", "%25").replace("\n", "%0A").replace(":", "%3A")
        lines.append(
            f"::{level} file={finding.path},line={finding.line},col={finding.column},"
            f"title=env-sentry::{message}"
        )
    return "\n".join(lines)


def to_sarif(findings: List[Finding], tool_version: str = "") -> str:
    rule_ids = sorted({finding.rule for finding in findings})
    rules = []
    for rule_id in rule_ids:
        rules.append(
            {
                "id": rule_id,
                "name": rule_id,
                "shortDescription": {"text": rule_id},
                "defaultConfiguration": {
                    "level": _SARIF_LEVEL.get(
                        next(finding.severity for finding in findings if finding.rule == rule_id),
                        "warning",
                    )
                },
            }
        )
    results = []
    for finding in findings:
        results.append(
            {
                "ruleId": finding.rule,
                "level": _SARIF_LEVEL.get(finding.severity, "warning"),
                "message": {"text": f"{finding.rule} ({finding.severity})"},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": finding.path},
                            "region": {"startLine": finding.line, "startColumn": finding.column},
                        }
                    }
                ],
                "properties": {"severity": finding.severity, "match": finding.redacted()},
            }
        )
    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "env-sentry",
                        "informationUri": "https://github.com/nour-yahyaoui/env-sentry",
                        "version": tool_version,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(payload, indent=2)


def should_fail(findings: List[Finding], fail_on: str = "any") -> bool:
    """Does the run warrant a non-zero exit code?"""
    if fail_on == "never" or not findings:
        return False
    if fail_on == "any":
        return True
    threshold = SEVERITY_RANK.get(fail_on, 0)
    return any(SEVERITY_RANK.get(finding.severity, 0) >= threshold for finding in findings)
