"""Ingest command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console, load_role_or_exit, suggest_next


def _status_color(status: object) -> str:
    from initrunner.ingestion.pipeline import FileStatus

    return {  # type: ignore[no-matching-overload]
        FileStatus.NEW: "green",
        FileStatus.UPDATED: "yellow",
        FileStatus.SKIPPED: "dim",
        FileStatus.ERROR: "red",
    }.get(status, "white")


def ingest(
    role_file: Annotated[
        Path, typer.Argument(help="Agent directory, role YAML, or installed role name")
    ],
    force: Annotated[bool, typer.Option("--force", help="Force re-ingestion of all files")] = False,
) -> None:
    """Ingest documents defined in the role's ingest config."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    from initrunner.cli._helpers import resolve_role_path
    from initrunner.ingestion.pipeline import FileStatus, resolve_sources, run_ingest

    role_file = resolve_role_path(role_file)
    role = load_role_or_exit(role_file)

    from initrunner.agent.loader import _load_dotenv
    from initrunner.services.ingest import effective_ingest_base_dir

    base_dir = effective_ingest_base_dir(role_file)
    _load_dotenv(base_dir)

    if role.spec.ingest is None:
        console.print("[red]Error:[/red] No ingest config in role definition.")
        console.print(
            "[dim]Hint:[/dim] Add an [bold]ingest:[/bold] section to your role YAML."
            " See [bold]initrunner examples[/bold] for templates."
        )
        raise typer.Exit(1)

    files, urls = resolve_sources(role.spec.ingest.sources, base_dir=base_dir)
    total = len(files) + len(urls)

    console.print(
        f"Ingesting for [cyan]{role.metadata.name}[/cyan]... ({len(files)} files, {len(urls)} URLs)"
    )

    if total == 0:
        console.print("[yellow]No files or URLs matched source patterns.[/yellow]")
        return

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Ingesting", total=total)

        def on_progress(path: Path, status: FileStatus) -> None:
            progress.update(task, advance=1, description=f"[{_status_color(status)}]{path.name}")

        resource_limits = role.spec.security.resources
        try:
            stats = run_ingest(
                role.spec.ingest,
                role.metadata.name,
                provider=role.spec.model.provider,
                base_dir=base_dir,
                force=force,
                progress_callback=on_progress,
                max_file_size_mb=resource_limits.max_file_size_mb,
                max_total_ingest_mb=resource_limits.max_total_ingest_mb,
            )
        except Exception as exc:
            from initrunner.stores.base import EmbeddingModelChangedError

            if not isinstance(exc, EmbeddingModelChangedError):
                raise
            progress.stop()
            if typer.confirm(
                f"{exc} This requires wiping the store and re-ingesting all documents. Proceed?"
            ):
                progress.start()
                stats = run_ingest(
                    role.spec.ingest,
                    role.metadata.name,
                    provider=role.spec.model.provider,
                    base_dir=base_dir,
                    force=True,
                    progress_callback=on_progress,
                    max_file_size_mb=resource_limits.max_file_size_mb,
                    max_total_ingest_mb=resource_limits.max_total_ingest_mb,
                )
            else:
                console.print("[yellow]Aborted.[/yellow]")
                raise typer.Exit(1) from None

    parts = []
    if stats.new:
        parts.append(f"[green]New: {stats.new}[/green]")
    if stats.updated:
        parts.append(f"[yellow]Updated: {stats.updated}[/yellow]")
    if stats.skipped:
        parts.append(f"[dim]Skipped: {stats.skipped}[/dim]")
    if stats.errored:
        parts.append(f"[red]Errors: {stats.errored}[/red]")

    console.print(f"[green]Done.[/green] {stats.total_chunks} chunks stored. " + " | ".join(parts))

    for fr in stats.file_results:
        if fr.status == FileStatus.ERROR:
            console.print(f"  [red]Error:[/red] {fr.path}: {fr.error}")

    suggest_next("ingest", role, role_file)
