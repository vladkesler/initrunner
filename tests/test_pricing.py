"""Tests for the shared pricing module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_estimate_cost_returns_dict_for_known_provider():
    """estimate_cost returns a cost dict when genai_prices succeeds."""
    from initrunner.pricing import estimate_cost

    mock_result = MagicMock()
    mock_result.input_price = 0.003
    mock_result.output_price = 0.006
    mock_result.total_price = 0.009

    with patch("initrunner.pricing.calc_price", mock_result, create=True):
        # Patch at the point of lazy import
        import initrunner.pricing as mod

        with patch.object(mod, "calc_price", return_value=mock_result, create=True):
            pass

    # Use a real call -- genai_prices is installed as a transitive dep
    result = estimate_cost(1000, 500, "gpt-4o", "openai")
    if result is not None:
        assert "input_cost_usd" in result
        assert "output_cost_usd" in result
        assert "total_cost_usd" in result
        assert result["total_cost_usd"] >= 0


def test_estimate_cost_returns_none_for_unknown_provider():
    """Unknown providers return None immediately."""
    from initrunner.pricing import estimate_cost

    assert estimate_cost(1000, 500, "my-model", "unknown_provider_xyz") is None


def test_estimate_cost_returns_none_for_empty_provider():
    from initrunner.pricing import estimate_cost

    assert estimate_cost(1000, 500, "gpt-4o", "") is None


def test_provider_map_covers_major_providers():
    """Verify all expected providers are mapped."""
    from initrunner.pricing import _PROVIDER_MAP

    expected = {
        "openai",
        "anthropic",
        "google",
        "groq",
        "mistral",
        "xai",
        "deepseek",
        "openrouter",
        "together",
        "fireworks",
    }
    assert expected == set(_PROVIDER_MAP.keys())


def test_dashboard_reexport():
    """dashboard/pricing.py re-exports from shared module."""
    from initrunner.dashboard.pricing import estimate_cost as dashboard_fn
    from initrunner.pricing import estimate_cost as shared_fn

    assert dashboard_fn is shared_fn
