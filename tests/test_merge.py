import subprocess
import sys

from env_sentry import merge
from env_sentry.envfile import EnvFile


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_adds_missing_keys_as_placeholders():
    target = EnvFile.parse("# mine\nAPI_KEY=realvalue\n")
    source = EnvFile.parse("API_KEY=other\nNEW_KEY=supersecretvalue\nPORT=8080\n")
    plan = merge.plan_merge(target, source)
    assert plan.added == ["NEW_KEY", "PORT"]
    assert plan.skipped == ["API_KEY"]
    rendered = target.render()
    assert "NEW_KEY=your_new_key_here" in rendered
    assert "supersecretvalue" not in rendered
    assert "PORT=8080" in rendered  # numeric config is not a secret
    assert "# mine" in rendered


def test_with_values_and_overwrite():
    target = EnvFile.parse("API_KEY=old\n")
    source = EnvFile.parse("API_KEY=new-value-1234\n")
    plan = merge.plan_merge(target, source)
    assert plan.skipped == ["API_KEY"]
    plan = merge.plan_merge(target, source, overwrite=True, with_values=True)
    assert plan.overwritten == ["API_KEY"]
    assert target.get("API_KEY") == "new-value-1234"


def test_only_and_skip_filters():
    target = EnvFile.parse("")
    source = EnvFile.parse("DB_HOST=h\nDB_PORT=p\nAPI_KEY=k\n")
    plan = merge.plan_merge(target, source, only=["DB_*"], skip=["DB_PORT"])
    assert plan.added == ["DB_HOST"]


def test_merge_files_dry_run(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".env.example").write_text("A=x\nB=y\n")
    plan = merge.merge_files(tmp_path / ".env", tmp_path / ".env.example", dry_run=True)
    assert plan.added == ["B"]
    assert (tmp_path / ".env").read_text() == "A=1\n"
    merge.merge_files(tmp_path / ".env", tmp_path / ".env.example")
    assert "B=" in (tmp_path / ".env").read_text()


def test_prune_dry_run_and_write(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("# c\nKEEP=1\nDEAD=2\n")
    plan, backup = merge.prune(env_path, keep_keys=["KEEP"], dry_run=True)
    assert plan.removed == ["DEAD"]
    assert backup is None
    assert "DEAD=2" in env_path.read_text()

    plan, backup = merge.prune(env_path, keep_keys=["KEEP"], dry_run=False)
    assert plan.removed == ["DEAD"]
    assert "DEAD" not in env_path.read_text()
    assert "# c" in env_path.read_text()
    assert backup and backup.exists()


def test_prune_keep_patterns(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("KEEP=1\nFEATURE_X=2\n")
    plan, _ = merge.prune(env_path, keep_keys=["KEEP"], keep_patterns=["FEATURE_*"], dry_run=False)
    assert plan.removed == []
    assert plan.kept == ["KEEP", "FEATURE_X"]


def test_cli_merge_and_prune(tmp_path):
    (tmp_path / ".env").write_text("API_KEY=real\nOLD=1\n")
    (tmp_path / ".env.example").write_text("API_KEY=x\nNEW=2\n")

    result = run(["merge", ".env.example", ".env", "--dry-run"], cwd=tmp_path)
    assert "+ NEW" in result.stdout
    assert "Dry run" in result.stdout

    result = run(["merge", ".env.example", ".env"], cwd=tmp_path)
    assert result.returncode == 0
    assert "NEW=" in (tmp_path / ".env").read_text()

    result = run(["prune", "--from-example"], cwd=tmp_path)
    assert "OLD" in result.stdout
    assert "OLD=1" in (tmp_path / ".env").read_text()  # dry run

    result = run(["prune", "--from-example", "--write"], cwd=tmp_path)
    assert result.returncode == 0
    assert "OLD=1" not in (tmp_path / ".env").read_text()
    assert (tmp_path / ".env.bak").exists()

    assert run(["merge", "nope.env", ".env"], cwd=tmp_path).returncode == 2
