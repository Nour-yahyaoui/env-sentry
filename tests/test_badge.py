import subprocess
import sys

from env_sentry import badge


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_colour_thresholds():
    assert badge.colour_for(100) == "#4c1"
    assert badge.colour_for(70) == "#dfb317"
    assert badge.colour_for(10) == "#e05d44"


def test_render_contains_score_and_label():
    svg = badge.render(87)
    assert svg.startswith("<svg")
    assert "87/100" in svg
    assert "env-sentry" in svg
    assert "#97ca00" in svg


def test_render_clamps_and_escapes():
    svg = badge.render(150, label="a & b")
    assert "100/100" in svg
    assert "a &amp; b" in svg


def test_flat_square_has_no_radius_gradient():
    svg = badge.render(55, style="flat-square")
    assert 'rx="0"' in svg
    assert "linearGradient" not in svg


def test_markdown_snippet():
    assert badge.markdown() == "![env-sentry health](.env-sentry-badge.svg)"


def test_cli_writes_badge_with_explicit_score(tmp_path):
    target = tmp_path / "badge.svg"
    result = run(["badge", "--score", "42", "-o", str(target)], cwd=tmp_path)
    assert result.returncode == 0
    assert "42/100" in target.read_text()
    assert "README snippet" in result.stdout


def test_cli_runs_audit_by_default(tmp_path):
    (tmp_path / ".env").write_text("API_KEY=realvalue123456\n")
    (tmp_path / ".env.example").write_text("API_KEY=your_api_key_here\n")
    (tmp_path / ".gitignore").write_text(".env\n")
    target = tmp_path / "b.svg"
    result = run(["badge", "-o", str(target)], cwd=tmp_path)
    assert result.returncode == 0
    assert target.exists()
