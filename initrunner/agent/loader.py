"""Load role.yaml and construct PydanticAI agents."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from initrunner._compat import require_provider
from initrunner._yaml import load_raw_yaml
from initrunner.agent.schema.base import ModelConfig, PartialModelConfig
from initrunner.agent.schema.role import RoleDefinition

logger = logging.getLogger(__name__)

_PROVIDER_API_KEY_ENVS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "cohere": "CO_API_KEY",
    "xai": "XAI_API_KEY",
}


class RoleLoadError(Exception):
    """Raised when a role definition cannot be loaded or validated."""


def load_role(path: Path) -> RoleDefinition:
    """Read a YAML file and validate it as a RoleDefinition."""
    from initrunner.deprecations import validate_role_dict

    raw = load_raw_yaml(path, RoleLoadError)
    try:
        role, _hits = validate_role_dict(raw)
    except (ValueError, Exception) as e:
        raise RoleLoadError(f"Validation failed for {path}:\n{e}") from e
    validate_capability_tool_conflicts(role)
    return role


# Capability names that conflict with InitRunner tool types.
# These pairs provide duplicate functionality and confuse the model.
_CAP_TOOL_CONFLICTS: dict[str, str] = {
    "WebSearch": "search",
    "WebFetch": "web_reader",
    "ImageGeneration": "image_gen",
}


def validate_capability_tool_conflicts(role: RoleDefinition) -> None:
    """Raise RoleLoadError if a capability and tool provide duplicate functionality."""
    cap_names = {s.name for s in role.spec.capabilities if hasattr(s, "name")}
    tool_types = {t.type for t in role.spec.tools}
    for cap_name, tool_type in _CAP_TOOL_CONFLICTS.items():
        if cap_name in cap_names and tool_type in tool_types:
            raise RoleLoadError(
                f"'{cap_name}' capability and '{tool_type}' tool both provide the "
                f"same functionality. Remove one:\n"
                f"  - Remove the capability to use InitRunner's '{tool_type}' tool\n"
                f"  - Remove the tool to use PydanticAI's native {cap_name} capability"
            )


def _build_model(model_config: ModelConfig):
    """Build a PydanticAI model -- string for standard providers, OpenAI model for custom."""
    if not model_config.needs_custom_provider():
        env_var = model_config.api_key_env or _PROVIDER_API_KEY_ENVS.get(model_config.provider)
        if env_var and not os.environ.get(env_var):
            raise RoleLoadError(
                f"API key not found. Set the {env_var} environment variable:\n"
                f"  export {env_var}=your-key-here\n"
                f"Or add it to a .env file in your role directory or ~/.initrunner/.env"
            )
        provider = model_config.provider
        # Default OpenAI to the Responses API. It is a superset of Chat
        # Completions and required for reasoning_effort + tools, builtin
        # capabilities (WebSearch, ImageGeneration), and newer models.
        if provider == "openai":
            provider = "openai-responses"
        return f"{provider}:{model_config.name}"

    from pydantic_ai.providers.openai import OpenAIProvider

    base_url = model_config.base_url
    if model_config.provider == "ollama":
        from initrunner.services.providers import OLLAMA_DEFAULT_BASE_URL

        base_url = base_url or OLLAMA_DEFAULT_BASE_URL
        api_key = "ollama"
    elif model_config.api_key_env:
        api_key = os.environ.get(model_config.api_key_env)
        if not api_key:
            raise RoleLoadError(
                f"Environment variable '{model_config.api_key_env}' is not set "
                f"(required by model config)"
            )
    else:
        api_key = None

    if base_url and ("localhost" in base_url or "127.0.0.1" in base_url):
        if Path("/.dockerenv").exists():
            logger.warning(
                "Detected Docker environment with localhost base_url '%s'. "
                "Consider using 'http://host.docker.internal:11434/v1' instead.",
                base_url,
            )

    provider = OpenAIProvider(base_url=base_url, api_key=api_key)

    from pydantic_ai.models.openai import OpenAIChatModel

    return OpenAIChatModel(model_config.name, provider=provider)


def _inject_local_fallbacks(caps: list) -> None:
    """Wire InitRunner's functions as local fallbacks for capabilities that lack them.

    PydanticAI's ``WebFetch`` has no default local, and ``WebFetchTool`` is not
    supported by any model's builtin list.  Injecting InitRunner's SSRF-protected
    URL fetcher makes ``- WebFetch`` work seamlessly in YAML.
    """
    from pydantic_ai.capabilities.web_fetch import WebFetch  # type: ignore[import-not-found]

    for cap in caps:
        if isinstance(cap, WebFetch) and not cap.local:
            from pydantic_ai.tools import Tool  # type: ignore[import-not-found]

            from initrunner._html import fetch_url_as_markdown_async

            cap.local = Tool(fetch_url_as_markdown_async, name="web_fetch")


def _validate_provider(role: RoleDefinition) -> None:
    """Check the provider SDK is installed, raising RoleLoadError if not."""
    try:
        require_provider(role.spec.model.provider)
    except RuntimeError as e:
        raise RoleLoadError(str(e)) from None


def _validate_reasoning(role: RoleDefinition) -> None:
    """Validate reasoning config against tool declarations."""
    config = role.spec.reasoning
    if config is None:
        return

    from initrunner.agent.schema.tools import TodoToolConfig

    has_todo = any(isinstance(t, TodoToolConfig) for t in role.spec.tools)

    if config.pattern in ("todo_driven", "plan_execute") and not has_todo:
        raise RoleLoadError(
            f"reasoning.pattern '{config.pattern}' requires a 'todo' tool in spec.tools"
        )
    if config.pattern == "reflexion" and config.reflection_rounds == 0:
        raise RoleLoadError("reasoning.pattern 'reflexion' requires reflection_rounds > 0")


def _resolve_skills_and_merge(
    role: RoleDefinition,
    role_dir: Path | None,
    extra_skill_dirs: list[Path] | None,
) -> tuple[str, list, set[Path]]:
    """Resolve skills, log warnings, merge tools, and compose the system prompt.

    Returns ``(system_prompt, all_tools, explicit_skill_paths)``.
    """
    system_prompt = role.spec.role
    all_tools = list(role.spec.tools)
    explicit_paths: set[Path] = set()

    if not role.spec.skills:
        return system_prompt, all_tools, explicit_paths

    from initrunner.agent.skills import (
        build_skill_system_prompt,
        merge_skill_tools,
        resolve_skills,
    )

    resolved_skills = resolve_skills(role.spec.skills, role_dir, extra_skill_dirs)
    explicit_paths = {rs.source_path for rs in resolved_skills}

    for rs in resolved_skills:
        for req in rs.requirement_statuses:
            if not req.met:
                logger.warning(
                    "Skill '%s': unmet %s -- %s",
                    rs.definition.frontmatter.name,
                    req.kind,
                    req.detail,
                )

    all_tools = merge_skill_tools(resolved_skills, role.spec.tools)
    skill_prompt = build_skill_system_prompt(resolved_skills)
    if skill_prompt:
        system_prompt = f"{role.spec.role}\n\n{skill_prompt}"

    return system_prompt, all_tools, explicit_paths


def _create_agent(
    role: RoleDefinition,
    system_prompt: str,
    toolsets: list,
    output_type: type,
    instrument: Any = None,
    prepare_tools: Any = None,
    capabilities: list | None = None,
) -> Agent:
    """Build the model and construct the PydanticAI Agent."""
    model_settings_kwargs: dict[str, Any] = {"max_tokens": role.spec.model.max_tokens}
    if not role.spec.model.is_reasoning_model():
        model_settings_kwargs["temperature"] = role.spec.model.temperature
    kwargs: dict[str, Any] = {
        "output_type": output_type,
        "system_prompt": system_prompt,
        "model_settings": ModelSettings(**model_settings_kwargs),
        "toolsets": toolsets if toolsets else None,
    }
    if instrument is not None:
        kwargs["instrument"] = instrument
    if prepare_tools is not None:
        kwargs["prepare_tools"] = prepare_tools
    if capabilities:
        kwargs["capabilities"] = capabilities

    from initrunner.agent.history_summarizer import build_history_processor

    kwargs["history_processors"] = [build_history_processor(role.spec.model)]  # type: ignore[arg-type]

    return Agent(_build_model(role.spec.model), **kwargs)  # type: ignore[arg-type]


def build_agent(
    role: RoleDefinition,
    role_dir: Path | None = None,
    output_type: type | None = None,
    extra_skill_dirs: list[Path] | None = None,
    *,
    prefer_async: bool = False,
) -> Agent:
    """Construct a PydanticAI Agent from a validated RoleDefinition."""
    # Ensure spec.model is a concrete ModelConfig (not PartialModelConfig)
    model = role.spec.model
    if model is None or (hasattr(model, "is_resolved") and not model.is_resolved()):
        raise RoleLoadError(
            "Model must be resolved before building an agent. Call resolve_role_model() first."
        )
    if not isinstance(role.spec.model, ModelConfig):
        role = _set_model(role, ModelConfig(**role.spec.model.model_dump()))
    _validate_provider(role)
    _validate_reasoning(role)
    system_prompt, all_tools, explicit_paths = _resolve_skills_and_merge(
        role, role_dir, extra_skill_dirs
    )

    # Resolve output type: explicit param wins, then role config, then str default
    if output_type is None:
        from initrunner.agent.output import resolve_output_type

        output_type = resolve_output_type(role.spec.output, role_dir)

    from initrunner.agent.tools import build_toolsets

    toolsets = build_toolsets(all_tools, role, role_dir=role_dir, prefer_async=prefer_async)

    # PydanticAI capabilities — native NamedSpec only
    capabilities = None
    if role.spec.capabilities:
        from pydantic_ai.agent.spec import (
            load_capability_from_nested_spec,  # type: ignore[import-not-found]
        )

        caps = [
            load_capability_from_nested_spec(s.model_dump(mode="json"))
            for s in role.spec.capabilities
        ]
        capabilities = caps

        # Auto-inject local fallbacks for capabilities that lack them.
        # WebFetch has no default local in PydanticAI and WebFetchTool is not
        # supported by any model's builtin list, so it always needs a local.
        _inject_local_fallbacks(caps)

        # Defensive: catch conflicts that slipped past load_role / dashboard validation.
        validate_capability_tool_conflicts(role)

        cap_names = {spec.name for spec in role.spec.capabilities if hasattr(spec, "name")}
        if "Thinking" in cap_names and role.spec.reasoning is not None:
            logger.warning(
                "Both a Thinking capability and spec.reasoning are declared. "
                "Thinking controls model-level extended thinking; "
                "spec.reasoning controls InitRunner orchestration patterns "
                "(react, reflexion, etc.). These are orthogonal but may cause confusion.",
            )
        if "MCP" in cap_names and any(t.type == "mcp" for t in role.spec.tools):
            logger.warning(
                "Both an MCP capability and an 'mcp' tool are declared. "
                "The MCP capability is PydanticAI's native MCP integration; "
                "the 'mcp' tool is InitRunner's tool-registry MCP wrapper. "
                "Both will be active -- ensure this is intentional.",
            )

    # Auto-construct guardrail capabilities from security.content config.
    # The InputGuardCapability fires in ``before_run`` (both streaming and
    # non-streaming) and raises ContentBlockedError to abort blocked runs.
    content = role.spec.security.content
    _has_input_guard = (
        content.blocked_input_patterns
        or content.profanity_filter
        or content.llm_classifier_enabled
        or content.max_prompt_length != 50_000
    )
    if _has_input_guard:
        from initrunner.agent.capabilities import InputGuardCapability

        auto_guard = InputGuardCapability(policy=content)
        capabilities = [auto_guard] + (capabilities or [])

    # Auto-discovered skills — progressive disclosure via activate_skill tool
    auto_skill_activated: set[str] = set()
    if role.spec.auto_skills.enabled:
        from initrunner.agent.auto_skills import (
            build_activate_skill_toolset,
            build_catalog_prompt,
            discover_skills,
        )

        discovered = discover_skills(
            role_dir=role_dir,
            extra_dirs=extra_skill_dirs,
            max_skills=role.spec.auto_skills.max_skills,
            exclude_paths=explicit_paths,
        )
        if discovered:
            from initrunner.agent.tool_events import wrap_observable

            system_prompt = f"{system_prompt}\n\n{build_catalog_prompt(discovered)}"
            ts = build_activate_skill_toolset(discovered, auto_skill_activated)
            toolsets.append(wrap_observable(ts))

    # Tool search meta-tool — hides tools behind BM25 search to reduce context
    prepare_tools = None
    if role.spec.tool_search.enabled:
        from initrunner.agent.tools.tool_search import (
            ToolSearchManager,
            build_tool_search_toolset,
        )

        ts_config = role.spec.tool_search
        manager = ToolSearchManager(
            always_available=ts_config.always_available,
            max_results=ts_config.max_results,
            threshold=ts_config.threshold,
        )
        from initrunner.agent.tool_events import wrap_observable

        toolsets.append(wrap_observable(build_tool_search_toolset(manager)))
        prepare_tools = manager.prepare_tools_callback
        system_prompt += (
            "\n\nIMPORTANT: You have many tools available beyond what you currently see. "
            "Most are hidden to save context. When no visible tool obviously fits the "
            "user's request, ALWAYS call `search_tools` before saying you cannot do "
            "something (e.g. search_tools('send slack message'), search_tools('read csv')). "
            "Matching tools will then become available for you to call."
        )

    instrument = None
    if role.spec.observability is not None:
        from initrunner.observability import get_instrumentation_settings

        instrument = get_instrumentation_settings(role.spec.observability)

    agent = _create_agent(
        role,
        system_prompt,
        toolsets,
        output_type,
        instrument=instrument,
        prepare_tools=prepare_tools,
        capabilities=capabilities,
    )

    # Register dynamic system prompt for procedural memory injection.
    # The closure reads ``_memory_store`` from the agent so the already-open
    # store is reused instead of opening a second handle (which would hit
    # LanceDB table locks).
    if role.spec.memory is not None and role.spec.memory.procedural.enabled:
        from initrunner.agent.memory_ops import build_memory_system_prompt

        @agent.system_prompt
        def _procedural_context() -> str:
            store = getattr(agent, "_memory_store", None)
            return build_memory_system_prompt(role, store=store)

    # Register dynamic system prompt for resume context injection.
    # The ``_resume_context`` attribute is set by interactive.py when
    # resuming a session with memory available.
    if role.spec.memory is not None:

        @agent.system_prompt
        def _resume_context() -> str:
            return getattr(agent, "_resume_context", "")

    return agent


def _load_dotenv(role_dir: Path | None) -> None:
    """Load .env files — local first, then global as fallback.

    Uses ``override=False`` so existing env vars always win.
    Local is loaded before global so project-local values take precedence.
    """
    from dotenv import load_dotenv

    if role_dir is not None:
        local_env = role_dir / ".env"
        if local_env.is_file():
            load_dotenv(local_env, override=False)
    from initrunner.config import get_global_env_path

    global_env = get_global_env_path()
    if global_env.is_file():
        load_dotenv(global_env, override=False)


def _set_model(role: RoleDefinition, model: ModelConfig) -> RoleDefinition:
    """Return a copy of *role* with its model set to a concrete ModelConfig."""
    new_spec = role.spec.model_copy(update={"model": model})
    return role.model_copy(update={"spec": new_spec})


def _apply_model_override(role: RoleDefinition, provider: str, name: str) -> RoleDefinition:
    """Return a copy of *role* with its model config replaced.

    Preserves tuning fields (temperature, max_tokens, context_window) from the
    existing model config.  Clears base_url/api_key_env when provider changes.
    """
    partial = role.spec.model
    base: dict[str, Any] = {}
    if partial is not None:
        base = {
            "temperature": partial.temperature,
            "max_tokens": partial.max_tokens,
            "context_window": partial.context_window,
        }
        if provider == partial.provider:
            base["base_url"] = partial.base_url
            base["api_key_env"] = partial.api_key_env
    new_model = ModelConfig(provider=provider, name=name, **base)
    return _set_model(role, new_model)


def detect_default_model() -> tuple[str, str, str | None, str | None, str]:
    """Detect the current default model and its source.

    Returns ``(provider, name, base_url, api_key_env, source)`` where *source*
    is one of ``"initrunner_model_env"``, ``"run_yaml"``, ``"auto_detected"``,
    or ``"none"``.  Never raises.
    """
    # 1. INITRUNNER_MODEL env var
    env_model = os.environ.get("INITRUNNER_MODEL")
    if env_model:
        from initrunner.model_aliases import parse_model_string, resolve_model_alias

        try:
            resolved = resolve_model_alias(env_model)
            prov, name = parse_model_string(resolved)
            return prov, name, None, None, "initrunner_model_env"
        except ValueError:
            pass

    # 2. run.yaml (from `initrunner setup`)
    from initrunner.cli.run_config import load_run_config

    run_cfg = load_run_config()
    if run_cfg.provider and run_cfg.model:
        return (
            run_cfg.provider,
            run_cfg.model,
            run_cfg.base_url,
            run_cfg.api_key_env,
            "run_yaml",
        )

    # 3. Auto-detect from API key env vars
    from initrunner.services.providers import detect_provider_and_model

    detected = detect_provider_and_model()
    if detected is not None:
        return detected.provider, detected.model, None, None, "auto_detected"

    return "", "", None, None, "none"


def _auto_detect_model() -> tuple[str, str, str | None, str | None]:
    """Detect provider/model from env, run.yaml, or API keys.

    Returns ``(provider, name, base_url, api_key_env)``.
    Raises :class:`RoleLoadError` if nothing can be detected.
    """
    prov, name, base_url, api_key_env, source = detect_default_model()
    if source == "none":
        raise RoleLoadError(
            "No model specified and none could be auto-detected.\n\n"
            "To fix this, do one of:\n"
            "  1. Add a model section to your role YAML:\n"
            "       model:\n"
            "         provider: openai\n"
            "         name: gpt-5-mini\n"
            "  2. Run 'initrunner setup' to configure a default provider\n"
            "  3. Set INITRUNNER_MODEL=provider:model "
            "(e.g. INITRUNNER_MODEL=openai:gpt-5-mini)\n"
            "  4. Set an API key environment variable "
            "(e.g. OPENAI_API_KEY, ANTHROPIC_API_KEY)"
        )
    return prov, name, base_url, api_key_env


def resolve_role_model(
    role: RoleDefinition,
    role_path: Path | None = None,
    *,
    model_override: str | None = None,
) -> RoleDefinition:
    """Return a copy of *role* with ``spec.model`` as a concrete :class:`ModelConfig`.

    Resolution order:

    1. *model_override* parameter (CLI ``--model``, dashboard model picker)
    2. Registry overrides for installed roles
    3. ``INITRUNNER_MODEL`` env var
    4. ``~/.initrunner/run.yaml`` (from ``initrunner setup``)
    5. API key env var detection (``OPENAI_API_KEY``, etc.)

    When the YAML provides a partial model config (e.g. ``temperature: 0.3``
    without provider/name), the auto-detected provider/name is merged in and
    the tuning fields are preserved.
    """
    from initrunner.model_aliases import parse_model_string

    partial = role.spec.model  # PartialModelConfig | None

    # 1. Explicit override wins
    if model_override:
        new_provider, new_name = parse_model_string(model_override)
        return _apply_model_override(role, new_provider, new_name)

    # 2. Already fully resolved in YAML
    if partial is not None and partial.is_resolved():
        resolved_role = _set_model(role, ModelConfig(**partial.model_dump()))
        if role_path:
            resolved_role = _apply_registry_overrides(resolved_role, role_path)
        return resolved_role

    # 3. Auto-detect and merge with partial tuning fields
    prov, name, base_url, api_key_env = _auto_detect_model()
    base = partial or PartialModelConfig()
    resolved = ModelConfig(
        provider=prov,
        name=name,
        base_url=base_url or base.base_url,
        api_key_env=api_key_env or base.api_key_env,
        temperature=base.temperature,
        max_tokens=base.max_tokens,
        context_window=base.context_window,
    )
    return _set_model(role, resolved)


def load_and_build(
    path: Path,
    extra_skill_dirs: list[Path] | None = None,
    model_override: str | None = None,
) -> tuple[RoleDefinition, Agent]:
    """Load a role YAML and build the corresponding agent.

    When *model_override* is a ``provider:model`` string the role's model
    config is replaced before the agent is built.  Otherwise, if the role
    was installed via the registry and the user set a provider override,
    that override is applied automatically.  If no model is specified in
    the YAML, auto-detects from env vars / ``run.yaml``.
    """
    _load_dotenv(path.parent)
    role = load_role(path)
    role = resolve_role_model(role, path, model_override=model_override)
    agent = build_agent(role, role_dir=path.parent, extra_skill_dirs=extra_skill_dirs)
    return role, agent


def _apply_registry_overrides(role: RoleDefinition, path: Path) -> RoleDefinition:
    """Apply provider/model overrides from the registry manifest, if present."""
    try:
        from initrunner.registry import get_overrides_for_path

        overrides = get_overrides_for_path(path)
    except Exception:
        return role

    if not overrides:
        return role

    provider = overrides.get("provider", "")
    model = overrides.get("model", "")
    if not provider or not model:
        return role

    orig = role.spec.model
    orig_str = f"{orig.provider}/{orig.name}" if isinstance(orig, ModelConfig) else "auto-detect"
    logger.info(
        "Applying registry override: %s/%s (original: %s)",
        provider,
        model,
        orig_str,
    )
    return _apply_model_override(role, provider, model)
