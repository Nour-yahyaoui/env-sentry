# Changelog

All notable changes to `env-sentry` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## 1.0.0 — the toolkit release

This is the release where env-sentry stops being "a check for `.env`" and
becomes a complete, still-zero-dependency `.env` toolkit. Everything from 0.1.x
keeps working; everything else is additive.

### New commands

- **`lint`** — validate `.env` syntax and style: duplicate keys, stray text,
  unquoted whitespace, inline `#` truncation, unterminated quotes, CRLF
  endings, BOM, missing final newline, non-`SCREAMING_SNAKE` keys.
  `--strict`, `--all`, `--format json`.
- **`diff`** — compare two env files with **values masked by default**.
  `--keys-only`, `--show-values`, `--show-same`, `--fail-on-diff`, JSON.
- **`merge`** — add keys from a template into `.env` without touching comments
  or order. `--overwrite`, `--with-values`, `--only/--skip`, `--dry-run`.
- **`prune`** — delete keys nothing references anymore. Dry-run by default,
  `--from-example`, `--keep` globs, `.env.bak` backup on `--write`.
- **`usage`** — cross-reference `.env` with the code: unused keys and undefined
  environment references across Python, Node, Go, Ruby, PHP, Java, Rust, C#
  and shell/compose interpolation.
- **`gen`** — generate CSPRNG secrets for empty/placeholder keys, with per-key
  heuristics, `--charset`, `--length`, `--prefix`, `--passphrase/--words`,
  `--dry-run`, `--print`, and mode-600 on write.
- **`audit`** — eleven weighted checks (gitignore coverage, tracked file, git
  history, permissions, key parity, duplicates, placeholders, template
  leakage, syntax) → 0–100 score and A+…F grade. `--min-score` CI gate,
  `--all`, JSON.
- **`badge`** — SVG health badge generated locally (flat / flat-square).
- **`stats`** — key counts by category, length and entropy distribution,
  repeated values, weak secrets.
- **`export`** — `.env` → JSON, YAML, shell, tfvars, INI, docker-compose,
  Kubernetes Secret, CSV. `--redact`, `--include/--exclude`, `--prefix`.
- **`history`** — replay recent git commits and find secrets that were
  committed and later removed. `--depth`, `--min-severity`, `--list-files`,
  `--all-files`, JSON.
- **`hooks`** — install a git `pre-commit`/`pre-push` hook with a marked block,
  backups for foreign hooks, clean uninstall, `--commands`.
- **`ci`** — generate GitHub Actions (with SARIF upload), GitLab CI and
  pre-commit configs.
- **`config`** — project defaults from `.env-sentry.json`, with type checking
  and clear warnings.
- **`completions`** — bash/zsh/fish completions generated from the live parser.
- **`watch`** — re-run `check` + high-severity `scan` when env files change.
- **`doctor`** — one-screen diagnosis of python, git, hooks, config,
  permissions and CI wiring, with copy-pasteable fixes.

### Detection engine (`scan`)

- 45+ provider signatures: AWS, Google/Firebase, Azure, DigitalOcean,
  Cloudflare, Heroku, GitHub (including fine-grained PATs), GitLab, Bitbucket,
  Stripe (live/test), Square, Braintree, PayPal, Slack (tokens + webhooks),
  Discord (tokens + webhooks), Telegram, Twilio, SendGrid, Mailgun, Mailchimp,
  OpenAI, Anthropic, Hugging Face, Replicate, Groq, Perplexity, OpenRouter,
  npm, PyPI, Shopify, Datadog, New Relic, Postman, Sentry DSN, Supabase,
  Vercel, private key blocks, JWTs, bearer tokens and credentials in URLs.
- Shannon-entropy heuristic for undocumented token formats.
- Every finding carries a severity (`critical`/`high`/`medium`/`low`), column,
  redacted preview and JSON form.
- `--format text|json|sarif|github`, `--output`, `--min-severity`,
  `--fail-on`, `--allowlist`, `--exclude`, `--extensions`, `--staged`.
- Allowlist file (`.env-sentry-allow`) with `rule:`, `path:` and literal
  entries; inline `env-sentry:ignore` / `nosec` markers.
- Scanner hardening: binary sniffing, 2 MB file cap, symlink safety.

### Improved existing commands

- **`init`** — nine stack templates (`--template`, `--list-templates`),
  `--create-env` (mode-600), `--force`, `--no-gitignore`; `.gitignore` setup
  now covers `.env.local`, `.env.*.local`, `.env.production`, `.env.staging`
  and backs off when a glob already covers `.env`.
- **`check`** — reports duplicate keys and empty values, adds
  `--strict`/`--ci` and `--format json`, and suggests `merge` for missing
  local keys. `.gitignore` matching now implements real git semantics
  (`*.env`, `.env*`, anchored and nested patterns, negation).
- **`sync`** — comment- and order-preserving template regeneration with
  context-aware placeholders; `--check` (CI drift gate), `--merge`,
  `--dry-run`, `--no-header`, idempotent output.
- **`.env` parser** — quotes (single/double with escapes), multi-line values,
  `export` prefixes, inline comments, duplicate detection, round-trip safe.

### Safety and correctness fixes

- `scan` skips `.gitignore`d files (a git-ignored `.env` can't leak, and
  flagging it made every pre-commit run fail); `--include-ignored` audits them.
- Documentation credentials (`postgres://user:password@localhost/...`,
  `your_*_here`, `<placeholder>`, `${VAR}`) no longer raise findings.
- `sync` refuses to wipe a hand-written template when `.env` has no keys, and
  `sync --check` validates key coverage instead of formatting.
- `gen` only fills credential-shaped keys and never touches numeric or
  config-suffixed keys (`MAX_TOKENS`, `ACCESS_TOKEN_EXPIRE_MINUTES`).

### CLI polish

- Colour output with `NO_COLOR`/`FORCE_COLOR` support and `--color`
  `auto|always|never`; `-q/--quiet`.
- `python -m env_sentry` entrypoint.
- Version and author are defined once in `env_sentry/__init__.py`.
- 218 tests, pyflakes-clean package.

## 0.1.4

- `scan` covers `.html`, `.vue`, `.svelte`, `.xml`, `.md`, `.mjs`, `.cjs` and
  `.env.local` / `.env.production` / any `.env.*` variant.

## 0.1.3

- `--version` shows the author; `check` respects a custom `--env` path when
  checking `.gitignore` instead of always assuming `.env`.

## 0.1.2

- `check` no longer claims things are "in sync" when `.env` doesn't exist yet.

## 0.1.1

- Fixed false positives on token-count variables (`max_tokens`, `use_token`, …)
  and on env-var lookups such as `os.environ.get("API_KEY")`.

## 0.1.0

- Initial release: `init`, `check`, `sync`, `scan`.
