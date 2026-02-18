"""OpenTelemetry observability: tracing setup, context propagation, and shutdown."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from initrunner.agent.schema.observability import ObservabilityConfig

_logger = logging.getLogger(__name__)

# Idempotent guard — only configure once per process.
_provider: Any = None


def setup_tracing(config: ObservabilityConfig, agent_name: str) -> Any:
    """Configure a global TracerProvider based on *config*.

    Returns the configured provider, or the existing one if already set up.
    All imports are lazy to keep CLI startup fast and avoid import errors
    when ``opentelemetry-sdk`` isn't installed.
    """
    global _provider
    if _provider is not None:
        return _provider

    if config.backend == "logfire":
        import logfire  # type: ignore[import-not-found]

        service = config.service_name or agent_name
        logfire.configure(service_name=service)
        _provider = True  # sentinel — Logfire manages its own provider
        return _provider

    from initrunner._compat import require_observability

    require_observability()

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
    from opentelemetry.sdk.trace.sampling import TraceIdRatioBased  # type: ignore[import-not-found]

    from initrunner import __version__

    service = config.service_name or agent_name
    resource = Resource.create(
        {
            "service.name": service,
            "service.version": __version__,
        }
    )

    sampler = TraceIdRatioBased(config.sample_rate)
    provider = TracerProvider(resource=resource, sampler=sampler)

    if config.backend == "console":
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        # otlp
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            BatchSpanProcessor,
        )

        exporter = OTLPSpanExporter(endpoint=config.endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    _provider = provider
    return _provider


def get_instrumentation_settings(config: ObservabilityConfig) -> Any:
    """Return a ``pydantic_ai.InstrumentationSettings`` configured for the active provider."""
    from pydantic_ai import InstrumentationSettings

    return InstrumentationSettings(include_content=config.include_content)


def inject_trace_context(carrier: dict[str, str]) -> None:
    """Inject current span context into *carrier* (W3C ``traceparent``/``tracestate``).

    No-op when OTel isn't configured.
    """
    if _provider is None:
        return
    try:
        from opentelemetry import propagate

        propagate.inject(carrier)
    except Exception:
        _logger.debug("Failed to inject trace context", exc_info=True)


def extract_trace_context(carrier: dict[str, str]) -> Any:
    """Extract span context from *carrier*. Returns an OTel ``Context``.

    Returns ``None`` when OTel isn't configured.
    """
    if _provider is None:
        return None
    try:
        from opentelemetry import propagate

        return propagate.extract(carrier)
    except Exception:
        _logger.debug("Failed to extract trace context", exc_info=True)
        return None


def shutdown_tracing() -> None:
    """Flush buffered spans and shut down the global TracerProvider.

    Safe to call from sync context — ``force_flush`` and ``shutdown`` are
    blocking calls.  No-op when the provider is managed by Logfire or was
    never configured.
    """
    global _provider
    if _provider is None:
        return

    # Logfire manages its own lifecycle.
    if _provider is True:
        _provider = None
        return

    try:
        _provider.force_flush(timeout_millis=5000)
    except Exception:
        _logger.debug("force_flush failed", exc_info=True)

    try:
        _provider.shutdown()
    except Exception:
        _logger.debug("shutdown failed", exc_info=True)

    _provider = None


def setup_log_correlation() -> None:
    """Inject ``trace_id`` / ``span_id`` into Python log records.

    Uses the OTel logging instrumentor so that any ``_logger.info(...)``
    call during a traced span automatically carries trace context.
    """
    if _provider is None:
        return
    try:
        from opentelemetry.instrumentation.logging import (  # type: ignore[import-not-found]
            LoggingInstrumentor,
        )

        LoggingInstrumentor().instrument(set_logging_format=True)
    except Exception:
        _logger.debug("Failed to set up log correlation", exc_info=True)
