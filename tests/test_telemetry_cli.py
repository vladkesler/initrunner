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


@pytest.fixture
def consented(home):
    """A persisted opt-in, so the capture site is active in non-TTY tests."""
    from initrunner.telemetry import _config

    _config.set_consent(True)
    return home


def _force_tty(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: value, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: value, raising=False)


def _commands(events: list[tuple[str, dict]]) -> list[dict]:
    return [props for (event, props) in events if event == "cli_command"]


def test_success_records_one_command(consented, captured_events, monkeypatch):
    from initrunner.cli import main as cli_main

    monkeypatch.setattr(sys, "argv", ["initrunner", "telemetry", "status"])
    with pytest.raises(SystemExit) as exc:
        cli_main.app_entry()

    assert exc.value.code in (0, None)
    commands = _commands(captured_events)
    assert len(commands) == 1
    assert commands[0]["command"] == "telemetry"
    assert commands[0]["status"] == "ok"


def test_error_path_records_status_and_exit_code(consented, captured_events, monkeypatch):
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


def test_version_path_recorded_when_callback_bypassed(consented, captured_events, monkeypatch):
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


def test_non_tty_first_run_does_not_prompt_or_send(home, captured_events, monkeypatch, capsys):
    import typer

    from initrunner.cli import main as cli_main
    from initrunner.telemetry import _config

    _force_tty(monkeypatch, False)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: pytest.fail("must not prompt in non-TTY"))
    monkeypatch.setattr(sys, "argv", ["initrunner", "doctor", "--role", "x", "--flow", "y"])
    with pytest.raises(SystemExit):
        cli_main.app_entry()

    out = capsys.readouterr()
    assert "help improve initrunner" not in (out.err + out.out).lower()
    assert captured_events == []  # opt-in: nothing sent while undecided
    state = _config._load_raw()
    assert state is None or state.consent == "unset"


def test_tty_first_run_prompt_accept_sends_first_run(home, captured_events, monkeypatch):
    import typer

    from initrunner.cli import main as cli_main
    from initrunner.telemetry import _config

    _force_tty(monkeypatch, True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(sys, "argv", ["initrunner", "doctor", "--role", "x", "--flow", "y"])
    with pytest.raises(SystemExit):
        cli_main.app_entry()

    assert any(event == "cli_first_run" for (event, _) in captured_events)
    state = _config._load_raw()
    assert state is not None and state.consent == "granted"


def test_tty_first_run_prompt_decline_persists_denied(home, captured_events, monkeypatch):
    import typer

    from initrunner.cli import main as cli_main
    from initrunner.telemetry import _config

    _force_tty(monkeypatch, True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(sys, "argv", ["initrunner", "doctor", "--role", "x", "--flow", "y"])
    with pytest.raises(SystemExit):
        cli_main.app_entry()

    assert captured_events == []  # declined: nothing sent
    state = _config._load_raw()
    assert state is not None and state.consent == "denied"


@pytest.mark.parametrize(
    "argv",
    [
        ["initrunner", "telemetry", "status"],
        ["initrunner", "--help"],
        ["initrunner", "doctor", "--help"],
    ],
)
def test_prompt_skipped_for_management_and_help(home, captured_events, monkeypatch, argv):
    import typer

    from initrunner.cli import main as cli_main
    from initrunner.telemetry import _config

    _force_tty(monkeypatch, True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: pytest.fail("must not prompt here"))
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit):
        cli_main.app_entry()

    assert all(event != "cli_first_run" for (event, _) in captured_events)
    state = _config._load_raw()
    assert state is None or state.consent == "unset"
