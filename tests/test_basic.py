import subprocess
import sys
from pathlib import Path


def run(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "env_sentry.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_init_and_check(tmp_path: Path):
    (tmp_path / ".env").write_text("API_KEY=abc123\nDEBUG=true\n")

    result = run(["init"], cwd=tmp_path)
    assert "Created" in result.stdout or ".env.example" in result.stdout

    result = run(["sync"], cwd=tmp_path)
    assert result.returncode == 0

    result = run(["check"], cwd=tmp_path)
    assert result.returncode == 0
    assert "in sync" in result.stdout


def test_check_flags_missing_key(tmp_path: Path):
    (tmp_path / ".env").write_text("API_KEY=abc123\nEXTRA_KEY=zzz\n")
    (tmp_path / ".env.example").write_text("API_KEY=your_api_key_here\n")
    (tmp_path / ".gitignore").write_text(".env\n")

    result = run(["check"], cwd=tmp_path)
    assert result.returncode == 1
    assert "EXTRA_KEY" in result.stdout


def test_scan_detects_known_pattern(tmp_path: Path):
    (tmp_path / "config.py").write_text('AWS_KEY = "AKIAABCDEFGHIJKLMNOP"\n')

    result = run(["scan", "."], cwd=tmp_path)
    assert result.returncode == 1
    assert "AWS Access Key" in result.stdout
