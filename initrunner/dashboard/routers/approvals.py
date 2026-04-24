"""Approval queue + resolve routes for the dashboard.

These endpoints sit alongside the OpenAI-compatible ``/v1/approvals/{run_id}``
route on ``initrunner/server/app.py`` but serve the dashboard's own needs:
grouping by run, exposing the originating prompt, and feeding the nav badge.

All reads hit the audit SQLite directly via :class:`AuditLogger`; the resolve
path calls ``services.execution.resume_run_sync`` in-process rather than
proxying to the OpenAI-compatible server.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query  # type: ignore[import-not-found]

from initrunner.audit.logger import AuditLogger, PendingApprovalRecord
from initrunner.dashboard.schemas import (
    ApprovalsResolveRequest,
    ApprovalsResolveResponse,
    PendingCallResponse,
    PendingCountResponse,
    PendingListResponse,
    PendingRunResponse,
)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

_logger = logging.getLogger(__name__)


def _audit_logger() -> AuditLogger:
    from initrunner.config import get_audit_db_path

    return AuditLogger(get_audit_db_path())


def _parse_args(raw: str) -> dict:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_value": parsed}


def _extract_originating_prompt(message_history_json: str) -> str | None:
    """Best-effort extraction of the initial user prompt from a stored history.

    Returns the first ``UserPromptPart`` text found in the serialized
    message history, or ``None`` if parsing fails or no prompt exists.
    Never raises — the drawer can render without it.
    """
    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, UserPromptPart

        messages = ModelMessagesTypeAdapter.validate_json(message_history_json)
        for msg in messages:
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        content = part.content
                        if isinstance(content, str):
                            return content
                        if isinstance(content, list):
                            texts = [c for c in content if isinstance(c, str)]
                            return " ".join(texts) if texts else None
    except Exception:
        return None
    return None


def _group_by_run(rows: list[PendingApprovalRecord]) -> list[PendingRunResponse]:
    """Collapse a flat list of pending-approval rows into per-run groups."""
    by_run: dict[str, list[PendingApprovalRecord]] = {}
    order: list[str] = []
    for row in rows:
        if row.run_id not in by_run:
            by_run[row.run_id] = []
            order.append(row.run_id)
        by_run[row.run_id].append(row)

    groups: list[PendingRunResponse] = []
    for run_id in order:
        run_rows = by_run[run_id]
        head = run_rows[0]
        groups.append(
            PendingRunResponse(
                run_id=run_id,
                agent_name=head.agent_name,
                role_path=head.role_path,
                created_at=head.created_at,
                originating_prompt=_extract_originating_prompt(head.message_history_json),
                calls=[
                    PendingCallResponse(
                        tool_call_id=r.tool_call_id,
                        tool_name=r.tool_name,
                        arguments=_parse_args(r.arguments_json),
                    )
                    for r in run_rows
                ],
            )
        )
    return groups


@router.get("/pending", response_model=None)
async def list_pending(
    count_only: bool = Query(False, description="Return only the count."),
    limit: int = Query(200, ge=1, le=1000),
) -> PendingListResponse | PendingCountResponse:
    """List unresolved approvals. With ``count_only=1``, returns just a count."""
    logger = _audit_logger()
    try:
        rows = await asyncio.to_thread(logger.list_pending_approvals, limit=limit)
    finally:
        await asyncio.to_thread(logger.close)

    if count_only:
        return PendingCountResponse(count=len(rows))

    groups = _group_by_run(rows)
    return PendingListResponse(runs=groups, count=len(rows))


@router.get("/{run_id}", response_model=PendingRunResponse)
async def get_run(run_id: str) -> PendingRunResponse:
    """Return the pending calls + context for one paused run."""
    logger = _audit_logger()
    try:
        rows = await asyncio.to_thread(logger.load_pending_approvals, run_id)
    finally:
        await asyncio.to_thread(logger.close)

    unresolved = [r for r in rows if r.resolved_at is None]
    if not unresolved:
        raise HTTPException(
            status_code=404,
            detail=f"No unresolved approvals found for run {run_id!r}",
        )
    return _group_by_run(unresolved)[0]


@router.post("/{run_id}", response_model=ApprovalsResolveResponse)
async def resolve_run(run_id: str, req: ApprovalsResolveRequest) -> ApprovalsResolveResponse:
    """Submit decisions for a paused run and resume it in-process."""
    if not req.decisions:
        raise HTTPException(status_code=400, detail="decisions must be non-empty")
    if not all(isinstance(v, bool) for v in req.decisions.values()):
        raise HTTPException(status_code=400, detail="every decision must be a bool")

    logger = _audit_logger()
    try:
        rows = await asyncio.to_thread(logger.load_pending_approvals, run_id)
        unresolved = [r for r in rows if r.resolved_at is None]
        if not unresolved:
            raise HTTPException(
                status_code=404,
                detail=f"No unresolved approvals found for run {run_id!r}",
            )

        role_paths = {r.role_path for r in unresolved if r.role_path}
        if len(role_paths) != 1:
            raise HTTPException(
                status_code=409,
                detail="Pending rows for this run disagree on the role path",
            )
        role_path = Path(next(iter(role_paths)))
        if not role_path.exists():
            raise HTTPException(
                status_code=410,
                detail=f"Role file no longer exists at {role_path}",
            )

        from initrunner.services.execution import build_agent_sync, resume_run_sync

        role, agent = await asyncio.to_thread(build_agent_sync, role_path)
        try:
            result, new_messages = await asyncio.to_thread(
                resume_run_sync,
                agent,
                role,
                run_id,
                req.decisions,
                audit_logger=logger,
                resolved_by=req.resolved_by,
                role_path=role_path,
            )
        except ValueError as exc:
            # missing decision for some unresolved tool_call_id
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        serialized_history: str | None = None
        if result.success or result.status == "paused":
            from pydantic_ai.messages import ModelMessagesTypeAdapter

            from initrunner.agent.history import session_limits, trim_message_history

            _, max_history = session_limits(role)
            trimmed = trim_message_history(new_messages, max_history)
            serialized_history = ModelMessagesTypeAdapter.dump_json(trimmed).decode("utf-8")

        return ApprovalsResolveResponse(
            run_id=run_id,
            status=result.status,
            success=result.success,
            output=result.output,
            error=result.error,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            total_tokens=result.total_tokens,
            duration_ms=result.duration_ms,
            message_history=serialized_history,
            pending_approvals=[
                PendingCallResponse(
                    tool_call_id=p.tool_call_id,
                    tool_name=p.tool_name,
                    arguments=p.arguments,
                )
                for p in result.pending_approvals
            ],
        )
    finally:
        await asyncio.to_thread(logger.close)
