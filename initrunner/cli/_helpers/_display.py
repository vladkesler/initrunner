"""Display, prompts, formatting, and installation helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from rich.markup import escape

from initrunner.cli._helpers._console import console

if TYPE_CHECKING:
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


def install_extra(extra: str) -> bool:
    """Best-effort install of an initrunner extra. Returns True on success."""
    import shutil
    import subprocess
    import sys

    pkg = f"initrunner[{extra}]"
    pkg_display = escape(pkg)

    exe = sys.executable.replace("\\", "/")
    if "/uv/tools/" in exe and shutil.which("uv"):
        cmd = ["uv", "tool", "install", "--force", pkg]
    elif "/pipx/venvs/" in exe:
        if shutil.which("pipx"):
            cmd = ["pipx", "install", "--force", pkg]
        else:
            cmd = [sys.executable, "-m", "pip", "install", pkg]
    elif shutil.which("uv"):
        cmd = ["uv", "pip", "install", pkg]
    else:
        cmd = [sys.executable, "-m", "pip", "install", pkg]

    try:
        with console.status(f"Installing {pkg_display}..."):
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        console.print(f"[green]Installed {pkg_display}[/green]")
        return True
    except (subprocess.CalledProcessError, OSError) as exc:
        console.print(
            f"[yellow]Warning:[/yellow] Could not install {pkg_display}: {escape(str(exc))}\n"
            f"Install manually: [bold]{escape(' '.join(cmd))}[/bold]"
        )
        return False


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
