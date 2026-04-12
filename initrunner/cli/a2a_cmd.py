"""A2A commands: serve an agent as an A2A server."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console
from initrunner.cli._options import AuditDbOption, ModelOption, NoAuditOption, SkillDirOption

app = typer.Typer(help="A2A protocol server.")


@app.command("serve")
def a2a_serve(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")],
    host: Annotated[str, typer.Option(help="Host to bind to")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8000,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="API key for auth"),
    ] = None,
    cors_origin: Annotated[
        list[str] | None,
        typer.Option("--cors-origin", help="CORS origin (repeatable)"),
    ] = None,
    audit_db: AuditDbOption = None,
    no_audit: NoAuditOption = False,
    skill_dir: SkillDirOption = None,
    model: ModelOption = None,
) -> None:
    """Expose an InitRunner agent as an A2A server."""
    from initrunner._compat import require_a2a
    from initrunner.a2a.server import build_a2a_app, run_a2a_server
    from initrunner.cli._helpers import (
        command_context,
        resolve_model_override,
        resolve_skill_dirs,
    )

    require_a2a()

    resolved_model = resolve_model_override(model)
    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        extra_skill_dirs=resolve_skill_dirs(skill_dir),
        model_override=resolved_model,
    ) as (role, agent, audit_logger, _memory_store, _sink_dispatcher):
        console.print(f"[bold]A2A Server:[/bold] {role.metadata.name}")
        console.print(f"  Endpoint:   http://{host}:{port}")
        console.print(f"  Agent card: http://{host}:{port}/.well-known/agent-card.json")
        if api_key:
            console.print("  Auth:       [yellow]enabled[/yellow] (Bearer token required)")
        if cors_origin:
            console.print(f"  CORS:       {', '.join(cors_origin)}")

        a2a_app = build_a2a_app(
            agent,
            role,
            host=host,
            port=port,
            audit_logger=audit_logger,
            api_key=api_key,
            cors_origins=cors_origin,
        )
        run_a2a_server(a2a_app, host=host, port=port)
