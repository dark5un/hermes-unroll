"""Tests for the hermes-unroll tracer module."""

import time

from tracer import TraceEvent, TraceRecorder, TraceSession


class TestTraceEvent:
    """TraceEvent dataclass behaviour."""

    def test_creates_with_kind_and_data(self):
        """A TraceEvent can be created with kind, data, and auto-timestamp."""
        event = TraceEvent(kind="llm_call", data={"model": "gpt-4"})
        assert event.kind == "llm_call"
        assert event.data["model"] == "gpt-4"
        assert isinstance(event.timestamp, float)
        assert event.timestamp > 0

    def test_default_timestamp_is_current_time(self):
        """Without an explicit timestamp, it defaults to roughly now."""
        before = time.time()
        event = TraceEvent(kind="user_message", data={"text": "hello"})
        after = time.time()
        assert before <= event.timestamp <= after

    def test_explicit_timestamp_is_honoured(self):
        """Passing timestamp as keyword arg overrides the default."""
        marker = 1234567890.0
        event = TraceEvent(
            kind="tool_call", data={"name": "read"}, timestamp=marker
        )
        assert event.timestamp == marker

    def test_empty_data_defaults_to_empty_dict(self):
        """data defaults to empty dict when not provided."""
        event = TraceEvent(kind="final_response")
        assert event.data == {}

    def test_all_event_kinds_are_accepted(self):
        """The enumerated kinds from the spec all work."""
        kinds = [
            "llm_call",
            "tool_call",
            "subagent_start",
            "subagent_stop",
            "system_prompt",
            "user_message",
            "interrupt",
            "guardrail",
            "retry",
            "compression",
            "error",
            "final_response",
        ]
        for kind in kinds:
            event = TraceEvent(kind=kind)
            assert event.kind == kind


class TestTraceSession:
    """TraceSession container behaviour."""

    def test_default_values_on_empty_session(self):
        """Fresh session has sensible defaults."""
        session = TraceSession(
            session_id="test_001", model="m", provider="p"
        )
        assert session.session_id == "test_001"
        assert session.model == "m"
        assert session.provider == "p"
        assert session.events == []
        assert session.system_prompt == ""
        assert session.initial_user_message == ""
        assert session.final_response == ""
        assert session.completed is False
        assert session.total_api_calls == 0
        assert session.total_tokens_in == 0
        assert session.total_tokens_out == 0
        assert session.started_at > 0

    def test_events_can_be_appended(self):
        """Events list supports append."""
        session = TraceSession(
            session_id="test_002", model="m", provider="p"
        )
        e1 = TraceEvent(kind="user_message", data={"text": "hi"})
        e2 = TraceEvent(kind="llm_call", data={"response_text": "hello"})
        session.events.append(e1)
        session.events.append(e2)
        assert len(session.events) == 2
        assert session.events[0].kind == "user_message"
        assert session.events[1].kind == "llm_call"

    def test_default_events_is_empty_list(self):
        """Without explicit events, the list is empty, not None."""
        session = TraceSession(
            session_id="test_003", model="m", provider="p"
        )
        assert session.events == []


class TestTraceRecorder:
    """TraceRecorder orchestration behaviour."""

    def test_record_appends_event(self):
        """After record(), events list has one entry."""
        r = TraceRecorder()
        r.record("llm_call", {"model": "gpt-4"})
        assert len(r.session.events) == 1
        assert r.session.events[0].kind == "llm_call"

    def test_record_multiple_events(self):
        """Multiple record() calls accumulate in order."""
        r = TraceRecorder()
        r.record("system_prompt", {"text": "You are helpful"})
        r.record("user_message", {"text": "Hi"})
        r.record("llm_call", {"response_text": "Hello"})
        assert len(r.session.events) == 3
        assert [e.kind for e in r.session.events] == [
            "system_prompt",
            "user_message",
            "llm_call",
        ]

    def test_set_metadata_updates_session_fields(self):
        """set_metadata maps named args to session attributes."""
        r = TraceRecorder()
        r.set_metadata(
            session_id="s1",
            model="deepseek/deepseek-v4-flash",
            provider="openrouter",
            system_prompt="You are a helpful assistant.",
            user_message="What time is it?",
        )
        s = r.session
        assert s.session_id == "s1"
        assert s.model == "deepseek/deepseek-v4-flash"
        assert s.provider == "openrouter"
        assert s.system_prompt == "You are a helpful assistant."
        assert s.initial_user_message == "What time is it?"

    def test_finalize_returns_events_list(self):
        """finalize() returns the session events."""
        r = TraceRecorder()
        r.record("system_prompt", {"text": "be helpful"})
        r.record("user_message", {"text": "hello"})
        events = r.finalize()
        assert isinstance(events, list)
        assert len(events) == 2
        assert events[0].kind == "system_prompt"

    def test_finalize_seals_recorder_and_returns_copy(self):
        """finalize seals the recorder: idempotent, post records dropped."""
        r = TraceRecorder()
        r.record("llm_call", {})
        events1 = r.finalize()
        events2 = r.finalize()
        assert events1 == events2 and events1 is not events2  # copy, idempotent
        r.record("llm_call", {"response_text": "late"})
        assert len(r.session.events) == 1  # late record dropped
        assert r.finalized is True

    def test_recorder_starts_with_empty_session_fields(self):
        """Initial session has empty ID/model/provider before set_metadata."""
        r = TraceRecorder()
        assert r.session.session_id == ""
        assert r.session.model == ""
        assert r.session.provider == ""

    def test_can_record_diverse_event_types(self):
        """record handles all spec event kinds without error."""
        r = TraceRecorder()
        kinds = [
            ("system_prompt", {"text": ""}),
            ("user_message", {"text": ""}),
            ("llm_call", {"response_text": ""}),
            ("tool_call", {"name": "search", "args": {}, "result": ""}),
            ("error", {"message": "timeout"}),
            ("final_response", {"text": "done"}),
            ("subagent_start", {"goal": "do it"}),
            ("subagent_stop", {"result": "ok"}),
        ]
        for kind, data in kinds:
            r.record(kind, data)
        assert len(r.session.events) == 8
        assert [e.kind for e in r.session.events] == [
            "system_prompt",
            "user_message",
            "llm_call",
            "tool_call",
            "error",
            "final_response",
            "subagent_start",
            "subagent_stop",
        ]

class TestSessionTags:
    """Session-level tags (C2-a capture side)."""

    def test_tags_default_empty(self):
        session = TraceSession(session_id="t", model="m", provider="p")
        assert session.tags == []

    def test_set_metadata_with_tags_round_trips(self):
        r = TraceRecorder()
        r.set_metadata(session_id="t", tags=["team-a", "feat-x"])
        assert r.session.tags == ["team-a", "feat-x"]

    def test_set_metadata_without_tags_keeps_default(self):
        r = TraceRecorder()
        r.set_metadata(session_id="t")
        assert r.session.tags == []
