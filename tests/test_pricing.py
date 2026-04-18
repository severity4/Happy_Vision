"""tests/test_pricing.py"""

from modules.pricing import (
    DEFAULT_PRICING,
    PRICING,
    USD_TO_TWD_APPROX,
    calc_cost_usd,
    format_cost,
)


def test_pricing_table_has_known_models():
    assert "gemini-2.5-flash-lite" in PRICING
    assert "gemini-2.5-flash" in PRICING
    # Legacy entries preserved so historical rows still compute
    assert "gemini-2.0-flash-lite" in PRICING
    assert "gemini-2.0-flash" in PRICING


def test_calc_cost_basic():
    # flash-lite: input $0.10/M, output $0.40/M
    # 1M input + 1M output = $0.10 + $0.40 = $0.50
    cost = calc_cost_usd("gemini-2.5-flash-lite", 1_000_000, 1_000_000)
    assert cost == 0.50


def test_calc_cost_single_photo_typical():
    # Typical photo: ~4000 input + ~400 output
    cost = calc_cost_usd("gemini-2.5-flash-lite", 4000, 400)
    # 4000*0.10/1M + 400*0.40/1M = 0.0004 + 0.00016 = 0.00056
    assert abs(cost - 0.00056) < 1e-9


def test_calc_cost_zero_tokens():
    assert calc_cost_usd("gemini-2.5-flash-lite", 0, 0) == 0.0


def test_calc_cost_negative_tokens_clamped():
    # Should never produce negative cost from bad input
    assert calc_cost_usd("gemini-2.5-flash-lite", -5, -10) == 0.0


def test_calc_cost_unknown_model_uses_default():
    # Unknown model falls back to DEFAULT_PRICING (flash-lite, cheapest)
    cost_unknown = calc_cost_usd("gemini-99-experimental", 1_000_000, 1_000_000)
    cost_default = calc_cost_usd("gemini-2.5-flash-lite", 1_000_000, 1_000_000)
    assert cost_unknown == cost_default


def test_calc_cost_flash_more_expensive_than_lite():
    args = (10_000, 1_000)
    lite = calc_cost_usd("gemini-2.5-flash-lite", *args)
    flash = calc_cost_usd("gemini-2.5-flash", *args)
    assert flash > lite


def test_calc_cost_none_tokens_treated_as_zero():
    # usage dict might have None if API didn't return counts
    assert calc_cost_usd("gemini-2.5-flash-lite", None, None) == 0.0


def test_format_cost_small_four_decimals():
    assert format_cost(0.0056) == "$0.0056"


def test_format_cost_large_two_decimals():
    assert format_cost(12.345) == "$12.35"


def test_default_pricing_is_cheapest_model():
    # Safety: default should be flash-lite (cheapest) to avoid over-reporting
    assert DEFAULT_PRICING == PRICING["gemini-2.5-flash-lite"]


def test_twd_conversion_rate_sane():
    # Rough sanity — not validating exchange rate, just that constant exists
    assert 25 < USD_TO_TWD_APPROX < 40
