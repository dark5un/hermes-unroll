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
    cost_usd: float = 0.0,
    active_skills: list | None = None,
) -> str:
    """Compile events into a Hermes-independent replay program."""
    traces_dir = _get_traces_dir()
    traces_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_filename(session_id or 'unsaved')}.py"
    filepath = traces_dir / filename

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    messages = reconstruct_messages(events)
    tl = _build_timeline(events, started_at)
    skills = _build_active_skills(events, active_skills)

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
        cost_usd=cost_usd,
        active_skills=skills,
    )

    filepath.write_text(code, encoding="utf-8")
    return str(filepath.resolve())


def _event_kind(e) -> str:
    if isinstance(e, dict):
        return str(e.get("kind", "?"))
    return str(getattr(e, "kind", "?"))


def _build_dependency_map(events: list) -> dict[int, list[int]]:
    """Build a step dependency map (Phase E1).

    Rules (step index -> list of dep step indices):
    - llm_call depends on the most recent prior user_message plus all
      prior tool_call steps since that message (or all prior tool_calls
      when no user_message precedes it).
    - tool_call depends on the most recent prior llm_call.
    - final_response depends on the last llm_call.
    - everything else depends on the previous step ([] for step 0).
    """
    kinds = [_event_kind(e) for e in events]
    deps: dict[int, list[int]] = {}
    for i, kind in enumerate(kinds):
        if kind == "llm_call":
            prior_user = -1
            for j in range(i - 1, -1, -1):
                if kinds[j] == "user_message":
                    prior_user = j
                    break
            if prior_user >= 0:
                tools_since = [
                    j for j in range(prior_user + 1, i) if kinds[j] == "tool_call"
                ]
                deps[i] = [prior_user, *tools_since]
            else:
                deps[i] = [j for j in range(i) if kinds[j] == "tool_call"]
        elif kind == "tool_call":
            prev_llm = -1
            for j in range(i - 1, -1, -1):
                if kinds[j] == "llm_call":
                    prev_llm = j
                    break
            deps[i] = [prev_llm] if prev_llm >= 0 else []
        elif kind == "final_response":
            last_llm = -1
            for j in range(i - 1, -1, -1):
                if kinds[j] == "llm_call":
                    last_llm = j
                    break
            if last_llm >= 0:
                deps[i] = [last_llm]
            else:
                deps[i] = [i - 1] if i > 0 else []
        else:
            deps[i] = [i - 1] if i > 0 else []
    return deps


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


def _build_state_graph(events: list, started_at: float = 0) -> dict:
    """Build a state-graph view of the trace (Phase D1).

    Returns {"nodes": [...], "edges": [...], "subgraphs": [...]} where
    nodes carry id/kind/label/original_offset_ms, edges chain consecutive
    steps, and subgraphs link subagent_start -> matching subagent_stop
    by child_role. Accepts dict or attribute events (diff.py duck-typing).
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, int]] = []
    subgraphs: list[dict[str, Any]] = []
    pending: dict[str, list[int]] = {}
    for i, e in enumerate(events):
        if isinstance(e, dict):
            kind = str(e.get("kind", "?"))
            data = e.get("data", {})
            if not isinstance(data, dict):
                data = {"value": data}
            ts = e.get("timestamp")
        else:
            kind = str(getattr(e, "kind", "?"))
            data = getattr(e, "data", {})
            if not isinstance(data, dict):
                data = {"value": data}
            ts = getattr(e, "timestamp", None)
        try:
            ts_f = float(ts) if ts is not None else None
        except (TypeError, ValueError):
            ts_f = None
        if started_at and ts_f is not None:
            offset_ms = int((ts_f - started_at) * 1000)
        else:
            offset_ms = 0
        label = f"{i}: {kind}"
        if kind == "subagent_start":
            role = str(data.get("child_role", ""))
            label = f"{i}: subagent_start:{role}" if role else label
        elif kind == "subagent_stop":
            role = str(data.get("child_role", ""))
            label = f"{i}: subagent_stop:{role}" if role else label
        elif kind == "tool_call":
            name = str(data.get("name", ""))
            label = f"{i}: tool_call:{name}" if name else label
        nodes.append({
            "id": i,
            "kind": kind,
            "label": label,
            "original_offset_ms": offset_ms,
        })
        if kind == "subagent_start":
            role = str(data.get("child_role", ""))
            pending.setdefault(role, []).append(i)
        elif kind == "subagent_stop":
            role = str(data.get("child_role", ""))
            stack = pending.get(role)
            if stack:
                start = stack.pop()
                subgraphs.append({"role": role, "start": start, "stop": i})
    for i in range(len(nodes) - 1):
        edges.append({"from": i, "to": i + 1})
    return {"nodes": nodes, "edges": edges, "subgraphs": subgraphs}


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


def _make_live_helper() -> str:
    """Build the _live_llm_call() helper source for the generated program.

    Default engine: direct ``openai`` SDK, lazily imported
    (``OpenAI(base_url, api_key)`` + ``chat.completions.create`` with
    ``messages`` and ``tools=TOOL_SCHEMAS``). PydanticAI is opt-in behind
    ``engine="pydantic"``. When ``openai`` is not installed, falls back to
    stdlib ``urllib`` POST to ``base_url/chat/completions`` with a Bearer
    key resolved as ``OPENAI_API_KEY`` -> ``HERMES_API_KEY`` -> ``.env``
    file under ``HERMES_HOME`` (or ``~/.hermes``). Returns
    ``(text, tool_calls)``. Never prints API keys.
    """
    return '''
def _load_api_key(explicit=""):
    """Resolve the API key without ever printing it."""
    import os as _os
    from pathlib import Path as _Path
    if explicit:
        return explicit
    for _var in ("OPENAI_API_KEY", "HERMES_API_KEY"):
        _val = _os.environ.get(_var)
        if _val:
            return _val
    _home = _os.environ.get("HERMES_HOME")
    _candidates = []
    if _home:
        _candidates.append(_Path(_home) / ".env")
    _candidates.append(_Path.home() / ".hermes" / ".env")
    for _env_file in _candidates:
        try:
            if _env_file.exists():
                for _line in _env_file.read_text().splitlines():
                    _k, _sep, _v = _line.partition("=")
                    if _k.strip() in ("OPENAI_API_KEY", "HERMES_API_KEY") and _v.strip():
                        return _v.strip().strip("\\'\\"")
        except OSError:
            continue
    raise SystemExit("no API key: set OPENAI_API_KEY/HERMES_API_KEY or ~/.hermes/.env")


def _live_llm_call(messages, model, base_url, api_key="", engine="openai"):
    """Execute a real LLM call. Returns (text, tool_calls)."""
    import json as _json
    if engine == "pydantic":
        try:
            from pydantic_ai import Agent
        except ImportError:
            raise SystemExit("pydantic engine needs the pydantic-ai extra installed")
        _agent = Agent(model="openai:" + model)
        _out = _agent.run_sync(messages)
        return (_out.output if hasattr(_out, "output") else str(_out)), []
    try:
        from openai import OpenAI
    except ImportError:
        import urllib.request as _request
        _key = _load_api_key(api_key)
        _url = (base_url or "").rstrip("/") + "/chat/completions"
        _req = _request.Request(
            _url,
            data=_json.dumps(
                {"model": model, "messages": messages, "tools": TOOL_SCHEMAS}
            ).encode(),
            headers={"Authorization": "Bearer " + _key, "Content-Type": "application/json"},
        )
        _body = _json.load(_request.urlopen(_req, timeout=60))
        _msg = _body["choices"][0]["message"]
        return _msg.get("content", "") or "", _msg.get("tool_calls", []) or []
    _key = _load_api_key(api_key)
    _client = OpenAI(base_url=base_url or None, api_key=_key)
    _resp = _client.chat.completions.create(
        model=model,
        messages=messages,
        tools=TOOL_SCHEMAS,
        tool_choice="auto",
        temperature=0.0,
    )
    _msg = _resp.choices[0].message
    _text = _msg.content or ""
    _tcs = []
    for _call in _msg.tool_calls or []:
        _tcs.append({
            "id": _call.id,
            "type": "function",
            "function": {
                "name": _call.function.name,
                "arguments": _call.function.arguments,
            },
        })
    return _text, _tcs
'''


def _build_tool_schemas(events: list) -> list[dict]:
    """Derive TOOL_SCHEMAS from tool names seen in the trace."""
    names: list[str] = []
    for e in events:
        if e.kind == "tool_call":
            n = e.data.get("name", "")
            if n and n not in names:
                names.append(n)
        elif e.kind == "llm_call":
            for tc in e.data.get("response_tool_calls", []) or []:
                n = (tc.get("function", {}) or {}).get("name", "")
                if n and n not in names:
                    names.append(n)
    return [
        {
            "type": "function",
            "function": {
                "name": n,
                "description": "",
                "parameters": {"type": "object"},
            },
        }
        for n in names
    ]


def _build_provider_config(model: str, provider: str) -> dict:
    """Build the PROVIDER_CONFIG constant (no secrets baked in)."""
    return {
        "model": model,
        "provider": provider,
        "base_url": "",
        "engine": "openai",
    }


def _build_active_skills(events: list, active_skills: list | None = None) -> list[str]:
    """Build the ACTIVE_SKILLS list (S2, ordered-unique).

    Prefers the explicit session-level list; falls back to deriving
    from skill_view events so older traces still emit the constant.
    Accepts dict or attribute events.
    """
    seen: list[str] = []
    for s in active_skills or []:
        if s and isinstance(s, str) and s not in seen:
            seen.append(s)
    for e in events:
        kind = e.get("kind") if isinstance(e, dict) else getattr(e, "kind", None)
        if kind != "skill_view":
            continue
        data = e.get("data", {}) if isinstance(e, dict) else getattr(e, "data", {})
        if not isinstance(data, dict):
            continue
        name = data.get("name")
        if name and isinstance(name, str) and name not in seen:
            seen.append(name)
    return seen


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
            steps += "        if LIVE:\n"
            steps += "            _live_text, _live_tcs = _live_llm_call(messages, MODEL, PROVIDER_CONFIG.get(\"base_url\", \"\"), \"\", ENGINE)\n"
            steps += "            if _live_tcs:\n"
            steps += "                msg = {\"role\": \"assistant\", \"tool_calls\": _live_tcs}\n"
            steps += "                if _live_text:\n"
            steps += "                    msg[\"content\"] = _live_text\n"
            steps += "                messages.append(msg)\n"
            steps += f"                step_log.append({{\"step\": {step_num}, \"kind\": \"llm_call\", \"live\": True}})\n"
            steps += "            else:\n"
            steps += "                msg = {\"role\": \"assistant\", \"content\": _live_text}\n"
            steps += "                messages.append(msg)\n"
            steps += f"                step_log.append({{\"step\": {step_num}, \"kind\": \"llm_call\", \"live\": True, \"text\": _live_text}})\n"
            steps += "        else:\n"
            if tcs:
                names = ", ".join(tc.get("function", {}).get("name", "?") for tc in tcs)
                jtcs = json.dumps(tcs, indent=2, ensure_ascii=False)
                jnames = json.dumps(names, ensure_ascii=False)
                steps += f"            # Model requested tool calls: {names}\n"
                steps += f"            msg = {{\"role\": \"assistant\", \"tool_calls\": {jtcs}}}\n"
                steps += "            messages.append(msg)\n"
                steps += f"            step_log.append({{\"step\": {step_num}, \"kind\": \"llm_call\", \"tool_calls\": {jnames}}})\n"
            else:
                jtxt = json.dumps(txt, ensure_ascii=False)
                steps += f"            msg = {{\"role\": \"assistant\", \"content\": {jtxt}}}\n"
                steps += "            messages.append(msg)\n"
                steps += f"            step_log.append({{\"step\": {step_num}, \"kind\": \"llm_call\", \"text\": {jtxt}}})\n"
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
            dur_val = dur if dur else "None"
            dur_comment = f"  # {dur}ms" if dur else ""
            steps += guard
            steps += f"        # Step {step_num}: Tool call: {name}{dur_comment}\n"
            steps += f"        _tool_args_{step_num} = {{}}\n"
            steps += f"        _tool_default_{step_num} = {jcontent}\n"
            steps += f"        _sub_args_{step_num} = _tool_args_{step_num}\n"
            steps += "        if SUBSTITUTE_TOOL:\n"
            steps += "            try:\n"
            steps += f"                _sub_step_{step_num}, _sub_json_{step_num} = SUBSTITUTE_TOOL.split(\" \", 1)\n"
            steps += f"                if int(_sub_step_{step_num}) == {step_num}:\n"
            steps += f"                    _sub_args_{step_num} = json.loads(_sub_json_{step_num})\n"
            steps += "            except Exception:\n"
            steps += "                pass\n"
            steps += f"        if {jname} in DESTRUCTIVE_TOOLS and not ALLOW_DESTRUCTIVE:\n"
            steps += f"            print(f\"DRY-RUN skipped destructive tool: {name}\")\n"
            steps += f"            messages.append({{\"role\": \"tool\", \"tool_call_id\": {jtid}, \"content\": {jcontent}, \"name\": {jname}}})\n"
            steps += f"            step_log.append({{\"step\": {step_num}, \"kind\": \"tool_call\", \"name\": {jname}, \"skipped\": True}})\n"
            steps += "        else:\n"
            steps += f"            _result_{step_num} = dispatch_tool({jname}, _sub_args_{step_num}, _tool_default_{step_num}, step={step_num})\n"
            steps += f"            messages.append({{\"role\": \"tool\", \"tool_call_id\": {jtid}, \"content\": _result_{step_num}, \"name\": {jname}}})\n"
            steps += f"            step_log.append({{\"step\": {step_num}, \"kind\": \"tool_call\", \"name\": {jname}, \"duration_ms\": {dur_val}}})\n"
            steps += "\n\n"
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
        elif event.kind == "tool_schemas":
            tcount = event.data.get("tool_count", 0) or 0
            steps += guard
            steps += f"        # Step {step_num}: Tool schemas ({tcount} tools)\n"
            steps += f"        step_log.append({{\"step\": {step_num}, \"kind\": \"tool_schemas\", \"tool_count\": {tcount}}})\n\n"
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
    cost_usd: float = 0.0,
    active_skills: list | None = None,
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
    schemas = _build_tool_schemas(events)
    jschemas = json.dumps(schemas, indent=2)
    provcfg = _build_provider_config(model, provider)
    jprov = json.dumps(provcfg, indent=2)
    jactive = json.dumps(
        _build_active_skills(events, active_skills), ensure_ascii=False
    )
    graph = _build_state_graph(events, started_at)
    jgraph = json.dumps(graph, indent=2, ensure_ascii=False)
    depmap = _build_dependency_map(events)
    # int-keyed Python literal (JSON would stringify the keys and break
    # int lookups in the generated program).
    jdeps = repr({int(k): list(v) for k, v in depmap.items()})
    cost = {
        "model": model,
        "cost_usd": float(cost_usd),
        "input_tokens": usage.get("total_input_tokens", 0),
        "output_tokens": usage.get("total_output_tokens", 0),
    }
    jcost = json.dumps(cost, indent=2)
    cost_str = f"${float(cost_usd):.4f} USD ({model})" if model else f"${float(cost_usd):.4f} USD"

    # The replay func, parse_args func, and human_duration func
    replay_func = _make_replay_function(replay_steps)
    parse_args_func = _make_parse_args_function()
    human_dur_func = _make_human_duration_function()
    live_helper = _make_live_helper()
    diff_html_helper = _make_diff_html_helper()

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
        JGRAPH=jgraph,
        JDEPS=jdeps,
        JCOST=jcost,
        COST_STR=cost_str,
        REPLAY_FUNC=replay_func,
        PARSE_ARGS_FUNC=parse_args_func,
        HUMAN_DUR_FUNC=human_dur_func,
        TOOL_SCHEMAS_JSON=jschemas,
        PROVIDER_JSON=jprov,
        ACTIVE_SKILLS_JSON=jactive,
        LIVE_HELPER=live_helper,
        DIFF_HTML_HELPER=diff_html_helper,
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
        "state_graph": STATE_GRAPH,
        "dependencies": DEPENDENCIES,
        "cost": COST,
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
    parser.add_argument("--html", type=str, default=None,
                        help="Writing path for HTML diff report (requires --diff)")
    parser.add_argument("--edit", type=str, default=None,
                        help="Counterfactual: change prompt and re-execute")
    parser.add_argument("--engine", type=str, default="openai",
                        choices=["openai", "pydantic"],
                        help="Live engine: openai SDK (default) or pydantic")
    parser.add_argument("--allow-destructive", action="store_true",
                        help="Allow destructive tools to run (default: dry-run skip)")
    return parser.parse_args()'''


def _make_diff_html_helper() -> str:
    """Build the inline _render_diff_html() source for the generated program.

    Mirrors diff.py render_html_diff logic (index-aligned rows classified as
    added/removed/changed/unchanged, inline CSS, timing delta column,
    HTML-escaped) but operates on the generated file's TIMELINE lists.
    Self-contained: only stdlib html, imported locally. Contains no dollar
    signs so it is safe for string.Template substitution.
    """
    return '''
def _render_diff_html(ours, theirs):
    """Render a self-contained HTML diff of two TIMELINE lists."""
    import html as _html

    def _summ(entry):
        if isinstance(entry, dict):
            kind = str(entry.get("kind", "?"))
            rest = {k: v for k, v in entry.items() if k != "kind"}
            if not rest:
                return kind
            items = ", ".join(f"{k}={v!r}" for k, v in sorted(rest.items()))
            text = kind + "(" + items + ")"
            return text if len(text) <= 300 else text[:297] + "..."
        return str(entry)

    def _off(entry):
        if isinstance(entry, dict):
            try:
                return float(entry.get("offset_ms", 0) or 0)
            except (TypeError, ValueError):
                return None
        return None

    ours = list(ours or [])
    theirs = list(theirs or [])
    n = max(len(ours), len(theirs))
    rows = []
    n_changed = n_added = n_removed = n_unchanged = 0
    for i in range(n):
        in_ours = i < len(ours)
        in_theirs = i < len(theirs)
        if in_ours and in_theirs:
            same = ours[i] == theirs[i]
            cls = "unchanged" if same else "changed"
            left = _summ(ours[i])
            right = _summ(theirs[i])
            if same:
                n_unchanged += 1
            else:
                n_changed += 1
        elif in_theirs:
            cls = "added"
            left = "\\u2014"
            right = _summ(theirs[i])
            n_added += 1
        else:
            cls = "removed"
            left = _summ(ours[i])
            right = "\\u2014"
            n_removed += 1
        d_ours = _off(ours[i]) if in_ours else None
        d_theirs = _off(theirs[i]) if in_theirs else None
        if d_ours is not None and d_theirs is not None:
            _delta = d_theirs - d_ours
            _sign = "+" if _delta >= 0 else "-"
            delta = _sign + str(round(abs(_delta))) + "ms"
        else:
            delta = "n/a"
        rows.append(
            "<tr class=\\"" + cls + "\\"><td class=\\"idx\\">" + str(i) + "</td>"
            + "<td>" + _html.escape(left) + "</td>"
            + "<td>" + _html.escape(right) + "</td>"
            + "<td class=\\"delta\\">" + _html.escape(delta) + "</td></tr>"
        )
    if rows:
        body_rows = "\\n".join(rows)
    else:
        body_rows = (
            "<tr class=\\"unchanged\\"><td class=\\"idx\\">\\u2014</td>"
            "<td>no steps</td><td>no steps</td>"
            "<td class=\\"delta\\">n/a</td></tr>"
        )
    return (
        "<!DOCTYPE html>\\n"
        "<html lang=\\"en\\">\\n"
        "<head>\\n"
        "<meta charset=\\"utf-8\\">\\n"
        "<meta name=\\"viewport\\" content=\\"width=device-width, initial-scale=1\\">\\n"
        "<title>Trace diff</title>\\n"
        "<style>\\n"
        "body { font-family: system-ui, sans-serif; margin: 2rem; color: #111; }\\n"
        "h1 { font-size: 1.25rem; }\\n"
        ".summary { margin-bottom: 1rem; color: #444; }\\n"
        "table.diff { border-collapse: collapse; width: 100%; }\\n"
        "table.diff th, table.diff td { border: 1px solid #ccc; padding: 6px 10px; "
        "text-align: left; vertical-align: top; font-size: 0.9rem; }\\n"
        "table.diff th { background: #f0f0f0; }\\n"
        "tr.unchanged { background: #ffffff; }\\n"
        "tr.changed { background: #fff3cd; }\\n"
        "tr.added { background: #d4edda; }\\n"
        "tr.removed { background: #f8d7da; }\\n"
        "td.idx { width: 3em; text-align: right; color: #666; }\\n"
        "td.delta { white-space: nowrap; }\\n"
        "</style>\\n"
        "</head>\\n"
        "<body>\\n"
        "<h1>Trace diff</h1>\\n"
        "<p class=\\"summary\\">steps: ours=" + str(len(ours))
        + " theirs=" + str(len(theirs)) + " &mdash;\\n"
        "changed=" + str(n_changed) + " added=" + str(n_added)
        + " removed=" + str(n_removed) + " unchanged=" + str(n_unchanged) + "</p>\\n"
        "<table class=\\"diff\\">\\n"
        "<thead><tr><th>step</th><th>ours</th><th>theirs</th>"
        "<th>&Delta; (theirs&minus;ours)</th></tr></thead>\\n"
        "<tbody>\\n" + body_rows + "\\n</tbody>\\n"
        "</table>\\n"
        "</body>\\n"
        "</html>"
    )'''


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