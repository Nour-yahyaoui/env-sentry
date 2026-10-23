import json
import subprocess
import sys


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def setup(tmp_path, env=None, example="API_KEY=your_api_key_here\n", gitignore=".env\n"):
    if env is not None:
        (tmp_path / ".env").write_text(env)
    if example is not None:
        (tmp_path / ".env.example").write_text(example)
    if gitignore is not None:
        (tmp_path / ".gitignore").write_text(gitignore)


def test_strict_fails_on_missing_local_keys(tmp_path):
    setup(tmp_path, env="API_KEY=real123\n", example="API_KEY=x\nNEW_KEY=y\n")
    assert run(["check"], cwd=tmp_path).returncode == 0
    result = run(["check", "--strict"], cwd=tmp_path)
    assert result.returncode == 1


def test_ci_alias(tmp_path):
    setup(tmp_path, env="API_KEY=real123\n", example="API_KEY=x\nNEW_KEY=y\n")
    assert run(["check", "--ci"], cwd=tmp_path).returncode == 1


def test_duplicates_and_empty_values_reported(tmp_path):
    setup(tmp_path, env="A=1\nA=2\nEMPTY=\n", example="A=x\nEMPTY=y\n")
    result = run(["check"], cwd=tmp_path)
    assert result.returncode == 0
    assert "Duplicate keys" in result.stdout
    assert "have no value" in result.stdout
    assert run(["check", "--strict"], cwd=tmp_path).returncode == 1


def test_json_output(tmp_path):
    setup(tmp_path, env="A=1\nB=2\n", example="A=x\n")
    result = run(["check", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["missing_in_example"] == ["B"]
    assert payload["duplicates"] == {}
    assert payload["exit_code"] == 1


def test_ci_without_env_file_does_not_fail_on_missing_keys(tmp_path):
    setup(tmp_path, env=None, example="A=x\nB=y\n")
    result = run(["check", "--ci", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["missing_in_env"] == []
    assert payload["exit_code"] == 0
