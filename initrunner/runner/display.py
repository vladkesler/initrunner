"""Rich console output helpers for runner modes."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from initrunner.agent.executor import AutonomousResult, RunResult, TokenBudgetStatus
from initrunner.agent.schema import RoleDefinition

console = Console()


def _display_result(result: RunResult, *, budget_status: TokenBudgetStatus | None = None) -> None:
    """Render a run result as a Rich panel."""
    if result.success:
        md = Markdown(result.output)
        subtitle = f"tokens: {result.tokens_in}in/{result.tokens_out}out | {result.duration_ms}ms"
        if budget_status is not None and budget_status.budget is not None:
            subtitle += f" | budget: {budget_status.consumed:,}/{budget_status.budget:,}"
        console.print(Panel(md, title="Agent", subtitle=subtitle, border_style="green"))
    else:
        console.print(
            Panel(
                f"[red]{result.error}[/red]",
                title="Error",
                border_style="red",
            )
        )


def _display_budget_warning(status: TokenBudgetStatus, consumed: int, budget: int | None) -> None:
    """Print budget warnings after a run completes."""
    if budget is None:
        return
    if status.exceeded:
        console.print(
            f"[yellow]Session token budget exhausted ({consumed:,}/{budget:,}). "
            f"Stopping further execution.[/yellow]"
        )
    elif status.warning:
        pct = int(consumed / budget * 100)
        console.print(
            f"[yellow]Warning: {pct}% of session token budget consumed "
            f"({consumed:,}/{budget:,})[/yellow]"
        )


def _display_save_warning() -> None:
    """Print a warning when session save fails."""
    console.print(
        "[yellow]Warning: Failed to save session — conversation will not be resumable.[/yellow]"
    )


def _display_autonomous_header(
    role: RoleDefinition, max_iterations: int, token_budget: int | None
) -> None:
    """Print the header for an autonomous run."""
    console.print(f"[bold]Autonomous mode[/bold] — agent: [cyan]{role.metadata.name}[/cyan]")
    console.print(f"  Max iterations: [cyan]{max_iterations}[/cyan]")
    if token_budget is not None:
        console.print(f"  Token budget: [cyan]{token_budget:,}[/cyan]")
    console.print()


def _display_iteration_result(
    result: RunResult,
    iteration: int,
    max_iterations: int,
    cumulative_tokens: int,
    token_budget: int | None,
) -> None:
    """Render the result of a single autonomous iteration."""
    budget_info = ""
    if token_budget is not None:
        budget_info = f" | budget: {cumulative_tokens:,}/{token_budget:,}"
    subtitle = (
        f"tokens: {result.tokens_in}in/{result.tokens_out}out | {result.duration_ms}ms{budget_info}"
    )
    if result.success:
        md = Markdown(result.output)
        console.print(
            Panel(
                md,
                title=f"Agent (iteration {iteration}/{max_iterations})",
                subtitle=subtitle,
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[red]{result.error}[/red]",
                title=f"Error (iteration {iteration}/{max_iterations})",
                subtitle=subtitle,
                border_style="red",
            )
        )


def _display_autonomous_summary(
    auto_result: AutonomousResult,
    reflection_summary: str | None,
    max_iterations: int,
    cumulative_tokens: int,
) -> None:
    """Print the summary panel after an autonomous run completes."""
    summary_text = (
        f"Status: {auto_result.final_status} | "
        f"Iterations: {auto_result.iteration_count}/{max_iterations} | "
        f"Tokens: {cumulative_tokens:,}"
    )
    if reflection_summary:
        summary_text += f"\nSummary: {reflection_summary}"
    console.print(
        Panel(
            summary_text,
            title="Autonomous Run Complete",
            border_style="cyan" if auto_result.success else "yellow",
        )
    )


def _display_daemon_header(
    role: RoleDefinition,
    guardrails: object,
    autonomous_trigger_types: set[str],
    dispatcher: object,
) -> None:
    """Print the header for daemon mode."""
    console.print(f"[bold]Daemon mode[/bold] — agent: [cyan]{role.metadata.name}[/cyan]")
    if guardrails.daemon_token_budget is not None:  # type: ignore[union-attr]
        console.print(f"  Lifetime token budget: [cyan]{guardrails.daemon_token_budget:,}[/cyan]")  # type: ignore[union-attr]
    if guardrails.daemon_daily_token_budget is not None:  # type: ignore[union-attr]
        console.print(
            f"  Daily token budget: [cyan]{guardrails.daemon_daily_token_budget:,}[/cyan]"  # type: ignore[union-attr]
        )
    if guardrails.daemon_token_budget or guardrails.daemon_daily_token_budget:  # type: ignore[union-attr]
        console.print("[dim]  Token budgets reset on process restart.[/dim]")
    if autonomous_trigger_types:
        console.print(
            f"  Autonomous triggers: [cyan]{', '.join(sorted(autonomous_trigger_types))}[/cyan]"
        )
    console.print(f"  {dispatcher.count} trigger(s) active. Press Ctrl+C to stop.\n")  # type: ignore[union-attr]
