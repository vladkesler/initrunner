"""Runtime/setup context: agent loading, API-key prompts, audit, and context managers."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from initrunner.cli._helpers._console import console
from initrunner.cli._helpers._display import ingest_status_color
from initrunner.cli._helpers._resolve import resolve_role_path

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger


def handle_api_key(
    env_var: str,
    env_path: os.PathLike,
    *,
    validate_provider: str | None,
) -> None:
    """Prompt for, validate, and persist an API key.

    Shared between ``setup`` and ``doctor --fix`` to avoid duplicating the
    env vs dotenv detection logic.
    """
    from dotenv import dotenv_values, set_key
    from rich.prompt import Prompt

    from initrunner.config import get_global_env_path, get_home_dir
    from initrunner.services.setup import validate_api_key as _validate_api_key

    env_path = Path(env_path)

    has_provider_key = bool(os.environ.get(env_var))
    if not has_provider_key and env_path.is_file():
        has_provider_key = bool(dotenv_values(env_path).get(env_var))

    if has_provider_key:
        console.print(
            f"[green]Using existing {env_var}.[/green] "
            f"[dim]Edit {get_global_env_path()} to change it.[/dim]"
        )
        return

    existing_in_env = os.environ.get(env_var)
    existing_in_dotenv = None
    if env_path.is_file():
        existing_in_dotenv = dotenv_values(env_path).get(env_var)

    if existing_in_env:
        console.print(f"[green]Found {env_var} in environment.[/green]")
        if not typer.confirm("Keep this key?", default=True):
            existing_in_env = None

    if existing_in_env:
        api_key = existing_in_env
    elif existing_in_dotenv:
        console.print(f"[green]Found {env_var} in {env_path}[/green]")
        if typer.confirm("Keep this key?", default=True):
            api_key = existing_in_dotenv
        else:
            api_key = Prompt.ask(f"Enter your {env_var}", password=True)
    else:
        api_key = Prompt.ask(f"Enter your {env_var}", password=True)

    # Validate the key
    if validate_provider is not None:
        with console.status("Validating API key..."):
            valid = _validate_api_key(validate_provider, api_key)
        if valid:
            console.print("[green]API key is valid.[/green]")
        else:
            console.print("[yellow]Warning:[/yellow] API key validation failed.")
            if typer.confirm("Re-enter the key?", default=True):
                api_key = Prompt.ask(f"Enter your {env_var}", password=True)

    # Write to .env if key is not already in the env
    if not os.environ.get(env_var):
        try:
            home_dir = get_home_dir()
            home_dir.mkdir(parents=True, exist_ok=True)
            set_key(str(env_path), env_var, api_key)
            env_path.chmod(0o600)
            console.print(f"Saved to [cyan]{env_path}[/cyan]")
        except (PermissionError, OSError) as exc:
            console.print(
                f"[yellow]Warning:[/yellow] Could not write {env_path}: {exc}\n"
                f"Set it manually: [bold]export {env_var}={api_key}[/bold]"
            )


def prompt_inline_api_key(env_var: str, provider: str) -> bool:
    """Prompt for an API key inline, persist it, return True on success.

    Used by ``load_and_build_or_exit`` to recover from a missing-key error
    on first run, so the user doesn't have to ctrl-C and round-trip
    through ``initrunner setup``.

    Returns ``False`` (no prompt) when stdin or stdout is not a TTY, when
    the user enters an empty key, or on Ctrl-C/Ctrl-D.  The caller should
    fall through to the existing error path in those cases.
    """
    from rich.prompt import Prompt

    from initrunner.services.setup import save_env_key

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False

    console.print(
        f"[yellow]No API key found for {provider}.[/yellow] "
        f"Enter your {provider} API key (or press Ctrl-C and run "
        f"[bold]initrunner setup[/bold] for full configuration):"
    )
    try:
        api_key = Prompt.ask(env_var, password=True, console=console).strip()
    except (KeyboardInterrupt, EOFError):
        return False
    if not api_key:
        return False

    # Set in-process before persisting so the retry succeeds even if disk
    # write fails.  save_env_key already returns None on PermissionError /
    # OSError, so we just check the return value.
    os.environ[env_var] = api_key
    saved_to = save_env_key(env_var, api_key)
    if saved_to:
        console.print(f"[green]Saved to[/green] [cyan]{saved_to}[/cyan]")
    else:
        console.print(
            "[yellow]Warning:[/yellow] Could not persist key to disk. "
            "It will work for this run only."
        )
    return True


def check_ollama_running() -> None:
    """Ping local Ollama and warn if it's not reachable."""
    from initrunner.services.providers import is_ollama_running

    if not is_ollama_running():
        console.print(
            "[yellow]Warning:[/yellow] Ollama does not appear to be running. "
            "Make sure to run: [bold]ollama serve[/bold]"
        )


def load_and_build_or_exit(
    role_file: Path,
    extra_skill_dirs: list[Path] | None = None,
    model_override: str | None = None,
) -> tuple[RoleDefinition, Agent]:
    role_file = resolve_role_path(role_file)
    from initrunner.agent.loader import MissingApiKeyError, RoleLoadError
    from initrunner.services.execution import build_agent_sync

    def _build():
        return build_agent_sync(
            role_file,
            extra_skill_dirs=extra_skill_dirs,
            model_override=model_override,
        )

    prompted = False
    while True:
        try:
            return _build()
        except MissingApiKeyError as e:
            if not prompted and prompt_inline_api_key(e.env_var, e.provider):
                prompted = True
                continue
            # Prompt skipped (non-TTY), declined (empty/Ctrl-C), or this is
            # the post-prompt retry.  Print the original missing-key
            # message verbatim.  We deliberately omit the "run initrunner
            # validate" hint here: validate checks YAML schema and would
            # say the role is fine.  The error text from _build_model()
            # already tells the user exactly what to do (export the env
            # var).
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1) from None
        except RoleLoadError as e:
            console.print(f"[red]Error:[/red] {e}")
            console.print(
                f"[dim]Hint:[/dim] Run [bold]initrunner validate {role_file}[/bold] for details."
            )
            raise typer.Exit(1) from None


def create_audit_logger(audit_db: Path | None, no_audit: bool) -> AuditLogger | None:
    if no_audit:
        return None
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    return _AuditLogger(audit_db or DEFAULT_DB_PATH)


def _no_memory_role(role: RoleDefinition) -> RoleDefinition:
    """Return a shallow copy of *role* with memory disabled.

    Used to skip memory store creation when ``with_memory=False``.
    """
    return role.model_copy(update={"spec": role.spec.model_copy(update={"memory": None})})


def _maybe_auto_ingest(role: RoleDefinition, role_file: Path) -> None:
    """Run auto-ingest before agent execution if sources are stale.

    No-op when no ``ingest:`` block is configured, when ``ingest.auto`` is
    False, or when nothing has changed since the last indexing pass. Catches
    :class:`EmbeddingModelChangedError` and exits with a hint pointing at
    ``initrunner ingest --force``.
    """
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    from initrunner.services.ingest import (
        compute_stale_ingest_plan,
        run_auto_ingest,
    )
    from initrunner.stores.base import EmbeddingModelChangedError

    plan = compute_stale_ingest_plan(role, role_file)
    if plan is None:
        return

    def _do_ingest(progress_callback):
        try:
            return run_auto_ingest(role, role_file, progress_callback=progress_callback)
        except EmbeddingModelChangedError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            console.print(f"[dim]Run: initrunner ingest {role_file} --force[/dim]")
            raise typer.Exit(1) from None

    if plan.progress_total > 0:
        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            console=console,
        ) as progress:
            ptask = progress.add_task("Indexing", total=plan.progress_total)

            def _on_progress(path: Path, status: object) -> None:
                progress.update(
                    ptask,
                    advance=1,
                    description=f"[{ingest_status_color(status)}]{path.name}",
                )

            stats = _do_ingest(_on_progress)
    else:
        # Purge-only or legacy-identity-record run -- no items to iterate,
        # no progress bar to show. The pipeline still runs (purge or
        # identity write).
        stats = _do_ingest(None)

    if stats.new or stats.updated:
        console.print(
            f"[green]Indexed[/green] {stats.new} new, "
            f"{stats.updated} updated ({stats.total_chunks} chunks)"
        )


@contextmanager
def ephemeral_context(
    role: RoleDefinition,
    agent: Agent,
    *,
    audit_db: Path | None = None,
    no_audit: bool = False,
    with_memory: bool = False,
):
    """Context manager for ephemeral (in-memory) roles.

    Like command_context() but accepts pre-built RoleDefinition + Agent.
    Skips sinks and observability.
    """
    from initrunner.stores.factory import managed_memory_store

    audit_logger = create_audit_logger(audit_db, no_audit)

    mem_role = role if with_memory else _no_memory_role(role)
    with managed_memory_store(mem_role, agent) as memory_store:
        try:
            yield role, agent, audit_logger, memory_store
        finally:
            if audit_logger is not None:
                audit_logger.close()


@contextmanager
def command_context(
    role_file: Path,
    *,
    audit_db: Path | None,
    no_audit: bool,
    with_memory: bool = False,
    with_sinks: bool = False,
    extra_skill_dirs: list[Path] | None = None,
    model_override: str | None = None,
    dry_run: bool = False,
):
    """Context manager for agent setup and resource cleanup.

    Yields (role, agent, audit_logger, memory_store, sink_dispatcher).
    """
    role_file = resolve_role_path(role_file)
    from initrunner.stores.factory import managed_memory_store

    role, agent = load_and_build_or_exit(
        role_file, extra_skill_dirs=extra_skill_dirs, model_override=model_override
    )

    # Setup observability after load so TracerProvider is active before
    # the first agent.run_sync() call (PydanticAI resolves it lazily).
    _otel_provider = None
    if role.spec.observability is not None:
        from initrunner.observability import setup_tracing

        _otel_provider = setup_tracing(role.spec.observability, role.metadata.name)
    audit_logger = create_audit_logger(audit_db, no_audit)

    mem_role = role if with_memory else _no_memory_role(role)
    with managed_memory_store(mem_role, agent) as memory_store:
        sink_dispatcher = None
        if with_sinks and role.spec.sinks:
            from initrunner.sinks.dispatcher import SinkDispatcher

            sink_dispatcher = SinkDispatcher(role.spec.sinks, role, role_dir=role_file.parent)

        try:
            # Auto-ingest hook: shared by all `initrunner run` execution
            # modes (single-shot, REPL, autonomous, serve, daemon, bot).
            # Runs after tracing/audit/memory are set up so ingest spans
            # land under the active TracerProvider. Skipped for dry-run
            # (TestModel) so test models don't trigger embedding API calls.
            # The surrounding finally still cleans up if the helper exits
            # via typer.Exit on EmbeddingModelChangedError.
            if not dry_run:
                _maybe_auto_ingest(role, role_file)

            yield role, agent, audit_logger, memory_store, sink_dispatcher
        finally:
            if audit_logger is not None:
                audit_logger.close()
            if _otel_provider is not None:
                from initrunner.observability import shutdown_tracing

                shutdown_tracing()
