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

Hermes exposes hooks at every lifecycle point — `post_llm_call`, `post_tool_call`, `on_session_end` — with consistent signatures and clean separation from core logic. That's the whole reason this plugin exists: the hook surface is well-designed enough that capturing every turn and emitting a runnable program took under 800 lines, zero core patches, and no monkeypatching.

| What you can do with a trace file | How |
|----------------------------------|-----|
| **Reproduce a run** | `python trace.py` replays the exact conversation |
| **Debug step by step** | Inspect LLM output at message 7, substitute a tool result, see what changes |
| **Regression test models** | Collect traces from production, run them in CI against candidate models |
| **Audit decisions** | `diff tuesday.py wednesday.py` shows exactly what the agent did differently |
| **Extract training data** | Traces are structured message lists — ready for fine-tuning or reward modelling |
| **Reapply reasoning patterns** | Change the first prompt, re-run, get a tailored agent for a similar task |

## How it works

Three hooks, one accumulator, one code generator.

| Component | File | Job |
|-----------|------|-----|
| `register(ctx)` | `__init__.py` | Wires hooks to the tracer |
| `TraceRecorder` | `tracer.py` | Accumulates `TraceEvent` objects during a session |
| `generate_trace_program()` | `generator.py` | Walks events, reconstructs messages, emits valid Python |

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
├── plugin.yaml              # Hermes plugin manifest
├── __init__.py              # Hook wiring
├── hermes_unroll/
│   ├── tracer.py            # Events + recorder
│   └── generator.py         # Code generator
├── tests/
│   ├── test_tracer.py       # 40 tests
│   └── test_generator.py
├── SPECIFICATION.md          # Full 9,000-word proposal
└── README.md
```

## Development

```bash
uv sync
uv run pytest          # 40 tests pass
uv run ruff check .    # lint clean
```

## Complementary: Pulse

hermes-unroll pairs with [Pulse](https://github.com/dark5un/pulse) — a session health coach that analyses conversation quality. hermes-unroll produces structured traces; Pulse analyses them for signal patterns, attribution, and coaching insights.

## License

MIT