# hermes-unroll

**A Hermes Agent plugin that captures every session's execution trace and compiles it into a reproducible Python program. The trace IS the program.**

Every LLM conversation is an ephemeral loop — decisions made, tools called, reasoning chains spun — and then it's gone. hermes-unroll captures every decision point as a structured event and, at session end, compiles the stream into a self-contained `.py` file.

```
User: "Deploy the staging environment"
  ↓  LLM call → reads files, patches, runs commands
  ↓  LLM call → verifies, tests
  ↓  LLM call → "Staging deployed. Running smoke tests."
  ↓
[ on_session_end ]
  ↓
~/.hermes/traces/unrolled/20260905_143052_a1b2c3.py
```

### What makes this interesting

Hermes exposes hooks at every lifecycle point — `post_llm_call`, `post_tool_call`, `on_session_end` — with consistent signatures and clean separation from core logic. That's the whole reason this plugin exists: the hook surface is well-designed enough that capturing every turn and emitting a runnable program took zero core patches and no monkeypatching.

| What you can do with a trace file | How |
|----------------------------------|-----|
| **Reproduce a run** | `python trace.py` replays the exact conversation |
| **Debug step by step** | Inspect LLM output at message 7, substitute a tool result, see what changes |
| **Regression test models** | Collect traces from production, run them in CI against candidate models |
| **Audit decisions** | `diff tuesday.py wednesday.py` shows exactly what the agent did differently |
| **Extract training data** | Traces are structured message lists — ready for fine-tuning or reward modelling |
| **Reapply reasoning patterns** | Change the first prompt, re-run, get a tailored agent for a similar task |

## How it works

Twelve hooks, one accumulator, one code generator.

| Component | File | Job |
|-----------|------|-----|
| `register(ctx)` | `__init__.py` | Wires 12 hooks to the tracer (session lifecycle + API depth + subagents + stream) |
| `TraceRecorder` | `tracer.py` | Accumulates `TraceEvent` objects during a session |
| `generate_trace_program()` | `generator.py` | Walks events, reconstructs messages, emits valid Python |
| `redact_event` | `redact.py` | Strips API keys, tokens, emails before writing to disk |
| `estimate_cost` | `pricing.py` | Per-model USD cost ledger |
| `is_destructive` | `safety.py` | Destructive-tool detection for the dry-run guard |
| `render_html_diff` | `diff.py` | Self-contained HTML trace diff |

Hook coverage (`plugin.yaml` / `manifest.json`): `on_session_start`,
`post_llm_call`, `post_tool_call`, `on_session_end`, `on_session_finalize`,
`pre_api_request`, `post_api_request`, `api_request_error`,
`subagent_start`, `subagent_stop`, `on_stream_delta`, `pre_tool_call`.

The generated file captures the full conversation history — system prompt, every user message, every LLM response (text + tool calls), and every tool result — ready to import, parse, or run.

### Example output

```python
# ── Metadata ──
# Generated: 2026-09-05 10:14:13
# Session: demo_20260905
# Model: deepseek/deepseek-v4-flash
# LLM calls: 2  Tool calls: 1  Messages: 5

# ── Conversation History ──
CONVERSATION_HISTORY = [
  {"role": "system", "content": "You are a helpful assistant."},
  {"role": "user", "content": "Hello"},
  {"role": "assistant", "tool_calls": [
    {"id": "call_abc", "type": "function",
     "function": {"name": "web_search", "arguments": '{"q": "hello"}'}}
  ]},
  {"role": "tool", "tool_call_id": "call_abc",
   "content": '{"results": []}', "name": "web_search"},
  {"role": "assistant", "content": "Hello there! How can I help?"}
]
```

## Installation

```bash
git clone https://github.com/dark5un/hermes-unroll.git \
  ~/.hermes/plugins/hermes-unroll
hermes plugins enable hermes-unroll
```

Restart Hermes. Every conversation produces a trace at `~/.hermes/traces/unrolled/<session_id>.py`.

## Project structure

```
~/.hermes/plugins/hermes-unroll/
├── plugin.yaml              # Hermes plugin manifest (12 hooks)
├── manifest.json            # Auto-discovery (same hooks list)
├── __init__.py              # Hook wiring (register + 12 handlers)
├── tracer.py                # TraceEvent, TraceSession, TraceRecorder
├── generator.py             # Code generator: events → .py file
├── redact.py                # PII/secrets redaction
├── pricing.py               # Per-model cost ledger
├── safety.py                # Destructive-tool detection
├── diff.py                  # HTML trace diff renderer
├── templates/
│   └── replay_template.py.txt  # Single source for generated program shape
├── docs/
│   ├── EXECUTION_CONTRACT.md   # Result schema + timing_log shape + exit codes
│   ├── LIVE_ENGINE_SPIKE.md    # openai vs PydanticAI vs urllib decision
│   └── SPEC_AUDIT.md           # Plan-to-code evidence table
├── tests/                   # 16 test files (tracer, generator, timing, range,
│                            #   counterfactual, deps, graph, schemas, live,
│                            #   redact, pricing, cost, safety, diff x2, pulse)
├── SPECIFICATION.md         # Full proposal
└── README.md
```

## Development

```bash
uv sync
uv run pytest          # 115 tests pass
uv run ruff check .    # lint clean
```

## Execution

Running a trace replays the original session step by step and prints a
timing summary plus a structured JSON `result` (see
`docs/EXECUTION_CONTRACT.md`):

```bash
python ~/.hermes/traces/unrolled/<session>.py
python ~/.hermes/traces/unrolled/<session>.py --from=2 --to=5
```

Result keys: `session_id`, `model`, `provider`, `started_at`,
`original_duration_ms`, `replay_duration_ms`, `messages_count`, `steps`,
`messages`, `usage`, `reasoning_blocks`, `timing_log`, `response_cache`,
`cost`, `state_graph`, `dependencies`, `from_step`, `to_step`.
Exit codes: 0 success, 1 generation error, 2 arg-parse error.

Each `timing_log` entry carries `step`, `kind`, `original_offset_ms`
(offset in the original `TIMELINE`), `replay_offset_ms` (ms since replay
start), `delta_ms` (`replay_offset_ms - original_offset_ms`),
`duration_ms` (original step duration, `null` when unknown), and
`replay_duration_ms` (`round((t1 - t0) * 1000)` per guarded step block).
Every `steps[i]` entry also gains `replay_duration_ms`, and
`timing_log[i]` shares its `step` index. Range replays (`--from`/`--to`)
omit skipped steps from `timing_log` while still recording `from_step` /
`to_step` in `result`.

### Replay flags

| Flag | Meaning |
|------|---------|
| `--live` | Execute real LLM calls (default: dry-run from `RESPONSE_CACHE`) |
| `--from N --to M` | Replay step range; skipped steps omitted from `timing_log`; `from_step`/`to_step` in result |
| `--stop-at N` | Print first N steps as JSON after replay |
| `--substitute-tool '<step> <json_args>'` | Replace a tool call's dispatched args |
| `--show-state` | Print step/message counts after replay |
| `--diff OTHER.py` | Step diff vs another trace (safe `ast.literal_eval` loader, never `exec`) |
| `--edit '<step> <new-text>'` | Counterfactual: mutate message, replay suffix, save `*_edit_<ts>.py` (never overwrites) |
| `--engine openai\|pydantic` | Live engine (default openai; stdlib urllib fallback, no hard deps) |
| `--allow-destructive` | Consent gate: without it, terminal/patch/write_file/execute_code print `[DRY-RUN]` and skip |

### Live replay prerequisites

`--live` needs an API key: `OPENAI_API_KEY` → `HERMES_API_KEY` →
`~/.hermes/.env`, and an OpenAI-compatible `base_url` (captured in
`PROVIDER_CONFIG` at trace time).

No install is required for the default path — without the `openai`
package the trace falls back to stdlib `urllib`. Install only for the
path you want:

```bash
pip install openai       # SDK path (default engine; nicer errors/retries)
pip install pydantic-ai  # only for --engine pydantic
# or as extras: pip install hermes-unroll[live] / hermes-unroll[pydantic]
```

Dry-run (no flags) needs nothing: it replays from `RESPONSE_CACHE`.

## Practical features

| Feature | Module | Notes |
|---------|--------|-------|
| PII / secrets redaction | `redact.py` | `sk-*`, `ghp_*`/`gho_*`, Bearer, emails, hex secrets; `unroll.redact.custom_patterns` |
| Cost ledger | `pricing.py` | `COST = {model, cost_usd, input_tokens, output_tokens}` + `# Cost: $…` header; `pricing_overrides` |
| Dry-run guard | `safety.py` | Destructive tools skip unless `--allow-destructive` |
| HTML diff | `diff.py` | `render_html_diff()` — self-contained report, no deps |
| Pulse auto-score | `__init__.py` | Opt-in via `UNROLL_PULSE_AUTO_SCORE=1` (default off); writes `<trace>.py.pulse.json`, fail-open |

## Complementary: Pulse

hermes-unroll pairs with [Pulse](https://github.com/dark5un/pulse) — a session health coach that analyses conversation quality. hermes-unroll produces structured traces; Pulse analyses them for signal patterns, attribution, and coaching insights.

## License

MIT
