"""Tests for actionable hint lines on error messages in runner modules."""

from io import StringIO
from unittest.mock import patch

from rich.console import Console

from initrunner.agent.executor import TokenBudgetStatus


class TestBudgetHints:
    """Budget exhaustion messages should include actionable hints."""

    def test_session_budget_exhausted_hint(self):
        from initrunner.runner.display import _display_budget_warning

        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)

        status = TokenBudgetStatus(consumed=10_000, budget=10_000, exceeded=True, warning=True)
        with patch("initrunner.runner.display.console", console):
            _display_budget_warning(status, consumed=10_000, budget=10_000)

        output = buf.getvalue()
        assert "Hint" in output
        assert "session_token_budget" in output

    def test_session_budget_warning_no_hint(self):
        """Warning (not exceeded) should NOT show a hint."""
        from initrunner.runner.display import _display_budget_warning

        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)

        status = TokenBudgetStatus(consumed=8_500, budget=10_000, exceeded=False, warning=True)
        with patch("initrunner.runner.display.console", console):
            _display_budget_warning(status, consumed=8_500, budget=10_000)

        output = buf.getvalue()
        assert "Warning" in output
        assert "Hint" not in output
