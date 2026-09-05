"""Hermes plugin entry point for hermes-unroll.

Subscribes to hooks and wires the tracer to the code generator.
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("hermes-unroll")

# Module-level recorder; one per active session.
_recorder = None
_session_id = ""
_model = ""
_provider = ""


def _resolve_traces_dir() -> Path:
    """Resolve output dir respecting $HERMES_HOME."""
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home) / "traces" / "unrolled"
    return Path.home() / ".hermes" / "traces" / "unrolled"


def _on_post_llm_call(
    session_id: str,
    assistant_response: str,
    conversation_history: list,
    model: str,
    platform: str,
    **kwargs,
):
    """Hook: fires after each successful LLM call turn."""
    global _session_id, _model, _provider
    if _recorder is None:
        return

    if not _session_id:
        _session_id = session_id
        _model = model
        _provider = platform
        _recorder.set_metadata(
            session_id=session_id,
            model=model,
            provider=platform,
        )

        for msg in conversation_history:
            if msg.get("role") == "system" and not _recorder.session.system_prompt:
                _recorder.session.system_prompt = msg.get("content", "")
                _recorder.record("system_prompt", {"text": msg.get("content", "")})
            if msg.get("role") == "user" and not _recorder.session.initial_user_message:
                _recorder.session.initial_user_message = msg.get("content", "")
                _recorder.record("user_message", {"text": msg.get("content", "")})
            if _recorder.session.system_prompt and _recorder.session.initial_user_message:
                break

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
    """Hook: fires after each tool returns."""
    if _recorder is None:
        return

    _recorder.record("tool_call", {
        "name": tool_name,
        "args": args,
        "content": result,
        "tool_call_id": task_id,
        "duration_ms": duration_ms,
    })


def _generate_trace(session_id: str, completed: bool = True):
    """Generate the trace file from accumulated events."""
    global _recorder, _session_id
    if _recorder is None:
        return

    # Lazy import to keep __init__.py importable without sibling modules
    from generator import generate_trace_program

    _recorder.session.completed = completed
    _recorder.session.final_response = (
        _recorder.session.events[-1].data.get("response_text", "")
        if _recorder.session.events and _recorder.session.events[-1].kind == "llm_call"
        else ""
    )

    events = _recorder.finalize()
    if not events:
        _recorder = None
        _session_id = ""
        return

    traces_dir = _resolve_traces_dir()
    try:
        traces_dir.mkdir(parents=True, exist_ok=True)
        program_path = generate_trace_program(
            events,
            session_id=session_id or _session_id,
            model=_model,
            provider=_provider,
            system_prompt=_recorder.session.system_prompt,
            user_message=_recorder.session.initial_user_message,
            final_response=_recorder.session.final_response,
        )
        logger.info("hermes-unroll: trace written to %s", program_path)
    except BaseException as exc:  # noqa: BLE001
        logger.error("hermes-unroll: failed to generate trace: %s", exc)

    _recorder = None
    _session_id = ""


def _on_session_end(
    session_id: str,
    completed: bool,
    interrupted: bool,
    model: str,
    platform: str,
    **kwargs,
):
    """Hook: fires at end of every run_conversation call + CLI exit."""
    _generate_trace(session_id, completed=completed and not interrupted)


def _on_session_finalize(
    session_id: str | None,
    platform: str,
    **kwargs,
):
    """Hook: fires when CLI/gateway tears down an active session."""
    if _recorder is not None and _recorder.session.events:
        _generate_trace(session_id or _session_id)


def register(ctx):
    """Called by Hermes plugin loader on session start."""
    global _recorder

    # Ensure the plugin directory is on sys.path so sibling modules import
    _plugin_dir = str(Path(__file__).resolve().parent)
    if _plugin_dir not in sys.path:
        sys.path.insert(0, _plugin_dir)

    from tracer import TraceRecorder

    _recorder = TraceRecorder()

    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("on_session_finalize", _on_session_finalize)

    logger.info("hermes-unroll: plugin registered")