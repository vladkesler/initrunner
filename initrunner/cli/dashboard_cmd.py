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

        @app.on_event("startup")
        async def _open_browser():
            import asyncio
            import webbrowser

            async def _wait_and_open():
                import httpx  # type: ignore[import-not-found]

                async with httpx.AsyncClient() as client:
                    for _ in range(20):
                        try:
                            r = await client.get(f"http://localhost:{port}/api/health")
                            if r.status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        await asyncio.sleep(0.25)
                webbrowser.open(f"http://localhost:{port}")

            asyncio.create_task(_wait_and_open())

    import uvicorn  # type: ignore[import-not-found]

    uvicorn.run(app, host=settings.host, port=port, log_level="warning")
