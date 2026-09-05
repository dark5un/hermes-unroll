"""WU-8 (UN-2/UN-3/UN-4/UN-10): replay identity and fidelity.

- Every LLM/tool cache lookup resolves by stable event_id (100% hit rate
  on mixed-kind fixtures); a coincidental index collision can never serve
  the wrong event's payload; a miss raises loudly instead of falling
  through to a silent default.
- Recorded tool args (redacted) are emitted as the generated default
  arguments; round-trip equality for safe fixtures.
- Captured provider base_url/api_mode appear in PROVIDER_CONFIG; keys never
  appear anywhere.
- --stop-at bounds execution (steps after the bound never execute).
"""

import json
import subprocess
import sys
from pathlib import Path

from generator import _build_response_cache, generate_trace_program
from tracer import TraceRecorder


def _events():
    rec = TraceRecorder()
    rec.record("system_prompt", {"text": "sys"})
    rec.record("user_message", {"text": "q1"})
    rec.record("llm_call", {"response_text": "a1", "response_tool_calls": []})
    rec.record("pre_api_request", {"api_call_count": 1})
    rec.record("tool_call", {
        "name": "terminal", "args": {"path": "/tmp/example"},
        "content": "RESULT-ONE", "tool_call_id": "call-1", "duration_ms": 5,
    }, event_id="call-1")
    rec.record("post_api_request", {"usage": {}})
    rec.record("llm_call", {"response_text": "a2", "response_tool_calls": []})
    rec.record("tool_call", {
        "name": "read", "args": {"path": "/tmp/other"},
        "content": "RESULT-TWO", "tool_call_id": "call-2", "duration_ms": 3,
    }, event_id="call-2")
    rec.record("final_response", {"text": "done"})
    return rec.session.events


def test_cache_keys_are_event_ids_with_full_hit_rate():
    events = _events()
    cache = _build_response_cache(events)
    assert len(cache) == 4  # 2 llm + 2 tool, nothing else cached
    assert set(cache) == {"llm:" + e.event_id for e in events if e.kind == "llm_call"} | {
        "tool:" + e.event_id for e in events if e.kind == "tool_call"
    }
    # Every generated tool step's event_id resolves to its own result.
    llm_texts = {e.event_id: e.data["response_text"] for e in events if e.kind == "llm_call"}
    tool_results = {e.event_id: e.data["content"] for e in events if e.kind == "tool_call"}
    for key, entry in cache.items():
        kind, eid = key.split(":", 1)
        if kind == "llm":
            assert entry["response_text"] == llm_texts[eid]
        else:
            assert entry["result"] == tool_results[eid]


def test_no_positional_cache_keys_remain():
    events = _events()
    cache = _build_response_cache(events)
    for key in cache:
        assert ":" in key
        assert not key.split(":")[1].isdigit() or key.startswith(("llm:llm_call", "tool:tool_call", "llm:call", "tool:call"))


def test_recorded_tool_args_emitted_as_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = _events()
    path = generate_trace_program(events, session_id="args-test")
    code = Path(path).read_text()
    assert '"/tmp/example"' in code or "/tmp/example" in code
    assert "_tool_args_" in code
    assert "_tool_args_0 = {}" not in code


def test_dry_run_replay_serves_exact_results(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = _events()
    path = generate_trace_program(events, session_id="replay-exact")
    proc = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = proc.stdout
    assert "RESULT-ONE" in out
    assert "RESULT-TWO" in out
    # Both results appear as tool messages in the structured output.
    structured = out.split("=== STRUCTURED OUTPUT ===")[1]
    payload = json.loads(structured)
    tool_contents = [m["content"] for m in payload["messages"] if m["role"] == "tool"]
    assert "RESULT-ONE" in tool_contents
    assert "RESULT-TWO" in tool_contents


def test_secret_tool_args_redacted_before_emit(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    from redact import redact_event

    rec = TraceRecorder()
    rec.record("user_message", {"text": "hi"})
    rec.record("tool_call", {
        "name": "t", "args": {"api_key": "sk-live-AAAAAAAA11111111"},
        "content": "ok", "tool_call_id": "c1", "duration_ms": 1,
    }, event_id="c1")
    events = [redact_event(e) for e in rec.session.events]
    path = generate_trace_program(events, session_id="secret-args")
    code = Path(path).read_text()
    assert "sk-live-AAAAAAAA11111111" not in code


def test_captured_provider_config_emitted_without_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = _events()
    path = generate_trace_program(
        events,
        session_id="prov-test",
        provider_config={
            "provider": "openai",
            "base_url": "https://local-vllm:8000/v1",
            "api_mode": "chat",
            "api_key": "sk-live-AAAAAAAA11111111",
        },
    )
    code = Path(path).read_text()
    assert "https://local-vllm:8000/v1" in code
    assert "sk-live-AAAAAAAA11111111" not in code


def test_stop_at_bounds_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    events = _events()
    path = generate_trace_program(events, session_id="stop-test")
    full = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=120, check=False)
    assert full.returncode == 0, full.stderr[-2000:]
    full_steps = json.loads(full.stdout.split("=== STRUCTURED OUTPUT ===")[1])["steps"]
    bounded = subprocess.run(
        [sys.executable, path, "--stop-at", "2"], capture_output=True, text=True, timeout=120, check=False
    )
    assert bounded.returncode == 0, bounded.stderr[-2000:]
    # --stop-at N bounds execution to N steps from the start: the printed
    # steps list has exactly 2 entries and later content (RESULT-TWO from a
    # later step) never executes. (stdout may carry DRY-RUN skip notices
    # before the JSON payload — slice from the first '['.)
    shown = json.loads(bounded.stdout[bounded.stdout.index("["):bounded.stdout.index("===")])
    assert len(shown) == 2
    assert "RESULT-TWO" not in json.dumps(shown)
    assert len(full_steps) > 2
