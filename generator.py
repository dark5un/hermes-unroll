"""Code generator: TraceEvent[] -> runnable .py file.

Phases 1-4:
Phase 1: Basic step-by-step replay with timing and structured JSON.
Phase 2: Reasoning/thinking blocks, usage metadata, enhanced event types.
Phase 3: Response cache, CLI flags (--stop-at, --substitute-tool, --show-state, --diff, --live).
Phase 4: Counterfactual engine (--edit mode, dependency tracking).
"""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any


def _get_traces_dir() -> Path:
    hermes_home = os.environ.get("HERMES_HOME")
    if hermes_home:
        return Path(hermes_home) / "traces" / "unrolled"
    return Path.home() / ".hermes" / "traces" / "unrolled"


def generate_trace_program(
    events: list,
    session_id: str = "",
    model: str = "",
    provider: str = "",
    system_prompt: str = "",
    user_message: str = "",
    final_response: str = "",
    started_at: float = 0,
) -> str:
    """Compile events into a Hermes-independent replay program."""
    traces_dir = _get_traces_dir()
    traces_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_filename(session_id or 'unsaved')}.py"
    filepath = traces_dir / filename

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    messages = reconstruct_messages(events)
    tl = _build_timeline(events, started_at)

    code = _build_program_text(
        session_id=session_id,
        timestamp=ts,
        model=model,
        provider=provider,
        events=events,
        messages=messages,
        timeline=tl,
        system_prompt=system_prompt,
        final_response=final_response,
        started_at=started_at,
    )

    filepath.write_text(code, encoding="utf-8")
    return str(filepath.resolve())


def _build_timeline(events: list, started_at: float) -> list[dict]:
    tl = []
    for e in events:
        entry: dict[str, Any] = {"kind": e.kind}
        if started_at and e.timestamp:
            entry["offset_ms"] = int((e.timestamp - started_at) * 1000)
        if e.kind in ("tool_call", "llm_call", "pre_api_request",
                       "post_api_request", "api_request_error") \
               and "duration_ms" in e.data and e.data["duration_ms"]:
            entry["duration_ms"] = e.data["duration_ms"]
        tl.append(entry)
    return tl


def _build_response_cache(events: list) -> dict:
    """Build a response cache dict for deterministic replay (Phase 3)."""
    cache: dict[str, Any] = {}
    step = 0
    for e in events:
        if e.kind == "llm_call":
            cache[f"llm_{step}"] = {
                "type": "llm_call",
                "response_text": e.data.get("response_text", ""),
                "response_tool_calls": e.data.get("response_tool_calls", []),
            }
            step += 1
        elif e.kind == "tool_call":
            cache[f"tool_{step}"] = {
                "type": "tool_call",
                "result": e.data.get("content", ""),
            }
            step += 1
    return cache


def _build_usage_summary(events: list) -> dict:
    """Aggregate usage stats from events (Phase 2)."""
    total_input = 0
    total_output = 0
    api_calls = 0
    errors = 0
    retries = 0
    for e in events:
        if e.kind == "post_api_request":
            usage = e.data.get("usage", {}) or {}
            total_input += usage.get("input_tokens", 0) or 0
            total_output += usage.get("output_tokens", 0) or 0
            api_calls += 1
        if e.kind == "api_request_error":
            errors += 1
        if e.kind == "pre_api_request":
            retry = e.data.get("retry_count", 0) or 0
            retries = max(retries, retry)
    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_api_calls": api_calls,
        "total_retries": retries,
        "total_errors": errors,
    }


def _build_reasoning_blocks(events: list) -> list[dict]:
    """Extract thinking/reasoning content from post_api_request events (Phase 2)."""
    blocks = []
    for i, e in enumerate(events):
        if e.kind == "post_api_request":
            thinking = (e.data.get("thinking_content", "") or "")[:2000]
            reasoning = (e.data.get("reasoning_content", "") or "")[:2000]
            if thinking or reasoning:
                blocks.append({
                    "event_index": i,
                    "kind": "reasoning_block",
                    "thinking": thinking,
                    "reasoning": reasoning,
                })
    return blocks


def _build_replay_steps(events: list) -> str:
    """Build step-by-step execution code for all 12 event kinds with range guard."""
    steps = ""
    step_num = 0
    for event in events:
        guard = f"    if _from <= {step_num} <= _to:\n        _t0 = time.perf_counter()\n"
        if event.kind == "system_prompt":
            steps += guard
            steps += f"        # Step {step_num}: System prompt (already set)\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"system_prompt\"}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "user_message":
            txt = event.data.get("text", "")
            jtxt = json.dumps(txt, ensure_ascii=False)
            steps += guard
            steps += f"        # Step {step_num}: User message\n"
            steps += f"        messages.append({{\"role\": \"user\", \"content\": {jtxt}}})\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"user_message\", \"text\": {jtxt}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "llm_call":
            txt = event.data.get("response_text", "")
            tcs = event.data.get("response_tool_calls", [])
            steps += guard
            steps += f"        # Step {step_num}: LLM call\n"
            if tcs:
                names = ", ".join(tc.get("function", {}).get("name", "?") for tc in tcs)
                jtcs = json.dumps(tcs, indent=2, ensure_ascii=False)
                jnames = json.dumps(names, ensure_ascii=False)
                steps += f"        # Model requested tool calls: {names}\n"
                steps += f"        msg = {{\"role\": \"assistant\", \"tool_calls\": {jtcs}}}\n"
                steps += "        messages.append(msg)\n"
                steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"llm_call\", \"tool_calls\": {jnames}}})\n"
            else:
                jtxt = json.dumps(txt, ensure_ascii=False)
                steps += f"        msg = {{\"role\": \"assistant\", \"content\": {jtxt}}}\n"
                steps += "        messages.append(msg)\n"
                steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"llm_call\", \"text\": {jtxt}}})\n"
            steps += "\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "tool_call":
            name = event.data.get("name", "")
            content = event.data.get("content", "")
            tid = event.data.get("tool_call_id", "")
            dur = event.data.get("duration_ms")
            jcontent = json.dumps(content, ensure_ascii=False)
            jtid = json.dumps(tid, ensure_ascii=False)
            jname = json.dumps(name, ensure_ascii=False)
            dur_val = dur if dur else "null"
            dur_comment = f"  # {dur}ms" if dur else ""
            steps += guard
            steps += f"        # Step {step_num}: Tool call: {name}{dur_comment}\n"
            steps += f"        messages.append({{\"role\": \"tool\", \"tool_call_id\": {jtid}, \"content\": {jcontent}, \"name\": {jname}}})\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"tool_call\", \"name\": {jname}, \"duration_ms\": {dur_val}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "final_response":
            txt = event.data.get("text", "")
            jtxt = json.dumps(txt, ensure_ascii=False)
            steps += guard
            steps += f"        # Step {step_num}: Final response\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"final_response\", \"text\": {jtxt}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "pre_api_request":
            apic = event.data.get("api_call_count", 0)
            approx = event.data.get("approx_input_tokens", 0) or 0
            rcnt = event.data.get("retry_count", 0) or 0
            steps += guard
            steps += f"        # Step {step_num}: API Request (call #{apic}, retry #{rcnt})\n"
            steps += f"        #   Approx tokens: {approx}\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"pre_api_request\", \"api_call_count\": {apic}, \"approx_input_tokens\": {approx}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "post_api_request":
            fr = event.data.get("finish_reason", "")
            dur_ms = event.data.get("api_duration_ms")
            usage = event.data.get("usage", {}) or {}
            thinking = (event.data.get("thinking_content", "") or "")
            reasoning = (event.data.get("reasoning_content", "") or "")
            durs = f" ({dur_ms}ms)" if dur_ms else ""
            u_in = usage.get("input_tokens", "?")
            u_out = usage.get("output_tokens", "?")
            steps += guard
            steps += f"        # Step {step_num}: API Response{durs}\n"
            steps += f"        #   Finish reason: {fr}\n"
            steps += f"        #   Usage: {u_in} in / {u_out} out\n"
            if thinking:
                jthinking = json.dumps(thinking[:200], ensure_ascii=False)
                steps += f"        #   Thinking: {jthinking}\n"
            if reasoning:
                jreasoning = json.dumps(reasoning[:200], ensure_ascii=False)
                steps += f"        #   Reasoning: {jreasoning}\n"
            jfr = json.dumps(fr, ensure_ascii=False)
            ht = str(bool(thinking) or False)
            ds = dur_ms if dur_ms else "null"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"post_api_request\", \"finish_reason\": {jfr}, \"api_duration_ms\": {ds}, \"has_thinking\": {ht}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "api_request_error":
            status = event.data.get("status_code")
            reason = event.data.get("reason", "")
            steps += guard
            steps += f"        # Step {step_num}: API Error (status={status}, reason={reason})\n"
            jreason = json.dumps(reason or "", ensure_ascii=False)
            ss = status if status is not None else "null"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"api_request_error\", \"status_code\": {ss}, \"reason\": {jreason}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "subagent_start":
            goal = event.data.get("child_goal", "")
            role = event.data.get("child_role", "")
            jgoal = json.dumps(goal, ensure_ascii=False)
            jrole = json.dumps(role, ensure_ascii=False)
            steps += guard
            steps += f"        # Step {step_num}: Subagent Start - {role}\n"
            steps += f"        #   Goal: {jgoal}\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"subagent_start\", \"role\": {jrole}, \"goal\": {jgoal}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "subagent_stop":
            summary = event.data.get("child_summary", "")
            role = event.data.get("child_role", "")
            jrole = json.dumps(role, ensure_ascii=False)
            steps += guard
            steps += f"        # Step {step_num}: Subagent Stop - {role}\n"
            if summary:
                jsummary = json.dumps(summary[:200], ensure_ascii=False)
                steps += f"        #   Summary: {jsummary}\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"subagent_stop\", \"role\": {jrole}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "on_stream_delta":
            delta = event.data.get("delta", "")
            knd = event.data.get("kind", "")
            dlen = len(delta)
            steps += guard
            steps += f"        # Step {step_num}: Stream delta ({knd}) +{dlen} chars\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"stream_delta\", \"len\": {dlen}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
        elif event.kind == "pre_tool_call":
            tname = event.data.get("name", "")
            jtname = json.dumps(tname, ensure_ascii=False)
            steps += guard
            steps += f"        # Step {step_num}: Pre-tool call guard - {tname}\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"pre_tool_call\", \"name\": {jtname}}})\n\n"
            steps += "        _t1 = time.perf_counter()\n"
            steps += "        _rd = round((_t1 - _t0) * 1000)\n"
            steps += "        _ro = round((_t1 - _replay_start) * 1000)\n"
            steps += f"        _tl = TIMELINE[{step_num}] if {step_num} < len(TIMELINE) else {{}}\n"
            steps += "        _oo = _tl.get(\"offset_ms\", 0) or 0\n"
            steps += "        _od = _tl.get(\"duration_ms\")\n"
            steps += "        _kk = _tl.get(\"kind\", \"\")\n"
            steps += "        step_log[-1][\"replay_duration_ms\"] = _rd\n"
            steps += f"        timing_log.append({{\"step\": {step_num}, \"kind\": _kk, \"original_offset_ms\": _oo, \"replay_offset_ms\": _ro, \"delta_ms\": _ro - _oo, \"duration_ms\": _od, \"replay_duration_ms\": _rd}})\n"
            step_num += 1
    return steps


def _build_program_text(
    session_id: str,
    timestamp: str,
    model: str,
    provider: str,
    events: list,
    messages: list[dict],
    timeline: list[dict],
    system_prompt: str,
    final_response: str,
    started_at: float = 0,
) -> str:
    nl = count_llm_calls(events)
    tc = count_tool_calls(events)
    msg_count = len(messages)
    total_duration_ms = 0
    if started_at and events:
        last_ts = max(e.timestamp for e in events if e.timestamp)
        total_duration_ms = int((last_ts - started_at) * 1000)

    replay_steps = _build_replay_steps(events)
    timeline_json = json.dumps(timeline, indent=2, ensure_ascii=False)
    dur_str = _human_duration(total_duration_ms)
    if started_at:
        started_at_iso = datetime.fromtimestamp(started_at, UTC).isoformat()
    else:
        started_at_iso = ""
    usage = _build_usage_summary(events)
    jusage = json.dumps(usage, indent=2)
    rb = _build_reasoning_blocks(events)
    jrb = json.dumps(rb, indent=2, ensure_ascii=False) if rb else "[]"
    cache = _build_response_cache(events)
    jcache = json.dumps(cache, indent=2)

    # The replay func, parse_args func, and human_duration func
    replay_func = _make_replay_function(replay_steps)
    parse_args_func = _make_parse_args_function()
    human_dur_func = _make_human_duration_function()

    # Read template and substitute
    template_path = Path(__file__).resolve().parent / "templates" / "replay_template.py.txt"
    template_src = template_path.read_text(encoding="utf-8")
    t = Template(template_src)

    return t.substitute(
        TIMESTAMP=timestamp,
        SESSION_ID=session_id,
        MODEL=model,
        PROVIDER=provider,
        LLM_NL=str(nl),
        TOOL_TC=str(tc),
        EVENT_N=str(len(events)),
        MSG_CNT=str(msg_count),
        DUR_STR=dur_str,
        JSID=json.dumps(session_id, ensure_ascii=False),
        JMODEL=json.dumps(model, ensure_ascii=False),
        JPROV=json.dumps(provider, ensure_ascii=False),
        JSTARTED=json.dumps(started_at_iso, ensure_ascii=False),
        JSYS=json.dumps(system_prompt, ensure_ascii=False),
        TOTAL_DUR=str(total_duration_ms),
        JEXP=json.dumps(final_response, ensure_ascii=False),
        TIMELINE_JSON=timeline_json,
        JUSAGE=jusage,
        JRB=jrb,
        JCACHE=jcache,
        REPLAY_FUNC=replay_func,
        PARSE_ARGS_FUNC=parse_args_func,
        HUMAN_DUR_FUNC=human_dur_func,
    )


def _make_replay_function(replay_steps_body: str) -> str:
    """Build the replay() function source for the generated program."""
    return f'''def replay(from_step=None, to_step=None):
    """
    Walk through the conversation step by step.
    In dry-run mode (default), responses come from the cache.
    With --live, they come from real LLM calls.

    Args:
        from_step: First step index to execute (inclusive, None = start)
        to_step: Last step index to execute (inclusive, None = end)
    """
    messages: list[dict] = []
    step_log: list[dict] = []
    timing_log: list[dict] = []
    step_num = 0
    _from = from_step if from_step is not None else 0
    _to = to_step if to_step is not None else 999999
    _replay_start = time.perf_counter()

    print(f"Replaying session {{SESSION_ID}}")
    print(f"Model: {{MODEL}}  Provider: {{PROVIDER}}")
    if from_step is not None or to_step is not None:
        _range_desc = f"steps {{_from}}-{{_to}}"
        print(f"Range: {{_range_desc}}")
    print(f"Original: {{len(TIMELINE)}} events, {{len(RESPONSE_CACHE)}} cached steps")
    print(f"Usage: {{USAGE.get('total_api_calls', '?')}} API calls, "
          f"{{_human_duration(USAGE.get('total_input_tokens', 0) // 10)}} input tokens")
    print(f"Total original duration: {{_human_duration(ORIGINAL_DURATION_MS)}}")
    print()
    print("--- Timeline (original) ---")
    for entry in TIMELINE:
        off = entry.get("offset_ms", 0)
        kind = entry["kind"]
        dur = entry.get("duration_ms")
        if dur:
            print(f"  +{{off}}ms  {{kind}}  ({{_human_duration(dur)}})")
        else:
            print(f"  +{{off}}ms  {{kind}}")
    if REASONING_BLOCKS:
        print()
        print("--- Reasoning/Thinking Blocks ---")
        for rb_entry in REASONING_BLOCKS:
            if rb_entry.get("thinking"):
                print(f"  Thinking: {{rb_entry['thinking'][:150]}}...")
            if rb_entry.get("reasoning"):
                print(f"  Reasoning: {{rb_entry['reasoning'][:150]}}...")
    print()
    print("--- Execution ---")

{replay_steps_body}

    print()
    print("--- Done ---")
    print(f"Messages: {{len(messages)}}")
    _replay_end = time.perf_counter()
    _replay_duration_ms = round((_replay_end - _replay_start) * 1000)
    print(f"Timing: {{len(timing_log)}} steps in {{_human_duration(_replay_duration_ms)}} "
          f"(original {{_human_duration(ORIGINAL_DURATION_MS)}})")
    print(f"Replay duration: {{_replay_duration_ms}}ms")

    result = {{
        "session_id": SESSION_ID,
        "model": MODEL,
        "provider": PROVIDER,
        "started_at": STARTED_AT,
        "original_duration_ms": ORIGINAL_DURATION_MS,
        "replay_duration_ms": _replay_duration_ms,
        "messages_count": len(messages),
        "from_step": from_step,
        "to_step": to_step,
        "steps": step_log,
        "messages": messages,
        "usage": USAGE,
        "reasoning_blocks": REASONING_BLOCKS,
        "timing_log": timing_log,
        "response_cache": RESPONSE_CACHE,
    }}
    return result'''


def _make_parse_args_function() -> str:
    """Build the _parse_args() function source for the generated program."""
    return '''\ndef _parse_args():
    parser = argparse.ArgumentParser(
        description="hermes-unroll replayer - reproduces and analyses agent traces"
    )
    parser.add_argument("--live", action="store_true", help="Execute real LLM calls")
    parser.add_argument("--from", dest="from_step", type=int, default=None,
                        help="Start from step N (inclusive)")
    parser.add_argument("--to", dest="to_step", type=int, default=None,
                        help="Stop at step N (inclusive)")
    parser.add_argument("--stop-at", type=int, default=None, help="Stop after N steps")
    parser.add_argument("--substitute-tool", type=str, default=None,
                        help="Replace tool call args: '<step> <json_args>'")
    parser.add_argument("--show-state", action="store_true",
                        help="Print full agent state after each step")
    parser.add_argument("--diff", type=str, default=None,
                        help="Compare with another trace.py file")
    parser.add_argument("--edit", type=str, default=None,
                        help="Counterfactual: change prompt and re-execute")
    return parser.parse_args()'''


def _make_human_duration_function() -> str:
    """Build the _human_duration() helper for the generated program."""
    return '''\ndef _human_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    s = ms / 1000
    if s < 60:
        return f"{s:.1f}s"
    m = int(s // 60)
    s = s % 60
    return f"{m}m {s:.0f}s"'''


def _human_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    s = ms / 1000
    if s < 60:
        return f"{s:.1f}s"
    m = int(s // 60)
    s = s % 60
    return f"{m}m {s:.0f}s"


def safe_filename(session_id: str) -> str:
    sanitized = re.sub(r"[^\w-]", "_", session_id).strip("._")
    return sanitized[:96] or "session"


def reconstruct_messages(events: list) -> list[dict]:
    messages: list[dict[str, Any]] = []
    for event in events:
        if event.kind == "system_prompt":
            if not any(m.get("role") == "system" for m in messages):
                messages.append({"role": "system", "content": event.data.get("text", "")})
        elif event.kind == "user_message":
            messages.append({"role": "user", "content": event.data.get("text", "")})
        elif event.kind == "llm_call":
            msg: dict[str, Any] = {"role": "assistant"}
            text = event.data.get("response_text", "")
            tcs = event.data.get("response_tool_calls", [])
            if text:
                msg["content"] = text
            if tcs:
                msg["tool_calls"] = tcs
            if not text and not tcs:
                msg["content"] = ""
            messages.append(msg)
        elif event.kind == "tool_call":
            entry: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": event.data.get("tool_call_id", ""),
                "content": event.data.get("content", ""),
                "name": event.data.get("name", ""),
            }
            dur = event.data.get("duration_ms")
            if dur:
                entry["duration_ms"] = dur
            messages.append(entry)
        elif event.kind == "final_response" and (not messages or messages[-1].get("role") != "assistant"):
            messages.append({"role": "assistant", "content": event.data.get("text", "")})
    return messages


def format_messages(messages: list[dict]) -> str:
    if not messages:
        return "[]"
    return json.dumps(messages, indent=2, ensure_ascii=False)


def count_llm_calls(events: list) -> int:
    return sum(1 for e in events if e.kind == "llm_call")


def count_tool_calls(events: list) -> int:
    return sum(1 for e in events if e.kind == "tool_call")