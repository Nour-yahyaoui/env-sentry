import json
import subprocess
import sys

from env_sentry import lint


def codes(text):
    return {issue.code for issue in lint.lint_text(text)}


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_clean_file_has_no_issues():
    assert lint.lint_text("A=1\nB=two\n# comment\n\nC='x y'\n") == []


def test_duplicate_keys():
    issues = lint.lint_text("A=1\nA=2\n")
    assert "duplicate-key" in {i.code for i in issues}
    assert issues[0].line == 2


def test_unquoted_space_and_inline_hash():
    assert "unquoted-space" in codes("A=hello world\n")
    assert "inline-hash" in codes("A=value#fragment\n")


def test_crlf_bom_and_missing_newline():
    assert "crlf" in codes("A=1\r\nB=2\r\n")
    assert "bom" in codes("\ufeffA=1\n")
    assert "eof-newline" in codes("A=1")


def test_unterminated_quote():
    assert "unterminated-quote" in codes('A="oops\n')


def test_multiline_value_is_fine():
    assert lint.lint_text('A="line1\nline2"\n') == []


def test_syntax_error_and_key_style():
    assert "syntax" in codes("not a pair\n")
    assert "key-style" in codes("camelKey=1\n")


def test_no_keys_is_a_warning():
    issues = lint.lint_text("# only comments\n")
    assert [issue.code for issue in issues] == ["no-keys"]
    assert issues[0].level == lint.WARNING


def test_missing_file(tmp_path):
    issues = lint.lint_file(tmp_path / "nope.env")
    assert issues[0].code == "missing-file"


def test_cli_exit_codes_and_json(tmp_path):
    (tmp_path / ".env").write_text("A=1\nA=2\n")
    result = run(["lint"], cwd=tmp_path)
    assert result.returncode == 1
    assert "duplicate-key" in result.stdout

    (tmp_path / ".env").write_text("A=1\n")
    assert run(["lint"], cwd=tmp_path).returncode == 0

    (tmp_path / ".env").write_text("camel=1\n")  # warning only
    assert run(["lint"], cwd=tmp_path).returncode == 0
    assert run(["lint", "--strict"], cwd=tmp_path).returncode == 1

    result = run(["lint", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["files"][".env"][0]["code"] == "key-style"


def test_cli_all_flag(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".env.prod").write_text("A=1\nA=2\n")
    result = run(["lint", "--all"], cwd=tmp_path)
    assert result.returncode == 1
    assert "2 file(s)" in result.stdout
