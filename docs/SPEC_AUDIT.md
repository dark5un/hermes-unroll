# hermes-unroll — Spec Alignment Audit (F1)

Plan: `.hermes/plans/2026-09-05_120000-hermes-unroll-executable-trace.md`
Audited: 2026-09-05 against `main` post-E/F2. Method: read-only source
inspection (hooks, replay branches, argparse flags, modules, tests).

## Evidence counts

- **Hooks:** `plugin.yaml` + `manifest.json` = 12
  (`on_session_start, post_llm_call, post_tool_call, on_session_end,
  on_session_finalize, pre_api_request, post_api_request,
  api_request_error, subagent_start, subagent_stop, on_stream_delta,
  pre_tool_call`); all 12 have `record()` calls + `def _on_*` in
  `__init__.py` (12 `register_hook` calls).
- **`_build_replay_steps` event kinds:** 13 branches — the 12 above plus
  `tool_schemas` (B1 snapshot event, keeps timeline/steps length invariant).
- **Generated-file CLI flags** (`_make_parse_args_function`): `--live,
  --from/--to, --stop-at, --substitute-tool, --show-state, --diff,
  --edit, --engine, --allow-destructive`.
- **Tests:** 16 files, 115 passing, `ruff check` clean.

## Item status

| Item | Status | Code evidence | Test evidence |
|---|---|---|---|
| A1 contract+schema | DONE | `docs/EXECUTION_CONTRACT.md` (result keys, timing shape, exit 0/1/2); README "Execution" section | — (doc) |
| A2 timed replay | DONE | `_build_replay_steps` + `_make_replay_function` (`t0/t1 perf_counter`); template `timing_log` init/summary | `test_timing_log.py` |
| A3 range replay | DONE | `--from/--to` + `from_step/to_step` in result; skipped steps omitted from `timing_log` | `test_range_replay.py` + range tests in `test_generator.py` |
| B1 tool schemas | DONE | `__init__.py` (`tool_schemas` event on first `pre_api_request` from `request["body"]["tools"]`); `_build_tool_schemas` → `TOOL_SCHEMAS` | `test_tool_schemas.py` |
| B2 provider routing (+skills) | DONE w/ gap | `provider_config` (provider/base_url/api_mode) → `PROVIDER_CONFIG`; **no `ACTIVE_SKILLS` emission** | `test_live_generation.py` (PROVIDER_CONFIG) |
| B3 dispatch table | DONE | template `dispatch_tool` (cache lookup + substitute override); dry-run default | `test_live_generation.py` |
| C1 engine spike | DONE | `docs/LIVE_ENGINE_SPIKE.md` (openai default, pydantic optional, urllib fallback) | — (doc) |
| C2 `--live` path | DONE | `_make_live_helper`, `_live_llm_call`, `_load_api_key` (OPENAI→HERMES→`.env`); `llm_call` `if LIVE:` branch | `test_live_generation.py` |
| C3 `--substitute-tool` | DONE | substitution check in `tool_call` block; `--allow-destructive` gate | `test_live_generation.py` |
| D1 state graph | DONE | `_build_state_graph` → `STATE_GRAPH` + `state_graph` in result | `test_state_graph.py` |
| D2 langgraph export | DONE | guarded `from langgraph.graph import StateGraph`; `build_langgraph()` → None if absent | `test_state_graph.py` |
| E1 dep map | DONE | `_build_dependency_map` → `DEPENDENCIES`; `_transitive_invalidated` | `test_dependencies.py`, `test_counterfactual.py` |
| E2 save-on-edit | DONE | `_save_edited_trace` (`*_edit_<ts>.py`, never overwrites); `cost` in result | `test_counterfactual.py` (+ live `--edit` run) |
| G1 redact | DONE | `redact.py`; fail-open `redact_event` in `_generate_trace` | `test_redact.py` |
| G2 cost ledger | DONE | `pricing.py:estimate_cost + pricing_overrides`; `COST` + `# Cost: $…` header | `test_pricing.py`, `test_cost_ledger.py` |
| G3 destructive guard | DONE | `safety.py:is_destructive`; dry-run skip + `skipped: True`; `--allow-destructive` | `test_safety.py`, `test_live_generation.py` |
| G4 HTML diff | DONE (CLI) w/ gap | `diff.py:render_html_diff`; `--diff` via safe `ast.literal_eval` loader; **no `--html` writer flag** | `test_diff.py`, `test_diff_security.py` |
| G5 pulse score | DONE | guarded import (`unroll.pulse_auto_score`, default false, fail-open) + sidecar | `test_pulse_integration.py` |
| F2 E2E + hardening | DONE (code) / OPEN (blog) | 12-kind survival test (TIMELINE/RESPONSE_CACHE/REASONING_BLOCKS/STATE_GRAPH); `exec→literal_eval` fix | `test_generator.py`, `test_diff_security.py` |

## Known gaps (accepted for v0.3.0)

1. **B2 skill context:** `ACTIVE_SKILLS` never emitted. Provider routing is
   captured; skill capture needs a core hook that does not exist yet.
   Downgraded to a v0.4 item.
2. **G4 `--html` flag:** `render_html_diff()` exists and is tested, but the
   generated program's `--diff` only prints text. The `--html` writer is a
   v0.4 item.
3. **F2 blog sync:** `onlyascii.dev` posts live outside this repo; owner to
   verify separately.
