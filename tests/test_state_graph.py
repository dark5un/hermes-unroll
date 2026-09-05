"""Tests for Phase D state-graph export (D1) and LangGraph guard (D2)."""

import ast
import json
import subprocess
import sys

from generator import _build_state_graph, generate_trace_program
from tracer import TraceEvent


def _ev(kind, data=None, ts=0.0):
    e = TraceEvent(kind=kind, data=data or {})
    e.timestamp = ts
    return e


class TestBuildStateGraph:
    def test_linear_three_events_yield_three_nodes_two_edges(self):
        events = [
            _ev("user_message", {"text": "hi"}, ts=1000.0),
            _ev("llm_call", {"response_text": "hello"}, ts=1001.0),
            _ev("final_response", {"text": "hello"}, ts=1002.0),
        ]
        g = _build_state_graph(events, started_at=1000.0)
        assert len(g["nodes"]) == 3
        assert len(g["edges"]) == 2
        assert g["edges"][0] == {"from": 0, "to": 1}
        assert g["edges"][1] == {"from": 1, "to": 2}
        for i, n in enumerate(g["nodes"]):
            assert n["id"] == i
            assert "kind" in n and "label" in n and "original_offset_ms" in n
        assert g["nodes"][0]["kind"] == "user_message"
        assert g["nodes"][0]["original_offset_ms"] == 0
        assert g["nodes"][1]["original_offset_ms"] == 1000

    def test_subagent_pair_yields_subgraph_entry(self):
        events = [
            _ev("subagent_start", {"child_role": "researcher", "child_goal": "find X"}, ts=1000.0),
            _ev("tool_call", {"name": "search"}, ts=1001.0),
            _ev("subagent_stop", {"child_role": "researcher", "child_summary": "done"}, ts=1002.0),
        ]
        g = _build_state_graph(events, started_at=1000.0)
        assert len(g["nodes"]) == 3
        assert "subgraphs" in g
        assert len(g["subgraphs"]) == 1
        sg = g["subgraphs"][0]
        assert sg["role"] == "researcher"
        assert sg["start"] == 0
        assert sg["stop"] == 2

    def test_dict_events_duck_typing(self):
        events = [
            {"kind": "user_message", "timestamp": 1000.0, "data": {"text": "hi"}},
            {"kind": "llm_call", "timestamp": 1001.0, "data": {}},
        ]
        g = _build_state_graph(events, started_at=1000.0)
        assert len(g["nodes"]) == 2
        assert len(g["edges"]) == 1


class TestGeneratedFileStateGraph:
    def test_generated_file_emits_state_graph_constant(self):
        events = [
            _ev("user_message", {"text": "hi"}, ts=1000.0),
            _ev("llm_call", {"response_text": "yo"}, ts=1001.0),
        ]
        path = generate_trace_program(events, session_id="test_stategraph_001", started_at=1000.0)
        with open(path) as f:
            code = f.read()
        assert "STATE_GRAPH" in code
        assert ast.parse(code) is not None

    def test_generated_file_has_langgraph_guard(self):
        events = [_ev("user_message", {"text": "hi"}, ts=1000.0)]
        path = generate_trace_program(events, session_id="test_langgraph_001", started_at=1000.0)
        with open(path) as f:
            code = f.read()
        assert "HAS_LANGGRAPH" in code
        assert "build_langgraph" in code
        assert "ImportError" in code
        assert ast.parse(code) is not None

    def test_generated_file_runs_and_prints_state_graph(self):
        events = [
            _ev("user_message", {"text": "hi"}, ts=1000.0),
            _ev("llm_call", {"response_text": "yo"}, ts=1001.0),
            _ev("final_response", {"text": "yo"}, ts=1002.0),
        ]
        path = generate_trace_program(events, session_id="test_stategraph_run", started_at=1000.0)
        proc = subprocess.run(
            [sys.executable, path], capture_output=True, text=True, timeout=60, check=False
        )
        assert proc.returncode == 0, proc.stderr
        marker = "=== STRUCTURED OUTPUT ==="
        assert marker in proc.stdout
        payload = proc.stdout.split(marker, 1)[1].strip()
        result = json.loads(payload)
        assert "state_graph" in result
        assert len(result["state_graph"]["nodes"]) == 3
        assert len(result["state_graph"]["edges"]) == 2

    def test_build_langgraph_returns_none_without_package(self):
        events = [_ev("user_message", {"text": "hi"}, ts=1000.0)]
        path = generate_trace_program(events, session_id="test_langgraph_run", started_at=1000.0)
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    f"import runpy; g = runpy.run_path({path!r}); "
                    "assert 'build_langgraph' in g, 'missing helper'; "
                    "assert g['build_langgraph']() is None, 'expected None without langgraph'; "
                    "assert g['HAS_LANGGRAPH'] is False, 'expected False flag'; "
                    "print('LANG_OK')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert "LANG_OK" in proc.stdout
