import json
import subprocess
import sys

from env_sentry import doctor


def git(root, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                   cwd=root, check=True, capture_output=True)


def by_label(facts):
    return {fact.label: fact for fact in facts}


def test_diagnose_basic_facts(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".env.example").write_text("A=x\n")
    facts = by_label(doctor.diagnose(tmp_path, "1.2.3"))
    assert facts["env-sentry"].value == "1.2.3"
    assert facts["env files"].value.startswith("2 (")
    assert facts["python"].status == doctor.OK


def test_permissions_warning(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    env.chmod(0o644)
    facts = by_label(doctor.diagnose(tmp_path))
    assert facts["permissions"].status == doctor.WARN
    env.chmod(0o600)
    facts = by_label(doctor.diagnose(tmp_path))
    assert facts["permissions"].status == doctor.OK


def test_git_facts_and_ci_detection(tmp_path):
    git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("run: env-sentry scan\n")

    facts = by_label(doctor.diagnose(tmp_path))
    assert facts["repository"].status == doctor.OK
    assert facts[".env ignored"].status == doctor.OK
    assert facts["CI integration"].status == doctor.OK


def test_ci_runs_env_sentry_none(tmp_path):
    assert doctor.ci_runs_env_sentry(tmp_path) is None


def test_suggestions_only_for_warnings(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".env").chmod(0o644)
    hints = doctor.suggestions(doctor.diagnose(tmp_path))
    assert any("chmod 600" in hint for hint in hints)


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_cli_text_and_json(tmp_path):
    git(tmp_path, "init")
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".env").chmod(0o600)

    result = run(["doctor"], cwd=tmp_path)
    assert result.returncode == 0
    assert "env-sentry doctor" in result.stdout
    assert "python" in result.stdout

    result = run(["doctor", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    labels = [fact["label"] for fact in payload["facts"]]
    assert "env-sentry" in labels
    assert isinstance(payload["suggestions"], list)
