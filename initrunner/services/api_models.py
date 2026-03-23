"""Report export helper."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.executor import AutonomousResult, RunResult
    from initrunner.agent.schema.role import RoleDefinition


def export_run_report_sync(
    role: RoleDefinition,
    result: RunResult | AutonomousResult,
    prompt: str,
    output_path: Path,
    *,
    template_name: str = "default",
    dry_run: bool = False,
) -> Path:
    """Export a markdown report from a run result (sync)."""
    from initrunner.report import export_report

    return export_report(
        role, result, prompt, output_path, template_name=template_name, dry_run=dry_run
    )
