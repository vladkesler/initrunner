"""Skill sub-commands: new, validate, list."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import console
from initrunner.cli._options import SkillDirOption

app = typer.Typer(help="Manage reusable skills.")


@app.command("new")
def skill_new(
    name: Annotated[str, typer.Argument(help="Skill name")] = "my-skill",
    provider: Annotated[str, typer.Option(help="Model provider (for tool defaults)")] = "openai",
) -> None:
    """Scaffold a new skill directory with SKILL.md."""
    from initrunner.templates import template_skill

    skill_dir_path = Path(name)
    skill_file = skill_dir_path / "SKILL.md"
    if skill_dir_path.exists():
        console.print(f"[red]Error:[/red] {skill_dir_path} already exists. Refusing to overwrite.")
        raise typer.Exit(1)
    skill_dir_path.mkdir(parents=True)
    content = template_skill(name, provider)
    skill_file.write_text(content)
    console.print(f"[green]Created[/green] {skill_file}")
    console.print("\n[dim]Next steps:[/dim]")
    console.print(f"  1. Edit {skill_file} to configure tools and prompt")
    console.print("  2. Reference in role.yaml:")
    console.print("     skills:")
    console.print(f"       - {name}")


@app.command("validate")
def skill_validate(
    path: Annotated[Path, typer.Argument(help="Path to SKILL.md file or directory")],
) -> None:
    """Validate a skill definition."""
    from initrunner.agent.skills import SkillLoadError, check_requirements, load_skill

    skill_path = path / "SKILL.md" if path.is_dir() else path
    try:
        skill_def = load_skill(skill_path)
    except SkillLoadError as e:
        console.print(f"[red]Invalid:[/red] {e}")
        raise typer.Exit(1) from None

    statuses = check_requirements(skill_def)

    table = Table(title=f"Skill: {skill_def.frontmatter.name}")
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Name", skill_def.frontmatter.name)
    table.add_row("Description", skill_def.frontmatter.description)
    if skill_def.frontmatter.license:
        table.add_row("License", skill_def.frontmatter.license)
    if skill_def.frontmatter.compatibility:
        table.add_row("Compatibility", skill_def.frontmatter.compatibility)
    if skill_def.frontmatter.metadata:
        meta = ", ".join(f"{k}={v}" for k, v in skill_def.frontmatter.metadata.items())
        table.add_row("Metadata", meta)

    if skill_def.frontmatter.tools:
        table.add_row("Tools", "\n".join(t.summary() for t in skill_def.frontmatter.tools))
    else:
        table.add_row("Tools", "(none)")

    if statuses:
        lines = []
        for s in statuses:
            icon = "[green]ok[/green]" if s.met else f"[red]missing: {s.detail}[/red]"
            lines.append(f"{s.kind}:{s.name} {icon}")
        table.add_row("Requirements", "\n".join(lines))
    else:
        table.add_row("Requirements", "(none)")

    prompt_preview = (
        skill_def.prompt[:200] + "..." if len(skill_def.prompt) > 200 else skill_def.prompt
    )
    table.add_row("Prompt", prompt_preview or "(empty)")

    console.print(table)
    console.print("[green]Valid[/green]")


@app.command("list")
def skill_list(
    skill_dir: SkillDirOption = None,
    auto: Annotated[
        bool,
        typer.Option("--auto", help="Show only auto-discovered skills"),
    ] = False,
    show_all: Annotated[
        bool,
        typer.Option("--all", help="Show both explicit and auto-discovered skills"),
    ] = False,
    role: Annotated[
        Path | None,
        typer.Option("--role", help="Role file for auto-discovery context"),
    ] = None,
) -> None:
    """List available skills."""
    from initrunner.agent.skills import SkillLoadError, load_skill

    explicit_found: list[tuple[str, str, str, Path]] = []
    auto_found: list[tuple[str, str, str, str]] = []

    # --- Explicit skills ---
    if not auto:
        search_dirs: list[Path] = []

        local_skills = Path("./skills")
        if local_skills.is_dir():
            search_dirs.append(local_skills)

        if skill_dir is not None and skill_dir.is_dir():
            search_dirs.append(skill_dir)

        from initrunner.config import get_skills_dir

        global_skills = get_skills_dir()
        if global_skills.is_dir():
            search_dirs.append(global_skills)

        for d in search_dirs:
            for skill_md in sorted(d.glob("*/SKILL.md")):
                try:
                    sd = load_skill(skill_md)
                    tools = ", ".join(t.type for t in sd.frontmatter.tools) or "(none)"
                    explicit_found.append(
                        (sd.frontmatter.name, sd.frontmatter.description, tools, skill_md)
                    )
                except SkillLoadError:
                    pass

            for md_file in sorted(d.glob("*.md")):
                if md_file.name == "SKILL.md":
                    continue
                try:
                    sd = load_skill(md_file)
                    tools = ", ".join(t.type for t in sd.frontmatter.tools) or "(none)"
                    explicit_found.append(
                        (sd.frontmatter.name, sd.frontmatter.description, tools, md_file)
                    )
                except SkillLoadError:
                    pass

    # --- Auto-discovered skills ---
    if auto or show_all:
        from initrunner.agent.auto_skills import discover_skills

        role_dir = role.parent if role else Path(".")
        extra_dirs = [skill_dir] if skill_dir else None
        discovered = discover_skills(role_dir=role_dir, extra_dirs=extra_dirs)
        for ds in discovered:
            auto_found.append((ds.name, ds.description, ds.scope, str(ds.path.parent)))

    if not explicit_found and not auto_found:
        console.print("No skills found. Use [bold]initrunner skill new[/bold] to create one.")
        return

    if explicit_found and not auto:
        table = Table(title="Explicit Skills")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Tools")
        table.add_column("Path", style="dim")

        for name, desc, tools, path in explicit_found:
            table.add_row(name, desc, tools, str(path))

        console.print(table)

    if auto_found:
        table = Table(title="Auto-Discovered Skills")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Scope")
        table.add_column("Source", style="dim")

        for name, desc, scope, source in auto_found:
            table.add_row(name, desc, scope, source)

        console.print(table)
