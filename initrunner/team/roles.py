"""Role synthesis from team/persona config."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.team.schema import PersonaConfig, TeamDefinition


def persona_to_role(
    name: str,
    persona: PersonaConfig,
    team: TeamDefinition,
) -> RoleDefinition:
    """Synthesize a RoleDefinition from a persona entry."""
    from initrunner.agent.schema.base import Kind, RoleMetadata
    from initrunner.agent.schema.guardrails import Guardrails
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition

    model = persona.model or team.spec.model
    if persona.tools_mode == "extend":
        tools = list(team.spec.tools) + list(persona.tools)
    else:
        tools = list(persona.tools)
    guardrails = Guardrails(
        max_tokens_per_run=team.spec.guardrails.max_tokens_per_run,
        max_tool_calls=team.spec.guardrails.max_tool_calls,
        timeout_seconds=team.spec.guardrails.timeout_seconds,
    )
    spec = AgentSpec(
        role=persona.role,
        model=model,
        tools=tools,
        guardrails=guardrails,
        observability=team.spec.observability,
    )
    metadata = RoleMetadata(name=name)
    return RoleDefinition(
        apiVersion=team.apiVersion,
        kind=Kind.AGENT,
        metadata=metadata,
        spec=spec,
    )


def team_report_role(team: TeamDefinition) -> RoleDefinition:
    """Synthesize a minimal role for report export from team metadata."""
    from initrunner.agent.schema.base import Kind, RoleMetadata
    from initrunner.agent.schema.role import AgentSpec, RoleDefinition

    spec = AgentSpec(
        role=team.metadata.description or "Team run",
        model=team.spec.model,
        tools=list(team.spec.tools),
    )
    metadata = RoleMetadata(name=team.metadata.name)
    return RoleDefinition(
        apiVersion=team.apiVersion,
        kind=Kind.AGENT,
        metadata=metadata,
        spec=spec,
    )
