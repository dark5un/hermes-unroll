"""Tests for session-tags capture (C2-a, task T2). UNROLL_ prefix, HERMES_ fallback."""

import importlib


def _reload(monkeypatch, env):
    for var in ("UNROLL_SESSION_TAGS", "HERMES_SESSION_TAGS"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import __init__ as plugin

    return importlib.reload(plugin)


def test_unroll_prefix_wins(monkeypatch):
    plugin = _reload(monkeypatch, {"UNROLL_SESSION_TAGS": "team-a", "HERMES_SESSION_TAGS": "team-b"})
    assert plugin._session_tags_from_env() == ["team-a"]


def test_hermes_fallback(monkeypatch):
    plugin = _reload(monkeypatch, {"HERMES_SESSION_TAGS": "team-b"})
    assert plugin._session_tags_from_env() == ["team-b"]


def test_unset_gives_empty(monkeypatch):
    plugin = _reload(monkeypatch, {})
    assert plugin._session_tags_from_env() == []


def test_whitespace_and_empties_cleaned(monkeypatch):
    plugin = _reload(monkeypatch, {"UNROLL_SESSION_TAGS": " team-a ,, feat-x "})
    assert plugin._session_tags_from_env() == ["team-a", "feat-x"]


def test_session_start_assigns_tags(monkeypatch):
    plugin = _reload(monkeypatch, {"UNROLL_SESSION_TAGS": "team-a"})
    plugin._on_session_start(session_id="s", model="m", platform="p")
    assert plugin._recorder.session.tags == ["team-a"]
