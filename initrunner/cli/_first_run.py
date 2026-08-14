"""First-run jobs menu shared by bare ``initrunner`` and ``setup``.

Presentation and dispatch only — not business logic.
"""

from __future__ import annotations

from pathlib import Path

from rich.panel import Panel
from rich.prompt import Prompt

from initrunner.cli._helpers import console

# Choice keys
CHAT = "chat"
STARTER = "starter"
NEW = "new"
DASHBOARD = "dashboard"


def configured_menu_options(*, include_dashboard: bool) -> list[tuple[str, str]]:
    """Return (label, key) pairs. Dashboard is last when included."""
    options: list[tuple[str, str]] = [
        ("Chat", CHAT),
        ("Try a starter", STARTER),
        ("Create an agent", NEW),
    ]
    if include_dashboard:
        options.append(("Dashboard (web UI)", DASHBOARD))
    return options


def setup_menu_options() -> list[tuple[str, str]]:
    """Setup next-action jobs. Dashboard is never in this list."""
    return configured_menu_options(include_dashboard=False)


def prompt_job_menu(
    options: list[tuple[str, str]],
    *,
    question: str = "What would you like to do?",
) -> str:
    """Numbered menu. Enter selects the first option (Chat)."""
    console.print()
    for i, (label, _key) in enumerate(options, 1):
        console.print(f"  [bold]{i}[/bold]. {label}")

    choice = Prompt.ask(
        f"\n{question}",
        choices=[str(i) for i in range(1, len(options) + 1)],
        default="1",
    )
    return options[int(choice) - 1][1]


def list_menu_starters() -> list:
    """First-hour starters that are Ready on this machine.

    Preference order from ``FIRST_HOUR_STARTERS``. Team entries are
    included only in a git checkout (they launch with ``-p``).
    """
    from initrunner.services.starters import (
        FIRST_HOUR_STARTERS,
        check_prerequisites,
        is_git_checkout,
        list_starters,
    )

    by_slug = {e.slug: e for e in list_starters()}
    ready = []
    for slug in FIRST_HOUR_STARTERS:
        entry = by_slug.get(slug)
        if entry is None:
            continue
        if entry.kind == "Team" and not is_git_checkout():
            continue
        if entry.kind == "Flow":
            continue
        errors, _warnings = check_prerequisites(entry)
        if errors:
            continue
        ready.append(entry)
    return ready


def prompt_starter_submenu() -> str | None:
    """Pick a ready starter slug, or ``None`` if none / cancelled."""
    starters = list_menu_starters()
    if not starters:
        console.print("[dim]No ready starters right now. Chat or create an agent instead.[/dim]")
        return None

    console.print()
    console.print("[bold]Starters that work with your current setup:[/bold]")
    for i, entry in enumerate(starters, 1):
        desc = entry.description.split("\n")[0].strip()
        if len(desc) > 60:
            desc = desc[:57] + "..."
        console.print(f"  [bold]{i}[/bold]. {entry.slug}  [dim]{desc}[/dim]")

    choice = Prompt.ask(
        "\nStarter",
        choices=[str(i) for i in range(1, len(starters) + 1)],
        default="1",
    )
    return starters[int(choice) - 1].slug


def dispatch_first_run_choice(key: str) -> None:
    """Run the selected first-run job."""
    if key == CHAT:
        from initrunner.cli._ephemeral import dispatch_ephemeral

        dispatch_ephemeral()
        return
    if key == STARTER:
        slug = prompt_starter_submenu()
        if slug is None:
            return
        from initrunner.cli.run_cmd import run
        from initrunner.services.starters import get_starter

        entry = get_starter(slug)
        if entry is not None and entry.kind == "Team":
            task = Prompt.ask("What should the team work on?")
            run(role_file=Path(slug), prompt=task)
            return
        run(role_file=Path(slug), interactive=True)
        return
    if key == NEW:
        from initrunner.cli.new_cmd import new

        new()
        return
    if key == DASHBOARD:
        from initrunner.cli.dashboard_cmd import launch_dashboard

        launch_dashboard()
        return
    raise ValueError(f"unknown first-run choice: {key}")


def print_next_steps_panel() -> None:
    """Static next-steps for non-TTY / ``-y`` setup."""
    console.print(
        Panel(
            "\n".join(
                [
                    "  [dim]Chat:[/dim]",
                    "  [bold]initrunner run -i[/bold]",
                    "",
                    "  [dim]Try a starter:[/dim]",
                    "  [bold]initrunner run memory -i[/bold]"
                    "          [dim]# remembers across sessions[/dim]",
                    "",
                    "  [dim]Or create your own:[/dim]",
                    "  [bold]initrunner new[/bold]",
                ]
            ),
            title="Next steps",
            border_style="cyan",
        )
    )
