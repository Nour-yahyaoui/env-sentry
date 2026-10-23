"""Allow ``python -m env_sentry`` as an alias for the CLI."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
