"""Cost estimation rate card for OpenAI models.

Per-token rates as of 2026-04. Unknown model names return None and a
warning is logged at the call site.
"""

from __future__ import annotations

from decimal import Decimal

# (input_per_token_usd, output_per_token_usd)
# Source: OpenAI's published per-1M-token rates as of 2026-04.
OPENAI_RATES_2026_04: dict[str, tuple[Decimal, Decimal]] = {
    "gpt-4o-mini": (Decimal("0.00000015"), Decimal("0.00000060")),
    "gpt-4o": (Decimal("0.0000025"), Decimal("0.0000100")),
}

RATE_CARD_VERSION = "openai-2026-04"


def estimate_cost(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal | None:
    """Estimated cost in USD. None when the model isn't in the rate card."""
    rates = OPENAI_RATES_2026_04.get(model_name)
    if rates is None:
        return None
    in_rate, out_rate = rates
    return (in_rate * prompt_tokens + out_rate * completion_tokens).quantize(Decimal("0.000001"))
