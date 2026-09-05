"""Tests for ACTIVE_SKILLS capture (S2)."""

import importlib.util
import sys
from pathlib import Path

from generator import generate_trace_program
from tracer import TraceEvent

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
INIT_PATH = PLUGIN_ROOT / "__init__.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("unroll_plugin_activeskills", INIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["unroll_plugin_activeskills"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fresh_session(mod, monkeypatch, tmp_path, session_id="s2-test"):
    from tracer import TraceRecorder

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    rec = TraceRecorder()
    mod._recorder = rec
    mod._session_id = session_id
    mod._model = "m"
    mod._provider = "p"
    return rec


def test_pre_tool_call_skill_view_records_event_and_session_list(
    monkeypatch, tmp_path
):
    mod = _load_plugin()
    rec = _fresh_session(mod, monkeypatch, tmp_path)
    mod._on_pre_tool_call(
        tool_name="skill_view", args={"name": "my-skill"}, task_id="t1"
    )
    kinds = [e.kind for e in rec.session.events]
    assert "skill_view" in kinds
    assert rec.session.active_skills == ["my-skill"]
    ev = next(e for e in rec.session.events if e.kind == "skill_view")
    assert ev.data["name"] == "my-skill"


def test_skill_view_dedupe_on_repeat(monkeypatch, tmp_path):
    mod = _load_plugin()
    rec = _fresh_session(mod, monkeypatch, tmp_path)
    mod._on_pre_tool_call(
        tool_name="skill_view", args={"name": "my-skill"}, task_id="t1"
    )
    mod._on_pre_tool_call(
        tool_name="skill_view", args={"name": "my-skill"}, task_id="t2"
    )
    assert rec.session.active_skills == ["my-skill"]


def test_non_skill_tools_unaffected(monkeypatch, tmp_path):
    mod = _load_plugin()
    rec = _fresh_session(mod, monkeypatch, tmp_path)
    mod._on_pre_tool_call(
        tool_name="terminal", args={"command": "ls"}, task_id="t1"
    )
    assert rec.session.active_skills == []
    kinds = [e.kind for e in rec.session.events]
    assert "skill_view" not in kinds
    assert "pre_tool_call" in kinds


def test_generated_source_contains_active_skills(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = [
        TraceEvent(kind="skill_view", data={"name": "my-skill"}),
        TraceEvent(kind="user_message", data={"text": "hi"}),
    ]
    path = generate_trace_program(
        events, session_id="s2-gen", active_skills=["my-skill"]
    )
    src = Path(path).read_text(encoding="utf-8")
    assert "ACTIVE_SKILLS" in src
    assert "my-skill" in src


def test_generated_source_from_skill_view_events_without_param(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = [
        TraceEvent(kind="skill_view", data={"name": "evt-skill"}),
    ]
    path = generate_trace_program(events, session_id="s2-gen2")
    src = Path(path).read_text(encoding="utf-8")
    assert "ACTIVE_SKILLS" in src
    assert "evt-skill" in src
