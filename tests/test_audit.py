import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from env_sentry import audit as audit_mod


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def make_repo(tmp_path: Path, env_text="API_KEY=abc123realvalue\n",
              example_text="API_KEY=your_api_key_here\n",
              gitignore=".env\n", perms=0o600):
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / ".env").write_text(env_text)
    if example_text is not None:
        (tmp_path / ".env.example").write_text(example_text)
    if gitignore is not None:
        (tmp_path / ".gitignore").write_text(gitignore)
    os.chmod(tmp_path / ".env", perms)
    return tmp_path


def by_id(result):
    return {check.ident: check for check in result.checks}


def test_clean_repo_scores_high(tmp_path):
    root = make_repo(tmp_path)
    result = audit_mod.audit(root)
    assert result.score >= 90, [c.to_dict() for c in result.checks]
    assert result.grade in {"A", "A+"}
    assert result.counts[audit_mod.FAIL] == 0


def test_missing_example_fails(tmp_path):
    root = make_repo(tmp_path, example_text=None)
    checks = by_id(audit_mod.audit(root))
    assert checks["example-exists"].status == audit_mod.FAIL
    assert checks["example-clean"].status == audit_mod.PASS


def test_not_gitignored_fails(tmp_path):
    root = make_repo(tmp_path, gitignore="node_modules/\n")
    checks = by_id(audit_mod.audit(root))
    assert checks["env-ignored"].status == audit_mod.FAIL
    assert audit_mod.audit(root).score < 90


def test_tracked_env_file_fails(tmp_path):
    root = make_repo(tmp_path, gitignore=None)
    (root / ".gitignore").write_text("")
    git(root, "add", "-f", ".env")
    git(root, "commit", "-m", "oops", "--no-gpg-sign")
    checks = by_id(audit_mod.audit(root))
    assert checks["env-tracked"].status == audit_mod.FAIL
    assert checks["env-history"].status == audit_mod.FAIL


def test_world_readable_permissions_warns(tmp_path):
    root = make_repo(tmp_path, perms=0o644)
    checks = by_id(audit_mod.audit(root))
    assert checks["env-permissions"].status == audit_mod.WARN


def test_duplicates_empty_and_syntax(tmp_path):
    root = make_repo(tmp_path, env_text="A=1\nA=2\nSECRET=\nBAD LINE HERE\n")
    checks = by_id(audit_mod.audit(root))
    assert checks["env-duplicates"].status == audit_mod.WARN
    assert checks["env-filled"].status == audit_mod.WARN
    assert checks["env-lint"].status == audit_mod.FAIL


def test_example_with_real_secret_fails(tmp_path):
    secret = "sk_live_" + "a" * 24
    root = make_repo(tmp_path, example_text=f"API_KEY={secret}\n")
    checks = by_id(audit_mod.audit(root))
    assert checks["example-clean"].status == audit_mod.FAIL


def test_key_parity(tmp_path):
    root = make_repo(tmp_path, env_text="A=1\nB=2\n", example_text="A=x\n")
    assert by_id(audit_mod.audit(root))["example-in-sync"].status == audit_mod.FAIL
    root = make_repo(tmp_path, env_text="A=1\n", example_text="A=x\nB=y\n")
    assert by_id(audit_mod.audit(root))["example-in-sync"].status == audit_mod.WARN


def test_score_and_grade_math():
    result = audit_mod.AuditResult([
        audit_mod.Check("a", "a", audit_mod.PASS, ""),
        audit_mod.Check("b", "b", audit_mod.FAIL, ""),
    ])
    assert 0 < result.score < 100
    assert result.grade in {"A", "B", "C", "D", "F"}
    assert audit_mod.bar(result.score).count("█") + audit_mod.bar(result.score).count("░") == 20


def test_cli_text_json_and_min_score(tmp_path, capsys):
    root = make_repo(tmp_path, gitignore="")
    result = run(["audit"], cwd=root)
    assert result.returncode == 0
    assert "Health score:" in result.stdout
    assert "grade" in result.stdout

    result = run(["audit", "--format", "json"], cwd=root)
    payload = json.loads(result.stdout)["audit"]
    assert payload["score"] < 100
    assert isinstance(payload["checks"], list)

    assert run(["audit", "--min-score", "99"], cwd=root).returncode == 1


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)
