"""
Value masking helpers.

Used by `diff`, `export --redact`, `stats` and anywhere a value might end up
in a log, a ticket or a screenshot. The rule is simple: keep a short prefix
and suffix so humans can still tell two values apart, never reveal the middle.
"""

from __future__ import annotations

import re
from typing import Optional

from .envfile import EnvFile, Entry

MASK = "****"


def mask_value(value: str, visible: int = 4) -> str:
    """``sk_live_abcdef123456`` -> ``sk_l…3456``."""
    if not value:
        return ""
    if len(value) <= visible * 2:
        return MASK
    return f"{value[:visible]}…{value[-visible:]}"


def mask_if_secret(key: str, value: str, visible: int = 4) -> str:
    """Mask only values whose key looks secret-ish; leave URLs/ports readable."""
    from .detect import SECRET_KEY_HINTS

    if SECRET_KEY_HINTS.search(key) or len(value) >= 24:
        return mask_value(value, visible)
    return value


def mask_env_text(text: str, visible: int = 4) -> str:
    """Return the same .env file with every value masked, structure intact."""
    env = EnvFile.parse(text)
    out = []
    for line in env.lines:
        if isinstance(line, Entry):
            out.append(f"{'export ' if line.export else ''}{line.key}={mask_value(line.value, visible)}")
        else:
            out.append(line)
    return "\n".join(out) + "\n" if out else ""


def mask_url_password(url: str) -> str:
    """``postgres://user:pw@host/db`` -> ``postgres://user:***@host/db``."""
    return re.sub(r"(://[^:/@\s]+:)([^@/\s]+)(@)", r"\1****\3", url)


def fingerprint(value: str, salt: Optional[str] = None) -> str:
    """Stable short hash of a secret, safe to commit or share for comparison."""
    import hashlib
    import hmac

    payload = (salt or "").encode() + value.encode()
    return hmac.new(b"env-sentry", payload, hashlib.sha256).hexdigest()[:16]
