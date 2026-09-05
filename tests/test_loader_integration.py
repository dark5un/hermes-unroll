"""WU-11 (Unroll half): loader-level integration harness.

Loads the plugin through the Hermes directory-loader path (real package
import with __path__ set), starts two independent sessions, interleaves
lifecycle + API + tool + stream + subagent hooks, finalizes in varying
callback orders, and asserts output isolation, exactly-once generation,
and complete metadata redaction.
"""

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _load_plugin(name="unroll_plugin_integration"):
    # Mirror the Hermes directory loader: copy plugin files to a temp dir
    # as a package (__init__.py at root), import with __path__ set.
    pkgdir = Path(tempfile.mkdtemp(prefix=f"{name}-")) / name
    pkgdir.mkdir()
    for src_file in PLUGIN_ROOT.glob("*.py"):
        shutil.copy(src_file, pkgdir / src_file.name)
    sys.path.insert(0, str(pkgdir.parent))
    return importlib.import_module(name)


def _drive_session(mod, sid, tag="-velocity"):
    mod._on_session_start(session_id=sid, model="m", platform="p")
    mod._on_pre_api_request(
        session_id=sid, model="m", provider="p", request_messages=[],
        conversation_history=[], user_message=f"hello{tag}", api_call_count=1,
        retry_count=0, approx_input_tokens=10, message_count=2, tool_count=0,
        request={"body": {"tools": []}}, system_prompt="sys",
        base_url="https://x", api_mode="chat",
    )
    mod._on_post_llm_call(
        session_id=sid, assistant_response=f"answer{tag}",
        conversation_history=[{"role": "user", "content": f"hello{tag}"}],
        model="m", platform="p", user_message=f"hello{tag}",
    )
    mod._on_post_tool_call(
        tool_name="terminal", args={"command": f"ls{tag}"}, result=f"out{tag}",
        task_id=f"t-{sid}", duration_ms=1, session_id=sid,
    )
    mod._on_stream_delta(session_id=sid, delta=f"d{tag}", kind="text")
    mod._on_subagent_start(
        parent_session_id=sid, child_session_id=f"{sid}-child",
        child_subagent_id="sa-1", child_role="r", child_goal="g",
    )
    mod._on_subagent_stop(
        parent_session_id=sid, child_session_id=f"{sid}-child",
        child_role="r", child_summary="done",
    )


def test_interleaved_sessions_isolated_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_int_iso")
    _drive_session(mod, "INT-A", tag="-aaa")
    _drive_session(mod, "INT-B", tag="-bbb")
    texts_a = [str(e.data) for e in mod._get_session("INT-A").recorder.session.events]
    texts_b = [str(e.data) for e in mod._get_session("INT-B").recorder.session.events]
    assert any("-aaa" in t for t in texts_a) and not any("-bbb" in t for t in texts_a)
    assert any("-bbb" in t for t in texts_b) and not any("-aaa" in t for t in texts_b)
    kinds_a = [e.kind for e in mod._get_session("INT-A").recorder.session.events]
    for kind in ("pre_api_request", "llm_call", "tool_call", "on_stream_delta",
                 "subagent_start", "subagent_stop"):
        assert kind in kinds_a


def test_finalize_orders_all_write_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for order in ("end-finalize", "finalize-end", "finalize-twice", "end-only"):
        mod = _load_plugin(f"unroll_int_ord_{order.replace('-', '_')}")
        sid = f"ORD-{order}"
        _drive_session(mod, sid)
        if order == "end-finalize":
            mod._on_session_end(session_id=sid, completed=True, interrupted=False, model="m", platform="p")
            mod._on_session_finalize(session_id=sid, platform="p")
        elif order == "finalize-end":
            mod._on_session_finalize(session_id=sid, platform="p")
            mod._on_session_end(session_id=sid, completed=True, interrupted=False, model="m", platform="p")
        elif order == "finalize-twice":
            mod._on_session_finalize(session_id=sid, platform="p")
            mod._on_session_finalize(session_id=sid, platform="p")
        else:
            mod._on_session_end(session_id=sid, completed=True, interrupted=False, model="m", platform="p")
        traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
        if order == "end-only":
            assert traces == [], "end-only must not write (finalize is the write point)"
        else:
            assert len(traces) == 1, f"{order}: expected exactly one trace"
        # Reset for next order.
        for t in traces:
            t.unlink()


def test_generated_files_fully_redacted_and_confidential(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_int_red")
    sid = "INT-RED"
    mod._on_session_start(session_id=sid, model="m", platform="p")
    rec = mod._get_session(sid).recorder
    rec.session.system_prompt = "sys sk-live-AAAAAAAA11111111"
    rec.session.initial_user_message = "mail bob@example.com"
    rec.record("user_message", {"text": "mail bob@example.com"})
    rec.record("llm_call", {"response_text": "done", "response_tool_calls": []})
    mod._on_session_finalize(session_id=sid, platform="p")
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert len(traces) == 1
    code = traces[0].read_text()
    assert "sk-live-AAAAAAAA11111111" not in code
    assert "bob@example.com" not in code
    import os

    assert os.stat(traces[0]).st_mode & 0o777 == 0o600
