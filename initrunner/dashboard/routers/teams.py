"""Team discovery, detail, YAML editing, and run routes."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import StreamingResponse

from initrunner.dashboard.deps import TeamCache, get_team_cache
from initrunner.dashboard.schemas import (
    ItemSummary,
    PersonaDetail,
    TeamDetail,
    TeamRunRequest,
    TeamSummary,
    TeamYamlSaveRequest,
    TeamYamlSaveResponse,
)

router = APIRouter(prefix="/api/teams", tags=["teams"])


def _team_features(spec) -> list[str]:
    """Derive the features list from a TeamSpec."""
    features: list[str] = []
    if spec.tools:
        features.append("tools")
    if spec.shared_memory.enabled:
        features.append("shared_memory")
    if spec.shared_documents.enabled:
        features.append("shared_documents")
    if spec.guardrails.team_token_budget is not None:
        features.append("team_budget")
    if spec.observability is not None:
        features.append("observability")
    return features


def _summary_from(tid: str, discovered) -> TeamSummary:
    """Build a TeamSummary from a DiscoveredTeam."""
    if discovered.error or discovered.team is None:
        return TeamSummary(
            id=tid,
            name=discovered.path.stem,
            description="",
            strategy="sequential",
            persona_count=0,
            persona_names=[],
            provider="",
            model="",
            has_model_overrides=False,
            features=[],
            path=str(discovered.path),
            error=discovered.error,
        )
    team = discovered.team
    persona_names = list(team.spec.personas.keys())
    has_overrides = any(p.model is not None for p in team.spec.personas.values())
    return TeamSummary(
        id=tid,
        name=team.metadata.name,
        description=team.metadata.description or "",
        strategy=team.spec.strategy,
        persona_count=len(persona_names),
        persona_names=persona_names,
        provider=team.spec.model.provider,
        model=team.spec.model.name,
        has_model_overrides=has_overrides,
        features=_team_features(team.spec),
        path=str(discovered.path),
    )


def _tool_summary(tool_config) -> ItemSummary:
    """Build an ItemSummary from a ToolConfig."""
    return ItemSummary(
        type=tool_config.type,
        summary=getattr(tool_config, "summary", lambda: tool_config.type)()
        if hasattr(tool_config, "summary") and callable(getattr(tool_config, "summary", None))
        else tool_config.type,
        config=tool_config.model_dump(exclude={"type"}, exclude_none=True),
    )


def _detail_from(tid: str, discovered) -> TeamDetail:
    """Build a TeamDetail from a DiscoveredTeam."""
    team = discovered.team
    personas = []
    for name, persona in team.spec.personas.items():
        persona_tools = [_tool_summary(t) for t in persona.tools]
        personas.append(
            PersonaDetail(
                name=name,
                role=persona.role,
                model=persona.model.model_dump() if persona.model else None,
                tools=persona_tools,
                tools_mode=persona.tools_mode,
                environment_count=len(persona.environment),
            )
        )

    shared_tools = [_tool_summary(t) for t in team.spec.tools]

    return TeamDetail(
        id=tid,
        name=team.metadata.name,
        description=team.metadata.description or "",
        path=str(discovered.path),
        strategy=team.spec.strategy,
        model=team.spec.model.model_dump(),
        personas=personas,
        guardrails=team.spec.guardrails.model_dump(),
        handoff_max_chars=team.spec.handoff_max_chars,
        shared_memory=team.spec.shared_memory.model_dump(),
        shared_documents=team.spec.shared_documents.model_dump(),
        tools=shared_tools,
        observability=team.spec.observability.model_dump() if team.spec.observability else None,
        features=_team_features(team.spec),
    )


# -- Endpoints -----------------------------------------------------------------


@router.get("")
async def list_teams(
    cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> list[TeamSummary]:
    return [_summary_from(tid, d) for tid, d in cache.all().items()]


@router.get("/{team_id}")
async def get_team(
    team_id: str,
    cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> TeamDetail:
    discovered = cache.get(team_id)
    if discovered is None:
        raise HTTPException(404, detail="Team not found")
    if discovered.error or discovered.team is None:
        raise HTTPException(
            422,
            detail=discovered.error or "Team failed to load",
        )
    return _detail_from(team_id, discovered)


@router.get("/{team_id}/yaml")
async def get_team_yaml(
    team_id: str,
    cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> dict:
    discovered = cache.get(team_id)
    if discovered is None:
        raise HTTPException(404, detail="Team not found")
    yaml_text = await asyncio.to_thread(discovered.path.read_text)
    return {"yaml": yaml_text, "path": str(discovered.path)}


@router.put("/{team_id}/yaml")
async def save_team_yaml(
    team_id: str,
    body: TeamYamlSaveRequest,
    cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> TeamYamlSaveResponse:
    discovered = cache.get(team_id)
    if discovered is None:
        raise HTTPException(404, detail="Team not found")

    from initrunner.services.team_builder import validate_team_yaml

    _, issues = await asyncio.to_thread(validate_team_yaml, body.yaml_text)
    errors = [f"{i.field}: {i.message}" for i in issues if i.severity == "error"]

    if errors:
        return TeamYamlSaveResponse(
            path=str(discovered.path),
            valid=False,
            issues=errors,
        )

    path = discovered.path
    await asyncio.to_thread(path.write_text, body.yaml_text)
    cache.refresh_one(team_id, path)

    return TeamYamlSaveResponse(
        path=str(path),
        valid=True,
    )


@router.post("/{team_id}/run/stream")
async def stream_team_run(
    team_id: str,
    body: TeamRunRequest,
    cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> StreamingResponse:
    discovered = cache.get(team_id)
    if discovered is None:
        raise HTTPException(404, detail="Team not found")
    if discovered.error or discovered.team is None:
        raise HTTPException(422, detail=discovered.error or "Team failed to load")

    from initrunner.dashboard.streaming import stream_team_run_sse

    return StreamingResponse(
        stream_team_run_sse(
            discovered.team,
            discovered.path.parent,
            body.prompt,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
