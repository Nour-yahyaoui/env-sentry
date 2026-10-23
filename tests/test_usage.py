import json
import subprocess
import sys

from env_sentry import usage


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_python_references(tmp_path):
    write(tmp_path, "app.py",
          'import os\n'
          'a = os.environ["DB_URL"]\n'
          'b = os.environ.get("API_KEY")\n'
          'c = os.getenv("SECRET_TOKEN")\n'
          'd = os.environ["PATH"]\n')
    write(tmp_path, ".env", "DB_URL=1\nAPI_KEY=2\nUNUSED=3\n")
    report = usage.analyse(tmp_path)
    assert set(report.used_keys()) == {"DB_URL", "API_KEY"}
    assert report.unused_keys() == ["UNUSED"]
    assert report.undefined_keys() == ["SECRET_TOKEN"]
    assert report.reference_count("DB_URL") == 1


def test_node_go_ruby_php_references(tmp_path):
    write(tmp_path, "app.ts", "const a = process.env.NODE_KEY;\nconst b = process.env['OTHER_KEY'];\n")
    write(tmp_path, "main.go", 'os.Getenv("GO_KEY")\n')
    write(tmp_path, "app.rb", 'ENV["RUBY_KEY"]\n')
    write(tmp_path, "app.php", "getenv('PHP_KEY');\n")
    write(tmp_path, ".env", "NODE_KEY=1\n")
    report = usage.analyse(tmp_path)
    assert {"OTHER_KEY", "GO_KEY", "RUBY_KEY", "PHP_KEY"} <= set(report.undefined_keys())


def test_shell_interpolation_and_noise(tmp_path):
    write(tmp_path, "run.sh", "echo ${APP_ENV:-dev}\necho $HOME\necho ${MISSING_VAR}\n")
    write(tmp_path, ".env", "APP_ENV=dev\n")
    report = usage.analyse(tmp_path)
    assert report.used_keys() == ["APP_ENV"]
    assert report.undefined_keys() == ["MISSING_VAR"]


def test_env_files_are_not_scanned_for_references(tmp_path):
    write(tmp_path, ".env", "A=1\nB=$A\n")
    report = usage.analyse(tmp_path)
    assert report.undefined_keys() == []
    assert report.unused_keys() == ["A", "B"]


def test_ignore_keys_and_exclusions(tmp_path):
    write(tmp_path, "app.py", "os.getenv('IGNORED_KEY')\nos.getenv('REAL_KEY')\n")
    write(tmp_path, ".env", "")
    report = usage.analyse(tmp_path, ignore={"IGNORED_KEY"})
    assert report.undefined_keys() == ["REAL_KEY"]

    write(tmp_path, "skipme.py", "os.getenv('SKIP_KEY')\n")
    report = usage.analyse(tmp_path, exclude=["skipme.py"])
    assert "SKIP_KEY" not in report.references


def test_cli_output_and_fail_on(tmp_path):
    write(tmp_path, "app.py", 'import os\nos.environ["USED_KEY"]\n')
    write(tmp_path, ".env", "USED_KEY=1\nDEAD_KEY=2\n")

    result = run(["usage"], cwd=tmp_path)
    assert result.returncode == 0
    assert "DEAD_KEY" in result.stdout

    result = run(["usage", "--fail-on", "unused"], cwd=tmp_path)
    assert result.returncode == 1

    result = run(["usage", "--format", "json"], cwd=tmp_path)
    payload = json.loads(result.stdout)
    assert payload["unused"] == ["DEAD_KEY"]
    assert payload["used"] == ["USED_KEY"]

    result = run(["usage", "--list-used"], cwd=tmp_path)
    assert "1 reference" in result.stdout

    assert run(["usage", "--env", "missing.env"], cwd=tmp_path).returncode == 2


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)
