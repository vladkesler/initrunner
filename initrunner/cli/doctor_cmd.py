"""Doctor command: provider configuration check, quickstart smoke test, and --fix."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from initrunner.cli._helpers import console
from initrunner.cli._options import SkillDirOption


def doctor(
    quickstart: Annotated[
        bool, typer.Option("--quickstart", help="Run a smoke prompt to verify end-to-end")
    ] = False,
    role_file: Annotated[
        Path | None, typer.Option("--role", help="Agent directory or role YAML file to test")
    ] = None,
    flow_file: Annotated[
        Path | None, typer.Option("--flow", help="Flow YAML file to validate")
    ] = None,
    deep: Annotated[
        bool,
        typer.Option("--deep", help="Run active checks (MCP connectivity, tool imports, DB open)"),
    ] = False,
    skill_dir: SkillDirOption = None,
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

    # ----- Flag interaction validation -----
    if flow_file is not None and role_file is not None:
        console.print("[red]Error:[/red] --flow and --role are mutually exclusive.")
        raise typer.Exit(1)
    if flow_file is not None and quickstart:
        console.print("[red]Error:[/red] --flow and --quickstart are mutually exclusive.")
        raise typer.Exit(1)
    if flow_file is not None and fix:
        console.print("[red]Error:[/red] --flow and --fix are mutually exclusive.")
        raise typer.Exit(1)
    if deep and role_file is None and flow_file is None:
        console.print("[red]Error:[/red] --deep requires --role or --flow.")
        raise typer.Exit(1)
    if skill_dir is not None and role_file is None and flow_file is None:
        console.print("[red]Error:[/red] --skill-dir requires --role or --flow.")
        raise typer.Exit(1)

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
        has_role_errors, role_fixed = _check_and_fix_role_health(
            role_file, fix=fix, yes=yes, deep=deep, skill_dir=skill_dir
        )
        fixed.extend(role_fixed)

    # ----- Flow Validation (when --flow provided) -----
    has_flow_errors = False
    if flow_file is not None:
        has_flow_errors = _check_flow_health(flow_file, deep=deep, skill_dir=skill_dir)

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

    if has_flow_errors:
        raise typer.Exit(1)

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


def _check_and_fix_role_health(
    path: Path,
    *,
    fix: bool,
    yes: bool,
    deep: bool = False,
    skill_dir: Path | None = None,
) -> tuple[bool, list[str]]:
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
            if hit.auto_fixed:
                status_label = "[cyan]auto-fixable[/cyan]"
            else:
                status_label = "[red]manual fix[/red]"
            hit_table.add_row(
                hit.id,
                f"[{severity_style}]{hit.severity}[/{severity_style}]",
                hit.message,
                status_label,
            )
            if hit.severity == "error" and not hit.auto_fixed:
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

    # ----- Security posture check -----
    if inspection.role is not None:
        from initrunner.services.doctor import diagnose_security

        sec_diag = diagnose_security(inspection.role)
        if sec_diag.warning:
            console.print(f"  [yellow]Warning:[/yellow] {sec_diag.warning}")
        if sec_diag.policy_dir_set:
            console.print("  [dim]Agent policy (initguard): configured[/dim]")

    # ----- Extended diagnostics -----
    if inspection.role is not None:
        from initrunner.cli._helpers import resolve_skill_dirs
        from initrunner.services.doctor import diagnose_role_deep

        extra_dirs = resolve_skill_dirs(skill_dir)
        diag = diagnose_role_deep(
            inspection.role, path.parent, deep=deep, extra_skill_dirs=extra_dirs
        )
        _render_role_diagnostics(diag)

    # ----- Fix: role extras + spec_version -----
    if fix:
        role_fixed = _fix_role(path, raw, yes)
        fixed.extend(role_fixed)
        # Re-inspect after fixes to update has_errors status
        if role_fixed and has_errors:
            try:
                re_raw = load_raw_yaml(path, ValueError)
                re_inspection = inspect_role_data(re_raw)
                remaining_errors = [
                    h for h in re_inspection.hits if h.severity == "error" and not h.auto_fixed
                ]
                if not remaining_errors and not re_inspection.schema_error:
                    has_errors = False
            except Exception:
                pass  # keep original has_errors

    return has_errors, fixed


def _fix_role(path: Path, raw: dict, yes: bool) -> list[str]:
    """Apply role-level fixes: missing extras, deprecation patches, and spec_version bump."""
    import yaml

    from initrunner.cli._helpers import install_extra
    from initrunner.services.doctor import (
        build_role_fix_plan,
        bump_spec_version_text,
        patch_deprecation_text,
    )

    plan = build_role_fix_plan(raw)
    fixed: list[str] = []

    # --- Missing extras ---
    for gap in plan.missing_extras:
        if yes or typer.confirm(
            f"Install initrunner[{gap.extras_name}] (needed by {gap.feature})?", default=True
        ):
            if install_extra(gap.extras_name):
                fixed.append(f"Installed initrunner[{gap.extras_name}]")

    # --- Fixable deprecations (surgical text edit, preserves formatting) ---
    applied_deprecation_fixes = False
    for hit in plan.fixable_deprecations:
        label = f"Fix {hit.id} ({hit.field_path}: {hit.original_value} -> "
        if hit.id == "DEP001":
            label += "memory.semantic.max_memories)"
        else:
            label += "lancedb)"
        if yes or typer.confirm(f"{label}?", default=True):
            try:
                text = path.read_text(encoding="utf-8")
                text = patch_deprecation_text(text, hit)
                path.write_text(text, encoding="utf-8")
                fixed.append(f"Fixed {hit.id}: {hit.field_path}")
                applied_deprecation_fixes = True
            except ValueError as exc:
                console.print(f"[yellow]Warning:[/yellow] {exc}")

    # After deprecation fixes, re-evaluate for spec_version bump
    if applied_deprecation_fixes:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        plan = build_role_fix_plan(raw)

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


# ---------------------------------------------------------------------------
# Extended diagnostics rendering
# ---------------------------------------------------------------------------


def _render_role_diagnostics(diag: object, *, indent: str = "") -> None:
    """Render a RoleDiagnostics as a Rich table."""
    from initrunner.services.doctor import RoleDiagnostics

    assert isinstance(diag, RoleDiagnostics)

    # Skip if there's nothing to show
    if (
        not diag.mcp_servers
        and not diag.skills
        and not diag.custom_tools
        and diag.memory_store is None
        and not diag.triggers
        and diag.docker is None
    ):
        return

    table = Table(title=f"{indent}Role Diagnostics")
    table.add_column("Category", style="cyan")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Details")

    for mcp in diag.mcp_servers:
        if mcp.status == "healthy":
            status = "[green]ok[/green]"
            details = f"{mcp.latency_ms}ms, {mcp.tool_count} tools"
        elif mcp.status == "degraded":
            status = "[yellow]degraded[/yellow]"
            details = f"{mcp.latency_ms}ms, {mcp.tool_count} tools"
        elif mcp.status == "skipped":
            status = "[dim]skipped[/dim]"
            details = "use --deep to check"
        else:
            status = "[red]unhealthy[/red]"
            details = mcp.error or "connection failed"
        table.add_row("mcp", mcp.server_label, status, details)

    for skill in diag.skills:
        if skill.resolved and not skill.unmet_requirements:
            status = "[green]ok[/green]"
            details = str(skill.source_path)
        elif skill.resolved:
            status = "[yellow]warn[/yellow]"
            n = len(skill.unmet_requirements)
            details = f"{n} unmet: {', '.join(skill.unmet_requirements)}"
        else:
            status = "[red]fail[/red]"
            details = skill.error or "not found"
        table.add_row("skill", skill.ref, status, details)

    for ct in diag.custom_tools:
        label = ct.module
        if ct.function:
            label += f".{ct.function}"
        if ct.sandbox_violation:
            status = "[red]fail[/red]"
            details = ct.sandbox_violation
        elif not ct.locatable:
            status = "[red]fail[/red]"
            details = ct.error or "module not found"
        elif ct.importable is False:
            status = "[red]fail[/red]"
            details = ct.error or "import failed"
        elif ct.callable_found is False:
            status = "[red]fail[/red]"
            details = ct.error or "function not found"
        elif ct.importable is True:
            status = "[green]ok[/green]"
            details = "importable"
        else:
            status = "[green]ok[/green]"
            details = "locatable"
        table.add_row("custom tool", label, status, details)

    if diag.memory_store is not None:
        ms = diag.memory_store
        if not ms.parent_exists:
            status = "[yellow]warn[/yellow]"
            details = "parent directory missing"
        elif not ms.parent_writable:
            status = "[red]fail[/red]"
            details = "parent directory not writable"
        elif ms.db_opens is False:
            status = "[red]fail[/red]"
            details = f"DB open failed: {ms.error}"
        elif ms.db_opens is True:
            status = "[green]ok[/green]"
            details = "accessible"
        else:
            status = "[green]ok[/green]"
            details = "path writable"
        table.add_row("memory", ms.store_path, status, details)

    for trig in diag.triggers:
        if trig.issues:
            status = "[yellow]warn[/yellow]"
            details = "; ".join(trig.issues)
        else:
            status = "[green]ok[/green]"
            details = trig.label
        table.add_row("trigger", trig.trigger_type, status, details)

    if diag.docker is not None:
        dk = diag.docker
        if not dk.daemon_available:
            status = "[red]fail[/red]"
            details = "Docker daemon not available"
        elif dk.image_available is False:
            status = "[yellow]warn[/yellow]"
            details = f"image '{dk.image}' not pulled locally; run `docker pull {dk.image}`"
        elif dk.image_available is True:
            status = "[green]ok[/green]"
            details = f"image '{dk.image}' available"
        else:
            status = "[green]ok[/green]"
            details = f"daemon ready; use --deep to check image '{dk.image}'"
        table.add_row("docker", "sandbox", status, details)

    console.print()
    console.print(table)


def _check_flow_health(path: Path, *, deep: bool = False, skill_dir: Path | None = None) -> bool:
    """Validate a flow file and its referenced roles. Returns True if errors found."""
    from initrunner.cli._helpers import resolve_skill_dirs
    from initrunner.services.doctor import diagnose_flow

    console.print()
    extra_dirs = resolve_skill_dirs(skill_dir)

    try:
        diag = diagnose_flow(path, deep=deep, extra_skill_dirs=extra_dirs)
    except Exception as exc:
        console.print(
            Panel(
                f"[red]Flow validation failed:[/red] {exc}",
                title="Flow Validation",
                border_style="red",
            )
        )
        return True

    if not diag.flow_valid:
        console.print(
            Panel(
                f"[red]Flow is invalid:[/red] {diag.flow_error or 'validation errors'}",
                title="Flow Validation",
                border_style="red",
            )
        )
    else:
        console.print("[green]Flow structure is valid.[/green]")

    # Show validation issues
    error_issues = [i for i in diag.validation_issues if i.severity == "error"]
    warn_issues = [i for i in diag.validation_issues if i.severity == "warning"]
    if error_issues or warn_issues:
        issue_table = Table(title="Flow Validation Issues")
        issue_table.add_column("Severity")
        issue_table.add_column("Field", style="cyan")
        issue_table.add_column("Message")

        for issue in error_issues:
            issue_table.add_row("[red]error[/red]", issue.field, issue.message)
        for issue in warn_issues:
            issue_table.add_row("[yellow]warning[/yellow]", issue.field, issue.message)

        console.print(issue_table)

    # Show missing roles
    for agent_name in diag.missing_roles:
        console.print(f"  [red]Missing role:[/red] agent '{agent_name}'")

    # Show role parse errors
    for agent_name, error in diag.role_errors.items():
        console.print(f"  [red]Role error ({agent_name}):[/red] {error}")

    # Per-agent diagnostics
    for agent_name, agent_diag in diag.agent_diagnostics.items():
        if agent_diag is not None:
            console.print(f"\n[bold]Agent: {agent_name}[/bold]")
            _render_role_diagnostics(agent_diag)

    return not diag.flow_valid
