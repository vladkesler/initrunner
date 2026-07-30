"""CLI tests for always-on services."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from initrunner.agent.schema.service import ProcessIdentity, ServiceState, ServiceStatus
from initrunner.cli.main import app

runner = CliRunner()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("INITRUNNER_HOME", str(tmp_path / "home"))
    from initrunner.config import get_home_dir

    get_home_dir.cache_clear()
    yield tmp_path / "home"
    get_home_dir.cache_clear()


def test_help_lists_service() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "service" in result.stdout
    # Panel name appears in rich help
    assert "Always-on" in result.stdout or "service" in result.stdout


def test_service_list(home: Path) -> None:
    result = runner.invoke(app, ["service", "list"])
    assert result.exit_code == 0
    assert "collector" in result.stdout


def test_service_info_collector(home: Path) -> None:
    result = runner.invoke(app, ["service", "info", "collector"])
    assert result.exit_code == 0
    assert "target" in result.stdout
    assert "service-collector" in result.stdout


def test_malicious_slug_rejected(home: Path) -> None:
    result = runner.invoke(app, ["service", "status", "../etc"])
    assert result.exit_code != 0


def test_start_positional_and_set_conflict(home: Path) -> None:
    result = runner.invoke(
        app,
        [
            "service",
            "start",
            "collector",
            "acme.com",
            "--set",
            "target=other.com",
        ],
    )
    assert result.exit_code != 0
    assert "not both" in result.stdout.lower() or "Error" in result.stdout


def test_duplicate_set_rejected(home: Path) -> None:
    result = runner.invoke(
        app,
        [
            "service",
            "start",
            "collector",
            "--set",
            "target=a",
            "--set",
            "target=b",
        ],
    )
    assert result.exit_code != 0
    assert "Duplicate" in result.stdout


def test_start_success_message(home: Path) -> None:
    state = ServiceState(
        slug="collector",
        service_version="1.0.0",
        status=ServiceStatus.RUNNING,
        params={"target": "acme.com"},
        every="daily",
        resolved_cron="0 6 * * *",
        timezone="UTC",
        generation=1,
        role_file="role.1.yaml",
        process=ProcessIdentity(
            pid=4242,
            boot_id="b",
            proc_start_ticks=1,
            role_path="/tmp/role.1.yaml",
        ),
        output_paths=["/tmp/out.md"],
    )
    from initrunner.services.always_on import StartResult

    with patch(
        "initrunner.services.always_on.start_service",
        return_value=StartResult(state=state),
    ):
        # get_catalog_entry still runs for primary param
        result = runner.invoke(app, ["service", "start", "collector", "acme.com"])
    assert result.exit_code == 0
    assert "Started" in result.stdout or "running" in result.stdout.lower()
    assert "acme.com" in result.stdout
    assert "/tmp/out.md" in result.stdout
