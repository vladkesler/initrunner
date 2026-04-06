"""Tests for tool event observability: error detection, ObservableToolset, and display."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from initrunner.agent.tool_events import (
    ObservableToolset,
    ToolEvent,
    _is_error_result,
    _tool_event_callback,
    reset_tool_event_callback,
    set_tool_event_callback,
    wrap_observable,
)

# ---------------------------------------------------------------------------
# _is_error_result
# ---------------------------------------------------------------------------


class TestIsErrorResult:
    def test_error_colon(self):
        assert _is_error_result("Error: something broke") == "Error: something broke"

    def test_error_fetching_url(self):
        result = _is_error_result("Error fetching URL: connection refused")
        assert result == "Error fetching URL: connection refused"

    def test_error_reading_file(self):
        result = _is_error_result("Error reading file: /tmp/no-such-file")
        assert result == "Error reading file: /tmp/no-such-file"

    def test_http_error(self):
        result = _is_error_result("HTTP error: 503 Service Unavailable")
        assert result == "HTTP error: 503 Service Unavailable"

    def test_permission_denied(self):
        result = _is_error_result("Permission denied: run_shell -- blocked by policy")
        assert result is not None
        assert "Permission denied" in result

    def test_ssrf_blocked(self):
        result = _is_error_result("SSRF blocked: invalid URL")
        assert result is not None

    def test_exit_code(self):
        result = _is_error_result("Exit code: 42")
        assert result == "Exit code: 42"

    def test_execution_timed_out(self):
        result = _is_error_result("Execution timed out after 30s")
        assert result == "Execution timed out after 30s"

    def test_normal_result(self):
        assert _is_error_result("The search returned 5 results.") is None

    def test_empty_string(self):
        assert _is_error_result("") is None

    def test_non_string_int(self):
        assert _is_error_result(42) is None

    def test_non_string_none(self):
        assert _is_error_result(None) is None

    def test_non_string_list(self):
        assert _is_error_result(["Error: nope"]) is None

    def test_truncates_long_error(self):
        long_error = "Error: " + "x" * 200
        result = _is_error_result(long_error)
        assert result is not None
        assert len(result) == 120

    def test_multiline_takes_first_line(self):
        result = _is_error_result("Error: line one\nline two\nline three")
        assert result == "Error: line one"

    def test_case_sensitive(self):
        """Error detection is case-sensitive -- 'error:' (lowercase) is not matched."""
        assert _is_error_result("error: lowercase") is None


# ---------------------------------------------------------------------------
# ObservableToolset
# ---------------------------------------------------------------------------


def _make_inner(return_value: str = "success result") -> AsyncMock:
    inner = AsyncMock()
    inner.id = "test-inner"
    inner.get_tools = AsyncMock(return_value={"tool_a": object()})
    inner.call_tool = AsyncMock(return_value=return_value)
    inner.__aenter__ = AsyncMock(return_value=inner)
    inner.__aexit__ = AsyncMock(return_value=None)
    return inner


class TestObservableToolset:
    @pytest.mark.anyio
    async def test_no_callback_fast_path(self):
        """When no callback is set, call_tool delegates directly."""
        inner = _make_inner()
        ts = ObservableToolset(inner)
        result = await ts.call_tool("tool_a", {}, None, None)  # type: ignore[arg-type]
        assert result == "success result"
        inner.call_tool.assert_called_once()

    @pytest.mark.anyio
    async def test_callback_receives_ok_event(self):
        events: list[ToolEvent] = []
        token = set_tool_event_callback(events.append)
        try:
            inner = _make_inner()
            ts = ObservableToolset(inner)
            await ts.call_tool("tool_a", {}, None, None)  # type: ignore[arg-type]
        finally:
            reset_tool_event_callback(token)

        assert len(events) == 2
        # Start event
        assert events[0].tool_name == "tool_a"
        assert events[0].status == "running"
        assert events[0].phase == "start"
        assert events[0].duration_ms == 0
        # Complete event
        assert events[1].tool_name == "tool_a"
        assert events[1].status == "ok"
        assert events[1].phase == "complete"
        assert events[1].error_summary is None
        assert events[1].duration_ms >= 0

    @pytest.mark.anyio
    async def test_callback_receives_error_event(self):
        events: list[ToolEvent] = []
        token = set_tool_event_callback(events.append)
        try:
            inner = _make_inner(return_value="Error: connection refused")
            ts = ObservableToolset(inner)
            await ts.call_tool("tool_a", {}, None, None)  # type: ignore[arg-type]
        finally:
            reset_tool_event_callback(token)

        assert len(events) == 2
        assert events[0].status == "running"
        assert events[0].phase == "start"
        assert events[1].status == "error"
        assert events[1].phase == "complete"
        assert events[1].error_summary == "Error: connection refused"

    @pytest.mark.anyio
    async def test_callback_exception_does_not_propagate(self):
        def bad_callback(event: ToolEvent) -> None:
            raise RuntimeError("callback crashed")

        token = set_tool_event_callback(bad_callback)
        try:
            inner = _make_inner()
            ts = ObservableToolset(inner)
            result = await ts.call_tool("tool_a", {}, None, None)  # type: ignore[arg-type]
            assert result == "success result"
        finally:
            reset_tool_event_callback(token)

    @pytest.mark.anyio
    async def test_delegates_id(self):
        inner = _make_inner()
        ts = ObservableToolset(inner)
        assert ts.id == "test-inner"

    @pytest.mark.anyio
    async def test_delegates_get_tools(self):
        inner = _make_inner()
        ts = ObservableToolset(inner)
        tools = await ts.get_tools(None)  # type: ignore[arg-type]
        assert "tool_a" in tools

    @pytest.mark.anyio
    async def test_context_manager(self):
        inner = _make_inner()
        ts = ObservableToolset(inner)
        async with ts as entered:
            assert entered is ts
        inner.__aenter__.assert_called_once()
        inner.__aexit__.assert_called_once()

    @pytest.mark.anyio
    async def test_result_passes_through(self):
        """The tool result is returned unchanged regardless of error detection."""
        error_msg = "Error: search timed out after 15s"
        inner = _make_inner(return_value=error_msg)
        events: list[ToolEvent] = []
        token = set_tool_event_callback(events.append)
        try:
            ts = ObservableToolset(inner)
            result = await ts.call_tool("search_web", {}, None, None)  # type: ignore[arg-type]
            assert result == error_msg
        finally:
            reset_tool_event_callback(token)


# ---------------------------------------------------------------------------
# wrap_observable (idempotent helper)
# ---------------------------------------------------------------------------


class TestWrapObservable:
    def test_wraps_non_observable(self):
        inner = _make_inner()
        wrapped = wrap_observable(inner)
        assert isinstance(wrapped, ObservableToolset)
        assert wrapped._inner is inner

    def test_idempotent(self):
        inner = _make_inner()
        first = wrap_observable(inner)
        second = wrap_observable(first)
        assert second is first


# ---------------------------------------------------------------------------
# ContextVar plumbing
# ---------------------------------------------------------------------------


class TestContextVarPlumbing:
    def test_set_and_reset(self):
        """set/reset round-trip restores the previous value."""
        # Reset to clean state in case of test pollution from prior tests
        cleanup_token = _tool_event_callback.set(None)
        try:
            assert _tool_event_callback.get() is None
            token = set_tool_event_callback(lambda e: None)
            assert _tool_event_callback.get() is not None
            reset_tool_event_callback(token)
            assert _tool_event_callback.get() is None
        finally:
            _tool_event_callback.reset(cleanup_token)


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------


class TestFormatToolEvent:
    def test_ok_event(self):
        from initrunner.runner.display import _format_tool_event

        event = ToolEvent("search_web", "ok", None, 1523)
        formatted = _format_tool_event(event)
        assert "search_web" in formatted
        assert "ok" in formatted
        assert "1523ms" in formatted

    def test_error_event(self):
        from initrunner.runner.display import _format_tool_event

        event = ToolEvent("search_web", "error", "Error: timed out", 15023)
        formatted = _format_tool_event(event)
        assert "search_web" in formatted
        assert "error" in formatted
        assert "Error: timed out" in formatted
        assert "15023ms" in formatted

    def test_error_event_no_summary(self):
        from initrunner.runner.display import _format_tool_event

        event = ToolEvent("fetch_url", "error", None, 500)
        formatted = _format_tool_event(event)
        assert "fetch_url" in formatted
        assert "error" in formatted
        assert "500ms" in formatted


class TestFormatToolEventPrefixed:
    def test_ok_event_prefixed(self):
        from initrunner.runner.display import _format_tool_event_prefixed

        event = ToolEvent("search_web", "ok", None, 1523)
        formatted = _format_tool_event_prefixed("producer", event)
        assert "[producer]" in formatted
        assert "search_web" in formatted
        assert "ok" in formatted
        assert "1523ms" in formatted

    def test_error_event_prefixed(self):
        from initrunner.runner.display import _format_tool_event_prefixed

        event = ToolEvent("search_web", "error", "Error: timed out", 15023)
        formatted = _format_tool_event_prefixed("consumer", event)
        assert "[consumer]" in formatted
        assert "search_web" in formatted
        assert "error" in formatted
        assert "Error: timed out" in formatted

    def test_start_phase_prefixed(self):
        from initrunner.runner.display import _format_tool_event_prefixed

        event = ToolEvent("fetch_url", "running", None, 0, phase="start")
        formatted = _format_tool_event_prefixed("agent-1", event)
        assert "[agent-1]" in formatted
        assert "fetch_url" in formatted
        assert "running..." in formatted

    def test_printer_factory(self):
        from initrunner.runner.display import _make_prefixed_tool_event_printer

        printer = _make_prefixed_tool_event_printer()
        assert callable(printer)
