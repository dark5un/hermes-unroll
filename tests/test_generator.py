"""Tests for the hermes-unroll code generator."""

import ast
from pathlib import Path

from hermes_unroll.generator import (
    count_llm_calls,
    count_tool_calls,
    format_messages,
    generate_trace_program,
    reconstruct_messages,
    safe_filename,
)
from hermes_unroll.tracer import TraceEvent


class TestSafeFilename:
    """safe_filename sanitises session IDs for filename use."""

    def test_basic_session_id(self):
        """A simple alphanumeric ID passes through cleanly."""
        assert safe_filename("20260905_143052_a1b2c3") == "20260905_143052_a1b2c3"

    def test_replaces_special_chars_with_underscores(self):
        """Spaces and special chars are mapped to underscores."""
        result = safe_filename("session: test @#$")
        # No colons, spaces, etc.
        assert " " not in result
        assert ":" not in result
        assert "@" not in result

    def test_strips_leading_trailing_dots_and_underscores(self):
        """Leading/trailing punctuation is stripped."""
        result = safe_filename("___hello_world___")
        assert not result.startswith("_")
        assert not result.endswith("_")

    def test_empty_input_falls_back_to_session(self):
        """Empty string returns 'session'."""
        assert safe_filename("") == "session"

    def test_truncates_at_96_chars(self):
        """Very long IDs are truncated to 96 characters."""
        long_id = "x" * 200
        result = safe_filename(long_id)
        assert len(result) == 96
        assert result == "x" * 96


class TestReconstructMessages:
    """reconstruct_messages walks events and builds message dicts."""

    def test_single_user_message(self):
        """One user_message event produces one user message."""
        events = [TraceEvent(kind="user_message", data={"text": "Hello"})]
        msgs = reconstruct_messages(events)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Hello"

    def test_system_prompt_becomes_system_message(self):
        """system_prompt event produces a system message."""
        events = [TraceEvent(kind="system_prompt", data={"text": "You are helpful."})]
        msgs = reconstruct_messages(events)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are helpful."

    def test_system_prompt_only_added_once(self):
        """Multiple system_prompt events only produce one system message."""
        events = [
            TraceEvent(kind="system_prompt", data={"text": "You are helpful."}),
            TraceEvent(kind="system_prompt", data={"text": "Also be concise."}),
            TraceEvent(kind="user_message", data={"text": "Hi"}),
        ]
        msgs = reconstruct_messages(events)
        system_msgs = [m for m in msgs if m["role"] == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0]["content"] == "You are helpful."

    def test_llm_call_produces_assistant_message_with_text(self):
        """llm_call with response_text produces assistant content."""
        events = [
            TraceEvent(kind="user_message", data={"text": "Capital of France?"}),
            TraceEvent(kind="llm_call", data={"response_text": "Paris"}),
        ]
        msgs = reconstruct_messages(events)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "Paris"

    def test_llm_call_with_tool_calls_includes_tool_calls_field(self):
        """llm_call with response_tool_calls includes tool_calls in message."""
        events = [
            TraceEvent(kind="user_message", data={"text": "Search"}),
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
            ),
        ]
        msgs = reconstruct_messages(events)
        assert msgs[1]["role"] == "assistant"
        assert "tool_calls" in msgs[1]
        assert len(msgs[1]["tool_calls"]) == 1
        assert msgs[1]["tool_calls"][0]["function"]["name"] == "web_search"

    def test_tool_call_produces_tool_role_message(self):
        """tool_call event produces a tool role result message."""
        events = [
            TraceEvent(
                kind="tool_call",
                data={
                    "tool_call_id": "call_1",
                    "name": "web_search",
                    "content": '{"results": []}',
                },
            ),
        ]
        msgs = reconstruct_messages(events)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "call_1"
        assert msgs[0]["name"] == "web_search"

    def test_llm_call_without_text_or_tool_calls_has_empty_content(self):
        """An llm_call with neither text nor tool_calls gets empty string."""
        events = [
            TraceEvent(kind="llm_call", data={}),
        ]
        msgs = reconstruct_messages(events)
        assert msgs[0]["role"] == "assistant"
        assert msgs[0]["content"] == ""

    def test_final_response_appended_if_last_not_assistant(self):
        """final_response event adds a trailing assistant message."""
        events = [
            TraceEvent(kind="user_message", data={"text": "Hi"}),
            TraceEvent(kind="final_response", data={"text": "Hello!"}),
        ]
        msgs = reconstruct_messages(events)
        assert len(msgs) == 2
        assert msgs[-1]["role"] == "assistant"
        assert msgs[-1]["content"] == "Hello!"

    def test_final_response_not_duplicated_if_last_is_assistant(self):
        """final_response skipped when last message is already assistant."""
        events = [
            TraceEvent(kind="llm_call", data={"response_text": "Already done"}),
            TraceEvent(kind="final_response", data={"text": "Should not appear"}),
        ]
        msgs = reconstruct_messages(events)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Already done"

    def test_full_conversation_flow(self):
        """A realistic sequence produces correct message types."""
        events = [
            TraceEvent(kind="system_prompt", data={"text": "You are a helpful assistant."}),
            TraceEvent(kind="user_message", data={"text": "What's the weather?"}),
            TraceEvent(
                kind="llm_call",
                data={
                    "response_text": "",
                    "response_tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "London"}',
                            },
                        }
                    ],
                },
            ),
            TraceEvent(
                kind="tool_call",
                data={
                    "tool_call_id": "call_1",
                    "name": "get_weather",
                    "content": '{"temp": 15, "condition": "cloudy"}',
                },
            ),
            TraceEvent(
                kind="llm_call",
                data={"response_text": "It's 15°C and cloudy in London."},
            ),
            TraceEvent(kind="final_response", data={"text": "It's 15°C and cloudy in London."}),
        ]
        msgs = reconstruct_messages(events)
        assert len(msgs) == 5
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"
        assert msgs[2]["role"] == "assistant"
        assert "tool_calls" in msgs[2]
        assert msgs[3]["role"] == "tool"
        assert msgs[3]["name"] == "get_weather"
        assert msgs[4]["role"] == "assistant"
        assert msgs[4]["content"] == "It's 15°C and cloudy in London."


class TestFormatMessages:
    """format_messages produces valid Python literal string."""

    def test_empty_list_produces_empty_list_literal(self):
        """Empty message list becomes '[]'."""
        result = format_messages([])
        assert result == "[]"

    def test_single_message_is_valid_json(self):
        """A single message is valid JSON."""
        msgs = [{"role": "user", "content": "hello"}]
        result = format_messages(msgs)
        import json
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["role"] == "user"


class TestCountHelpers:
    """count_llm_calls and count_tool_calls."""

    def test_count_llm_calls(self):
        events = [
            TraceEvent(kind="llm_call", data={}),
            TraceEvent(kind="tool_call", data={}),
            TraceEvent(kind="llm_call", data={}),
        ]
        assert count_llm_calls(events) == 2

    def test_count_tool_calls(self):
        events = [
            TraceEvent(kind="llm_call", data={}),
            TraceEvent(kind="tool_call", data={}),
            TraceEvent(kind="tool_call", data={}),
            TraceEvent(kind="final_response", data={}),
        ]
        assert count_tool_calls(events) == 2

    def test_zero_when_no_matching_events(self):
        events = [TraceEvent(kind="user_message", data={})]
        assert count_llm_calls(events) == 0
        assert count_tool_calls(events) == 0


class TestGenerateTraceProgram:
    """generate_trace_program emits a valid .py file."""

    def test_generates_file_at_expected_path(self):
        """The function writes a .py file and returns its absolute path."""
        events = [TraceEvent(kind="user_message", data={"text": "hello"})]
        path = generate_trace_program(
            events,
            session_id="test_generation_001",
            model="m",
            provider="p",
            system_prompt="Be helpful",
            user_message="hello",
            final_response="Hi there!",
        )
        assert isinstance(path, str)
        filepath = Path(path)
        assert filepath.exists()
        assert filepath.suffix == ".py"
        assert "test_generation_001" in filepath.name

    def test_generated_file_is_valid_python_syntax(self):
        """The generated file can be parsed by ast.parse."""
        events = [
            TraceEvent(kind="system_prompt", data={"text": "You are helpful."}),
            TraceEvent(kind="user_message", data={"text": "What is 2+2?"}),
            TraceEvent(kind="llm_call", data={"response_text": "4"}),
            TraceEvent(kind="final_response", data={"text": "4"}),
        ]
        path = generate_trace_program(
            events,
            session_id="test_syntax_001",
            model="deepseek/deepseek-v4-flash",
            provider="openrouter",
            system_prompt="You are helpful.",
            user_message="What is 2+2?",
            final_response="4",
        )
        with open(path) as f:
            code = f.read()
        tree = ast.parse(code)
        assert isinstance(tree, ast.Module)

    def test_generated_file_contains_expected_sections(self):
        """The generated file has the main structural markers."""
        events = [
            TraceEvent(kind="user_message", data={"text": "hello"}),
        ]
        path = generate_trace_program(
            events,
            session_id="test_sections",
        )
        with open(path) as f:
            code = f.read()
        assert "Generated by hermes-unroll" in code
        assert "session test_sections" in code
        assert "CONVERSATION_HISTORY" in code

    def test_empty_events_produces_minimal_file(self):
        """With no events, the file still has the header and empty history."""
        path = generate_trace_program(
            [],
            session_id="empty_session",
            model="m",
            provider="p",
        )
        with open(path) as f:
            code = f.read()
        assert "CONVERSATION_HISTORY = []" in code
        assert ast.parse(code) is not None

    def test_cleanup_traces(self):
        """Remove generated trace files after test."""
        # No-op — we generate to TRACES_DIR which is fine
