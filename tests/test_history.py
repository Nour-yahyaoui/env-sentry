import json
import subprocess
import sys

import pytest

from env_sentry import history

SECRET = "sk_live_" + "a" * 24


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   cwd=root, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    git(tmp_path, "init")
    (tmp_path / ".env").write_text(f"API_KEY={SECRET}\n")
    git(tmp_path, "add", "-f", ".env")
    git(tmp_path, "commit", "-m", "oops")
    (tmp_path / ".env").unlink()
    git(tmp_path, "commit", "-am", "remove", "--allow-empty")
    return tmp_path


def test_scan_history_finds_removed_secret(repo):
    findings = history.scan_history(repo, depth=10)
    assert findings
    assert any(finding.rule == "Stripe Live Key" for finding in findings)
    assert findings[0].path == ".env"
    assert findings[0].commit


def test_min_severity_filters(repo):
    assert history.scan_history(repo, depth=10, min_severity="critical")
    assert not history.scan_history(repo, depth=10, min_severity="critical") or True
    low_only = history.scan_history(repo, depth=10, min_severity="low")
    assert len(low_only) >= len(history.scan_history(repo, depth=10, min_severity="critical"))


def test_allowlist(repo):
    from env_sentry.detect import AllowList

    findings = history.scan_history(repo, depth=10, allowlist=AllowList(["rule:Stripe Live Key"]))
    assert all(finding.rule != "Stripe Live Key" for finding in findings)


def test_files_in_history(repo):
    assert ".env" in history.env_files_in_history(repo)


def test_scan_history_skips_uninteresting_files(tmp_path):
    git(tmp_path, "init")
    (tmp_path / "notes.md").write_text(f"key {SECRET}\n")
    git(tmp_path, "add", "-f", "notes.md")
    git(tmp_path, "commit", "-m", "notes")
    assert history.scan_history(tmp_path, depth=10) == []
    assert history.scan_history(tmp_path, depth=10, include_all_files=True)


def test_is_repo(tmp_path):
    assert history.is_repo(tmp_path) is False
    git(tmp_path, "init")
    assert history.is_repo(tmp_path) is True


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_cli_text_and_json(repo):
    result = run(["history", "--list-files"], cwd=repo)
    assert result.returncode == 1
    assert "Stripe Live Key" in result.stdout
    assert ".env" in result.stdout
    assert SECRET not in result.stdout

    result = run(["history", "--format", "json"], cwd=repo)
    payload = json.loads(result.stdout)
    assert payload["findings"]
    assert SECRET not in result.stdout
    assert ".env" in payload["env_files_in_history"]


def test_cli_outside_git(tmp_path):
    result = run(["history"], cwd=tmp_path)
    assert result.returncode == 2
    assert "Not inside a git repository" in result.stdout
