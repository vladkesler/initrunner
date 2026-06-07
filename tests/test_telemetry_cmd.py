"""`initrunner telemetry ...` subcommands and the doctor status row."""

from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from initrunner.cli.telemetry_cmd import app as telemetry_app
from initrunner.config import get_home_dir

runner = CliRunner()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path))
    for var in ("DO_NOT_TRACK", "INITRUNNER_TELEMETRY", "CI"):
        monkeypatch.delenv(var, raising=False)
    get_home_dir.cache_clear()
    return tmp_path


def test_status_enable_disable_reset(home):
    from initrunner.telemetry import _config

    # Fresh install: opt-in, undecided.
    result = runner.invoke(telemetry_app, ["status"])
    assert result.exit_code == 0
    assert "opt-in" in result.output.lower()

    result = runner.invoke(telemetry_app, ["disable"])
    assert result.exit_code == 0
    disabled = _config._load_raw()
    assert disabled is not None and disabled.consent == "denied"

    result = runner.invoke(telemetry_app, ["status"])
    assert "disabled" in result.output.lower()
    assert "consent-denied" in result.output

    result = runner.invoke(telemetry_app, ["enable"])
    assert result.exit_code == 0
    enabled = _config._load_raw()
    assert enabled is not None and enabled.consent == "granted"

    result = runner.invoke(telemetry_app, ["status"])
    assert "enabled" in result.output.lower()

    before_reset = _config._load_raw()
    assert before_reset is not None
    old_id = before_reset.install_id
    result = runner.invoke(telemetry_app, ["reset"])
    assert result.exit_code == 0
    after_reset = _config._load_raw()
    assert after_reset is not None and after_reset.install_id != old_id


def test_doctor_shows_telemetry_row(home):
    from initrunner.cli.doctor_cmd import doctor

    app = typer.Typer()
    app.command()(doctor)
    result = runner.invoke(app, [])
    assert "Usage telemetry" in result.output
