import json
import subprocess
import sys

from env_sentry import diffing
from env_sentry.envfile import EnvFile


def changes(left_text, right_text, include_same=False):
    return diffing.compare(EnvFile.parse(left_text), EnvFile.parse(right_text), include_same)


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_detects_added_removed_changed():
    result = changes("A=1\nB=old-value-123456\nC=3\n", "A=1\nB=new-value-123456\nD=4\n")
    kinds = {change.key: change.kind for change in result}
    assert kinds == {"B": diffing.CHANGED, "C": diffing.REMOVED, "D": diffing.ADDED}


def test_values_are_masked_by_default():
    result = changes("SECRET=supersecretvalue1\n", "SECRET=supersecretvalue2\n")
    rendered = result[0].render()
    assert "supersecretvalue" not in rendered
    assert "→" in rendered
    assert "supersecretvalue1" in result[0].render(show_values=True)


def test_show_same():
    result = changes("A=1\n", "A=1\n", include_same=True)
    assert result[0].kind == diffing.SAME


def test_order_is_stable():
    result = changes("A=1\nB=2\nC=3\n", "A=9\nB=2\nC=8\n")
    assert [change.key for change in result] == ["A", "C"]


def test_summary_and_counts():
    result = changes("A=1\nB=2\n", "A=2\nC=3\n")
    assert "1 added" in diffing.summary(result)
    assert diffing.counts(result)[diffing.CHANGED] == 1


def test_cli_text_and_json(tmp_path):
    (tmp_path / ".env").write_text("API_KEY=sk_live_abcdefgh12345678\nOLD=1\n")
    (tmp_path / ".env.prod").write_text("API_KEY=sk_live_abcdefgh99999999\nNEW=2\n")

    result = run(["diff", ".env", ".env.prod"], cwd=tmp_path)
    assert result.returncode == 0
    assert "sk_live_abcdefgh" not in result.stdout
    assert "API_KEY" in result.stdout
    assert "1 added, 1 removed, 1 changed" in result.stdout

    result = run(["diff", ".env", ".env.prod", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["counts"]["changed"] == 1
    assert "sk_live_abcdefgh12345678" not in result.stdout


def test_cli_fail_on_diff_and_missing_file(tmp_path):
    (tmp_path / "a.env").write_text("A=1\n")
    (tmp_path / "b.env").write_text("A=2\n")
    assert run(["diff", "a.env", "b.env", "--fail-on-diff"], cwd=tmp_path).returncode == 1
    (tmp_path / "b.env").write_text("A=1\n")
    assert run(["diff", "a.env", "b.env", "--fail-on-diff"], cwd=tmp_path).returncode == 0
    assert run(["diff", "a.env", "nope.env"], cwd=tmp_path).returncode == 2


def test_cli_keys_only(tmp_path):
    (tmp_path / "a.env").write_text("A=1\n")
    (tmp_path / "b.env").write_text("A=1\nB=2\n")
    result = run(["diff", "a.env", "b.env", "--keys-only"], cwd=tmp_path)
    assert "+ B" in result.stdout
