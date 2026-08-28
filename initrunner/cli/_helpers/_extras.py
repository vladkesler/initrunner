"""Offering to install a missing extra, and rerunning the command afterwards."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, NoReturn

import typer
from rich.markup import escape

from initrunner.cli._helpers._console import console

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Sequence as _Sequence


def _console(stderr: bool):
    """The console to talk on.

    ``mcp serve`` owns stdout for the protocol, so every line this helper prints
    in that case has to go to stderr, the hint included.
    """
    if not stderr:
        return console
    from rich.console import Console

    return Console(stderr=True)


def _is_interactive() -> bool:
    """True when there is a person to answer the prompt.

    ``CI`` is honoured because a green pipeline that quietly installs a
    dependency hides the fact that the image is missing it.
    """
    from initrunner._install import was_reexeced

    if was_reexeced():
        # The install already ran once and the extra is still missing; asking
        # again would loop.
        return False
    if os.environ.get("CI"):
        return False
    return sys.stdin.isatty() and sys.stdout.isatty()


def _reexec(argv: _Sequence[str]) -> NoReturn:
    """Replace this process with the same command, now that the extra is there.

    ``python -m initrunner`` rather than ``sys.argv[0]``: the console script and
    ``python -m`` both land in ``app_entry``, and the module form works even
    when the entry point was just rewritten by the installer.
    """
    from initrunner._install import REEXEC_ENV_VAR

    os.environ[REEXEC_ENV_VAR] = "1"
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, "-m", "initrunner", *argv])


def offer_install(extras: Iterable[str], *, needed_by: str, stderr: bool = False) -> NoReturn:
    """Report a missing extra, offer to install it, and rerun the command.

    Always exits: either by re-executing the command once the extra is in place,
    or by raising ``typer.Exit(1)``.  On anything but an interactive terminal
    with an install method that can be rebuilt safely, this only prints the
    command to run by hand.
    """
    from initrunner._install import install_command, manual_hint

    out = _console(stderr)
    wanted = sorted({e for e in extras if e})
    spec = escape(f"initrunner[{','.join(wanted)}]")
    out.print(f"[red]Error:[/red] {escape(needed_by)} needs {spec}")

    if not _is_interactive() or install_command(wanted) is None:
        out.print(f"Install it with: [bold]{escape(manual_hint(wanted))}[/bold]")
        raise typer.Exit(1)

    try:
        proceed = typer.confirm("Install now?", default=True)
    except (KeyboardInterrupt, EOFError, typer.Abort):
        out.print("\n[dim]Cancelled.[/dim]")
        raise typer.Exit(1) from None

    if not proceed:
        out.print(f"Install it with: [bold]{escape(manual_hint(wanted))}[/bold]")
        raise typer.Exit(1)

    from initrunner.cli._helpers._display import install_extras

    if not install_extras(wanted):
        raise typer.Exit(1)

    _reexec(sys.argv[1:])
