"""Eval commands: test."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import (
    console,
    load_and_build_or_exit,
    load_role_or_exit,
    resolve_model_override,
    resolve_role_path,
)
from initrunner.cli._options import ModelOption


def _display_suite_result(suite_result: object, verbose: bool = False) -> None:
    from initrunner.eval.runner import SuiteResult

    sr: SuiteResult = suite_result  # type: ignore[assignment]

    table = Table(title=f"Test Suite: {sr.suite_name}")
    table.add_column("Case", style="cyan")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Tokens", justify="right")
    if verbose:
        table.add_column("Details")

    for cr in sr.case_results:
        status = "[green]PASS[/green]" if cr.passed else "[red]FAIL[/red]"
        duration = f"{cr.duration_ms}ms"
        tokens = str(cr.run_result.total_tokens)

        details = ""
        if verbose and cr.assertion_results:
            lines = []
            for ar in cr.assertion_results:
                icon = "[green]\u2713[/green]" if ar.passed else "[red]\u2717[/red]"
                lines.append(f"{icon} {ar.message}")
            if not cr.run_result.success:
                lines.append(f"[red]Error: {cr.run_result.error}[/red]")
            details = "\n".join(lines)

        if verbose:
            table.add_row(cr.case.name, status, duration, tokens, details)
        else:
            table.add_row(cr.case.name, status, duration, tokens)

    console.print(table)
    counts = f"[bold]{sr.passed}/{sr.total} passed[/bold]"
    stats = f"[dim]{sr.total_tokens} tokens | {sr.total_duration_ms}ms total[/dim]"
    if sr.all_passed:
        console.print(f"\n{counts} [green]\u2713 All tests passed[/green]  {stats}")
    else:
        console.print(f"\n{counts} [red]\u2717 Some tests failed[/red]  {stats}")


def test(
    role_file: Annotated[
        Path, typer.Argument(help="Agent directory, role YAML, or installed role name")
    ],
    suite: Annotated[Path, typer.Option("-s", "--suite", help="Path to test suite YAML")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Simulate with TestModel (no API calls)")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Show assertion details")
    ] = False,
    concurrency: Annotated[
        int, typer.Option("-j", "--concurrency", help="Number of concurrent workers")
    ] = 1,
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Save JSON results to file")
    ] = None,
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Filter cases by tag (repeatable)")
    ] = None,
    model: ModelOption = None,
) -> None:
    """Run a test suite against an agent role."""
    role_file = resolve_role_path(role_file)

    from initrunner.eval.runner import SuiteLoadError, load_suite
    from initrunner.services.eval import run_suite_sync, save_result

    resolved_model = resolve_model_override(model)

    if dry_run:
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        role = load_role_or_exit(role_file)
        agent = Agent(TestModel())
    else:
        role, agent = load_and_build_or_exit(role_file, model_override=resolved_model)

    try:
        test_suite = load_suite(suite)
    except SuiteLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(
        f"Running [cyan]{test_suite.metadata.name}[/cyan] "
        f"({len(test_suite.cases)} cases) against [cyan]{role.metadata.name}[/cyan]"
        + (" [dim](dry-run)[/dim]" if dry_run else "")
        + (f" [dim](concurrency={concurrency})[/dim]" if concurrency > 1 else "")
    )

    suite_result = run_suite_sync(
        agent,
        role,
        test_suite,
        dry_run=dry_run,
        concurrency=concurrency,
        tag_filter=tag,
        role_file=role_file,
    )
    _display_suite_result(suite_result, verbose=verbose)

    if output is not None:
        save_result(suite_result, output)
        console.print(f"[green]Results saved:[/green] {output}")

    if not suite_result.all_passed:
        raise typer.Exit(1)
