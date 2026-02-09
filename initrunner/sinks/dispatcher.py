"""Sink lifecycle manager — builds sinks from config and dispatches payloads."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from initrunner._log import get_logger
from initrunner.agent.executor import RunResult
from initrunner.agent.schema import (
    CustomSinkConfig,
    FileSinkConfig,
    RoleDefinition,
    SinkConfig,
    WebhookSinkConfig,
)
from initrunner.sinks.base import SinkBase, SinkPayload

logger = get_logger("sink.dispatcher")


def _build_webhook_sink(config: WebhookSinkConfig, role_dir: Path | None = None) -> SinkBase:
    from initrunner.sinks.webhook import WebhookSink

    return WebhookSink(
        url=config.url,
        method=config.method,
        headers=config.headers,
        timeout_seconds=config.timeout_seconds,
        retry_count=config.retry_count,
    )


def _build_file_sink(config: FileSinkConfig, role_dir: Path | None = None) -> SinkBase:
    from initrunner.sinks.file import FileSink

    return FileSink(path=config.path, fmt=config.format)


def _build_custom_sink(config: CustomSinkConfig, role_dir: Path | None = None) -> SinkBase:
    from initrunner.sinks.custom import CustomSink

    return CustomSink(module=config.module, function=config.function, role_dir=role_dir)


_SINK_BUILDERS: dict[type, Callable[..., SinkBase]] = {
    WebhookSinkConfig: _build_webhook_sink,
    FileSinkConfig: _build_file_sink,
    CustomSinkConfig: _build_custom_sink,
}


def build_sink(config: SinkConfig, role_dir: Path | None = None) -> SinkBase | None:
    """Build a sink instance from a config object. Returns None if unknown type."""
    builder = _SINK_BUILDERS.get(type(config))
    return builder(config, role_dir) if builder else None


class SinkDispatcher:
    def __init__(
        self,
        sink_configs: list[SinkConfig],
        role: RoleDefinition,
        role_dir: Path | None = None,
    ) -> None:
        self._sinks: list[SinkBase] = []
        self._role = role

        for config in sink_configs:
            sink = build_sink(config, role_dir)
            if sink:
                self._sinks.append(sink)

    def add_sink(self, sink: SinkBase) -> None:
        """Add an externally-constructed sink (e.g. DelegateSink)."""
        self._sinks.append(sink)

    def dispatch(
        self,
        result: RunResult,
        prompt: str,
        *,
        trigger_type: str | None = None,
        trigger_metadata: dict[str, str] | None = None,
    ) -> None:
        payload = SinkPayload.from_run(
            result,
            agent_name=self._role.metadata.name,
            model=self._role.spec.model.name,
            provider=self._role.spec.model.provider,
            prompt=prompt,
            trigger_type=trigger_type,
            trigger_metadata=trigger_metadata,
        )

        for sink in self._sinks:
            try:
                sink.send(payload)
            except Exception as exc:
                name = type(sink).__name__
                logger.error("Sink %s failed: %s", name, exc)

    @property
    def count(self) -> int:
        return len(self._sinks)
