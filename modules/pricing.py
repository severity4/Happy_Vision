"""modules/pricing.py — Gemini API pricing table + per-call cost calculator.

Prices are USD per 1,000,000 tokens. Google revises the rate card occasionally;
update the table when it changes and bump the constant below.
Last verified: 2026-04-18 via https://ai.google.dev/pricing
"""

PRICING_VERIFIED = "2026-04-18"

# USD per 1,000,000 tokens (input, output)
PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash":      {"input": 0.30, "output": 2.50},
    # Legacy/backcompat names — keep so older saved rows still compute
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash":      {"input": 0.10,  "output": 0.40},
}

# Fallback for unknown model names. Prefer the cheaper family to avoid
# over-reporting spend on stale data.
DEFAULT_PRICING = PRICING["gemini-2.5-flash-lite"]

# Rough TWD conversion used only for side-label display. Real billing is USD.
USD_TO_TWD_APPROX = 32.0

# Gemini Batch API is 50% of realtime pricing (confirmed 2026-04-19 via
# https://ai.google.dev/gemini-api/docs/batch-api). Kept as a named constant
# so UI cost estimators and batch_monitor stay aligned.
BATCH_DISCOUNT_MULTIPLIER = 0.5


def calc_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    batch: bool = False,
) -> float:
    """Return cost in USD for one analyze call. Always non-negative.

    `batch=True` applies the Batch API discount — use when computing
    projected cost for a batch submission, or when storing the realised
    cost of a batch-mode result."""
    input_tokens = max(0, int(input_tokens or 0))
    output_tokens = max(0, int(output_tokens or 0))
    p = PRICING.get(model, DEFAULT_PRICING)
    cost = (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000.0
    if batch:
        cost *= BATCH_DISCOUNT_MULTIPLIER
    return cost


def format_cost(cost_usd: float) -> str:
    """Format a small USD cost for display (4 decimals for single photos)."""
    if cost_usd >= 1.0:
        return f"${cost_usd:,.2f}"
    return f"${cost_usd:.4f}"
