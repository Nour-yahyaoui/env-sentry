import json
import subprocess
import sys
from pathlib import Path

from env_sentry import detect, report
from env_sentry.detect import Finding

SECRET = "sk_live_" + "a" * 24


def sample():
    return [
        Finding(path="app.py", line=3, column=1, rule="Stripe Live Key",
                severity=detect.CRITICAL, value=SECRET),
        Finding(path="docs/x.md", line=9, column=5, rule="JWT", severity=detect.MEDIUM,
                value="eyJabcdefghij.eyJabcdefghij.abcdefghij"),
    ]


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_json_shape_and_redaction():
    payload = json.loads(report.to_json(sample(), "9.9.9", "."))
    assert payload["tool"] == "env-sentry"
    assert payload["counts"]["critical"] == 1
    assert len(payload["findings"]) == 2
    assert SECRET not in json.dumps(payload)
    assert payload["findings"][0]["rule"] == "Stripe Live Key"


def test_github_annotations():
    out = report.to_github(sample())
    assert "::error file=app.py,line=3" in out
    assert "::warning file=docs/x.md,line=9" in out


def test_sarif_is_valid_ish():
    payload = json.loads(report.to_sarif(sample(), "9.9.9"))
    assert payload["version"] == "2.1.0"
    run_result = payload["runs"][0]
    assert run_result["tool"]["driver"]["name"] == "env-sentry"
    assert len(run_result["results"]) == 2
    assert run_result["results"][0]["locations"][0]["physicalLocation"]["region"]["startLine"] == 3


def test_should_fail_thresholds():
    findings = sample()
    assert report.should_fail(findings, "any")
    assert report.should_fail(findings, detect.CRITICAL)
    assert not report.should_fail(findings, "never")
    assert not report.should_fail([], "any")
    medium_only = [findings[1]]
    assert not report.should_fail(medium_only, detect.HIGH)


def test_cli_json_format_and_exit_codes(tmp_path):
    (tmp_path / "app.py").write_text(f'STRIPE_SECRET_KEY = "{SECRET}"\n')
    result = run(["scan", ".", "--format", "json"], cwd=tmp_path)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["findings"]

    result = run(["scan", ".", "--format", "json", "--fail-on", "never"], cwd=tmp_path)
    assert result.returncode == 0

    result = run(["scan", ".", "--format", "json", "--min-severity", "critical"], cwd=tmp_path)
    assert "Stripe Live Key" in result.stdout


def test_cli_output_file(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    target = tmp_path / "out.json"
    result = run(["scan", ".", "--format", "json", "-o", str(target)], cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(target.read_text())["findings"] == []


def test_cli_exclude_and_allowlist(tmp_path):
    (tmp_path / "vendorish").mkdir()
    (tmp_path / "vendorish" / "leak.py").write_text(f'K = "{SECRET}"\n')
    (tmp_path / "ok.py").write_text("x = 1\n")

    result = run(["scan", ".", "--exclude", "vendorish/*"], cwd=tmp_path)
    assert result.returncode == 0

    (tmp_path / ".env-sentry-allow").write_text("rule:Stripe Live Key\n")
    result = run(["scan", "."], cwd=tmp_path)
    assert result.returncode == 0
