"""Pydantic response schemas for the approvals router."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PendingCallResponse(BaseModel):
    """One tool call awaiting human approval."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


class PendingRunResponse(BaseModel):
    """One paused run with every tool call awaiting approval on it.

    The dashboard queue groups by run because
    ``services.execution.resume_run_sync`` requires decisions for every
    ``tool_call_id`` in a run — partial batches are rejected.
    """

    run_id: str
    agent_name: str
    role_path: str | None
    created_at: str
    originating_prompt: str | None
    calls: list[PendingCallResponse]


class PendingListResponse(BaseModel):
    """Queue payload: grouped pending runs + total count."""

    runs: list[PendingRunResponse]
    count: int


class PendingCountResponse(BaseModel):
    """Lightweight nav-badge payload."""

    count: int


class ApprovalsResolveRequest(BaseModel):
    """Body of ``POST /api/approvals/{run_id}``: one bool per tool_call_id."""

    decisions: dict[str, bool]
    resolved_by: str | None = None


class ApprovalsResolveResponse(BaseModel):
    """Result of a resume.

    - ``status == "done"``: the run completed; ``output`` carries the result.
    - ``status == "paused"``: the model queued more approval-required calls;
      ``pending_approvals`` lists them and the caller should loop.
    """

    run_id: str
    status: str  # "done" | "paused"
    success: bool
    output: str
    error: str | None
    tokens_in: int
    tokens_out: int
    total_tokens: int
    duration_ms: int
    message_history: str | None
    pending_approvals: list[PendingCallResponse]
