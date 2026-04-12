"""Path resolution, YAML detection, model override, and role loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from initrunner.cli._helpers._console import console

if TYPE_CHECKING:
    from initrunner.agent.schema.role import RoleDefinition

_INITRUNNER_API_VERSIONS = {"initrunner/v1"}
_INITRUNNER_KINDS = {"Agent", "Team", "Flow"}


def resolve_role_path(path: Path) -> Path:
    """Resolve a directory, file, or installed role name to its role YAML file.

    When *path* is a file, return it unchanged.  When it is a directory:
    1. If ``<dir>/role.yaml`` exists, use it.
    2. Otherwise scan top-level ``*.yaml`` / ``*.yml`` for files whose
       ``apiVersion`` is in ``initrunner/v1`` and ``kind`` is Agent or Team.
    3. Exactly one match -> use it.
    4. Zero -> exit with error.
    5. Multiple -> exit with error listing the names.

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


def resolve_memory_path(role: RoleDefinition) -> Path:
    from initrunner.stores.base import resolve_memory_path as _resolve

    mem = role.spec.memory
    return _resolve(mem.store_path if mem else None, role.metadata.name)
