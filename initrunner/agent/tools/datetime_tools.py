"""Date/time tools."""

from __future__ import annotations

from pydantic_ai.toolsets.function import FunctionToolset

from initrunner.agent.schema import DateTimeToolConfig
from initrunner.agent.tools._registry import ToolBuildContext, register_tool


@register_tool("datetime", DateTimeToolConfig)
def build_datetime_toolset(config: DateTimeToolConfig, ctx: ToolBuildContext) -> FunctionToolset:
    """Build a FunctionToolset for date/time operations."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    toolset = FunctionToolset()

    @toolset.tool
    def current_time(timezone: str = "") -> str:
        """Get the current date and time. Leave timezone empty to use the default."""
        tz_name = timezone or config.default_timezone
        try:
            tz = ZoneInfo(tz_name)
        except (KeyError, Exception):
            return f"Error: invalid timezone '{tz_name}'"
        now = datetime.now(tz)
        return f"{now.isoformat()} ({now.strftime('%A, %B %d, %Y %I:%M:%S %p %Z')})"

    @toolset.tool
    def parse_date(text: str, format: str = "") -> str:
        """Parse a date string. Leave format empty for ISO 8601 auto-detection."""
        try:
            if format:
                dt = datetime.strptime(text, format)
            else:
                dt = datetime.fromisoformat(text)
            return dt.isoformat()
        except (ValueError, TypeError):
            return f"Could not parse '{text}' — use ISO 8601 format (e.g. 2024-01-15T10:30:00)"

    return toolset
