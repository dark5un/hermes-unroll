"""Hermes plugin entry point for hermes-unroll.

Subscribes to hooks and wires the tracer to the code generator.
"""

import logging

from hermes_unroll.generator import generate_trace_program
from hermes_unroll.tracer import TraceRecorder

logger = logging.getLogger("hermes-unroll")

# Module-level recorder; one per active session.
_recorder: TraceRecorder | None = None
_session_id: str = ""
_model: str = ""
_provider: str = ""


def _on_post_llm_call(
    session_id: str,
    assistant_response: str,
    conversation_history: list,
    model: str,
    platform: str,
    **kwargs,
):
    """Hook: fires after each successful LLM call turn.

    Records the system prompt (first occurrence only), the user message,
    the assistant response, and any tool calls embedded in the conversation
    history.
    """
    global _session_id, _model, _provider
    if _recorder is None:
        return

    # Set metadata on first call
    if not _session_id:
        _session_id = session_id
        _model = model
        _provider = platform
        _recorder.set_metadata(
            session_id=session_id,
            model=model,
            provider=platform,
        )

        # Walk the conversation history for the system prompt and first user message
        for msg in conversation_history:
            if msg.get("role") == "system" and not _recorder.session.system_prompt:
                _recorder.session.system_prompt = msg.get("content", "")
                _recorder.record("system_prompt", {"text": msg.get("content", "")})
            if msg.get("role") == "user" and not _recorder.session.initial_user_message:
                _recorder.session.initial_user_message = msg.get("content", "")
                _recorder.record("user_message", {"text": msg.get("content", "")})
            if _recorder.session.system_prompt and _recorder.session.initial_user_message:
                break

    # Record the LLM response
    # Extract tool_calls from the last assistant message in conversation_history
    tool_calls = []
    for msg in reversed(conversation_history):
        if msg.get("role") == "assistant":
            tool_calls = msg.get("tool_calls", [])
            break

    _recorder.record("llm_call", {
        "response_text": assistant_response,
        "response_tool_calls": tool_calls or [],
        "model": model,
        "provider": platform,
    })


def _on_post_tool_call(
    tool_name: str,
    args: dict,
    result: str,
    task_id: str,
    duration_ms: int,
    **kwargs,
):
    """Hook: fires after each tool returns.

    Records the tool name, arguments, result, and duration.
    """
    if _recorder is None:
        return

    _recorder.record("tool_call", {
        "name": tool_name,
        "args": args,
        "content": result,
        "tool_call_id": task_id,
        "duration_ms": duration_ms,
    })


def _on_session_end(
    session_id: str,
    completed: bool,
    interrupted: bool,
    model: str,
    platform: str,
    **kwargs,
):
    """Hook: fires when a session ends.

    Compiles the accumulated trace into a .py file.
    """
    global _recorder, _session_id
    if _recorder is None:
        return

    # Finalise metadata
    _recorder.session.completed = completed and not interrupted
    _recorder.session.final_response = (
        _recorder.session.events[-1].data.get("response_text", "")
        if _recorder.session.events and _recorder.session.events[-1].kind == "llm_call"
        else ""
    )

    events = _recorder.finalize()
    if not events:
        _recorder = None
        return

    try:
        program_path = generate_trace_program(
            events,
            session_id=session_id,
            model=model or _model,
            provider=platform or _provider,
            system_prompt=_recorder.session.system_prompt,
            user_message=_recorder.session.initial_user_message,
            final_response=_recorder.session.final_response,
        )
        logger.info("hermes-unroll: trace written to %s", program_path)
    except BaseException as exc:  # noqa: BLE001
        logger.error("hermes-unroll: failed to generate trace: %s", exc)

    _recorder = None
    _session_id = ""


def register(ctx):
    """Called by Hermes plugin loader on session start."""
    global _recorder
    _recorder = TraceRecorder()

    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)

    logger.info("hermes-unroll: plugin registered")