"""Tests for the hermes-unroll HTML trace diff (diff.py)."""

from diff import render_html_diff


def _ev(kind, data=None, ts=0.0):
    return {"kind": kind, "data": data or {}, "timestamp": ts}


class TestRenderHtmlDiff:
    def test_changed_step_marked(self):
        ours = [_ev("a", ts=1.0), _ev("b", ts=2.0), _ev("c", ts=3.0)]
        theirs = [_ev("a", ts=1.0), _ev("X", ts=2.5), _ev("c", ts=3.0)]
        html = render_html_diff(ours, theirs)
        assert 'class="changed"' in html

    def test_added_and_removed_steps_marked(self):
        ours = [_ev("a", ts=1.0)]
        theirs = [_ev("a", ts=1.0), _ev("b", ts=2.0)]
        html = render_html_diff(ours, theirs)
        assert 'class="added"' in html

        html2 = render_html_diff(theirs, ours)
        assert 'class="added"' in html2 or 'class="removed"' in html2

    def test_timing_delta_shown_per_step(self):
        ours = [_ev("a", ts=100.0), _ev("b", ts=101.0)]
        theirs = [_ev("a", ts=100.0), _ev("b", ts=101.5)]
        html = render_html_diff(ours, theirs)
        assert "ms" in html

    def test_self_contained_html_with_inline_css(self):
        html = render_html_diff([_ev("a")], [_ev("a")])
        assert "<html" in html.lower()
        assert "<style" in html.lower()
        assert "</html>" in html.lower()

    def test_identical_traces_have_no_diff_classes(self):
        ours = [_ev("a", ts=1.0), _ev("b", ts=2.0)]
        html = render_html_diff(ours, list(ours))
        assert 'class="changed"' not in html
        assert 'class="added"' not in html
        assert 'class="removed"' not in html

    def test_accepts_objects_with_attributes(self):
        class E:
            def __init__(self, kind, data, timestamp):
                self.kind = kind
                self.data = data
                self.timestamp = timestamp

        ours = [E("a", {}, 1.0), E("b", {}, 2.0), E("c", {}, 3.0)]
        theirs = [E("a", {}, 1.0), E("Z", {}, 2.0), E("c", {}, 3.0)]
        html = render_html_diff(ours, theirs)
        assert 'class="changed"' in html

    def test_explicit_timelines_used_for_delta(self):
        ours = [_ev("a"), _ev("b")]
        theirs = [_ev("a"), _ev("b")]
        html = render_html_diff(
            ours, theirs, timeline_ours=[100.0, 200.0], timeline_theirs=[150.0, 200.0]
        )
        assert "+50ms" in html or "+50" in html
