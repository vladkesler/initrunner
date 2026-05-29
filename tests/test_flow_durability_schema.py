"""Tests for the flow DurabilityConfig schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from initrunner.flow.schema import (
    DurabilityConfig,
    FlowAgentConfig,
    FlowDefinition,
    FlowMetadata,
    FlowSpec,
)


def _flow(durability: dict | None = None) -> FlowDefinition:
    spec: dict = {"agents": {"a": {"role": "a.yaml"}}}
    if durability is not None:
        spec["durability"] = durability
    return FlowDefinition(
        apiVersion="initrunner.dev/v1",
        kind="Flow",
        metadata=FlowMetadata(name="t"),
        spec=FlowSpec(**spec),
    )


def test_default_durability_disabled() -> None:
    flow = _flow()
    assert flow.spec.durability.enabled is False
    assert flow.spec.durability.backend == "none"
    assert flow.spec.durability.active is False


def test_enabled_implies_journal_backend() -> None:
    cfg = DurabilityConfig(enabled=True)
    assert cfg.backend == "journal"
    assert cfg.active is True


def test_explicit_journal_backend() -> None:
    cfg = DurabilityConfig(enabled=True, backend="journal")
    assert cfg.active is True


def test_disabled_backend_none_is_inactive() -> None:
    cfg = DurabilityConfig(enabled=False, backend="none")
    assert cfg.active is False


def test_unsupported_backends_rejected() -> None:
    for backend in ("temporal", "dbos", "redis"):
        with pytest.raises(ValidationError):
            DurabilityConfig(backend=backend)  # type: ignore[arg-type]


def test_invalid_retry_policy_rejected() -> None:
    with pytest.raises(ValidationError):
        DurabilityConfig(retry_policy="quadratic")  # type: ignore[arg-type]


def test_flow_parses_durability_block() -> None:
    flow = _flow({"enabled": True, "max_retries": 5})
    assert flow.spec.durability.active is True
    assert flow.spec.durability.max_retries == 5


def test_flow_agent_config_unaffected() -> None:
    # Durability lives on FlowSpec, not per-agent.
    cfg = FlowAgentConfig(role="r.yaml")
    assert not hasattr(cfg, "durability")
