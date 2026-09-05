"""Hermes plugin entry point for hermes-unroll.

Subscribes to hooks and wires the tracer to the code generator.
Phase 1: 5 hooks (on_session_start, post_llm_call, post_tool_call,
                   on_session_end, on_session_finalize)
Phase 2: +7 hooks (pre_api_request, post_api_request, api_request_error,
                   subagent_start, subagent_stop, on_stream_delta,
                   pre_tool_call)
"""

import json
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
_first_turn = False


def _resolve_traces_dir() -> Path:
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home) / "traces" / "unrolled"
    return Path.home() / ".hermes" / "traces" / "unrolled"


# ---------------------------------------------------------------------------
# Phase 1 hooks
# ---------------------------------------------------------------------------


def _on_post_llm_call(
    session_id: str,
    assistant_response: str,
    conversation_history: list,
    model: str,
    platform: str,
    **kwargs,
):
    """Hook: fires after each successful LLM call turn."""
    global _first_turn
    if _recorder is None:
        return

    if _first_turn:
        _first_turn = False
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

    for msg in reversed(conversation_history):
        if msg.get("role") == "user":
            _recorder.record("user_message", {"text": msg.get("content", "")})
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
    """Generate the trace file from ALL accumulated events so far."""
    global _session_id
    if _recorder is None:
        return

    from generator import generate_trace_program

    _recorder.session.completed = completed
    _recorder.session.final_response = (
        _recorder.session.events[-1].data.get("response_text", "")
        if _recorder.session.events and _recorder.session.events[-1].kind == "llm_call"
        else ""
    )

    events = _recorder.finalize()
    if not events:
        return

    # B2: redact secrets from every event before generation (fail-open).
    try:
        from redact import redact_event

        _redacted = []
        for _e in events:
            try:
                _redacted.append(redact_event(_e))
            except Exception:  # noqa: BLE001
                _redacted.append(_e)
        events = _redacted
    except Exception:  # noqa: BLE001, S110
        pass

    # B2: cost ledger — summed usage x model pricing (fail-open).
    cost_usd = 0.0
    try:
        from pricing import estimate_cost

        _tin = 0
        _tout = 0
        for _e in events:
            if _e.kind == "post_api_request":
                _u = _e.data.get("usage", {}) or {}
                _tin += _u.get("input_tokens", 0) or 0
                _tout += _u.get("output_tokens", 0) or 0
        cost_usd = estimate_cost(_model or _recorder.session.model, _tin, _tout)
    except Exception:  # noqa: BLE001
        cost_usd = 0.0

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
            started_at=_recorder.session.started_at,
            cost_usd=cost_usd,
            active_skills=list(
                getattr(_recorder.session, "active_skills", None) or []
            ),
            tags=list(getattr(_recorder.session, "tags", None) or []),
        )
        logger.info("hermes-unroll: trace written to %s", program_path)
        # Guarded Pulse auto-score (G5 init-part): opt-in via
        # unroll.pulse_auto_score (default false). Never breaks traces.
        pulse_enabled = False
        try:
            env_raw = os.environ.get("UNROLL_PULSE_AUTO_SCORE")
            if env_raw is not None:
                pulse_enabled = env_raw.strip().lower() in (
                    "1", "true", "yes", "on",
                )
            else:
                get_config = globals().get("get_config")
                if callable(get_config):
                    try:
                        pulse_enabled = bool(
                            get_config("unroll.pulse_auto_score", False)
                        )
                    except TypeError:
                        try:
                            pulse_enabled = bool(
                                get_config("unroll.pulse_auto_score")
                            )
                        except Exception:  # noqa: BLE001
                            pulse_enabled = False
                    except Exception:  # noqa: BLE001
                        pulse_enabled = False
        except Exception:  # noqa: BLE001
            pulse_enabled = False
        if pulse_enabled:
            try:
                import importlib

                pulse_mod = importlib.import_module("pulse")
                score_fn = pulse_mod.score_session
                score = score_fn(events)
                if isinstance(score, dict):
                    payload = dict(score)
                else:
                    payload = {"pulse_score": score}
                sidecar_path = Path(str(program_path) + ".pulse.json")
                sidecar_path.write_text(
                    json.dumps(payload, indent=2), encoding="utf-8"
                )
                logger.info(
                    "hermes-unroll: pulse sidecar written to %s", sidecar_path
                )
            except ImportError:
                pass
            except Exception as exc:  # noqa: BLE001
                logger.warning("hermes-unroll: pulse auto-score failed: %s", exc)
    except BaseException as exc:  # noqa: BLE001
        logger.error("hermes-unroll: failed to generate trace: %s", exc)

    _session_id = session_id or _session_id


def _session_tags_from_env() -> list[str]:
    """Read session tags from env. UNROLL_ prefix wins, HERMES_ is legacy fallback."""
    raw = os.environ.get("UNROLL_SESSION_TAGS", "") or os.environ.get(
        "HERMES_SESSION_TAGS", ""
    )
    return [t.strip() for t in raw.split(",") if t.strip()]


def _on_session_start(
    session_id: str,
    model: str,
    platform: str,
    **kwargs,
):
    """Hook: fires when a new session is created."""
    global _recorder, _session_id, _model, _provider, _first_turn
    from tracer import TraceRecorder

    _recorder = TraceRecorder()
    _recorder.session.tags = _session_tags_from_env()
    _session_id = session_id
    _model = model
    _provider = platform
    _first_turn = True


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


# ---------------------------------------------------------------------------
# Phase 2 hooks — Enhanced Trace Depth
# ---------------------------------------------------------------------------


def _on_pre_api_request(
    session_id: str,
    model: str,
    provider: str,
    request_messages: list,
    conversation_history: list,
    user_message: str,
    api_call_count: int,
    retry_count: int,
    approx_input_tokens: int | None,
    message_count: int,
    tool_count: int,
    **kwargs,
):
    """Hook: fires before each API request to the LLM.

    Captures the request payload as sent to the provider.
    """
    if _recorder is None:
        return

    _recorder.record("pre_api_request", {
        "model": model,
        "provider": provider,
        "request_messages": request_messages,
        "user_message": user_message,
        "api_call_count": api_call_count,
        "retry_count": retry_count,
        "approx_input_tokens": approx_input_tokens,
        "message_count": message_count,
        "tool_count": tool_count,
    })

    # B1: snapshot tool schemas + provider routing on FIRST pre_api_request
    # per session only. Fail-open: missing request key must never raise.
    try:
        request = kwargs.get("request") or {}
        system_prompt = kwargs.get("system_prompt") or ""
        if system_prompt and not _recorder.session.system_prompt:
            _recorder.session.system_prompt = system_prompt
        already = any(e.kind == "tool_schemas" for e in _recorder.session.events)
        if not already:
            body = request.get("body") or {} if isinstance(request, dict) else {}
            tools = body.get("tools") or [] if isinstance(body, dict) else []
            _recorder.session.tool_schemas = list(tools)
            _recorder.session.provider_config = {
                "provider": provider,
                "base_url": kwargs.get("base_url", ""),
                "api_mode": kwargs.get("api_mode", ""),
                "model": model,
            }
            _recorder.record("tool_schemas", {
                "tools": list(tools),
                "tool_count": tool_count,
            })
    except Exception:  # noqa: BLE001, S110
        pass


def _on_post_api_request(
    session_id: str,
    model: str,
    provider: str,
    api_duration: float,
    finish_reason: str | None,
    usage: dict | None,
    response: dict | None,
    assistant_message: object | None,
    assistant_content_chars: int,
    assistant_tool_call_count: int,
    api_call_count: int,
    **kwargs,
):
    """Hook: fires after each API request completes.

    Captures raw response, usage metrics, finish reason, and duration.
    Extracts thinking/reasoning blocks from the assistant message.
    """
    if _recorder is None:
        return

    # Extract reasoning/thinking content from the assistant message
    thinking_content = None
    reasoning_content = None
    if assistant_message is not None:
        thinking_content = getattr(assistant_message, "thinking", None) or ""
        reasoning_content = getattr(
            assistant_message, "reasoning_content", None
        ) or ""

    _recorder.record("post_api_request", {
        "model": model,
        "provider": provider,
        "api_duration_ms": int(api_duration * 1000) if api_duration else None,
        "finish_reason": finish_reason,
        "usage": usage or {},
        "assistant_content_chars": assistant_content_chars,
        "assistant_tool_call_count": assistant_tool_call_count,
        "api_call_count": api_call_count,
        "thinking_content": thinking_content,
        "reasoning_content": reasoning_content,
    })

    # Update session-level token accounting
    if usage:
        _recorder.session.total_api_calls += 1
        _recorder.session.total_tokens_in += usage.get("input_tokens", 0) or 0
        _recorder.session.total_tokens_out += usage.get("output_tokens", 0) or 0


def _on_api_request_error(
    session_id: str,
    model: str,
    provider: str,
    api_call_count: int,
    api_duration: float,
    status_code: int | None,
    retry_count: int | None,
    max_retries: int | None,
    retryable: bool | None,
    reason: str | None,
    error: dict | None,
    **kwargs,
):
    """Hook: fires when an API request fails."""
    if _recorder is None:
        return

    _recorder.record("api_request_error", {
        "model": model,
        "provider": provider,
        "api_call_count": api_call_count,
        "api_duration_ms": int(api_duration * 1000) if api_duration else None,
        "status_code": status_code,
        "retry_count": retry_count,
        "max_retries": max_retries,
        "retryable": retryable,
        "reason": reason,
        "error": error,
    })


def _on_stream_delta(
    session_id: str,
    delta: str,
    kind: str,
    **kwargs,
):
    """Hook: fires for each streamed text delta.

    Captures the raw streaming output for exact token reconstruction.
    """
    if _recorder is None:
        return

    _recorder.record("on_stream_delta", {
        "delta": delta,
        "kind": kind,
    })


def _on_subagent_start(
    parent_session_id: str | None,
    child_session_id: str | None,
    child_subagent_id: str | None,
    child_role: str | None,
    child_goal: str | None,
    **kwargs,
):
    """Hook: fires when a subagent is spawned."""
    if _recorder is None:
        return

    _recorder.record("subagent_start", {
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "child_subagent_id": child_subagent_id,
        "child_role": child_role,
        "child_goal": child_goal,
    })


def _on_subagent_stop(
    parent_session_id: str | None,
    child_session_id: str | None,
    child_role: str | None,
    child_summary: str | None,
    **kwargs,
):
    """Hook: fires when a subagent completes."""
    if _recorder is None:
        return

    _recorder.record("subagent_stop", {
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "child_role": child_role,
        "child_summary": child_summary,
    })


def _on_pre_tool_call(
    tool_name: str,
    args: dict,
    task_id: str,
    **kwargs,
):
    """Hook: fires before a tool executes.

    Captures the tool name and arguments before execution for guardrail
    interception records.
    """
    if _recorder is None:
        return

    _recorder.record("pre_tool_call", {
        "name": tool_name,
        "args": args,
        "task_id": task_id,
    })

    # S2: ACTIVE_SKILLS capture — skill_view views mark a skill active.
    # Fail-open: never let bookkeeping break the tool path.
    try:
        if tool_name == "skill_view":
            a = args if isinstance(args, dict) else {}
            name = a.get("name")
            file_path = a.get("file_path", "")
            if name and isinstance(name, str):
                skills = getattr(_recorder.session, "active_skills", None)
                if not isinstance(skills, list):
                    skills = []
                    _recorder.session.active_skills = skills
                if name not in skills:
                    skills.append(name)
                _recorder.record("skill_view", {
                    "name": name,
                    "file_path": file_path or "",
                })
    except Exception:  # noqa: BLE001, S110
        pass


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(ctx):
    """Called by Hermes plugin loader on session start."""
    _plugin_dir = str(Path(__file__).resolve().parent)
    if _plugin_dir not in sys.path:
        sys.path.insert(0, _plugin_dir)

    # Phase 1: session lifecycle hooks
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_hook("on_session_finalize", _on_session_finalize)

    # Phase 2: enhanced trace depth hooks
    ctx.register_hook("pre_api_request", _on_pre_api_request)
    ctx.register_hook("post_api_request", _on_post_api_request)
    ctx.register_hook("api_request_error", _on_api_request_error)
    ctx.register_hook("subagent_start", _on_subagent_start)
    ctx.register_hook("subagent_stop", _on_subagent_stop)
    ctx.register_hook("on_stream_delta", _on_stream_delta)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)

    logger.info("hermes-unroll: plugin registered (12 hooks)")