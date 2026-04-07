"""Team YAML scaffolding and validation for the dashboard builder."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.team.schema import TeamDefinition

from initrunner.services._yaml_validation import (
    ValidationIssue,
    parse_yaml_text,
    unwrap_pydantic_error,
)


def build_blank_team_yaml(
    name: str,
    strategy: str = "sequential",
    persona_count: int = 2,
    provider: str = "openai",
    model: str | None = None,
    personas: list[dict] | None = None,
    debate_max_rounds: int = 3,
    debate_synthesize: bool = True,
) -> str:
    """Generate a minimal valid Team YAML from parameters.

    When *personas* is provided it takes precedence over *persona_count*.
    Each dict may contain ``name``, ``role``, and an optional ``model`` dict
    with ``provider``, ``name``, ``base_url``, ``api_key_env``.
    """
    model_name = model or "gpt-5-mini"
    personas_block = _build_personas_block(personas, persona_count)

    debate_block = ""
    if strategy == "debate":
        debate_block = (
            f"  debate:\n"
            f"    max_rounds: {debate_max_rounds}\n"
            f"    synthesize: {'true' if debate_synthesize else 'false'}\n"
        )

    return (
        f"apiVersion: initrunner/v1\n"
        f"kind: Team\n"
        f"metadata:\n"
        f"  name: {name}\n"
        f'  description: ""\n'
        f"spec:\n"
        f"  model:\n"
        f"    provider: {provider}\n"
        f"    name: {model_name}\n"
        f"  strategy: {strategy}\n"
        f"{debate_block}"
        f"  personas:\n"
        f"{personas_block}"
        f"  tools: []\n"
        f"  guardrails:\n"
        f"    max_tokens_per_run: 50000\n"
        f"    timeout_seconds: 300\n"
    )


def _build_personas_block(
    personas: list[dict] | None,
    persona_count: int,
) -> str:
    """Build the YAML ``personas:`` block as an indented string."""
    if not personas:
        lines = ""
        for i in range(max(persona_count, 2)):
            pname = _persona_name(i)
            lines += f'    {pname}: "describe this persona\'s role"\n'
        return lines

    lines = ""
    for entry in personas:
        pname = entry.get("name", "persona")
        role = entry.get("role", "")
        model_cfg = entry.get("model")

        if model_cfg:
            lines += f"    {pname}:\n"
            role_str = role or "describe this persona's role"
            lines += f'      role: "{_escape_yaml_str(role_str)}"\n'
            lines += "      model:\n"
            lines += f"        provider: {model_cfg['provider']}\n"
            lines += f"        name: {model_cfg['name']}\n"
            if model_cfg.get("base_url"):
                lines += f"        base_url: {model_cfg['base_url']}\n"
            if model_cfg.get("api_key_env"):
                lines += f"        api_key_env: {model_cfg['api_key_env']}\n"
        elif role:
            lines += f'    {pname}: "{_escape_yaml_str(role)}"\n'
        else:
            lines += f'    {pname}: "describe this persona\'s role"\n'

    return lines


def _escape_yaml_str(s: str) -> str:
    """Escape a string for safe embedding inside double-quoted YAML."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _persona_name(index: int) -> str:
    """Generate a default persona name for the given index."""
    names = [
        "analyst",
        "reviewer",
        "advisor",
        "checker",
        "specialist",
        "evaluator",
        "auditor",
        "planner",
    ]
    if index < len(names):
        return names[index]
    return f"persona-{index + 1}"


def validate_team_yaml(text: str) -> tuple[TeamDefinition | None, list[ValidationIssue]]:
    """Parse and validate team YAML, returning the definition and any issues."""
    raw, issues = parse_yaml_text(text)
    if raw is None:
        return None, issues

    from initrunner.deprecations import validate_team_dict

    try:
        team, _hits = validate_team_dict(raw)
    except Exception as exc:
        issues.extend(unwrap_pydantic_error(exc))
        return None, issues

    # Cross-field warnings
    if team.spec.strategy == "parallel" and len(team.spec.personas) == 2:
        issues.append(
            ValidationIssue(
                field="spec.strategy",
                message=(
                    "Parallel strategy with only 2 personas has limited benefit over sequential"
                ),
                severity="info",
            )
        )

    if not team.spec.tools and all(not p.tools for p in team.spec.personas.values()):
        issues.append(
            ValidationIssue(
                field="spec.tools",
                message="No tools configured for team or any persona",
                severity="info",
            )
        )

    return team, issues


def build_team_next_steps(path: Path, team: TeamDefinition) -> list[str]:
    """Generate contextual CLI hints based on team features."""
    steps: list[str] = []
    steps.append(f'Run: initrunner run {path} -p "your task"')

    if team.spec.shared_documents.enabled and team.spec.shared_documents.sources:
        steps.append("Shared documents will be ingested on first run")

    if team.spec.shared_memory.enabled:
        steps.append("Shared memory is enabled -- personas will share a memory store")

    if team.spec.strategy == "debate":
        rounds = team.spec.debate.max_rounds
        synth = "with synthesis" if team.spec.debate.synthesize else "no synthesis"
        steps.append(
            f"Debate strategy: {rounds} rounds, {len(team.spec.personas)} "
            f"personas per round ({synth})"
        )
    elif team.spec.strategy == "parallel":
        steps.append(f"Parallel strategy: all {len(team.spec.personas)} personas run concurrently")
    else:
        max_chars = team.spec.handoff_max_chars
        steps.append(
            f"Sequential strategy: personas run in order with handoff (max {max_chars} chars)"
        )

    return steps
