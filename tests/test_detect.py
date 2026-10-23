from env_sentry import detect
from env_sentry.detect import AllowList, Finding, scan_text, shannon_entropy


def rules(text, path="app.py"):
    return [f.rule for f in scan_text(text, path=path)]


def test_aws_key_detected_as_critical():
    findings = scan_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    assert findings
    assert findings[0].rule == "AWS Access Key"
    assert findings[0].severity == detect.CRITICAL


def test_github_fine_grained_pat():
    token = "github_pat_" + "A1b2C3d4" * 8
    assert "GitHub Token" in rules(f'TOKEN="{token}"')


def test_private_key_block():
    assert "Private Key Block" in rules("-----BEGIN RSA PRIVATE KEY-----\nabc\n")


def test_jwt_detected():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop"
    assert "JWT" in rules(jwt)


def test_credentials_in_url():
    assert "Basic Auth URL" in rules("DATABASE_URL=postgres://admin:s3cretpass@db.example.com/app")


def test_slack_and_stripe_and_openai():
    slack = "xoxb-" + "1234567890-" * 3
    assert "Slack Token" in rules(slack)
    assert "Stripe Live Key" in rules('STRIPE_KEY = "sk_live_' + "a" * 24 + '"')
    assert "OpenAI Key" in rules('OPENAI_API_KEY = "sk-proj-' + "a" * 32 + '"')


def test_stripe_not_reported_as_openai():
    findings = scan_text('K = "sk_live_' + "a" * 24 + '"')
    assert "OpenAI Key" not in [f.rule for f in findings]


def test_discord_and_telegram():
    assert "Telegram Bot Token" in rules("bot 123456789:AA" + "b" * 33)
    webhook = "https://discord.com/api/webhooks/123456789012345678/" + "x" * 64
    assert "Discord Webhook" in rules(webhook)


def test_placeholder_values_are_not_flagged():
    findings = scan_text('API_KEY = "your_api_key_here"\nSECRET = "<token>"\n')
    assert findings == []


def test_code_expressions_are_not_flagged():
    findings = scan_text(
        'API_KEY = os.environ["API_KEY"]\n'
        "SECRET = get_secret_from_vault()\n"
        'AUTH = str(os.getenv("AUTH"))\n'
    )
    assert findings == []


def test_counts_are_not_flagged():
    findings = scan_text(
        "max_tokens = 4096\n"
        "token_count = 9001\n"
        "num_keys = 4\n"
        "secret_length = 64\n"
        "password_required = True\n"
    )
    assert findings == []


def test_env_file_unquoted_value_detected():
    findings = scan_text("DB_PASSWORD=hunter2hunter2\n", path=".env", is_env_file=True)
    assert findings
    assert findings[0].rule == "Suspicious value for 'DB_PASSWORD'"


def test_ignore_marker_suppresses_line():
    findings = scan_text('K = "AKIAIOSFODNN7EXAMPLE"  # env-sentry:ignore\n')
    assert findings == []


def test_allowlist_by_value_rule_and_path():
    finding = Finding(path="a.py", line=1, column=1, rule="GitHub Token", severity=detect.HIGH,
                      value="ghp_" + "x" * 36)
    assert AllowList(["ghp_" + "x" * 36]).allows(finding)
    assert AllowList(["rule:GitHub Token"]).allows(finding)
    assert AllowList(["path:*.py"]).allows(finding)
    assert not AllowList(["something-else"]).allows(finding)


def test_findings_are_redacted():
    finding = Finding(path="a.py", line=1, column=1, rule="X", severity=detect.HIGH,
                      value="sk_live_abcdefghijklmnop")
    assert "sk_live_abcdefghijklmnop" not in finding.redacted()
    assert finding.redacted().startswith("sk_l")
    assert "value" not in finding.to_dict()


def test_entropy():
    assert shannon_entropy("aaaaaaaa") == 0
    assert shannon_entropy("aB3$xY9qLm2") > 3.0


def test_min_severity_filtering(tmp_path):
    (tmp_path / "a.py").write_text('K = "sk_test_' + "a" * 24 + '"\n')
    all_findings = detect.scan_path(tmp_path, min_severity=detect.LOW)
    high_findings = detect.scan_path(tmp_path, min_severity=detect.CRITICAL)
    assert all_findings
    assert not high_findings


def test_gitignored_files_are_skipped_unless_requested(tmp_path):
    (tmp_path / ".gitignore").write_text(".env\n")
    (tmp_path / ".env").write_text('SECRET_KEY = "' + "a" * 32 + '"\n')
    (tmp_path / "app.py").write_text("x = 1\n")

    assert detect.scan_path(tmp_path) == []
    assert detect.scan_path(tmp_path, include_ignored=True)


def test_documentation_urls_are_not_flagged(tmp_path):
    findings = scan_text(
        "DATABASE_URL=postgres://user:password@localhost:5432/app\n"
        "REDIS_URL=redis://localhost:6379\n"
        "API_KEY=your_api_key_here\n"
    , is_env_file=True)
    assert findings == []


def test_numeric_config_keys_are_not_generated():
    from env_sentry.gensecrets import is_secret_key

    assert is_secret_key("API_KEY")
    assert is_secret_key("DB_PASSWORD")
    assert not is_secret_key("ACCESS_TOKEN_EXPIRE_MINUTES")
    assert not is_secret_key("MAX_TOKENS")
    assert not is_secret_key("JWT_SECRET_URL")
    assert not is_secret_key("APP_NAME")
