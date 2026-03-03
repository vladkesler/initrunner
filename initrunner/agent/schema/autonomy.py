"""Autonomous agent execution configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CompactionConfig(BaseModel):
    """Configuration for LLM-driven conversation history compaction."""

    enabled: bool = False
    threshold: int = Field(default=30, ge=1)
    tail_messages: int = Field(default=6, ge=1)
    model_override: str | None = None
    summary_prefix: str = "[CONVERSATION HISTORY SUMMARY]\n"


class AutonomyConfig(BaseModel):
    """Configuration for autonomous agent execution."""

    continuation_prompt: str = (
        "Continue working on the task. Review your progress so far and "
        "decide your next step. If you have completed the task, call the "
        "finish_task tool with a summary."
    )
    max_history_messages: int = 40
    max_plan_steps: int = 20
    iteration_delay_seconds: float = 0
    max_no_tool_call_iterations: int = 2
    max_scheduled_per_run: int = 3
    max_scheduled_total: int = 50
    max_schedule_delay_seconds: int = 86400  # 24h
    compaction: CompactionConfig = CompactionConfig()
