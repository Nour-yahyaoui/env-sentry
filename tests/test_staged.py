import subprocess
import sys

import pytest

from env_sentry.scanner import staged_files


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   cwd=root, check=True, capture_output=True)


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    git(tmp_path, "init")
    return tmp_path


def test_staged_files_only_returns_staged(repo):
    (repo / "a.py").write_text("x = 1\n")
    (repo / "b.py").write_text("y = 2\n")
    git(repo, "add", "a.py")
    staged = [path.name for path in staged_files(repo)]
    assert staged == ["a.py"]


def test_staged_ignores_deleted_and_ignored_dirs(repo):
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "x.js").write_text("z = 1\n")
    (repo / "keep.py").write_text("k = 1\n")
    git(repo, "add", "-f", "node_modules/x.js", "keep.py")
    names = [path.name for path in staged_files(repo)]
    assert "keep.py" in names
    assert "x.js" not in names


def test_cli_scan_staged(repo):
    (repo / "clean.py").write_text("value = 1\n")
    git(repo, "add", "clean.py")
    result = run(["scan", ".", "--staged"], cwd=repo)
    assert result.returncode == 0
    assert "Nothing staged" not in result.stdout

    (repo / "leak.py").write_text('KEY = "sk_live_' + "a" * 24 + '"\n')
    git(repo, "add", "leak.py")
    result = run(["scan", ".", "--staged"], cwd=repo)
    assert result.returncode == 1
    assert "Stripe Live Key" in result.stdout


def test_cli_scan_staged_nothing_staged(repo):
    result = run(["scan", ".", "--staged"], cwd=repo)
    assert result.returncode == 0
    assert "Nothing staged" in result.stdout


def test_scan_files_helper(tmp_path):
    from env_sentry import detect

    leak = tmp_path / "a.py"
    leak.write_text('K = "AKIAIOSFODNN7EXAMPLE"\n')
    clean = tmp_path / "b.py"
    clean.write_text("x = 1\n")
    findings = detect.scan_files([leak, clean])
    assert [finding.path for finding in findings] == [str(leak)]
