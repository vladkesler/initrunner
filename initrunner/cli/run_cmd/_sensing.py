"""Intent sensing: resolve prompt to best-matching role."""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from initrunner.cli._helpers import console


def _resolve_via_sensing(prompt: str, *, dry_run: bool) -> Path:
    """Run intent sensing to find the best role. Returns resolved role path.

    Searches the default role directories (cwd, ./examples/roles,
    ~/.initrunner/roles, and the bundled starters). Sensing picks a role on the
    user's behalf, so it always confirms when there is a terminal to ask; piped
    and scripted runs proceed with the selection.
    """
    from initrunner.cli._helpers import display_sense_result
    from initrunner.services.role_selector import NoRolesFoundError, select_role_sync

    try:
        with console.status("[dim]Sensing best role...[/dim]"):
            selection = select_role_sync(prompt, allow_llm=not dry_run)
    except (NoRolesFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    display_sense_result(selection)
    if sys.stdin.isatty() and not typer.confirm("Use this role?", default=True):
        raise typer.Exit()
    return selection.candidate.path
