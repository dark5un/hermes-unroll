# Changelog

All notable changes to hermes-unroll are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [0.5.0] - 2026-09-05

### Added

- Session tags (C2-a capture side): `UNROLL_SESSION_TAGS="team-a,feat-x"`
  (comma-separated; `HERMES_SESSION_TAGS` read as legacy fallback) captured
  at session start onto `TraceSession.tags` and emitted as a `SESSION_TAGS`
  constant in every generated trace. Downstream: Pulse sidecars carry
  `session_tags` and `pulse costs --group-by tag` attributes cost with no
  registry CSV. Empty/unset → `[]`; never breaks traces.

### Fixed

- Session-tags tests load the plugin via importlib spec (unique module name),
  matching the other spec-loading test files — `tests/__init__.py` was
  shadowing the plugin root's `__init__.py` under full-suite runs.

## [Unreleased]

### Fixed

- Exactly-once trace lifecycle: `on_session_end` fires per turn and now only
  updates completion state — the single write happens at
  `on_session_finalize`, which pops and seals the context under the sessions
  lock. `TraceRecorder.finalize()` returns a copy and seals the recorder;
  post-finalize records are dropped. Duplicate finalize is byte-identical.
- Redaction is fail-closed and covers session metadata: new
  `redact_session_metadata()` redacts system_prompt, initial/final text,
  skill/tag lists, and provider_config (pattern + structured secret keys);
  any redaction failure (or a failed `redact` import) aborts persistence
  instead of writing unredacted data. Deletes both fail-open `except` blocks.
- Atomic confidential writes: `generate_trace_program()` writes via temp
  file + fsync + `chmod 0600` + `os.replace()`, sets the traces dir `0700`,
  and appends a content-hash filename suffix so colliding session ids never
  silently overwrite. Captured `provider_config` (base_url/api_mode) is now
  passed through and emitted; keys are never embedded.
- First-turn user message recorded exactly once via the hook's `user_message`
  parameter (UN-9); the reverse-scan duplication is deleted.
- Replay identity (UN-2/UN-3/UN-4/UN-10): stable `event_id` assigned at
  record time; `RESPONSE_CACHE` keyed `tool:<event_id>`/`llm:<event_id>`
  (100% exact resolution, misses raise loudly); recorded (redacted) tool
  args emitted as dispatch defaults; captured `provider_config`
  base_url/api_mode emitted without keys; `--stop-at N` bounds execution
  (count from `--from`) instead of truncating display. Structured
  secret-key redaction now also applies to event payloads (e.g. JWTs under
  `token` keys that match no text pattern).

**Existing artifacts:** traces written before this fix may contain an
unredacted system prompt / profile block at mode 0644. Re-permission with
`chmod 0600 ~/.hermes/traces/unrolled/*.py` (and `chmod 0700` on the dir)
or delete pre-fix traces; new traces are 0600 with metadata redacted. A
`unroll scrub` command for old artifacts is tracked future work.

- Session state is keyed by session id: new `SessionContext` dataclass
  (`recorder`, `model`, `provider`, `first_turn`, `finalized`) in
  `_sessions` dict guarded by `threading.RLock`. Every hook resolves its
  context from its own session argument; unknown sessions are a no-op with
  a debug log, never a fallback. Subagent events belong to the parent
  session. Deletes the process-global `_recorder`/`_session_id`/`_model`/
  `_provider`/`_first_turn` that mixed concurrent sessions' events.

### Added

- Session tags (C2-a capture side): `UNROLL_SESSION_TAGS="team-a,feat-x"`
  (comma-separated; `HERMES_SESSION_TAGS` read as legacy fallback) captured
  at session start onto `TraceSession.tags` and emitted as a `SESSION_TAGS`
  constant in every generated trace. Downstream: Pulse sidecars carry
  `session_tags` and `pulse costs --group-by tag` attributes cost with no
  registry CSV. Empty/unset → `[]`; never breaks traces.

- Live replay prerequisites documented where users actually meet `--live`:
  generated trace docstring states the no-install urllib default plus
  `pip install openai` (SDK path) / `pip install pydantic-ai`
  (`--engine pydantic`) and the `OPENAI_API_KEY` -> `HERMES_API_KEY` ->
  `~/.hermes/.env` key order; `--live`/`--engine` `--help` repeats it.
  New `README` section "Live replay prerequisites".
- `pyproject` optional extras: `pip install hermes-unroll[live]` (openai)
  and `hermes-unroll[pydantic]` (pydantic-ai). Runtime stays zero-dep.

## [0.4.0] - 2026-09-05

### Added

- `ACTIVE_SKILLS` capture: `skill_view` tool calls mark skills active
  (ordered-unique session list, `skill_view` events); emitted as an
  `ACTIVE_SKILLS` constant in every trace.
- `--html` report writer: `--diff OTHER.py --html report.html` writes a
  self-contained HTML diff (`_render_diff_html` inline in the trace file,
  no dependencies) alongside the terminal comparison.

## [0.3.0] - 2026-09-05

First usable release: generated traces are truly executable,
Hermes-independent programs with live replay, safety gates, and audit tools.

### Added

- Timed structured logging: every replayed step measures its own wall time;
  `result` gains `started_at`, `replay_duration_ms`, and a per-step
  `timing_log` comparing original vs replay offsets (`docs/EXECUTION_CONTRACT.md`).
- Range-correct replay: `--from/--to` omits skipped steps from `timing_log`
  while recording `from_step`/`to_step`.
- Tool-schema snapshot on first `pre_api_request` (`TOOL_SCHEMAS`) plus
  provider routing (`PROVIDER_CONFIG`); dry-run dispatch table with cache
  lookup and `--substitute-tool` override.
- Live execution: `--live` with `--engine openai|pydantic` (openai SDK
  default, PydanticAI opt-in, stdlib urllib fallback reading
  `OPENAI_API_KEY`/`HERMES_API_KEY`/`~/.hermes/.env`); never prints keys.
- LangGraph export: `STATE_GRAPH` (nodes/edges/subgraphs) in every trace
  plus guarded `build_langgraph()` (None when langgraph absent).
- Counterfactual engine: `DEPENDENCIES` map, transitive invalidation,
  `--edit '<step> <new-text>'` replays the suffix and saves
  `*_edit_<ts>.py` without touching the original.
- PII/secrets redaction (`redact.py`): API keys, GitHub tokens, Bearer
  headers, emails, hex secrets; custom patterns supported, fail-open.
- Cost ledger (`pricing.py`): `COST = {model, cost_usd, input/output_tokens}`
  plus `# Cost: $…` header; `pricing_overrides` supported.
- Destructive-tool guard (`safety.py`): terminal/patch/write_file/
  execute_code print `[DRY-RUN]` and skip unless `--allow-destructive`.
- HTML diff renderer (`diff.py`): self-contained report, no dependencies.
- Pulse auto-score (opt-in, default off): writes `<trace>.py.pulse.json`
  sidecar, fail-open when Pulse is absent or errors.
- Safe `--diff` loader: `ast.literal_eval` extraction, `exec()` removed.
- Docs: execution contract, live-engine spike decision, spec audit table;
  README with 12-hook list, 9-flag table, and practical-features section.

### Security

- `--diff` no longer `exec()`s the compared trace file; extraction via
  `ast.parse` + `ast.literal_eval` (proven by no-execution probe tests).
- Destructive tools never run without explicit `--allow-destructive`.
- Redaction runs before traces hit disk; live path never logs API keys.

### Known gaps (v0.4)

- `ACTIVE_SKILLS` emission needs a core hook that does not exist yet.
- `--html` writer flag for the diff report (renderer exists and is tested).
