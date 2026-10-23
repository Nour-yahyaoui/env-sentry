import os
import stat
import subprocess
import sys

import pytest

from env_sentry import hooks


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_render_hook_marks_and_commands():
    body = hooks.render_hook("pre-push", version="1.2.3")
    assert hooks.BEGIN in body and hooks.END in body
    assert "1.2.3" in body
    assert "_run_env_sentry check" in body and "_run_env_sentry scan" in body


def test_install_creates_executable_hook(repo):
    path = hooks.install(repo, "pre-commit", version="9.9.9")
    assert path.name == "pre-commit"
    text = path.read_text()
    assert text.startswith("#!/bin/sh")
    assert hooks.BEGIN in text
    assert path.stat().st_mode & stat.S_IXUSR


def test_install_is_idempotent(repo):
    hooks.install(repo, "pre-commit")
    hooks.install(repo, "pre-commit")
    text = (hooks.hooks_dir(repo) / "pre-commit").read_text()
    assert text.count(hooks.BEGIN) == 1


def test_existing_hook_requires_force(repo):
    hook = hooks.hooks_dir(repo) / "pre-commit"
    hook.write_text("#!/bin/sh\necho existing\n")
    with pytest.raises(FileExistsError):
        hooks.install(repo, "pre-commit")
    assert hook.read_text().startswith("#!/bin/sh\necho existing")
    assert (hook.parent / "pre-commit.env-sentry.bak").exists()

    hooks.install(repo, "pre-commit", force=True)
    text = hook.read_text()
    assert "echo existing" in text
    assert hooks.BEGIN in text


def test_preserves_foreign_lines_and_uninstall_removes_only_ours(repo):
    hook = hooks.hooks_dir(repo) / "pre-push"
    hook.write_text("#!/bin/sh\necho custom\n")
    hooks.install(repo, "pre-push", force=True)
    assert "echo custom" in hook.read_text()

    assert hooks.uninstall(repo, "pre-push") is True
    assert hook.exists()
    assert "echo custom" in hook.read_text()
    assert hooks.BEGIN not in hook.read_text()
    assert hooks.uninstall(repo, "pre-push") is False


def test_uninstall_deletes_pure_env_sentry_hook(repo):
    hooks.install(repo, "pre-commit")
    assert hooks.uninstall(repo, "pre-commit") is True
    assert not (hooks.hooks_dir(repo) / "pre-commit").exists()


def test_status(repo):
    assert hooks.status(repo) == {"pre-commit": False, "pre-push": False}
    hooks.install(repo, "pre-commit")
    assert hooks.status(repo)["pre-commit"] is True


def test_repo_root_detection(repo):
    assert hooks.repo_root(repo) == repo.resolve()


def test_cli_flow(repo):
    result = run(["hooks", "status"], cwd=repo)
    assert "not installed" in result.stdout

    result = run(["hooks", "install", "--commands", "check,scan"], cwd=repo)
    assert result.returncode == 0
    text = (repo / ".git" / "hooks" / "pre-commit").read_text()
    assert "_run_env_sentry check" in text and "_run_env_sentry scan" in text

    assert "installed" in run(["hooks", "status"], cwd=repo).stdout
    assert run(["hooks", "uninstall"], cwd=repo).returncode == 0
    assert "not installed" in run(["hooks", "status"], cwd=repo).stdout


def test_cli_outside_git_repo(tmp_path):
    result = run(["hooks", "status"], cwd=tmp_path)
    assert result.returncode == 2
    assert "Not inside a git repository" in result.stdout
