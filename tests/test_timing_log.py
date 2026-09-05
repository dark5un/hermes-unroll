"""A2: timing_log per-step timing comparison (subprocess replay)."""

import json
import subprocess
import sys

from generator import generate_trace_program
from tracer import TraceEvent


def _run_trace(path, args=None):
    cmd = [sys.executable, path, *(args or [])]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode == 0, f"replay failed: {proc.stderr[-2000:]}"
    marker = "=== STRUCTURED OUTPUT ==="
    assert marker in proc.stdout
    payload = proc.stdout.split(marker, 1)[1].strip()
    return proc, json.loads(payload)


def test_timing_log_matches_steps_with_offsets():
    t0 = 1000.0
    events = [
        TraceEvent(kind="user_message", timestamp=t0 + 1.0, data={"text": "hi"}),
        TraceEvent(kind="llm_call", timestamp=t0 + 2.0, data={"response_text": "hello"}),
    ]
    path = generate_trace_program(
        events,
        session_id="test_timing_log_a2",
        model="m",
        provider="p",
        started_at=t0,
    )
    proc, result = _run_trace(path)
    assert "timing_log" in result
    assert "replay_duration_ms" in result
    assert "started_at" in result
    assert len(result["timing_log"]) == len(result["steps"])
    assert len(result["timing_log"]) == 2
    for entry in result["timing_log"]:
        for key in (
            "step",
            "kind",
            "original_offset_ms",
            "replay_offset_ms",
            "delta_ms",
            "duration_ms",
            "replay_duration_ms",
        ):
            assert key in entry, f"missing {key} in {entry}"
        assert entry["replay_offset_ms"] >= 0
        assert entry["replay_duration_ms"] >= 0
        assert entry["delta_ms"] == entry["replay_offset_ms"] - entry["original_offset_ms"]
    # original offsets come from TIMELINE
    assert result["timing_log"][0]["original_offset_ms"] == 1000
    assert result["timing_log"][1]["original_offset_ms"] == 2000
    # steps carry replay_duration_ms
    for s in result["steps"]:
        assert "replay_duration_ms" in s
    # timing summary printed
    assert "Timing" in proc.stdout or "timing" in proc.stdout.lower()
