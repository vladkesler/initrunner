"""A2A commands: serve an agent as an A2A server."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from initrunner.cli._helpers import console
from initrunner.cli._options import AuditDbOption, ModelOption, NoAuditOption, SkillDirOption

app = typer.Typer(help="A2A protocol server.")


def _default_advertise_url(host: str, port: int) -> str:
    host_for_url = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{host_for_url}:{port}"


@app.command("serve")
def a2a_serve(
    role_file: Annotated[Path, typer.Argument(help="Agent directory or role YAML file")],
    agent_member: Annotated[
        str | None,
        typer.Option("--agent", help="Which agent to serve, for a group of agents"),
    ] = None,
    host: Annotated[str, typer.Option(help="Host to bind to")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on")] = 8000,
    url: Annotated[
        str | None,
        typer.Option("--url", help="Public advertise URL written into the agent card"),
    ] = None,
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
        resolve_role_path,
        resolve_skill_dirs,
    )

    require_a2a()

    from initrunner.middleware import resolve_exposed_api_key

    # Fail closed: the A2A JSON-RPC endpoint drives the agent. Don't serve it
    # off-host without auth.
    api_key, generated_key = resolve_exposed_api_key(host, api_key)

    advertised_url = url or _default_advertise_url(host, port)
    if url is None and host in {"0.0.0.0", "::", "*"}:
        console.print(
            f"[yellow]Warning:[/yellow] binding {host} advertises a non-dialable "
            f"card URL ({advertised_url}). Pass --url with a reachable address."
        )

    # A2A serves one agent card per URL, so a group needs the member named.
    role_mutator = None
    from initrunner.cli._helpers import detect_yaml_kind

    if detect_yaml_kind(resolve_role_path(role_file)) == "Group":
        from initrunner.cli.run_cmd._group import (
            load_roster_or_exit,
            member_overlay,
            resolve_member_or_exit,
        )

        roster = load_roster_or_exit(resolve_role_path(role_file))
        if agent_member is None:
            console.print(
                "[red]Error:[/red] an A2A server serves one agent card; pick a member "
                f"with --agent. Available agents: {', '.join(roster.keys())}"
            )
            raise typer.Exit(1)
        role_file = resolve_member_or_exit(roster, agent_member)
        role_mutator = member_overlay(roster)
    elif agent_member is not None:
        console.print(
            f"[red]Error:[/red] --agent picks one member of a group, and {role_file} is"
            " not a group."
        )
        raise typer.Exit(1)

    extra_skill_dirs = resolve_skill_dirs(skill_dir)
    resolved_model = resolve_model_override(model)
    with command_context(
        role_file,
        audit_db=audit_db,
        no_audit=no_audit,
        extra_skill_dirs=extra_skill_dirs,
        model_override=resolved_model,
        role_mutator=role_mutator,
    ) as (role, agent, audit_logger, _memory_store, _sink_dispatcher):
        from initrunner.agent.skills import resolve_skills

        resolved_role = resolve_role_path(role_file)
        resolved_skills = resolve_skills(role.spec.skills, resolved_role.parent, extra_skill_dirs)

        console.print(f"[bold]A2A Server:[/bold] {role.metadata.name}")
        console.print(f"  Endpoint:   http://{host}:{port}")
        console.print(f"  Agent card: {advertised_url}/.well-known/agent-card.json")
        if generated_key is not None:
            console.print(
                "  Auth:       [yellow]enabled[/yellow] -- generated key (no --api-key given):\n"
                f"              [bold]{generated_key}[/bold]"
            )
        elif api_key:
            console.print("  Auth:       [yellow]enabled[/yellow] (Bearer token required)")
        if cors_origin:
            console.print(f"  CORS:       {', '.join(cors_origin)}")

        a2a_app = build_a2a_app(
            agent,
            role,
            url=advertised_url,
            audit_logger=audit_logger,
            api_key=api_key,
            cors_origins=cors_origin,
            skills=resolved_skills,
        )
        run_a2a_server(a2a_app, host=host, port=port)
