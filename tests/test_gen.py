import stat
import subprocess
import sys

from env_sentry import gensecrets


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_generate_lengths_and_charsets():
    value = gensecrets.generate(length=40, charset="hex")
    assert len(value) == 40
    assert all(ch in gensecrets.HEX for ch in value)
    assert gensecrets.generate(prefix="sk_").startswith("sk_")


def test_generate_is_random():
    assert gensecrets.generate(length=32) != gensecrets.generate(length=32)


def test_invalid_parameters():
    for kwargs in ({"length": 2}, {"charset": "klingon"}):
        try:
            gensecrets.generate(**kwargs)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"expected ValueError for {kwargs}")


def test_passphrase_options():
    phrase = gensecrets.passphrase(words=5)
    assert len(phrase.split("-")) == 5
    assert gensecrets.passphrase(words=3, capitalize=True)[0].isupper()
    assert any(ch.isdigit() for ch in gensecrets.passphrase(words=2, number=True))


def test_strength_scores():
    assert gensecrets.strength("password") <= 10
    assert gensecrets.strength(gensecrets.generate(length=32)) >= 70


def test_generate_for_key_picks_passphrase_for_password():
    assert "-" in gensecrets.generate_for_key("DB_PASSWORD")


def test_cli_fills_placeholders(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# app\nAPI_KEY=your_api_key_here\nEMPTY=\nREAL=alreadyrealvalue123\n")
    result = run(["gen", "--length", "24"], cwd=tmp_path)
    assert result.returncode == 0
    text = env.read_text()
    assert "your_api_key_here" not in text
    assert "REAL=alreadyrealvalue123" in text
    assert "# app" in text
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    for line in text.splitlines():
        if line.startswith("API_KEY"):
            assert len(line.split("=", 1)[1]) == 24
    # non-secret names are left alone unless --all-keys is used
    assert "EMPTY=\n" in text


def test_all_keys_fills_non_secret_names(tmp_path):
    env = tmp_path / ".env"
    env.write_text("APP_NAME=\nAPI_KEY=\n")
    run(["gen", "--all-keys", "--length", "20"], cwd=tmp_path)
    text = env.read_text()
    for line in text.splitlines():
        assert len(line.split("=", 1)[1]) == 20


def test_seeds_env_from_example_when_missing(tmp_path):
    (tmp_path / ".env.example").write_text(
        "APP_NAME=my-app\nAPI_KEY=your_api_key_here\nDB_PASSWORD=\n"
    )
    result = run(["gen", "--length", "20"], cwd=tmp_path)
    assert result.returncode == 0
    assert "seeding it from .env.example" in result.stdout
    text = (tmp_path / ".env").read_text()
    assert "my-app" in text
    lines = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    assert len(lines["API_KEY"]) == 20
    assert "-" in lines["DB_PASSWORD"]  # password keys become passphrases


def test_cli_dry_run_does_not_write(tmp_path):
    env = tmp_path / ".env"
    env.write_text("API_KEY=\n")
    result = run(["gen", "--dry-run"], cwd=tmp_path)
    assert "API_KEY=" in result.stdout
    assert env.read_text() == "API_KEY=\n"


def test_cli_force_and_specific_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=realvalue123\nB=realvalue456\n")
    result = run(["gen", "--key", "A", "--print"], cwd=tmp_path)
    assert result.returncode == 0
    lines = dict(line.split("=", 1) for line in env.read_text().splitlines())
    assert lines["A"] != "realvalue123"
    assert lines["B"] == "realvalue456"

    result = run(["gen", "--force", "--dry-run"], cwd=tmp_path)
    assert "A=" in result.stdout and "B=" in result.stdout


def test_cli_missing_env(tmp_path):
    assert run(["gen"], cwd=tmp_path).returncode == 2
