"""E1: dependency map chain on user-llm-tool-llm-final sequence."""

from pathlib import Path

from generator import _build_dependency_map, generate_trace_program
from tracer import TraceEvent


def _seq():
    return [
        TraceEvent(kind="user_message", data={"text": "hello"}),
        TraceEvent(kind="llm_call", data={"response_text": "hi"}),
        TraceEvent(
            kind="tool_call",
            data={"name": "search", "content": "r", "tool_call_id": "c1"},
        ),
        TraceEvent(kind="llm_call", data={"response_text": "done"}),
        TraceEvent(kind="final_response", data={"text": "done"}),
    ]


class TestDependencyMap:
    def test_chain(self):
        deps = _build_dependency_map(_seq())
        assert deps[0] == []
        assert deps[1] == [0]
        assert deps[2] == [1]
        assert deps[3] == [0, 2]
        assert deps[4] == [3]

    def test_emitted_in_generated_file_and_result(self):
        path = generate_trace_program(
            _seq(),
            session_id="test_deps_e1",
            model="m",
            provider="p",
        )
        src = Path(path).read_text(encoding="utf-8")
        assert "DEPENDENCIES" in src
        assert "dependencies" in src
