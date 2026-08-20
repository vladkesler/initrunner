"""Shared Rich console singleton."""

from rich.console import Console

console = Console()


def print_error(message: object, *, stderr: bool = False) -> None:
    """Print an error line, escaping Rich markup in *message*.

    Install hints read ``uv pip install initrunner[vector]``. Rich takes the
    bracket for markup and prints ``uv pip install initrunner``, which is the
    core package the user already has, so the escape is what makes the hint
    actionable rather than misleading.
    """
    from rich.markup import escape

    target = Console(stderr=True) if stderr else console
    target.print(f"[red]Error:[/red] {escape(str(message))}")
