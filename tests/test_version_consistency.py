"""WU-10 (Unroll half): version/manifest consistency gate.

Single version source is pyproject.toml; plugin.yaml, manifest.json, and
the trace template header must match it. This test fails on skew (the
UN-11 defect: manifest 0.4.0 vs plugin 0.5.0).
"""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def _pyproject_version():
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_versions_agree():
    expected = _pyproject_version()
    plugin_yaml = (ROOT / "plugin.yaml").read_text()
    assert f"version: {expected}" in plugin_yaml
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["version"] == expected


def test_template_header_version_matches():
    expected = _pyproject_version()
    header = (ROOT / "templates" / "replay_template.py.txt").read_text()[:400]
    assert f"v{expected}" in header
