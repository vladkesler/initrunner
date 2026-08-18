"""Build an A2A 1.0 AgentCard from an InitRunner role."""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2a.types import (  # type: ignore[import-not-found]
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.constants import (  # type: ignore[import-not-found]
    PROTOCOL_VERSION_1_0,
    TransportProtocol,
)

from initrunner.a2a.convert import INPUT_MODES

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.agent.skills import ResolvedSkill


def build_agent_card(
    role: RoleDefinition,
    *,
    url: str,
    require_auth: bool,
    streaming: bool = True,
    skills: list[ResolvedSkill] | None = None,
) -> AgentCard:
    """Construct a 1.0 AgentCard advertised at ``/.well-known/agent-card.json``.

    Task and conversation context live in process memory and are lost on
    restart. ``streaming`` advertises ``SendStreamingMessage`` / token chunks.
    """
    card_skills = [
        AgentSkill(
            id=role.metadata.name,
            name=role.metadata.name,
            description=role.metadata.description,
            tags=list(role.metadata.tags),
        )
    ]
    for resolved in skills or []:
        frontmatter = resolved.definition.frontmatter
        card_skills.append(
            AgentSkill(
                id=frontmatter.name,
                name=frontmatter.name,
                description=frontmatter.description,
            )
        )

    card = AgentCard(
        name=role.metadata.name,
        description=role.metadata.description,
        version=role.metadata.version,
        supported_interfaces=[
            AgentInterface(
                url=url,
                protocol_binding=TransportProtocol.JSONRPC,
                protocol_version=PROTOCOL_VERSION_1_0,
            )
        ],
        capabilities=AgentCapabilities(
            streaming=streaming,
            push_notifications=False,
            extended_agent_card=False,
        ),
        default_input_modes=list(INPUT_MODES),
        default_output_modes=["text/plain", "application/json"],
        skills=card_skills,
    )

    if require_auth:
        card.security_schemes["bearer"].CopyFrom(
            SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(
                    scheme="bearer",
                    description="InitRunner API key (Bearer token)",
                )
            )
        )
        card.security_requirements.append(SecurityRequirement(schemes={"bearer": StringList()}))

    return card
