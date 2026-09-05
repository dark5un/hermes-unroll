"""A3: range replay omits skipped steps from timing_log."""

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
    return proc, json.loads(proc.stdout.split(marker, 1)[1].strip())


def _three_events(t0):
    return [
        TraceEvent(kind="user_message", timestamp=t0 + 1.0, data={"text": "one"}),
        TraceEvent(kind="user_message", timestamp=t0 + 2.0, data={"text": "two"}),
        TraceEvent(kind="user_message", timestamp=t0 + 3.0, data={"text": "three"}),
    ]


def test_range_replay_omits_skipped_steps_from_timing_log():
    t0 = 1000.0
    path = generate_trace_program(
        _three_events(t0),
        session_id="test_range_replay_a3",
        model="m",
        provider="p",
        started_at=t0,
    )
    _, full = _run_trace(path)
    assert len(full["timing_log"]) == 3

    _, ranged = _run_trace(path, ["--from", "1", "--to", "1"])
    assert ranged["from_step"] == 1
    assert ranged["to_step"] == 1
    assert len(ranged["steps"]) == 1
    assert len(ranged["timing_log"]) == 1
    assert ranged["timing_log"][0]["step"] == 1
    assert ranged["timing_log"][0]["original_offset_ms"] == 2000
    for key in (
        "step",
        "kind",
        "original_offset_ms",
        "replay_offset_ms",
        "delta_ms",
        "duration_ms",
        "replay_duration_ms",
    ):
        assert key in ranged["timing_log"][0]
