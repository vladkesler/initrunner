"""CLI ``new`` command -- single entry point for agent creation."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.panel import Panel
from rich.syntax import Syntax

from initrunner.cli._helpers import console

if TYPE_CHECKING:
    from initrunner.services.agent_builder import BuilderSession, TurnResult


def new(
    description: Annotated[str | None, typer.Argument(help="Agent description")] = None,
    from_source: Annotated[
        str | None, typer.Option("--from", help="Source: file path, example name, or hub:ref")
    ] = None,
    template: Annotated[str | None, typer.Option("--template", help="Template name")] = None,
    blank: Annotated[bool, typer.Option("--blank", help="Start from blank template")] = False,
    provider: Annotated[str | None, typer.Option(help="Model provider")] = None,
    model: Annotated[str | None, typer.Option(help="Model name")] = None,
    output: Annotated[Path, typer.Option(help="Output file path")] = Path("role.yaml"),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing file")] = False,
    no_refine: Annotated[bool, typer.Option("--no-refine", help="Skip refinement loop")] = False,
) -> None:
    """Create a new agent role via conversational builder.

    Seed modes (mutually exclusive):
      DESCRIPTION          Generate from natural language
      --from SOURCE        Local file, example name, or hub:ref
      --template NAME      Start from a named template
      --blank              Start from minimal blank template

    Without any seed, starts an interactive conversation.
    """
    from initrunner.agent.loader import _load_dotenv
    from initrunner.services.agent_builder import BuilderSession
    from initrunner.services.roles import _detect_provider

    _load_dotenv(Path.cwd())

    # --- Mutual exclusivity check ---
    seed_count = sum(
        [
            description is not None,
            from_source is not None,
            template is not None,
            blank,
        ]
    )
    if seed_count > 1:
        console.print(
            "[red]Error:[/red] Specify at most one of: DESCRIPTION, --from, --template, --blank"
        )
        raise typer.Exit(1)

    # --- Resolve provider ---
    if provider is None:
        provider = _detect_provider()

    # --- Scaffold shortcuts (non-YAML templates) ---
    if template == "tool":
        _scaffold_tool(output, provider)
        return
    if template == "skill":
        console.print("[dim]Tip: use 'initrunner skill new <name>' instead.[/dim]")
        _scaffold_skill(output)
        return

    session = BuilderSession()

    # --- Seed ---
    try:
        turn = _seed_session(session, description, from_source, template, blank, provider, model)
    except (ValueError, FileNotFoundError, OSError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # --- Show initial result ---
    _display_turn(turn, session)

    # --- Show omitted asset warnings ---
    if session.omitted_assets:
        assets = ", ".join(session.omitted_assets)
        console.print(f"[yellow]Warning:[/yellow] Omitted sidecar files: {assets}")

    # --- Refinement loop ---
    if not no_refine:
        turn = _refinement_loop(session, turn, provider, model)
        if turn is None:
            # User quit
            console.print("[dim]Discarded.[/dim]")
            raise typer.Exit()

    # --- Save ---
    if output.exists() and not force:
        if not typer.confirm(f"{output} already exists. Overwrite?", default=False):
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit()
        force = True  # User confirmed

    try:
        result = session.save(output, force=force)
    except FileExistsError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None

    # --- Post-creation output ---
    console.print(f"\n[green]Created[/green] {result.yaml_path}")

    if not result.valid:
        for issue in result.issues:
            console.print(f"[yellow]Warning:[/yellow] {issue}")

    if result.omitted_assets:
        console.print(
            f"[dim]Note: omitted files from bundle: {', '.join(result.omitted_assets)}[/dim]"
        )

    console.print("\n[bold]Next steps:[/bold]")
    for step in result.next_steps:
        console.print(f"  {step}")


def _seed_session(
    session: BuilderSession,
    description: str | None,
    from_source: str | None,
    template: str | None,
    blank: bool,
    provider: str,
    model: str | None,
) -> TurnResult:
    """Resolve seed mode and execute it. Returns the initial TurnResult."""

    if blank:
        return session.seed_blank(provider, model)

    if template is not None:
        return session.seed_template(template, provider, model)

    if from_source is not None:
        return _seed_from_source(session, from_source, provider, model)

    if description is not None:
        with console.status("Generating..."):
            return session.seed_description(description, provider, model)

    # No seed -- interactive: ask LLM what to build
    with console.status("Generating..."):
        return session.seed_description(
            "Ask the user what kind of agent they want to build. "
            "Start by asking clarifying questions.",
            provider,
            model,
        )


def _seed_from_source(
    session: BuilderSession,
    source: str,
    provider: str,
    model: str | None,
) -> TurnResult:
    """Resolve --from SOURCE: hub ref, local file, or example name."""
    if source.startswith("hub:"):
        ref = source[4:]
        with console.status(f"Fetching from hub: {ref}..."):
            return session.seed_from_hub(ref)

    path = Path(source)
    if path.exists():
        return session.seed_from_file(path)

    # Try as example name
    return session.seed_from_example(source)


def _display_turn(turn: TurnResult, session: BuilderSession) -> None:
    """Display a TurnResult with syntax-highlighted YAML panel."""
    if turn.explanation:
        console.print(f"\n{turn.explanation}\n")

    # Build panel title
    name = "new-agent"
    if session.role and session.role.metadata.name:
        name = session.role.metadata.name

    error_count = sum(1 for i in turn.issues if i.severity == "error")
    warning_count = sum(1 for i in turn.issues if i.severity == "warning")
    if error_count:
        status = f"[red]{error_count} error(s)[/red]"
    elif warning_count:
        status = f"[yellow]{warning_count} warning(s)[/yellow]"
    else:
        status = "[green]VALID[/green]"

    syntax = Syntax(turn.yaml_text, "yaml", theme="monokai", line_numbers=False)
    panel = Panel(syntax, title=f"{name} -- {status}", border_style="cyan")
    console.print(panel)


def _refinement_loop(
    session: BuilderSession,
    turn: TurnResult,
    provider: str,
    model: str | None,
) -> TurnResult | None:
    """Interactive refinement loop. Returns final TurnResult or None if user quit."""
    while True:
        try:
            user_input = console.input('\n[bold]Refine[/bold] (empty to save, "quit" to discard): ')
        except (EOFError, KeyboardInterrupt):
            return None

        user_input = user_input.strip()

        if not user_input or user_input.lower() == "save":
            return turn

        if user_input.lower() in ("quit", "q"):
            return None

        with console.status("Refining..."):
            try:
                turn = session.refine(user_input, provider, model)
            except Exception as e:
                console.print(f"[red]Error during refinement:[/red] {e}")
                continue

        _display_turn(turn, session)


def _scaffold_tool(output: Path, provider: str) -> None:
    """Scaffold a custom tool Python module."""
    from initrunner.templates import template_tool

    py_name = output.stem.replace("-", "_")
    out_path = Path(f"{py_name}.py")
    if out_path.exists():
        console.print(f"[red]Error:[/red] {out_path} already exists.")
        raise typer.Exit(1)
    content = template_tool(py_name, provider)
    out_path.write_text(content)
    console.print(f"[green]Created[/green] {out_path}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. Edit {out_path} to add your tool functions")
    console.print("  2. Reference in role.yaml:")
    console.print("     tools:")
    console.print("       - type: custom")
    console.print(f"         module: {py_name}")


def _scaffold_skill(output: Path) -> None:
    """Scaffold a skill directory with SKILL.md."""
    from initrunner.templates import template_skill

    name = output.stem
    skill_dir_path = Path(name)
    skill_file = skill_dir_path / "SKILL.md"
    if skill_dir_path.exists():
        console.print(f"[red]Error:[/red] {skill_dir_path} already exists.")
        raise typer.Exit(1)
    skill_dir_path.mkdir(parents=True)
    content = template_skill(name, "openai")
    skill_file.write_text(content)
    console.print(f"[green]Created[/green] {skill_file}")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. Edit {skill_file} to configure tools and prompt")
    console.print("  2. Reference in role.yaml:")
    console.print("     skills:")
    console.print(f"       - {name}")
