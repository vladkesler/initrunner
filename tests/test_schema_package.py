"""Smoke tests verifying schema sub-modules import independently (no circular imports)."""

import importlib

import pytest

SUBMODULES = [
    "initrunner.agent.schema.base",
    "initrunner.agent.schema.guardrails",
    "initrunner.agent.schema.tools",
    "initrunner.agent.schema.triggers",
    "initrunner.agent.schema.sinks",
    "initrunner.agent.schema.ingestion",
    "initrunner.agent.schema.memory",
    "initrunner.agent.schema.security",
    "initrunner.agent.schema.observability",
    "initrunner.agent.schema.autonomy",
    "initrunner.agent.schema.output",
    "initrunner.agent.schema.role",
]


@pytest.mark.parametrize("module_name", SUBMODULES)
def test_submodule_imports(module_name: str) -> None:
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_role_aggregates_all_domains() -> None:
    """RoleDefinition should be constructable from the split modules."""
    from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition

    role = RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name="test-agent"),
        spec=AgentSpec(
            role="You are a test agent.",
            model=ModelConfig(provider="openai", name="gpt-4o-mini"),
        ),
    )
    assert role.metadata.name == "test-agent"
