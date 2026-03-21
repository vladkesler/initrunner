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
    else:
        # OCI
        console.print(f"  [bold]Role:[/bold]        {preview.name}")
        console.print(f"  [bold]Description:[/bold] {preview.description or '(none)'}")
        console.print(f"  [bold]Author:[/bold]      {preview.author or '(unknown)'}")
        console.print(f"  [bold]Source:[/bold]       {preview.source_label}")
    for w in preview.warnings:
        console.print(f"  [yellow]Warning:[/yellow] {w}")
    console.print()


def _post_install_provider_check(result: object, *, yes: bool = False) -> None:
    """Check provider compatibility after install; offer adaptation if mismatch."""
    from rich.panel import Panel
    from rich.prompt import Prompt

    from initrunner.cli._helpers import resolve_role_path
    from initrunner.registry import InstallResult, set_role_overrides
    from initrunner.services.providers import check_role_provider_compatibility

    assert isinstance(result, InstallResult)

    try:
        role_path = resolve_role_path(result.path)
    except (SystemExit, Exception):
        return  # Can't resolve role YAML -- skip check silently

    try:
        compat = check_role_provider_compatibility(role_path)
    except Exception:
        return  # Load/parse error -- user will see it at run time

    if compat.user_has_key:
        # Provider matches -- show status and move on
        console.print(
            f"  Provider: {compat.role_provider} / {compat.role_model} [green][Key set][/green]"
        )
    elif not compat.available_providers:
        console.print(
            "[yellow]Warning:[/yellow] No provider configured. "
            "Run [bold]initrunner setup[/bold] first."
        )
    else:
        # Mismatch -- build adaptation options
        from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS

        env_var = _PROVIDER_API_KEY_ENVS.get(compat.role_provider, compat.role_provider.upper())
        lines = [
            f"  Role uses:  [bold]{compat.role_provider} / {compat.role_model}[/bold]",
            f"  {env_var}: [red]Missing[/red]",
            "",
        ]
        for i, dp in enumerate(compat.available_providers, 1):
            lines.append(f"  {i}. Adapt to [cyan]{dp.provider}[/cyan] ({dp.model})")
        keep_idx = len(compat.available_providers) + 1
        lines.append(f"  {keep_idx}. Keep as-is (set {env_var} later)")

        console.print(Panel("\n".join(lines), title="Provider Check", border_style="yellow"))

        if yes:
            # Non-interactive: auto-adapt to top available provider
            chosen = compat.available_providers[0]
            set_role_overrides(
                result.display_name,
                {
                    "provider": chosen.provider,
                    "model": chosen.model,
                },
            )
            console.print(
                f"  Auto-adapted to [cyan]{chosen.provider} / {chosen.model}[/cyan] "
                f"(override stored in registry)"
            )
        else:
            raw = Prompt.ask(
                f"Adapt? [1-{keep_idx}]",
                default="1",
            )
            idx = int(raw) - 1 if raw.strip().isdigit() else -1
            if 0 <= idx < len(compat.available_providers):
                chosen = compat.available_providers[idx]
                set_role_overrides(
                    result.display_name,
                    {
                        "provider": chosen.provider,
                        "model": chosen.model,
                    },
                )
                console.print(
                    f"  Adapted to [cyan]{chosen.provider} / {chosen.model}[/cyan] "
                    f"(override stored in registry)"
                )
            else:
                console.print("  Keeping original provider.")

    # Embedding warning
    if compat.needs_embeddings and not compat.has_embedding_key:
        from initrunner.ingestion.embeddings import _default_embedding_key_env

        emb_env = _default_embedding_key_env(compat.effective_embedding_provider)
        console.print(
            f"\n  [yellow]Note:[/yellow] This role uses RAG/memory. "
            f"Effective embedding provider is [bold]{compat.effective_embedding_provider}[/bold]."
            f"\n  Set [bold]{emb_env}[/bold] for embeddings. "
            f"Run: [bold]initrunner doctor[/bold]"
        )


def install(
    source: Annotated[
        str,
        typer.Argument(help="Source: owner/name[@ver], oci://registry/repo:tag"),
    ],
    force: Annotated[bool, typer.Option("--force", "-f", help="Overwrite existing")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Install a role from InitHub or an OCI registry."""
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
        result = confirm_install(source, force=force)
    except RoleExistsError as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        raise typer.Exit(1) from None
    except RegistryError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Installed[/green] {preview.name} -> {result.path}")

    # --- Post-install provider compatibility check ---
    _post_install_provider_check(result, yes=yes)

    console.print(f'  Run: [bold]initrunner run {result.display_name} -p "your prompt"[/bold]')


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
    tags: Annotated[list[str] | None, typer.Option("--tag", "-t", help="Filter by tag")] = None,
) -> None:
    """Search InitHub for agent packs."""
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

    if role_info.get("source_type") == "hub":
        _display_hub_info(role_info)
    else:
        _display_oci_info(role_info)


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
    table.add_column("Version")
    table.add_column("Run", style="green")

    for role in roles:
        source_label = role.source_type.upper()
        repo_label = role.repo or role.oci_ref
        version_label = role.hub_version or role.ref
        table.add_row(
            role.name, source_label, repo_label, version_label, f"initrunner run {role.name}"
        )

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
    readme: Annotated[
        Path | None, typer.Option("--readme", help="README file (InitHub only)")
    ] = None,
    repo_url: Annotated[
        str | None, typer.Option("--repo-url", help="Repository URL (InitHub only)")
    ] = None,
    category: Annotated[
        list[str] | None,
        typer.Option("--category", "-c", help="Category (InitHub only)"),
    ] = None,
) -> None:
    """Publish a role bundle to InitHub (default) or an OCI registry."""
    from initrunner.cli._helpers import resolve_role_path

    role_file = resolve_role_path(role_file)

    if ref:
        # OCI publish path
        from initrunner.packaging.oci import OCIError
        from initrunner.services.packaging import publish_role

        try:
            digest = publish_role(role_file, ref, tag=tag)
            console.print(f"[green]Published[/green] -> {ref}:{tag}")
            console.print(f"  Digest: {digest}")
        except OCIError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None
    else:
        # InitHub publish path
        from initrunner.hub import HubError, hub_publish, load_hub_token
        from initrunner.packaging.bundle import create_bundle

        token = load_hub_token()
        if not token:
            console.print("Not logged in. Run [bold]initrunner login[/bold] first.")
            raise typer.Exit(1)

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
            console.print(f"  Install: [cyan]initrunner install {owner}/{name}[/cyan]")
        except HubError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None
        finally:
            bundle_path.unlink(missing_ok=True)


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
        result = confirm_install(ref, force=force)
    except RoleExistsError as e:
        console.print(f"[yellow]Warning:[/yellow] {e}")
        raise typer.Exit(1) from None
    except RegistryError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    console.print(f"[green]Installed[/green] {preview.name} -> {result.path}")
    console.print(f'  Run: [bold]initrunner run {result.display_name} -p "your prompt"[/bold]')


def login(
    registry: Annotated[
        str | None,
        typer.Argument(help="Registry hostname (e.g. ghcr.io). Omit for InitHub."),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option("--token", help="InitHub API token (for CI/headless)"),
    ] = None,
    username: Annotated[
        str | None, typer.Option("--username", "-u", help="Username (OCI only)")
    ] = None,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read password from stdin (OCI only)")
    ] = False,
) -> None:
    """Log in to InitHub (default) or an OCI registry."""
    # Validate option combinations
    if registry and token:
        console.print("[red]Error:[/red] --token is for InitHub login only, not OCI registries.")
        raise typer.Exit(1)

    if not registry and (username or password_stdin):
        console.print(
            "[red]Error:[/red] --username and --password-stdin are for OCI registries."
            " Provide a registry hostname."
        )
        raise typer.Exit(1)

    if registry:
        # OCI registry login
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
    else:
        # InitHub login
        import time
        import webbrowser
        from datetime import UTC, datetime

        from initrunner.hub import (
            HubDeviceCodeExpired,
            HubError,
            poll_device_code,
            request_device_code,
            save_hub_token,
        )

        if token is not None:
            save_hub_token(token.strip())
            console.print("[green]Token saved.[/green]")
            return

        # Device code flow
        try:
            dc = request_device_code()
        except HubError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None

        user_code = dc["user_code"]
        device_code = dc["device_code"]
        verification_url = dc["verification_url"]
        interval = dc.get("interval_seconds", 5)
        expires_at_str = dc["expires_at"]

        console.print()
        console.print(f"  Your code: [bold cyan]{user_code}[/bold cyan]")
        console.print()
        console.print(f"  Open: [cyan]{verification_url}[/cyan]")
        console.print()

        try:
            webbrowser.open(verification_url)
        except Exception:
            pass

        consecutive_errors = 0

        try:
            with console.status("Waiting for browser authorization..."):
                while True:
                    time.sleep(interval)

                    # Local expiry check
                    try:
                        expires_at = datetime.fromisoformat(expires_at_str)
                        if expires_at.tzinfo is None:
                            expires_at = expires_at.replace(tzinfo=UTC)
                        if datetime.now(UTC) >= expires_at:
                            console.print("[red]Device code expired.[/red] Please try again.")
                            raise typer.Exit(1)
                    except (ValueError, TypeError):
                        pass

                    try:
                        result = poll_device_code(device_code)
                        consecutive_errors = 0
                    except HubDeviceCodeExpired:
                        console.print("[red]Device code expired.[/red] Please try again.")
                        raise typer.Exit(1) from None
                    except HubError as e:
                        if "invalid" in str(e).lower() or "consumed" in str(e).lower():
                            console.print(f"[red]Error:[/red] {e}")
                            raise typer.Exit(1) from None
                        consecutive_errors += 1
                        if consecutive_errors >= 3:
                            console.print("[red]Too many network errors. Please try again.[/red]")
                            raise typer.Exit(1) from None
                        continue

                    if result["status"] == "pending":
                        continue

                    if result["status"] == "complete":
                        save_hub_token(result["token"])
                        uname = result["username"]
                        console.print(f"[green]Logged in as[/green] [cyan]{uname}[/cyan]")
                        return
        except KeyboardInterrupt:
            console.print("\nLogin cancelled.")
            raise typer.Exit(0) from None


def logout() -> None:
    """Remove stored InitHub credentials."""
    from initrunner.hub import remove_hub_token

    remove_hub_token()
    console.print("InitHub credentials removed.")


def whoami() -> None:
    """Show the currently authenticated InitHub user."""
    from initrunner.hub import HubAuthError, HubError, _hub_request, load_hub_token

    token = load_hub_token()
    if not token:
        console.print("Not logged in. Run [bold]initrunner login[/bold] first.")
        raise typer.Exit(1)

    try:
        data = _hub_request("/user", token=token)
        console.print(f"Logged in as [cyan]{data.get('username', 'unknown')}[/cyan]")
    except HubAuthError:
        console.print("[red]Token is invalid or expired.[/red] Run [bold]initrunner login[/bold].")
        raise typer.Exit(1) from None
    except HubError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
