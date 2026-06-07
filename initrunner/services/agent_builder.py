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
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from initrunner.role_generator import build_schema_reference
from initrunner.services._yaml_validation import (
    ValidationIssue,
    parse_yaml_text,
    unwrap_pydantic_error,
)

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage

    from initrunner.agent.schema.role import RoleDefinition

_logger = logging.getLogger(__name__)

# Cap the LLM transcript carried across refinements. Trimming is boundary-aware
# (see ``BuilderSession._trim_messages``) so a slice never starts mid-exchange.
_MAX_HISTORY_MESSAGES = 40


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


# ValidationIssue is re-exported from _yaml_validation for backward compat.
__all__ = ["ValidationIssue"]


@dataclass
class TurnResult:
    """Returned by every builder turn."""

    explanation: str  # LLM's explanation / questions
    yaml_text: str  # Full current YAML
    issues: list[ValidationIssue]  # Validation results
    import_warnings: list[str] = field(default_factory=list)  # Lossy import warnings
    test_prompt: str | None = None  # Tailored test prompt extracted from explanation

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
    generated_assets: list[str] = field(default_factory=list)  # Written sidecar paths


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_yaml(text: str) -> tuple[RoleDefinition | None, list[ValidationIssue]]:
    """Parse and validate YAML text, returning the role and any issues."""
    raw, issues = parse_yaml_text(text)
    if raw is None:
        return None, issues

    from initrunner.deprecations import validate_role_dict

    try:
        role, _hits = validate_role_dict(raw)
    except Exception as e:
        issues.extend(unwrap_pydantic_error(e))
        return None, issues

    # Cross-field reasoning validation
    from initrunner.agent.loader import (
        RoleLoadError,
        _validate_reasoning,
        validate_capability_tool_conflicts,
    )

    try:
        _validate_reasoning(role)
    except RoleLoadError as e:
        issues.append(ValidationIssue(field="spec.reasoning", message=str(e), severity="error"))

    # Capability / tool conflict validation
    try:
        validate_capability_tool_conflicts(role)
    except RoleLoadError as e:
        issues.append(ValidationIssue(field="spec.capabilities", message=str(e), severity="error"))

    # Warnings for common issues
    if role.spec.role and len(role.spec.role.strip()) < 10:
        issues.append(
            ValidationIssue(
                field="spec.role",
                message="System prompt is very short",
                severity="warning",
            )
        )

    # Recommendations
    from initrunner.agent.schema.tools import ThinkToolConfig

    if role.spec.reasoning and role.spec.reasoning.pattern == "reflexion":
        has_think_critique = any(
            isinstance(t, ThinkToolConfig) and t.critique for t in role.spec.tools
        )
        if not has_think_critique:
            issues.append(
                ValidationIssue(
                    field="spec.tools",
                    message="Think tool with critique: true recommended for reflexion pattern",
                    severity="info",
                )
            )

    if role.spec.reasoning and role.spec.reasoning.pattern != "react" and not role.spec.autonomy:
        issues.append(
            ValidationIssue(
                field="spec.autonomy",
                message="Autonomy block recommended for non-react reasoning patterns",
                severity="info",
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


_TEST_PROMPT_RE = re.compile(
    r"^[ \t]*test prompt:[ \t]*(\S[^\r\n]*?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_test_prompt(explanation: str) -> tuple[str | None, str]:
    """Pull a ``Test prompt: ...`` line out of explanation text.

    Returns ``(test_prompt, explanation_without_line)``. Outer quotes wrapping
    the prompt are stripped. If no marker line is present, or the prompt is
    empty/whitespace after stripping, returns ``(None, explanation)`` with the
    explanation untouched.
    """
    match = _TEST_PROMPT_RE.search(explanation)
    if not match:
        return None, explanation
    prompt = match.group(1).strip().strip("\"'").strip()
    if not prompt:
        return None, explanation
    cleaned = (explanation[: match.start()] + explanation[match.end() :]).strip()
    return prompt, cleaned


def sanitize_module_stem(stem: str, *, fallback: str = "agent") -> str:
    """Turn an arbitrary file stem into a valid Python module identifier.

    Maps non-identifier characters to ``_``, strips edge underscores, and
    prefixes ``fallback`` when the result is empty or starts with a digit
    (e.g. ``2fa-bot`` -> ``agent_2fa_bot``, ``role.v2`` -> ``role_v2``).
    """
    s = re.sub(r"[^0-9a-zA-Z_]", "_", stem).strip("_")
    if not s:
        return fallback
    if s[0].isdigit():
        s = f"{fallback}_{s}"
    return s if s.isidentifier() else fallback


def build_tool_summary() -> str:
    """Generate a concise tool summary (delegates to shared implementation)."""
    from initrunner.role_generator import build_tool_summary as _shared

    return _shared()


def build_next_steps(role: RoleDefinition, yaml_path: Path) -> list[str]:
    """Generate contextual next-step hints based on role features."""
    steps: list[str] = []
    p = str(yaml_path)

    # Trigger-specific prerequisites (deduped)
    seen_extras: set[str] = set()
    for trigger in role.spec.triggers or []:
        if trigger.type == "discord" and "discord" not in seen_extras:
            seen_extras.add("discord")
            steps.append("export DISCORD_BOT_TOKEN='your-token-here'")
            steps.append("uv sync --extra discord")
        elif trigger.type == "telegram" and "telegram" not in seen_extras:
            seen_extras.add("telegram")
            steps.append("export TELEGRAM_BOT_TOKEN='your-token-here'")
            steps.append("uv sync --extra telegram")

    if role.spec.ingest:
        steps.append(f"initrunner ingest {p}")
    if role.spec.triggers:
        steps.append(f"initrunner run {p} --daemon")
    if role.spec.memory:
        steps.append(f"initrunner run {p} -i")

    if not any(s.startswith("initrunner") for s in steps):
        steps.append(f"initrunner run {p} -p 'hello'")

    steps.append(f"initrunner validate {p}")
    return steps


# ---------------------------------------------------------------------------
# Builder LLM prompt
# ---------------------------------------------------------------------------


_BUILDER_SYSTEM_PROMPT = """\
You are an expert InitRunner agent builder. You produce minimal role.yaml files.

Rules:
- Output a brief explanation followed by the YAML in a fenced ```yaml block.
- In your explanation (BEFORE the YAML block), include a single line of the form \
`Test prompt: <one short, concrete prompt that exercises this agent>`. \
Make it specific to the agent's task -- not "hello". \
Omit the line if the agent is daemon-only (triggers + no useful one-shot mode) \
or needs ingestion before being useful.
- metadata.name must match ^[a-z0-9][a-z0-9-]*[a-z0-9]$ (lowercase, hyphens only).
- Always include metadata.spec_version: 2.
- spec.role is the system prompt -- write a focused one for the agent's task.
- NEVER include fields that match their default value. Omit them entirely.
- NEVER include null or empty fields.
- NEVER include sections the agent doesn't need (output, auto_skills, tool_search, daemon, \
security, observability -- omit unless the user explicitly asks for them).
- For tools, only write `- type: <name>`. Add fields only when non-default.
- NEVER declare both a capability and its equivalent tool. \
NEVER declare both a capability and its equivalent tool. Choose the best one per function:
- Web search: use WebSearch capability (model-native search, reliable). \
Only use type: search if the user needs a specific provider (brave, serpapi, tavily).
- URL fetching: use type: web_reader tool (SSRF protection, domain filtering). \
Do NOT use WebFetch capability.
- Image generation: use ImageGeneration capability. \
Only use type: image_gen if the user needs a non-OpenAI model.
- Thinking: use Thinking capability for extended reasoning.
- When refining, preserve existing choices unless asked to change them.
- A typical role is 30-50 lines. If yours exceeds 60, you are over-specifying.

Example of a well-structured minimal role:
```yaml
apiVersion: initrunner/v1
kind: Agent
metadata:
  name: news-monitor
  description: Monitors and summarizes breaking news
  tags: [news, monitoring]
  spec_version: 2
spec:
  model:
    provider: openai
    name: gpt-5.4-mini-2026-03-17
  role: |
    You monitor breaking news. Search for the latest headlines,
    summarize key events, and cite sources with links.
  tools:
    - type: web_reader
  capabilities:
    - WebSearch
    - Thinking: low
  triggers:
    - type: cron
      schedule: "0 * * * *"
      prompt: Summarize the latest breaking news.
      autonomous: true
```

Add memory, autonomy, ingest, or other sections only when the user's description calls for them.

Feature guide (use the right section for each request):
- RAG / document ingestion / knowledge base = `ingest` section. `sources` is required:
  ingest:
    sources:
      - ./docs
  NEVER write `ingest: {{}}`. Always ask the user for the source path if not provided.
- Memory / remember across sessions = `memory` section. \
`memory: {{}}` enables all defaults and is valid. \
Only add sub-fields when the user needs specific tuning:
  memory:
    semantic:
      max_memories: 500
- RAG and memory are independent features. RAG retrieves from ingested \
documents; memory stores agent experiences across sessions. \
Add both when the user asks for both.

{schema_reference}

{tool_summary}
"""


# ---------------------------------------------------------------------------
# YAML model-block rewrite helper
# ---------------------------------------------------------------------------


def rewrite_model_block(
    yaml_text: str,
    *,
    provider: str | None = None,
    name: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> str:
    """Replace or inject fields in the spec.model block.

    Scoped by indentation: enters the block when ``  model:`` is found
    (spec-level indent) and exits when indentation returns to that level
    or above.  ``provider:`` and ``name:`` lines are *replaced* in-place;
    ``base_url`` and ``api_key_env`` are *injected* after the ``name:`` line.
    """
    lines = yaml_text.split("\n")
    result: list[str] = []
    in_model = False
    model_indent = 0
    injected = False

    for line in lines:
        stripped = line.lstrip()

        # Detect entry into spec.model block
        if not in_model and stripped == "model:" and line.startswith("  model:"):
            in_model = True
            model_indent = len(line) - len(stripped)
            result.append(line)
            continue

        # Inside model block -- check if we've exited (indentation <= model key)
        if in_model and stripped and not stripped.startswith("#"):
            current_indent = len(line) - len(stripped)
            if current_indent <= model_indent:
                in_model = False

        if in_model:
            field_indent = " " * (len(line) - len(stripped))
            # Replace provider: line
            if provider is not None and stripped.startswith("provider:"):
                result.append(f"{field_indent}provider: {provider}")
                continue
            # Replace name: line, then inject trailing fields
            if stripped.startswith("name:"):
                if name is not None:
                    result.append(f"{field_indent}name: {name}")
                else:
                    result.append(line)
                if not injected:
                    if base_url is not None:
                        result.append(f"{field_indent}base_url: {base_url}")
                    if api_key_env is not None:
                        result.append(f"{field_indent}api_key_env: {api_key_env}")
                    injected = True
                continue

        result.append(line)

    return "\n".join(result)


# Backward-compat alias used by dashboard routers.
_rewrite_model_block = rewrite_model_block


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
        self.import_warnings: list[str] = []
        self._sidecar_source: str | None = None  # Custom tool module content
        self._history: list[str] = []  # YAML snapshots for undo (turn boundaries)
        self._last_test_prompt: str | None = None  # Survives non-LLM command turns

    # -- Properties ----------------------------------------------------------

    @property
    def yaml_text(self) -> str:
        return self._yaml_text

    @yaml_text.setter
    def yaml_text(self, value: str) -> None:
        self._yaml_text = value
        self._role_cache = None
        self._issues_cache = None
        self._canonicalize_if_valid()

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

    def _canonicalize_if_valid(self) -> None:
        """Minimize YAML if it parses and validates without errors."""
        role, issues = _validate_yaml(self._yaml_text)
        self._role_cache = role
        self._issues_cache = issues
        if role is not None and not any(i.severity == "error" for i in issues):
            from initrunner.services.roles import canonicalize_role_yaml

            self._yaml_text = canonicalize_role_yaml(role)

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

        self._agent = Agent(model, instructions=system)
        return self._agent

    # -- Internal helpers ----------------------------------------------------

    def _make_turn_result(self, explanation: str) -> TurnResult:
        test_prompt, cleaned = _extract_test_prompt(explanation)
        # Record the freshly extracted prompt (may be None when an AI turn
        # changes the agent) so command-only turns can carry it forward.
        self._last_test_prompt = test_prompt
        return TurnResult(
            explanation=cleaned,
            yaml_text=self._yaml_text,
            issues=self.issues,
            import_warnings=list(self.import_warnings),
            test_prompt=test_prompt,
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

    def seed_blank(
        self, provider: str, model: str | None = None, *, agent_name: str = "my-agent"
    ) -> TurnResult:
        """Seed from the basic template."""
        from initrunner.templates import template_basic

        self.seed_source = "blank"
        self.yaml_text = template_basic(agent_name, provider, model)
        return self._make_turn_result("Started from blank template. Refine as needed.")

    def seed_template(
        self,
        template_name: str,
        provider: str,
        model: str | None = None,
        *,
        agent_name: str = "my-agent",
    ) -> TurnResult:
        """Seed from a named template."""
        from initrunner.templates import TEMPLATES

        builder = TEMPLATES.get(template_name)
        if builder is None:
            available = ", ".join(sorted(TEMPLATES.keys()))
            raise ValueError(f"Unknown template '{template_name}'. Available: {available}")

        # Templates that produce non-YAML (tool, skill) are not valid seeds
        if template_name in ("tool", "skill"):
            raise ValueError(
                f"Template '{template_name}' produces a {template_name} scaffold, not a role YAML. "
                f"Use 'initrunner init --template {template_name}' instead."
            )

        self.seed_source = f"template:{template_name}"
        self.yaml_text = builder(agent_name, provider, model)
        return self._make_turn_result(f"Started from '{template_name}' template. Refine as needed.")

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
        self._trim_messages()

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

    def seed_yaml(self, text: str, *, source_label: str = "form") -> TurnResult:
        """Seed from pre-built YAML text (deterministic, no LLM/network).

        Used by the offline structured-form path. The ``yaml_text`` setter
        validates and canonicalizes, so the result flows into the same
        display/refine/save path as any other seed.
        """
        self.seed_source = source_label
        self.yaml_text = text
        return self._make_turn_result("Built from your answers. Refine as needed, or save.")

    def seed_from_agent_spec(self, path: Path) -> TurnResult:
        """Seed from a PydanticAI Agent Spec YAML/JSON file (deterministic)."""
        import yaml

        from initrunner.services.agent_spec_import import load_agent_spec

        self.seed_source = f"agent-spec:{path}"
        role_dict = load_agent_spec(path)
        warnings = role_dict.pop("_import_warnings", [])
        self.yaml_text = yaml.safe_dump(role_dict, sort_keys=False)
        self.import_warnings = list(warnings)
        explanation = f"Imported PydanticAI Agent Spec from {path}."
        if warnings:
            explanation += "\nSome fields were dropped (see warnings)."
        return self._make_turn_result(explanation)

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

    def seed_from_langchain(
        self,
        source_path: Path,
        provider: str,
        model_name: str | None = None,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ) -> TurnResult:
        """Seed from a LangChain Python file via AST extraction + LLM normalization."""
        self.seed_source = f"langchain:{source_path}"
        source = source_path.read_text(encoding="utf-8")
        return self.seed_from_langchain_source(
            source, provider, model_name, base_url=base_url, api_key_env=api_key_env
        )

    def seed_from_langchain_source(
        self,
        source: str,
        provider: str,
        model_name: str | None = None,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ) -> TurnResult:
        """Seed from LangChain Python source string via AST extraction + LLM normalization."""
        from initrunner.services._langchain_prompt import LANGCHAIN_IMPORT_PROMPT
        from initrunner.services.langchain_import import (
            build_sidecar_module,
            extract_langchain_import,
            validate_sidecar_imports,
        )

        if not self.seed_source:
            self.seed_source = "langchain:source"

        # 1. AST extraction (deterministic)
        lc_import = extract_langchain_import(source)

        # 2. Build sidecar module for custom tools
        sidecar = build_sidecar_module(lc_import)
        if sidecar is not None:
            self._sidecar_source = sidecar
            sandbox_warnings = validate_sidecar_imports(sidecar)
            lc_import.warnings.extend(sandbox_warnings)

        # 3. Store warnings
        self.import_warnings = list(lc_import.warnings)

        # 4. LLM normalization -- build a one-shot import agent (not cached)
        from pydantic_ai import Agent

        from initrunner.agent.loader import _build_model
        from initrunner.agent.schema.base import ModelConfig
        from initrunner.templates import _default_model_name

        if model_name is None:
            model_name = _default_model_name(provider)

        schema_ref = build_schema_reference()
        tool_sum = build_tool_summary()
        system = LANGCHAIN_IMPORT_PROMPT.format(
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
        import_agent = Agent(model, instructions=system)

        # 5. Send structured summary to LLM
        prompt_text = lc_import.to_prompt_text()
        result = import_agent.run_sync(
            f"Convert this LangChain agent to an InitRunner role.yaml:\n\n{prompt_text}"
        )
        self._messages = list(result.all_messages())
        self._trim_messages()

        explanation, yaml_content = self._extract_yaml_from_response(result.output)
        self.yaml_text = yaml_content

        # 6. Auto-repair on validation failure
        if any(i.severity == "error" for i in self.issues):
            repaired = self._auto_repair(
                provider, model_name, base_url=base_url, api_key_env=api_key_env
            )
            if repaired is not None:
                self.yaml_text = repaired

        return self._make_turn_result(explanation or "Imported from LangChain source.")

    def seed_from_pydanticai(
        self,
        source_path: Path,
        provider: str,
        model_name: str | None = None,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ) -> TurnResult:
        """Seed from a PydanticAI Python file via AST extraction + LLM normalization."""
        self.seed_source = f"pydanticai:{source_path}"
        source = source_path.read_text(encoding="utf-8")
        return self.seed_from_pydanticai_source(
            source, provider, model_name, base_url=base_url, api_key_env=api_key_env
        )

    def seed_from_pydanticai_source(
        self,
        source: str,
        provider: str,
        model_name: str | None = None,
        *,
        base_url: str | None = None,
        api_key_env: str | None = None,
    ) -> TurnResult:
        """Seed from PydanticAI Python source string via AST extraction + LLM normalization."""
        from initrunner.services._pydanticai_prompt import PYDANTICAI_IMPORT_PROMPT
        from initrunner.services.pydanticai_import import (
            build_sidecar_module,
            extract_pydanticai_import,
            validate_sidecar_imports,
        )

        if not self.seed_source:
            self.seed_source = "pydanticai:source"

        # 1. AST extraction (deterministic)
        pai_import = extract_pydanticai_import(source)

        # 2. Build sidecar module for custom tools
        sidecar = build_sidecar_module(pai_import)
        if sidecar is not None:
            self._sidecar_source = sidecar
            sandbox_warnings = validate_sidecar_imports(sidecar)
            pai_import.warnings.extend(sandbox_warnings)

        # 3. Store warnings
        self.import_warnings = list(pai_import.warnings)

        # 4. LLM normalization -- build a one-shot import agent (not cached)
        from pydantic_ai import Agent

        from initrunner.agent.loader import _build_model
        from initrunner.agent.schema.base import ModelConfig
        from initrunner.templates import _default_model_name

        if model_name is None:
            model_name = _default_model_name(provider)

        schema_ref = build_schema_reference()
        tool_sum = build_tool_summary()
        system = PYDANTICAI_IMPORT_PROMPT.format(
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
        import_agent = Agent(model, instructions=system)

        # 5. Send structured summary to LLM
        prompt_text = pai_import.to_prompt_text()
        result = import_agent.run_sync(
            f"Convert this PydanticAI agent to an InitRunner role.yaml:\n\n{prompt_text}"
        )
        self._messages = list(result.all_messages())
        self._trim_messages()

        explanation, yaml_content = self._extract_yaml_from_response(result.output)
        self.yaml_text = yaml_content

        # 6. Auto-repair on validation failure
        if any(i.severity == "error" for i in self.issues):
            repaired = self._auto_repair(
                provider, model_name, base_url=base_url, api_key_env=api_key_env
            )
            if repaired is not None:
                self.yaml_text = repaired

        return self._make_turn_result(explanation or "Imported from PydanticAI source.")

    # -- History / undo ------------------------------------------------------

    def _commit_history(self) -> None:
        """Snapshot the current canonical YAML as an undo checkpoint."""
        if self._yaml_text:
            self._history.append(self._yaml_text)

    def checkpoint(self) -> None:
        """Public turn-boundary snapshot for deterministic (non-LLM) edits."""
        self._commit_history()

    def undo(self) -> bool:
        """Revert to the previous YAML snapshot. Returns False if none.

        Restores YAML only; the LLM transcript (``_messages``) is left intact
        because it is append-only and re-truncating it would desync PydanticAI
        request/response pairing. The current YAML is always re-sent in the
        refine prompt, so refinement context is preserved regardless.
        """
        if not self._history:
            return False
        self.yaml_text = self._history.pop()  # setter re-validates + canonicalizes
        return True

    @property
    def previous_yaml(self) -> str | None:
        """The most recent undo snapshot, or None."""
        return self._history[-1] if self._history else None

    def current_turn(self) -> TurnResult:
        """A TurnResult for the current YAML, no LLM call.

        Carries ``_last_test_prompt`` forward (rather than re-extracting from an
        empty explanation) so deterministic command turns -- ``:model``,
        ``:validate``, ``:undo`` -- do not erase a previously tailored prompt.
        """
        return TurnResult(
            explanation="",
            yaml_text=self._yaml_text,
            issues=self.issues,
            import_warnings=list(self.import_warnings),
            test_prompt=self._last_test_prompt,
        )

    def _trim_messages(self) -> None:
        """Cap the transcript, cutting on a ModelRequest boundary.

        PydanticAI re-sends ``instructions`` every run, so dropping old turns
        never loses the system prompt. Cutting on a request boundary avoids
        slicing into the middle of a request/response/tool exchange.
        """
        if len(self._messages) <= _MAX_HISTORY_MESSAGES:
            return
        from pydantic_ai.messages import ModelRequest

        cut = len(self._messages) - _MAX_HISTORY_MESSAGES
        for i in range(cut, len(self._messages)):
            if isinstance(self._messages[i], ModelRequest):
                self._messages = self._messages[i:]
                return
        # No safe boundary in the tail -- leave history intact this round.

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
        self._commit_history()  # snapshot pre-refine state for :undo
        agent = self._get_agent(provider, model_name, base_url=base_url, api_key_env=api_key_env)

        prompt = (
            f"Current role.yaml:\n```yaml\n{self._yaml_text}\n```\n\nUser request: {user_input}"
        )

        result = agent.run_sync(prompt, message_history=self._messages or None)
        self._messages = list(result.all_messages())
        self._trim_messages()

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
        self._trim_messages()

        _, yaml_content = self._extract_yaml_from_response(result.output)
        return yaml_content

    # -- Post-creation -------------------------------------------------------

    def save(self, path: Path, *, force: bool = False) -> PostCreateResult:
        """Validate and write the current YAML to disk."""
        from initrunner.services.roles import save_role_yaml_sync

        issue_strings: list[str] = []
        valid = True
        generated_paths: list[str] = []

        if path.exists() and not force:
            raise FileExistsError(f"{path} already exists. Use --force to overwrite.")

        # Resolve sidecar module name from output YAML stem
        if self._sidecar_source is not None:
            # Sanitize stem to a valid Python module identifier.
            sidecar_module = f"{sanitize_module_stem(path.stem)}_tools"
            # Replace placeholder module name in YAML
            self._yaml_text = self._yaml_text.replace("_langchain_tools", sidecar_module)
            self._yaml_text = self._yaml_text.replace("_pydanticai_tools", sidecar_module)
            # Invalidate caches after YAML mutation
            self._role_cache = None
            self._issues_cache = None

        try:
            role = save_role_yaml_sync(path, self._yaml_text)
        except (ValueError, Exception) as e:
            # Write anyway but note the issue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._yaml_text)
            issue_strings.append(str(e))
            valid = False
            role = self.role

        # Write sidecar module
        if self._sidecar_source is not None:
            sidecar_path = path.parent / f"{sidecar_module}.py"
            sidecar_path.write_text(self._sidecar_source)
            generated_paths.append(str(sidecar_path))

        next_steps = build_next_steps(role, path) if role else [f"initrunner validate {path}"]

        return PostCreateResult(
            yaml_path=path,
            valid=valid,
            issues=issue_strings,
            next_steps=next_steps,
            omitted_assets=self.omitted_assets,
            generated_assets=generated_paths,
        )
