"""Cost analytics service -- queries audit data and applies pricing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentCostEntry:
    agent_name: str
    run_count: int
    tokens_in: int
    tokens_out: int
    total_cost_usd: float | None
    avg_cost_per_run: float | None


@dataclass
class DailyCostEntry:
    date: str  # YYYY-MM-DD
    run_count: int
    total_cost_usd: float | None


@dataclass
class ModelCostEntry:
    model: str
    provider: str
    run_count: int
    tokens_in: int
    tokens_out: int
    total_cost_usd: float | None


@dataclass
class CostReport:
    entries: list[AgentCostEntry]
    total_cost_usd: float | None  # None if any entry unpriceable
    total_runs: int
    period_start: str | None
    period_end: str | None


@dataclass
class CostSummary:
    today: float | None
    this_week: float | None
    this_month: float | None
    all_time: float | None
    top_agents: list[AgentCostEntry]
    daily_trend: list[DailyCostEntry]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _price_group(row: dict) -> float | None:
    """Estimate USD cost for one aggregate group. Returns None if unpriceable."""
    from initrunner.pricing import estimate_cost

    result = estimate_cost(row["tokens_in"], row["tokens_out"], row["model"], row["provider"])
    return result["total_cost_usd"] if result else None


def _sum_costs(costs: list[float | None]) -> float | None:
    """Sum costs with strict N/A semantics: any None makes the total None."""
    if any(c is None for c in costs):
        return None
    return round(sum(c for c in costs if c is not None), 6)


def _agent_entries_from_rows(rows: list[dict]) -> list[AgentCostEntry]:
    """Build AgentCostEntry list, merging rows that share the same agent name.

    A single agent may appear in multiple rows if it used different models.
    """
    from collections import defaultdict

    by_agent: dict[str, dict] = defaultdict(
        lambda: {"run_count": 0, "tokens_in": 0, "tokens_out": 0, "costs": []}
    )
    for row in rows:
        a = by_agent[row["agent_name"]]
        a["run_count"] += row["run_count"]
        a["tokens_in"] += row["tokens_in"]
        a["tokens_out"] += row["tokens_out"]
        a["costs"].append(_price_group(row))

    entries = []
    for name, data in by_agent.items():
        total = _sum_costs(data["costs"])
        entries.append(
            AgentCostEntry(
                agent_name=name,
                run_count=data["run_count"],
                tokens_in=data["tokens_in"],
                tokens_out=data["tokens_out"],
                total_cost_usd=total,
                avg_cost_per_run=(
                    round(total / data["run_count"], 6)
                    if total is not None and data["run_count"]
                    else None
                ),
            )
        )
    # Sort by cost descending (None last)
    entries.sort(key=lambda e: (e.total_cost_usd is None, -(e.total_cost_usd or 0)))
    return entries


def _daily_entries_from_rows(rows: list[dict]) -> list[DailyCostEntry]:
    """Build DailyCostEntry list, merging rows that share the same date."""
    from collections import defaultdict

    by_date: dict[str, dict] = defaultdict(lambda: {"run_count": 0, "costs": []})
    for row in rows:
        d = by_date[row["date"]]
        d["run_count"] += row["run_count"]
        d["costs"].append(_price_group(row))

    entries = []
    for date, data in sorted(by_date.items()):
        entries.append(
            DailyCostEntry(
                date=date,
                run_count=data["run_count"],
                total_cost_usd=_sum_costs(data["costs"]),
            )
        )
    return entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def cost_report_sync(
    *,
    agent_name: str | None = None,
    since: str | None = None,
    until: str | None = None,
    audit_db: Path | None = None,
) -> CostReport:
    """Cost breakdown by agent for a time period."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        return CostReport(
            entries=[],
            total_cost_usd=None,
            total_runs=0,
            period_start=since,
            period_end=until,
        )

    with _AuditLogger(db_path) as logger:
        rows = logger.cost_by_agent(agent_name=agent_name, since=since, until=until)

    entries = _agent_entries_from_rows(rows)
    total_runs = sum(e.run_count for e in entries)
    all_costs = [e.total_cost_usd for e in entries]
    return CostReport(
        entries=entries,
        total_cost_usd=_sum_costs(all_costs),
        total_runs=total_runs,
        period_start=since,
        period_end=until,
    )


def cost_by_model_sync(
    *,
    since: str | None = None,
    until: str | None = None,
    audit_db: Path | None = None,
) -> list[ModelCostEntry]:
    """Cost breakdown by model/provider."""
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        return []

    with _AuditLogger(db_path) as logger:
        rows = logger.cost_by_model(since=since, until=until)

    return [
        ModelCostEntry(
            model=row["model"],
            provider=row["provider"],
            run_count=row["run_count"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            total_cost_usd=_price_group(row),
        )
        for row in rows
    ]


def cost_summary_sync(
    *,
    audit_db: Path | None = None,
) -> CostSummary:
    """Overall cost summary: today, this week, this month, all-time, top agents, daily trend."""
    from datetime import UTC, datetime

    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    db_path = audit_db or DEFAULT_DB_PATH
    if not db_path.exists():
        return CostSummary(
            today=None,
            this_week=None,
            this_month=None,
            all_time=None,
            top_agents=[],
            daily_trend=[],
        )

    from datetime import timedelta

    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (
        (now - timedelta(days=now.weekday()))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    trend_start = (now - timedelta(days=30)).isoformat()

    with _AuditLogger(db_path) as logger:
        today_rows = logger.cost_by_day(since=today_start)
        week_rows = logger.cost_by_day(since=week_start)
        month_rows = logger.cost_by_day(since=month_start)
        all_rows = logger.cost_by_agent()
        trend_rows = logger.cost_by_day(since=trend_start)

    def _period_cost(rows: list[dict]) -> float | None:
        entries = _daily_entries_from_rows(rows)
        costs = [e.total_cost_usd for e in entries]
        return _sum_costs(costs) if costs else None

    top = _agent_entries_from_rows(all_rows)[:5]

    return CostSummary(
        today=_period_cost(today_rows),
        this_week=_period_cost(week_rows),
        this_month=_period_cost(month_rows),
        all_time=(
            _sum_costs([e.total_cost_usd for e in _agent_entries_from_rows(all_rows)])
            if all_rows
            else None
        ),
        top_agents=top,
        daily_trend=_daily_entries_from_rows(trend_rows),
    )


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

_TOKENS_PER_TOOL = 200
_BASELINE_USER_PROMPT_TOKENS = 200
_TOOL_CALL_OVERHEAD = 600  # 100 call args + 500 result per call
_TYPICAL_OUTPUT_FRACTION = 0.3


@dataclass
class RoleCostEstimate:
    model: str
    provider: str
    model_resolved: bool
    estimated_input_tokens: int
    estimated_output_tokens_typical: int
    estimated_output_tokens_max: int
    per_run_typical: float | None
    per_run_max: float | None
    daily_estimate: float | None
    monthly_estimate: float | None
    trigger_runs_per_day: float | None
    assumptions: list[str]


def estimate_role_cost_sync(
    role_path: Path,
    *,
    prompt_tokens: int | None = None,
) -> RoleCostEstimate:
    """Estimate per-run cost from a role YAML file.

    Uses ``role.spec.role`` (raw system prompt) only -- skills are excluded.
    If the model is unresolved, USD projections are skipped.
    """
    from initrunner.agent.loader import load_role
    from initrunner.pricing import estimate_cost

    role = load_role(role_path)
    assumptions: list[str] = []

    # Model resolution
    model_cfg = role.spec.model
    model_resolved = model_cfg.is_resolved() if model_cfg else False
    model_name = model_cfg.name if model_cfg else ""
    provider = model_cfg.provider if model_cfg else ""

    if not model_resolved:
        assumptions.append("Model unresolved at parse time; USD estimates unavailable")

    # Input tokens
    system_prompt = role.spec.role or ""
    system_tokens = len(system_prompt) // 4
    tool_count = len(role.spec.tools)
    tool_desc_tokens = tool_count * _TOKENS_PER_TOOL
    user_tokens = prompt_tokens if prompt_tokens is not None else _BASELINE_USER_PROMPT_TOKENS
    if prompt_tokens is None:
        assumptions.append(f"User prompt estimated at {_BASELINE_USER_PROMPT_TOKENS} tokens")

    max_tool_calls = role.spec.guardrails.max_tool_calls
    tool_call_tokens = max_tool_calls * _TOOL_CALL_OVERHEAD

    input_tokens = system_tokens + tool_desc_tokens + user_tokens + tool_call_tokens
    assumptions.append(f"System prompt: ~{system_tokens} tokens (len/4)")
    assumptions.append(f"{tool_count} tools, {max_tool_calls} max calls")
    assumptions.append("Conservative: excludes skill content")

    # Output tokens
    max_output = model_cfg.max_tokens if model_cfg else 4096
    typical_output = int(max_output * _TYPICAL_OUTPUT_FRACTION)
    assumptions.append(f"Output: {typical_output} typical, {max_output} max")

    # Pricing
    per_run_typical: float | None = None
    per_run_max: float | None = None

    if model_resolved:
        typical_result = estimate_cost(input_tokens, typical_output, model_name, provider)
        max_result = estimate_cost(input_tokens, max_output, model_name, provider)
        per_run_typical = typical_result["total_cost_usd"] if typical_result else None
        per_run_max = max_result["total_cost_usd"] if max_result else None
        if per_run_typical is None:
            assumptions.append(f"No pricing data for {provider}:{model_name}")

    # Trigger projections
    runs_per_day: float | None = None
    daily_estimate: float | None = None
    monthly_estimate: float | None = None

    if role.spec.triggers:
        from initrunner.agent.schema.triggers import CronTriggerConfig, HeartbeatTriggerConfig

        total_runs_per_day = 0.0
        for trigger in role.spec.triggers:
            if isinstance(trigger, CronTriggerConfig):
                try:
                    from croniter import croniter  # type: ignore[import-not-found]

                    cron = croniter(trigger.schedule)
                    # Count firings in a 24h window
                    from datetime import UTC, datetime, timedelta

                    start = datetime.now(UTC)
                    end = start + timedelta(days=1)
                    count = 0
                    while True:
                        nxt = cron.get_next(datetime)
                        if nxt > end:
                            break
                        count += 1
                    total_runs_per_day += count
                except Exception:
                    assumptions.append(f"Could not parse cron schedule: {trigger.schedule}")
            elif isinstance(trigger, HeartbeatTriggerConfig):
                total_runs_per_day += 86400 / trigger.interval_seconds

        if total_runs_per_day > 0:
            runs_per_day = round(total_runs_per_day, 2)
            assumptions.append(f"~{runs_per_day} trigger firings/day")
            if per_run_typical is not None:
                daily_estimate = round(per_run_typical * total_runs_per_day, 6)
                monthly_estimate = round(daily_estimate * 30, 6)

    return RoleCostEstimate(
        model=model_name,
        provider=provider,
        model_resolved=model_resolved,
        estimated_input_tokens=input_tokens,
        estimated_output_tokens_typical=typical_output,
        estimated_output_tokens_max=max_output,
        per_run_typical=per_run_typical,
        per_run_max=per_run_max,
        daily_estimate=daily_estimate,
        monthly_estimate=monthly_estimate,
        trigger_runs_per_day=runs_per_day,
        assumptions=assumptions,
    )
