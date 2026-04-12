"""Intent sensing: resolve prompt to best-matching role."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from initrunner.cli._helpers import console


def _resolve_via_sensing(
    prompt: str,
    *,
    role_dir: Path | None,
    confirm_role: bool,
    dry_run: bool,
) -> Path:
    """Run intent sensing to find the best role. Returns resolved role path."""
    from initrunner.cli._helpers import display_sense_result
    from initrunner.services.role_selector import NoRolesFoundError, select_role_sync

    try:
        with console.status("[dim]Sensing best role...[/dim]"):
            selection = select_role_sync(
                prompt,
                role_dir=role_dir,
                allow_llm=not dry_run,
            )
    except (NoRolesFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    display_sense_result(selection)
    if confirm_role:
        if not sys.stdin.isatty():
            console.print("[red]Error:[/red] --confirm-role requires an interactive terminal.")
            raise typer.Exit(1)
        if not typer.confirm("Use this role?", default=True):
            raise typer.Exit()
    return selection.candidate.path
