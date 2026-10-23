# 🛡️ env-sentry

**The zero-dependency `.env` toolkit: lint it, diff it, audit it, scan for leaks, generate real secrets — and keep them out of git.**

[![PyPI](https://img.shields.io/badge/pip%20install-env--sentry-blue)](https://pypi.org/project/env-sentry/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-211%20passing-brightgreen)](tests/)

Every project with a `.env` file eventually has one of these moments:

- Someone's `.env` isn't in `.gitignore` and real secrets get pushed to GitHub.
- `.env.example` drifts out of sync, and a new teammate spends 20 minutes figuring out which env vars they're missing.
- A Stripe key or AWS credential gets hardcoded "just for testing" and never gets cleaned up.
- A key is deleted from `.env` — but it's still sitting in git history forever.

`env-sentry` is a single CLI that catches all four, plus the everyday annoyances in between — **with no dependencies to install**.

---

## Install

```bash
pip install env-sentry
```

```bash
env-sentry --version              # env-sentry 1.0.0 — built by Nour Yahyaoui
python -m env_sentry --version    # same thing, if the script isn't on your PATH
```

Works on Python 3.8+ on Linux, macOS and Windows. No third-party packages, ever.

## 60-second quick start

```bash
# 1. Scaffold .env.example from a stack template + git-ignore every .env variant
env-sentry init --template fastapi

# 2. Seed .env from the template and generate strong values for its secrets
env-sentry gen

# 3. Confirm everything is in sync and nothing is leaking
env-sentry check && env-sentry scan

# 4. Score it, then see which keys nothing actually uses
env-sentry audit
env-sentry usage
```

Two commands in and you already have a real `.env`: `gen` copies the
template's non-secret defaults (names, ports, URLs) and replaces every
`your_*_here` credential with a CSPRNG value.

---

## Commands at a glance

| Command | What it does |
|---|---|
| `init` | Create `.env.example` (optionally from a **stack template**), add `.env*` to `.gitignore`, optionally create a mode-600 `.env` |
| `check` | Diff `.env` vs `.env.example`, flag leaked secrets in the template, duplicate keys, empty values, and confirm `.env` is git-ignored |
| `sync` | Regenerate `.env.example` from `.env` — comments and order preserved, every value replaced by a context-aware placeholder |
| `lint` | Validate `.env` syntax and style: duplicate keys, unquoted spaces, unterminated quotes, CRLF, BOM, key naming |
| `scan` | Find hardcoded secrets: **45+ provider signatures**, entropy heuristics, allowlists, SARIF/JSON/GitHub output |
| `history` | Replay recent git commits and find secrets that were committed and later "removed" |
| `diff` | Compare two env files — values **masked by default**, safe to paste in a PR |
| `merge` | Add missing keys from a template into your `.env` without touching comments or order |
| `prune` | Remove keys nothing references anymore (dry-run by default, keeps a `.bak`) |
| `usage` | Cross-reference `.env` with the code: unused keys and undefined `os.environ` references |
| `gen` | Generate cryptographically strong secrets for empty/placeholder keys (or a passphrase) |
| `audit` | Eleven weighted checks → a 0–100 health score with an A+…F grade |
| `badge` | Render that score as an SVG badge for your README |
| `stats` | Key counts by category, entropy distribution, reused values, weak secrets |
| `export` | Convert `.env` to JSON, YAML, shell, docker-compose, Kubernetes Secret, tfvars, INI, CSV |
| `hooks` | Install a git `pre-commit`/`pre-push` hook (safe append + clean uninstall) |
| `ci` | Print or write a GitHub Actions / GitLab CI / pre-commit config |
| `watch` | Re-run `check` + `scan` every time an env file changes |
| `doctor` | Diagnose your setup: git, hooks, permissions, config, CI wiring |
| `config` | Project defaults via `.env-sentry.json` |
| `completions` | Bash, zsh and fish completions generated from the real CLI |

*Every* command supports `--help` with examples, and most support `--format json` for scripting.

---

## What it catches

### 1. The three classic `.env` disasters

```
$ env-sentry check

❌ Keys in .env but missing from .env.example:
   - STRIPE_SECRET_KEY
   - DATABASE_URL
   Run `env-sentry sync` to add them to the template.

⚠️  2 key(s) in .env have no value:
   - SMTP_PASSWORD

🚨 '.env' does not appear to be listed in .gitignore!
   Anyone who commits will leak real secrets. Run `env-sentry init` to fix this.
```

`check` now understands real `.gitignore` semantics — `*.env`, `.env*`, `/secrets/`, and nested `.gitignore` files all count, so you don't get false alarms (and `.env.staging` isn't silently "covered" by an unrelated `.env` line).

Use it as a CI gate:

```bash
env-sentry check --ci          # warnings become failures
env-sentry check --format json # machine-readable report
```

### 2. Secrets in your source tree

```
$ env-sentry scan

src/config.py:14   CRITICAL AWS Access Key            (AKIA…MPLE)
src/config.py:15   HIGH     Suspicious value for 'AWS_SECRET'
notes/todo.txt:3   CRITICAL GitHub Token              (ghp_…9f2c)
infra/main.tf:22   CRITICAL Private Key Block
scripts/deploy.sh:7 HIGH    Basic Auth URL            (post…/app)

❌ 5 potential secret(s) found (3 critical, 2 high). Review before committing/pushing.
```

Detects (among others): AWS, Google/Firebase, Azure, DigitalOcean, Cloudflare, Heroku, GitHub, GitLab, Bitbucket, Stripe, Square, Braintree, Slack, Discord, Telegram, Twilio, SendGrid, Mailgun, Mailchimp, OpenAI, Anthropic, Hugging Face, Replicate, Groq, Perplexity, OpenRouter, npm, PyPI, Shopify, Datadog, New Relic, Postman, Sentry DSN, Supabase, Vercel, private key blocks, JWTs, bearer tokens, credentials in URLs — plus an entropy heuristic for tokens nobody has a signature for yet.

Every finding has a **severity** so you can gate precisely:

```bash
env-sentry scan . --min-severity high --fail-on critical
env-sentry scan . --staged                  # fast pre-commit mode
env-sentry scan . --include-ignored         # also check git-ignored files
env-sentry scan . --format sarif -o out.sarif   # GitHub code scanning
env-sentry scan . --format github           # inline PR annotations
```

**False positives are handled properly:** placeholder values, `os.environ[...]` lookups, `max_tokens`-style counts, `get_token()` calls, documentation URLs like `postgres://user:password@localhost/db`, `${VAR}` templates and test fixtures are ignored. When you *do* need an exception, use either an inline marker or an allowlist:

```python
DEMO_KEY = "AKIAIOSFODNN7EXAMPLE"  # env-sentry:ignore
```

```gitignore
# .env-sentry-allow
rule:Stripe Test Key
path:tests/fixtures/*
sk_live_the_one_that_is_intentionally_public
```

### 3. Secrets that are already in git history

Deleting a key does not delete it from history. `env-sentry history` replays recent diffs and tells you exactly what is still recoverable:

```
$ env-sentry history --list-files

⚠️  Env-like files that were committed at some point:
   - .env

1d80b44f7a  2025-04-18  .env:1  Stripe Live Key  (nour)
❌ 1 secret(s) found in git history.
   Rotate the credentials — they are recoverable with `git show`.
```

### 4. Keys nothing uses, and variables that don't exist

```
$ env-sentry usage

12 key(s) in .env
⚠️  2 key(s) defined but never referenced in code:
   - LEGACY_API_KEY
   - OLD_S3_BUCKET
❌ 1 key(s) referenced in code but missing from .env:
   - REDIS_URL
```

Understands Python, Node/Deno/Bun, Go, Ruby, PHP, Java/Kotlin, Rust, C#, shell scripts and `${VAR:-default}` interpolation in compose files.

### 5. A file that doesn't even parse

```
$ env-sentry lint --strict

  ERROR   line 4    DUP already defined on line 3; the last value wins  [duplicate-key]
  ERROR   line 5    value for SPACE contains whitespace and is not quoted  [unquoted-space]
  WARNING line 6    file does not end with a newline  [eof-newline]
3 error(s), 1 warning(s), 0 note(s) in 1 file(s)
```

---

## Audit score, badge, and stats

```
$ env-sentry audit

✅ .env exists                        .env found with 14 key(s)
✅ .env.example exists                .env.example found
✅ Template covers every key          template and local keys match
✅ .env is git-ignored                .env matches .gitignore
✅ .env is not tracked by git         no tracked env file
✅ .env never reached git history     no .env commits found
✅ .env is private                    owner-only permissions
✅ No duplicate keys                  keys are unique
⚠️  Secrets are filled in              2 key(s) are empty or still placeholders: API_KEY, JWT_SECRET
   ↳ Run `env-sentry gen` to create strong values
✅ .env.example holds no real secrets template only contains placeholders
✅ .env is well formed                no syntax issues

Health score: 93/100  grade A  [██████████████████░░]
```

Fail CI below a threshold, and drop a badge in your README:

```bash
env-sentry audit --min-score 90
env-sentry badge -o .env-sentry-badge.svg
```

```
$ env-sentry stats

Keys by category
  database         ▇▇ 3
  payments         ▇▇ 2
  auth             ▇ 1
  other            ▇ 8

⚠️  The same value is reused under multiple keys:
   - STRIPE_KEY = API_KEY
```

---

## Generating secrets

```bash
$ env-sentry gen

✅  API_KEY = <generated>  100/100
✅  JWT_SECRET = <generated>  100/100
ℹ️  Generated 2 secret(s) in .env (file permissions set to 600)
```

```bash
env-sentry gen --key DB_PASSWORD --passphrase      # ember-falcon-quartz-tide
env-sentry gen --key HMAC_SALT --charset hex --length 64
env-sentry gen --dry-run --print                   # preview without writing
env-sentry gen --all-keys                          # also fill non-secret empty keys
```

CSPRNG-backed (`secrets`, never `random`), unambiguous alphabets (no `0/O/1/l`), and per-key heuristics: password keys get passphrases, salt/HMAC keys get hex.

---

## Moving data between formats

```bash
env-sentry export --format json
env-sentry export --format k8s --name app-secrets --namespace prod
env-sentry export --format compose --service api
env-sentry export --format shell --prefix APP_
env-sentry export --format yaml --redact       # safe to paste anywhere
```

Supported: `dotenv`, `json`, `yaml`, `shell`, `tfvars`, `ini`, `compose`, `k8s`, `csv`.

## Comparing environments safely

```bash
$ env-sentry diff .env .env.production

--- .env
+++ .env.production
~ API_KEY        sk_l…5678 → sk_l…9999
- OLD            ****
+ NEW            ****

1 added, 1 removed, 1 changed
   values are masked; pass --show-values to reveal them
```

`--keys-only` for a pure key comparison, `--fail-on-diff` to gate CI, `--format json` for tooling.

---

## CI integration in one command

```bash
env-sentry ci --write                 # .github/workflows/env-sentry.yml
env-sentry ci --provider gitlab --write
env-sentry ci --provider pre-commit --write
```

The generated GitHub workflow installs env-sentry, runs `check --ci`, scans with `--fail-on high`, and uploads SARIF so findings appear **inline on the PR diff**.

Prefer a local hook?

```bash
env-sentry hooks install                    # pre-commit, scan --fail-on high
env-sentry hooks install --type pre-push --commands check,scan,audit
env-sentry hooks uninstall                  # removes only env-sentry's block
```

Existing hooks (husky, the `pre-commit` framework, handwritten scripts) are backed up and only appended to with `--force` — never clobbered.

## Project config

Stop repeating flags in every CI step:

```json
// .env-sentry.json
{
  "env": ".env.local",
  "example": ".env.example",
  "exclude": ["tests/fixtures/*", "docs/*"],
  "min_severity": "medium",
  "fail_on": "high",
  "ignore_keys": ["NODE_ENV", "CI"],
  "allowlist": ".env-sentry-allow"
}
```

```bash
env-sentry config --init   # starter file
env-sentry config          # show what is in effect
```

CLI flags always win over config values.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Clean |
| `1` | Issues found (drift, secrets, lint errors, score below `--min-score`, stale template with `--check`) |
| `2` | Usage problem (missing file, not a git repository) |

`--fail-on` (`any`, `critical`, `high`, `medium`, `low`, `never`) tunes when `scan` returns 1.

## Performance notes

- Only text files are read (binary sniffing + 2 MB cap), symlinks are never followed.
- Files excluded by `.gitignore` are skipped: they cannot be committed, so
  flagging your own local `.env` would just make every hook run fail. Use
  `--include-ignored` when you want to audit those files too.
- `--staged` makes pre-commit runs proportional to what you staged, not repo size.
- `history --depth N` bounds the git walk.

## Why not just use `git-secrets` / `truffleHog` / `detect-secrets`?

Those are excellent heavy tools for deep auditing. `env-sentry` is the **whole daily workflow** in one dependency-free binary: scaffolding, drift checks, linting, safe diffs, generation, history scanning, CI wiring and a score you can actually show someone. No config file required, no runtime to install — just an honest answer to "is my `.env` setup safe today?"

## Upgrading from 0.1.x

Everything from 0.1.x still works: `init`, `check`, `sync`, `scan` keep their flags and exit codes, and the old messages are still there (now colourised). New commands are additive. `scan` findings now include a severity and are sorted deterministically.

---

## Development

```bash
git clone https://github.com/nour-yahyaoui/env-sentry
cd env-sentry
pip install -e . pytest
pytest -q
```

Layout:

```
env_sentry/
  cli.py          command wiring and argparse definitions
  envfile.py      comment/quote/multiline preserving .env parser
  detect.py       signature rules, entropy heuristics, allowlists
  scanner.py      filesystem walking, binary detection, gitignore
  gitignore.py    real gitignore pattern matching
  report.py       text/json/sarif/github renderers
  lint.py audit.py diffing.py merge.py usage.py stats.py
  export *        exporters.py, gensecrets.py, history.py, hooks.py
  ci/cfg *        cicd.py, config.py, completions.py, templates.py
  ui.py badge.py redact.py doctor.py watch.py
```

## License

MIT — see [LICENSE](LICENSE).

---

Built by [Nour Yahyaoui](https://github.com/Nour-yahyaoui).
