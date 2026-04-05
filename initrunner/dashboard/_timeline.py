"""Shared timeline response builder for agents, flows, and teams."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from initrunner.dashboard.pricing import estimate_cost
from initrunner.dashboard.schemas import (
    TimelineCostResponse,
    TimelineEntryResponse,
    TimelineResponse,
    TimelineStatsResponse,
)


def build_timeline_response(
    rows: list[dict],
    stats_dict: dict,
) -> TimelineResponse:
    """Build a TimelineResponse from audit query results.

    Cost is estimated per-row from stored ``model`` and ``provider`` columns.
    Rows with ``model="multi"`` or missing provider are not priced.
    """
    entries: list[TimelineEntryResponse] = []
    total_cost = 0.0

    for row in rows:
        end_time_str = row["timestamp"]
        dur = row["duration_ms"]
        try:
            end_dt = datetime.fromisoformat(end_time_str)
            start_dt = end_dt - timedelta(milliseconds=dur)
            start_time_str = start_dt.isoformat()
        except (ValueError, TypeError):
            start_time_str = end_time_str

        cost = None
        row_model = row.get("model")
        row_provider = row.get("provider")
        if row_model and row_provider and row_model != "multi" and row_provider != "multi":
            cost_dict = estimate_cost(row["tokens_in"], row["tokens_out"], row_model, row_provider)
            if cost_dict:
                cost = TimelineCostResponse(total_cost_usd=cost_dict["total_cost_usd"])
                total_cost += cost_dict["total_cost_usd"]

        metadata = None
        if row.get("trigger_metadata"):
            try:
                metadata = json.loads(row["trigger_metadata"])
            except (ValueError, TypeError):
                pass

        entries.append(
            TimelineEntryResponse(
                run_id=row["run_id"],
                start_time=start_time_str,
                end_time=end_time_str,
                duration_ms=dur,
                status="success" if row["success"] else "error",
                trigger_type=row.get("trigger_type"),
                trigger_metadata=metadata,
                tokens_in=row["tokens_in"],
                tokens_out=row["tokens_out"],
                total_tokens=row["total_tokens"],
                tool_calls=row["tool_calls"],
                cost=cost,
            )
        )

    stats = TimelineStatsResponse(
        **stats_dict,
        total_cost_usd=round(total_cost, 6) if total_cost > 0 else None,
    )
    return TimelineResponse(entries=entries, stats=stats)
