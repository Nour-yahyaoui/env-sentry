import json
import subprocess
import sys

from env_sentry import stats
from env_sentry.envfile import EnvFile

SAMPLE = """# config
DB_URL=postgres://localhost/app
DB_PASSWORD=short
STRIPE_KEY=sk_live_abcdefgh12345678
API_KEY=sk_live_abcdefgh12345678
EMPTY=
PORT=5432
DEBUG=false
DUP=1
DUP=2
"""


def test_counts_and_categories():
    env = EnvFile.parse(SAMPLE)
    result = stats.analyse(env, ".env", SAMPLE)
    assert result.keys == 9
    assert result.comments == 1
    assert result.empty_values == 1
    assert result.duplicates == 1
    assert result.categories["database"] == 2
    assert result.categories["payments"] == 1
    assert result.max_length == 24
    assert result.bytes == len(SAMPLE.encode())


def test_repeated_values_and_weak_keys():
    result = stats.analyse(EnvFile.parse(SAMPLE), ".env", SAMPLE)
    assert ["STRIPE_KEY", "API_KEY"] in result.repeated_values
    assert "DB_PASSWORD" in result.weak_keys


def test_category_for_unknown_key():
    assert stats.category_for("SOMETHING_ELSE") == "other"
    assert stats.category_for("OPENAI_API_KEY") == "ai"


def test_empty_file():
    result = stats.analyse(EnvFile.parse(""))
    assert result.keys == 0
    assert result.avg_length == 0


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_cli_text_and_json(tmp_path):
    (tmp_path / ".env").write_text(SAMPLE)
    result = run(["stats"], cwd=tmp_path)
    assert result.returncode == 0
    assert "Keys by category" in result.stdout
    assert "reused under multiple keys" in result.stdout

    result = run(["stats", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["keys"] == 9
    assert payload["categories"]["payments"] == 1

    assert run(["stats", "--env", "missing.env"], cwd=tmp_path).returncode == 2
