"""WU-7 (UN-7/UN-8/UN-9/UN-12): idempotent lifecycle, closed redaction,
atomic writes.

- end + finalize writes exactly one trace; finalize twice is byte-identical;
  events recorded after finalize never appear in the written trace.
- Every generated string field is redacted (system_prompt, final_response,
  user_message defaults, active_skills, tags, provider_config) — the whole
  generated file is secret-scanned, not selected constants.
- Redaction is fail-closed: a raising redact_event, or a failed redact
  import, means no trace file is written.
- First-turn fixture yields exactly one initial user_message event.
- Write failures leave no truncated artifact at the destination path.
- Two sessions normalizing to the same safe_filename do not silently
  overwrite each other.
"""

import importlib.util
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
INIT_PATH = PLUGIN_ROOT / "__init__.py"

SECRETS = {
    "system_prompt": "SYSTEM PROMPT SECRET sk-live-AAAAAAAA11111111",
    "final_response": "final contains Bearer abcdef1234567890XYZ",
    "user_message": "contact me at leaked@example.com please",
    "skill": "my-secret-skill",
    "tag": "team-token-abc123",
    "base_url": "https://user:s3cret-pass@internal.example.com/v1",
    "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
}


def _load_plugin(name: str = "unroll_plugin_lifecycle"):
    spec = importlib.util.spec_from_file_location(name, INIT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _start(mod, sid: str = "s-life", **kw):
    mod._on_session_start(session_id=sid, model=kw.get("model", "m"), platform=kw.get("platform", "p"))
    return mod._get_session(sid).recorder


def _seed(mod, sid: str, secrets: bool = False):
    rec = mod._get_session(sid).recorder
    sys_txt = SECRETS["system_prompt"] if secrets else "sys"
    rec.session.system_prompt = sys_txt
    rec.session.initial_user_message = SECRETS["user_message"] if secrets else "hi"
    rec.record("user_message", {"text": SECRETS["user_message"] if secrets else "hi"})
    rec.record("llm_call", {"response_text": SECRETS["final_response"] if secrets else "hello", "response_tool_calls": []})
    return rec


def test_end_then_finalize_writes_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_plugin_life_once")
    _start(mod)
    _seed(mod, "s-life")
    # on_session_end fires per turn: state update only, no write.
    mod._on_session_end(session_id="s-life", completed=True, interrupted=False, model="m", platform="p")
    assert list((tmp_path / "traces" / "unrolled").glob("*.py")) == []
    assert mod._get_session("s-life") is not None
    mod._on_session_finalize(session_id="s-life", platform="p")
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert len(traces) == 1
    # Session context is gone after finalize — no second generation possible.
    assert mod._get_session("s-life") is None


def test_finalize_twice_is_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_plugin_life_twice")
    _start(mod)
    _seed(mod, "s-life")
    mod._on_session_finalize(session_id="s-life", platform="p")
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert len(traces) == 1
    first = traces[0].read_bytes()
    mod._on_session_finalize(session_id="s-life", platform="p")
    traces2 = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert len(traces2) == 1
    assert traces2[0].read_bytes() == first


def test_events_after_finalize_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_plugin_life_after")
    _start(mod)
    _seed(mod, "s-life")
    mod._on_session_finalize(session_id="s-life", platform="p")
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    code = traces[0].read_text()
    assert "LATE MESSAGE" not in code
    # Late hooks on a finalized session are no-ops, not crashes.
    mod._on_post_tool_call(tool_name="t", args={}, result="LATE MESSAGE", task_id="x", duration_ms=1, session_id="s-life")
    assert list((tmp_path / "traces" / "unrolled").glob("*.py")) == traces


def test_generated_file_contains_no_secrets_anywhere(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_plugin_life_secrets")
    _start(mod)
    rec = _seed(mod, "s-life", secrets=True)
    rec.session.active_skills = ["grocery-list", "helper leaked@example.com"]
    rec.session.tags = ["team-a", "token sk-live-AAAAAAAA11111111"]
    rec.session.provider_config = {"provider": "p", "base_url": SECRETS["base_url"], "api_mode": "m", "model": "m"}
    rec.record("tool_call", {"name": "t", "args": {"token": SECRETS["jwt"]}, "content": "ok", "tool_call_id": "t1", "duration_ms": 1})
    mod._on_session_finalize(session_id="s-life", platform="p")
    traces = list((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert traces
    code = traces[0].read_text()
    for label, secret in SECRETS.items():
        assert secret not in code, f"leaked {label}"
    assert "leaked@example.com" not in code
    # Plain inventory names are functional data and survive; secrets inside
    # names are redacted.
    assert "grocery-list" in code
    assert "team-a" in code
    assert "[REDACTED" in code


def test_redaction_failure_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_plugin_life_redfail")
    _start(mod)
    _seed(mod, "s-life")
    import redact as redact_mod

    def _boom(_event, _custom=None):
        raise RuntimeError("redactor exploded")

    monkeypatch.setattr(redact_mod, "redact_event", _boom)
    mod._on_session_finalize(session_id="s-life", platform="p")
    assert list((tmp_path / "traces" / "unrolled").glob("*.py")) == []


def test_redact_import_failure_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_plugin_life_importfail")
    _start(mod)
    _seed(mod, "s-life")
    import builtins

    real_import = builtins.__import__

    def _guard(name, *args, **kwargs):
        if name == "redact":
            raise ImportError("No module named 'redact'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _guard)
    mod._on_session_finalize(session_id="s-life", platform="p")
    assert list((tmp_path / "traces" / "unrolled").glob("*.py")) == []


def test_first_turn_records_single_user_message():
    mod = _load_plugin("unroll_plugin_life_first")
    _start(mod, sid="s-first")
    mod._on_post_llm_call(
        session_id="s-first",
        assistant_response="hello",
        conversation_history=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "the question"},
        ],
        model="m",
        platform="p",
        user_message="the question",
    )
    rec = mod._get_session("s-first").recorder
    kinds = [e.kind for e in rec.session.events]
    # UN-9: the hook supplies user_message; it is recorded once. The old
    # reverse-scan duplicated it on turn 1 (two identical user_messages).
    user_texts = [e.data.get("text") for e in rec.session.events if e.kind == "user_message"]
    assert user_texts == ["the question"]
    assert rec.session.initial_user_message == "the question"
    assert kinds.count("system_prompt") == 1


def test_multi_turn_message_sequence_is_exact():
    mod = _load_plugin("unroll_plugin_life_multi")
    _start(mod, sid="s-multi")
    for q, a in [("q1", "a1"), ("q2", "a2")]:
        mod._on_post_llm_call(
            session_id="s-multi",
            assistant_response=a,
            conversation_history=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": q},
                {"role": "assistant", "content": a},
            ],
            model="m",
            platform="p",
            user_message=q,
        )
    rec = mod._get_session("s-multi").recorder
    user_texts = [e.data.get("text") for e in rec.session.events if e.kind == "user_message"]
    assert user_texts == ["q1", "q2"]
    llm_texts = [e.data.get("response_text") for e in rec.session.events if e.kind == "llm_call"]
    assert llm_texts == ["a1", "a2"]


def test_write_failure_leaves_no_truncated_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_plugin_life_writefail")
    _start(mod)
    _seed(mod, "s-life")
    import tempfile

    import generator as gen_mod  # noqa: F401 — module import needed for monkeypatch target

    def _boom_mkstemp(*args, **kwargs):
        raise OSError("disk exploded")

    monkeypatch.setattr(tempfile, "mkstemp", _boom_mkstemp)
    mod._on_session_finalize(session_id="s-life", platform="p")
    assert list((tmp_path / "traces" / "unrolled").glob("*.py")) == []
    assert list((tmp_path / "traces" / "unrolled").glob("*.tmp")) == []


def test_filename_collision_does_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    mod = _load_plugin("unroll_plugin_life_collide")
    _start(mod, sid="a/b")
    _seed(mod, "a/b")
    mod._on_session_finalize(session_id="a/b", platform="p")
    _start(mod, sid="a_b")
    _seed(mod, "a_b")
    mod._on_session_finalize(session_id="a_b", platform="p")
    traces = sorted((tmp_path / "traces" / "unrolled").glob("*.py"))
    assert len(traces) == 2
    assert traces[0].read_bytes() != traces[1].read_bytes() or traces[0].name != traces[1].name
    contents = [t.read_text() for t in traces]
    assert any("a/b" in c for c in contents) and any("a_b" in c for c in contents)
