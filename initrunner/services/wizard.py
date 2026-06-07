"""Pure data and deterministic builders for the ``initrunner new`` wizard.

This module holds the catalog and assembly logic behind the guided start menu
and the offline (no-LLM) structured form. It is intentionally free of ``rich``
and ``typer`` so it stays unit-testable; the interactive prompting lives in
``initrunner/cli/new_cmd.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from initrunner.examples import ExampleEntry

# Agent name rule, mirrored from the role schema / builder system prompt.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

# Tools omitted from the offline form: they require nested or
# validator-dependent config a flat field prompt cannot capture in v1. They
# remain reachable via AI refinement or hand-editing.
_EXCLUDED_OFFLINE_TOOLS = frozenset({"mcp"})


# ---------------------------------------------------------------------------
# Start menu
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StartOption:
    """One row of the guided start menu."""

    key: str  # describe | template | example | offline | import
    label: str
    annotation: str  # credential implication, shown dim
    needs_llm: bool


START_OPTIONS: list[StartOption] = [
    StartOption("describe", "Describe it in natural language", "AI generates it", True),
    StartOption("template", "Start from a template", "no API key needed", False),
    StartOption("example", "Start from a bundled example", "no API key needed", False),
    StartOption("offline", "Build it manually, no AI", "no API key needed", False),
    StartOption("import", "Import LangChain / PydanticAI / Agent Spec", "AI assists", True),
]


def list_wizard_templates() -> list[tuple[str, str]]:
    """Return ``(name, description)`` pairs for the template picker."""
    from initrunner.templates import WIZARD_TEMPLATES

    return list(WIZARD_TEMPLATES.items())


def list_example_entries(category: str = "role") -> list[ExampleEntry]:
    """Return bundled example entries for the example picker."""
    from initrunner.examples import list_examples

    return list_examples(category=category)


# ---------------------------------------------------------------------------
# Tool catalog (offline form)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolChoice:
    """A tool offered in the offline form's multi-select."""

    type: str
    description: str
    fields: list[tuple[str, str, str]]  # (field, prompt, default) from TOOL_PROMPT_FIELDS
    required_fields: list[str]  # fields that must be supplied (else skip the tool)


def _required_fields(tool_type: str, prompt_fields: list[tuple[str, str, str]]) -> list[str]:
    """Fields the user must supply: schema-required, plus blank-default prompts.

    A blank default in ``TOOL_PROMPT_FIELDS`` (e.g. ``slack.webhook_url``) marks
    a field with no sensible default that the tool needs to function, even when
    the schema types it as optional.
    """
    required: list[str] = []
    try:
        from initrunner.agent.tools._registry import get_tool_types

        config_cls = get_tool_types().get(tool_type)
    except Exception:  # pragma: no cover - registry import is reliable in practice
        config_cls = None

    if config_cls is not None:
        for name, info in config_cls.model_fields.items():
            if name == "type":
                continue
            if info.is_required():
                required.append(name)

    for name, _prompt, default in prompt_fields:
        if default == "" and name not in required:
            required.append(name)
    return required


def list_tool_choices() -> list[ToolChoice]:
    """Curated, deterministic tool list for the offline form.

    Sourced from ``TOOL_DESCRIPTIONS`` (the simple, flat-promptable tools),
    minus ``_EXCLUDED_OFFLINE_TOOLS``. Insertion order is preserved.
    """
    from initrunner.templates import TOOL_DESCRIPTIONS, TOOL_PROMPT_FIELDS

    choices: list[ToolChoice] = []
    for tool_type, description in TOOL_DESCRIPTIONS.items():
        if tool_type in _EXCLUDED_OFFLINE_TOOLS:
            continue
        prompt_fields = TOOL_PROMPT_FIELDS.get(tool_type, [])
        choices.append(
            ToolChoice(
                type=tool_type,
                description=description,
                fields=prompt_fields,
                required_fields=_required_fields(tool_type, prompt_fields),
            )
        )
    return choices


# ---------------------------------------------------------------------------
# Value coercion + name validation
# ---------------------------------------------------------------------------


def coerce_field_value(raw: str) -> Any:
    """Parse a user-entered scalar into its natural type.

    ``"100"`` -> ``100``, ``"true"`` -> ``True``, ``"[a, b]"`` -> ``["a", "b"]``,
    ``"./data.db"`` -> ``"./data.db"``. An empty string yields ``None`` so the
    caller can tell a required field was left blank.
    """
    import yaml

    text = raw.strip()
    if text == "":
        return None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return raw


def validate_agent_name(name: str) -> bool:
    """True if *name* matches the role schema's metadata.name pattern."""
    return bool(_NAME_RE.match(name))


# ---------------------------------------------------------------------------
# Offline form assembly
# ---------------------------------------------------------------------------


@dataclass
class OfflineFormSpec:
    """Answers collected by the offline form, ready for assembly."""

    name: str
    description: str
    system_prompt: str
    provider: str
    model: str | None
    tools: list[dict[str, Any]] = field(default_factory=list)
    memory: bool = False
    ingest_sources: list[str] | None = None
    triggers: list[dict[str, Any]] | None = None


def build_offline_yaml(spec: OfflineFormSpec) -> str:
    """Assemble a valid role.yaml from form answers (no LLM/network call)."""
    from initrunner.services.roles import build_role_yaml_sync

    ingest = {"sources": spec.ingest_sources} if spec.ingest_sources else None
    return build_role_yaml_sync(
        name=spec.name,
        description=spec.description,
        provider=spec.provider,
        model_name=spec.model,
        system_prompt=spec.system_prompt,
        tools=spec.tools or None,
        memory=spec.memory,
        ingest=ingest,
        triggers=spec.triggers or None,
    )
