"""Tests for the first-run jobs menu helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from initrunner.cli._first_run import (
    CHAT,
    DASHBOARD,
    NEW,
    STARTER,
    configured_menu_options,
    dispatch_first_run_choice,
    list_menu_starters,
    setup_menu_options,
)


class TestMenuOptions:
    def test_dashboard_last_when_included(self):
        opts = configured_menu_options(include_dashboard=True)
        assert [k for _, k in opts] == [CHAT, STARTER, NEW, DASHBOARD]
        assert opts[0][0] == "Chat"

    def test_dashboard_omitted_when_unavailable(self):
        opts = configured_menu_options(include_dashboard=False)
        assert DASHBOARD not in [k for _, k in opts]
        assert [k for _, k in opts] == [CHAT, STARTER, NEW]

    def test_setup_menu_never_includes_dashboard(self):
        assert DASHBOARD not in [k for _, k in setup_menu_options()]


def _entry(slug: str, kind: str = "Agent", errors=None, warnings=None):
    return SimpleNamespace(
        slug=slug,
        kind=kind,
        description=f"{slug} starter",
        _errors=errors or [],
        _warnings=warnings or [],
    )


class TestListMenuStarters:
    def test_first_hour_order_and_filters(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # not a git repo → skip reviewer
        memory = _entry("memory")
        helpdesk = _entry("helpdesk")
        scout = _entry("scout", errors=["missing extra"])
        reviewer = _entry("reviewer", kind="Team")

        def fake_check(entry):
            return entry._errors, entry._warnings

        with (
            patch(
                "initrunner.services.starters.list_starters",
                return_value=[helpdesk, reviewer, scout, memory],
            ),
            patch("initrunner.services.starters.check_prerequisites", side_effect=fake_check),
        ):
            ready = list_menu_starters()

        assert [e.slug for e in ready] == ["memory", "helpdesk"]

    def test_empty_catalog(self):
        with (
            patch("initrunner.services.starters.list_starters", return_value=[]),
            patch("initrunner.services.starters.check_prerequisites"),
        ):
            assert list_menu_starters() == []


class TestDispatch:
    def test_chat_dispatches_ephemeral(self):
        mock = MagicMock()
        with patch("initrunner.cli._ephemeral.dispatch_ephemeral", mock):
            dispatch_first_run_choice(CHAT)
        mock.assert_called_once_with()

    def test_new_dispatches_builder(self):
        mock = MagicMock()
        with patch("initrunner.cli.new_cmd.new", mock):
            dispatch_first_run_choice(NEW)
        mock.assert_called_once_with()

    def test_dashboard_launches(self):
        mock = MagicMock()
        with patch("initrunner.cli.dashboard_cmd.launch_dashboard", mock):
            dispatch_first_run_choice(DASHBOARD)
        mock.assert_called_once_with()

    def test_starter_empty_does_not_run(self):
        with (
            patch("initrunner.cli._first_run.prompt_starter_submenu", return_value=None),
            patch("initrunner.cli.run_cmd.run") as mock_run,
        ):
            dispatch_first_run_choice(STARTER)
        mock_run.assert_not_called()

    def test_starter_runs_interactive(self):
        mock_run = MagicMock()
        with (
            patch("initrunner.cli._first_run.prompt_starter_submenu", return_value="memory"),
            patch("initrunner.cli.run_cmd.run", mock_run),
        ):
            dispatch_first_run_choice(STARTER)
        kwargs = mock_run.call_args.kwargs
        assert kwargs["interactive"] is True
        assert kwargs["role_file"].name == "memory"
