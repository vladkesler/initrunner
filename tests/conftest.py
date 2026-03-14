"""Shared test fixtures and helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from initrunner.agent.schema.autonomy import AutonomyConfig
from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
from initrunner.agent.schema.guardrails import Guardrails
from initrunner.agent.schema.role import AgentSpec, RoleDefinition
from initrunner.agent.tools._registry import ToolBuildContext


def make_role(
    *,
    name: str = "test-agent",
    system_prompt: str = "You are a test.",
    provider: str = "openai",
    model_name: str = "gpt-5-mini",
    max_iterations: int = 10,
    autonomous_token_budget: int | None = None,
    autonomy: AutonomyConfig | None = None,
    guardrails: Guardrails | None = None,
    **spec_kwargs,
) -> RoleDefinition:
    """Build a minimal RoleDefinition for tests."""
    g = guardrails or Guardrails(
        max_iterations=max_iterations,
        autonomous_token_budget=autonomous_token_budget,
    )
    return RoleDefinition(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=Metadata(name=name),
        spec=AgentSpec(
            role=system_prompt,
            model=ModelConfig(provider=provider, name=model_name),
            guardrails=g,
            autonomy=autonomy,
            **spec_kwargs,
        ),
    )


def make_tool_build_context(
    *,
    role_dir: Path | None = None,
    **role_kwargs,
) -> ToolBuildContext:
    """Build a minimal ToolBuildContext for tool tests."""
    role = make_role(**role_kwargs)
    return ToolBuildContext(role=role, role_dir=role_dir)


def make_mock_agent(
    *,
    output: str = "Hello!",
    tokens_in: int = 10,
    tokens_out: int = 5,
    tool_calls: int = 0,
) -> MagicMock:
    """Build a mock PydanticAI Agent with configurable usage stats."""
    agent = MagicMock()
    result = MagicMock()
    result.output = output

    usage = MagicMock()
    usage.input_tokens = tokens_in
    usage.output_tokens = tokens_out
    usage.total_tokens = tokens_in + tokens_out
    usage.tool_calls = tool_calls
    result.usage.return_value = usage
    result.all_messages.return_value = [{"role": "assistant", "content": output}]

    agent.run_sync.return_value = result
    return agent


@pytest.fixture
def role():
    """Provide a default test RoleDefinition."""
    return make_role()


@pytest.fixture
def tool_ctx():
    """Provide a default ToolBuildContext."""
    return make_tool_build_context()


@pytest.fixture
def mock_agent():
    """Provide a default mock agent."""
    return make_mock_agent()
