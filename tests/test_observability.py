"""Tests for the OpenTelemetry observability module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from initrunner.agent.schema import ObservabilityConfig, RoleDefinition

# ---------------------------------------------------------------------------
# ObservabilityConfig validation
# ---------------------------------------------------------------------------


class TestObservabilityConfig:
    def test_defaults(self):
        cfg = ObservabilityConfig()
        assert cfg.backend == "otlp"
        assert cfg.endpoint == "http://localhost:4317"
        assert cfg.service_name == ""
        assert cfg.trace_tool_calls is True
        assert cfg.trace_token_usage is True
        assert cfg.sample_rate == 1.0
        assert cfg.include_content is False

    def test_sample_rate_valid_zero(self):
        cfg = ObservabilityConfig(sample_rate=0.0)
        assert cfg.sample_rate == 0.0

    def test_sample_rate_valid_one(self):
        cfg = ObservabilityConfig(sample_rate=1.0)
        assert cfg.sample_rate == 1.0

    def test_sample_rate_valid_half(self):
        cfg = ObservabilityConfig(sample_rate=0.5)
        assert cfg.sample_rate == 0.5

    def test_sample_rate_too_low(self):
        with pytest.raises(ValidationError):
            ObservabilityConfig(sample_rate=-0.1)

    def test_sample_rate_too_high(self):
        with pytest.raises(ValidationError):
            ObservabilityConfig(sample_rate=1.1)

    def test_backend_otlp(self):
        cfg = ObservabilityConfig(backend="otlp")
        assert cfg.backend == "otlp"

    def test_backend_console(self):
        cfg = ObservabilityConfig(backend="console")
        assert cfg.backend == "console"

    def test_backend_logfire(self):
        cfg = ObservabilityConfig(backend="logfire")
        assert cfg.backend == "logfire"

    def test_backend_invalid(self):
        with pytest.raises(ValidationError):
            ObservabilityConfig(backend="datadog")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Schema integration: observability field on AgentSpec
# ---------------------------------------------------------------------------


def _minimal_role_data() -> dict:
    return {
        "apiVersion": "initrunner/v1",
        "kind": "Agent",
        "metadata": {"name": "test-agent", "description": "A test agent"},
        "spec": {
            "role": "You are a test agent.",
            "model": {"provider": "openai", "name": "gpt-4o"},
        },
    }


class TestObservabilityInSchema:
    def test_observability_none_by_default(self):
        role = RoleDefinition.model_validate(_minimal_role_data())
        assert role.spec.observability is None

    def test_observability_parses(self):
        data = _minimal_role_data()
        data["spec"]["observability"] = {
            "backend": "console",
            "service_name": "my-svc",
            "sample_rate": 0.5,
            "include_content": True,
        }
        role = RoleDefinition.model_validate(data)
        assert role.spec.observability is not None
        assert role.spec.observability.backend == "console"
        assert role.spec.observability.service_name == "my-svc"
        assert role.spec.observability.sample_rate == 0.5
        assert role.spec.observability.include_content is True

    def test_observability_invalid_backend_in_role(self):
        data = _minimal_role_data()
        data["spec"]["observability"] = {"backend": "invalid"}
        with pytest.raises(ValidationError):
            RoleDefinition.model_validate(data)


# ---------------------------------------------------------------------------
# setup_tracing / shutdown_tracing
# ---------------------------------------------------------------------------


class TestSetupTracing:
    def setup_method(self):
        """Reset module-level _provider before each test."""
        import initrunner.observability as obs

        obs._provider = None

    def teardown_method(self):
        import initrunner.observability as obs

        obs._provider = None

    def test_setup_console_backend(self):
        """Console backend should set up without external OTLP deps."""
        pytest.importorskip("opentelemetry.sdk")

        from initrunner.observability import setup_tracing

        cfg = ObservabilityConfig(backend="console")
        provider = setup_tracing(cfg, "test-agent")
        assert provider is not None

        from initrunner.observability import shutdown_tracing

        shutdown_tracing()

    def test_idempotent_setup(self):
        """Calling setup_tracing twice returns same provider."""
        pytest.importorskip("opentelemetry.sdk")

        from initrunner.observability import setup_tracing

        cfg = ObservabilityConfig(backend="console")
        p1 = setup_tracing(cfg, "test-agent")
        p2 = setup_tracing(cfg, "test-agent")
        assert p1 is p2

        from initrunner.observability import shutdown_tracing

        shutdown_tracing()

    def test_shutdown_resets_provider(self):
        """After shutdown, _provider should be None."""
        pytest.importorskip("opentelemetry.sdk")

        import initrunner.observability as obs
        from initrunner.observability import setup_tracing, shutdown_tracing

        cfg = ObservabilityConfig(backend="console")
        setup_tracing(cfg, "test-agent")
        assert obs._provider is not None

        shutdown_tracing()
        assert obs._provider is None


# ---------------------------------------------------------------------------
# Trace context propagation round-trip
# ---------------------------------------------------------------------------


class TestTraceContextPropagation:
    def setup_method(self):
        import initrunner.observability as obs

        obs._provider = None

    def teardown_method(self):
        import initrunner.observability as obs

        obs._provider = None

    def test_inject_noop_when_not_configured(self):
        """inject_trace_context should be a no-op with no provider."""
        from initrunner.observability import inject_trace_context

        carrier: dict[str, str] = {}
        inject_trace_context(carrier)
        assert "traceparent" not in carrier

    def test_extract_returns_none_when_not_configured(self):
        """extract_trace_context should return None with no provider."""
        from initrunner.observability import extract_trace_context

        result = extract_trace_context({"traceparent": "00-abc-def-01"})
        assert result is None

    def test_inject_extract_roundtrip(self):
        """Inject and extract should propagate traceparent."""
        pytest.importorskip("opentelemetry.sdk")

        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]

        import initrunner.observability as obs
        from initrunner.observability import (
            extract_trace_context,
            inject_trace_context,
            shutdown_tracing,
        )

        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        obs._provider = provider

        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("test-span"):
            carrier: dict[str, str] = {}
            inject_trace_context(carrier)
            assert "traceparent" in carrier

            ctx = extract_trace_context(carrier)
            assert ctx is not None

        shutdown_tracing()


# ---------------------------------------------------------------------------
# get_tracer returns no-op when OTel not configured
# ---------------------------------------------------------------------------


class TestNoOpTracer:
    def test_get_tracer_noop(self):
        """get_tracer('initrunner') returns no-op when OTel isn't configured."""
        from opentelemetry import trace

        tracer = trace.get_tracer("initrunner")
        # No-op tracer should not raise
        with tracer.start_as_current_span("test"):
            pass


# ---------------------------------------------------------------------------
# get_instrumentation_settings
# ---------------------------------------------------------------------------


class TestInstrumentationSettings:
    def test_returns_settings_with_include_content(self):
        from initrunner.observability import get_instrumentation_settings

        cfg = ObservabilityConfig(include_content=True)
        settings = get_instrumentation_settings(cfg)
        assert settings.include_content is True

    def test_returns_settings_without_include_content(self):
        from initrunner.observability import get_instrumentation_settings

        cfg = ObservabilityConfig(include_content=False)
        settings = get_instrumentation_settings(cfg)
        assert settings.include_content is False


# ---------------------------------------------------------------------------
# Agent creation passes instrument= when observability is set
# ---------------------------------------------------------------------------


class TestAgentCreationWithInstrumentation:
    def test_create_agent_passes_instrument(self):
        """_create_agent should pass instrument kwarg to Agent."""
        from initrunner.agent.loader import _create_agent

        mock_settings = MagicMock()

        with patch("initrunner.agent.loader._build_model", return_value="openai:gpt-4o"):
            with patch("initrunner.agent.loader.Agent") as MockAgent:
                role_data = _minimal_role_data()
                role = RoleDefinition.model_validate(role_data)

                _create_agent(role, "system prompt", [], str, instrument=mock_settings)

                call_kwargs = MockAgent.call_args
                assert call_kwargs.kwargs["instrument"] is mock_settings

    def test_create_agent_no_instrument_by_default(self):
        """_create_agent without instrument should not pass it to Agent."""
        from initrunner.agent.loader import _create_agent

        with patch("initrunner.agent.loader._build_model", return_value="openai:gpt-4o"):
            with patch("initrunner.agent.loader.Agent") as MockAgent:
                role_data = _minimal_role_data()
                role = RoleDefinition.model_validate(role_data)

                _create_agent(role, "system prompt", [], str)

                call_kwargs = MockAgent.call_args
                assert "instrument" not in call_kwargs.kwargs
