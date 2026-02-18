"""Report generation from agent run results."""

from __future__ import annotations

import importlib.resources
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Template

if TYPE_CHECKING:
    from initrunner.agent.executor import AutonomousResult, RunResult
    from initrunner.agent.prompt import UserPrompt
    from initrunner.agent.schema.role import RoleDefinition

BUILT_IN_TEMPLATES = ("default", "pr-review", "changelog", "ci-fix")


@dataclass
class ReportContext:
    agent_name: str
    model: str
    run_id: str
    prompt: str
    output: str
    tokens_in: int
    tokens_out: int
    total_tokens: int
    tool_calls: int
    duration_ms: int
    success: bool
    error: str | None
    timestamp: str
    dry_run: bool
    autonomous: bool
    iteration_count: int
    iterations: list[dict] = field(default_factory=list)
    final_status: str = "completed"
    finish_summary: str | None = None


def build_report_context(
    role: RoleDefinition,
    result: RunResult | AutonomousResult,
    prompt: UserPrompt,
    *,
    dry_run: bool = False,
) -> ReportContext:
    """Build a ReportContext from a role, run result, and prompt."""
    from initrunner.agent.executor import AutonomousResult as _AutonomousResult
    from initrunner.agent.prompt import extract_text_from_prompt

    prompt_text = extract_text_from_prompt(prompt)
    timestamp = datetime.now(UTC).isoformat()

    if isinstance(result, _AutonomousResult):
        return ReportContext(
            agent_name=role.metadata.name,
            model=role.spec.model.to_model_string(),
            run_id=result.run_id,
            prompt=prompt_text,
            output=result.final_output,
            tokens_in=result.total_tokens_in,
            tokens_out=result.total_tokens_out,
            total_tokens=result.total_tokens,
            tool_calls=result.total_tool_calls,
            duration_ms=result.total_duration_ms,
            success=result.success,
            error=result.error,
            timestamp=timestamp,
            dry_run=dry_run,
            autonomous=True,
            iteration_count=result.iteration_count,
            iterations=[
                {
                    "output": it.output,
                    "tokens_in": it.tokens_in,
                    "tokens_out": it.tokens_out,
                    "total_tokens": it.total_tokens,
                    "tool_calls": it.tool_calls,
                    "duration_ms": it.duration_ms,
                    "success": it.success,
                    "error": it.error,
                }
                for it in result.iterations
            ],
            final_status=result.final_status,
            finish_summary=result.finish_summary,
        )

    # RunResult (single-shot)
    return ReportContext(
        agent_name=role.metadata.name,
        model=role.spec.model.to_model_string(),
        run_id=result.run_id,
        prompt=prompt_text,
        output=result.output,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        total_tokens=result.total_tokens,
        tool_calls=result.tool_calls,
        duration_ms=result.duration_ms,
        success=result.success,
        error=result.error,
        timestamp=timestamp,
        dry_run=dry_run,
        autonomous=False,
        iteration_count=0,
    )


def render_report(context: ReportContext, template_name: str = "default") -> str:
    """Render a report from a ReportContext using the named template.

    Raises ValueError if the template name is not recognised.
    """
    if template_name not in BUILT_IN_TEMPLATES:
        raise ValueError(
            f"Unknown report template '{template_name}'. Available: {', '.join(BUILT_IN_TEMPLATES)}"
        )

    filename = f"{template_name}.md.j2"
    pkg_files = importlib.resources.files("initrunner._report_templates")
    template_text = (pkg_files / filename).read_text(encoding="utf-8")
    template = Template(template_text)

    from dataclasses import asdict

    return template.render(**asdict(context))


def export_report(
    role: RoleDefinition,
    result: RunResult | AutonomousResult,
    prompt: UserPrompt,
    output_path: Path,
    *,
    template_name: str = "default",
    dry_run: bool = False,
) -> Path:
    """Build context, render template, and write report to disk."""
    context = build_report_context(role, result, prompt, dry_run=dry_run)
    content = render_report(context, template_name)
    output_path = Path(output_path)
    output_path.write_text(content, encoding="utf-8")
    return output_path
