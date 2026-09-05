"""WU-6 (UN-1): session-keyed context — interleaved sessions never mix.

The plugin previously kept one process-global ``_recorder`` (+
``_session_id``/``_model``/``_provider``/``_first_turn``), unconditionally
replaced on every ``on_session_start``. On any multi-session host
(gateway, concurrent runs) two sessions' events and metadata mix.

These tests pin the session-keyed contract:

- starting A then B yields two independent recorders;
- interleaved hooks of every kind land only in their own session;
- an unknown session id is a no-op (never a fallback to another session);
- subagent events land in the documented owner (the parent session).
"""

import importlib.util
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
INIT_PATH = PLUGIN_ROOT / "__init__.py"


def _load_plugin(name: str = "unroll_plugin_session_isolation"):
    spec = importlib.util.spec_from_file_location(name, INIT_PATH)
    assert spec is not None and spec.loader is not None  # plugin file always exists
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_two_session_starts_yield_independent_recorders():
    mod = _load_plugin()
    mod._on_session_start(session_id="A", model="m-a", platform="p-a")
    mod._on_session_start(session_id="B", model="m-b", platform="p-b")
    ctx_a = mod._get_session("A")
    ctx_b = mod._get_session("B")
    assert ctx_a is not None and ctx_b is not None
    assert ctx_a is not ctx_b
    assert ctx_a.recorder is not ctx_b.recorder
    assert ctx_a.model == "m-a" and ctx_b.model == "m-b"


def test_interleaved_events_stay_in_their_session():
    mod = _load_plugin()
    mod._on_session_start(session_id="A", model="m", platform="p")
    mod._on_session_start(session_id="B", model="m", platform="p")

    mod._on_post_llm_call(
        session_id="A",
        assistant_response="answer-a",
        conversation_history=[{"role": "user", "content": "q-a"}],
        model="m",
        platform="p",
        user_message="q-a",
    )
    mod._on_post_llm_call(
        session_id="B",
        assistant_response="answer-b",
        conversation_history=[{"role": "user", "content": "q-b"}],
        model="m",
        platform="p",
        user_message="q-b",
    )
    mod._on_post_tool_call(
        tool_name="terminal",
        args={"command": "ls-a"},
        result="out-a",
        task_id="t-a",
        duration_ms=1,
        session_id="A",
    )
    mod._on_post_tool_call(
        tool_name="terminal",
        args={"command": "ls-b"},
        result="out-b",
        task_id="t-b",
        duration_ms=1,
        session_id="B",
    )
    mod._on_pre_api_request(
        session_id="A",
        model="m",
        provider="p",
        request_messages=[],
        conversation_history=[],
        user_message="q-a",
        api_call_count=1,
        retry_count=0,
        approx_input_tokens=None,
        message_count=1,
        tool_count=0,
    )
    mod._on_pre_tool_call(
        tool_name="terminal",
        args={"command": "ls-b"},
        task_id="t-b",
        session_id="B",
    )

    kinds_a = [e.kind for e in mod._get_session("A").recorder.session.events]
    kinds_b = [e.kind for e in mod._get_session("B").recorder.session.events]
    texts_a = [e.data.get("text", e.data.get("response_text", "")) for e in mod._get_session("A").recorder.session.events]
    texts_b = [e.data.get("text", e.data.get("response_text", "")) for e in mod._get_session("B").recorder.session.events]
    args_a = [str(e.data.get("args", "")) for e in mod._get_session("A").recorder.session.events]
    args_b = [str(e.data.get("args", "")) for e in mod._get_session("B").recorder.session.events]

    assert "llm_call" in kinds_a and "tool_call" in kinds_a
    assert "llm_call" in kinds_b and "pre_tool_call" in kinds_b
    # Same kinds exist in both (each session made its own calls) — payloads
    # must not cross: A's tool args never appear in B and vice versa.
    assert any("ls-a" in a for a in args_a) and not any("ls-b" in a for a in args_a)
    assert any("ls-b" in a for a in args_b) and not any("ls-a" in a for a in args_b)
    assert not any("q-b" in str(t) or "answer-b" in str(t) for t in texts_a)
    assert not any("q-a" in str(t) or "answer-a" in str(t) for t in texts_b)


def test_restarting_a_session_does_not_clobber_the_other():
    mod = _load_plugin()
    mod._on_session_start(session_id="A", model="m", platform="p")
    mod._on_session_start(session_id="B", model="m", platform="p")
    rec_b_before = mod._get_session("B").recorder
    mod._on_post_tool_call(
        tool_name="t",
        args={},
        result="r-b",
        task_id="t1",
        duration_ms=1,
        session_id="B",
    )
    # A restarts (e.g. reconnect); B's accumulated events must survive.
    mod._on_session_start(session_id="A", model="m2", platform="p")
    assert mod._get_session("B").recorder is rec_b_before
    assert any(
        e.data.get("content") == "r-b"
        for e in mod._get_session("B").recorder.session.events
    )


def test_unknown_session_hook_is_noop():
    mod = _load_plugin()
    mod._on_session_start(session_id="A", model="m", platform="p")
    before = len(mod._get_session("A").recorder.session.events)
    mod._on_post_tool_call(
        tool_name="terminal",
        args={},
        result="ghost",
        task_id="t9",
        duration_ms=1,
        session_id="NOPE",
    )
    assert mod._get_session("NOPE") is None
    assert len(mod._get_session("A").recorder.session.events) == before


def test_subagent_events_land_in_parent_session():
    mod = _load_plugin()
    mod._on_session_start(session_id="parent", model="m", platform="p")
    mod._on_subagent_start(
        parent_session_id="parent",
        child_session_id="child-1",
        child_subagent_id="sa-1",
        child_role="researcher",
        child_goal="look things up",
    )
    mod._on_subagent_stop(
        parent_session_id="parent",
        child_session_id="child-1",
        child_role="researcher",
        child_summary="done",
    )
    kinds = [e.kind for e in mod._get_session("parent").recorder.session.events]
    assert "subagent_start" in kinds and "subagent_stop" in kinds
    # No phantom child context is created.
    assert mod._get_session("child-1") is None


def test_no_process_global_recorder_remains():
    mod = _load_plugin()
    assert not hasattr(mod, "_recorder")
    assert not hasattr(mod, "_first_turn")
