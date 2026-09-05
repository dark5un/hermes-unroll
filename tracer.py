"""hermes-unroll — trace event accumulator.

TraceEvent, TraceSession, and TraceRecorder for capturing
every decision point in the Hermes agent loop.
"""

import itertools
import time
from dataclasses import dataclass, field

# Process-wide monotonic counter backing stable event ids.
_event_counter = itertools.count()


@dataclass
class TraceEvent:
    """A single decision point in the agent loop.

    ``event_id`` is assigned at record time and is the stable identity
    for replay cache keys and emitted steps — never a positional index.
    """

    kind: str
    timestamp: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)
    event_id: str = ""


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
        self.finalized = False

    def record(self, kind: str, data: dict, event_id: str = "") -> TraceEvent:
        """Append a TraceEvent with the given kind and data.

        Assigns a stable ``event_id`` (``f"{kind}-{n}"`` from a monotonic
        counter) unless the caller supplies one (e.g. the host's
        ``tool_call_id``/``turn_id``). After finalize() the recorder is
        sealed: further records are dropped so post-finalize hooks cannot
        leak events into an already-written trace. Returns the event.
        """
        if self.finalized:
            return TraceEvent(kind=kind, data=data or {}, event_id=event_id)
        event = TraceEvent(
            kind=kind, data=data or {}, event_id=event_id or f"{kind}-{next(_event_counter)}"
        )
        self.session.events.append(event)
        return event

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
        """Return a copy of the accumulated events and seal the recorder."""
        self.finalized = True
        return list(self.session.events)
