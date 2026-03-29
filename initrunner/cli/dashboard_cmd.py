"""``initrunner dashboard`` -- launch the web UI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console


def launch_dashboard(
    *,
    port: int = 8100,
    no_open: bool = False,
    expose: bool = False,
    api_key: str | None = None,
    extra_role_dirs: list[Path] | None = None,
) -> None:
    """Start the dashboard server (blocking)."""
    from initrunner.dashboard.app import create_app  # type: ignore[import-not-found]
    from initrunner.dashboard.config import DashboardSettings  # type: ignore[import-not-found]

    settings = DashboardSettings(
        port=port,
        expose=expose,
        api_key=api_key,
        extra_role_dirs=extra_role_dirs or [],
    )

    if expose:
        if api_key:
            console.print(
                "[yellow]Warning: dashboard exposed on all interfaces "
                "-- authentication enabled[/yellow]"
            )
        else:
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


def dashboard(
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8100,
    no_open: Annotated[bool, typer.Option("--no-open", help="Don't open browser")] = False,
    expose: Annotated[bool, typer.Option("--expose", help="Bind to 0.0.0.0")] = False,
    api_key: Annotated[
        str | None,
        typer.Option(
            "--api-key",
            envvar="INITRUNNER_DASHBOARD_API_KEY",
            help="Require this API key for all requests",
        ),
    ] = None,
    roles_dir: Annotated[
        list[Path] | None,
        typer.Option("--roles-dir", help="Extra directories to scan for roles"),
    ] = None,
) -> None:
    """Launch the dashboard web UI."""
    launch_dashboard(
        port=port,
        no_open=no_open,
        expose=expose,
        api_key=api_key,
        extra_role_dirs=roles_dir,
    )
