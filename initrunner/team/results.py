"""Result dataclasses and aggregation for team mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.executor import RunResult


@dataclass
class StepMetadata:
    """Per-step metadata for structured round tracking."""

    step_kind: str = "persona"  # "persona" | "synthesis"
    round_num: int | None = None
    max_rounds: int | None = None


@dataclass
class TeamResult:
    team_run_id: str
    team_name: str
    agent_results: list[RunResult] = field(default_factory=list)
    agent_names: list[str] = field(default_factory=list)
    step_metadata: list[StepMetadata] = field(default_factory=list)
    final_output: str = ""
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_tokens: int = 0
    total_tool_calls: int = 0
    total_duration_ms: int = 0
    success: bool = True
    error: str | None = None


def accumulate_result(
    result: TeamResult,
    persona_name: str,
    run_result: RunResult,
    metadata: StepMetadata | None = None,
) -> None:
    """Add a persona's run result to the team result."""
    result.agent_results.append(run_result)
    result.agent_names.append(persona_name)
    result.step_metadata.append(metadata or StepMetadata())
    result.total_tokens_in += run_result.tokens_in
    result.total_tokens_out += run_result.tokens_out
    result.total_tokens += run_result.total_tokens
    result.total_tool_calls += run_result.tool_calls
    result.total_duration_ms += run_result.duration_ms
