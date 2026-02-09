"""Tests for the compose health monitor."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, PropertyMock

from initrunner.compose.health import HealthMonitor
from initrunner.compose.schema import ComposeServiceConfig, RestartPolicy


def _make_mock_service(
    *,
    alive: bool = True,
    error_count: int = 0,
    restart_condition: str = "none",
    max_retries: int = 3,
    delay_seconds: float = 0,
) -> MagicMock:
    svc = MagicMock()
    type(svc).is_alive = PropertyMock(return_value=alive)
    type(svc).error_count = PropertyMock(return_value=error_count)
    svc.config = ComposeServiceConfig(
        role="role.yaml",
        restart=RestartPolicy(
            condition=restart_condition,  # type: ignore[invalid-argument-type]
            max_retries=max_retries,
            delay_seconds=delay_seconds,  # type: ignore[invalid-argument-type]
        ),
    )
    return svc


class TestHealthMonitor:
    def test_creation(self):
        services = {"a": _make_mock_service()}
        monitor = HealthMonitor(services, check_interval=1.0)
        assert monitor.restart_counts == {"a": 0}

    def test_start_stop(self):
        services = {"a": _make_mock_service()}
        monitor = HealthMonitor(services, check_interval=0.1)
        monitor.start()
        time.sleep(0.2)
        monitor.stop()

    def test_no_restart_when_alive(self):
        svc = _make_mock_service(alive=True, restart_condition="always")
        services = {"a": svc}
        monitor = HealthMonitor(services, check_interval=0.1)
        monitor._check_and_restart()
        svc.start.assert_not_called()

    def test_no_restart_when_policy_none(self):
        svc = _make_mock_service(alive=False, restart_condition="none")
        services = {"a": svc}
        monitor = HealthMonitor(services, check_interval=0.1)
        monitor._check_and_restart()
        svc.start.assert_not_called()

    def test_restart_on_failure_with_errors(self):
        svc = _make_mock_service(
            alive=False,
            error_count=1,
            restart_condition="on-failure",
            delay_seconds=0,
        )
        services = {"a": svc}
        monitor = HealthMonitor(services, check_interval=0.1)
        monitor._check_and_restart()
        svc.start.assert_called_once()
        assert monitor.restart_counts["a"] == 1

    def test_no_restart_on_failure_without_errors(self):
        svc = _make_mock_service(
            alive=False,
            error_count=0,
            restart_condition="on-failure",
            delay_seconds=0,
        )
        services = {"a": svc}
        monitor = HealthMonitor(services, check_interval=0.1)
        monitor._check_and_restart()
        svc.start.assert_not_called()

    def test_restart_always(self):
        svc = _make_mock_service(
            alive=False,
            restart_condition="always",
            delay_seconds=0,
        )
        services = {"a": svc}
        monitor = HealthMonitor(services, check_interval=0.1)
        monitor._check_and_restart()
        svc.start.assert_called_once()

    def test_max_retries_exceeded(self):
        svc = _make_mock_service(
            alive=False,
            restart_condition="always",
            max_retries=2,
            delay_seconds=0,
        )
        services = {"a": svc}
        monitor = HealthMonitor(services, check_interval=0.1)

        # First two restarts succeed
        monitor._check_and_restart()
        monitor._check_and_restart()
        assert monitor.restart_counts["a"] == 2

        # Third should be blocked
        monitor._check_and_restart()
        assert svc.start.call_count == 2  # Still only 2

    def test_multiple_services(self):
        healthy = _make_mock_service(alive=True, restart_condition="always")
        dead = _make_mock_service(
            alive=False,
            restart_condition="always",
            delay_seconds=0,
        )
        services = {"healthy": healthy, "dead": dead}
        monitor = HealthMonitor(services, check_interval=0.1)
        monitor._check_and_restart()

        healthy.start.assert_not_called()
        dead.start.assert_called_once()
