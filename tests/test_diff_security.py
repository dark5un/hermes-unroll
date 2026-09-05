"""Security tests for the --diff trace loader (Phase F2).

The replay template must NOT exec() untrusted trace files. The loader
must extract TIMELINE (plus USAGE/STATE_GRAPH/COST/MODEL/SESSION_ID)
via ast.literal_eval so a malicious trace file can never execute code.
"""

import ast
from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "replay_template.py.txt"

WANTED_KEYS = ("TIMELINE", "USAGE", "STATE_GRAPH", "COST", "MODEL", "SESSION_ID")


def _load_diff_values(path: str) -> dict:
    """Mirror of the safe loader embedded in the replay template."""
    import ast as _ast

    with open(path) as _f:
        _diff_text = _f.read()
    try:
        _diff_tree = _ast.parse(_diff_text, filename=path)
    except SyntaxError as _se:
        raise ValueError(f"cannot parse diff trace file: {_se}") from _se
    _other: dict = {}
    for _node in _diff_tree.body:
        if isinstance(_node, _ast.Assign):
            for _t in _node.targets:
                if isinstance(_t, _ast.Name) and _t.id in WANTED_KEYS:
                    try:
                        _other[_t.id] = _ast.literal_eval(_node.value)
                    except Exception:  # noqa: BLE001, S110 -- mirror of template loader: skip non-literal assigns
                        pass
    return _other


class TestDiffLoaderSecurity:
    def test_template_contains_no_exec(self):
        """The template must not use exec() anywhere."""
        text = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "exec(" not in text, "replay template must not use exec()"

    def test_template_uses_ast_literal_eval(self):
        """The diff loader must parse with ast and extract with literal_eval."""
        text = TEMPLATE_PATH.read_text(encoding="utf-8")
        assert "ast" in text, "template diff loader should import/use ast"
        assert "literal_eval" in text, "template diff loader should use literal_eval"
        assert "TIMELINE" in text

    def test_malicious_trace_is_not_executed(self, tmp_path):
        """A probe file with top-level RAISE/os.system must NOT fire."""
        probe = tmp_path / "evil_trace.py"
        probe.write_text(
            "TIMELINE = [{'kind': 'user_message', 'offset_ms': 0}]\n"
            "raise RuntimeError('PWNED_BY_DIFF_LOADER')\n",
            encoding="utf-8",
        )
        # Must extract TIMELINE without executing the raise.
        values = _load_diff_values(str(probe))
        assert values.get("TIMELINE") == [{"kind": "user_message", "offset_ms": 0}]

    def test_os_system_probe_is_not_executed(self, tmp_path):
        """An os.system payload at module level must NOT fire."""
        marker = tmp_path / "pwned_marker.txt"
        probe = tmp_path / "evil_trace2.py"
        probe.write_text(
            "import os\n"
            f"os.system('touch {marker}')\n"
            "TIMELINE = [{'kind': 'llm_call', 'offset_ms': 5}]\n",
            encoding="utf-8",
        )
        values = _load_diff_values(str(probe))
        assert values.get("TIMELINE") == [{"kind": "llm_call", "offset_ms": 5}]
        assert not marker.exists(), "os.system payload must not have executed"

    def test_loader_extracts_all_wanted_keys(self, tmp_path):
        """TIMELINE, USAGE, STATE_GRAPH, COST, MODEL, SESSION_ID extract cleanly."""
        probe = tmp_path / "good_trace.py"
        probe.write_text(
            "TIMELINE = [{'kind': 'user_message'}]\n"
            "USAGE = {'total_api_calls': 1}\n"
            "STATE_GRAPH = {'nodes': [], 'edges': []}\n"
            "COST = {'cost_usd': 0.01}\n"
            "MODEL = 'm'\n"
            "SESSION_ID = 's'\n",
            encoding="utf-8",
        )
        values = _load_diff_values(str(probe))
        assert values["TIMELINE"] == [{"kind": "user_message"}]
        assert values["USAGE"] == {"total_api_calls": 1}
        assert values["STATE_GRAPH"] == {"nodes": [], "edges": []}
        assert values["COST"] == {"cost_usd": 0.01}
        assert values["MODEL"] == "m"
        assert values["SESSION_ID"] == "s"

    def test_loader_rejects_unparseable_file(self, tmp_path):
        """A syntactically invalid file fails with a clear error, no exec."""
        probe = tmp_path / "broken_trace.py"
        probe.write_text("TIMELINE = [this is not valid python {{{\n", encoding="utf-8")
        try:
            _load_diff_values(str(probe))
        except ValueError as e:
            assert "cannot parse" in str(e)
        else:
            raise AssertionError("expected ValueError for unparseable file")

    def test_template_diff_block_parses_as_valid_python(self):
        """The template's own diff-loader block must stay syntactically valid."""
        text = TEMPLATE_PATH.read_text(encoding="utf-8")
        # string.Template uses $VARS; substitute dummies so ast.parse sees plain code.
        import re
        import string

        dummy = {m.group(1): "None" for m in re.finditer(r"\$([A-Za-z_][A-Za-z0-9_]*)", text)}
        filled = string.Template(text).safe_substitute(dummy)
        tree = ast.parse(filled)
        assert isinstance(tree, ast.Module)
