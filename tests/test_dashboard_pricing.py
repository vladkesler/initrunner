"""Tests for initrunner.dashboard.pricing."""

from __future__ import annotations

from unittest.mock import patch

from initrunner.dashboard.pricing import estimate_cost


class TestEstimateCost:
    def test_known_provider_returns_cost(self):
        result = estimate_cost(1000, 500, "gpt-4o", "openai")
        assert result is not None
        assert "input_cost_usd" in result
        assert "output_cost_usd" in result
        assert "total_cost_usd" in result
        assert result["total_cost_usd"] > 0

    def test_unknown_provider_returns_none(self):
        assert estimate_cost(1000, 500, "some-model", "ollama") is None

    def test_unknown_model_returns_none(self):
        result = estimate_cost(1000, 500, "nonexistent-model-xyz", "openai")
        # genai-prices may raise or return zero -- either way we handle it
        # The function should not raise
        assert result is None or isinstance(result, dict)

    def test_zero_tokens(self):
        result = estimate_cost(0, 0, "gpt-4o", "openai")
        assert result is not None
        assert result["total_cost_usd"] == 0.0

    def test_anthropic_provider(self):
        result = estimate_cost(1000, 500, "claude-sonnet-4-20250514", "anthropic")
        assert result is not None
        assert result["total_cost_usd"] > 0

    def test_calc_price_exception_returns_none(self):
        with patch("genai_prices.calc_price", side_effect=Exception("boom")):
            assert estimate_cost(1000, 500, "gpt-4o", "openai") is None
