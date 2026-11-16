"""Model prices in USD per 1M tokens: (input, output).

Defaults cover Anthropic's current models (list prices, Nov 2026). Any other model,
Gemini included, is priced through the MODEL_PRICES env var, e.g.
    MODEL_PRICES={"gemini-3.8-flash": [0.30, 2.50]}
Unpriced models still count tokens; their cost is reported as unknown, never as $0.
"""

DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    # shortcut: Haiku 5.5 doubles past 100K-token prompts; we use the base rate.
    "claude-haiku-5-5": (0.10, 0.50),
}


def cost_usd(
    prices: dict[str, tuple[float, float]], model: str | None, input_tokens: int, output_tokens: int
) -> float | None:
    """Cost of the tokens, or None when the model has no price."""
    if model is None or model not in prices:
        return None
    price_in, price_out = prices[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000
