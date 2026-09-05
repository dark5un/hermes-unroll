"""B2: cost ledger — COST dict + cost header comment, math correct."""

import importlib.util
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
INIT_PATH = PLUGIN_ROOT / "__init__.py"


def _load_plugin(name="unroll_plugin_cost"):
    spec = importlib.util.spec_from_file_location(name, INIT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod.__name__] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generate_trace_program_emits_cost():
    from generator import generate_trace_program
    from pricing import estimate_cost
    from tracer import TraceEvent

    events = [TraceEvent(kind="user_message", data={"text": "hi"})]
    expected = estimate_cost("gpt-4o", 1000, 2000)
    assert expected > 0
    path = generate_trace_program(
        events,
        session_id="cost-unit-test",
        model="gpt-4o",
        provider="openai",
        cost_usd=expected,
    )
    code = Path(path).read_text(encoding="utf-8")
    assert "COST" in code
    assert re.search(r"(?i)#.*cost.*\$?\s*[\d.]+", code), "cost header comment missing"
    ns: dict = {"__name__": "cost_check"}
    exec(compile(code, path, "exec"), ns)  # noqa: S102 — reading back generated COST
    assert isinstance(ns["COST"], dict)
    assert abs(ns["COST"]["cost_usd"] - expected) < 1e-9


def test_generate_trace_computes_cost_from_usage(tmp_path, monkeypatch):
    from pricing import estimate_cost

    mod = _load_plugin("unroll_plugin_cost_e2e")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod._on_session_start(session_id="cost-e2e", model="gpt-4o", platform="openai")
    rec = mod._get_session("cost-e2e").recorder
    rec.session.system_prompt = "sys"
    rec.session.initial_user_message = "hi"
    rec.record("user_message", {"text": "hi"})
    rec.record("post_api_request", {"usage": {"input_tokens": 1000, "output_tokens": 2000}})
    rec.record("post_api_request", {"usage": {"input_tokens": 500, "output_tokens": 500}})
    mod._generate_trace("cost-e2e")
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert traces, "trace program should be written"
    code = traces[0].read_text(encoding="utf-8")
    assert "COST" in code
    expected = estimate_cost("gpt-4o", 1500, 2500)
    ns: dict = {"__name__": "cost_check"}
    exec(compile(code, str(traces[0]), "exec"), ns)  # noqa: S102 — reading back generated COST
    assert abs(ns["COST"]["cost_usd"] - expected) < 1e-9
