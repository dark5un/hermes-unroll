"""E2: counterfactual edit support in generated source."""

from pathlib import Path

from generator import generate_trace_program
from tracer import TraceEvent


def _seq():
    return [
        TraceEvent(kind="user_message", data={"text": "hello"}),
        TraceEvent(kind="llm_call", data={"response_text": "hi"}),
        TraceEvent(kind="final_response", data={"text": "hi"}),
    ]


class TestCounterfactual:
    def test_generated_source_has_edit_helpers(self):
        path = generate_trace_program(
            _seq(),
            session_id="test_counterfactual_e2",
            model="m",
            provider="p",
        )
        src = Path(path).read_text(encoding="utf-8")
        assert "_save_edited_trace" in src
        assert "invalidated_steps" in src

    def test_generated_source_has_cost_key(self):
        path = generate_trace_program(
            _seq(),
            session_id="test_counterfactual_cost",
            model="m",
            provider="p",
        )
        src = Path(path).read_text(encoding="utf-8")
        assert '"cost"' in src or "'cost'" in src
