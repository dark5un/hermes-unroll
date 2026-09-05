"""Pulse auto-score integration (G5 init-part).

Production code must try/except ImportError fail-open; Pulse is NOT
installed, so tests inject a fake ``pulse`` module via sys.modules.
Plugin __init__ is loaded via importlib spec to avoid package collisions.
"""

import importlib.util
import json
import sys
import types
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
INIT_PATH = PLUGIN_ROOT / "__init__.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("unroll_plugin_pulse", INIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["unroll_plugin_pulse"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_recorder_with_events(mod, tmp_path, monkeypatch):
    """Point traces dir at tmp HERMES_HOME and seed a recorder with events."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("UNROLL_PULSE_AUTO_SCORE", "true")
    mod._on_session_start(session_id="pulse-test-session", model="m", platform="p")
    rec = mod._get_session("pulse-test-session").recorder
    rec.session.system_prompt = "sys"
    rec.session.initial_user_message = "hi"
    rec.record("user_message", {"text": "hi"})
    rec.record("llm_call", {"response_text": "hello", "response_tool_calls": []})
    return rec


def test_pulse_present_writes_sidecar(tmp_path, monkeypatch):
    mod = _load_plugin()
    _make_recorder_with_events(mod, tmp_path, monkeypatch)
    fake = types.ModuleType("pulse")
    fake.score_session = lambda events: {"pulse_score": 0.87, "events_seen": len(events)}
    monkeypatch.setitem(sys.modules, "pulse", fake)
    mod._generate_trace("pulse-test-session")
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert traces, "trace program should be written"
    sidecar = Path(str(traces[0]) + ".pulse.json")
    assert sidecar.exists(), "sidecar should be written when pulse present"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert data["pulse_score"] == 0.87


def test_pulse_absent_no_sidecar_trace_still_written(tmp_path, monkeypatch):
    mod = _load_plugin()
    _make_recorder_with_events(mod, tmp_path, monkeypatch)
    monkeypatch.delitem(sys.modules, "pulse", raising=False)
    import builtins

    real_import = builtins.__import__

    def _guard(name, *args, **kwargs):
        if name == "pulse":
            raise ImportError("No module named 'pulse'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guard)
    # importlib.import_module uses __import__ under the hood, so this works.
    mod._generate_trace("pulse-test-session")
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert traces, "trace program should still be written without pulse"
    sidecars = list((tmp_path / "traces" / "unrolled").glob("*.pulse.json"))
    assert sidecars == [], "no sidecar expected when pulse absent"


def test_pulse_raising_trace_still_written(tmp_path, monkeypatch):
    mod = _load_plugin()
    _make_recorder_with_events(mod, tmp_path, monkeypatch)

    def _boom(events):
        raise RuntimeError("pulse exploded")

    fake = types.ModuleType("pulse")
    fake.score_session = _boom
    monkeypatch.setitem(sys.modules, "pulse", fake)
    mod._generate_trace("pulse-test-session")  # must not raise
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert traces, "trace program should still be written when pulse raises"
