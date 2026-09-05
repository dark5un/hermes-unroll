"""TDD: live generation (C2) + substitute/destructive guards (C3)."""

import ast
import subprocess
import sys
from pathlib import Path

from generator import (
    _build_replay_steps,
    _make_parse_args_function,
    generate_trace_program,
)
from tracer import TraceEvent


def _sample_events():
    return [
        TraceEvent(kind="system_prompt", data={"text": "Be helpful."}, event_id="system_prompt-1"),
        TraceEvent(kind="user_message", data={"text": "Search the web"}, event_id="user-1"),
        TraceEvent(
            kind="llm_call",
            data={
                "response_text": "",
                "response_tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query": "Paris"}',
                        },
                    }
                ],
            },
            event_id="call_1",
        ),
        TraceEvent(
            kind="tool_call",
            data={
                "tool_call_id": "call_1",
                "name": "web_search",
                "content": '{"results": []}',
            },
            event_id="call_1",
        ),
        TraceEvent(kind="final_response", data={"text": "done"}, event_id="final-1"),
    ]


def _gen_code(tmp_session="test_live_gen_c2c3"):
    events = _sample_events()
    path = generate_trace_program(
        events,
        session_id=tmp_session,
        model="gpt-4o",
        provider="openai",
        system_prompt="Be helpful.",
        user_message="Search the web",
        final_response="done",
    )
    return Path(path).read_text(encoding="utf-8"), str(path)


class TestLiveHelper:
    def test_generated_source_contains_live_llm_call(self):
        code, _ = _gen_code()
        assert "def _live_llm_call" in code

    def test_live_helper_lazy_openai_and_urllib_fallback(self):
        code, _ = _gen_code()
        assert "from openai import OpenAI" in code
        assert "chat.completions.create" in code
        assert "urllib" in code
        assert "chat/completions" in code
        assert "OPENAI_API_KEY" in code
        assert "HERMES_API_KEY" in code
        assert ".env" in code
        assert "Bearer" in code

    def test_tool_schemas_and_provider_config_constants(self):
        code, _ = _gen_code()
        assert "TOOL_SCHEMAS" in code
        assert "PROVIDER_CONFIG" in code

    def test_llm_call_blocks_emit_live_branch(self):
        code, _ = _gen_code()
        assert "_live_llm_call" in code
        # LIVE branch guarding cache path
        assert "LIVE" in code

    def test_parse_args_has_engine_choice(self):
        src = _make_parse_args_function()
        assert "--engine" in src
        assert "openai" in src
        assert "pydantic" in src

    def test_generated_source_has_engine_flag(self):
        code, _ = _gen_code()
        assert "--engine" in code


class TestSubstituteAndDestructive:
    def test_allow_destructive_flag(self):
        src = _make_parse_args_function()
        assert "allow-destructive" in src
        code, _ = _gen_code()
        assert "allow-destructive" in code
        assert "ALLOW_DESTRUCTIVE" in code
        assert "DESTRUCTIVE_TOOLS" in code

    def test_tool_call_blocks_emit_substitute_check(self):
        code, _ = _gen_code()
        assert "substitute_tool" in code
        # form: "<step> <json-args>" split on first space
        assert 'split(" ", 1)' in code or "split(' ', 1)" in code

    def test_destructive_guard_dry_run_skipped(self):
        code, _ = _gen_code()
        assert "DRY-RUN" in code
        assert "skipped" in code

    def test_dispatch_tool_helper(self):
        code, _ = _gen_code()
        assert "def dispatch_tool" in code

    def test_replay_steps_reference_substitute_and_destructive(self):
        steps = _build_replay_steps(_sample_events())
        assert "substitute_tool" in steps or "SUBSTITUTE_TOOL" in steps
        assert "DESTRUCTIVE_TOOLS" in steps
        assert "ALLOW_DESTRUCTIVE" in steps


class TestGeneratedFileStillValid:
    def test_ast_parse(self):
        code, _ = _gen_code("test_live_parse_c2c3")
        assert ast.parse(code) is not None

    def test_dry_run_executes(self):
        _, path = _gen_code("test_live_dryrun_c2c3")
        proc = subprocess.run(
            [sys.executable, path],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert "STRUCTURED OUTPUT" in proc.stdout
