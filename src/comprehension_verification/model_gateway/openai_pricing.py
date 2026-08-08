"""Conservative, dated pricing policy for the explicit GPT-5.6 routes."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping


@dataclass(frozen=True, slots=True)
class TokenPrices:
    input_per_million: float
    cached_input_per_million: float
    output_per_million: float


# Observed 2026-08-08 on official OpenAI model/pricing surfaces. Luna had also
# been observed on an official surface at a lower 0.20/0.02/1.20 rate during
# bootstrap. The higher observation is deliberately used until credentials and
# project-tier pricing can be checked at the later human gate.
PRICING_OBSERVED_DATE: Final = "2026-08-08"
PRICING_SOURCE_URL: Final = "https://developers.openai.com/api/docs/pricing"
MODEL_PRICES: Final[Mapping[str, TokenPrices]] = MappingProxyType(
    {
        "gpt-5.6-sol": TokenPrices(5.00, 0.50, 30.00),
        "gpt-5.6-luna": TokenPrices(1.00, 0.10, 6.00),
    }
)
LONG_CONTEXT_THRESHOLD: Final = 272_000


def estimate_cost_usd(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Compute a conservative standard-tier cost from provider usage tokens."""

    try:
        prices = MODEL_PRICES[model]
    except KeyError as exc:
        raise ValueError(f"No approved pricing record for model: {model}") from exc
    input_tokens = max(0, input_tokens)
    cached_input_tokens = min(input_tokens, max(0, cached_input_tokens))
    cache_write_tokens = min(input_tokens, max(0, cache_write_tokens))
    ordinary_input = max(0, input_tokens - cached_input_tokens - cache_write_tokens)
    input_multiplier = 2.0 if input_tokens > LONG_CONTEXT_THRESHOLD else 1.0
    output_multiplier = 1.5 if input_tokens > LONG_CONTEXT_THRESHOLD else 1.0
    total = (
        ordinary_input * prices.input_per_million * input_multiplier
        + cached_input_tokens * prices.cached_input_per_million * input_multiplier
        + cache_write_tokens * prices.input_per_million * 1.25 * input_multiplier
        + max(0, output_tokens) * prices.output_per_million * output_multiplier
    ) / 1_000_000
    return round(total, 8)
