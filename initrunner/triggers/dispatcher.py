"""Trigger lifecycle manager."""

from __future__ import annotations

from collections.abc import Callable

from initrunner.triggers.base import TriggerBase, TriggerEvent

# ---------------------------------------------------------------------------
# Trigger builder registry
# ---------------------------------------------------------------------------

_TRIGGER_BUILDERS: dict[type, Callable[..., TriggerBase]] = {}


def register_trigger_builder(
    config_type: type,
) -> Callable[[Callable[..., TriggerBase]], Callable[..., TriggerBase]]:
    """Register a builder function for a trigger config type."""

    def decorator(fn: Callable[..., TriggerBase]) -> Callable[..., TriggerBase]:
        _TRIGGER_BUILDERS[config_type] = fn
        return fn

    return decorator


# ---------------------------------------------------------------------------
# Built-in trigger builders (registered at import time)
# ---------------------------------------------------------------------------


def _register_builtins() -> None:
    """Register the three built-in trigger types.

    Wrapped in a function to keep the config-type imports lazy — the
    individual trigger modules are still only imported when a trigger
    is actually built.
    """
    from initrunner.agent.schema import (
        CronTriggerConfig,
        FileWatchTriggerConfig,
        WebhookTriggerConfig,
    )

    @register_trigger_builder(CronTriggerConfig)
    def _build_cron(config, callback):
        from initrunner.triggers.cron import CronTrigger

        return CronTrigger(config, callback)

    @register_trigger_builder(FileWatchTriggerConfig)
    def _build_file_watch(config, callback):
        from initrunner.triggers.file_watcher import FileWatchTrigger

        return FileWatchTrigger(config, callback)

    @register_trigger_builder(WebhookTriggerConfig)
    def _build_webhook(config, callback):
        from initrunner.triggers.webhook import WebhookTrigger

        return WebhookTrigger(config, callback)


_register_builtins()


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


class TriggerDispatcher:
    """Builds, starts, and stops all triggers from role config."""

    def __init__(
        self,
        trigger_configs: list,
        callback: Callable[[TriggerEvent], None],
    ) -> None:
        self._triggers: list[TriggerBase] = []
        for config in trigger_configs:
            builder = _TRIGGER_BUILDERS.get(type(config))
            if builder:
                self._triggers.append(builder(config, callback))

    def start_all(self) -> None:
        for trigger in self._triggers:
            trigger.start()

    def stop_all(self) -> None:
        for trigger in self._triggers:
            trigger.stop()

    def __enter__(self) -> TriggerDispatcher:
        self.start_all()
        return self

    def __exit__(self, *args: object) -> None:
        self.stop_all()

    @property
    def count(self) -> int:
        return len(self._triggers)
