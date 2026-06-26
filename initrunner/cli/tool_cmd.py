"""Tool sub-commands: new (LLM-scaffold a custom tool)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console

app = typer.Typer(help="Scaffold and inspect agent tools.")


@app.callback()
def _tool() -> None:
    """Scaffold and inspect agent tools."""


@app.command("new")
def tool_new(
    description: Annotated[str, typer.Argument(help="What the tool should do")],
    provider: Annotated[str | None, typer.Option(help="Model provider")] = None,
    model: Annotated[str | None, typer.Option(help="Model name")] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Module file path (default: <derived>.py in cwd)"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files")] = False,
) -> None:
    """LLM-scaffold a custom tool from a natural-language description.

    Generates a plain-Python module (referenced as a 'custom' tool) plus a
    pytest stub. The module is AST-validated, never imported during scaffolding,
    and passes through the same policy and sandbox layers as any tool when the
    agent runs.
    """
    from pydantic_ai.exceptions import ModelHTTPError
    from rich.panel import Panel
    from rich.syntax import Syntax

    from initrunner._compat import require_provider
    from initrunner.agent.loader import _load_dotenv, detect_default_model
    from initrunner.cli.new_cmd import _handle_builder_error
    from initrunner.services.tool_builder import scaffold_tool, write_scaffold

    _load_dotenv(Path.cwd())

    # Provider/model precedence mirrors `new`: CLI flags > env/run.yaml auto-detect.
    base_url: str | None = None
    api_key_env: str | None = None
    if provider is None or model is None:
        d_prov, d_model, d_base_url, d_api_key_env, _src = detect_default_model()
        if provider is None:
            provider = d_prov or "openai"
        if model is None and d_model:
            model = d_model
        base_url = d_base_url
        api_key_env = d_api_key_env

    try:
        require_provider(provider)
    except RuntimeError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None

    name_hint = output.stem if output is not None else None
    try:
        with console.status("Scaffolding tool..."):
            scaffold = scaffold_tool(
                description,
                provider,
                model,
                name_hint=name_hint,
                base_url=base_url,
                api_key_env=api_key_env,
            )
    except ModelHTTPError as exc:
        _handle_builder_error(exc, provider)
        raise typer.Exit(1) from None

    if not scaffold.module_source:
        console.print("[red]Error:[/red] the model did not produce a tool module. Try rephrasing.")
        for warning in scaffold.warnings:
            console.print(f"[yellow]-[/yellow] {warning}")
        raise typer.Exit(1)

    if scaffold.explanation:
        console.print(f"\n{scaffold.explanation}\n")
    console.print(
        Panel(
            Syntax(scaffold.module_source, "python", theme="monokai", line_numbers=False),
            title=f"{scaffold.module_name}.py",
            border_style="cyan",
        )
    )

    for warning in scaffold.warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    out_dir = output.parent if output is not None else Path.cwd()
    try:
        written = write_scaffold(scaffold, out_dir, force=force)
    except FileExistsError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None

    console.print("\n[bold]Created:[/bold]")
    for path in written:
        console.print(f"  [green]+[/green] {path}")

    console.print("\n[bold]Reference it in role.yaml:[/bold]")
    for line in scaffold.yaml_snippet.splitlines():
        console.print(f"  [dim]{line}[/dim]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. Review {scaffold.module_name}.py (it runs as plain Python).")
    console.print("  2. Add the snippet above to your role's tools.")
    console.print(
        "  3. Iterate live: [bold]initrunner run role.yaml --dev[/bold], then "
        f"[bold]/tool add {scaffold.module_name}[/bold]."
    )
