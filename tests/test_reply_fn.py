"""Tests for reply_fn integration with DaemonRunner and chunk_text helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from initrunner.agent.executor import RunResult
from initrunner.triggers.base import TriggerEvent, _chunk_text


class TestChunkText:
    def test_short_text_returns_single_chunk(self):
        result = _chunk_text("hello", 100)
        assert result == ["hello"]

    def test_empty_string_returns_single_chunk(self):
        result = _chunk_text("", 100)
        assert result == [""]

    def test_exact_limit_returns_single_chunk(self):
        text = "a" * 100
        result = _chunk_text(text, 100)
        assert result == [text]

    def test_splits_at_newline(self):
        text = "line1\nline2\nline3"
        result = _chunk_text(text, 12)
        assert result == ["line1\nline2", "line3"]

    def test_hard_cuts_when_no_newline(self):
        text = "a" * 200
        result = _chunk_text(text, 100)
        assert len(result) == 2
        assert result[0] == "a" * 100
        assert result[1] == "a" * 100

    def test_multiple_chunks(self):
        text = "a" * 300
        result = _chunk_text(text, 100)
        assert len(result) == 3

    def test_telegram_limit(self):
        text = "x" * 8000
        result = _chunk_text(text, 4096)
        assert len(result) == 2
        assert all(len(c) <= 4096 for c in result)

    def test_discord_limit(self):
        text = "x" * 5000
        result = _chunk_text(text, 2000)
        assert len(result) == 3
        assert all(len(c) <= 2000 for c in result)

    def test_strips_leading_newlines_between_chunks(self):
        text = "abc\n\n\ndef"
        result = _chunk_text(text, 4)
        # "abc\n" split at newline → "abc", then "\n\ndef" → stripped → "def"
        assert result[0] == "abc"
        assert result[1] == "def"


class TestReplyFnInDaemon:
    """Test that DaemonRunner._on_trigger_inner calls reply_fn correctly."""

    @patch("initrunner.runner.daemon.execute_run")
    def test_reply_fn_called_with_output(self, mock_execute):
        from initrunner.runner.daemon import DaemonRunner

        mock_result = MagicMock(spec=RunResult)
        mock_result.output = "Hello from agent"
        mock_result.total_tokens = 100
        mock_result.success = True
        mock_execute.return_value = (mock_result, None)

        reply_fn = MagicMock()
        event = TriggerEvent(
            trigger_type="telegram",
            prompt="Hi",
            reply_fn=reply_fn,
        )

        agent = MagicMock()
        role = MagicMock()
        role.spec.guardrails.daemon_token_budget = None
        role.spec.guardrails.daemon_daily_token_budget = None
        role.spec.triggers = []
        role.spec.autonomy = None
        role.spec.memory = None

        runner = DaemonRunner(agent, role)
        runner._autonomous_trigger_types = set()
        runner._on_trigger_inner(event)

        reply_fn.assert_called_once_with("Hello from agent")

    @patch("initrunner.runner.daemon.execute_run")
    def test_reply_fn_none_is_safe(self, mock_execute):
        """Events without reply_fn (e.g., cron) don't crash."""
        from initrunner.runner.daemon import DaemonRunner

        mock_result = MagicMock(spec=RunResult)
        mock_result.output = "Agent output"
        mock_result.total_tokens = 100
        mock_result.success = True
        mock_execute.return_value = (mock_result, None)

        event = TriggerEvent(
            trigger_type="cron",
            prompt="Do something",
            # reply_fn is None by default
        )

        agent = MagicMock()
        role = MagicMock()
        role.spec.guardrails.daemon_token_budget = None
        role.spec.guardrails.daemon_daily_token_budget = None
        role.spec.triggers = []
        role.spec.autonomy = None
        role.spec.memory = None

        runner = DaemonRunner(agent, role)
        runner._autonomous_trigger_types = set()
        runner._on_trigger_inner(event)
        # Should not raise

    @patch("initrunner.runner.daemon.execute_run")
    def test_reply_fn_exception_does_not_crash(self, mock_execute):
        """reply_fn failures are logged but don't crash the daemon."""
        from initrunner.runner.daemon import DaemonRunner

        mock_result = MagicMock(spec=RunResult)
        mock_result.output = "Agent output"
        mock_result.total_tokens = 100
        mock_result.success = True
        mock_execute.return_value = (mock_result, None)

        reply_fn = MagicMock(side_effect=RuntimeError("network error"))
        event = TriggerEvent(
            trigger_type="telegram",
            prompt="Hi",
            reply_fn=reply_fn,
        )

        agent = MagicMock()
        role = MagicMock()
        role.spec.guardrails.daemon_token_budget = None
        role.spec.guardrails.daemon_daily_token_budget = None
        role.spec.triggers = []
        role.spec.autonomy = None
        role.spec.memory = None

        runner = DaemonRunner(agent, role)
        runner._autonomous_trigger_types = set()

        # Should not raise — exception is caught and logged
        runner._on_trigger_inner(event)

        # reply_fn was attempted
        reply_fn.assert_called_once_with("Agent output")

    @patch("initrunner.runner.daemon.execute_run")
    def test_reply_fn_called_in_conversational_mode(self, mock_execute):
        """Conversational triggers (telegram) skip autonomous and use execute_run."""
        from initrunner.agent.schema.autonomy import AutonomyConfig
        from initrunner.runner.daemon import DaemonRunner

        mock_result = MagicMock(spec=RunResult)
        mock_result.output = "Here is the detailed answer."
        mock_result.total_tokens = 200
        mock_result.success = True
        mock_execute.return_value = (mock_result, None)

        reply_fn = MagicMock()
        event = TriggerEvent(
            trigger_type="telegram",
            prompt="Hi from Telegram",
            reply_fn=reply_fn,
            metadata={"chat_id": "12345"},
        )

        agent = MagicMock()
        role = MagicMock()
        role.spec.guardrails.daemon_token_budget = None
        role.spec.guardrails.daemon_daily_token_budget = None
        role.spec.triggers = []
        role.spec.autonomy = AutonomyConfig()
        role.spec.memory = None

        runner = DaemonRunner(agent, role)
        runner._autonomous_trigger_types = {"telegram"}
        runner._on_trigger_inner(event)

        reply_fn.assert_called_once_with("Here is the detailed answer.")

    @patch("initrunner.runner.daemon.run_autonomous")
    def test_non_conversational_autonomous_joins_all_outputs(self, mock_autonomous):
        """Non-conversational autonomous triggers (scheduled) join all outputs."""
        from initrunner.agent.schema.autonomy import AutonomyConfig
        from initrunner.runner.daemon import DaemonRunner

        iter1 = MagicMock()
        iter1.output = "Step 1 done."
        iter2 = MagicMock()
        iter2.output = "Step 2 done."

        mock_auto_result = MagicMock()
        mock_auto_result.iterations = [iter1, iter2]
        mock_auto_result.final_output = "Step 2 done."
        mock_auto_result.final_messages = None
        mock_auto_result.total_tokens = 200
        mock_autonomous.return_value = mock_auto_result

        reply_fn = MagicMock()
        event = TriggerEvent(
            trigger_type="scheduled",
            prompt="Run scheduled task",
            reply_fn=reply_fn,
            # No chat_id/channel_id → conversation_key is None
        )

        agent = MagicMock()
        role = MagicMock()
        role.spec.guardrails.daemon_token_budget = None
        role.spec.guardrails.daemon_daily_token_budget = None
        role.spec.triggers = []
        role.spec.autonomy = AutonomyConfig()
        role.spec.memory = None

        runner = DaemonRunner(agent, role)
        runner._autonomous_trigger_types = set()  # "scheduled" always uses autonomous
        runner._on_trigger_inner(event)

        reply_fn.assert_called_once_with("Step 1 done.\n\nStep 2 done.")

    @patch("initrunner.runner.daemon.execute_run")
    def test_reply_fn_not_called_when_output_empty(self, mock_execute):
        """Don't call reply_fn when output is empty."""
        from initrunner.agent.schema.autonomy import AutonomyConfig
        from initrunner.runner.daemon import DaemonRunner

        mock_result = MagicMock(spec=RunResult)
        mock_result.output = ""
        mock_result.total_tokens = 50
        mock_result.success = True
        mock_execute.return_value = (mock_result, None)

        reply_fn = MagicMock()
        event = TriggerEvent(
            trigger_type="telegram",
            prompt="Hi",
            reply_fn=reply_fn,
            metadata={"chat_id": "999"},
        )

        agent = MagicMock()
        role = MagicMock()
        role.spec.guardrails.daemon_token_budget = None
        role.spec.guardrails.daemon_daily_token_budget = None
        role.spec.triggers = []
        role.spec.autonomy = AutonomyConfig()
        role.spec.memory = None

        runner = DaemonRunner(agent, role)
        runner._autonomous_trigger_types = {"telegram"}
        runner._on_trigger_inner(event)

        reply_fn.assert_not_called()

    @patch("initrunner.runner.daemon.run_autonomous")
    def test_non_conversational_autonomous_still_uses_autonomous(self, mock_autonomous):
        """Non-conversational triggers (e.g. cron) still route through run_autonomous."""
        from initrunner.agent.schema.autonomy import AutonomyConfig
        from initrunner.runner.daemon import DaemonRunner

        mock_auto_result = MagicMock()
        mock_auto_result.final_output = "Cron result"
        mock_auto_result.final_messages = None
        mock_auto_result.iterations = [MagicMock(output="Cron result")]
        mock_auto_result.total_tokens = 150
        mock_autonomous.return_value = mock_auto_result

        event = TriggerEvent(
            trigger_type="cron",
            prompt="Run cron job",
        )

        agent = MagicMock()
        role = MagicMock()
        role.spec.guardrails.daemon_token_budget = None
        role.spec.guardrails.daemon_daily_token_budget = None
        role.spec.triggers = []
        role.spec.autonomy = AutonomyConfig()
        role.spec.memory = None

        runner = DaemonRunner(agent, role)
        runner._autonomous_trigger_types = {"cron"}
        runner._on_trigger_inner(event)

        mock_autonomous.assert_called_once()
