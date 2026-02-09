"""Skill sub-commands: validate, list."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from initrunner.cli._helpers import console

app = typer.Typer(help="Manage reusable skills.")


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
    skill_dir: Annotated[
        Path | None, typer.Option("--skill-dir", help="Extra directory to scan")
    ] = None,
) -> None:
    """List available skills."""
    from initrunner.agent.skills import SkillLoadError, load_skill

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

    skills_found: list[tuple[str, str, str, Path]] = []

    for d in search_dirs:
        for skill_md in sorted(d.glob("*/SKILL.md")):
            try:
                sd = load_skill(skill_md)
                tools = ", ".join(t.type for t in sd.frontmatter.tools) or "(none)"
                skills_found.append(
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
                skills_found.append(
                    (sd.frontmatter.name, sd.frontmatter.description, tools, md_file)
                )
            except SkillLoadError:
                pass

    if not skills_found:
        console.print(
            "No skills found. Use [bold]initrunner init --template skill[/bold] to create one."
        )
        return

    table = Table(title="Available Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Tools")
    table.add_column("Path", style="dim")

    for name, desc, tools, path in skills_found:
        table.add_row(name, desc, tools, str(path))

    console.print(table)
