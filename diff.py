"""hermes-unroll — HTML diff of two agent traces.

Compares two event sequences step-by-step (aligned by index) and renders
a self-contained HTML page with inline CSS. No external dependencies.
"""

import html as _html
from typing import Any


def _kind_of(event: Any) -> str:
    if isinstance(event, dict):
        return str(event.get("kind", "?"))
    return str(getattr(event, "kind", "?"))


def _data_of(event: Any) -> dict:
    if isinstance(event, dict):
        data = event.get("data", {})
        return data if isinstance(data, dict) else {"value": data}
    data = getattr(event, "data", {})
    return data if isinstance(data, dict) else {"value": data}


def _ts_of(event: Any) -> float | None:
    if isinstance(event, dict):
        ts = event.get("timestamp")
    else:
        ts = getattr(event, "timestamp", None)
    try:
        return float(ts) if ts is not None else None
    except (TypeError, ValueError):
        return None


def _summarize(event: Any) -> str:
    kind = _kind_of(event)
    data = _data_of(event)
    if not data:
        return kind
    items = ", ".join(f"{k}={v!r}" for k, v in sorted(data.items()))
    text = f"{kind}({items})"
    return text if len(text) <= 300 else text[:297] + "..."


def _fmt_delta(delta_ms: float) -> str:
    sign = "+" if delta_ms >= 0 else "\u2212"  # minus sign for negatives
    # Use ASCII '+'/'-' prefix style: tests look for "+50ms"; keep '-' ASCII too.
    if delta_ms < 0:
        sign = "-"
    return f"{sign}{abs(delta_ms):.0f}ms"


def _step_duration_ms(
    idx: int,
    events: list,
    timeline: list[float] | tuple | None,
) -> float | None:
    if timeline is not None and idx < len(timeline):
        try:
            return float(timeline[idx])
        except (TypeError, ValueError):
            return None
    if idx < len(events):
        ts = _ts_of(events[idx])
        if ts is None:
            return None
        # timestamp is seconds (time.time); convert step gap to ms when possible
        if idx == 0:
            return 0.0
        prev = _ts_of(events[idx - 1])
        if prev is None:
            return None
        return (ts - prev) * 1000.0
    return None


def render_html_diff(
    our_events: list,
    their_events: list,
    timeline_ours: list[float] | tuple | None = None,
    timeline_theirs: list[float] | tuple | None = None,
) -> str:
    """Render a self-contained HTML diff of two traces aligned by step index.

    Rows are classified per step index:
      - both sides present and equal   -> class="unchanged"
      - both present but different     -> class="changed"
      - only in theirs                 -> class="added"
      - only in ours                   -> class="removed"
    """
    ours = list(our_events or [])
    theirs = list(their_events or [])
    n = max(len(ours), len(theirs))

    rows: list[str] = []
    n_changed = n_added = n_removed = n_unchanged = 0
    for i in range(n):
        in_ours = i < len(ours)
        in_theirs = i < len(theirs)
        if in_ours and in_theirs:
            same = _kind_of(ours[i]) == _kind_of(theirs[i]) and _data_of(
                ours[i]
            ) == _data_of(theirs[i])
            cls = "unchanged" if same else "changed"
            left = _summarize(ours[i])
            right = _summarize(theirs[i])
            if same:
                n_unchanged += 1
            else:
                n_changed += 1
        elif in_theirs:
            cls = "added"
            left = "\u2014"
            right = _summarize(theirs[i])
            n_added += 1
        else:
            cls = "removed"
            left = _summarize(ours[i])
            right = "\u2014"
            n_removed += 1

        d_ours = _step_duration_ms(i, ours, timeline_ours)
        d_theirs = _step_duration_ms(i, theirs, timeline_theirs)
        if d_ours is not None and d_theirs is not None:
            delta = _fmt_delta(d_theirs - d_ours)
        else:
            delta = "n/a"

        rows.append(
            f'<tr class="{cls}"><td class="idx">{i}</td>'
            f"<td>{_html.escape(left)}</td>"
            f"<td>{_html.escape(right)}</td>"
            f'<td class="delta">{_html.escape(delta)}</td></tr>'
        )

    body_rows = "\n".join(rows) if rows else (
        '<tr class="unchanged"><td class="idx">\u2014</td>'
        "<td>no steps</td><td>no steps</td>"
        '<td class="delta">n/a</td></tr>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trace diff</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #111; }}
h1 {{ font-size: 1.25rem; }}
.summary {{ margin-bottom: 1rem; color: #444; }}
table.diff {{ border-collapse: collapse; width: 100%; }}
table.diff th, table.diff td {{ border: 1px solid #ccc; padding: 6px 10px;
  text-align: left; vertical-align: top; font-size: 0.9rem; }}
table.diff th {{ background: #f0f0f0; }}
tr.unchanged {{ background: #ffffff; }}
tr.changed {{ background: #fff3cd; }}
tr.added {{ background: #d4edda; }}
tr.removed {{ background: #f8d7da; }}
td.idx {{ width: 3em; text-align: right; color: #666; }}
td.delta {{ white-space: nowrap; }}
</style>
</head>
<body>
<h1>Trace diff</h1>
<p class="summary">steps: ours={len(ours)} theirs={len(theirs)} &mdash;
changed={n_changed} added={n_added} removed={n_removed}
unchanged={n_unchanged}</p>
<table class="diff">
<thead><tr><th>step</th><th>ours</th><th>theirs</th><th>&Delta; (theirs&minus;ours)</th></tr></thead>
<tbody>
{body_rows}
</tbody>
</table>
</body>
</html>"""
