"""Cost analytics models."""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "AgentCostResponse",
    "CostSummaryResponse",
    "DailyCostResponse",
    "ModelCostResponse",
]


class AgentCostResponse(BaseModel):
    agent_name: str
    run_count: int
    tokens_in: int
    tokens_out: int
    total_cost_usd: float | None
    avg_cost_per_run: float | None


class DailyCostResponse(BaseModel):
    date: str
    run_count: int
    total_cost_usd: float | None


class CostSummaryResponse(BaseModel):
    today: float | None
    this_week: float | None
    this_month: float | None
    all_time: float | None
    top_agents: list[AgentCostResponse]
    daily_trend: list[DailyCostResponse]


class ModelCostResponse(BaseModel):
    model: str
    provider: str
    run_count: int
    tokens_in: int
    tokens_out: int
    total_cost_usd: float | None
