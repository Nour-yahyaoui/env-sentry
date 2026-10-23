import base64
import json
import subprocess
import sys

from env_sentry import exporters
from env_sentry.envfile import EnvFile

ENV = EnvFile.parse(
    "# app\n"
    "API_KEY=sk_live_abcdefgh12345678\n"
    'DB_URL=postgres://user:pw@localhost:5432/app\n'
    'GREETING="hello world"\n'
)


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_json_export():
    payload = json.loads(exporters.export_env(ENV, "json"))
    assert payload["API_KEY"] == "sk_live_abcdefgh12345678"


def test_yaml_and_shell():
    yaml_out = exporters.export_env(ENV, "yaml")
    assert "API_KEY: sk_live_abcdefgh12345678" in yaml_out
    shell_out = exporters.export_env(ENV, "shell")
    assert 'export GREETING="hello world"' in shell_out


def test_compose_and_k8s():
    compose = exporters.export_env(ENV, "compose", service="api")
    assert "services:" in compose and "      - API_KEY=sk_live" in compose
    k8s = exporters.export_env(ENV, "k8s", name="db-creds", namespace="prod")
    assert "name: db-creds" in k8s and "namespace: prod" in k8s
    encoded = base64.b64encode(b"sk_live_abcdefgh12345678").decode()
    assert encoded in k8s


def test_ini_tfvars_csv():
    assert exporters.export_env(ENV, "ini", section="db").startswith("[db]\n")
    assert 'API_KEY = "sk_live_abcdefgh12345678"' in exporters.export_env(ENV, "tfvars")
    assert "KEY,VALUE" in exporters.export_env(ENV, "csv")


def test_redact_hides_values():
    out = exporters.export_env(ENV, "json", redact=True)
    assert "sk_live_abcdefgh12345678" not in out
    assert "sk_l…5678" in out


def test_include_exclude_and_prefix():
    out = json.loads(exporters.export_env(ENV, "json", include=["API_*"], prefix="APP_"))
    assert list(out) == ["APP_API_KEY"]
    out = json.loads(exporters.export_env(ENV, "json", exclude=["API_*", "DB_*"]))
    assert list(out) == ["GREETING"]


def test_unknown_format_raises():
    try:
        exporters.export_env(ENV, "nope")
    except ValueError as exc:
        assert "unknown" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_cli_export_to_file(tmp_path):
    (tmp_path / ".env").write_text("A=1\nB=two\n")
    target = tmp_path / "secrets.yaml"
    result = run(["export", "--format", "yaml", "-o", str(target)], cwd=tmp_path)
    assert result.returncode == 0
    assert "A: 1" in target.read_text()

    result = run(["export", "--format", "json", "--redact"], cwd=tmp_path)
    assert json.loads(result.stdout)["B"] == "****"

    assert run(["export", "--env", "missing.env"], cwd=tmp_path).returncode == 2
