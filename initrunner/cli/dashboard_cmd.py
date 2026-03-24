"""``initrunner dashboard`` -- launch the web UI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console


def dashboard(
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8100,
    no_open: Annotated[bool, typer.Option("--no-open", help="Don't open browser")] = False,
    expose: Annotated[bool, typer.Option("--expose", help="Bind to 0.0.0.0 (no auth)")] = False,
    roles_dir: Annotated[
        list[Path] | None,
        typer.Option("--roles-dir", help="Extra directories to scan for roles"),
    ] = None,
) -> None:
    """Launch the dashboard web UI."""
    from initrunner.dashboard.app import create_app
    from initrunner.dashboard.config import DashboardSettings

    settings = DashboardSettings(
        port=port,
        expose=expose,
        extra_role_dirs=roles_dir or [],
    )

    if expose:
        console.print(
            "[yellow]Warning: dashboard exposed on all interfaces "
            "-- no authentication enabled[/yellow]"
        )

    app = create_app(settings)

    url = f"http://{'0.0.0.0' if expose else 'localhost'}:{port}"
    console.print(f"[bold]InitRunner Dashboard[/bold] at [link={url}]{url}[/link]")

    if not no_open:
        import threading

        def _open_when_ready() -> None:
            import time
            import urllib.request
            import webbrowser

            for _ in range(20):
                try:
                    with urllib.request.urlopen(
                        f"http://localhost:{port}/api/health", timeout=2
                    ) as resp:
                        if resp.status == 200:
                            webbrowser.open(f"http://localhost:{port}")
                            return
                except Exception:
                    pass
                time.sleep(0.25)

        threading.Thread(target=_open_when_ready, daemon=True).start()

    import uvicorn  # type: ignore[import-not-found]

    uvicorn.run(app, host=settings.host, port=port, log_level="warning")
