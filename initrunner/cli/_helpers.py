"""Shared CLI helpers: error handling, role loading, and context management."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.markup import escape

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema import RoleDefinition
    from initrunner.audit.logger import AuditLogger

console = Console()


def install_extra(extra: str) -> bool:
    """Best-effort install of an initrunner extra. Returns True on success."""
    import shutil
    import subprocess
    import sys

    pkg = f"initrunner[{extra}]"
    pkg_display = escape(pkg)
    if shutil.which("uv"):
        cmd = ["uv", "pip", "install", pkg]
    else:
        cmd = [sys.executable, "-m", "pip", "install", pkg]

    try:
        with console.status(f"Installing {pkg_display}..."):
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        console.print(f"[green]Installed {pkg_display}[/green]")
        return True
    except (subprocess.CalledProcessError, OSError) as exc:
        console.print(
            f"[yellow]Warning:[/yellow] Could not install {pkg_display}: {exc}\n"
            f"Install manually: [bold]{' '.join(cmd)}[/bold]"
        )
        return False


def prompt_model_selection(
    provider: str,
    ollama_models: list[str] | None = None,
) -> str:
    """Show model choices for a provider and return selected model name."""
    from rich.prompt import Prompt

    from initrunner.templates import PROVIDER_MODELS, _default_model_name

    if provider == "ollama" and ollama_models:
        choices = [(m, "(local)") for m in ollama_models]
    else:
        choices = PROVIDER_MODELS.get(provider, [])

    default = choices[0][0] if choices else _default_model_name(provider)

    console.print()
    console.print("[bold]Select a model:[/bold]")
    for i, (model_id, desc) in enumerate(choices, 1):
        default_tag = " (default)" if model_id == default else ""
        desc_part = f" — {desc}" if desc else ""
        console.print(f"  {i}. {model_id}{desc_part}{default_tag}")
    console.print("  Or type a custom model name (press Enter for default)")

    raw = Prompt.ask("Model", default=default)

    if raw.strip().isdigit():
        idx = int(raw.strip()) - 1
        if 0 <= idx < len(choices):
            return choices[idx][0]

    return raw.strip() or default


def check_ollama_running() -> None:
    """Ping local Ollama and warn if it's not reachable."""
    import urllib.request

    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
    except Exception:
        console.print(
            "[yellow]Warning:[/yellow] Ollama does not appear to be running. "
            "Make sure to run: [bold]ollama serve[/bold]"
        )


def load_role_or_exit(role_file: Path) -> RoleDefinition:
    from initrunner.agent.loader import RoleLoadError, load_role

    try:
        return load_role(role_file)
    except RoleLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


def resolve_skill_dirs(skill_dir: Path | None) -> list[Path] | None:
    dirs: list[Path] = []
    if skill_dir is not None:
        dirs.append(skill_dir)
    env_val = os.environ.get("INITRUNNER_SKILL_DIR")
    if env_val:
        dirs.append(Path(env_val))
    return dirs if dirs else None


def load_and_build_or_exit(
    role_file: Path,
    extra_skill_dirs: list[Path] | None = None,
) -> tuple[RoleDefinition, Agent]:
    from initrunner.agent.loader import RoleLoadError, load_and_build

    try:
        return load_and_build(role_file, extra_skill_dirs=extra_skill_dirs)
    except RoleLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None


def create_audit_logger(audit_db: Path | None, no_audit: bool) -> AuditLogger | None:
    if no_audit:
        return None
    from initrunner.audit.logger import DEFAULT_DB_PATH
    from initrunner.audit.logger import AuditLogger as _AuditLogger

    return _AuditLogger(audit_db or DEFAULT_DB_PATH)


def resolve_memory_path(role: RoleDefinition) -> Path:
    from initrunner.stores.base import resolve_memory_path as _resolve

    mem = role.spec.memory
    return _resolve(mem.store_path if mem else None, role.metadata.name)


@contextmanager
def command_context(
    role_file: Path,
    *,
    audit_db: Path | None,
    no_audit: bool,
    with_memory: bool = False,
    with_sinks: bool = False,
    extra_skill_dirs: list[Path] | None = None,
):
    """Context manager for agent setup and resource cleanup.

    Yields (role, agent, audit_logger, memory_store, sink_dispatcher).
    """
    role, agent = load_and_build_or_exit(role_file, extra_skill_dirs=extra_skill_dirs)

    # Setup observability after load so TracerProvider is active before
    # the first agent.run_sync() call (PydanticAI resolves it lazily).
    _otel_provider = None
    if role.spec.observability is not None:
        from initrunner.observability import setup_tracing

        _otel_provider = setup_tracing(role.spec.observability, role.metadata.name)
    audit_logger = create_audit_logger(audit_db, no_audit)

    memory_store = None
    if with_memory and role.spec.memory is not None:
        from initrunner.stores.factory import create_memory_store

        mem_path = resolve_memory_path(role)
        memory_store = create_memory_store(role.spec.memory.store_backend, mem_path)

    sink_dispatcher = None
    if with_sinks and role.spec.sinks:
        from initrunner.sinks.dispatcher import SinkDispatcher

        sink_dispatcher = SinkDispatcher(role.spec.sinks, role, role_dir=role_file.parent)

    try:
        yield role, agent, audit_logger, memory_store, sink_dispatcher
    finally:
        if memory_store is not None:
            memory_store.close()
        if audit_logger is not None:
            audit_logger.close()
        if _otel_provider is not None:
            from initrunner.observability import shutdown_tracing

            shutdown_tracing()
