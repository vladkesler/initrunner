"""Registry commands: install, uninstall, search, info, list, update, publish, pull, login."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import console


def _display_install_preview(preview: object) -> None:
    """Render an InstallPreview to the console."""
    from initrunner.registry import InstallPreview

    assert isinstance(preview, InstallPreview)

    console.print()
    if preview.source_type == "hub":
        console.print(f"  [bold]Package:[/bold]     {preview.name}")
        console.print(f"  [bold]Version:[/bold]     {preview.version}")
        console.print(f"  [bold]Description:[/bold] {preview.description or '(none)'}")
        console.print(f"  [bold]Author:[/bold]      {preview.author or '(unknown)'}")
        console.print(f"  [bold]Downloads:[/bold]   {preview.downloads}")
    elif preview.source_type == "oci":
        console.print(f"  [bold]Role:[/bold]        {preview.name}")
        console.print(f"  [bold]Description:[/bold] {preview.description or '(none)'}")
        console.print(f"  [bold]Author:[/bold]      {preview.author or '(unknown)'}")
        console.print(f"  [bold]Source:[/bold]       {preview.source_label}")
    else:
        # GitHub
        console.print(f"  [bold]Role:[/bold]        {preview.name}")
        console.print(f"  [bold]Description:[/bold] {preview.description or '(none)'}")
        console.print(f"  [bold]Author:[/bold]      {preview.author or '(unknown)'}")
        tools_str = ", ".join(preview.tools) if preview.tools else "none"
        console.print(f"  [bold]Tools:[/bold]       {tools_str}")
        console.print(f"  [bold]Model:[/bold]       {preview.model}")
    for w in preview.warnings:
        console.print(f"  [yellow]Warning:[/yellow] {w}")
    console.print()


def install(
    source: Annotated[
        str,
        typer.Argument(
            help="Source: hub:owner/name[@ver], user/repo[:path][@ref], role name, or oci://..."
        ),
    ],
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Install a role from GitHub, the community index, or an OCI registry."""
    from initrunner.registry import (
        RegistryError,
        RoleExistsError,
        confirm_install,
        preview_install,
    )

    try:
        preview = preview_install(source, force=force)
    except RoleExistsError as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        raise typer.Exit(1) from None
    except RegistryError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not yes:
        _display_install_preview(preview)
        if not typer.confirm("Install this role?"):
            raise typer.Abort()

    try:
        path = confirm_install(source, force=force)
    except RoleExistsError as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        raise typer.Exit(1) from None
    except RegistryError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Installed[/green] {preview.name} -> {path}")


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
    """Search InitHub for agent packs."""
    from initrunner.registry import NetworkError, RegistryError, hub_search_index

    try:
        results = hub_search_index(query)
    except (NetworkError, RegistryError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not results:
        console.print(f"No packages found matching '{query}'.")
        return

    table = Table(title="InitHub Packages")
    table.add_column("Package", style="cyan")
    table.add_column("Description")
    table.add_column("Tags")

    for entry in results:
        table.add_row(
            entry.name,
            entry.description,
            ", ".join(entry.tags),
        )
    console.print(table)


def _display_oci_info(d: dict) -> None:  # type: ignore[type-arg]
    """Display OCI bundle manifest metadata."""
    name = str(d.get("name", "unknown"))
    table = Table(title=f"Role: {name}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Name", name)
    table.add_row("Version", str(d.get("version", "")))
    table.add_row("Description", str(d.get("description", "(none)")))
    table.add_row("Author", str(d.get("author", "(unknown)")))
    tags_val = d.get("tags")
    tags_str = ", ".join(str(t) for t in tags_val) if isinstance(tags_val, list) else ""
    table.add_row("Tags", tags_str)
    table.add_row("InitRunner Version", str(d.get("initrunner_version", "")))
    files_val = d.get("files")
    table.add_row("Files", str(len(files_val)) if isinstance(files_val, list) else "0")
    console.print(table)


def _display_hub_info(d: dict) -> None:  # type: ignore[type-arg]
    """Display InitHub package info table."""
    name = str(d.get("name", "unknown"))
    table = Table(title=f"Package: {name}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")
    table.add_row("Name", name)
    table.add_row("Description", str(d.get("description") or "(none)"))
    table.add_row("Author", str(d.get("author") or "(unknown)"))
    table.add_row("Latest Version", str(d.get("latest_version") or "(none)"))
    table.add_row("Downloads", str(d.get("downloads", 0)))
    tags = d.get("tags")
    table.add_row("Tags", ", ".join(tags) if tags else "(none)")
    versions = d.get("versions")
    if versions is not None:
        table.add_row("Versions", ", ".join(versions) if versions else "(none)")
    repo_url = d.get("repository_url")
    if repo_url:
        table.add_row("Repository", repo_url)
    console.print(table)


def info(
    source: Annotated[str, typer.Argument(help="Role source to inspect")],
) -> None:
    """Inspect a role's metadata and tools without installing."""
    from initrunner.registry import RegistryError, info_role

    try:
        role_info = info_role(source)
    except RegistryError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # Dict results: hub or OCI
    if isinstance(role_info, dict):
        if role_info.get("source_type") == "hub":  # type: ignore[arg-type]
            _display_hub_info(role_info)
        else:
            _display_oci_info(role_info)
        return

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
    table.add_column("Source", style="dim")
    table.add_column("Repo")
    table.add_column("Ref")
    table.add_column("Installed At")

    for role in roles:
        source_label = role.source_type.upper()
        repo_label = role.repo or role.oci_ref
        table.add_row(role.name, source_label, repo_label, role.ref, role.installed_at[:19])

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


def publish(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")] = Path(
        "."
    ),
    ref: Annotated[str, typer.Argument(help="OCI reference (oci://registry/repo)")] = "",
    tag: Annotated[str, typer.Option("--tag", "-t", help="Tag for the artifact")] = "latest",
) -> None:
    """Publish a role bundle to an OCI registry."""
    from initrunner.cli._helpers import resolve_role_path
    from initrunner.packaging.oci import OCIError
    from initrunner.services.packaging import publish_role

    if not ref:
        console.print("[red]Error:[/red] OCI reference argument is required.")
        raise typer.Exit(1)

    role_file = resolve_role_path(role_file)

    try:
        digest = publish_role(role_file, ref, tag=tag)
        console.print(f"[green]Published[/green] → {ref}:{tag}")
        console.print(f"  Digest: {digest}")
    except OCIError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


def pull(
    ref: Annotated[str, typer.Argument(help="OCI reference (oci://registry/repo:tag)")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Pull a role bundle from an OCI registry."""
    from initrunner.registry import (
        RegistryError,
        RoleExistsError,
        confirm_install,
        preview_install,
    )

    if not ref.startswith("oci://"):
        ref = f"oci://{ref}"

    try:
        preview = preview_install(ref, force=force)
    except RoleExistsError as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        raise typer.Exit(1) from None
    except RegistryError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not yes:
        _display_install_preview(preview)
        if not typer.confirm("Install this role?"):
            raise typer.Abort()

    try:
        path = confirm_install(ref, force=force)
    except RoleExistsError as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        raise typer.Exit(1) from None
    except RegistryError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Installed[/green] {preview.name} -> {path}")


def login(
    registry: Annotated[str, typer.Argument(help="Registry hostname (e.g. ghcr.io)")],
    username: Annotated[str | None, typer.Option("--username", "-u", help="Username")] = None,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read password from stdin")
    ] = False,
) -> None:
    """Log in to an OCI registry."""
    import sys

    from initrunner.packaging.auth import save_auth

    if username is None:
        username = typer.prompt("Username")

    if password_stdin:
        password = sys.stdin.readline().strip()
    else:
        password = typer.prompt("Password", hide_input=True)

    save_auth(registry, username, password)
    console.print(f"[green]Login succeeded[/green] for {registry}")
