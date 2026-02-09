"""Audit log query endpoints."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query, Request

from initrunner.api.models import AuditListResponse, AuditRecordResponse
from initrunner.services import query_audit_sync

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
async def list_audit_records(
    request: Request,
    agent_name: Annotated[str | None, Query()] = None,
    since: Annotated[str | None, Query(description="ISO timestamp")] = None,
    until: Annotated[str | None, Query(description="ISO timestamp")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    """Query audit trail records with optional filters."""
    audit_logger = getattr(request.app.state, "audit_logger", None)
    records = await asyncio.to_thread(
        query_audit_sync,
        agent_name=agent_name,
        since=since,
        until=until,
        limit=limit,
        audit_logger=audit_logger,
    )

    return AuditListResponse(
        records=[
            AuditRecordResponse(
                id=r.run_id,
                agent_name=r.agent_name,
                run_id=r.run_id,
                prompt=r.user_prompt,
                output=r.output,
                success=r.success,
                error=r.error,
                tokens_in=r.tokens_in,
                tokens_out=r.tokens_out,
                total_tokens=r.total_tokens,
                tool_calls=r.tool_calls,
                duration_ms=r.duration_ms,
                timestamp=r.timestamp,
                trigger_type=r.trigger_type,
            )
            for r in records
        ]
    )
