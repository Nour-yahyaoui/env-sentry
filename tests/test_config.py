import json
import subprocess
import sys

from env_sentry import config


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_load_missing(tmp_path):
    cfg = config.Config.load(tmp_path)
    assert cfg.data == {}
    assert cfg.path is None


def test_load_and_nested_lookup(tmp_path):
    (tmp_path / ".env-sentry.json").write_text('{"env": ".env.custom"}')
    nested = tmp_path / "src" / "deep"
    nested.mkdir(parents=True)
    cfg = config.Config.load(nested)
    assert cfg.get("env") == ".env.custom"
    assert cfg.path.name == ".env-sentry.json"


def test_invalid_json_is_ignored(tmp_path):
    (tmp_path / ".env-sentry.json").write_text("{not json")
    assert config.Config.load(tmp_path).data == {}


def test_warnings_for_unknown_and_bad_types(tmp_path):
    (tmp_path / ".env-sentry.json").write_text('{"nope": 1, "env": 5}')
    warnings = config.Config.load(tmp_path).warnings()
    assert any("unknown key" in message for message in warnings)
    assert any("should be str" in message for message in warnings)


def test_as_list_accepts_strings(tmp_path):
    (tmp_path / ".env-sentry.json").write_text('{"exclude": "a/*, b/*"}')
    cfg = config.Config.load(tmp_path)
    assert cfg.as_list("exclude") == ["a/*", "b/*"]
    assert cfg.as_csv("exclude") == "a/*,b/*"


def test_cli_init_and_show(tmp_path):
    result = run(["config"], cwd=tmp_path)
    assert "No .env-sentry.json" in result.stdout

    assert run(["config", "--init"], cwd=tmp_path).returncode == 0
    assert (tmp_path / ".env-sentry.json").exists()
    assert run(["config", "--init"], cwd=tmp_path).returncode == 1
    assert run(["config", "--init", "--force"], cwd=tmp_path).returncode == 0

    (tmp_path / ".env-sentry.json").write_text('{"env": ".env.local", "min_severity": "high"}')
    result = run(["config", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["config"]["env"] == ".env.local"


def test_config_supplies_flag_defaults(tmp_path):
    (tmp_path / ".env-sentry.json").write_text('{"min_severity": "critical", "fail_on": "high"}')
    (tmp_path / ".env").write_text("API_KEY=sk_test_abcdefghijklmnopqrst\n")

    result = run(["scan", ".", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["findings"] == []  # medium Stripe test key filtered out

    result = run(["scan", ".", "--format", "json", "--min-severity", "low"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["findings"]


def test_explicit_flag_beats_config(tmp_path):
    (tmp_path / ".env-sentry.json").write_text('{"min_severity": "critical"}')
    (tmp_path / ".env").write_text("API_KEY=sk_test_abcdefghijklmnopqrst\n")
    result = run(["scan", ".", "--format", "json", "--min-severity=low"], cwd=tmp_path)
    assert json.loads(result.stdout)["findings"]
