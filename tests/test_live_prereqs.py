"""Live prerequisites are documented: optional extras + install guidance.

Users hitting --live on bare Python must be told upfront what to install
(openai SDK path, pydantic-ai engine) instead of discovering it at runtime.
"""

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_pyproject_has_live_optional_extras():
    """pyproject must expose live/pydantic extras so pip can install them."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    optional = data["project"].get("optional-dependencies", {})
    assert "live" in optional, "missing [project.optional-dependencies] live extra"
    assert any("openai" in dep for dep in optional["live"])
    assert "pydantic" in optional, "missing [project.optional-dependencies] pydantic extra"
    assert any("pydantic-ai" in dep for dep in optional["pydantic"])


def test_template_docstring_states_live_prerequisites():
    """Generated trace header must tell users what to install for --live."""
    text = (REPO / "templates" / "replay_template.py.txt").read_text(encoding="utf-8")
    assert "pip install openai" in text
    assert "pip install pydantic-ai" in text
    assert "OPENAI_API_KEY" in text


def test_parse_args_help_mentions_install():
    """--live/--engine --help must point at the install, not just the flag."""
    from generator import _make_parse_args_function

    src = _make_parse_args_function()
    assert "pip install openai" in src
    assert "pip install pydantic-ai" in src


def test_readme_has_live_prerequisites_section():
    """README must have a Live replay prerequisites section."""
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert "prerequisites" in text.lower()
    assert "pip install openai" in text
    assert "pip install pydantic-ai" in text
