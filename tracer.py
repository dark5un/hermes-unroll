"""hermes-unroll — trace event accumulator.

TraceEvent, TraceSession, and TraceRecorder for capturing
every decision point in the Hermes agent loop.
"""

import time
from dataclasses import dataclass, field


@dataclass
class TraceEvent:
    """A single decision point in the agent loop."""
    kind: str
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)


@dataclass
class TraceSession:
    """Container for one complete agent session's trace."""
    session_id: str
    model: str
    provider: str
    started_at: float = field(default_factory=time.time)
    events: list[TraceEvent] = field(default_factory=list)
    system_prompt: str = ""
    initial_user_message: str = ""
    final_response: str = ""
    completed: bool = False
    total_api_calls: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    tool_schemas: list = field(default_factory=list)
    provider_config: dict = field(default_factory=dict)
    active_skills: list = field(default_factory=list)
    tags: list = field(default_factory=list)


class TraceRecorder:
    """Accumulates TraceEvents during a session."""

    def __init__(self) -> None:
        self.session = TraceSession(session_id="", model="", provider="")

    def record(self, kind: str, data: dict) -> None:
        """Append a TraceEvent with the given kind and data."""
        self.session.events.append(TraceEvent(kind=kind, data=data or {}))

    def set_metadata(
        self,
        session_id: str = "",
        model: str = "",
        provider: str = "",
        system_prompt: str = "",
        user_message: str = "",
        tags: list | None = None,
    ) -> None:
        """Update session-level metadata fields."""
        self.session.session_id = session_id
        self.session.model = model
        self.session.provider = provider
        self.session.system_prompt = system_prompt
        self.session.initial_user_message = user_message
        if tags is not None:
            self.session.tags = list(tags)

    def finalize(self) -> list[TraceEvent]:
        """Return the accumulated events list."""
        return self.session.events