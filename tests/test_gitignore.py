from pathlib import Path

from env_sentry.gitignore import GitIgnore, Pattern


def rules(tmp_path: Path, text: str) -> GitIgnore:
    (tmp_path / ".gitignore").write_text(text)
    return GitIgnore.load(tmp_path)


def test_exact_filename(tmp_path):
    g = rules(tmp_path, ".env\n")
    assert g.is_ignored(".env")
    assert not g.is_ignored(".env.staging")


def test_glob_patterns(tmp_path):
    g = rules(tmp_path, "*.env\n.env*\n")
    assert g.is_ignored(".env.local")
    assert g.is_ignored("config/prod.env")
    assert not g.is_ignored("config/prod.env.bak")


def test_directory_pattern_ignores_children(tmp_path):
    g = rules(tmp_path, "secrets/\n")
    assert g.is_ignored("secrets/api.env")
    assert g.is_ignored("secrets/nested/deep.env")
    assert g.is_ignored("sub/secrets/x.env")
    assert not g.is_ignored("secrets.txt")


def test_anchored_pattern_only_matches_at_root(tmp_path):
    g = rules(tmp_path, "/config.env\n")
    assert g.is_ignored("config.env")
    assert not g.is_ignored("app/config.env")


def test_negation_wins_when_it_comes_last(tmp_path):
    g = rules(tmp_path, "*.env*\n!.env.example\n")
    assert g.is_ignored(".env.local")
    assert not g.is_ignored(".env.example")


def test_negation_order_matters(tmp_path):
    g = rules(tmp_path, "!.env.example\n*.env*\n")
    assert g.is_ignored(".env.example")


def test_comments_and_blank_lines_are_skipped(tmp_path):
    g = rules(tmp_path, "# a comment\n\n.env\n")
    assert len(g) == 1
    assert g.is_ignored(".env")


def test_double_star(tmp_path):
    g = rules(tmp_path, "**/secrets/*.env\n")
    assert g.is_ignored("a/b/secrets/key.env")


def test_question_mark_and_brackets(tmp_path):
    g = rules(tmp_path, "key?.env\nslot[0-9].env\n")
    assert g.is_ignored("key1.env", is_dir=False)
    assert not g.is_ignored("key12.env", is_dir=False)
    assert g.is_ignored("slot5.env", is_dir=False)
    assert not g.is_ignored("slotx.env", is_dir=False)


def test_nested_gitignore_applies_to_its_subtree(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / ".gitignore").write_text("*.env\n")
    g = GitIgnore.load(tmp_path)
    assert g.is_ignored("app/local.env")
    assert not g.is_ignored("local.env")


def test_pattern_objects_expose_flags():
    p = Pattern("!keep.env")
    assert p.negated is True
    d = Pattern("build/")
    assert d.dir_only is True
