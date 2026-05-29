"""Audit log query routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query  # type: ignore[import-not-found]

from initrunner.dashboard.schemas import (
    AuditRecordResponse,
    AuditRunDetailResponse,
    AuditStatsResponse,
    TopAgentResponse,
)

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def query_audit(
    agent_name: str | None = Query(None),
    run_id: str | None = Query(None),
    trigger_type: str | None = Query(None),
    since: str | None = Query(None, description="ISO 8601 datetime"),
    until: str | None = Query(None, description="ISO 8601 datetime"),
    limit: int = Query(50, ge=1, le=500),
    exclude_trigger_types: list[str] | None = Query(None),  # noqa: B008
) -> list[AuditRecordResponse]:
    from initrunner.config import get_audit_db_path
    from initrunner.services.operations import query_audit_sync

    records = await asyncio.to_thread(
        query_audit_sync,
        agent_name=agent_name,
        run_id=run_id,
        trigger_type=trigger_type,
        since=since,
        until=until,
        limit=limit,
        audit_db=get_audit_db_path(),
        exclude_trigger_types=exclude_trigger_types,
    )

    from initrunner.pricing import estimate_cost

    def _cost(r: object) -> float | None:
        result = estimate_cost(r.tokens_in, r.tokens_out, r.model, r.provider)  # type: ignore[union-attr]
        return result["total_cost_usd"] if result else None

    return [
        AuditRecordResponse(
            run_id=r.run_id,
            agent_name=r.agent_name,
            timestamp=r.timestamp,
            user_prompt=r.user_prompt,
            model=r.model,
            provider=r.provider,
            output=r.output,
            tokens_in=r.tokens_in,
            tokens_out=r.tokens_out,
            total_tokens=r.total_tokens,
            thinking_tokens=r.thinking_tokens,
            reasoning_tokens=r.reasoning_tokens,
            tool_calls=r.tool_calls,
            duration_ms=r.duration_ms,
            success=r.success,
            error=r.error,
            trigger_type=r.trigger_type,
            cost_usd=_cost(r),
        )
        for r in records
    ]


@router.get("/stats")
async def audit_stats(
    agent_name: str | None = Query(None),
    since: str | None = Query(None, description="ISO 8601 datetime"),
    until: str | None = Query(None, description="ISO 8601 datetime"),
) -> AuditStatsResponse:
    from initrunner.config import get_audit_db_path
    from initrunner.services.operations import audit_stats_sync

    stats = await asyncio.to_thread(
        audit_stats_sync,
        agent_name=agent_name,
        since=since,
        until=until,
        audit_db=get_audit_db_path(),
    )
    return AuditStatsResponse(
        total_runs=stats.total_runs,
        success_rate=stats.success_rate,
        total_tokens=stats.total_tokens,
        avg_duration_ms=stats.avg_duration_ms,
        top_agents=[
            TopAgentResponse(name=a.name, count=a.count, avg_duration_ms=a.avg_duration_ms)
            for a in stats.top_agents
        ],
    )


def _parse_json_list(raw: str | None) -> list[dict] | None:
    """Decode a JSON-encoded list, returning None for empty or malformed input."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, list) else None


@router.get("/{run_id}")
async def audit_run_detail(run_id: str) -> AuditRunDetailResponse:
    """Drill-down for a single run: base record plus parsed timeline and judge verdicts.

    Registered after ``/stats`` so FastAPI matches the literal path before the converter.
    """
    from initrunner.config import get_audit_db_path
    from initrunner.services.operations import query_audit_sync

    records = await asyncio.to_thread(
        query_audit_sync,
        run_id=run_id,
        limit=1,
        audit_db=get_audit_db_path(),
    )
    if not records:
        raise HTTPException(status_code=404, detail="Run not found")

    r = records[0]

    from initrunner.pricing import estimate_cost

    cost = estimate_cost(r.tokens_in, r.tokens_out, r.model, r.provider)
    cost_usd = cost["total_cost_usd"] if cost else None

    return AuditRunDetailResponse(
        run_id=r.run_id,
        agent_name=r.agent_name,
        timestamp=r.timestamp,
        user_prompt=r.user_prompt,
        model=r.model,
        provider=r.provider,
        output=r.output,
        tokens_in=r.tokens_in,
        tokens_out=r.tokens_out,
        total_tokens=r.total_tokens,
        thinking_tokens=r.thinking_tokens,
        reasoning_tokens=r.reasoning_tokens,
        tool_calls=r.tool_calls,
        duration_ms=r.duration_ms,
        success=r.success,
        error=r.error,
        trigger_type=r.trigger_type,
        cost_usd=cost_usd,
        event_timeline=_parse_json_list(r.event_timeline_json),
        judge_verdicts=_parse_json_list(r.judge_verdicts),
    )
