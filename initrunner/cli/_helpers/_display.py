"""Display, prompts, formatting, and installation helpers."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rich.markup import escape

from initrunner.cli._helpers._console import console

if TYPE_CHECKING:
    from collections.abc import Iterable

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.services.role_selector import SelectionResult


def ingest_status_color(status: object) -> str:
    """Map a :class:`~initrunner.ingestion.pipeline.FileStatus` to a Rich color."""
    from initrunner.ingestion.pipeline import FileStatus

    return {  # type: ignore[no-matching-overload]
        FileStatus.NEW: "green",
        FileStatus.UPDATED: "yellow",
        FileStatus.SKIPPED: "dim",
        FileStatus.ERROR: "red",
    }.get(status, "white")


def display_sense_result(result: SelectionResult) -> None:
    """Render the intent-sensed role in a Rich panel."""
    from rich.panel import Panel
    from rich.table import Table

    c = result.candidate

    # Relative path if possible
    try:
        display_path = str(c.path.relative_to(Path.cwd()))
    except ValueError:
        display_path = str(c.path)

    # Method label
    method = result.method
    if method == "only_one":
        method_str = "[dim]only role available[/dim]"
    elif method == "keyword":
        method_str = (
            f"[green]keyword match[/green] (score: {result.top_score:.2f}, gap: {result.gap:.2f})"
        )
    elif method == "llm":
        method_str = "[yellow]LLM selection[/yellow]"
    else:
        method_str = "[yellow]fallback — no strong match[/yellow]"

    tags_str = ", ".join(c.tags) if c.tags else "[dim]none[/dim]"

    table = Table.grid(padding=(0, 1))
    table.add_column(style="dim", no_wrap=True)
    table.add_column()
    table.add_row("Name", f"[cyan]{escape(c.name)}[/cyan]")
    table.add_row("File", escape(display_path))
    table.add_row("Tags", tags_str)
    table.add_row("Method", method_str)
    if c.reason:
        table.add_row("Reason", escape(c.reason))

    console.print(Panel(table, title="[bold]Intent Sensing[/bold]", border_style="dim"))


def install_extras(extras: Iterable[str]) -> bool:
    """Best-effort install of one or more initrunner extras.

    Returns ``True`` when the installer ran and succeeded.  When this install
    cannot be rebuilt safely without the user watching (a pipx venv, a checkout,
    a container, Windows) nothing is run: the command to run by hand is printed
    and this returns ``False``.
    """
    import subprocess

    from initrunner._install import install_command, manual_hint

    wanted = sorted({e for e in extras if e})
    pkg_display = escape(f"initrunner[{','.join(wanted)}]")
    cmd = install_command(wanted)
    if cmd is None:
        console.print(
            f"[yellow]Warning:[/yellow] Cannot install {pkg_display} automatically here.\n"
            f"Install manually: [bold]{escape(manual_hint(wanted))}[/bold]"
        )
        return False

    # Inherited stdio: lancedb and pymupdf can take minutes to build, and the
    # installer's own progress is the only sign that anything is happening.
    console.print(f"Installing {pkg_display}...")
    try:
        subprocess.run(cmd, check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        console.print(
            f"[yellow]Warning:[/yellow] Could not install {pkg_display}: {escape(str(exc))}\n"
            f"Install manually: [bold]{escape(shlex.join(cmd))}[/bold]"
        )
        return False
    console.print(f"[green]Installed {pkg_display}[/green]")
    return True


def prompt_model_selection(
    provider: str,
    ollama_models: list[str] | None = None,
) -> str:
    """Show model choices for a provider and return selected model name."""
    from rich.prompt import Prompt

    from initrunner.templates import PROVIDER_MODELS, _default_model_name

    if provider == "ollama" and ollama_models:
        choices = [(m, "(local)") for m in ollama_models]
    else:
        choices = PROVIDER_MODELS.get(provider, [])

    default = choices[0][0] if choices else _default_model_name(provider)

    console.print()
    console.print("[bold]Select a model:[/bold]")
    for i, (model_id, desc) in enumerate(choices, 1):
        default_tag = " (default)" if model_id == default else ""
        desc_part = f" — {desc}" if desc else ""
        console.print(f"  {i}. {model_id}{desc_part}{default_tag}")
    console.print("  Or type a custom model name (press Enter for default)")

    raw = Prompt.ask("Model", default=default)

    if raw.strip().isdigit():
        idx = int(raw.strip()) - 1
        if 0 <= idx < len(choices):
            return choices[idx][0]

    return raw.strip() or default


_NextContext = Literal["run_single", "run_autonomous", "run_repl_exit", "ingest", "validate"]


def suggest_next(context: _NextContext, role: RoleDefinition, role_path: Path) -> None:
    """Print 2-3 contextual next-step suggestions after a command."""
    if not sys.stdout.isatty():
        return

    try:
        role_ref = str(role_path.relative_to(Path.cwd()))
    except ValueError:
        role_ref = str(role_path)

    suggestions: list[tuple[str, str]] = []

    if context == "run_single":
        suggestions.append((f"initrunner run {role_ref} -i", "interactive REPL"))
        if role.spec.autonomy:
            suggestions.append((f'initrunner run {role_ref} -a -p "..."', "autonomous mode"))
        else:
            suggestions.append(
                (
                    f'initrunner run {role_ref} --report report.md -p "..."',
                    "export a report",
                )
            )

    elif context == "run_repl_exit":
        if role.spec.ingest:
            suggestions.append((f"initrunner ingest {role_ref}", "re-ingest documents"))
        if role.spec.memory:
            suggestions.append((f"initrunner memory list {role_ref}", "view stored memories"))
        if role.spec.autonomy:
            suggestions.append((f'initrunner run {role_ref} -a -p "..."', "autonomous mode"))

    elif context == "run_autonomous":
        suggestions.append((f"initrunner run {role_ref} -i", "continue interactively"))
        if role.spec.memory:
            suggestions.append((f"initrunner memory list {role_ref}", "view stored memories"))
        suggestions.append(
            (
                f'initrunner run {role_ref} --report report.md -a -p "..."',
                "export a report",
            )
        )

    elif context == "ingest":
        suggestions.append((f'initrunner run {role_ref} -p "..."', "run the agent"))
        suggestions.append((f"initrunner validate {role_ref}", "re-validate role"))

    elif context == "validate":
        suggestions.append((f'initrunner run {role_ref} -p "..."', "run the agent"))
        if role.spec.ingest:
            suggestions.append((f"initrunner ingest {role_ref}", "ingest documents"))
        suggestions.append((f"initrunner doctor --role {role_ref}", "smoke-test provider"))

    if not suggestions:
        return

    console.print()
    console.print("[dim]Next steps:[/dim]")
    for cmd, desc in suggestions[:3]:
        console.print(f"  [bold]{cmd}[/bold]  [dim]# {desc}[/dim]")
