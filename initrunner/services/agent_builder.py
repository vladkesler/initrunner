"""UI-agnostic multi-turn conversational agent builder.

Provides ``BuilderSession`` -- a stateful, multi-turn builder that uses an LLM
to draft and refine role YAML from various seed inputs (blank template,
named template, natural language description, local file, bundled example, or
hub bundle).

``yaml_text`` is the single source of truth.  ``role`` and ``issues`` are
cached properties that re-parse on demand and invalidate when ``yaml_text``
changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml

from initrunner.role_generator import build_schema_reference

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from initrunner.agent.schema.role import RoleDefinition

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: Literal["error", "warning"]


@dataclass
class TurnResult:
    """Returned by every builder turn."""

    explanation: str  # LLM's explanation / questions
    yaml_text: str  # Full current YAML
    issues: list[ValidationIssue]  # Validation results

    @property
    def ready(self) -> bool:
        """True when no errors remain (warnings are OK)."""
        return not any(i.severity == "error" for i in self.issues)


@dataclass
class PostCreateResult:
    yaml_path: Path
    valid: bool
    issues: list[str]
    next_steps: list[str]  # Contextual based on role features
    omitted_assets: list[str]  # Files from multi-file bundles not imported


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_yaml(text: str) -> tuple[RoleDefinition | None, list[ValidationIssue]]:
    """Parse and validate YAML text, returning the role and any issues."""
    from initrunner.agent.schema.role import RoleDefinition as RoleDef

    issues: list[ValidationIssue] = []

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as e:
        issues.append(
            ValidationIssue(
                field="yaml",
                message=f"Invalid YAML syntax: {e}",
                severity="error",
            )
        )
        return None, issues

    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue(
                field="yaml",
                message="YAML must be a mapping",
                severity="error",
            )
        )
        return None, issues

    try:
        role = RoleDef.model_validate(raw)
    except Exception as e:
        issues.append(ValidationIssue(field="schema", message=str(e), severity="error"))
        return None, issues

    # Warnings for common issues
    if role.spec.role and len(role.spec.role.strip()) < 10:
        issues.append(
            ValidationIssue(
                field="spec.role",
                message="System prompt is very short",
                severity="warning",
            )
        )

    return role, issues


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _strip_yaml_fences(text: str) -> str:
    """Remove markdown code fences wrapping YAML content."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def build_tool_summary() -> str:
    """Generate a concise tool summary from the live registry."""
    from initrunner.agent.tools._registry import get_tool_types

    tool_types = get_tool_types()
    lines = ["# Available tools (use in spec.tools list):"]
    for type_name, config_cls in sorted(tool_types.items()):
        desc_parts = []
        for fname, finfo in config_cls.model_fields.items():
            if fname in ("type", "permissions"):
                continue
            from pydantic_core import PydanticUndefined

            if finfo.default is not PydanticUndefined:
                desc_parts.append(f"{fname}={finfo.default!r}")
            else:
                desc_parts.append(f"{fname}=(required)")
        lines.append(f"- type: {type_name}  # {', '.join(desc_parts)}")
    return "\n".join(lines)


def build_next_steps(role: RoleDefinition, yaml_path: Path) -> list[str]:
    """Generate contextual next-step hints based on role features."""
    steps: list[str] = []
    p = str(yaml_path)

    if role.spec.ingest:
        steps.append(f"initrunner ingest {p}")
    if role.spec.triggers:
        steps.append(f"initrunner run {p} --daemon")
    if role.spec.memory:
        steps.append(f"initrunner run {p} -i")

    if not steps:
        steps.append(f"initrunner run {p} -p 'hello'")

    steps.append(f"initrunner validate {p}")
    return steps


# ---------------------------------------------------------------------------
# Builder LLM prompt
# ---------------------------------------------------------------------------


_BUILDER_SYSTEM_PROMPT = """\
You are an expert InitRunner agent builder. You help users create and refine \
role.yaml configuration files through conversation.

Rules:
- When given a description or refinement request, produce a complete role.yaml.
- Output a brief explanation of what you did or questions you have, followed by \
the complete YAML in a fenced ```yaml block.
- Use apiVersion: initrunner/v1 and kind: Agent.
- metadata.name must match ^[a-z0-9][a-z0-9-]*[a-z0-9]$ (lowercase, hyphens only).
- Pick appropriate tools, triggers, and features based on the description.
- Use sensible defaults for guardrails.
- The spec.role field is the system prompt -- write a good one that matches the description.
- For tool configs, only include fields that differ from defaults.
- Keep YAML clean and minimal.
- Only include sections the agent actually needs.
- CRITICAL: The schema reference below uses dotted paths like "spec.model" for readability. \
In the actual YAML, these MUST be nested under their parent key, NOT used as flat dotted keys.
- When refining, preserve the user's existing choices unless they ask to change them.
- Ask clarifying questions when the request is ambiguous.

{schema_reference}

{tool_summary}
"""


# ---------------------------------------------------------------------------
# BuilderSession
# ---------------------------------------------------------------------------


class BuilderSession:
    """UI-agnostic multi-turn conversational agent builder."""

    def __init__(self) -> None:
        self._yaml_text: str = ""
        self._role_cache: RoleDefinition | None = None
        self._issues_cache: list[ValidationIssue] | None = None
        self._messages: list[ModelMessage] = []
        self._agent: object | None = None  # Lazy PydanticAI Agent
        self.seed_source: str = ""
        self.omitted_assets: list[str] = []

    # -- Properties ----------------------------------------------------------

    @property
    def yaml_text(self) -> str:
        return self._yaml_text

    @yaml_text.setter
    def yaml_text(self, value: str) -> None:
        self._yaml_text = value
        self._role_cache = None
        self._issues_cache = None

    @property
    def role(self) -> RoleDefinition | None:
        """Parse on demand, cache until yaml_text changes."""
        if self._role_cache is None and self._yaml_text:
            self._role_cache, self._issues_cache = _validate_yaml(self._yaml_text)
        return self._role_cache

    @property
    def issues(self) -> list[ValidationIssue]:
        if self._issues_cache is None:
            if not self._yaml_text:
                return []
            self._role_cache, self._issues_cache = _validate_yaml(self._yaml_text)
        return self._issues_cache

    # -- Agent setup ---------------------------------------------------------

    def _get_agent(
        self,
        provider: str,
        model_name: str | None = None,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ):
        """Lazy-init the PydanticAI agent for the builder LLM."""
        if self._agent is not None:
            return self._agent

        from pydantic_ai import Agent

        from initrunner.agent.loader import _build_model
        from initrunner.agent.schema.base import ModelConfig
        from initrunner.templates import _default_model_name

        if model_name is None:
            model_name = _default_model_name(provider)

        schema_ref = build_schema_reference()
        tool_sum = build_tool_summary()
        system = _BUILDER_SYSTEM_PROMPT.format(
            schema_reference=schema_ref,
            tool_summary=tool_sum,
        )

        gen_model_config = ModelConfig(
            provider=provider,
            name=model_name,
            base_url=base_url,
            api_key_env=api_key_env,
        )
        model = _build_model(gen_model_config)

        self._agent = Agent(model, system_prompt=system)
        return self._agent

    # -- Internal helpers ----------------------------------------------------

    def _make_turn_result(self, explanation: str) -> TurnResult:
        return TurnResult(
            explanation=explanation,
            yaml_text=self._yaml_text,
            issues=self.issues,
        )

    def _extract_yaml_from_response(self, text: str) -> tuple[str, str]:
        """Split LLM response into explanation and YAML content.

        Returns (explanation, yaml_text).
        """
        # Look for fenced yaml block
        import re

        fence_pattern = re.compile(r"```(?:ya?ml)?\s*\n(.*?)```", re.DOTALL)
        match = fence_pattern.search(text)
        if match:
            yaml_content = match.group(1).strip()
            explanation = text[: match.start()].strip()
            if not explanation:
                explanation = text[match.end() :].strip()
            return explanation, yaml_content

        # No fences -- check if the whole thing looks like YAML
        if text.strip().startswith("apiVersion:"):
            return "", text.strip()

        # Fallback: return as explanation, keep current yaml
        return text.strip(), self._yaml_text

    # -- Seed flows ----------------------------------------------------------

    def seed_blank(self, provider: str, model: str | None = None) -> TurnResult:
        """Seed from the basic template."""
        from initrunner.templates import template_basic

        self.seed_source = "blank"
        self.yaml_text = template_basic("my-agent", provider, model)
        return self._make_turn_result("Started from blank template. Refine as needed.")

    def seed_template(self, name: str, provider: str, model: str | None = None) -> TurnResult:
        """Seed from a named template."""
        from initrunner.templates import TEMPLATES

        builder = TEMPLATES.get(name)
        if builder is None:
            available = ", ".join(sorted(TEMPLATES.keys()))
            raise ValueError(f"Unknown template '{name}'. Available: {available}")

        # Templates that produce non-YAML (tool, skill) are not valid seeds
        if name in ("tool", "skill"):
            raise ValueError(
                f"Template '{name}' produces a {name} scaffold, not a role YAML. "
                f"Use 'initrunner init --template {name}' instead."
            )

        self.seed_source = f"template:{name}"
        self.yaml_text = builder("my-agent", provider, model)
        return self._make_turn_result(f"Started from '{name}' template. Refine as needed.")

    def seed_description(
        self,
        text: str,
        provider: str,
        model_name: str | None = None,
        *,
        name_hint: str | None = None,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ) -> TurnResult:
        """Seed from a natural language description via LLM."""
        self.seed_source = "description"
        agent = self._get_agent(provider, model_name, base_url=base_url, api_key_env=api_key_env)

        user_prompt = f"Create a role.yaml for: {text}"
        if name_hint:
            user_prompt += f"\nUse the name: {name_hint}"

        result = agent.run_sync(user_prompt)
        self._messages = list(result.all_messages())

        explanation, yaml_content = self._extract_yaml_from_response(result.output)
        self.yaml_text = yaml_content

        # Auto-repair on validation failure
        if any(i.severity == "error" for i in self.issues):
            yaml_content = self._auto_repair(
                provider, model_name, base_url=base_url, api_key_env=api_key_env
            )
            if yaml_content is not None:
                self.yaml_text = yaml_content

        return self._make_turn_result(explanation or "Generated from your description.")

    def seed_from_file(self, path: Path) -> TurnResult:
        """Seed from a local YAML file."""
        self.seed_source = f"file:{path}"
        self.yaml_text = path.read_text(encoding="utf-8")
        return self._make_turn_result(f"Loaded from {path}. Refine as needed.")

    def seed_from_example(self, name: str) -> TurnResult:
        """Seed from a bundled example."""
        from initrunner.examples import ExampleNotFoundError, get_example

        try:
            entry = get_example(name)
        except ExampleNotFoundError:
            raise ValueError(f"Example '{name}' not found in catalog.") from None

        self.seed_source = f"example:{name}"
        self.yaml_text = entry.primary_content

        # Track omitted sidecar files
        if entry.multi_file:
            self.omitted_assets = [f for f in entry.files if f != entry.primary_file]

        explanation = f"Loaded example '{name}': {entry.description}"
        if self.omitted_assets:
            explanation += (
                f"\nNote: This example has additional files not included in the builder: "
                f"{', '.join(self.omitted_assets)}. "
                f"Use 'initrunner examples copy {name}' to get all files."
            )

        return self._make_turn_result(explanation)

    def seed_from_hub(self, ref: str) -> TurnResult:
        """Seed from a hub bundle (fetches role YAML only)."""
        from initrunner.services.packaging import pull_role

        self.seed_source = f"hub:{ref}"

        extracted_path = pull_role(ref)
        # Find the role YAML in the extracted bundle
        role_files = list(extracted_path.glob("*.yaml")) + list(extracted_path.glob("*.yml"))
        if not role_files:
            raise ValueError(f"No YAML files found in hub bundle '{ref}'")

        primary = role_files[0]
        self.yaml_text = primary.read_text(encoding="utf-8")

        # Track other files as omitted
        all_files = list(extracted_path.rglob("*"))
        self.omitted_assets = [
            str(f.relative_to(extracted_path)) for f in all_files if f.is_file() and f != primary
        ]

        explanation = f"Loaded from hub: {ref}"
        if self.omitted_assets:
            explanation += (
                f"\nNote: Bundle contains additional files not loaded: "
                f"{', '.join(self.omitted_assets)}"
            )

        return self._make_turn_result(explanation)

    # -- Refinement ----------------------------------------------------------

    def refine(
        self,
        user_input: str,
        provider: str,
        model_name: str | None = None,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ) -> TurnResult:
        """Refine the current YAML based on user input."""
        agent = self._get_agent(provider, model_name, base_url=base_url, api_key_env=api_key_env)

        prompt = (
            f"Current role.yaml:\n```yaml\n{self._yaml_text}\n```\n\nUser request: {user_input}"
        )

        result = agent.run_sync(prompt, message_history=self._messages or None)
        self._messages = list(result.all_messages())

        explanation, yaml_content = self._extract_yaml_from_response(result.output)
        self.yaml_text = yaml_content

        # Auto-repair on validation failure
        if any(i.severity == "error" for i in self.issues):
            repaired = self._auto_repair(
                provider, model_name, base_url=base_url, api_key_env=api_key_env
            )
            if repaired is not None:
                self.yaml_text = repaired

        return self._make_turn_result(explanation or "Updated based on your request.")

    def _auto_repair(
        self,
        provider: str,
        model_name: str | None,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ) -> str | None:
        """One automatic repair retry. Returns fixed YAML or None."""
        errors = [i for i in self.issues if i.severity == "error"]
        if not errors:
            return None

        agent = self._get_agent(provider, model_name, base_url=base_url, api_key_env=api_key_env)
        error_text = "\n".join(f"- {e.field}: {e.message}" for e in errors)
        repair_prompt = (
            f"The YAML you generated has validation errors:\n{error_text}\n\n"
            f"Fix the issues and output the corrected YAML in a ```yaml block."
        )

        _logger.info("Auto-repairing: %s", error_text)
        result = agent.run_sync(repair_prompt, message_history=self._messages or None)
        self._messages = list(result.all_messages())

        _, yaml_content = self._extract_yaml_from_response(result.output)
        return yaml_content

    # -- Post-creation -------------------------------------------------------

    def save(self, path: Path, *, force: bool = False) -> PostCreateResult:
        """Validate and write the current YAML to disk."""
        from initrunner.services.roles import save_role_yaml_sync

        issue_strings: list[str] = []
        valid = True

        if path.exists() and not force:
            raise FileExistsError(f"{path} already exists. Use --force to overwrite.")

        try:
            role = save_role_yaml_sync(path, self._yaml_text)
        except (ValueError, Exception) as e:
            # Write anyway but note the issue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._yaml_text)
            issue_strings.append(str(e))
            valid = False
            role = self.role

        next_steps = build_next_steps(role, path) if role else [f"initrunner validate {path}"]

        return PostCreateResult(
            yaml_path=path,
            valid=valid,
            issues=issue_strings,
            next_steps=next_steps,
            omitted_assets=self.omitted_assets,
        )
