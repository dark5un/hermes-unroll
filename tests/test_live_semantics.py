"""WU-9 (UN-5/UN-6/UN-13): live/counterfactual semantics — Option A.

- Live replay is model-only: --live serves LLM steps from the provider and
  tool calls from cache/stub. --allow-destructive is a no-op-with-error
  under model-only live mode (it cannot imply execution).
- --edit applies the edit to the input message BEFORE replay, invalidates
  dependent cache entries via DEPENDENCIES, and never writes back over the
  source trace.
- One safety policy from one source: safety.is_destructive (command
  patterns + name policy) consumed by both safety.py and the template.
  Denylist documented as not-a-sandbox; read-only allowlist guidance.
"""

import json
import subprocess
import sys
from pathlib import Path

from generator import generate_trace_program
from tracer import TraceRecorder


def _events():
    rec = TraceRecorder()
    rec.record("system_prompt", {"text": "sys"})
    rec.record("user_message", {"text": "original question"})
    rec.record("llm_call", {"response_text": "answer one", "response_tool_calls": []})
    rec.record("tool_call", {
        "name": "terminal", "args": {"command": "ls"},
        "content": "CACHED-RESULT", "tool_call_id": "c1", "duration_ms": 1,
    }, event_id="c1")
    rec.record("llm_call", {"response_text": "final", "response_tool_calls": []})
    return rec.session.events


def test_live_model_only_declared_in_help(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = generate_trace_program(_events(), session_id="live-help")
    proc = subprocess.run([sys.executable, path, "--help"], capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0
    assert "model-only" in proc.stdout.lower()


def test_allow_destructive_errors_under_live_model_only(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = generate_trace_program(_events(), session_id="live-destr")
    proc = subprocess.run(
        [sys.executable, path, "--live", "--allow-destructive"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 2
    assert "model-only" in (proc.stdout + proc.stderr).lower()


def test_edit_applies_before_replay_and_invalidates(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = generate_trace_program(_events(), session_id="edit-pre")
    proc = subprocess.run(
        [sys.executable, path, "--edit", "1 EDITED QUESTION"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    payload = json.loads(proc.stdout.split("=== STRUCTURED OUTPUT ===")[1])
    user_contents = [m["content"] for m in payload["messages"] if m["role"] == "user"]
    assert "EDITED QUESTION" in user_contents
    assert "original question" not in user_contents
    assert payload["invalidated_steps"]
    # Never writes back over the source trace: no sibling edit file
    # overwrites the original, and the original still holds the old text.
    assert "original question" in Path(path).read_text()


def test_edit_never_overwrites_source_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = generate_trace_program(_events(), session_id="edit-src")
    before = Path(path).read_bytes()
    proc = subprocess.run(
        [sys.executable, path, "--edit", "1 CHANGED"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert Path(path).read_bytes() == before


def test_safety_policy_single_source():
    import safety
    from safety import DESTRUCTIVE_TOOLS, is_destructive

    assert DESTRUCTIVE_TOOLS == safety.POLICY["destructive_names"]
    # Denylist coverage from the plan: redirection, mv, find -delete,
    # git reset --hard, package removal, chained commands.
    assert is_destructive("terminal", {"command": "echo hi > /etc/passwd"}) is True
    assert is_destructive("terminal", {"command": "mv a b"}) is True
    assert is_destructive("terminal", {"command": "find . -delete"}) is True
    assert is_destructive("terminal", {"command": "git reset --hard"}) is True
    assert is_destructive("terminal", {"command": "apt-get remove foo"}) is True
    assert is_destructive("terminal", {"command": "ls && rm -rf /tmp/x"}) is True
    assert is_destructive("terminal", {"command": "ls -la"}) is False
