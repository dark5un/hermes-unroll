# Changelog

All notable changes to hermes-unroll are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

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
