"""Tests for pricing.py — per-1M-token cost estimates."""

from pricing import PRICING, estimate_cost


def test_pricing_covers_expected_models():
    expected = [
        "gpt-4o",
        "gpt-4o-mini",
        "claude-3-5-sonnet",
        "claude-3-5-haiku",
        "deepseek-chat",
        "deepseek-reasoner",
        "llama-3.1-70b",
        "llama-3.1-8b",
        "mistral-large",
        "gemini-1.5-pro",
    ]
    for model in expected:
        assert model in PRICING, f"{model} missing from PRICING"
        entry = PRICING[model]
        assert entry["input"] > 0
        assert entry["output"] > 0


def test_gpt4o_1000_in_500_out_math():
    entry = PRICING["gpt-4o"]
    expected = 1000 / 1_000_000 * entry["input"] + 500 / 1_000_000 * entry["output"]
    assert estimate_cost("gpt-4o", 1000, 500) == expected


def test_unknown_model_returns_zero():
    assert estimate_cost("no-such-model-xyz", 1000, 500) == 0.0


def test_pricing_overrides_respected():
    overrides = {"gpt-4o": {"input": 1.0, "output": 2.0}}
    expected = 1000 / 1_000_000 * 1.0 + 500 / 1_000_000 * 2.0
    assert estimate_cost("gpt-4o", 1000, 500, pricing_overrides=overrides) == expected


def test_zero_tokens_zero_cost():
    assert estimate_cost("gpt-4o", 0, 0) == 0.0
