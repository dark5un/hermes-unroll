"""Tests for redact module — secret redaction for trace events."""
import re

from redact import REDACT_PATTERNS, redact_event, redact_text
from tracer import TraceEvent


def test_api_key_redacted():
    s = "my key is sk-abc123XYZ4567890abcdef"
    out = redact_text(s)
    assert "sk-abc123" not in out
    assert "[REDACTED:api_key]" in out


def test_email_redacted():
    out = redact_text("contact alice@example.com for details")
    assert "alice@example.com" not in out
    assert "[REDACTED:email]" in out


def test_bearer_token_redacted():
    out = redact_text("Authorization: Bearer abcdef1234567890")
    assert "abcdef1234567890" not in out
    assert "Bearer" not in out or "[REDACTED" in out


def test_hex_secret_redacted():
    secret = "a" * 40
    out = redact_text(f"api_key={secret}")
    assert secret not in out
    assert "[REDACTED" in out


def test_custom_pattern():
    out = redact_text("password is hunter2-xyz", custom_patterns=[r"hunter2-xyz"])
    assert "hunter2-xyz" not in out


def test_redact_event_redacts_data():
    ev = TraceEvent(kind="llm_call", data={"prompt": "key sk-abc123XYZ4567890abcdef", "n": 1})
    red = redact_event(ev)
    assert "sk-abc123" not in str(red.data["prompt"])
    assert red.data["n"] == 1
    assert red.kind == "llm_call"


def test_github_token_redacted():
    out = redact_text("token gho_abcdefghij1234567890ABCD")
    assert "gho_abcdefghij" not in out
    assert "[REDACTED" in out


def test_openai_env_var_redacted():
    out = redact_text("OPENAI_API_KEY=sk-abc123XYZ4567890abcdef")
    assert "sk-abc123" not in out
    assert "[REDACTED" in out


def test_redact_patterns_list_nonempty():
    assert isinstance(REDACT_PATTERNS, list)
    assert len(REDACT_PATTERNS) >= 5
    for pat, _repl in REDACT_PATTERNS:
        re.compile(pat)
