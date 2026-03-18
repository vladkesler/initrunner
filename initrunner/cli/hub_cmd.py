"""InitHub marketplace commands (deprecated -- use top-level commands)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

app = typer.Typer(name="hub", help="InitHub commands (deprecated: use top-level equivalents).")


def _deprecation_warning(old: str, new: str) -> None:
    console.print(
        f"[yellow]Deprecated: use 'initrunner {new}' instead of 'initrunner hub {old}'[/yellow]"
    )


@app.command()
def login(
    token: Annotated[
        str | None, typer.Option("--token", help="API token (for CI/headless)")
    ] = None,
) -> None:
    """Log in to InitHub. (Deprecated: use 'initrunner login')"""
    _deprecation_warning("login", "login")
    from initrunner.cli.registry_cmd import login as top_login

    top_login(registry=None, token=token)


@app.command()
def logout() -> None:
    """Remove stored InitHub credentials. (Deprecated: use 'initrunner logout')"""
    _deprecation_warning("logout", "logout")
    from initrunner.cli.registry_cmd import logout as top_logout

    top_logout()


@app.command()
def whoami() -> None:
    """Show the currently authenticated InitHub user. (Deprecated: use 'initrunner whoami')"""
    _deprecation_warning("whoami", "whoami")
    from initrunner.cli.registry_cmd import whoami as top_whoami

    top_whoami()


@app.command()
def publish(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")] = Path(
        "."
    ),
    readme: Annotated[Path | None, typer.Option("--readme", help="README file")] = None,
    repo_url: Annotated[str | None, typer.Option("--repo-url", help="Repository URL")] = None,
    category: Annotated[list[str] | None, typer.Option("--category", "-c", help="Category")] = None,
) -> None:
    """Publish a role to InitHub. (Deprecated: use 'initrunner publish')"""
    _deprecation_warning("publish", "publish")
    from initrunner.cli.registry_cmd import publish as top_publish

    top_publish(role_file=role_file, readme=readme, repo_url=repo_url, category=category)


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query")],
    tags: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Filter by tag")] = None,
) -> None:
    """Search InitHub for agent packs. (Deprecated: use 'initrunner search')"""
    _deprecation_warning("search", "search")
    from initrunner.cli.registry_cmd import search as top_search

    top_search(query=query, tags=tags)


@app.command()
def info(
    package: Annotated[str, typer.Argument(help="Package (owner/name)")],
) -> None:
    """Show InitHub package details. (Deprecated: use 'initrunner info')"""
    _deprecation_warning("info", "info")
    from initrunner.cli.registry_cmd import info as top_info

    top_info(source=package)
