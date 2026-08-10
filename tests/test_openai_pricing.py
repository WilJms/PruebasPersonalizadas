from __future__ import annotations

from comprehension_verification.model_gateway.openai_pricing import (
    MODEL_PRICES,
    PRICING_OBSERVED_DATE,
    PRICING_SOURCE_URL,
    TokenPrices,
    estimate_cost_usd,
)


def test_gpt_5_6_standard_short_context_prices_match_current_openai_table() -> None:
    assert PRICING_OBSERVED_DATE == "2026-08-10"
    assert PRICING_SOURCE_URL == "https://developers.openai.com/api/docs/pricing"
    assert dict(MODEL_PRICES) == {
        "gpt-5.6-sol": TokenPrices(5.00, 0.50, 30.00),
        "gpt-5.6-terra": TokenPrices(2.00, 0.20, 12.00),
        "gpt-5.6-luna": TokenPrices(0.20, 0.02, 1.20),
    }


def test_updated_terra_and_luna_prices_are_used_by_cost_estimation() -> None:
    assert estimate_cost_usd(
        model="gpt-5.6-terra",
        input_tokens=100_000,
        cached_input_tokens=0,
        output_tokens=100_000,
    ) == 1.4
    assert estimate_cost_usd(
        model="gpt-5.6-luna",
        input_tokens=100_000,
        cached_input_tokens=0,
        output_tokens=100_000,
    ) == 0.14


def test_cache_write_and_long_context_multipliers_follow_official_policy() -> None:
    assert estimate_cost_usd(
        model="gpt-5.6-terra",
        input_tokens=100_000,
        cache_write_tokens=100_000,
        output_tokens=0,
    ) == 0.25
    assert estimate_cost_usd(
        model="gpt-5.6-luna",
        input_tokens=272_001,
        output_tokens=100_000,
    ) == 0.2888004
