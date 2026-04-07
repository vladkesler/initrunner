"""Shared CLI helpers: error handling, role loading, and context management."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import typer
from rich.console import Console
from rich.markup import escape

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from initrunner.agent.schema.role import RoleDefinition
    from initrunner.audit.logger import AuditLogger
    from initrunner.services.role_selector import SelectionResult

console = Console()


def ingest_status_color(status: object) -> str:
    """Map a :class:`~initrunner.ingestion.pipeline.FileStatus` to a Rich color."""
    from initrunner.ingestion.pipeline import FileStatus

    return {  # type: ignore[no-matching-overload]
        FileStatus.NEW: "green",
        FileStatus.UPDATED: "yellow",
        FileStatus.SKIPPED: "dim",
        FileStatus.ERROR: "red",
    }.get(status, "white")


_INITRUNNER_API_VERSIONS = {"initrunner/v1"}
_INITRUNNER_KINDS = {"Agent", "Team", "Flow"}


def resolve_role_path(path: Path) -> Path:
    """Resolve a directory, file, or installed role name to its role YAML file.

    When *path* is a file, return it unchanged.  When it is a directory:
    1. If ``<dir>/role.yaml`` exists, use it.
    2. Otherwise scan top-level ``*.yaml`` / ``*.yml`` for files whose
       ``apiVersion`` is in ``initrunner/v1`` and ``kind`` is Agent or Team.
    3. Exactly one match → use it.
    4. Zero → exit with error.
    5. Multiple → exit with error listing the names.

    When *path* is neither a file nor a directory, try to resolve it as an
    installed role name via the registry.
    """
    if path.is_file():
        return path

    if path.is_dir():
        # 1. Convention: role.yaml
        default = path / "role.yaml"
        if default.is_file():
            return default

        # 2. Scan top-level YAML files
        import yaml

        candidates: list[Path] = []
        for ext in ("*.yaml", "*.yml"):
            for f in path.glob(ext):
                if not f.is_file():
                    continue
                try:
                    with open(f) as fh:
                        data = yaml.safe_load(fh)
                    if (
                        isinstance(data, dict)
                        and data.get("apiVersion") in _INITRUNNER_API_VERSIONS
                        and data.get("kind") in _INITRUNNER_KINDS
                    ):
                        candidates.append(f)
                except Exception:
                    continue

        if len(candidates) == 1:
            return candidates[0]

        if len(candidates) == 0:
            console.print(f"[red]Error:[/red] No role YAML found in {path}")
            console.print(
                "[dim]Hint:[/dim] Create one with [bold]initrunner new[/bold],"
                " or run [bold]initrunner examples[/bold]."
            )
            raise typer.Exit(1)

        names = ", ".join(sorted(c.name for c in candidates))
        console.print(
            f"[red]Error:[/red] Multiple role YAML files in {path}: {names}; pass one explicitly"
        )
        raise typer.Exit(1)

    # Not a file or directory: try installed role lookup
    from initrunner.registry import RegistryError, resolve_installed_path

    try:
        resolved = resolve_installed_path(str(path))
    except RegistryError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        console.print(
            "[dim]Hint:[/dim] Run [bold]initrunner examples[/bold] to see available starters."
        )
        raise typer.Exit(1) from None

    if resolved is not None:
        return resolve_role_path(resolved)

    # Fallback: try bundled starters (lowest priority)
    from initrunner.services.starters import resolve_starter_path

    starter_path = resolve_starter_path(str(path))
    if starter_path is not None:
        return starter_path

    console.print(f"[red]Error:[/red] Path not found: {path}")
    console.print(
        "[dim]Hint:[/dim] Check the path, or run [bold]initrunner examples[/bold] to see starters."
    )
    raise typer.Exit(1)


def resolve_role_paths(paths: list[Path]) -> list[Path]:
    """Resolve a list of paths, applying :func:`resolve_role_path` to each."""
    return [resolve_role_path(p) for p in paths]


def prepare_starter(role_file: Path, model: str | None) -> str | None:
    """If *role_file* is a bundled starter, check prerequisites and auto-detect model.

    Returns the effective model string:

    * The original *model* if already provided (prerequisites are still checked).
    * Auto-detected ``"provider:name"`` when *model* is ``None``.
    * ``None`` when *role_file* is not a starter (caller proceeds normally).

    Prints warnings for missing user data.
    Raises ``typer.Exit(1)`` on hard prerequisite failures.
    """
    from initrunner.services.starters import STARTERS_DIR, check_prerequisites, get_starter

    try:
        if not role_file.resolve().is_relative_to(STARTERS_DIR.resolve()):
            return None
    except ValueError:
        return None

    entry = get_starter(role_file.stem)
    if entry is None:
        return None

    errors, warnings = check_prerequisites(entry)
    if errors:
        for e in errors:
            if e.startswith(" "):
                console.print(e)
            else:
                console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    for w in warnings:
        console.print(f"[yellow]Note:[/yellow] {w}")

    if model is not None:
        return model

    # Prefer the user's explicit choice from setup (run.yaml)
    from initrunner.cli.run_config import load_run_config

    run_cfg = load_run_config()
    if run_cfg.provider and run_cfg.model:
        return f"{run_cfg.provider}:{run_cfg.model}"

    from initrunner._compat import require_provider
    from initrunner.services.providers import list_available_providers

    for detected in list_available_providers():
        try:
            require_provider(detected.provider)
        except RuntimeError:
            continue
        return f"{detected.provider}:{detected.model}"

    console.print(
        "[red]Error:[/red] No usable provider found. "
        "Run `initrunner setup` or set an API key environment variable."
    )
    raise typer.Exit(1)


def display_sense_result(result: SelectionResult) -> None:
    """Render the intent-sensed role in a Rich panel."""
    from rich.panel import Panel
    from rich.table import Table

    c = result.candidate

    # Relative path if possible
    try:
        display_path = str(c.path.relative_to(Path.cwd()))
    except ValueError:
        display_path = str(c.path)

    # Method label
    method = result.method
    if method == "only_one":
        method_str = "[dim]only role available[/dim]"
    elif method == "keyword":
        method_str = (
            f"[green]keyword match[/green] (score: {result.top_score:.2f}, gap: {result.gap:.2f})"
        )
    elif method == "llm":
        method_str = "[yellow]LLM selection[/yellow]"
    else:
        method_str = "[yellow]fallback — no strong match[/yellow]"

    tags_str = ", ".join(c.tags) if c.tags else "[dim]none[/dim]"

    table = Table.grid(padding=(0, 1))
    table.add_column(style="dim", no_wrap=True)
    table.add_column()
    table.add_row("Name", f"[cyan]{escape(c.name)}[/cyan]")
    table.add_row("File", escape(display_path))
    table.add_row("Tags", tags_str)
    table.add_row("Method", method_str)
    if c.reason:
        table.add_row("Reason", escape(c.reason))

    console.print(Panel(table, title="[bold]Intent Sensing[/bold]", border_style="dim"))


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


def install_extra(extra: str) -> bool:
    """Best-effort install of an initrunner extra. Returns True on success."""
    import shutil
    import subprocess
    import sys

    pkg = f"initrunner[{extra}]"
    pkg_display = escape(pkg)

    exe = sys.executable.replace("\\", "/")
    if "/uv/tools/" in exe and shutil.which("uv"):
        cmd = ["uv", "tool", "install", "--force", pkg]
    elif "/pipx/venvs/" in exe:
        if shutil.which("pipx"):
            cmd = ["pipx", "install", "--force", pkg]
        else:
            cmd = [sys.executable, "-m", "pip", "install", pkg]
    elif shutil.which("uv"):
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
            f"[yellow]Warning:[/yellow] Could not install {pkg_display}: {escape(str(exc))}\n"
            f"Install manually: [bold]{escape(' '.join(cmd))}[/bold]"
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
    from initrunner.services.providers import is_ollama_running

    if not is_ollama_running():
        console.print(
            "[yellow]Warning:[/yellow] Ollama does not appear to be running. "
            "Make sure to run: [bold]ollama serve[/bold]"
        )


def detect_yaml_kind(path: Path) -> str:
    """Peek at a YAML file's ``kind`` field without full validation.

    Returns the kind string (e.g. ``"Agent"``, ``"Team"``, ``"Flow"``).
    Defaults to ``"Agent"`` on any failure.

    Raises ``typer.Exit(1)`` if the file uses the removed ``kind: Compose``.
    Thin CLI wrapper around :func:`initrunner.services.yaml_validation.detect_yaml_kind`
    that converts the pure-Python exception into a printed error and exit.
    """
    from initrunner.services.yaml_validation import (
        InvalidComposeKindError,
    )
    from initrunner.services.yaml_validation import (
        detect_yaml_kind as _detect,
    )

    try:
        return _detect(path)
    except InvalidComposeKindError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None


def preflight_validate_or_exit(path: Path) -> None:
    """Validate *path* against its YAML schema and exit on errors.

    Used by every CLI run path (``run``, ``flow up``) as a pre-flight
    check before any agent build or API call.  Stays silent on
    warning-only files -- the ``validate`` command shows warnings, but
    the run path does not, to keep successful runs free of advisory
    noise.
    """
    from initrunner.cli._validation_panel import render_validation_panel
    from initrunner.services.yaml_validation import validate_yaml_file

    _, kind, issues = validate_yaml_file(path)
    if any(i.severity == "error" for i in issues):
        console.print(render_validation_panel(path, kind, issues))
        raise typer.Exit(1)


def resolve_run_target(target: Path) -> tuple[Path, str]:
    """Resolve a run target to *(resolved_path, kind)*.

    Explicit files may resolve to any kind (Agent, Team, Flow).
    Directory and installed-name resolution stays Agent/Team-only via
    :func:`resolve_role_path`.
    """
    resolved = resolve_role_path(target)
    kind = detect_yaml_kind(resolved)
    return resolved, kind


def load_role_or_exit(role_file: Path) -> RoleDefinition:
    role_file = resolve_role_path(role_file)
    from initrunner.agent.loader import RoleLoadError
    from initrunner.services.discovery import load_role_sync

    try:
        return load_role_sync(role_file)
    except RoleLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            f"[dim]Hint:[/dim] Run [bold]initrunner validate {role_file}[/bold] for details."
        )
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
    model_override: str | None = None,
) -> tuple[RoleDefinition, Agent]:
    role_file = resolve_role_path(role_file)
    from initrunner.agent.loader import RoleLoadError
    from initrunner.services.execution import build_agent_sync

    try:
        return build_agent_sync(
            role_file,
            extra_skill_dirs=extra_skill_dirs,
            model_override=model_override,
        )
    except RoleLoadError as e:
        console.print(f"[red]Error:[/red] {e}")
        console.print(
            f"[dim]Hint:[/dim] Run [bold]initrunner validate {role_file}[/bold] for details."
        )
        raise typer.Exit(1) from None


def resolve_model_override(model_flag: str | None) -> str | None:
    """Resolve a ``--model`` CLI flag value to ``provider:model``.

    Returns ``None`` when *model_flag* is ``None``.  Resolves aliases and
    validates the result contains a colon.  Exits with error on failure.
    """
    if model_flag is None:
        return None

    from initrunner.model_aliases import parse_model_string, resolve_model_alias

    resolved = resolve_model_alias(model_flag)
    try:
        parse_model_string(resolved)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1) from None
    return resolved


def _apply_model_override(role: RoleDefinition, model_string: str) -> RoleDefinition:
    """Return a copy of *role* with its model config replaced by *model_string*.

    Preserves temperature and max_tokens.  Clears ``base_url`` and
    ``api_key_env`` only when the provider changes.
    """
    from initrunner.model_aliases import parse_model_string

    new_provider, new_name = parse_model_string(model_string)
    old_model = role.spec.model

    update: dict = {"provider": new_provider, "name": new_name}
    if new_provider != old_model.provider:  # type: ignore[union-attr]
        update["base_url"] = None
        update["api_key_env"] = None

    new_model = old_model.model_copy(update=update)  # type: ignore[union-attr]
    new_spec = role.spec.model_copy(update={"model": new_model})
    return role.model_copy(update={"spec": new_spec})


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


def resolve_memory_path(role: RoleDefinition) -> Path:
    from initrunner.stores.base import resolve_memory_path as _resolve

    mem = role.spec.memory
    return _resolve(mem.store_path if mem else None, role.metadata.name)


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
            yield role, agent, audit_logger, memory_store, sink_dispatcher
        finally:
            if audit_logger is not None:
                audit_logger.close()
            if _otel_provider is not None:
                from initrunner.observability import shutdown_tracing

                shutdown_tracing()


_NextContext = Literal["run_single", "run_autonomous", "run_repl_exit", "ingest", "validate"]


def suggest_next(context: _NextContext, role: RoleDefinition, role_path: Path) -> None:
    """Print 2-3 contextual next-step suggestions after a command."""
    if not sys.stdout.isatty():
        return

    try:
        role_ref = str(role_path.relative_to(Path.cwd()))
    except ValueError:
        role_ref = str(role_path)

    suggestions: list[tuple[str, str]] = []

    if context == "run_single":
        suggestions.append((f"initrunner run {role_ref} -i", "interactive REPL"))
        if role.spec.autonomy:
            suggestions.append((f'initrunner run {role_ref} -a -p "..."', "autonomous mode"))
        else:
            suggestions.append(
                (
                    f'initrunner run {role_ref} --report report.md -p "..."',
                    "export a report",
                )
            )

    elif context == "run_repl_exit":
        if role.spec.ingest:
            suggestions.append((f"initrunner ingest {role_ref}", "re-ingest documents"))
        if role.spec.memory:
            suggestions.append((f"initrunner memory list {role_ref}", "view stored memories"))
        if role.spec.autonomy:
            suggestions.append((f'initrunner run {role_ref} -a -p "..."', "autonomous mode"))

    elif context == "run_autonomous":
        suggestions.append((f"initrunner run {role_ref} -i", "continue interactively"))
        if role.spec.memory:
            suggestions.append((f"initrunner memory list {role_ref}", "view stored memories"))
        suggestions.append(
            (
                f'initrunner run {role_ref} --report report.md -a -p "..."',
                "export a report",
            )
        )

    elif context == "ingest":
        suggestions.append((f'initrunner run {role_ref} -p "..."', "run the agent"))
        suggestions.append((f"initrunner validate {role_ref}", "re-validate role"))

    elif context == "validate":
        suggestions.append((f'initrunner run {role_ref} -p "..."', "run the agent"))
        if role.spec.ingest:
            suggestions.append((f"initrunner ingest {role_ref}", "ingest documents"))
        suggestions.append((f"initrunner doctor --role {role_ref}", "smoke-test provider"))

    if not suggestions:
        return

    console.print()
    console.print("[dim]Next steps:[/dim]")
    for cmd, desc in suggestions[:3]:
        console.print(f"  [bold]{cmd}[/bold]  [dim]# {desc}[/dim]")
