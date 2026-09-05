"""hermes-unroll — secret redaction for trace events."""

import copy
import re

REDACT_PATTERNS: list[tuple[str, str]] = [
    # OpenAI-style sk-* keys (incl. sk-proj-...)
    (r"sk-(?:proj-)?[A-Za-z0-9_-]{8,}", "[REDACTED:api_key]"),
    # GitHub tokens: ghp_, gho_, ghu_, ghs_, ghr_
    (r"\bgh[pousr]_[A-Za-z0-9]{8,}\b", "[REDACTED:token]"),
    # Bearer headers: redact whole header value
    (r"Bearer\s+[A-Za-z0-9\-._~+/=]{8,}", "[REDACTED:bearer]"),
    # authorization headers (Basic, Token, etc.)
    (r"(?i)(authorization\s*[:=]\s*)([A-Za-z0-9\-._~+/=]{8,}.*)", r"\1[REDACTED:auth]"),
    # OPENAI_API_KEY=... / API_KEY=... env assignments
    (r"(?i)(OPENAI_API_KEY\s*=\s*)([A-Za-z0-9\-._~+/]+)", r"\1[REDACTED:api_key]"),
    (r"(?i)\b([A-Z_]*API_KEY\s*=\s*)([A-Za-z0-9\-._~+/]+)", r"\1[REDACTED:api_key]"),
    # 32+ char hex blobs near key/token/secret/password words
    (
        r"(?i)\b((?:api[_-]?key|secret|token|password)\b[^A-Za-z0-9]{0,10})([0-9a-f]{32,})\b",
        r"\1[REDACTED:secret]",
    ),
    # email addresses
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED:email]"),
]

_COMPILED = [(re.compile(p), r) for p, r in REDACT_PATTERNS]


def redact_text(s: str, custom_patterns: list[str] | None = None) -> str:
    """Redact secrets from a string."""
    out = s
    for pat, repl in _COMPILED:
        out = pat.sub(repl, out)
    for cp in custom_patterns or []:
        out = re.sub(cp, "[REDACTED:custom]", out)
    return out


def _redact_value(v: object, custom_patterns: list[str] | None = None) -> object:
    if isinstance(v, str):
        return redact_text(v, custom_patterns)
    if isinstance(v, dict):
        return {k: _redact_value(val, custom_patterns) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        red = [_redact_value(i, custom_patterns) for i in v]
        return type(v)(red) if isinstance(v, tuple) else red
    return v


def redact_event(event, custom_patterns: list[str] | None = None):
    """Return a copy of event with all string data redacted."""
    new_event = copy.deepcopy(event)
    new_event.data = _redact_value(new_event.data, custom_patterns)
    return new_event
