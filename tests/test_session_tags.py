"""Tests for session-tags capture (C2-a, task T2). UNROLL_ prefix, HERMES_ fallback."""

import importlib.util
import sys
from pathlib import Path

INIT_PATH = Path(__file__).resolve().parent.parent / "__init__.py"


def _load_plugin():
    # Unique spec name per call: avoids the tests/__init__.py package
    # shadowing the plugin root's __init__.py (same bug the other
    # spec-loading test files work around).
    spec = importlib.util.spec_from_file_location("unroll_plugin_sessiontags", INIT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    spec.loader.exec_module(mod)
    return mod


def test_unroll_prefix_wins(monkeypatch):
    monkeypatch.setenv("UNROLL_SESSION_TAGS", "team-a")
    monkeypatch.setenv("HERMES_SESSION_TAGS", "team-b")
    assert _load_plugin()._session_tags_from_env() == ["team-a"]


def test_hermes_fallback(monkeypatch):
    monkeypatch.delenv("UNROLL_SESSION_TAGS", raising=False)
    monkeypatch.setenv("HERMES_SESSION_TAGS", "team-b")
    assert _load_plugin()._session_tags_from_env() == ["team-b"]


def test_unset_gives_empty(monkeypatch):
    monkeypatch.delenv("UNROLL_SESSION_TAGS", raising=False)
    monkeypatch.delenv("HERMES_SESSION_TAGS", raising=False)
    assert _load_plugin()._session_tags_from_env() == []


def test_whitespace_and_empties_cleaned(monkeypatch):
    monkeypatch.setenv("UNROLL_SESSION_TAGS", " team-a ,, feat-x ")
    assert _load_plugin()._session_tags_from_env() == ["team-a", "feat-x"]


def test_session_start_assigns_tags(monkeypatch):
    monkeypatch.setenv("UNROLL_SESSION_TAGS", "team-a")
    plugin = _load_plugin()
    plugin._on_session_start(session_id="s", model="m", platform="p")
    assert plugin._get_session("s").recorder.session.tags == ["team-a"]
