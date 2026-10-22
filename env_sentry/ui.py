"""
Terminal output helpers for env-sentry.

Everything here is dependency-free: plain ANSI escape codes, switched off
automatically when stdout is not a TTY, or when ``NO_COLOR`` is set in the
environment (see https://no-color.org). ``--color=always`` forces it back on.
"""

from __future__ import annotations

import os
import sys

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

_CODES = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "grey": "\033[90m",
}

SYMBOLS = {
    "ok": "✅",
    "warn": "⚠️ ",
    "error": "❌",
    "info": "ℹ️ ",
    "bug": "🚨",
    "lock": "🔒",
    "bullet": "  •",
}


def auto_color() -> bool:
    """Decide whether colour should be used by default."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        return sys.stdout.isatty()
    except Exception:  # pragma: no cover - exotic stdout objects
        return False


class UI:
    """Small facade over print() that keeps output consistent and colourful."""

    def __init__(self, color: "bool | None" = None, quiet: bool = False) -> None:
        self.color = auto_color() if color is None else bool(color)
        self.quiet = quiet

    # -- low level ---------------------------------------------------
    def paint(self, text: str, color: str = "", bold: bool = False) -> str:
        if not self.color:
            return text
        code = _CODES.get(color, "")
        prefix = (BOLD if bold else "") + code
        return f"{prefix}{text}{RESET}" if prefix else text

    def write(self, text: str = "", *, force: bool = False) -> None:
        if self.quiet and not force:
            return
        print(text)

    # -- semantic helpers --------------------------------------------
    def header(self, text: str) -> None:
        self.write(self.paint(text, "cyan", bold=True))

    def ok(self, text: str) -> None:
        self.write(f"{SYMBOLS['ok']}  {self.paint(text, 'green')}")

    def warn(self, text: str) -> None:
        self.write(f"{SYMBOLS['warn']} {self.paint(text, 'yellow')}")

    def error(self, text: str) -> None:
        self.write(f"{SYMBOLS['error']} {self.paint(text, 'red')}")

    def info(self, text: str) -> None:
        self.write(f"{SYMBOLS['info']} {text}")

    def bullet(self, text: str, color: str = "grey") -> None:
        self.write(f"   - {self.paint(text, color)}")

    def detail(self, text: str) -> None:
        """Secondary, dimmed explanatory text."""
        self.write(self.paint(f"   {text}", "grey"))


ui = UI()
