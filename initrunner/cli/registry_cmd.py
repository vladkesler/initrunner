"""Registry commands: install, uninstall, search, info, list, update."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import console


def install(
    source: Annotated[
        str, typer.Argument(help="GitHub source (user/repo[:path][@ref]) or role name")
    ],
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Install a role from GitHub or the community index."""
    from initrunner.registry import (
        NetworkError,
        RegistryError,
        RoleExistsError,
        RoleNotFoundError,
        install_role,
    )

    try:
        install_role(source, force=force, yes=yes)
    except RoleExistsError as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        raise typer.Exit(1) from None
    except (RoleNotFoundError, NetworkError, RegistryError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


def uninstall(
    name: Annotated[str, typer.Argument(help="Role name to remove")],
) -> None:
    """Remove an installed role."""
    from initrunner.registry import RoleNotFoundError, uninstall_role

    try:
        uninstall_role(name)
        console.print(f"[green]Uninstalled[/green] {name}.")
    except RoleNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


def search(
    query: Annotated[str, typer.Argument(help="Search query")],
) -> None:
    """Search the community role index."""
    from initrunner.registry import NetworkError, RegistryError, search_index

    try:
        results = search_index(query)
    except (NetworkError, RegistryError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not results:
        console.print(f"No roles found matching '{query}'.")
        return

    table = Table(title="Community Roles")
    table.add_column("Name", style="cyan")
    table.add_column("Author")
    table.add_column("Description")
    table.add_column("Tags")

    for entry in results:
        table.add_row(
            entry.name,
            entry.author,
            entry.description,
            ", ".join(entry.tags),
        )
    console.print(table)


def info(
    source: Annotated[str, typer.Argument(help="Role source to inspect")],
) -> None:
    """Inspect a role's metadata and tools without installing."""
    from initrunner.registry import NetworkError, RegistryError, RoleNotFoundError, info_role

    try:
        role_info = info_role(source)
    except (RoleNotFoundError, NetworkError, RegistryError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    table = Table(title=f"Role: {role_info.name}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Name", role_info.name)
    table.add_row("Description", role_info.description or "(none)")
    table.add_row("Author", role_info.author or "(unknown)")
    table.add_row("Model", f"{role_info.provider}/{role_info.model}")
    table.add_row("Tools", ", ".join(role_info.tools) if role_info.tools else "none")
    table.add_row("Triggers", "yes" if role_info.has_triggers else "no")
    table.add_row("Ingestion", "yes" if role_info.has_ingestion else "no")
    table.add_row("Memory", "yes" if role_info.has_memory else "no")

    console.print(table)


def list_roles(
    installed: Annotated[bool, typer.Option("--installed", help="Show installed roles")] = True,
) -> None:
    """List installed roles."""
    from initrunner.registry import list_installed

    roles = list_installed()

    if not roles:
        console.print("No roles installed. Use [bold]initrunner install[/bold] to add roles.")
        return

    table = Table(title="Installed Roles")
    table.add_column("Name", style="cyan")
    table.add_column("Repo")
    table.add_column("Ref")
    table.add_column("Installed At")

    for role in roles:
        table.add_row(role.name, role.repo, role.ref, role.installed_at[:19])

    console.print(table)


def update(
    name: Annotated[str | None, typer.Argument(help="Role name to update (omit for --all)")] = None,
    all_roles: Annotated[bool, typer.Option("--all", help="Update all installed roles")] = False,
) -> None:
    """Update an installed role to the latest version."""
    from initrunner.registry import RoleNotFoundError, update_all, update_role

    if all_roles or (name is None and not all_roles):
        if name is None:
            results = update_all()
            if not results:
                console.print("No roles installed.")
                return
            for r in results:
                status = "[green]Updated[/green]" if r.updated else "[dim]Unchanged[/dim]"
                console.print(f"  {status} {r.name}: {r.message}")
            return

    if name is None:
        console.print("[red]Error:[/red] Provide a role name or use --all.")
        raise typer.Exit(1)

    try:
        result = update_role(name)
    except RoleNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if result.updated:
        console.print(f"[green]Updated[/green] {name}: {result.message}")
    else:
        console.print(f"[dim]{name}:[/dim] {result.message}")
