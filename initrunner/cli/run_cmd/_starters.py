"""Starter agent listing and save-to-local helpers."""

from __future__ import annotations

from pathlib import Path

import typer

from initrunner.cli._helpers import console


def _show_starter_listing() -> None:
    """Render a Rich table of available starter agents."""
    from rich.table import Table

    from initrunner.services.starters import check_prerequisites, list_starters

    starters = list_starters()
    if not starters:
        console.print("[dim]No starter agents found.[/dim]")
        return

    table = Table(title="Starter Agents", show_lines=False, pad_edge=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Kind", style="dim")
    table.add_column("Description")
    table.add_column("Features", style="green")
    table.add_column("Status")

    for entry in starters:
        errors, _warnings = check_prerequisites(entry)
        if errors:
            status = f"[yellow]{errors[0]}[/yellow]"
        else:
            status = "[green]Ready[/green]"

        desc = entry.description
        if len(desc) > 50:
            desc = desc[:47] + "..."

        table.add_row(
            entry.slug,
            entry.kind,
            desc,
            " ".join(entry.features),
            status,
        )

    console.print()
    console.print(table)
    console.print()
    console.print("[dim]Usage:[/dim]")
    console.print("  initrunner run <name>              Run interactively")
    console.print('  initrunner run <name> -p "..."      Single-shot with prompt')
    console.print("  initrunner run <name> --save .      Copy to local directory for customization")
    console.print()


def _handle_save(role_file: Path, save_dir: Path) -> None:
    """Copy a starter to a local directory."""
    import shutil

    from initrunner.services.starters import STARTERS_DIR

    try:
        if not role_file.resolve().is_relative_to(STARTERS_DIR.resolve()):
            console.print("[red]Error:[/red] --save only works with bundled starters.")
            raise typer.Exit(1)
    except ValueError:
        console.print("[red]Error:[/red] --save only works with bundled starters.")
        raise typer.Exit(1) from None

    starter_dir = role_file.parent
    save_dir.mkdir(parents=True, exist_ok=True)

    if starter_dir.resolve() == STARTERS_DIR.resolve():
        # Single-file starter
        dest = save_dir / "role.yaml"
        shutil.copy2(role_file, dest)
        console.print(f"[green]Copied[/green] {role_file.name} to {dest}")
    else:
        # Composite starter (subdirectory)
        for item in starter_dir.iterdir():
            src = starter_dir / item.name
            dst = save_dir / item.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        console.print(f"[green]Copied[/green] {starter_dir.name}/ to {save_dir}")

    console.print()
    console.print("[dim]Next steps:[/dim]")
    edit_target = save_dir / "role.yaml" if (save_dir / "role.yaml").exists() else save_dir
    console.print(f"  1. Edit {edit_target}")
    console.print(f"  2. initrunner run {save_dir} -i")
    console.print()
