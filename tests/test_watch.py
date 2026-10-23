import subprocess
import sys
from pathlib import Path

from env_sentry import watch


def test_files_to_watch(tmp_path):
    (tmp_path / ".env").write_text("A=1\n")
    (tmp_path / ".env.local").write_text("B=2\n")
    (tmp_path / "prod.env").write_text("C=3\n")
    (tmp_path / ".env.bak").write_text("old\n")
    (tmp_path / "notes.txt").write_text("x\n")

    names = [path.name for path in watch.files_to_watch(tmp_path)]
    assert ".env" in names
    assert ".env.bak" not in names
    assert "notes.txt" not in names
    assert "prod.env" in names


def test_snapshot_and_diff(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    before = watch.snapshot([env])
    assert str(env) in before

    env.write_text("A=12\n")
    after = watch.snapshot([env])
    assert watch.diff_snapshots(before, after) == [env]

    assert watch.diff_snapshots(after, watch.snapshot([])) == [env]


def test_wait_for_change_detects_edit():
    state = {"text": "A=1\n", "ticks": 0}

    class FakePath:
        def __init__(self, name):
            self.name = name

        def stat(self):
            class S:
                st_mtime_ns = hash(state["text"])
                st_size = len(state["text"])
            return S()

        def __str__(self):
            return self.name

    def paths():
        return [FakePath(".env")]

    def sleep(_seconds):
        state["ticks"] += 1
        if state["ticks"] == 3:
            state["text"] = "A=2\n"

    changed = watch.wait_for_change(paths, interval=0, sleep=sleep)
    assert changed and str(changed[0]) == ".env"


def test_wait_for_change_timeout():
    class Clock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            self.now += 1.0
            return self.now

    assert watch.wait_for_change(lambda: [], interval=0, timeout=2, sleep=lambda _: None,
                                 clock=Clock()) is None


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_cli_once(tmp_path):
    (tmp_path / ".env").write_text("API_KEY=your_api_key_here\n")
    (tmp_path / ".env.example").write_text("API_KEY=your_api_key_here\n")
    (tmp_path / ".gitignore").write_text(".env\n")
    result = run(["watch", "--once"], cwd=tmp_path)
    assert result.returncode == 0
    assert "Watching" in result.stdout
    assert "in sync" in result.stdout
    assert "No obvious hardcoded secrets" in result.stdout


def test_cli_missing_files(tmp_path):
    result = run(["watch", "--once"], cwd=tmp_path)
    assert result.returncode == 2
