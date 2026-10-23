import stat
import subprocess
import sys

import pytest

from env_sentry import templates


def run(args, cwd):
    return subprocess.run([sys.executable, "-m", "env_sentry.cli", *args],
                          cwd=cwd, capture_output=True, text=True)


def test_templates_render_and_validate(tmp_path):
    for name in templates.names():
        body = templates.render(name)
        assert "=" in body
        assert not body.startswith(" ")
    with pytest.raises(ValueError):
        templates.render("cobol")


def test_init_with_template(tmp_path):
    result = run(["init", "--template", "django"], cwd=tmp_path)
    assert result.returncode == 0
    text = (tmp_path / ".env.example").read_text()
    assert "DJANGO_SETTINGS_MODULE" in text
    assert "SECRET_KEY=your_django_secret_key_here" in text


def test_init_existing_example_is_left_alone(tmp_path):
    (tmp_path / ".env.example").write_text("KEEP=me\n")
    result = run(["init"], cwd=tmp_path)
    assert "already exists" in result.stdout
    assert (tmp_path / ".env.example").read_text() == "KEEP=me\n"

    run(["init", "--force", "--template", "node"], cwd=tmp_path)
    assert "NODE_ENV" in (tmp_path / ".env.example").read_text()


def test_init_list_templates(tmp_path):
    result = run(["init", "--list-templates"], cwd=tmp_path)
    assert "fastapi" in result.stdout
    assert "nextjs" in result.stdout


def test_init_create_env_with_private_permissions(tmp_path):
    result = run(["init", "--create-env"], cwd=tmp_path)
    assert result.returncode == 0
    env = tmp_path / ".env"
    assert env.exists()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_init_gitignore_variants_and_no_gitignore(tmp_path):
    run(["init"], cwd=tmp_path)
    text = (tmp_path / ".gitignore").read_text()
    assert ".env\n" in text
    assert ".env.local" in text
    assert ".env.example" not in text.split("\n")  # templates are committed

    (tmp_path / ".gitignore").write_text("")
    run(["init", "--no-gitignore", "--force"], cwd=tmp_path)
    assert (tmp_path / ".gitignore").read_text() == ""


def test_init_respects_existing_glob(tmp_path):
    (tmp_path / ".gitignore").write_text(".env*\n!.env.example\n")
    result = run(["init"], cwd=tmp_path)
    assert "already git-ignored" in result.stdout
    assert (tmp_path / ".gitignore").read_text() == ".env*\n!.env.example\n"


def test_init_unknown_template(tmp_path):
    assert run(["init", "--template", "nope"], cwd=tmp_path).returncode == 2
