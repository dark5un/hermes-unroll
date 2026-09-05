"""Per-model token pricing and cost estimation.

Prices are USD per 1M tokens, stored as ``{"input": ..., "output": ...}``.
Values track public list prices at time of writing; pass ``pricing_overrides``
to use fresher/custom rates without editing this table.
"""

PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.00},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "llama-3.1-70b": {"input": 0.88, "output": 0.88},
    "llama-3.1-8b": {"input": 0.18, "output": 0.18},
    "mistral-large": {"input": 2.00, "output": 6.00},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
}


def _resolve_rate(model: str, kind: str, pricing_overrides=None) -> float | None:
    """Return the per-1M rate for ``kind`` ("input"/"output"), or None if unknown."""
    if pricing_overrides and model in pricing_overrides:
        override = pricing_overrides[model]
        if isinstance(override, dict):
            value = override.get(kind)
        elif isinstance(override, (tuple, list)) and len(override) == 2:
            value = override[0] if kind == "input" else override[1]
        else:
            value = None
        if value is not None:
            return float(value)
        # Override present but missing this side: fall through to base table.
    entry = PRICING.get(model)
    if entry is None:
        return None
    return float(entry[kind])


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing_overrides: dict | None = None,
) -> float:
    """Estimate USD cost for a model call.

    Unknown models return 0.0. ``pricing_overrides`` maps model names to
    ``{"input": per_1M, "output": per_1M}`` (tuples ``(in, out)`` also accepted)
    and takes precedence over :data:`PRICING`.
    """
    in_rate = _resolve_rate(model, "input", pricing_overrides)
    out_rate = _resolve_rate(model, "output", pricing_overrides)
    if in_rate is None or out_rate is None:
        return 0.0
    return input_tokens / 1_000_000 * in_rate + output_tokens / 1_000_000 * out_rate
