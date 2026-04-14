"""Cost analytics API routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query  # type: ignore[import-not-found]

from initrunner.dashboard.schemas import (
    AgentCostResponse,
    CostSummaryResponse,
    DailyCostResponse,
    ModelCostResponse,
    ToolCostResponse,
)

router = APIRouter(prefix="/api/cost", tags=["cost"])


@router.get("/summary")
async def get_cost_summary() -> CostSummaryResponse:
    from initrunner.config import get_audit_db_path
    from initrunner.services.cost import cost_summary_sync

    summary = await asyncio.to_thread(cost_summary_sync, audit_db=get_audit_db_path())
    return CostSummaryResponse(
        today=summary.today,
        this_week=summary.this_week,
        this_month=summary.this_month,
        all_time=summary.all_time,
        top_agents=[
            AgentCostResponse(
                agent_name=e.agent_name,
                run_count=e.run_count,
                tokens_in=e.tokens_in,
                tokens_out=e.tokens_out,
                total_cost_usd=e.total_cost_usd,
                avg_cost_per_run=e.avg_cost_per_run,
            )
            for e in summary.top_agents
        ],
        daily_trend=[
            DailyCostResponse(
                date=d.date,
                run_count=d.run_count,
                total_cost_usd=d.total_cost_usd,
            )
            for d in summary.daily_trend
        ],
    )


@router.get("/by-agent")
async def get_cost_by_agent(
    agent_name: str | None = Query(None),
    since: str | None = Query(None, description="ISO 8601 datetime"),
    until: str | None = Query(None, description="ISO 8601 datetime"),
) -> list[AgentCostResponse]:
    from initrunner.config import get_audit_db_path
    from initrunner.services.cost import cost_report_sync

    report = await asyncio.to_thread(
        cost_report_sync,
        agent_name=agent_name,
        since=since,
        until=until,
        audit_db=get_audit_db_path(),
    )
    return [
        AgentCostResponse(
            agent_name=e.agent_name,
            run_count=e.run_count,
            tokens_in=e.tokens_in,
            tokens_out=e.tokens_out,
            total_cost_usd=e.total_cost_usd,
            avg_cost_per_run=e.avg_cost_per_run,
        )
        for e in report.entries
    ]


@router.get("/daily")
async def get_cost_daily(
    days: int = Query(30, ge=1, le=365),
    agent_name: str | None = Query(None),
) -> list[DailyCostResponse]:
    from datetime import UTC, datetime, timedelta

    from initrunner.config import get_audit_db_path

    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    # Use cost_by_day via the summary path
    from initrunner.audit.logger import AuditLogger

    db_path = get_audit_db_path()
    if not db_path.exists():
        return []

    def _query() -> list[DailyCostResponse]:
        from initrunner.services.cost import _daily_entries_from_rows

        with AuditLogger(db_path) as logger:
            rows = logger.cost_by_day(agent_name=agent_name, since=since)
        entries = _daily_entries_from_rows(rows)
        return [
            DailyCostResponse(
                date=e.date,
                run_count=e.run_count,
                total_cost_usd=e.total_cost_usd,
            )
            for e in entries
        ]

    return await asyncio.to_thread(_query)


@router.get("/by-model")
async def get_cost_by_model(
    since: str | None = Query(None, description="ISO 8601 datetime"),
    until: str | None = Query(None, description="ISO 8601 datetime"),
) -> list[ModelCostResponse]:
    from initrunner.config import get_audit_db_path
    from initrunner.services.cost import cost_by_model_sync

    entries = await asyncio.to_thread(
        cost_by_model_sync,
        since=since,
        until=until,
        audit_db=get_audit_db_path(),
    )
    return [
        ModelCostResponse(
            model=e.model,
            provider=e.provider,
            run_count=e.run_count,
            tokens_in=e.tokens_in,
            tokens_out=e.tokens_out,
            total_cost_usd=e.total_cost_usd,
        )
        for e in entries
    ]


@router.get("/by-tool")
async def get_cost_by_tool(
    agent_name: str | None = Query(None),
    since: str | None = Query(None, description="ISO 8601 datetime"),
    until: str | None = Query(None, description="ISO 8601 datetime"),
) -> list[ToolCostResponse]:
    from initrunner.config import get_audit_db_path
    from initrunner.services.cost import cost_by_tool_sync

    entries = await asyncio.to_thread(
        cost_by_tool_sync,
        agent_name=agent_name,
        since=since,
        until=until,
        audit_db=get_audit_db_path(),
    )
    return [
        ToolCostResponse(
            tool_name=e.tool_name,
            usage_count=e.usage_count,
            run_count=e.run_count,
            tokens_in=e.tokens_in,
            tokens_out=e.tokens_out,
            total_cost_usd=e.total_cost_usd,
            avg_cost_per_use=e.avg_cost_per_use,
        )
        for e in entries
    ]
