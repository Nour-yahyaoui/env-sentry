import subprocess
import sys

import env_sentry
from env_sentry import cli


def test_versions_stay_in_sync():
    assert cli.VERSION == env_sentry.__version__
    assert cli.AUTHOR == env_sentry.__author__


def test_version_flag():
    result = subprocess.run([sys.executable, "-m", "env_sentry.cli", "--version"],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert env_sentry.__version__ in result.stdout
    assert "Nour Yahyaoui" in result.stdout


def test_python_dash_m_entrypoint():
    result = subprocess.run([sys.executable, "-m", "env_sentry", "--version"],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert env_sentry.__version__ in result.stdout


def test_help_lists_every_command():
    result = subprocess.run([sys.executable, "-m", "env_sentry", "--help"],
                            capture_output=True, text=True)
    for command in ("init", "check", "sync", "scan", "lint", "diff", "export", "gen",
                    "audit", "badge", "hooks", "merge", "prune", "stats", "config",
                    "ci", "completions", "history", "watch", "doctor"):
        assert command in result.stdout, command
