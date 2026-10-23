import subprocess
import sys

from env_sentry import cicd


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_templates_contain_expected_steps():
    github = cicd.render("github")
    assert "env-sentry scan" in github
    assert "upload-sarif" in github
    assert "env-sentry check" in github
    assert cicd.render("gitlab").count("env-sentry") >= 2
    assert "pre-commit" in cicd.render("pre-commit")


def test_unknown_provider():
    try:
        cicd.render("jenkins")
    except ValueError as exc:
        assert "unknown provider" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_cli_prints_by_default(tmp_path):
    result = run(["ci"], cwd=tmp_path)
    assert result.returncode == 0
    assert "name: env-sentry" in result.stdout
    assert not (tmp_path / ".github").exists()


def test_cli_write_and_force(tmp_path):
    result = run(["ci", "--write"], cwd=tmp_path)
    assert result.returncode == 0
    target = tmp_path / ".github" / "workflows" / "env-sentry.yml"
    assert target.exists()

    assert run(["ci", "--write"], cwd=tmp_path).returncode == 1
    assert run(["ci", "--write", "--force"], cwd=tmp_path).returncode == 0


def test_cli_precommit_provider_to_custom_path(tmp_path):
    target = tmp_path / "pre-commit.yaml"
    result = run(["ci", "--provider", "pre-commit", "--write", "-o", str(target)], cwd=tmp_path)
    assert result.returncode == 0
    assert "env-sentry-scan" in target.read_text()
