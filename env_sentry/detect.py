"""
Secret detection rules and the scanner that applies them.

Detectors are grouped in three layers:

1. **Signature rules** — well-known token formats (AWS, GitHub, Stripe, OpenAI,
   Slack, private key blocks, ...). High precision, near-zero false positives.
2. **Contextual rules** — a suspicious key name (``password``, ``api_key``, ...)
   assigned a non-placeholder literal.
3. **Entropy heuristics** — long, random-looking literals assigned to a
   secret-ish name, which catches internal/undocumented token formats.

Every finding carries a ``severity`` so CI can fail on ``high`` only.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .envfile import is_placeholder

# ----------------------------------------------------------------------
# severities
# ----------------------------------------------------------------------

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

SEVERITY_RANK = {CRITICAL: 3, HIGH: 2, MEDIUM: 1, LOW: 0}


@dataclass(frozen=True)
class Rule:
    """A named signature for one kind of credential."""

    name: str
    pattern: re.Pattern
    severity: str = HIGH
    provider: str = ""
    value_group: int = 0
    description: str = ""

    def finditer(self, text: str) -> Iterator[re.Match]:
        return self.pattern.finditer(text)


def _rule(name: str, pattern: str, severity: str = HIGH, provider: str = "",
          value_group: int = 0, description: str = "", flags: int = 0) -> Rule:
    return Rule(name, re.compile(pattern, flags), severity, provider or name.split()[0],
                value_group, description)


# ----------------------------------------------------------------------
# signature rules
# ----------------------------------------------------------------------

SIGNATURE_RULES: List[Rule] = [
    # -- cloud ------------------------------------------------------
    _rule("AWS Access Key", r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b", CRITICAL, "AWS",
          description="AWS access key id"),
    _rule("AWS Secret Key",
          r"(?i)aws.{0,20}(?:secret|private).{0,20}?['\"]([A-Za-z0-9/+=]{40})['\"]",
          CRITICAL, "AWS", value_group=1, description="AWS secret access key"),
    _rule("Google API Key", r"\bAIza[0-9A-Za-z\-_]{35}\b", HIGH, "Google"),
    _rule("Google OAuth Secret", r"\bGOCSPX-[0-9A-Za-z\-_]{28}\b", HIGH, "Google"),
    _rule("Firebase Cloud Messaging Key", r"\bAAAA[A-Za-z0-9_-]{7}:[A-Za-z0-9_-]{140}\b",
          HIGH, "Firebase"),
    _rule("DigitalOcean Token", r"\bdop_v1_[a-f0-9]{64}\b", CRITICAL, "DigitalOcean"),
    _rule("Azure Storage Key",
          r"(?i)(?:account[_-]?key|azure)[^\n]{0,20}?['\"]([A-Za-z0-9+/]{86}==)['\"]",
          CRITICAL, "Azure", value_group=1),
    _rule("Heroku API Key", r"\bHRKU-[A-Za-z0-9_-]{32,}\b", HIGH, "Heroku"),
    _rule("Cloudflare API Token", r"\b(?:v1\.0-[A-Za-z0-9_-]{120,}|CFPAT-[A-Za-z0-9_-]{30,})\b",
          HIGH, "Cloudflare"),

    # -- source control ---------------------------------------------
    _rule("GitHub Token",
          r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b",
          CRITICAL, "GitHub"),
    _rule("GitLab Token", r"\bglpat-[A-Za-z0-9_-]{20,}\b", CRITICAL, "GitLab"),
    _rule("Bitbucket App Password", r"\bATBB[A-Za-z0-9]{28,}\b", HIGH, "Bitbucket"),

    # -- payments ---------------------------------------------------
    _rule("Stripe Live Key", r"\b(?:sk|rk)_live_[A-Za-z0-9]{20,}\b", CRITICAL, "Stripe"),
    _rule("Stripe Test Key", r"\b(?:sk|rk)_test_[A-Za-z0-9]{20,}\b", MEDIUM, "Stripe"),
    _rule("Square Access Token", r"\bsq0atp-[A-Za-z0-9_-]{22}\b|\bsq0csp-[A-Za-z0-9_-]{43}\b",
          CRITICAL, "Square"),
    _rule("Braintree Token", r"\baccess_token\$(?:production|sandbox)\$[a-z0-9]{16}\$[a-f0-9]{32}\b",
          HIGH, "Braintree"),
    _rule("PayPal Client Secret", r"\bE[A-Za-z0-9]{79}\b", LOW, "PayPal"),

    # -- messaging --------------------------------------------------
    _rule("Slack Token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", CRITICAL, "Slack"),
    _rule("Slack Webhook",
          r"https://hooks\.slack\.com/services/T[A-Z0-9]{8,}/B[A-Z0-9]{8,}/[A-Za-z0-9]{20,}",
          HIGH, "Slack"),
    _rule("Discord Webhook",
          r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\d{17,20}/[A-Za-z0-9_-]{60,}",
          HIGH, "Discord"),
    _rule("Discord Bot Token",
          r"\b[MNO][A-Za-z0-9_-]{23,25}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,39}\b",
          HIGH, "Discord"),
    _rule("Telegram Bot Token", r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b", HIGH, "Telegram"),
    _rule("Twilio Key", r"\bSK[0-9a-fA-F]{32}\b", HIGH, "Twilio"),
    _rule("SendGrid Key", r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b", CRITICAL, "SendGrid"),
    _rule("Mailgun Key", r"\bkey-[0-9a-zA-Z]{32}\b", HIGH, "Mailgun"),
    _rule("Mailchimp Key", r"\b[0-9a-f]{32}-us\d{1,2}\b", HIGH, "Mailchimp"),

    # -- AI providers -----------------------------------------------
    _rule("OpenAI Key", r"\bsk-(?!(?:live|test)_)(?:proj-)?[A-Za-z0-9_-]{20,}\b", CRITICAL, "OpenAI",
          description="Also matches other sk- prefixed providers"),
    _rule("Anthropic Key", r"\bsk-ant-[A-Za-z0-9_-]{20,}\b", CRITICAL, "Anthropic"),
    _rule("Hugging Face Token", r"\bhf_[A-Za-z0-9]{30,}\b", HIGH, "HuggingFace"),
    _rule("Replicate Token", r"\br8_[A-Za-z0-9]{30,}\b", HIGH, "Replicate"),
    _rule("Groq Key", r"\bgsk_[A-Za-z0-9]{40,}\b", HIGH, "Groq"),
    _rule("Perplexity Key", r"\bpplx-[A-Za-z0-9]{40,}\b", HIGH, "Perplexity"),
    _rule("OpenRouter Key", r"\bsk-or-v1-[a-f0-9]{64}\b", HIGH, "OpenRouter"),

    # -- package registries / ops -----------------------------------
    _rule("npm Token", r"\bnpm_[A-Za-z0-9]{36}\b", HIGH, "npm"),
    _rule("PyPI Token", r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}\b", HIGH, "PyPI"),
    _rule("Shopify Token", r"\bshp(?:at|ca|pa|ss)_[a-fA-F0-9]{32}\b", CRITICAL, "Shopify"),
    _rule("Datadog API Key",
          r"(?i)datadog.{0,20}?['\"]([a-f0-9]{32})['\"]", HIGH, "Datadog", value_group=1),
    _rule("New Relic Key", r"\bNRAK-[A-Z0-9]{27}\b", HIGH, "NewRelic"),
    _rule("Postman Key", r"\bPMAK-[a-f0-9]{24}-[a-f0-9]{34}\b", HIGH, "Postman"),
    _rule("Sentry DSN",
          r"https://[a-f0-9]{32}@(?:o\d+\.)?ingest\.(?:[a-z]+\.)?sentry\.io/\d+",
          MEDIUM, "Sentry"),
    _rule("Supabase Service Key", r"\bsb_secret_[A-Za-z0-9_-]{20,}\b", CRITICAL, "Supabase"),
    _rule("Supabase Publishable Key", r"\bsb_publishable_[A-Za-z0-9_-]{20,}\b", LOW, "Supabase"),
    _rule("Vercel Token", r"\bvercel_[A-Za-z0-9]{24,}\b", HIGH, "Vercel"),

    # -- generic structures -----------------------------------------
    _rule("Private Key Block",
          r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----", CRITICAL, "PKI"),
    _rule("PGP Private Key Block", r"-----BEGIN PGP PRIVATE KEY BLOCK-----", CRITICAL, "PKI"),
    _rule("JWT", r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", MEDIUM,
          "JWT"),
    _rule("Basic Auth URL", r"[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s:/@]{3,}@[^\s/@]+", HIGH,
          "URL", description="Credentials embedded in a connection string"),
    _rule("Bearer Token", r"(?i)authorization\s*[:=]\s*['\"]?bearer\s+([A-Za-z0-9._\-]{20,})",
          HIGH, "HTTP", value_group=1),
    _rule("AWS ARN with Account", r"\barn:aws:iam::\d{12}:user/[\w.-]+", LOW, "AWS"),
]

# ----------------------------------------------------------------------
# contextual detection
# ----------------------------------------------------------------------

SECRET_KEY_HINTS = re.compile(
    r"(secret|token|api[_-]?key|apikey|password|passwd|pwd|access[_-]?key|"
    r"private[_-]?key|auth|credential|client[_-]?secret|session[_-]?id|"
    r"signing[_-]?key|encryption[_-]?key|connection[_-]?string|dsn|"
    r"service[_-]?role|bearer|license[_-]?key|webhook[_-]?secret)",
    re.IGNORECASE,
)

# Names that contain a secret-ish word but are counts, flags or metadata.
NOT_SECRET_HINTS = re.compile(
    r"(max|min|num|count|total|limit|delta|use|avg|is|has|enable|disable|"
    r"ttl|timeout|expire|expiry|expiration|length|len|size|type|name|url|uri|"
    r"header|prefix|suffix|pattern|regex|policy|field|column|label|path|dir|"
    r"format|version|ttl_seconds)[_-]?(tokens?|keys?|secrets?|passwords?|auth)\b|"
    r"\b(tokens?|keys?|secrets?|passwords?|auth)[_-]?(count|total|num|limit|"
    r"length|type|name|ttl|url|header|prefix|path|enabled|required|expiry)\b",
    re.IGNORECASE,
)

# key = "value"  /  key: "value"  /  key: 'value'
ASSIGN_RE = re.compile(
    r"""(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)\s*(?:=|:|=>)\s*
        (?P<quote>['"`])(?P<value>[^'"`\n]{6,})(?P=quote)""",
    re.VERBOSE,
)
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")

MIN_ENTROPY = 3.2
MIN_ENTROPY_LENGTH = 20


def shannon_entropy(text: str) -> float:
    """Bits of entropy per character (0.0 for empty strings)."""
    if not text:
        return 0.0
    counts: Dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _looks_random(value: str) -> bool:
    if len(value) < MIN_ENTROPY_LENGTH:
        return False
    if value.isdigit() or value.replace(".", "", 1).isdigit():
        return False
    if re.fullmatch(r"[a-zA-Z]+", value):
        return False
    has_mixed = bool(re.search(r"[a-z]", value)) and bool(re.search(r"[A-Z0-9]", value))
    return has_mixed and shannon_entropy(value) >= MIN_ENTROPY


def looks_like_secret(key: str, value: str, is_literal: bool = True) -> bool:
    """Contextual heuristic: suspicious name + plausible literal value."""
    if not value or is_placeholder(value):
        return False
    if len(value) < 12:
        return False
    if NOT_SECRET_HINTS.search(key):
        return False
    if not SECRET_KEY_HINTS.search(key):
        return False
    if not is_literal:
        return False
    if value.replace(".", "", 1).isdigit():
        return False
    if re.fullmatch(r"https?://[^:@/\s]+", value):
        return False
    return True


# ----------------------------------------------------------------------
# findings
# ----------------------------------------------------------------------

IGNORE_MARKERS = ("env-sentry:ignore", "env-sentry: allow", "nosec", "gitleaks:allow")


@dataclass
class Finding:
    path: str
    line: int
    column: int
    rule: str
    severity: str
    excerpt: str = ""
    value: str = field(default="", repr=False)

    def redacted(self) -> str:
        """A safe preview of the offending value: ``sk_l…4f9a``."""
        if not self.value:
            return ""
        value = self.value
        if len(value) <= 10:
            return "*" * len(value)
        return f"{value[:4]}…{value[-4:]}"

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "rule": self.rule,
            "severity": self.severity,
            "excerpt": self.excerpt,
            "match": self.redacted(),
        }

    def sort_key(self) -> Tuple[str, int, int]:
        return (self.path, self.line, self.column)


class AllowList:
    """Simple allowlist: literal strings, rule names, glob(ish) paths."""

    def __init__(self, entries: Optional[Iterable[str]] = None) -> None:
        self.literals: List[str] = []
        self.rules: List[str] = []
        self.paths: List[str] = []
        for raw in entries or ():
            entry = raw.strip()
            if not entry or entry.startswith("#"):
                continue
            if entry.startswith("rule:"):
                self.rules.append(entry[len("rule:"):].strip())
            elif entry.startswith("path:"):
                self.paths.append(entry[len("path:"):].strip())
            else:
                self.literals.append(entry)

    @classmethod
    def load(cls, path: Path) -> "AllowList":
        path = Path(path)
        if not path.is_file():
            return cls([])
        return cls(path.read_text(errors="ignore").splitlines())

    def __len__(self) -> int:
        return len(self.literals) + len(self.rules) + len(self.paths)

    def allows(self, finding: Finding) -> bool:
        if finding.rule in self.rules:
            return True
        for pattern in self.paths:
            if Path(finding.path).match(pattern) or finding.path.startswith(pattern.rstrip("*")):
                return True
        return any(literal in finding.value for literal in self.literals)


# ----------------------------------------------------------------------
# scanning
# ----------------------------------------------------------------------

def scan_line_detail(line: str, is_env_file: bool = False) -> List[Tuple[str, str, str, int]]:
    """Scan one line. Returns tuples of (rule, severity, value, column)."""
    found: List[Tuple[str, str, str, int]] = []
    seen: set = set()

    def add(name: str, severity: str, value: str, column: int) -> None:
        key = (name, value)
        if key in seen:
            return
        seen.add(key)
        found.append((name, severity, value, column))

    for rule in SIGNATURE_RULES:
        for match in rule.finditer(line):
            value = ""
            if rule.value_group and rule.value_group <= (match.lastindex or 0):
                value = match.group(rule.value_group) or ""
            else:
                value = match.group(0)
            add(rule.name, rule.severity, value, match.start() + 1)

    if is_env_file:
        env_match = ENV_LINE_RE.match(line)
        if env_match and looks_like_secret(env_match.group(1), _unquote(env_match.group(2))):
            add(f"Suspicious value for '{env_match.group(1)}'", HIGH,
                _unquote(env_match.group(2)), 1)
    else:
        for match in ASSIGN_RE.finditer(line):
            key, value = match.group("key"), match.group("value")
            if looks_like_secret(key, value) or (
                SECRET_KEY_HINTS.search(key) and not is_placeholder(value) and _looks_random(value)
            ):
                add(f"Suspicious value for '{key}'", HIGH, value, match.start() + 1)

        # KEY=value in code files (e.g. .ini/.properties/.yaml style)
        env_match = ENV_LINE_RE.match(line)
        if env_match and not any(f[0].startswith("Suspicious") for f in found):
            key = env_match.group(1)
            value = _unquote(env_match.group(2))
            if looks_like_secret(key, value) and _is_literal_token(value):
                add(f"Suspicious value for '{key}'", HIGH, value, 1)

    return found


LITERAL_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-./+=:$~]{12,}$")


def _is_literal_token(value: str) -> bool:
    """Reject obvious code expressions (``get_token_from_vault()``)."""
    return bool(LITERAL_TOKEN_RE.match(value))


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"', "`"):
        return raw[1:-1]
    return raw.split(" #")[0].strip()


def scan_text(text: str, path: str = "<text>", is_env_file: bool = False,
              allowlist: Optional[AllowList] = None) -> List[Finding]:
    findings: List[Finding] = []
    for index, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        if any(marker in lowered for marker in IGNORE_MARKERS):
            continue
        for rule, severity, value, column in scan_line_detail(line, is_env_file=is_env_file):
            finding = Finding(
                path=path,
                line=index,
                column=column,
                rule=rule,
                severity=severity,
                excerpt=line.strip()[:160],
                value=value,
            )
            if allowlist and allowlist.allows(finding):
                continue
            findings.append(finding)
    return findings


def scan_file(path: Path, allowlist: Optional[AllowList] = None) -> List[Finding]:
    path = Path(path)
    try:
        text = path.read_text(errors="ignore")
    except OSError:
        return []
    is_env = path.name.startswith(".env")
    return scan_text(text, path=str(path), is_env_file=is_env, allowlist=allowlist)


def scan_files(paths: Iterable[Path], allowlist: Optional[AllowList] = None,
               min_severity: str = LOW) -> List[Finding]:
    """Scan an explicit list of files (used by --staged)."""
    threshold = SEVERITY_RANK.get(min_severity, 0)
    findings: List[Finding] = []
    for path in paths:
        for finding in scan_file(Path(path), allowlist=allowlist):
            if SEVERITY_RANK.get(finding.severity, 0) >= threshold:
                findings.append(finding)
    return findings


def scan_path(root: Path, allowlist: Optional[AllowList] = None,
              min_severity: str = LOW, extensions: Optional[Sequence[str]] = None,
              exclude: Sequence[str] = ()) -> List[Finding]:
    """Walk ``root`` and return findings at or above ``min_severity``."""
    from .scanner import iter_files  # local import avoids a cycle

    threshold = SEVERITY_RANK.get(min_severity, 0)
    findings: List[Finding] = []
    for file_path in iter_files(Path(root), extensions=extensions, exclude=exclude):
        for finding in scan_file(file_path, allowlist=allowlist):
            if SEVERITY_RANK.get(finding.severity, 0) >= threshold:
                findings.append(finding)
    return findings
