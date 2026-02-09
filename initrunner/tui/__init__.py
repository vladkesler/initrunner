"""TUI dashboard for InitRunner (requires textual)."""

from __future__ import annotations

from pathlib import Path


def run_tui(*, role_dir: Path | None = None) -> None:
    """Launch the interactive TUI dashboard."""
    from initrunner._log import setup_logging
    from initrunner.tui.app import InitRunnerApp

    setup_logging()
    app = InitRunnerApp(role_dir=role_dir)
    app.run()
