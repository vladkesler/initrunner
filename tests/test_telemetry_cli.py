"""The single app_entry() capture site: one event per run, error/exit/version paths."""

from __future__ import annotations

import sys

import pytest

from initrunner.config import get_home_dir


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
    for var in ("DO_NOT_TRACK", "INITRUNNER_TELEMETRY", "CI"):
        monkeypatch.delenv(var, raising=False)
    get_home_dir.cache_clear()
    return tmp_path


@pytest.fixture
def captured_events(monkeypatch):
    """Capture enqueued events and stub the network flush."""
    from initrunner.telemetry import _sender

    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(_sender, "enqueue", lambda event, did, props: events.append((event, props)))
    monkeypatch.setattr(_sender, "flush", lambda: None)
    return events


def _commands(events: list[tuple[str, dict]]) -> list[dict]:
    return [props for (event, props) in events if event == "cli_command"]


def test_success_records_one_command(home, captured_events, monkeypatch):
    from initrunner.cli import main as cli_main

    monkeypatch.setattr(sys, "argv", ["initrunner", "telemetry", "status"])
    with pytest.raises(SystemExit) as exc:
        cli_main.app_entry()

    assert exc.value.code in (0, None)
    commands = _commands(captured_events)
    assert len(commands) == 1
    assert commands[0]["command"] == "telemetry"
    assert commands[0]["status"] == "ok"


def test_error_path_records_status_and_exit_code(home, captured_events, monkeypatch):
    from initrunner.cli import main as cli_main

    # --role and --flow are mutually exclusive: typer.Exit(1) before any work.
    monkeypatch.setattr(sys, "argv", ["initrunner", "doctor", "--role", "x", "--flow", "y"])
    with pytest.raises(SystemExit) as exc:
        cli_main.app_entry()

    assert exc.value.code == 1
    command = _commands(captured_events)[0]
    assert command["command"] == "doctor"
    assert command["status"] == "error"
    assert command["exit_code"] == 1


def test_version_path_recorded_when_callback_bypassed(home, captured_events, monkeypatch):
    from initrunner.cli import main as cli_main

    monkeypatch.setattr(sys, "argv", ["initrunner", "--version"])
    with pytest.raises(SystemExit) as exc:
        cli_main.app_entry()

    assert exc.value.code in (0, None)
    commands = _commands(captured_events)
    assert len(commands) == 1
    assert commands[0]["command"] == "version"


def test_do_not_track_suppresses_all_capture(home, captured_events, monkeypatch):
    from initrunner.cli import main as cli_main

    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setattr(sys, "argv", ["initrunner", "telemetry", "status"])
    with pytest.raises(SystemExit):
        cli_main.app_entry()

    assert captured_events == []


def test_first_run_notice_shown_once_on_non_tty(home, captured_events, monkeypatch, capsys):
    from initrunner.cli import main as cli_main

    monkeypatch.setattr(sys, "argv", ["initrunner", "telemetry", "status"])
    with pytest.raises(SystemExit):
        cli_main.app_entry()
    first_err = capsys.readouterr().err
    assert "anonymous usage data" in first_err.lower()
    assert any(event == "cli_first_run" for (event, _) in captured_events)

    # Second run: notice does not repeat.
    captured_events.clear()
    with pytest.raises(SystemExit):
        cli_main.app_entry()
    second_err = capsys.readouterr().err
    assert "anonymous usage data" not in second_err.lower()
    assert all(event != "cli_first_run" for (event, _) in captured_events)
