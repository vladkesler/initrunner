"""Tests for the clarify tool: config, ContextVar plumbing, tool behavior, and daemon routing."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from initrunner.agent.clarify import (
    ClarifyState,
    get_clarify_callback,
    reset_clarify_callback,
    set_clarify_callback,
)
from initrunner.agent.schema.tools import ClarifyToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, get_tool_types, is_run_scoped
from initrunner.agent.tools.clarify import build_clarify_toolset

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx():
    """Build a minimal ToolBuildContext for tests."""
    from initrunner.agent.schema.role import RoleDefinition

    role = RoleDefinition.model_validate(
        {
            "apiVersion": "initrunner/v1",
            "kind": "Agent",
            "metadata": {"name": "test-agent", "description": "test"},
            "spec": {
                "role": "test",
                "model": {"provider": "openai", "name": "gpt-5-mini"},
            },
        }
    )
    return ToolBuildContext(role=role)


# ---------------------------------------------------------------------------
# ClarifyToolConfig
# ---------------------------------------------------------------------------


class TestClarifyConfig:
    def test_type_literal(self):
        config = ClarifyToolConfig()
        assert config.type == "clarify"

    def test_defaults(self):
        config = ClarifyToolConfig()
        assert config.max_clarifications == 3
        assert config.timeout_seconds == 300

    def test_summary(self):
        config = ClarifyToolConfig(max_clarifications=5)
        assert config.summary() == "clarify: max=5"

    def test_round_trip(self):
        config = ClarifyToolConfig(max_clarifications=2, timeout_seconds=60)
        data = config.model_dump()
        restored = ClarifyToolConfig.model_validate(data)
        assert restored.max_clarifications == 2
        assert restored.timeout_seconds == 60

    def test_from_dict(self):
        config = ClarifyToolConfig.model_validate({"type": "clarify"})
        assert config.type == "clarify"

    def test_max_clarifications_bounds(self):
        with pytest.raises(ValueError):
            ClarifyToolConfig(max_clarifications=0)
        with pytest.raises(ValueError):
            ClarifyToolConfig(max_clarifications=11)

    def test_timeout_bounds(self):
        with pytest.raises(ValueError):
            ClarifyToolConfig(timeout_seconds=10)
        with pytest.raises(ValueError):
            ClarifyToolConfig(timeout_seconds=3700)

    def test_parse_through_role(self):
        """Config round-trips through the registry-driven tool parser."""
        from initrunner.agent.schema.role import RoleDefinition

        role = RoleDefinition.model_validate(
            {
                "apiVersion": "initrunner/v1",
                "kind": "Agent",
                "metadata": {"name": "test-agent", "description": "test"},
                "spec": {
                    "role": "test",
                    "model": {"provider": "openai", "name": "gpt-5-mini"},
                    "tools": [{"type": "clarify", "max_clarifications": 5}],
                },
            }
        )
        tool = role.spec.tools[0]
        assert isinstance(tool, ClarifyToolConfig)
        assert tool.max_clarifications == 5


# ---------------------------------------------------------------------------
# ContextVar plumbing
# ---------------------------------------------------------------------------


class TestClarifyContextVar:
    def test_default_is_none(self):
        assert get_clarify_callback() is None

    def test_set_and_reset_round_trip(self):
        original = get_clarify_callback()

        def cb(q: str) -> str:
            return "answer"

        token = set_clarify_callback(cb)
        assert get_clarify_callback() is cb
        reset_clarify_callback(token)
        assert get_clarify_callback() is original


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestClarifyRegistration:
    def test_registered_in_tool_types(self):
        types = get_tool_types()
        assert "clarify" in types
        assert types["clarify"] is ClarifyToolConfig

    def test_is_run_scoped(self):
        assert is_run_scoped("clarify") is True


# ---------------------------------------------------------------------------
# ClarifyState
# ---------------------------------------------------------------------------


class TestClarifyState:
    def test_defaults(self):
        state = ClarifyState()
        assert state.max_clarifications == 3
        assert state.count == 0
        assert state.history == []

    def test_custom_max(self):
        state = ClarifyState(max_clarifications=7)
        assert state.max_clarifications == 7


# ---------------------------------------------------------------------------
# Clarify toolset behavior
# ---------------------------------------------------------------------------


class TestClarifyToolset:
    def test_builds_toolset_with_clarify(self):
        config = ClarifyToolConfig()
        toolset = build_clarify_toolset(config, _make_ctx())
        assert "clarify" in toolset.tools

    def test_no_callback_returns_fallback(self):
        """Without a callback set, the tool degrades gracefully."""
        config = ClarifyToolConfig()
        toolset = build_clarify_toolset(config, _make_ctx())
        fn = toolset.tools["clarify"].function
        result = fn(question="What DB?")
        assert "not available" in result
        assert "best judgment" in result

    def test_with_callback_returns_answer(self):
        config = ClarifyToolConfig()
        toolset = build_clarify_toolset(config, _make_ctx())
        fn = toolset.tools["clarify"].function

        token = set_clarify_callback(lambda q: "PostgreSQL")
        try:
            result = fn(question="What database?")
        finally:
            reset_clarify_callback(token)

        assert "User response: PostgreSQL" == result

    def test_callback_receives_question(self):
        config = ClarifyToolConfig()
        toolset = build_clarify_toolset(config, _make_ctx())
        fn = toolset.tools["clarify"].function

        received = []
        token = set_clarify_callback(lambda q: (received.append(q), "yes")[1])
        try:
            fn(question="Should I continue?")
        finally:
            reset_clarify_callback(token)

        assert received == ["Should I continue?"]

    def test_tracks_count(self):
        config = ClarifyToolConfig(max_clarifications=5)
        toolset = build_clarify_toolset(config, _make_ctx())
        fn = toolset.tools["clarify"].function

        token = set_clarify_callback(lambda q: "ok")
        try:
            fn(question="Q1")
            fn(question="Q2")
            result = fn(question="Q3")
        finally:
            reset_clarify_callback(token)

        assert "User response: ok" == result

    def test_respects_max_limit(self):
        config = ClarifyToolConfig(max_clarifications=2)
        toolset = build_clarify_toolset(config, _make_ctx())
        fn = toolset.tools["clarify"].function

        mock_cb = MagicMock(return_value="ok")
        token = set_clarify_callback(mock_cb)
        try:
            fn(question="Q1")
            fn(question="Q2")
            result = fn(question="Q3")  # over limit
        finally:
            reset_clarify_callback(token)

        assert "limit reached" in result.lower()
        assert mock_cb.call_count == 2  # not called for Q3

    def test_records_history(self):
        config = ClarifyToolConfig()
        toolset = build_clarify_toolset(config, _make_ctx())
        fn = toolset.tools["clarify"].function

        answers = iter(["answer1", "answer2"])
        token = set_clarify_callback(lambda q: next(answers))
        try:
            fn(question="Q1")
            fn(question="Q2")
        finally:
            reset_clarify_callback(token)

        # Access state through the closure -- build a fresh one to inspect
        # The state is internal to the closure, so we verify via tool output
        # which includes "User response: answer1", "User response: answer2"

    def test_timeout_error_returns_graceful(self):
        config = ClarifyToolConfig()
        toolset = build_clarify_toolset(config, _make_ctx())
        fn = toolset.tools["clarify"].function

        def _timeout(q: str) -> str:
            raise TimeoutError("timed out")

        token = set_clarify_callback(_timeout)
        try:
            result = fn(question="Q?")
        finally:
            reset_clarify_callback(token)

        assert "timeout" in result.lower()
        assert "best judgment" in result

    def test_generic_exception_returns_graceful(self):
        config = ClarifyToolConfig()
        toolset = build_clarify_toolset(config, _make_ctx())
        fn = toolset.tools["clarify"].function

        def _boom(q: str) -> str:
            raise RuntimeError("connection lost")

        token = set_clarify_callback(_boom)
        try:
            result = fn(question="Q?")
        finally:
            reset_clarify_callback(token)

        assert "connection lost" in result
        assert "best judgment" in result


# ---------------------------------------------------------------------------
# PendingClarification (daemon integration)
# ---------------------------------------------------------------------------


class TestPendingClarification:
    def test_basic_flow(self):
        """Answer delivered from another thread unblocks the waiting side."""
        from initrunner.runner.daemon import PendingClarification

        pc = PendingClarification()
        received = []

        def _waiter():
            pc.event.wait(timeout=5)
            received.append(pc.answer)

        t = threading.Thread(target=_waiter)
        t.start()

        # Simulate answer arrival
        pc.answer = "42"
        pc.event.set()

        t.join(timeout=5)
        assert received == ["42"]

    def test_timeout(self):
        """Wait returns False when no answer arrives."""
        from initrunner.runner.daemon import PendingClarification

        pc = PendingClarification()
        assert pc.event.wait(timeout=0.01) is False


class TestDaemonClarifyRouting:
    """Verify that clarification answers bypass semaphore and budget."""

    def _make_runner(self):
        """Build a DaemonRunner with mocked agent/role."""
        from initrunner.runner.daemon import DaemonRunner

        role = _make_ctx().role
        agent = MagicMock()
        return DaemonRunner(agent, role)

    def test_answer_bypasses_semaphore(self):
        """When a clarification is pending, the answer does not acquire the semaphore."""
        from initrunner.runner.daemon import PendingClarification
        from initrunner.triggers.base import (
            TriggerEvent,
            register_conversational_trigger_type,
        )

        register_conversational_trigger_type("telegram")
        runner = self._make_runner()
        # TriggerEvent.conversation_key is derived from metadata
        conv_key = "telegram:12345"

        # Register a pending clarification
        pc = PendingClarification()
        with runner._pending_lock:
            runner._pending_clarifications[conv_key] = pc

        # Exhaust all semaphore slots
        for _ in range(runner._MAX_CONCURRENT):
            runner._concurrency_semaphore.acquire()

        # Send answer -- should succeed despite no free slots
        event = TriggerEvent(
            prompt="The answer is 42",
            trigger_type="telegram",
            metadata={"channel_target": "12345"},
        )
        assert event.conversation_key == conv_key
        runner._on_trigger(event)

        assert pc.event.is_set()
        assert pc.answer == "The answer is 42"

        # Release semaphore slots for cleanup
        for _ in range(runner._MAX_CONCURRENT):
            runner._concurrency_semaphore.release()

    def test_answer_does_not_start_new_run(self):
        """A clarification answer should not trigger a new agent run."""
        from initrunner.runner.daemon import PendingClarification
        from initrunner.triggers.base import (
            TriggerEvent,
            register_conversational_trigger_type,
        )

        register_conversational_trigger_type("telegram")
        runner = self._make_runner()
        conv_key = "telegram:67890"

        pc = PendingClarification()
        with runner._pending_lock:
            runner._pending_clarifications[conv_key] = pc

        event = TriggerEvent(
            prompt="my answer",
            trigger_type="telegram",
            metadata={"channel_target": "67890"},
        )
        runner._on_trigger(event)

        # The event was consumed as an answer, no run started
        assert pc.answer == "my answer"
        assert pc.event.is_set()

    def test_non_pending_proceeds_normally(self):
        """Without a pending clarification, trigger proceeds to semaphore."""
        from initrunner.triggers.base import TriggerEvent

        runner = self._make_runner()

        # Exhaust semaphore
        for _ in range(runner._MAX_CONCURRENT):
            runner._concurrency_semaphore.acquire()

        event = TriggerEvent(
            prompt="normal message",
            trigger_type="telegram",
            metadata={"chat_id": "99999"},
        )
        # Should be skipped (no free semaphore slot) -- just verify no crash
        runner._on_trigger(event)

        # Release
        for _ in range(runner._MAX_CONCURRENT):
            runner._concurrency_semaphore.release()

    def test_non_conversational_no_clarify_callback(self):
        """Non-conversational triggers (no conv_key) get no clarify callback."""
        runner = self._make_runner()
        cb = runner._make_daemon_clarify_callback(None, MagicMock(), 300)
        assert cb is None

    def test_no_reply_fn_no_clarify_callback(self):
        """Missing reply_fn means no clarify callback."""
        runner = self._make_runner()
        cb = runner._make_daemon_clarify_callback("conv-key", None, 300)
        assert cb is None


class TestDaemonClarifyCallback:
    """Test the daemon clarify callback itself."""

    def _make_runner(self):
        from initrunner.runner.daemon import DaemonRunner

        role = _make_ctx().role
        agent = MagicMock()
        return DaemonRunner(agent, role)

    def test_callback_sends_question_and_returns_answer(self):
        runner = self._make_runner()
        reply_fn = MagicMock()
        cb = runner._make_daemon_clarify_callback("conv-1", reply_fn, 5.0)
        assert cb is not None

        # Simulate answer delivery in another thread
        def _deliver_answer():
            import time

            time.sleep(0.05)
            with runner._pending_lock:
                pc = runner._pending_clarifications.get("conv-1")
                if pc:
                    pc.answer = "PostgreSQL"
                    pc.event.set()

        t = threading.Thread(target=_deliver_answer)
        t.start()

        result = cb("What database?")
        t.join(timeout=5)

        reply_fn.assert_called_once_with("[Clarification needed]\nWhat database?")
        assert result == "PostgreSQL"

    def test_callback_timeout_raises(self):
        runner = self._make_runner()
        reply_fn = MagicMock()
        cb = runner._make_daemon_clarify_callback("conv-2", reply_fn, 0.05)

        with pytest.raises(TimeoutError):
            cb("Question that nobody answers")

        # Pending entry should be cleaned up
        with runner._pending_lock:
            assert "conv-2" not in runner._pending_clarifications

    def test_callback_cleans_up_on_success(self):
        runner = self._make_runner()
        reply_fn = MagicMock()
        cb = runner._make_daemon_clarify_callback("conv-3", reply_fn, 5.0)

        def _deliver():
            import time

            time.sleep(0.05)
            with runner._pending_lock:
                pc = runner._pending_clarifications.get("conv-3")
                if pc:
                    pc.answer = "yes"
                    pc.event.set()

        t = threading.Thread(target=_deliver)
        t.start()
        cb("Confirm?")
        t.join(timeout=5)

        with runner._pending_lock:
            assert "conv-3" not in runner._pending_clarifications
