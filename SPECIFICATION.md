# Hermes Trace-to-Program: Unroll the Agent Loop

## A Comprehensive Proposal

---

# PART I: THE IDEA — What, Why, How

## What Is an Agent Loop?

Every agent harness (Hermes, DeepSeek Harness, Pi, Claude Code, Codex, LangChain, AutoGen, CrewAI) uses a variation of the same fundamental pattern:

```
while True:
    1. Take user input (prompt)
    2. Build context (system prompt + conversation history + tools)
    3. Call the LLM
    4. If the LLM returns text → deliver it, done
    5. If the LLM returns tool calls → execute them, collect results
    6. Append results to context
    7. Go back to step 3 (the loop)
```

This is the "Wiggum's loop" — a town drunk staggering through action after action, never quite remembering what he did two turns ago. Every decision is ephemeral: the reasoning, the false starts, the retries, the exact tool arguments, the model's chain-of-thought — all gone the moment the turn ends.

**What's lost:**
- The exact sequence of decisions that produced the answer
- The model's reasoning at each step (why it chose tool A instead of tool B)
- The timing and cost of every sub-operation
- The ability to replay, edit, and compare runs
- The ability to learn from failures programmatically

## The Core Idea: Unroll the Loop

Instead of treating the agent loop as an opaque runtime, **we capture every decision as a structured event**, then **compile the event stream into a self-contained, executable Python program**.

The loop is "unrolled": what was a flat while-loop becomes a linearized, inspectable sequence:

```
Loop form:                         Unrolled form:
                                        
User prompt ──────────           run_20260905.py:
    ↓                            ──────────────
  LLM call ──→ tool call         # Phase 1: system prompt
    ↓              ↓             # Phase 2: user message
  LLM call ──→ tool call         # Phase 3: LLM response (thought + action)
    ↓                            # Phase 4: tool execution + result
  LLM call ──→ final text        # Phase 5: LLM response (thought + action)
    ↓                            # ...
  response delivered             # Phase N: final response
                                 # ──────────────
                                 # Run: python run_20260905.py
```

The program IS the trace. The trace IS the program.

## Why This Matters

### 1. Reproducibility

Today: "The model said it did X, but when I re-ran, it did Y. Was it lying or did I mis-remember?"

With unrolled trace: `python trace.py` reproduces the exact run. If it differs, you know the model or environment changed.

### 2. Debugging

Today: You read a log transcript and guess where things went wrong.

With unrolled trace: You set a breakpoint at message 7. You inspect the agent state. You substitute tool result 3 with a different value and see what changes downstream.

### 3. Regression Testing

Today: You ship a new model version and hope nothing broke.

With unrolled trace: You collect 100 `.py` files from production runs and run them in CI against the new model. Any divergence is caught as a test failure.

### 4. Training Data

Today: You scrape logs and parse them into training format.

With unrolled trace: The trace is already structured Python with messages, tool calls, and reasoning. Extraction is trivial.

### 5. Audit

Today: "What did the agent do on Tuesday at 3pm?" — you read a wall of text.

With unrolled trace: `diff run_tuesday.py run_wednesday.py` shows exactly what changed.

### 6. Knowledge Transfer

Today: An agent does something clever. You can't reuse it — the reasoning lives in the ephemeral conversation.

With unrolled trace: You take the `.py` file, change the first prompt, and get a new agent tailored to a slightly different task.

---

# PART II: ECOSYSTEM RESEARCH

## Has This Been Done Before?

**In pieces, but not the synthesis you're describing.**

| Project | What It Does | The Gap |
|---|---|---|
| **Execution Lineage** (arXiv 2605.06365, 2025) | DAG of artifact-producing nodes with identity-based replay | Stores traces as DAG metadata, not as executable source code |
| **TraceCompiler** (arXiv 2608.02680, 2025) | Mines multiple agent traces and compiles recurring intents into deterministic workflows | Post-hoc mining — the initial run doesn't become a program |
| **Shepherd** (Stanford/Northeastern, 2025) | Reversible Git-like execution traces with fork/revert | Immutable effect stream, not a serialized Python program |
| **CompileAgent** (2025) | Compiles agent reasoning into IR → deterministic executor | Uses a DSL/bytecode IR, not Python source code |
| **Hindsight** (2025) | Record → replay → attribute → fix → verify by replay | Deterministic via response cache, trace stored in a separate format |
| **AgentReplay** (2025) | Language-neutral trace protocol with CI gates | Regression harness — not the trace-as-program |
| **DSPy** (Stanford, 2024) | Compiles declarative LM pipelines with optimization | Graph-based compilation, not trace unrolling |
| **Heimdall** / **stepback** (2025) | Reversible debugger, counterfactual replay for agent runs | Trace is a record, not a self-contained .py |
| **Hermes-Trace plugin** (hlothaire, 2025) | 18 hooks capturing every agent event as a directed graph | Observability only — no code generation |
| **Hermes Flight Recorder** (BunsDev, 2025) | Scorecards, static reports, CI gates from trajectories | Deterministic evaluation, not programmatic replay |

**The synthesis that doesn't exist anywhere:** taking the executed trace and emitting a self-contained, runnable Python program that reproduces the exact run — then treating that program as a first-class artifact for editing, debugging, and diffing.

## Can This Apply to Other Agent Harnesses?

| Harness | Language | Architecture | Existing Trace Data | Effort for This Feature |
|---|---|---|---|---|
| **Hermes** | Python | AIAgent + phase-decomposed loop + plugin hooks (18 hooks) | Yes: trajectory JSONL, Flight Recorder, Session DB, Hermes-Trace graph | **~2 days (plugin PoC)** |
| **DeepSeek Harness** | TypeScript | Cordis plugin architecture + event-sourced session log | Yes: session/event log with turn/step/tool boundaries | **~2 weeks** (different language, flat event log needs graph reconstruction) |
| **Pi-Agent (Python)** | Python | Minimal agent_loop() async generator with event stream | Minimal: no built-in trajectory infrastructure | **~5 days** (simple core, but build recorder from scratch) |
| **Claude Code** | TypeScript | Proprietary, limited hook surface | No public tracing API | **Unknown** (closed system) |
| **LangGraph** | Python | StateGraph-based with checkpointing | Yes: checkpoints are typed state snapshots | **~1 week** (checkpoints are natural trace points) |

---

# PART III: CASE STUDIES AND USE CASES

## Industry Use Cases

### Case Study 1: Regulated Financial Services — Audit Compliance

**Scenario:** A fintech deploys an AI agent that processes loan applications. The agent calls credit bureaus, validates documents, computes DTI ratios, and makes recommendations.

**Problem:** Regulators (FCA, SEC, ECB) require "explainable AI decisions" — you must prove what the agent did and why, down to every API call and reasoning step.

**With the unrolled trace:**
- Every loan decision is accompanied by `loan_20260905.py`
- The regulator's auditor can run the file and verify the exact tool calls, timings, and model reasoning
- `diff good_loan.py bad_loan.py` shows the exact point where the agent diverged (e.g., called a different credit bureau API)
- The `.py` file is legally admissible: it's a self-contained, verifiable record

**Questions this answers:**
- What tool(s) did the agent call, in what order, with what arguments?
- What model reasoning preceded each tool call?
- Did the agent handle API failures, and how?
- Can we reproduce the decision on demand for an auditor?
- What changed between an approved and a rejected application?

### Case Study 2: Enterprise SaaS — CI/CD for Agent Behavior

**Scenario:** A CRM platform ships an AI assistant that writes emails, schedules meetings, and updates records. Each new model release risks breaking existing workflows.

**Problem:** No regression harness exists for agent behavior. You can't ship a model update with confidence.

**With the unrolled trace:**
- Collect 100 `trace_*.py` files from production runs
- Run them in CI against the candidate model:
  ```bash
  for f in traces/*.py; do python "$f" || echo "REGRESSION: $f"; done
  ```
- Any output mismatch is a regression. Any new tool call is a drift. Any different timing is a performance change.
- PR gates block merges that break agent traces

**Questions this answers:**
- Does model v2 produce the same output as v1 on real user inputs?
- Did the agent start calling different tools for the same user request?
- Are there new latency or cost regressions?
- Which production inputs are most sensitive to model changes?

### Case Study 3: Healthcare — Reproducible Medical Reasoning

**Scenario:** A medical AI agent triages patients, reviews lab results, and suggests diagnoses.

**Problem:** Patient safety requires that every decision can be independently verified. A hallucinated tool call could be dangerous.

**With the unrolled trace:**
- Every patient interaction produces a `.py` file stored in the medical record
- A second AI or human reviewer runs the trace: it reproduces the exact same reasoning
- The trace can be "frozen" at the point of a decision and a counterfactual run made (e.g., "what if the lab result had been different?")
- No black box — every reasoning step is captured in structured, executable form

**Questions this answers:**
- What patient data did the agent access, and when?
- What was the model's reasoning before recommending a diagnosis?
- Did the agent follow the correct clinical protocol (tool call sequence)?
- Can we reproduce the triage decision on demand?
- What would the agent have recommended with different input data?

### Case Study 4: E-Learning — Personalized Tutoring

**Scenario:** An AI tutor adapts lessons in real-time based on student responses.

**Problem:** You need to understand why the tutor chose a particular pedagogical strategy and whether it was effective.

**With the unrolled trace:**
- Every tutoring session is a `.py` file
- Compare traces across students: which lesson path leads to better outcomes?
- Edit the trace: change the student's answer, re-run, see if the tutor adapts correctly
- Build a training dataset from the best-performing traces

**Questions this answers:**
- What adaptation did the tutor make and why?
- Which teaching strategy was chosen and at what point?
- How does the tutor's behavior change with different student inputs?
- Can we extract the best teaching sequences as training data?

### Case Study 5: AI Research — Failure Attribution and Model Improvement

**Scenario:** An LLM research lab is fine-tuning models on agent tasks.

**Problem:** When training a model to replace GPT-4, you need to know exactly where it fails, not just its final score.

**With the unrolled trace:**
- Run the baseline model on 1000 tasks, producing 1000 `.py` files
- Run the candidate model on the same tasks, producing 1000 more
- `diff` every pair: you know the exact node where the candidate started diverging
- Train a reward model that penalizes divergence from the baseline trace
- Build a counterfactual dataset: "trace with error" corrected by "trace after fix"

**Questions this answers:**
- At which step did the model make its first mistake?
- Is the failure in reasoning, tool choice, or argument formatting?
- Does the new model make the same mistakes or different ones?
- Which prompts or tool schemas cause the most divergence?

### Case Study 6: DevOps — Autonomous Incident Response

**Scenario:** An AI agent responds to production incidents: reads logs, checks metrics, rolls back deployments, pages engineers.

**Problem:** You need to trust that the agent acted correctly. An automated rollback is dangerous if it's the wrong rollback.

**With the unrolled trace:**
- Every incident response produces a `.py` file
- Post-mortems use `diff` to compare what the agent did vs. what the SRE would have done
- Run `trace.py --substitute-tool=rollback "dry-run"` — simulate the rollback without executing it
- Build a corpus of incident traces for training better response models

**Questions this answers:**
- What metrics did the agent check before deciding to roll back?
- Was the rollback command correct for the specific incident?
- What was the model's reasoning when it escalated to a human?
- Can we replay the incident response after a fix to verify it would work?

## Personal Use Cases

### Case Study 7: The Personal Research Assistant

**Scenario:** You use Hermes to research topics weekly — stock analysis, technology trends, market data.

**Problem:** A great research session happens, but the chain of thought is lost. Next week, you can't remember why you reached a conclusion.

**With the unrolled trace:**
- Every research session is a `.py` file
- You re-run it a week later to refresh the context
- You edit the first prompt: "Update this analysis with this week's data" — and the agent re-derives from the previous reasoning
- You build a library of reusable research traces, one per topic

**Questions this answers:**
- What sources did the agent consult last week?
- What reasoning did it use to weigh conflicting data?
- Can I reproduce the analysis on demand?
- How much did the conclusion depend on specific data points?

### Case Study 8: Personal Coding Agent — Debugging History

**Scenario:** You use Hermes as a coding agent. It fixes bugs, writes tests, and refactors code.

**Problem:** A fix was applied, but you don't know exactly what the agent changed or why.

**With the unrolled trace:**
- Every coding session produces a `.py` file with `read_file`, `patch`, `write_file` calls
- `diff` shows every file change, tool call, and reasoning step
- You can roll back: re-run the trace up to the point before the mistake
- You can replay: run the trace on a different branch to apply the same fix pattern

**Questions this answers:**
- What files did the agent read, in what order?
- What patches did it apply and why?
- What tests did it run and what were the results?
- Can I reproduce the fix on a different codebase?

### Case Study 9: Learning and Education

**Scenario:** You're learning a new framework. You ask Hermes to explain concepts and build examples.

**Problem:** Six months later, you need to revisit the concept. The understanding is gone.

**With the unrolled trace:**
- Every learning session is a `.py` file — a reproducible lesson
- Re-run it to refresh the explanation
- Edit the questions to test deeper understanding
- Share `.py` files with colleagues as structured, runnable tutorials

**Questions this answers:**
- What examples did the agent show?
- What follow-up questions did I ask?
- What was the agent's teaching strategy?
- Can I re-derive the same understanding from the trace?

---

# PART IV: THE BUILD PLAN (Agent-Ready Specification)

This section is a **self-contained implementation specification** that you can feed to a coding agent with the prompt: "Build this."

---

## Overview

**Project:** `hermes-unroll` — a Hermes Agent plugin that captures every session's execution trace and compiles it into a self-contained, executable Python file.

**Output:** For every Hermes conversation, create `~/.hermes/traces/unrolled/<session_id>.py` — a runnable program that reproduces the exact conversation.

**Time estimate:** 2-3 days for PoC, 2-3 weeks for full implementation.

---

## Phase 1: Plugin Framework (PoC — 2-3 days)

### File Structure

```
~/.hermes/plugins/unroll/
├── plugin.yaml
├── __init__.py          # Plugin entry point: register(ctx)
├── tracer.py            # TraceEvent dataclass, accumulator, JSONL persistence
└── generator.py         # Code generator: TraceEvent[] → .py file
```

### `plugin.yaml`

```yaml
name: hermes-unroll
description: "Unroll the agent loop into a reproducible Python program"
version: 0.1.0
author: "Hermes User"
hooks:
  - post_llm_call
  - post_tool_call
  - on_session_end
skills: []
```

### `__init__.py` (Plugin Entry Point)

```python
"""Plugin entry point — subscribes to hooks and wires the tracer to the code generator."""

from .tracer import TraceRecorder
from .generator import generate_trace_program

recorder: TraceRecorder | None = None

def register(ctx):
    """Called by Hermes plugin loader on session start."""
    global recorder
    recorder = TraceRecorder()
    ctx.state.trace_recorder = recorder

    ctx.register_hook("post_llm_call", on_post_llm_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("on_session_end", on_session_end)

    logger.info("hermes-unroll: plugin registered")

def on_post_llm_call(session_id, request_kwargs, response, usage, ...):
    global recorder
    recorder.record("llm_call", {
        "provider": provider,
        "model": model,
        "request_messages": request_messages,
        "response_text": response_text,
        "response_tool_calls": tool_calls,
        "usage": usage,
        "finish_reason": finish_reason,
        "duration_ms": duration_ms,
    })

def on_post_tool_call(session_id, tool_name, args, result, duration_ms, ...):
    global recorder
    recorder.record("tool_call", {
        "name": tool_name,
        "args": args,
        "result": result,
        "duration_ms": duration_ms,
        "status": "success" | "error",
        "error": error_message if error else None,
    })

def on_session_end(session_id, ...):
    global recorder
    events = recorder.finalize()
    program_path = generate_trace_program(events, session_id)
    recorder = None
    logger.info(f"hermes-unroll: trace written to {program_path}")
```

### `tracer.py` (Event Accumulator)

```python
"""Structured trace event accumulation."""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any

@dataclass
class TraceEvent:
    """A single decision point in the agent loop."""
    kind: str                    # "llm_call" | "tool_call" | "subagent_start" | "subagent_stop" | "system_prompt" | "user_message" | "interrupt" | "guardrail" | "retry" | "compression" | "error" | "final_response"
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

class TraceRecorder:
    """Accumulates TraceEvents during a session."""

    def __init__(self):
        self.session = TraceSession(session_id="", model="", provider="")

    def record(self, kind: str, data: dict) -> None:
        self.session.events.append(TraceEvent(kind=kind, data=data))

    def set_metadata(self, session_id: str, model: str, provider: str,
                     system_prompt: str, user_message: str) -> None:
        self.session.session_id = session_id
        self.session.model = model
        self.session.provider = provider
        self.session.system_prompt = system_prompt
        self.session.initial_user_message = user_message

    def finalize(self) -> list[TraceEvent]:
        return self.session.events
```

### `generator.py` (Code Generator)

This is the core of the plugin. It takes a list of `TraceEvent` objects and emits a Python file.

```python
"""Code generator: TraceEvent[] → runnable .py file."""

import os
from datetime import datetime
from pathlib import Path
from typing import Any

TRACES_DIR = Path.home() / ".hermes" / "traces" / "unrolled"

def generate_trace_program(
    events: list,
    session_id: str,
    model: str = "",
    provider: str = "",
    system_prompt: str = "",
    user_message: str = "",
    final_response: str = "",
) -> str:
    """Compile events into a self-contained .py file.
    Returns the absolute path to the written file.
    """

    TRACES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_filename(session_id or 'unsaved')}.py"
    filepath = TRACES_DIR / filename

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Extract all messages from events for the conversation_history
    messages = reconstruct_messages(events)

    code = f'''#!/usr/bin/env python3
"""
Reproducible Agent Run — session {session_id}
Generated by hermes-unroll v0.1.0 at {timestamp}
Original: model={model}, provider={provider}, turns={len(events)}
"""

from run_agent import AIAgent

# ── System Prompt (exact copy) ──
SYSTEM_PROMPT = {repr(system_prompt)}

# ── Conversation History (every message, tool call, tool result) ──
# {len(messages)} messages covering {count_llm_calls(events)} LLM calls
# {count_tool_calls(events)} tool calls
CONVERSATION_HISTORY = {format_messages(messages)}

# ── Agent Configuration ──
agent = AIAgent(
    model={repr(model)},
    provider={repr(provider)},
    save_trajectories=False,
    quiet_mode=True,
)

# ── Reproduce the Run ──
result = agent.run_conversation(
    {repr(user_message)},
    system_message=SYSTEM_PROMPT,
    conversation_history=CONVERSATION_HISTORY,
)

# ── Verification ──
expected = {repr(final_response)}
actual = result.get("final_response", "")
if actual == expected:
    print("✓ Exact reproduction — output matches")
else:
    print(f"⚠ Output differs:\\n  Expected: {expected[:200]}...\\n  Actual:   {actual[:200]}...")

print(f"  Turns: {result.get('api_calls', 0)}  Tokens in: {result.get('input_tokens', 0)}  Tokens out: {result.get('output_tokens', 0)}")
'''

    filepath.write_text(code, encoding="utf-8")
    return str(filepath)


# ── Helper Functions ──

def safe_filename(session_id: str) -> str:
    """Collapse non-alphanumeric characters for safe filenames."""
    import re
    sanitized = re.sub(r"[^\w-]", "_", session_id).strip("._")
    return sanitized[:96] or "session"

def reconstruct_messages(events: list) -> list[dict]:
    """Walk the event list and reconstruct the message sequence.
    Returns a list of {"role": ..., "content": ..., "tool_calls": ..., "tool_call_id": ...} dicts.
    """
    messages = []
    for event in events:
        if event.kind == "system_prompt":
            # Add as a system message at the start
            if not any(m.get("role") == "system" for m in messages):
                messages.append({"role": "system", "content": event.data.get("text", "")})
        elif event.kind == "user_message":
            messages.append({"role": "user", "content": event.data.get("text", "")})
        elif event.kind == "llm_call":
            # Assistant response — may have text, tool_calls, or both
            msg = {"role": "assistant"}
            text = event.data.get("response_text", "")
            tool_calls_raw = event.data.get("response_tool_calls", [])
            if text:
                msg["content"] = text
            if tool_calls_raw:
                msg["tool_calls"] = tool_calls_raw
            if not text and not tool_calls_raw:
                msg["content"] = ""  # empty response placeholder
            messages.append(msg)
        elif event.kind == "tool_call":
            # Tool result message
            messages.append({
                "role": "tool",
                "tool_call_id": event.data.get("tool_call_id", ""),
                "content": event.data.get("content", ""),
                "name": event.data.get("name", ""),
            })
        elif event.kind == "final_response":
            # The final assistant message
            if not messages or messages[-1].get("role") != "assistant":
                messages.append({"role": "assistant", "content": event.data.get("text", "")})
    return messages

def format_messages(messages: list[dict]) -> str:
    """Pretty-format the messages list as Python literal code."""
    import json
    # Use compact serialization with indentation
    return json.dumps(messages, indent=2, ensure_ascii=False)

def count_llm_calls(events: list) -> int:
    return sum(1 for e in events if e.kind == "llm_call")

def count_tool_calls(events: list) -> int:
    return sum(1 for e in events if e.kind == "tool_call")
```

### Minimum Viable Registration

The plugin also needs a `manifest.json` for auto-discovery:

```json
{
  "name": "hermes-unroll",
  "version": "0.1.0",
  "description": "Unroll the agent loop into a reproducible Python program",
  "hooks": ["post_llm_call", "post_tool_call", "on_session_end"]
}
```

---

## Phase 2: Enhanced Trace Depth (3-4 days)

### Add These Additional Hooks

Modify `__init__.py` to register:

| Hook | Data Captured |
|---|---|
| `pre_api_request` | Request messages as sent to the LLM (after compression, with all context) |
| `post_api_request` | Raw response, usage metrics, finish reason, duration |
| `api_request_error` | Error classification, retry count, fallback used |
| `subagent_start` | Subagent goal, context, model |
| `subagent_stop` | Subagent result, summary, token usage, duration |
| `on_stream_delta` | Streaming text deltas (for reconstructing the exact delivered tokens) |
| `pre_tool_call` | Tool name and arguments (before execution — for guardrail interception) |

### Enhanced Generator: Include Reasoning

Modify the generator to extract and include the model's reasoning/thinking blocks:

```python
# In each LLM call event, extract:
# - thinking_content (any <thinking>…</thinking> blocks)
# - scratchpad_content (any <REASONING_SCRATCHPAD>…</REASONING_SCRATCHPAD> blocks)
# - codex_reasoning_items (encrypted reasoning from Responses API)

# The emitted program includes these as comments or as structured fields
```

### Enhanced Generator: Include Metadata Footer

Append a metadata block to the emitted `.py` file:

```python
# ── Metadata ──
# Generated: 2026-09-05T14:30:22Z
# Session: 20260905_143052_a1b2c3
# Model: deepseek/deepseek-v4-flash
# Provider: openrouter
# LLM calls: 5
# Tool calls: 8
# Tokens in: 48,250
# Tokens out: 7,894
# Duration: 720.9s
# Completed: True
```

---

## Phase 3: Node-Level Replay (5-7 days)

### Approach: Pydantic Agent Format

Instead of using `AIAgent.run_conversation()` in the emitted file, emit a program using Pydantic AI's `agent.iter()` for node-by-node replay.

```python
# Generated program with node-level replay:

from pydantic_ai import Agent
from pydantic_graph import End

agent = Agent(
    model="openai:gpt-4o",
    system_prompt=SYSTEM_PROMPT,
)
input_messages = [...]  # reconstructed conversation

async def replay():
    async with agent.iter(input_messages) as agent_run:
        next_node = agent_run.next_node
        nodes = [next_node]
        while not isinstance(next_node, End):
            next_node = await agent_run.next(next_node)
            nodes.append(next_node)
        return agent_run.result
```

This requires converting Hermes's internal message format to Pydantic AI format — a mapping step.

### CLI Flags for the Emitted Program

```bash
python trace.py                          # Full reproduction
python trace.py --stop-at=3              # Run first 3 nodes, then pause and dump state
python trace.py --substitute-tool=2 '{"query": "different question"}'  # Replace tool call 2's args
python trace.py --show-state             # After each node, print the full agent state
python trace.py --diff another_trace.py  # Compare two traces node-by-node
```

### Implementation of `--stop-at`

```python
if args.stop_at:
    for i, (span, event) in enumerate(trace):
        if i >= args.stop_at:
            print(f"STOPPED at node {i}")
            print(f"State: {json.dumps(event.data, indent=2)}")
            break
        engine.step()
```

### Implementation of `--substitute-tool`

```python
if args.substitute_tool:
    index, new_args = args.substitute_tool.split(" ", 1)
    index = int(index)
    # Find the tool call event at index, replace its args
    for i, event in enumerate(events):
        if event.kind == "tool_call" and i == index:
            event.data["args"] = json.loads(new_args)
            break
    # Re-emit the .py with the change
    generate_trace_program(events, ...)
```

---

## Phase 4: Counterfactual Engine (3-5 days, opportunity-based)

### Deterministic Replay Cache

Record the model's output at each LLM call and include it as a cache in the emitted file. On re-run, instead of calling the API, return the cached response.

```python
# In the emitted file:
_RESPONSE_CACHE = {
    "llm_call_1": "The capital of France is Paris.",
    "llm_call_2": json.dumps({"function": "search", "args": {"q": "Paris capital"}}),
    "llm_call_3": "The Eiffel Tower was built in 1889.",
}
```

When `--live` is passed, ignore the cache and call the real API. When `--dry-run` (default), use the cache.

### Edit Mode

```bash
python trace.py --edit "change prompt 1 to 'What is the capital of Germany?'"
```

The program:
1. Detects which nodes depend on the changed input (dependency tracing)
2. Invalidates downstream cached responses
3. Re-executes only the affected suffix
4. Saves the result as a new `.py` file

---

## Verification Criteria

For each phase, the build is complete when:

| Criterion | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|
| Plugin loads without errors | ✓ | ✓ | ✓ | ✓ |
| Every conversation produces a `.py` file | ✓ | ✓ | ✓ | ✓ |
| `.py` file runs without errors | ✓ | ✓ | ✓ | ✓ |
| `.py` file reproduces the final response | ✓ | ✓ | ✓ | ✓ |
| Reasoning/thinking blocks are captured | | ✓ | ✓ | ✓ |
| Subagent traces are captured | | ✓ | ✓ | ✓ |
| Error/retry traces are captured | | ✓ | ✓ | ✓ |
| `--stop-at=N` flag works | | | ✓ | ✓ |
| `--substitute-tool` flag works | | | ✓ | ✓ |
| `--diff` flag works | | | ✓ | ✓ |
| Deterministic replay cache works | | | | ✓ |
| Edit mode works | | | | ✓ |

---

## Testing

### Unit Tests

```python
# tests/test_tracer.py
def test_trace_event_structure():
    event = TraceEvent(kind="llm_call", data={"model": "gpt-4"})
    assert event.kind == "llm_call"
    assert event.data["model"] == "gpt-4"

# tests/test_generator.py
def test_generates_valid_python():
    events = [TraceEvent(kind="user_message", data={"text": "hello"})]
    path = generate_trace_program(events, "test_session")
    assert Path(path).exists()
    # Verify the file is syntactically valid Python
    import ast
    with open(path) as f:
        ast.parse(f.read())

def test_reconstruct_messages():
    events = [
        TraceEvent(kind="system_prompt", data={"text": "You are a helpful assistant."}),
        TraceEvent(kind="user_message", data={"text": "What is the capital?"}),
        TraceEvent(kind="llm_call", data={"response_text": "The capital is Paris."}),
    ]
    msgs = reconstruct_messages(events)
    assert len(msgs) == 3
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert msgs[2]["role"] == "assistant"

# tests/test_replay.py
def test_replay_produces_same_output():
    # Run a conversation with Hermes
    agent = AIAgent(model="mock", ...)
    result1 = agent.run_conversation("test query")
    # Get the unrolled trace
    events = recorder.session.events
    # Compile it
    path = generate_trace_program(events, "test_replay")
    # Run the compiled trace
    import subprocess
    p = subprocess.run(["python", path], capture_output=True)
    assert p.returncode == 0
```

### Integration Tests

```python
# Test with a real (mock-provider) conversation:
# 1. Start a conversation with the mock provider (fixed outputs)
# 2. Get the .py file
# 3. Run it — verify output matches exactly
# 4. Run it again — verify output is identical (determinism)

# Test with tool calls:
# 1. Conversation involves read_file + search
# 2. .py file contains both tool call events with full args/results
# 3. Re-run produces same sequence

# Test error recovery:
# 1. Conversation triggers a 429 retry
# 2. .py file contains retry events with error classification
# 3. Re-run (with mock) replays the retry logic
```

---

## Deployment

### For the User

1. Place the plugin files in `~/.hermes/plugins/unroll/`
2. Enable in config.yaml:
   ```yaml
   plugins:
     entries:
       hermes-unroll:
         enabled: true
   ```
3. Restart Hermes
4. Every session now produces a `.py` file at `~/.hermes/traces/unrolled/<session_id>.py`

### For Distribution

Package as a pip-installable entry point plugin:

```python
# pyproject.toml
[project.entry-points."hermes_agent.plugins"]
hermes-unroll = "hermes_unroll:register"
```

---

## Known Limitations

1. **Non-deterministic API** — The same prompt can produce different LLM responses. Mitigation: include sampling parameters (temperature, top_p, seed) and offer a response cache mode.

2. **Side-effecting tools** — Re-running a destructive tool (file delete, DB write) can cause damage. Mitigation: default to `--dry-run` that mocks tool results from the recorded trace; require `--live-tools` for real execution.

3. **Context compression** — Compressed conversations lose message fidelity. Mitigation: capture the pre-compression messages in the trace, not the post-compression ones.

4. **Encrypted reasoning** — Some providers (Codex API) return encrypted reasoning that can't be replayed. Mitigation: store the encrypted blob and replay it verbatim; the model decrypts it.

5. **Large traces** — A 50-turn conversation with 100 tool calls could produce a 10,000-line `.py` file. Mitigation: offer a "compact" mode that stores messages as JSON references instead of inline literals.

---

## Success Metrics

| Metric | Target |
|---|---|
| PoC time | 2-3 days |
| Plugin lines of code | < 800 |
| Emitted file size vs. raw trace | < 2x larger (after compression) |
| Replay accuracy (same model, same day) | 100% (with fixed temperature) |
| Replay accuracy (same model, different day) | > 95% (API model drift) |
| User adoption | Plugin available, zero core code changes |

---

## Architecture Diagram (the pipeline)

```
┌─────────────┐    ┌──────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  Hermes     │    │  unroll      │    │  code generator  │    │  trace_20260905  │
│  Agent Loop │───▶│  plugin      │───▶│  (generator.py)  │───▶│  .py             │
│  (run_agent │    │  (tracer.py) │    │  Jinja2 template │    │                  │
│  .py)       │    │  accumulates │    │  walks events,   │    │  self-contained  │
│             │    │  TraceEvents │    │  emits Python    │    │  executable      │
└─────────────┘    └──────────────┘    └─────────────────┘    └──────────────────┘
                         │                                            │
                         │                                            │
                         ▼                                            ▼
                  ┌──────────────┐                           ┌──────────────────┐
                  │  trace_raw   │                           │  python trace.py  │
                  │  .jsonl      │                           │                   │
                  │  (debug)     │                           │  → exact replay   │
                  └──────────────┘                           │  → node stepping  │
                                                             │  → counterfactual │
                                                             │  → diff           │
                                                             └──────────────────┘
```

---

# APPENDIX: The Interview Answer

If you're asked again: "What specific step would you replace with AI in software delivery?"

**Your real answer (you didn't have to say "all of it"):**

> "I wouldn't replace any single step. I'd make the entire delivery pipeline a first-class citizen of the AI's trace. Every decision the agent makes — every tool call, every model response, every test run — gets captured not as a log you have to read, but as a self-contained program you can rerun, edit, and debug. The agent doesn't replace a step; it makes the whole pipeline reproducible and introspectable."

---

*Document written 2026-09-05. Covers the full specification for Hermes Trace-to-Program (Unroll the Agent Loop) based on research of Hermes source code (run_agent.py, conversation_loop.py, turn_tool_round.py, turn_finalizer.py, trajectory.py, plugins.py, hooks.py) and the broader ecosystem (Execution Lineage, TraceCompiler, Shepherd, CompileAgent, Hindsight, AgentReplay, DSPy, CompileAgent, Pi-Agent, DeepSeek Harness).*