"""B1: tool_schemas snapshot on FIRST pre_api_request per session.

Plugin __init__ loaded via importlib spec to avoid package collisions
(same pattern as test_pulse_integration.py).
"""

import importlib.util
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
INIT_PATH = PLUGIN_ROOT / "__init__.py"


def _load_plugin():
    spec = importlib.util.spec_from_file_location("unroll_plugin_toolschemas", INIT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["unroll_plugin_toolschemas"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fresh_session(mod, session_id="s-tool-1"):
    mod._on_session_start(session_id=session_id, model="gpt-4o", platform="openai")
    return mod._get_session(session_id).recorder


def _pre_kwargs(tools=None, **extra):
    body = {} if tools is None else {"tools": tools}
    kw = {
        "session_id": "s-tool-1",
        "model": "gpt-4o",
        "provider": "openai",
        "request_messages": [],
        "conversation_history": [],
        "user_message": "hi",
        "api_call_count": 1,
        "retry_count": 0,
        "approx_input_tokens": 10,
        "message_count": 2,
        "tool_count": len(tools or []),
        "request": {"method": "POST", "body": body},
        "system_prompt": "",
        "base_url": "https://api.openai.com/v1",
        "api_mode": "responses",
    }
    kw.update(extra)
    return kw


def test_first_call_records_tool_schemas_event():
    mod = _load_plugin()
    _fresh_session(mod)
    tools = [{"type": "function", "function": {"name": "read"}}]
    mod._on_pre_api_request(**_pre_kwargs(tools=tools))
    kinds = [e.kind for e in mod._get_session("s-tool-1").recorder.session.events]
    assert "tool_schemas" in kinds
    evt = next(e for e in mod._get_session("s-tool-1").recorder.session.events if e.kind == "tool_schemas")
    assert evt.data["tools"] == tools
    assert evt.data["tool_count"] == 1
    pc = mod._get_session("s-tool-1").recorder.session.provider_config
    assert pc["provider"] == "openai"
    assert pc["base_url"] == "https://api.openai.com/v1"
    assert pc["api_mode"] == "responses"
    assert pc["model"] == "gpt-4o"


def test_second_call_does_not_duplicate():
    mod = _load_plugin()
    _fresh_session(mod)
    mod._on_pre_api_request(**_pre_kwargs(tools=[{"type": "function"}]))
    mod._on_pre_api_request(
        **_pre_kwargs(tools=[{"type": "other"}], api_call_count=2)
    )
    schemas = [e for e in mod._get_session("s-tool-1").recorder.session.events if e.kind == "tool_schemas"]
    assert len(schemas) == 1


def test_missing_request_key_handled_fail_open():
    mod = _load_plugin()
    _fresh_session(mod)
    kw = _pre_kwargs(tools=[{"type": "function"}])
    del kw["request"]
    mod._on_pre_api_request(**kw)  # must not raise
    schemas = [e for e in mod._get_session("s-tool-1").recorder.session.events if e.kind == "tool_schemas"]
    assert len(schemas) == 1
    assert schemas[0].data["tools"] == []
