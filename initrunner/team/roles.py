"""Role synthesis from team/persona config."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.team.schema import PersonaConfig, TeamDefinition


def resolve_persona_role(
    name: str,
    persona: PersonaConfig,
    team: TeamDefinition,
) -> tuple[RoleDefinition, Path | None]:
    """Return the role to run for a persona plus the directory it came from.

    Personas adapted from a ``use:`` reference run the full referenced role and
    resolve relative paths against its own directory. Inline personas synthesize
    a minimal role and have no directory of their own. The referenced role is
    copied because callers patch shared stores onto it in place.
    """
    role, role_dir = team.member_provenance(name)
    if role is not None:
        return role.model_copy(deep=True), role_dir
    return persona_to_role(name, persona, team), None


def load_member_dotenvs(team: TeamDefinition) -> None:
    """Load .env files for personas that reference their own role files.

    Done once up front, in declared order, rather than per build: the parallel,
    debate and ensemble strategies build personas from threads and ``load_dotenv``
    mutates the process environment. ``override=False`` means the team's own .env
    still wins, and earlier personas win over later ones.
    """
    from initrunner.agent.loader import _load_dotenv

    seen: set[Path] = set()
    for name in team.spec.personas:
        _role, role_dir = team.member_provenance(name)
        if role_dir is not None and role_dir not in seen:
            seen.add(role_dir)
            _load_dotenv(role_dir)


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
