"""Audit records and statistics models."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "AuditRecordResponse",
    "AuditStatsResponse",
    "TopAgentResponse",
    "TriggerStatResponse",
]


class AuditRecordResponse(BaseModel):
    run_id: str
    agent_name: str
    timestamp: str
    user_prompt: str
    model: str
    provider: str
    output: str
    tokens_in: int
    tokens_out: int
    total_tokens: int
    tool_calls: int
    duration_ms: int
    success: bool
    error: str | None = None
    trigger_type: str | None = None
    cost_usd: float | None = None


class TopAgentResponse(BaseModel):
    name: str
    count: int
    avg_duration_ms: int


class AuditStatsResponse(BaseModel):
    total_runs: int
    success_rate: float
    total_tokens: int
    avg_duration_ms: int
    top_agents: list[TopAgentResponse]


class TriggerStatResponse(BaseModel):
    """Per-trigger operational stats for the agent detail page."""

    trigger_type: str
    summary: str
    fire_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    last_fire_time: str | None = None
    avg_duration_ms: int = 0
    last_error: str | None = None
    next_check_time: str | None = None
