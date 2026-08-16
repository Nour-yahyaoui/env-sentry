# 🛡️ env-sentry

**Stop leaking secrets in `.env` files. Zero dependencies, one command.**

[![PyPI](https://img.shields.io/badge/pip%20install-env--sentry-blue)](https://pypi.org/project/env-sentry/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](pyproject.toml)

Every project with a `.env` file eventually has one of these moments:

- Someone's `.env` isn't in `.gitignore` and real secrets get pushed to GitHub.
- `.env.example` drifts out of sync, and a new teammate spends 20 minutes figuring out which env vars they're missing.
- A Stripe key or AWS credential gets hardcoded "just for testing" and never gets cleaned up.

`env-sentry` is a tiny CLI that catches all three, in one command, with **no dependencies to install**.

---

## Install

```bash
pip install env-sentry
```

## Quick start

```bash
# Scaffold .env.example and make sure .env is git-ignored
env-sentry init

# Compare .env against .env.example, flag drift and leaked secrets
env-sentry check

# Regenerate .env.example from .env (values are redacted, never copied)
env-sentry sync

# Scan the whole repo for hardcoded API keys, tokens, and private keys
env-sentry scan
```

### Example output

```
$ env-sentry check

❌ Keys in .env but missing from .env.example:
   - STRIPE_SECRET_KEY
   - DATABASE_URL

🚨 .env.example may contain REAL secret values, not placeholders:
   - OLD_API_KEY

🚨 '.env' does not appear to be listed in .gitignore!
   Anyone who commits will leak real secrets. Run `env-sentry init` to fix this.
```

```
$ env-sentry scan

config.py:14  AWS Access Key
config.py:14  Suspicious value for 'AWS_SECRET'
notes.txt:3   GitHub Token

🚨 3 potential secret(s) found. Review before committing/pushing.
```

---

## What it checks for

| Command | What it does |
|---|---|
| `init` | Creates `.env.example` if missing, adds `.env` to `.gitignore` |
| `check` | Diffs `.env` vs `.env.example`, flags real secrets accidentally left in the example file, confirms `.env` is git-ignored |
| `sync` | Rewrites `.env.example` from `.env`'s keys with placeholder values — your real secrets never touch the example file |
| `scan` | Walks the repo looking for AWS keys, GitHub/Slack tokens, Stripe live keys, private key blocks, JWTs, and suspicious `KEY=value` pairs |

Exit codes are non-zero on any issue found, so it's a one-line addition to CI or a pre-commit hook:

```yaml
# .github/workflows/tests.yml
- run: pip install env-sentry && env-sentry check && env-sentry scan
```

```bash
# pre-commit hook
env-sentry scan || exit 1
```

---

## Why not just use `git-secrets` / `truffleHog` / `detect-secrets`?

Those are great, heavier tools for deep git-history scanning. `env-sentry` is intentionally small: it's the **5-second daily check**, not a security audit platform. No config file, no dependencies, no setup — just an honest answer to "did I mess up my `.env` today?"

---

## "env-sentry is not recognized as a command"

This happens when pip installs the executable into a folder that isn't on your system PATH yet — pip usually warns you about this during install (`WARNING: The script env-sentry.exe is installed in '...' which is not on PATH`).

**Quick workaround (works immediately, no setup):**
```bash
python -m env_sentry.cli --version
```
Use `python -m env_sentry.cli <command>` in place of `env-sentry <command>` any time.

**Permanent fix on Windows:**
1. Copy the exact folder path from pip's warning message (something like `C:\Users\<you>\AppData\Local\Python\pythoncore-3.x\Scripts`)
2. Press the Windows key, search **"Edit environment variables for your account"**, open it
3. Under **User variables**, select **Path** → **Edit** → **New** → paste the folder path → OK on everything
4. **Close every open terminal window completely** (not just the tab — PATH only reloads for new windows)
5. Open a fresh terminal and run `env-sentry --version` — it should now work directly

**Permanent fix on macOS/Linux:**
Add pip's user script directory to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.):
```bash
export PATH="$HOME/.local/bin:$PATH"
```
Then run `source ~/.zshrc` (or restart your terminal).

---

## Changelog

- **0.1.4** — `scan` now covers `.html`, `.vue`, `.svelte`, `.xml`, `.md`, `.mjs`, `.cjs` files, and `.env.local` / `.env.production` / any `.env.*` variant — these were previously invisible to the scanner
- **0.1.3** — `--version` now shows the author; `check` respects a custom `--env` path when checking `.gitignore` instead of always assuming `.env`
- **0.1.2** — `check` no longer claims things are "in sync" when `.env` doesn't exist yet
- **0.1.1** — Fixed false positives on token-count variables (`max_tokens`, `use_token`, etc.) and on env-var lookups like `os.environ.get("API_KEY")` — only real hardcoded string literals get flagged now
- **0.1.0** — Initial release: `init`, `check`, `sync`, `scan`

---

## Contributing

Issues and PRs welcome. The whole tool is a single ~250 line file (`env_sentry/cli.py`) on purpose — keep it that way.

## License

MIT

---

Built by [Nour Yahyaoui](https://github.com/Nour-yahyaoui).
