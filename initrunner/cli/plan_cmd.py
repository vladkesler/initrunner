"""The ``plan`` command: a static, offline dry-run of a role."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from initrunner.cli._helpers import console
from initrunner.cli._options import SkillDirOption

if TYPE_CHECKING:
    from initrunner.services.plan import AgentPlan


def plan(
    role_file: Annotated[
        Path, typer.Argument(help="Agent directory, role YAML, or installed role name")
    ],
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", "-p", help="Size the cost estimate and tool_search surfacing"),
    ] = None,
    skill_dir: SkillDirOption = None,
    no_sandbox_probe: Annotated[
        bool,
        typer.Option("--no-sandbox-probe", help="Skip the host sandbox availability probe"),
    ] = False,
    no_introspect: Annotated[
        bool,
        typer.Option("--no-introspect", help="List tools at type level (no builder construction)"),
    ] = False,
    as_json: Annotated[
        bool, typer.Option("--json", help="Emit the plan as JSON instead of tables")
    ] = False,
) -> None:
    """Predict what a role would do, without calling the model.

    Shows reachable tools, would-fire policies, applied guardrails, the sandbox
    that engages, armed triggers, and a heuristic cost estimate. It is a
    best-effort static prediction: the model decides at runtime what it calls.
    """
    import dataclasses

    from initrunner.cli._helpers import detect_yaml_kind, resolve_role_path, resolve_skill_dirs
    from initrunner.services.plan import plan_role_from_path

    role_file = resolve_role_path(role_file)
    kind = detect_yaml_kind(role_file)
    if kind != "Agent":
        console.print(
            f"[red]Error:[/red] `initrunner plan` supports Agent roles; this file is `{kind}`."
        )
        raise typer.Exit(1)

    try:
        agent_plan = plan_role_from_path(
            role_file,
            prompt=prompt,
            probe_sandbox=not no_sandbox_probe,
            introspect=not no_introspect,
            extra_skill_dirs=resolve_skill_dirs(skill_dir),
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from None

    if as_json:
        console.print_json(data=dataclasses.asdict(agent_plan))
        return

    _render_plan(agent_plan)


def _render_plan(plan_obj: AgentPlan) -> None:
    from rich.panel import Panel
    from rich.table import Table
    from rich.tree import Tree

    console.print(
        f"\n[bold]Plan:[/bold] {plan_obj.role_name}  "
        f"[dim]({plan_obj.model_label})[/dim]\n"
        f"[dim]Static prediction, no model call.[/dim]"
    )

    # --- Reachable tools ---
    surfaced = set(plan_obj.tool_search_surfaced or [])
    tools_table = Table(title="Reachable tools", title_justify="left", show_lines=False)
    tools_table.add_column("Tool", style="cyan")
    tools_table.add_column("Type")
    tools_table.add_column("Source")
    tools_table.add_column("Policy")
    for tool in plan_obj.tools:
        if tool.policy is None:
            policy_cell = "[dim]-[/dim]"
        elif tool.policy.allowed:
            policy_cell = "[green]allow[/green]"
        else:
            policy_cell = f"[red]deny[/red] [dim]{tool.policy.reason}[/dim]"
        name = tool.name + (" [yellow](run-scoped)[/yellow]" if tool.run_scoped else "")
        if plan_obj.tool_search_surfaced is not None and tool.name in surfaced:
            name += " [green]*[/green]"
        tools_table.add_row(name, tool.tool_type, tool.source, policy_cell)
    if not plan_obj.tools:
        tools_table.add_row("[dim]none[/dim]", "", "", "")
    console.print(tools_table)
    if plan_obj.tool_search_surfaced is not None:
        console.print("  [dim]* surfaced by tool_search for this prompt[/dim]")

    # --- Policies ---
    p = plan_obj.policy
    if p.active:
        body = (
            f"[green]active[/green]  dir={p.policy_dir}\n"
            f"policies={p.policy_count}  rules={p.rule_count}  agent_checks={p.agent_checks}"
        )
    else:
        body = f"[dim]inactive[/dim]\n{p.note or ''}"
    console.print(Panel(body, title="initguard policy", border_style="dim"))

    # --- Guardrails ---
    g_table = Table(title="Guardrails", title_justify="left")
    g_table.add_column("Limit", style="cyan")
    g_table.add_column("Value")
    for item in plan_obj.guardrails:
        g_table.add_row(item.label, item.value)
    console.print(g_table)

    # --- Sandbox ---
    s = plan_obj.sandbox
    style = "green" if s.available else "yellow"
    sb_lines = [f"requested: {s.requested_backend}  resolved: {s.resolved_backend or '-'}"]
    sb_lines.append(f"status: [{style}]{s.status}[/{style}]")
    if s.reason:
        sb_lines.append(f"[dim]{s.reason}[/dim]")
    sb_lines.append(f"network: {s.network}  mounts: {s.mounts_count}")
    console.print(Panel("\n".join(sb_lines), title="Sandbox", border_style="dim"))

    # --- Triggers ---
    if plan_obj.triggers:
        tree = Tree("Armed triggers")
        for tr in plan_obj.triggers:
            auto = " [magenta](autonomous)[/magenta]" if tr.autonomous else ""
            node = tree.add(f"[cyan]{tr.type}[/cyan] [dim]({tr.predictability})[/dim]{auto}")
            node.add(f"[dim]{tr.summary}[/dim]")
            node.add(f"[dim]{tr.detail}[/dim]")
        console.print(tree)

    # --- Cost ---
    cost = plan_obj.cost
    c_table = Table(title="Cost (heuristic estimate)", title_justify="left")
    c_table.add_column("Metric", style="cyan")
    c_table.add_column("Value")
    c_table.add_row("input tokens (est.)", str(cost.estimated_input_tokens))
    c_table.add_row(
        "output tokens (typical/max)",
        f"{cost.estimated_output_tokens_typical}/{cost.estimated_output_tokens_max}",
    )
    c_table.add_row("per run (typical/max)", _fmt_usd(cost.per_run_typical, cost.per_run_max))
    if cost.daily_estimate is not None:
        c_table.add_row("per day / month", _fmt_usd(cost.daily_estimate, cost.monthly_estimate))
    console.print(c_table)
    if cost.assumptions:
        console.print(
            Panel(
                "\n".join(f"- {a}" for a in cost.assumptions),
                title="Cost assumptions",
                border_style="dim",
            )
        )

    # --- Caveats ---
    console.print(
        Panel(
            "\n".join(f"- {c}" for c in plan_obj.caveats),
            title="Caveats",
            border_style="dim",
        )
    )


def _fmt_usd(typical: float | None, maximum: float | None) -> str:
    if typical is None:
        return "[dim]n/a (model/pricing unresolved)[/dim]"
    hi = f" / ${maximum:.4f}" if maximum is not None else ""
    return f"${typical:.4f}{hi}"
