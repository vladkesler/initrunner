"""Cost estimation using genai-prices and PydanticAI's RequestUsage."""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

_PROVIDER_MAP: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "groq": "groq",
    "mistral": "mistralai",
    "xai": "x-ai",
    "deepseek": "deepseek",
    "openrouter": "openrouter",
    "together": "togetherai",
    "fireworks": "fireworks-ai",
}


def estimate_cost(
    tokens_in: int,
    tokens_out: int,
    model_name: str,
    provider: str,
) -> dict[str, float] | None:
    """Return estimated USD cost, or ``None`` if pricing is unavailable.

    Uses PydanticAI's ``RequestUsage`` (which satisfies the
    ``genai_prices.AbstractUsage`` protocol) and ``genai_prices.calc_price``.
    """
    mapped = _PROVIDER_MAP.get(provider)
    if mapped is None:
        return None

    try:
        from genai_prices import calc_price  # type: ignore[import-not-found]
        from pydantic_ai.usage import RequestUsage

        usage = RequestUsage(input_tokens=tokens_in, output_tokens=tokens_out)
        result = calc_price(usage, model_name, provider_id=mapped)
        return {
            "input_cost_usd": float(result.input_price),
            "output_cost_usd": float(result.output_price),
            "total_cost_usd": float(result.total_price),
        }
    except Exception:
        _logger.debug("Cost estimation failed for %s/%s", provider, model_name, exc_info=True)
        return None
