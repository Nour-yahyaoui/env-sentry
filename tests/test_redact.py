from env_sentry.redact import (
    fingerprint,
    mask_env_text,
    mask_if_secret,
    mask_url_password,
    mask_value,
)


def test_mask_value_keeps_edges():
    masked = mask_value("sk_live_abcdef123456")
    assert masked.startswith("sk_l")
    assert masked.endswith("3456")
    assert "abcdef" not in masked


def test_mask_short_values_fully():
    assert mask_value("abc123") == "****"


def test_mask_env_text_preserves_keys_and_comments():
    text = "# db settings\nDB_PASSWORD=hunter2hunter2hunter2\nPORT=5432\n"
    masked = mask_env_text(text)
    assert "hunter2" not in masked
    assert "DB_PASSWORD=" in masked
    assert "# db settings" in masked


def test_mask_if_secret_only_hides_secrets():
    assert "…" in mask_if_secret("API_KEY", "abcdefghijklmnop")
    assert mask_if_secret("APP_URL", "https://example.com") == "https://example.com"


def test_mask_url_password():
    assert mask_url_password("postgres://admin:s3cret@db:5432/app") == "postgres://admin:****@db:5432/app"


def test_fingerprint_is_stable_and_salted():
    assert fingerprint("abc") == fingerprint("abc")
    assert fingerprint("abc") != fingerprint("abd")
    assert fingerprint("abc") != fingerprint("abc", salt="prod")
    assert len(fingerprint("abc")) == 16
