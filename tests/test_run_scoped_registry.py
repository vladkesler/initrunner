"""Tests for run_scoped flag in the tool registry."""

from __future__ import annotations

from initrunner.agent.tools._registry import is_run_scoped


class TestRunScoped:
    def test_think_is_run_scoped(self):
        assert is_run_scoped("think") is True

    def test_todo_is_run_scoped(self):
        assert is_run_scoped("todo") is True

    def test_spawn_is_run_scoped(self):
        assert is_run_scoped("spawn") is True

    def test_datetime_is_not_run_scoped(self):
        assert is_run_scoped("datetime") is False

    def test_unknown_is_not_run_scoped(self):
        assert is_run_scoped("nonexistent_tool_type") is False
