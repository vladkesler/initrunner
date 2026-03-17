"""InitHub marketplace commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

app = typer.Typer(name="hub", help="InitHub marketplace commands.")


@app.command()
def login() -> None:
    """Log in to InitHub with an API token."""
    from initrunner.hub import save_hub_token

    console.print("Create a token at [cyan]https://hub.initrunner.ai/settings[/cyan]")
    token = typer.prompt("Paste your InitHub API token", hide_input=True)
    save_hub_token(token.strip())
    console.print("[green]Token saved.[/green]")


@app.command()
def logout() -> None:
    """Remove stored InitHub credentials."""
    from initrunner.hub import remove_hub_token

    remove_hub_token()
    console.print("InitHub credentials removed.")


@app.command()
def whoami() -> None:
    """Show the currently authenticated InitHub user."""
    from initrunner.hub import HubAuthError, HubError, _hub_request, load_hub_token

    token = load_hub_token()
    if not token:
        console.print("Not logged in. Run [bold]initrunner hub login[/bold] first.")
        raise typer.Exit(1)

    try:
        data = _hub_request("/user", token=token)
        console.print(f"Logged in as [cyan]{data.get('username', 'unknown')}[/cyan]")
    except HubAuthError:
        console.print(
            "[red]Token is invalid or expired.[/red] Run [bold]initrunner hub login[/bold]."
        )
        raise typer.Exit(1) from None
    except HubError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


@app.command()
def publish(
    role_file: Annotated[Path, typer.Argument(help="Path to role.yaml file")],
    readme: Annotated[Path | None, typer.Option("--readme", help="README file")] = None,
    repo_url: Annotated[str | None, typer.Option("--repo-url", help="Repository URL")] = None,
    category: Annotated[list[str] | None, typer.Option("--category", "-c", help="Category")] = None,
) -> None:
    """Publish a role to InitHub."""
    from initrunner.hub import HubError, hub_publish, load_hub_token
    from initrunner.packaging.bundle import create_bundle

    token = load_hub_token()
    if not token:
        console.print("Not logged in. Run [bold]initrunner hub login[/bold] first.")
        raise typer.Exit(1)

    if not role_file.exists():
        console.print(f"[red]Error:[/red] File not found: {role_file}")
        raise typer.Exit(1)

    # Create bundle
    console.print("Creating bundle...")
    try:
        bundle_path = create_bundle(role_file)
    except Exception as e:
        console.print(f"[red]Error creating bundle:[/red] {e}")
        raise typer.Exit(1) from None

    readme_text = None
    if readme and readme.exists():
        readme_text = readme.read_text()

    console.print(f"Publishing [cyan]{bundle_path.name}[/cyan] to InitHub...")
    try:
        result = hub_publish(
            str(bundle_path),
            token,
            readme=readme_text,
            repository_url=repo_url,
            categories=category,
        )
        owner = result.get("owner", "")
        name = result.get("name", "")
        version = result.get("version", "")
        console.print(f"[green]Published[/green] {owner}/{name}@{version}")
        console.print(f"  Install: [cyan]initrunner install hub:{owner}/{name}[/cyan]")
    except HubError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    finally:
        # Clean up bundle
        bundle_path.unlink(missing_ok=True)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    tags: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Filter by tag")] = None,
) -> None:
    """Search InitHub for agent packs."""
    from rich.table import Table

    from initrunner.hub import HubError, hub_search

    try:
        results = hub_search(query, tags=tags)
    except HubError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    if not results:
        console.print(f"No packages found matching '{query}'.")
        return

    table = Table(title="InitHub Packages")
    table.add_column("Package", style="cyan")
    table.add_column("Version")
    table.add_column("Description")
    table.add_column("Downloads", justify="right")
    table.add_column("Tags")

    for r in results:
        table.add_row(
            f"{r.owner}/{r.name}",
            r.latest_version,
            r.description[:60] + ("..." if len(r.description) > 60 else ""),
            str(r.downloads),
            ", ".join(r.tags[:3]),
        )
    console.print(table)


@app.command()
def info(
    package: Annotated[str, typer.Argument(help="Package (owner/name)")],
) -> None:
    """Show InitHub package details."""
    from initrunner.cli.registry_cmd import _display_hub_info
    from initrunner.hub import HubError, hub_resolve

    # Parse owner/name
    if "/" not in package:
        console.print("[red]Error:[/red] Use format: owner/name")
        raise typer.Exit(1)

    parts = package.split("/", 1)
    owner, name = parts[0], parts[1]

    try:
        pkg = hub_resolve(owner, name)
    except HubError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    _display_hub_info(
        {
            "name": f"{pkg.owner}/{pkg.name}",
            "description": pkg.description,
            "author": pkg.author,
            "latest_version": pkg.latest_version,
            "downloads": pkg.downloads,
            "tags": pkg.tags,
            "versions": pkg.versions,
            "repository_url": pkg.repository_url,
        }
    )
