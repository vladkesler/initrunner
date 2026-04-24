"""Export sub-commands -- convert role.yaml to other formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

app = typer.Typer(help="Export a role.yaml to other formats.")


@app.command("agent-spec")
def export_agent_spec(
    role_path: Annotated[Path, typer.Argument(help="Path to the role.yaml file")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output path (defaults to <name>.agent-spec.yaml)"),
    ] = None,
    with_schema: Annotated[
        bool,
        typer.Option(
            "--with-schema/--no-schema",
            help="Also write a companion JSON Schema for editor autocomplete",
        ),
    ] = True,
) -> None:
    """Convert a role.yaml to a PydanticAI Agent Spec YAML."""
    import yaml

    from initrunner.agent.loader import RoleLoadError, load_role
    from initrunner.services.agent_spec_export import role_to_agent_spec

    if not role_path.exists():
        console.print(f"[red]Error:[/red] Role file not found: {role_path}")
        raise typer.Exit(1)

    try:
        role = load_role(role_path)
    except RoleLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    spec_dict, dropped = role_to_agent_spec(role)

    out_path = output or role_path.with_suffix("").with_name(
        f"{role.metadata.name}.agent-spec.yaml"
    )
    out_path.write_text(yaml.safe_dump(spec_dict, sort_keys=False), encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out_path}")

    if with_schema:
        try:
            from pydantic_ai.agent.spec import AgentSpec
        except ImportError:
            console.print(
                "[yellow]Skipping schema:[/yellow] pydantic_ai.agent.spec not importable."
            )
        else:
            schema_path = out_path.with_suffix(".schema.json")
            schema_path.write_text(
                json.dumps(AgentSpec.model_json_schema(), indent=2), encoding="utf-8"
            )
            console.print(f"[green]Wrote[/green] {schema_path}")

    if dropped.names:
        from rich.table import Table

        table = Table(title="Dropped sections (no Agent-Spec analogue)")
        table.add_column("Section", style="yellow")
        for name in dropped.names:
            table.add_row(name)
        console.print(table)
        console.print(
            "[dim]These are InitRunner-specific. The emitted spec covers only what "
            "PydanticAI's Agent Spec models.[/dim]"
        )
