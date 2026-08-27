"""Flag validation for the run command.

Every flag `run` accepts is either consumed by the target it is given to, or
rejected here. Nothing is silently dropped: a flag the target cannot honour is
an error, not a no-op, so a run never quietly ignores what was asked for.
"""

from __future__ import annotations

import enum

import typer

from initrunner.cli._helpers import console

# ---------------------------------------------------------------------------
# Run mode resolution
# ---------------------------------------------------------------------------


@enum.unique
class RunMode(enum.Enum):
    STANDARD = "standard"
    DAEMON = "daemon"
    SERVE = "serve"


def _resolve_run_mode(
    *,
    daemon_mode: bool,
    serve_mode: bool,
    autonomous: bool,
) -> RunMode:
    """Resolve mutually exclusive mode flags into a single RunMode.

    ``--autonomous`` is a STANDARD-mode modifier, mutually exclusive with the
    long-running modes.
    """
    active: list[tuple[str, RunMode]] = []
    if daemon_mode:
        active.append(("--daemon", RunMode.DAEMON))
    if serve_mode:
        active.append(("--serve", RunMode.SERVE))
    if autonomous:
        active.append(("--autonomous", RunMode.STANDARD))

    if len(active) > 1:
        console.print(
            f"[red]Error:[/red] Cannot combine {active[0][0]} and {active[1][0]}."
            " Choose one run mode."
        )
        raise typer.Exit(1)

    return active[0][1] if active else RunMode.STANDARD


# ---------------------------------------------------------------------------
# Universal validation (runs before ephemeral / role branching)
# ---------------------------------------------------------------------------

_VALID_FORMATS = ("auto", "json", "text", "rich")


def _validate_universal_flags(
    *,
    mode: RunMode,
    output_format: str,
    interactive: bool,
    autonomous: bool,
    sense: bool,
    prompt: str | None,
    host: str | None,
    port: int | None,
) -> None:
    """Validate flags whose meaning depends only on the run mode."""
    # -- Format --
    if output_format not in _VALID_FORMATS:
        console.print(
            f"[red]Error:[/red] Unknown format '{output_format}'. Use: {', '.join(_VALID_FORMATS)}"
        )
        raise typer.Exit(1)

    if output_format in ("json", "text") and interactive:
        console.print("[red]Error:[/red] --format json|text is not supported with -i.")
        raise typer.Exit(1)

    if output_format in ("json", "text") and autonomous:
        console.print("[red]Error:[/red] --format json|text is not supported with -a.")
        raise typer.Exit(1)

    # -- Mode-only flags --
    # A long-running mode has no single run to format or prompt.
    if mode is not RunMode.STANDARD:
        if output_format != "auto":
            console.print(
                f"[red]Error:[/red] --format only applies to a standard run, not --{mode.value}."
            )
            raise typer.Exit(1)
        if prompt:
            console.print(
                f"[red]Error:[/red] --prompt only applies to a standard run,"
                f" not --{mode.value}. Triggers supply the prompt in daemon mode."
            )
            raise typer.Exit(1)

    if mode is not RunMode.SERVE:
        bound = [f for f, v in (("--host", host), ("--port", port)) if v is not None]
        if bound:
            console.print(f"[red]Error:[/red] {', '.join(bound)} only applies to --serve mode.")
            raise typer.Exit(1)

    # -- Sense --
    if sense and not prompt:
        console.print("[red]Error:[/red] --sense requires --prompt (-p).")
        raise typer.Exit(1)
    if sense and mode is not RunMode.STANDARD:
        console.print(f"[red]Error:[/red] --sense is not supported with {mode.value} mode.")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Per-target validation
# ---------------------------------------------------------------------------

# Flags that steer one agent's run. A team, flow or whole group has no single
# run to steer, so these are rejected rather than quietly dropped.
_SINGLE_AGENT_FLAGS = (
    "--interactive",
    "--autonomous",
    "--resume",
    "--attach",
    "--report",
    "--var",
    "--format",
)

# Ephemeral mode is keyed like a target kind so one table covers every context.
EPHEMERAL_KIND = "Ephemeral"

# kind -> (denied flags, allowed run modes)
_KIND_POLICY: dict[str, tuple[tuple[str, ...], frozenset[RunMode]]] = {
    # No role file: no target to attach a report, template var, or member to.
    EPHEMERAL_KIND: (
        ("--autonomous", "--dry-run", "--report", "--var", "--agent", "--format"),
        frozenset({RunMode.STANDARD}),
    ),
    # Team and Flow build their own agents, so a single agent's model and run
    # flags have nowhere to land.
    "Team": ((*_SINGLE_AGENT_FLAGS, "--model"), frozenset({RunMode.STANDARD})),
    "Flow": ((*_SINGLE_AGENT_FLAGS, "--model", "--dry-run"), frozenset({RunMode.STANDARD})),
    "Group": (
        (*_SINGLE_AGENT_FLAGS, "--dry-run"),
        frozenset({RunMode.STANDARD, RunMode.SERVE, RunMode.DAEMON}),
    ),
}

_SUFFIX_BY_KIND = {
    "Group": " Pick one member with --agent <name> to run it as a single agent.",
}


def _validate_kind_flags(
    kind: str,
    mode: RunMode,
    *,
    active_flags: dict[str, bool],
) -> None:
    """Reject run flags the target cannot honour.

    ``Agent`` targets accept everything, including a group member picked with
    ``--agent``, which is rewritten to an Agent target before this runs.
    """
    policy = _KIND_POLICY.get(kind)
    if policy is None:
        return
    denied_flags, allowed_modes = policy

    invalid = [flag for flag in denied_flags if active_flags.get(flag)]
    if invalid:
        target = "without a role file" if kind == EPHEMERAL_KIND else f"for {kind} targets"
        console.print(
            f"[red]Error:[/red] {', '.join(invalid)} not supported {target}."
            f"{_SUFFIX_BY_KIND.get(kind, '')}"
        )
        raise typer.Exit(1)

    if mode not in allowed_modes:
        if kind == EPHEMERAL_KIND:
            console.print(
                f"[red]Error:[/red] {mode.value} mode is not supported without a role file."
            )
            raise typer.Exit(1)
        suffix = (
            " Add --agent <name> to run one member that way."
            if kind == "Group"
            else " It is only supported for Agent targets."
        )
        console.print(
            f"[red]Error:[/red] --{mode.value} is not supported for {kind} targets.{suffix}"
        )
        raise typer.Exit(1)


def _validate_role_only_flags(
    *,
    tools: list[str] | None,
    memory: bool | None,
    ingest: list[str] | None,
) -> None:
    """Reject ephemeral-only flags when a role file is provided."""
    invalid = []
    if tools:
        invalid.append("--tools")
    # bool | None: --no-memory is False, which is still an explicit choice.
    if memory is not None:
        invalid.append("--memory/--no-memory")
    if ingest:
        invalid.append("--ingest")
    if invalid:
        console.print(
            f"[red]Error:[/red] {', '.join(invalid)} not supported with a role file"
            " (these settings come from the YAML)."
        )
        raise typer.Exit(1)
