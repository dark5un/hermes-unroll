"""H1: --html writer flag for the HTML diff report (requires --diff)."""

import ast
import subprocess
import sys
from pathlib import Path

from generator import _build_program_text, generate_trace_program, reconstruct_messages
from tracer import TraceEvent


def _events_variant_b(t0, text):
    return [
        TraceEvent(kind="user_message", timestamp=t0 + 1.0, data={"text": text}),
        TraceEvent(kind="llm_call", timestamp=t0 + 2.0, data={"response_text": "hello"}),
    ]


def _program_text(events):
    return _build_program_text(
        session_id="html-test",
        timestamp="2026-01-01 00:00:00",
        model="m",
        provider="p",
        events=events,
        messages=reconstruct_messages(events),
        timeline=[
            {"kind": e.kind, "offset_ms": 0, "duration_ms": 0} for e in events
        ],
        system_prompt="",
        final_response="",
        started_at=0,
        cost_usd=0.0,
    )


class TestHtmlFlag:
    def test_generated_source_contains_html_flag(self):
        src = _program_text(_events_variant_b(1000.0, "hi"))
        assert "--html" in src

    def test_generated_source_contains_inline_renderer(self):
        src = _program_text(_events_variant_b(1000.0, "hi"))
        assert "_render_diff_html" in src

    def test_generated_source_parses(self):
        src = _program_text(_events_variant_b(1000.0, "hi"))
        ast.parse(src)

    def test_end_to_end_html_report_with_changed_class(self, tmp_path):
        t0 = 1000.0
        ours = _events_variant_b(t0, "hello ours")
        theirs = [
            TraceEvent(kind="user_message", timestamp=t0 + 1.0, data={"text": "hello theirs"}),
            # Same kinds, different timestamp -> different TIMELINE offset_ms.
            TraceEvent(kind="llm_call", timestamp=t0 + 9.0, data={"response_text": "hello"}),
        ]
        ours_path = generate_trace_program(
            ours, session_id="html_ours_e2e", model="m", provider="p",
            started_at=t0,
        )
        theirs_path = generate_trace_program(
            theirs, session_id="html_theirs_e2e", model="m", provider="p",
            started_at=t0,
        )
        report = tmp_path / "report.html"
        assert Path(ours_path).is_file()
        proc = subprocess.run(
            [sys.executable, ours_path, "--diff", theirs_path, "--html", str(report)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, f"replay failed: {proc.stderr[-2000:]}"
        assert report.is_file(), f"HTML report not written. stdout={proc.stdout[-1500:]}"
        html = report.read_text(encoding="utf-8")
        assert 'class="changed"' in html
