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


def test_scan_ignores_token_count_variables(tmp_path: Path):
    (tmp_path / "config.py").write_text(
        "max_tokens = 4096\n"
        "use_token_streaming = True\n"
        "delta_tokens_seen = 128000\n"
        "a_tokens, b_tokens = split_tokens(text)\n"
    )

    result = run(["scan", "."], cwd=tmp_path)
    assert result.returncode == 0
    assert "Suspicious value" not in result.stdout


def test_scan_ignores_non_literal_values(tmp_path: Path):
    (tmp_path / "config.py").write_text(
        'ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")\n'
        "ANTHROPIC_AUTH_TOKEN = get_token_from_vault()\n"
    )

    result = run(["scan", "."], cwd=tmp_path)
    assert result.returncode == 0
    assert "Suspicious value" not in result.stdout


def test_check_does_not_claim_sync_when_env_missing(tmp_path: Path):
    (tmp_path / ".env.example").write_text("# scaffold\n")
    (tmp_path / ".gitignore").write_text(".env\n")

    result = run(["check"], cwd=tmp_path)
    assert "in sync" not in result.stdout
    assert "not found" in result.stdout


def test_version_shows_author(tmp_path: Path):
    result = run(["--version"], cwd=tmp_path)
    assert "env-sentry" in result.stdout
    assert "Nour Yahyaoui" in result.stdout


def test_check_respects_custom_env_path_for_gitignore(tmp_path: Path):
    (tmp_path / ".env.staging").write_text("API_KEY=abc123supersecret\n")
    (tmp_path / ".env.example").write_text("API_KEY=your_api_key_here\n")
    (tmp_path / ".gitignore").write_text(".env\n")  # does NOT cover .env.staging

    result = run(["check", "--env", ".env.staging"], cwd=tmp_path)
    assert result.returncode == 1
    assert ".env.staging" in result.stdout
    assert "does not appear to be listed in .gitignore" in result.stdout


def test_scan_detects_secrets_in_html(tmp_path: Path):
    fake_token = "ghp_" + "x" * 36  # built at runtime, not a literal secret-shaped string
    (tmp_path / "index.html").write_text(
        "<html><body><script>\n"
        f'const api_key ="{fake_token}"\n'
        "</script></body></html>\n"
    )

    result = run(["scan", "."], cwd=tmp_path)
    assert result.returncode == 1
    assert "GitHub Token" in result.stdout


def test_scan_detects_env_variant_files(tmp_path: Path):
    fake_token = "ghp_" + "x" * 36  # built at runtime, not a literal secret-shaped string
    (tmp_path / ".env.local").write_text(f"API_KEY={fake_token}\n")

    result = run(["scan", "."], cwd=tmp_path)
    assert result.returncode == 1
    assert ".env.local" in result.stdout


def test_scan_still_flags_real_hardcoded_secret(tmp_path: Path):
    (tmp_path / "config.py").write_text(
        'STRIPE_SECRET_KEY = "sk_test_reallyLongHardcodedSecretValue123456"\n'
    )

    result = run(["scan", "."], cwd=tmp_path)
    assert result.returncode == 1
    assert "STRIPE_SECRET_KEY" in result.stdout
