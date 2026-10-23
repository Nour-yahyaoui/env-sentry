"""
Ready-to-commit CI configuration.

`env-sentry ci` prints (or writes) a workflow that fails on leaked secrets and
uploads findings to GitHub code scanning, so reviewers see them inline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

PROVIDERS = ("github", "gitlab", "pre-commit")

DEFAULT_PATHS: Dict[str, str] = {
    "github": ".github/workflows/env-sentry.yml",
    "gitlab": ".gitlab-ci.env-sentry.yml",
    "pre-commit": ".pre-commit-config.yaml",
}

GITHUB = """name: env-sentry

on:
  push:
    branches: [main, master]
  pull_request:

permissions:
  contents: read
  security-events: write

jobs:
  env-sentry:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.x"

      - name: Install env-sentry
        run: pip install env-sentry

      - name: Check .env hygiene
        run: env-sentry check --ci

      - name: Scan for hardcoded secrets
        run: env-sentry scan . --format sarif -o env-sentry.sarif --fail-on high

      - name: Upload SARIF to code scanning
        if: always()
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: env-sentry.sarif
"""

GITLAB = """# .gitlab-ci.yml snippet — include or paste into your existing pipeline.
env-sentry:
  image: python:3.12-slim
  stage: test
  script:
    - pip install env-sentry
    - env-sentry check --ci || true
    - env-sentry scan . --format json -o env-sentry.json --fail-on high
  artifacts:
    when: always
    paths:
      - env-sentry.json
"""

PRECOMMIT = """# Add to .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: env-sentry-scan
        name: env-sentry scan
        entry: env-sentry scan . --fail-on high
        language: system
        pass_filenames: false
      - id: env-sentry-check
        name: env-sentry check
        entry: env-sentry check
        language: system
        pass_filenames: false
"""

TEMPLATES = {"github": GITHUB, "gitlab": GITLAB, "pre-commit": PRECOMMIT}


def render(provider: str = "github") -> str:
    if provider not in TEMPLATES:
        raise ValueError(f"unknown provider: {provider} (choose from {', '.join(PROVIDERS)})")
    return TEMPLATES[provider]


def default_path(provider: str) -> Path:
    return Path(DEFAULT_PATHS[provider])


def write(provider: str = "github", path: str = "", force: bool = False) -> Path:
    target = Path(path) if path else default_path(provider)
    if target.exists() and not force:
        raise FileExistsError(f"{target} already exists (use --force to overwrite)")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(provider))
    return target
