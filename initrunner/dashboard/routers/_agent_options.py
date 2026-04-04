"""Shared helper for building agent picker options from the role cache."""

from __future__ import annotations

from initrunner.dashboard.deps import RoleCache
from initrunner.dashboard.schemas import AgentSlotModel, AgentSlotOption


def build_agent_options(role_cache: RoleCache) -> list[AgentSlotOption]:
    """Build picker options from the role cache.

    Used by both flow and team builder option endpoints.  Skips errored
    roles and sorts the result by agent name.
    """
    agents: list[AgentSlotOption] = []
    for rid, dr in role_cache.all().items():
        if dr.error or dr.role is None:
            continue
        model = dr.role.spec.model
        agents.append(
            AgentSlotOption(
                id=rid,
                name=dr.role.metadata.name,
                description=dr.role.metadata.description or "",
                path=str(dr.path),
                tags=list(dr.role.metadata.tags or []),
                features=list(dr.role.spec.features),
                model=AgentSlotModel(
                    provider=model.provider,
                    name=model.name,
                    base_url=model.base_url,
                    api_key_env=model.api_key_env,
                )
                if model
                else None,
            )
        )
    agents.sort(key=lambda a: a.name)
    return agents
