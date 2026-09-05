# Execution Contract — Hermes-Unroll Executable Trace

Source plan: `2026-09-05_120000` (`.hermes/plans/2026-09-05_120000-hermes-unroll-executable-trace.md`, Phase A Task A1).

This document locks the JSON schema emitted by the generated
`traces/unrolled/<session>.py` replay program so all later tasks
(Phase A–G) have a stable target.

## 1. `result` top-level keys

The structured JSON printed at the end of a replay MUST contain exactly
these top-level keys:

| Key | Type | Meaning |
|-----|------|---------|
| `session_id` | str | Original traced session id |
| `model` | str | Model name used in the original session |
| `provider` | str | Provider name (e.g. `openai`, `openrouter`) |
| `started_at` | str | ISO-8601 start timestamp of the original session |
| `original_duration_ms` | int | Wall time of the original session in milliseconds |
| `replay_duration_ms` | int | Wall time of the replay run in milliseconds |
| `messages_count` | int | `len(messages)` at end of replay |
| `steps` | list[dict] | Per-event step records (see §3) |
| `messages` | list[dict] | Rebuilt chat messages (`role` / `content`) |
| `usage` | dict | Token/cost usage aggregate (`prompt_tokens`, `completion_tokens`, `total_tokens`, …) |
| `reasoning_blocks` | list | Captured reasoning blocks (may be empty) |
| `timing_log` | list[dict] | Per-step timing comparison log (see §2) |
| `response_cache` | dict | Cached LLM/tool responses keyed by step |
| `from_step` | int \| null | `--from` range lower bound (null = start) |
| `to_step` | int \| null | `--to` range upper bound (null = end) |

Additional keys (e.g. `state_graph`, `REDACTED_FIELDS`) may be added by
later phases but MUST NOT remove or rename the keys above.

## 2. `timing_log` entry shape

Every executed step appends one entry with exactly this shape:

```json
{
  "step": 0,
  "kind": "user_message",
  "original_offset_ms": 0,
  "replay_offset_ms": 0,
  "delta_ms": 0,
  "duration_ms": 12,
  "replay_duration_ms": 1
}
```

| Field | Type | Meaning |
|-------|------|---------|
| `step` | int | Zero-based step index (matches `steps[i]`) |
| `kind` | str | Event kind (`user_message`, `llm_call`, `tool_call`, `tool_result`, … — 12 hook kinds) |
| `original_offset_ms` | int | Offset of this step in the original `TIMELINE` |
| `replay_offset_ms` | int | Offset of this step in the replay run (ms since replay start) |
| `delta_ms` | int | `replay_offset_ms - original_offset_ms` (drift indicator) |
| `duration_ms` | int \| null | Original step duration (`null` when unknown) |
| `replay_duration_ms` | int | Measured replay wall time for this step (`round((t1 - t0) * 1000)`) |

Rules:

- `len(timing_log) == len(steps)` for a full (unranged) replay.
- Range replays (`--from`/`--to`) MUST still record `from_step`/`to_step`
  in `result`; skipped steps are either omitted from `timing_log` or
  marked `{"skipped": true}` (decision locked in Task A3).
- Each guarded replay block measures wall time with
  `t0 = time.perf_counter()` / `t1 = time.perf_counter()`.

## 3. `steps` entries

Each entry in `steps` carries the original timing fields PLUS the replay
measurement:

- `duration_ms` — original step duration (int | null).
- `replay_duration_ms` — measured replay duration for that step (int).

`steps[i]` and `timing_log[i]` share the same `step` index.

## 4. Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success — replay completed, valid JSON printed |
| `1` | Generation error — trace build or replay raised |
| `2` | Arg-parse error — invalid CLI flags (`--from`/`--to`, `--stop-at`, `--edit`, …) |

## 5. Compatibility

- The generated file is standalone: it MUST NOT import
  `run_agent.AIAgent` or any Hermes internals.
- Consumers may parse `result` with `python trace.py | jq .timing_log`
  or `jq .steps`, `.messages`, `.usage`.
