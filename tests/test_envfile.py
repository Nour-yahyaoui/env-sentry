from env_sentry.envfile import (
    EnvFile,
    is_placeholder,
    key_diff,
    parse_env_file,
    placeholder_for,
)


def test_parses_simple_pairs():
    values = parse_env_file_text("A=1\nB=two\n")
    assert values == {"A": "1", "B": "two"}


def parse_env_file_text(text):
    return EnvFile.parse(text).values()


def test_strips_export_prefix_and_comments():
    env = EnvFile.parse("# lead\nexport TOKEN=abc  # trailing\n\n# tail\n")
    assert env.get("TOKEN") == "abc"
    assert env.entries[0].export is True
    assert env.entries[0].inline_comment == "# trailing"


def test_keeps_quoted_values_verbatim():
    env = EnvFile.parse("""RAW='has # hash and spaces'\nDBL="line1\\nline2"\n""")
    assert env.get("RAW") == "has # hash and spaces"
    assert env.get("DBL") == "line1\nline2"


def test_multiline_quoted_value():
    env = EnvFile.parse('CERT="-----BEGIN-----\nabc\n-----END-----"\nNEXT=1\n')
    assert "abc" in env.get("CERT")
    assert env.get("NEXT") == "1"


def test_duplicate_keys_are_reported():
    env = EnvFile.parse("A=1\nA=2\n")
    assert env.duplicates() == {"A": [1, 2]}
    assert env.get("A") == "1"


def test_empty_values_and_missing_file(tmp_path):
    env = EnvFile.parse("EMPTY=\n")
    assert env.empty_keys() == ["EMPTY"]
    missing = EnvFile.load(tmp_path / "nope.env")
    assert missing.exists is False
    assert missing.entries == []


def test_comment_only_lines_survive_render():
    src = "# hello\nA=1\n\nB=2\n"
    assert EnvFile.parse(src).render() == src


def test_placeholders_never_leak_values():
    env = EnvFile.parse("API_KEY=sk_live_supersecret\nPORT=8080\nDEBUG=true\n")
    rendered = env.render_placeholders()
    assert "sk_live_supersecret" not in rendered
    assert "API_KEY=your_api_key_here" in rendered
    assert "PORT=8080" in rendered
    assert "DEBUG=false" in rendered


def test_is_placeholder():
    for value in ("your_api_key_here", "changeme", "<token>", "${TOKEN}", "dummy", "0"):
        assert is_placeholder(value), value
    assert not is_placeholder("sk_live_9f8a7b6c5d4e3f2a1b")


def test_key_diff_preserves_order():
    only_left, only_right = key_diff(["B", "A", "C"], ["C", "D"])
    assert only_left == ["B", "A"]
    assert only_right == ["D"]


def test_placeholder_for_smart_defaults():
    assert placeholder_for("SMTP_PORT") == "0"
    assert placeholder_for("DATABASE_URL") == "https://example.com"
    assert placeholder_for("CONTACT_EMAIL") == "you@example.com"
    assert placeholder_for("STRIPE_SECRET") == "your_stripe_secret_here"
