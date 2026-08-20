"""Group handling for the run command: member selection and listing."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from initrunner.cli._helpers import console, print_error

if TYPE_CHECKING:
    from collections.abc import Callable

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.group.schema import Roster


def load_roster_or_exit(group_file: Path) -> Roster:
    """Load a group file, or a directory of agent files."""
    from initrunner.group.loader import GroupLoadError, load_roster

    try:
        return load_roster(group_file)
    except GroupLoadError as e:
        print_error(e)
        raise typer.Exit(1) from e


def member_overlay(roster: Roster) -> Callable[[RoleDefinition], RoleDefinition]:
    """Group settings a member picks up when run on its own."""
    from initrunner.group.prepare import make_group_overlay

    return make_group_overlay(roster.group)


def resolve_member_or_exit(roster: Roster, key: str) -> Path:
    """Path of the requested member's role file."""
    member = roster.members.get(key)
    if member is None:
        from initrunner.group.prepare import unknown_member_message

        console.print(f"[red]Error:[/red] {unknown_member_message(roster, key)}")
        raise typer.Exit(1)
    return member.path


def sense_member_or_exit(
    roster: Roster,
    prompt: str,
    *,
    confirm_role: bool,
    dry_run: bool,
) -> str:
    """Pick the member that best matches *prompt*.

    Uses the same scoring as sensing over a role directory, but the candidates
    are the group's members rather than whatever is on disk.
    """
    from initrunner.cli._helpers._display import display_sense_result
    from initrunner.services.role_selector import RoleCandidate, select_candidate_sync

    candidates = [
        RoleCandidate(
            path=member.path,
            name=member.role.metadata.name,
            description=member.role.metadata.description,
            tags=list(member.role.metadata.tags),
        )
        for member in roster.members.values()
    ]
    selection = select_candidate_sync(prompt, candidates, allow_llm=not dry_run)
    display_sense_result(selection)

    by_name = {member.role.metadata.name: key for key, member in roster.members.items()}
    key = by_name.get(selection.candidate.name)
    if key is None:
        console.print(
            f"[red]Error:[/red] sensed agent '{selection.candidate.name}' is not in the group."
        )
        raise typer.Exit(1)

    if confirm_role and not typer.confirm(f"Use agent '{key}'?", default=True):
        console.print("Cancelled.")
        raise typer.Exit(1)
    return key


def print_members(roster: Roster, group_file: Path) -> None:
    """List the group's agents and how to run one."""
    from rich.table import Table

    table = Table(title=f"Agents in '{roster.name}'")
    table.add_column("Agent", style="cyan")
    table.add_column("Role", style="green")
    table.add_column("Description")

    for key, member in roster.members.items():
        table.add_row(key, member.role.metadata.name, member.role.metadata.description or "-")

    console.print(table)
    first = next(iter(roster.members), "<name>")
    console.print(
        f"\nRun one agent:      [bold]initrunner run {group_file} --agent {first}[/bold]\n"
        f'Pick one by prompt: [bold]initrunner run {group_file} --sense -p "..."[/bold]\n'
        f"Serve all of them:  [bold]initrunner run {group_file} --serve[/bold]"
    )
