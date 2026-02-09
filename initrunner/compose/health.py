"""Health monitor with restart policy enforcement for compose services."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from initrunner._log import get_logger

if TYPE_CHECKING:
    from initrunner.compose.orchestrator import ComposeService

logger = get_logger("compose.health")


class HealthMonitor:
    """Periodically checks service health and applies restart policies."""

    def __init__(
        self,
        services: dict[str, ComposeService],
        check_interval: float = 10.0,
    ) -> None:
        self._services = services
        self._check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._restart_counts: dict[str, int] = {name: 0 for name in services}

    def _check_and_restart(self) -> None:
        """Check each service and restart if policy allows."""
        for name, service in self._services.items():
            if self._stop_event.is_set():
                return

            if service.is_alive:
                continue

            policy = service.config.restart
            if policy.condition == "none":
                continue

            if policy.condition == "on-failure" and service.error_count == 0:
                continue

            with self._lock:
                if self._restart_counts[name] >= policy.max_retries:
                    logger.error(
                        "Service '%s' exceeded max restarts (%d). Not restarting.",
                        name,
                        policy.max_retries,
                    )
                    continue

                self._restart_counts[name] += 1
                current_count = self._restart_counts[name]

            logger.warning(
                "Restarting service '%s' (attempt %d/%d)",
                name,
                current_count,
                policy.max_retries,
            )

            # Use stop_event.wait() instead of time.sleep() for interruptibility
            if self._stop_event.wait(timeout=policy.delay_seconds):
                return  # Stop requested during delay

            service.start()

    def _run(self) -> None:
        """Main monitor loop."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self._check_interval)
            if not self._stop_event.is_set():
                self._check_and_restart()

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="compose-health")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def restart_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._restart_counts)
