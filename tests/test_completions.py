import subprocess
import sys

from env_sentry import completions
from env_sentry.cli import build_parser


def test_bash_mentions_every_subcommand():
    script = completions.bash(build_parser())
    for command in ("init", "check", "sync", "scan", "audit", "diff", "export", "gen"):
        assert command in script
    assert "complete -F _env_sentry_complete env-sentry" in script


def test_zsh_and_fish_renderers():
    zsh = completions.zsh(build_parser())
    assert zsh.startswith("#compdef env-sentry")
    assert "'scan:" in zsh or "scan)" in zsh

    fish = completions.fish(build_parser())
    assert "complete -c env-sentry" in fish
    assert "__fish_use_subcommand" in fish


def test_unknown_shell():
    try:
        completions.render("powershell", build_parser())
    except ValueError as exc:
        assert "unsupported shell" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_cli_output_and_file(tmp_path):
    result = run(["completions", "bash"], cwd=tmp_path)
    assert result.returncode == 0
    assert "# bash completion" in result.stdout

    target = tmp_path / "completions.bash"
    result = run(["completions", "bash", "-o", str(target)], cwd=tmp_path)
    assert result.returncode == 0
    assert target.exists()
    assert "install" in result.stdout or "eval" in result.stdout


def test_generated_bash_is_syntactically_valid(tmp_path):
    script = tmp_path / "c.bash"
    result = run(["completions", "bash", "-o", str(script)], cwd=tmp_path)
    check = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0
    assert check.returncode == 0, check.stderr
