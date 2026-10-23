"""
Cryptographically secure value generation.

Uses ``secrets`` (the CSPRNG-backed standard library module), never
``random``. Every character is chosen uniformly, and the alphabets avoid
characters that commonly break shell quoting or URL parsing.
"""

from __future__ import annotations

import secrets
import string
from typing import List

# Deliberately unambiguous: no 0/O, 1/l/I.
ALNUM = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DIGITS = "23456789"
HEX = "0123456789abcdef"
BASE64 = string.ascii_letters + string.digits + "-_"
URLSAFE = string.ascii_letters + string.digits + "-._~"

CHARSETS = {
    "alnum": ALNUM,
    "alpha": ALPHA,
    "hex": HEX,
    "base64": BASE64,
    "urlsafe": URLSAFE,
    "digits": DIGITS,
}

# Small built-in list: enough variety for memorable passphrases without
# shipping a megabyte of wordlist.
WORDS: List[str] = """
acorn amber anchor apple arrow aspen atlas autumn badger basil beacon berry birch
bison blaze bloom bolt boulder breeze brick brook cactus candle canyon cedar chalk
cherry cipher clover cobra comet copper coral cosmos cotton crane crater crystal
dawn delta desert dew dolphin dove dragon drift eagle earth ember emerald falcon
feather fern field finch fjord flame flint forest fox frost galaxy garden garnet
gecko ginger glacier glade globe granite grape harbor hawk hazel heather hedge
heron hill hollow honey horizon ice indigo iris island ivory jade jaguar jasmine
juniper kestrel kite lagoon lake lantern lark lava leaf lemon lichen lilac linen
lion lizard lotus lunar lynx maple marble meadow mesa meteor mint mist mole
monsoon moon moss mountain nectar needle nest nickel night north oak oasis ocean
olive onyx opal orbit orchid osprey otter owl palm panther paper peach pearl
pebble pepper pine planet plum polar pond poppy prairie prism quartz quill rain
raven reed reef ridge river robin rocket root rose ruby ridge sage sail salmon
sand sapphire scout sea shadow shell shore silver sky slate snow solar sparrow
spruce star steel stone storm summit sun swan swift temple thistle thunder tide
timber topaz torch trail tulip tundra turquoise valley vapor velvet vine violet
walnut wave wheat willow wind winter wolf wren yarrow zephyr zinc
""".split()


def generate(
    length: int = 32,
    charset: str = "alnum",
    prefix: str = "",
    suffix: str = "",
) -> str:
    """A random string of ``length`` characters from the named charset."""
    if length < 4:
        raise ValueError("length must be at least 4")
    alphabet = CHARSETS.get(charset)
    if alphabet is None:
        raise ValueError(f"unknown charset: {charset} (choose from {', '.join(CHARSETS)})")
    body = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}{body}{suffix}"


def generate_hex(bytes_count: int = 32) -> str:
    return secrets.token_hex(bytes_count)


def generate_urlsafe(bytes_count: int = 32) -> str:
    return secrets.token_urlsafe(bytes_count)


def passphrase(words: int = 4, separator: str = "-", capitalize: bool = False,
               number: bool = False) -> str:
    """A memorable passphrase such as ``ember-falcon-quartz-tide``."""
    if words < 2:
        raise ValueError("a passphrase needs at least 2 words")
    chosen = [secrets.choice(WORDS) for _ in range(words)]
    if capitalize:
        chosen = [word.capitalize() for word in chosen]
    phrase = separator.join(chosen)
    if number:
        phrase += f"{separator}{secrets.randbelow(9000) + 1000}"
    return phrase


SECRET_WORDS = ("key", "token", "secret", "password", "passwd", "pwd", "auth",
                "credential", "salt", "hmac", "signature", "dsn", "connection")


# Keys that mention a secret word but are really configuration.
CONFIG_SUFFIXES = (
    "minutes", "seconds", "hours", "days", "ttl", "expiry", "expires", "expiration",
    "length", "count", "counts", "size", "sizes", "limit", "limits", "timeout",
    "timeouts", "interval", "port", "ports", "url", "uri", "host", "path", "dir",
    "file", "algorithm", "format", "version", "enabled", "required", "name",
    "type", "prefix", "header", "policy", "mode", "endpoint",
    "tokens", "keys", "secrets", "passwords",
)


def is_secret_key(key: str) -> bool:
    """Does this key plausibly need a generated credential?"""
    lowered = key.lower()
    if lowered.rsplit("_", 1)[-1] in CONFIG_SUFFIXES:
        return False
    if lowered.endswith(tuple("_" + suffix for suffix in CONFIG_SUFFIXES)):
        return False
    return any(word in lowered for word in SECRET_WORDS)


def strength(value: str) -> int:
    """Rough 0-100 strength score, used for friendly feedback."""
    if not value:
        return 0
    from .detect import shannon_entropy

    entropy = shannon_entropy(value) * len(value)
    score = min(100, int(entropy * 1.6))
    if value.lower() in {"password", "changeme", "secret", "admin"}:
        score = min(score, 10)
    return score


def generate_for_key(key: str, length: int = 32, charset: str = "alnum",
                     prefix: str = "") -> str:
    """Pick a sensible generator based on what the key name implies."""
    lowered = key.lower()
    if any(hint in lowered for hint in ("password", "passphrase", "secret_phrase")):
        return passphrase(4)
    if "hex" in lowered or lowered.endswith("_salt"):
        return generate(length=length, charset="hex", prefix=prefix)
    if any(hint in lowered for hint in ("webhook", "signature", "hmac")):
        return generate(length=length, charset="hex", prefix=prefix)
    if any(hint in lowered for hint in ("token", "key", "secret", "password", "pwd")):
        return generate(length=length, charset=charset, prefix=prefix)
    return generate(length=length, charset=charset, prefix=prefix)
