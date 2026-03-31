"""Doctor command: provider configuration check, quickstart smoke test, and --fix."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from initrunner.cli._helpers import console


def doctor(
    quickstart: Annotated[
        bool, typer.Option("--quickstart", help="Run a smoke prompt to verify end-to-end")
    ] = False,
    role_file: Annotated[
        Path | None, typer.Option("--role", help="Agent directory or role YAML file to test")
    ] = None,
    fix: Annotated[
        bool, typer.Option("--fix", help="Interactively repair detected issues")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Auto-confirm all fix prompts")] = False,
) -> None:
    """Check provider configuration, API keys, and connectivity."""
    import os

    from initrunner._compat import require_provider
    from initrunner.agent.loader import _load_dotenv
    from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT as _PROVIDER_API_KEY_ENVS

    if fix and not yes and not sys.stdin.isatty():
        console.print("[red]Error:[/red] --fix requires --yes in non-interactive mode.")
        raise typer.Exit(1)

    if role_file is not None:
        from initrunner.cli._helpers import resolve_role_path

        role_file = resolve_role_path(role_file)

    # Load .env so that .env-only setups are detected
    if role_file is not None:
        _load_dotenv(role_file.parent)
    else:
        _load_dotenv(Path.cwd())

    # ----- Step 1: Config scan (always) -----
    table = Table(title="Provider Status")
    table.add_column("Provider", style="cyan")
    table.add_column("API Key")
    table.add_column("SDK")
    table.add_column("Status")

    for provider, env_var in _PROVIDER_API_KEY_ENVS.items():
        key_set = bool(os.environ.get(env_var))
        key_status = "[green]Set[/green]" if key_set else "[dim]Missing[/dim]"

        sdk_status = "[dim]—[/dim]"
        if key_set:
            try:
                require_provider(provider)
                sdk_status = "[green]OK[/green]"
            except RuntimeError:
                sdk_status = "[yellow]Missing[/yellow]"

        if key_set:
            status = "[green]Ready[/green]"
        else:
            status = "[dim]Not configured[/dim]"

        table.add_row(provider, key_status, sdk_status, status)

    # Ollama row
    from initrunner.services.providers import is_ollama_running

    ollama_ready = "[green]Ready[/green]" if is_ollama_running() else "[dim]Not running[/dim]"

    table.add_row("ollama", "[dim]—[/dim]", "[dim]—[/dim]", ollama_ready)

    # Docker row
    try:
        from initrunner.agent.docker_sandbox import check_docker_available

        docker_status = (
            "[green]Ready[/green]" if check_docker_available() else "[dim]Not available[/dim]"
        )
    except Exception:
        docker_status = "[dim]Not available[/dim]"
    table.add_row("docker", "[dim]—[/dim]", "[dim]—[/dim]", docker_status)

    console.print(table)

    # ----- Embedding Providers -----
    from initrunner.ingestion.embeddings import _PROVIDER_EMBEDDING_KEY_DEFAULTS

    embed_table = Table(title="Embedding Providers")
    embed_table.add_column("Provider", style="cyan")
    embed_table.add_column("Embedding Key Env")
    embed_table.add_column("Status")

    for emb_provider, emb_env in _PROVIDER_EMBEDDING_KEY_DEFAULTS.items():
        emb_key_set = bool(os.environ.get(emb_env))
        emb_status = "[green]Set[/green]" if emb_key_set else "[dim]Missing[/dim]"
        embed_table.add_row(emb_provider, emb_env, emb_status)

    embed_table.add_row("ollama", "[dim]—[/dim]", "[dim]No key needed[/dim]")

    console.print()
    console.print(embed_table)
    console.print(
        "[dim]Note: Anthropic uses OpenAI embeddings (OPENAI_API_KEY) for RAG/memory.[/dim]"
    )

    # ----- Fix: providers (when --fix) -----
    fixed: list[str] = []
    if fix:
        fixed.extend(_fix_providers(role_file, yes))

    # ----- Role Validation (when --role provided) -----
    has_role_errors = False
    if role_file is not None:
        has_role_errors, role_fixed = _check_and_fix_role_health(role_file, fix=fix, yes=yes)
        fixed.extend(role_fixed)

    # ----- Fix summary -----
    if fixed:
        console.print()
        console.print(
            Panel(
                "\n".join(f"  {item}" for item in fixed),
                title="Fixed",
                border_style="green",
            )
        )

    if not quickstart or has_role_errors:
        if has_role_errors:
            raise typer.Exit(1)
        return

    # ----- Step 2: Smoke test (--quickstart) -----
    console.print()
    console.print("[bold]Running quickstart smoke test...[/bold]")

    try:
        if role_file is not None:
            from initrunner.agent.loader import load_and_build

            role, agent = load_and_build(role_file)
        else:
            from initrunner.agent.loader import build_agent
            from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
            from initrunner.agent.schema.guardrails import Guardrails
            from initrunner.agent.schema.role import AgentSpec, RoleDefinition
            from initrunner.services.roles import _detect_provider
            from initrunner.templates import _default_model_name

            detected_provider = _detect_provider()
            model_name = _default_model_name(detected_provider)
            role = RoleDefinition(
                apiVersion=ApiVersion.V1,
                kind=Kind.AGENT,
                metadata=RoleMetadata(name="doctor-quickstart", spec_version=2),
                spec=AgentSpec(
                    role="You are a helpful assistant.",
                    model=ModelConfig(provider=detected_provider, name=model_name),
                    guardrails=Guardrails(timeout_seconds=60),
                ),
            )
            agent = build_agent(role, role_dir=None)

        from initrunner.services.execution import execute_run_sync

        with console.status("Running smoke prompt...", spinner="dots"):
            result, _ = execute_run_sync(agent, role, "Say hello in one sentence.")

        if result.success:
            preview = result.output[:200]
            console.print(
                Panel(
                    f"[green]Smoke test passed![/green]\n\n"
                    f"[bold]Response:[/bold] {preview}\n"
                    f"[bold]Tokens:[/bold] {result.total_tokens} | "
                    f"[bold]Duration:[/bold] {result.duration_ms}ms",
                    title="Quickstart Result",
                    border_style="green",
                )
            )
        else:
            console.print(
                Panel(
                    f"[red]Smoke test failed:[/red] {result.error}",
                    title="Quickstart Result",
                    border_style="red",
                )
            )
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as exc:
        console.print(
            Panel(
                f"[red]Smoke test error:[/red] {exc}",
                title="Quickstart Result",
                border_style="red",
            )
        )
        raise typer.Exit(1) from None


# ---------------------------------------------------------------------------
# --fix: provider SDK + API key repair
# ---------------------------------------------------------------------------


def _fix_providers(role_file: Path | None, yes: bool) -> list[str]:
    """Offer to install missing SDKs and set a targeted API key. Returns fix descriptions."""
    from initrunner.cli._helpers import handle_api_key, install_extra
    from initrunner.config import get_global_env_path
    from initrunner.services.doctor import derive_role_provider, diagnose_providers

    diagnoses = diagnose_providers()
    fixed: list[str] = []

    # --- SDK installs ---
    for d in diagnoses:
        if not d.fixable_sdk:
            continue
        if yes or typer.confirm(f"Install SDK for {d.provider}?", default=True):
            if install_extra(d.extras_name):  # type: ignore[arg-type]
                fixed.append(f"Installed initrunner[{d.extras_name}]")

    # --- Targeted API key ---
    target: tuple[str, str] | None = None

    if role_file is not None:
        from initrunner._yaml import load_raw_yaml

        try:
            raw = load_raw_yaml(role_file, ValueError)
            target = derive_role_provider(raw)
        except Exception:
            pass
    else:
        key_fixable = [d for d in diagnoses if d.fixable_key]
        if len(key_fixable) == 1:
            target = (key_fixable[0].provider, key_fixable[0].env_var)
        elif len(key_fixable) > 1:
            if yes:
                console.print(
                    "[dim]Multiple providers need API keys; "
                    "pass --role to target one, or run interactively.[/dim]"
                )
            else:
                console.print()
                console.print("[bold]Multiple providers need an API key:[/bold]")
                for i, d in enumerate(key_fixable, 1):
                    console.print(f"  {i}. {d.provider} ({d.env_var})")
                from rich.prompt import Prompt

                choice = Prompt.ask(
                    "Which provider?",
                    choices=[str(i) for i in range(1, len(key_fixable) + 1)],
                )
                picked = key_fixable[int(choice) - 1]
                target = (picked.provider, picked.env_var)

    if target is not None:
        provider, env_var = target
        import os

        if not os.environ.get(env_var):
            if yes:
                # API keys require interactive input; can't auto-confirm.
                console.print(f"[dim]Set {env_var} manually or re-run without --yes.[/dim]")
            elif typer.confirm(f"Set API key for {provider} ({env_var})?", default=True):
                validate_prov = provider if provider in ("openai", "anthropic") else None
                handle_api_key(env_var, get_global_env_path(), validate_provider=validate_prov)
                fixed.append(f"Set {env_var}")

    return fixed


# ---------------------------------------------------------------------------
# Role health check + fix
# ---------------------------------------------------------------------------


def _check_and_fix_role_health(path: Path, *, fix: bool, yes: bool) -> tuple[bool, list[str]]:
    """Validate a role file, optionally fix issues.

    Returns ``(has_errors, list_of_fix_descriptions)``.
    """
    from initrunner._yaml import load_raw_yaml
    from initrunner.deprecations import CURRENT_ROLE_SPEC_VERSION, inspect_role_data

    console.print()
    fixed: list[str] = []

    # Stage 1: parse YAML
    try:
        raw = load_raw_yaml(path, ValueError)
    except Exception as exc:
        console.print(
            Panel(
                f"[red]Cannot read role file:[/red] {exc}",
                title="Role Validation",
                border_style="red",
            )
        )
        return True, fixed

    # Stage 2: inspect (non-raising except future version)
    try:
        inspection = inspect_role_data(raw)
    except ValueError as exc:
        console.print(
            Panel(
                f"[red]{exc}[/red]",
                title="Role Validation",
                border_style="red",
            )
        )
        return True, fixed

    role_name = raw.get("metadata", {}).get("name", path.stem)
    has_errors = False

    # Display deprecation hits
    if inspection.hits:
        hit_table = Table(
            title=f"Role Validation: {role_name} "
            f"(spec_version: {inspection.spec_version}, "
            f"current: {CURRENT_ROLE_SPEC_VERSION})"
        )
        hit_table.add_column("ID", style="cyan")
        hit_table.add_column("Severity")
        hit_table.add_column("Issue")
        hit_table.add_column("Status")

        for hit in inspection.hits:
            severity_style = "red" if hit.severity == "error" else "yellow"
            hit_table.add_row(
                hit.id,
                f"[{severity_style}]{hit.severity}[/{severity_style}]",
                hit.message,
                "[green]auto-fixed[/green]" if hit.auto_fixed else "[red]manual fix[/red]",
            )
            if hit.severity == "error":
                has_errors = True

        console.print(hit_table)

    # Display schema errors
    if inspection.schema_error:
        has_errors = True
        console.print(
            Panel(
                f"[red]{inspection.schema_error}[/red]",
                title="Schema Error",
                border_style="red",
            )
        )

    # Summary
    if not has_errors:
        if inspection.spec_version < CURRENT_ROLE_SPEC_VERSION:
            console.print("[green]Role is valid.[/green]")
            console.print(
                f"[dim]spec_version {inspection.spec_version} is behind "
                f"current {CURRENT_ROLE_SPEC_VERSION}.[/dim]"
            )
        else:
            console.print("[green]Role is valid and up to date.[/green]")

    # ----- Fix: role extras + spec_version -----
    if fix:
        fixed.extend(_fix_role(path, raw, yes))

    return has_errors, fixed


def _fix_role(path: Path, raw: dict, yes: bool) -> list[str]:
    """Apply role-level fixes: missing extras and spec_version bump."""
    from initrunner.cli._helpers import install_extra
    from initrunner.services.doctor import build_role_fix_plan, bump_spec_version_text

    plan = build_role_fix_plan(raw)
    fixed: list[str] = []

    # --- Missing extras ---
    for gap in plan.missing_extras:
        if yes or typer.confirm(
            f"Install initrunner[{gap.extras_name}] (needed by {gap.feature})?", default=True
        ):
            if install_extra(gap.extras_name):
                fixed.append(f"Installed initrunner[{gap.extras_name}]")

    # --- Spec version bump (surgical text edit, preserves formatting) ---
    if plan.can_bump_spec_version:
        if yes or typer.confirm(f"Bump spec_version to {plan.latest_spec_version}?", default=True):
            try:
                text = path.read_text(encoding="utf-8")
                text = bump_spec_version_text(text, plan.latest_spec_version)
                path.write_text(text, encoding="utf-8")
                fixed.append(f"Bumped spec_version to {plan.latest_spec_version}")
            except ValueError as exc:
                console.print(f"[yellow]Warning:[/yellow] {exc}")

    return fixed
