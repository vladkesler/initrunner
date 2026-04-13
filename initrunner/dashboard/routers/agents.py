"""Agent discovery and detail routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException  # type: ignore[import-not-found]

from initrunner.dashboard.deps import RoleCache, SkillCache, get_role_cache, get_skill_cache
from initrunner.dashboard.schemas import (
    AgentDetail,
    AgentSummary,
    BudgetProgressResponse,
    DeleteResponse,
    ItemSummary,
    SkillRef,
    TimelineResponse,
    TriggerStatResponse,
)

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _capability_summaries(specs: list) -> list[ItemSummary]:
    """Build dashboard summaries from capability NamedSpec entries."""
    result = []
    for spec in specs:
        name = spec.name
        args = spec.arguments
        if args is None:
            summary = name
            config: dict = {}
        elif isinstance(args, dict):
            parts = [f"{k}={v}" for k, v in args.items()]
            summary = f"{name}: {', '.join(parts)}"
            config = args
        else:
            # tuple -- single positional arg
            summary = f"{name}: {args[0]}"
            config = {"value": args[0]}
        result.append(ItemSummary(type=name, summary=summary, config=config))
    return result


def _summary_from(role_id: str, discovered) -> AgentSummary:
    """Build an AgentSummary from a DiscoveredRole."""
    if discovered.error or discovered.role is None:
        return AgentSummary(
            id=role_id,
            name=discovered.path.stem,
            description="",
            tags=[],
            provider="",
            model="",
            features=[],
            path=str(discovered.path),
            error=discovered.error,
        )
    role = discovered.role
    meta = role.metadata
    spec = role.spec
    return AgentSummary(
        id=role_id,
        name=meta.name,
        description=meta.description or "",
        tags=list(meta.tags or []),
        provider=spec.model.provider if spec.model else "",
        model=spec.model.name if spec.model else "",
        features=list(spec.features),
        path=str(discovered.path),
    )


@router.get("")
async def list_agents(
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> list[AgentSummary]:
    roles = role_cache.all()
    return [_summary_from(rid, dr) for rid, dr in roles.items()]


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> AgentSummary:
    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _summary_from(agent_id, dr)


def _check_provider(discovered) -> str | None:
    """Check provider SDK and API key availability, mirroring runtime."""
    import os

    from initrunner._compat import require_provider
    from initrunner.agent.loader import _load_dotenv
    from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT as _PROVIDER_API_KEY_ENVS

    spec = discovered.role.spec
    if not spec.model or not spec.model.name:
        return None  # model will be auto-detected at runtime
    _load_dotenv(discovered.path.parent)
    try:
        require_provider(spec.model.provider)
    except RuntimeError as e:
        return str(e)
    env_var = spec.model.api_key_env or _PROVIDER_API_KEY_ENVS.get(spec.model.provider)
    if env_var and not os.environ.get(env_var):
        return f"API key not set. Export {env_var} or add it to ~/.initrunner/.env"
    return None


def _detail_from(role_id: str, discovered, skill_refs: list[SkillRef] | None = None) -> AgentDetail:
    """Build an AgentDetail from a DiscoveredRole."""
    if discovered.error or discovered.role is None:
        from initrunner.agent.schema.base import ModelConfig
        from initrunner.agent.schema.guardrails import Guardrails
        from initrunner.agent.schema.output import OutputConfig

        return AgentDetail(
            id=role_id,
            name=discovered.path.stem,
            description="",
            tags=[],
            path=str(discovered.path),
            error=discovered.error,
            model=ModelConfig(provider="unknown", name="unknown").model_dump(),
            output=OutputConfig().model_dump(),
            guardrails=Guardrails().model_dump(),
        )
    role = discovered.role
    meta = role.metadata
    spec = role.spec
    return AgentDetail(
        id=role_id,
        name=meta.name,
        description=meta.description or "",
        tags=list(meta.tags or []),
        path=str(discovered.path),
        author=meta.author or "",
        team=meta.team or "",
        version=meta.version or "",
        model=spec.model.model_dump() if spec.model and spec.model.name else {},
        output=spec.output.model_dump(),
        guardrails=spec.guardrails.model_dump(),
        memory=spec.memory.model_dump() if spec.memory else None,
        ingest=spec.ingest.model_dump() if spec.ingest else None,
        reasoning=spec.reasoning.model_dump() if spec.reasoning else None,
        autonomy=spec.autonomy.model_dump() if spec.autonomy else None,
        tools=[
            ItemSummary(type=t.type, summary=t.summary(), config=t.model_dump(exclude={"type"}))
            for t in spec.tools
        ],
        triggers=[ItemSummary(type=t.type, summary=t.summary()) for t in spec.triggers],
        sinks=[ItemSummary(type=t.type, summary=t.summary()) for t in spec.sinks],
        capabilities=_capability_summaries(spec.capabilities),
        skills=list(spec.skills),
        skill_refs=skill_refs or [SkillRef(name=s) for s in spec.skills],
        features=list(spec.features),
        tool_search=spec.tool_search.model_dump() if spec.tool_search.enabled else None,
        security=spec.security.effective_label,
        provider_warning=_check_provider(discovered),
    )


@router.get("/{agent_id}/detail")
async def get_agent_detail(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    skill_cache: Annotated[SkillCache, Depends(get_skill_cache)],
) -> AgentDetail:
    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    skill_refs = _resolve_skill_refs(dr, skill_cache)
    return _detail_from(agent_id, dr, skill_refs=skill_refs)


def _resolve_skill_refs(discovered, skill_cache: SkillCache) -> list[SkillRef]:
    """Resolve agent skill refs to SkillRef objects with cache IDs."""
    if discovered.role is None or not discovered.role.spec.skills:
        return []

    from initrunner.agent.skills import SkillLoadError, _resolve_skill_path

    # Build a path -> cache ID lookup
    path_to_id: dict[str, str] = {}
    for sid, skill in skill_cache.all().items():
        path_to_id[str(skill.path.resolve())] = sid

    refs: list[SkillRef] = []
    for raw_ref in discovered.role.spec.skills:
        try:
            path = _resolve_skill_path(raw_ref, discovered.path.parent, None)
            cache_id = path_to_id.get(str(path))
            refs.append(SkillRef(name=raw_ref, skill_id=cache_id))
        except SkillLoadError:
            refs.append(SkillRef(name=raw_ref, skill_id=None))

    return refs


@router.get("/{agent_id}/yaml")
async def get_agent_yaml(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> dict[str, str]:
    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        content = dr.path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read file: {exc}") from exc
    return {"yaml": content, "path": str(dr.path)}


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> DeleteResponse:
    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    path = dr.path
    try:
        await asyncio.to_thread(path.unlink, True)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Cannot delete file: {exc}") from exc
    role_cache.evict(agent_id)
    return DeleteResponse(id=agent_id, path=str(path))


@router.get("/{agent_id}/trigger-stats")
async def get_trigger_stats(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> list[TriggerStatResponse]:
    from initrunner.agent.schema.triggers import CronTriggerConfig, HeartbeatTriggerConfig
    from initrunner.config import get_audit_db_path
    from initrunner.services.operations import (
        next_cron_check,
        next_heartbeat_check,
        trigger_stats_sync,
    )

    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if dr.role is None:
        return []

    triggers = dr.role.spec.triggers
    if not triggers:
        return []

    stats_list = await asyncio.to_thread(
        trigger_stats_sync,
        agent_name=dr.role.metadata.name,
        audit_db=get_audit_db_path(),
    )
    stats_by_type = {s.trigger_type: s for s in stats_list}

    results: list[TriggerStatResponse] = []
    for cfg in triggers:
        s = stats_by_type.get(cfg.type)

        check_time: str | None = None
        if isinstance(cfg, CronTriggerConfig):
            check_time = next_cron_check(cfg.schedule)
        elif isinstance(cfg, HeartbeatTriggerConfig):
            last = s.last_fire_time if s else None
            check_time = next_heartbeat_check(last, cfg.interval_seconds)

        results.append(
            TriggerStatResponse(
                trigger_type=cfg.type,
                summary=cfg.summary(),
                fire_count=s.fire_count if s else 0,
                success_count=s.success_count if s else 0,
                fail_count=s.fail_count if s else 0,
                last_fire_time=s.last_fire_time if s else None,
                avg_duration_ms=s.avg_duration_ms if s else 0,
                last_error=s.last_error if s else None,
                next_check_time=check_time,
            )
        )
    return results


@router.get("/{agent_id}/timeline")
async def get_timeline(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    since: str | None = None,
    until: str | None = None,
    limit: int = 500,
) -> TimelineResponse:
    from datetime import timedelta

    from initrunner.config import get_audit_db_path
    from initrunner.dashboard._timeline import build_timeline_response
    from initrunner.dashboard.schemas import TimelineStatsResponse

    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if dr.role is None:
        return TimelineResponse(entries=[], stats=TimelineStatsResponse())

    agent_name = dr.role.metadata.name

    now = datetime.now(UTC)
    if until is None:
        until = now.isoformat()
    if since is None:
        since = (now - timedelta(hours=24)).isoformat()

    from initrunner.audit.logger import AuditLogger

    def _query():
        al = AuditLogger(get_audit_db_path())
        try:
            return (
                al.timeline_query(agent_name=agent_name, since=since, until=until, limit=limit),
                al.timeline_stats(agent_name=agent_name, since=since, until=until),
            )
        finally:
            al.close()

    rows, stats_dict = await asyncio.to_thread(_query)
    return build_timeline_response(rows, stats_dict)


@router.get("/{agent_id}/budget-progress")
async def get_budget_progress(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> BudgetProgressResponse:
    from initrunner.audit.logger import AuditLogger
    from initrunner.config import get_audit_db_path
    from initrunner.dashboard.schemas import BudgetGauge
    from initrunner.runner.budget import BudgetSnapshot

    dr = role_cache.get(agent_id)
    if dr is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if dr.role is None:
        return BudgetProgressResponse()

    guardrails = dr.role.spec.guardrails
    tz = guardrails.budget_timezone

    def _load():
        al = AuditLogger(get_audit_db_path())
        try:
            return al.load_budget_state(dr.role.metadata.name)  # type: ignore[union-attr]
        finally:
            al.close()

    saved = await asyncio.to_thread(_load)

    if saved is not None:
        snap = BudgetSnapshot.from_dict(saved).with_resets(tz)
        gauges = snap.to_progress(guardrails)
    else:
        # No persisted state -- build zero-consumed snapshot for gauge computation
        snap = BudgetSnapshot(
            total_consumed=0,
            daily_consumed=0,
            daily_cost_consumed=0.0,
            weekly_cost_consumed=0.0,
            last_reset_date="",
            last_weekly_reset="",
        )
        gauges = snap.to_progress(guardrails)

    # Convert raw dicts to BudgetGauge models (or None)
    def _to_gauge(d: dict | None) -> BudgetGauge | None:
        return BudgetGauge(**d) if d else None

    return BudgetProgressResponse(
        daily_tokens=_to_gauge(gauges["daily_tokens"]),
        daily_cost=_to_gauge(gauges["daily_cost"]),
        weekly_cost=_to_gauge(gauges["weekly_cost"]),
        lifetime_tokens=_to_gauge(gauges["lifetime_tokens"]),
        timezone=tz,
        last_updated=saved.get("updated_at") if saved else None,
    )
