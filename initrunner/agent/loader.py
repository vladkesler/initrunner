"""Load role.yaml and construct PydanticAI agents."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.settings import ModelSettings

from initrunner._compat import require_provider
from initrunner._yaml import load_raw_yaml
from initrunner.agent.schema.base import ModelConfig, PartialModelConfig
from initrunner.agent.schema.execution import ExecutionConfig
from initrunner.agent.schema.role import RoleDefinition
from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT as _PROVIDER_API_KEY_ENVS

logger = logging.getLogger(__name__)


class RoleLoadError(Exception):
    """Raised when a role definition cannot be loaded or validated."""


class MissingApiKeyError(RoleLoadError):
    """Raised when a role's provider has no API key in env or dotenv.

    Carries the env var name and provider so the CLI can prompt for the
    key inline instead of forcing the user to round-trip through
    ``initrunner setup``.
    """

    def __init__(self, env_var: str, provider: str, message: str):
        super().__init__(message)
        self.env_var = env_var
        self.provider = provider


def load_role(path: Path) -> RoleDefinition:
    """Read a YAML file and validate it as a RoleDefinition."""
    from initrunner.deprecations import validate_role_dict

    raw = load_raw_yaml(path, RoleLoadError)
    try:
        role, _hits = validate_role_dict(raw)
    except (ValueError, Exception) as e:
        raise RoleLoadError(f"Validation failed for {path}:\n{e}") from e
    validate_capability_tool_conflicts(role)
    _validate_templating(role)
    return role


def _validate_templating(role: RoleDefinition) -> None:
    """Enforce that ``{{var}}`` in the role prompt matches ``deps_schema``.

    Catches the mismatch at load time so users don't get a half-rendered
    system prompt at run time.  No-op when the role has neither templates nor
    a deps_schema.
    """
    from initrunner.agent.templating import TemplatingError, has_templates

    prompt = role.spec.role or ""
    deps_schema = role.spec.deps_schema

    if deps_schema is None and not has_templates(prompt):
        return
    if deps_schema is None:
        raise RoleLoadError(
            "spec.role uses {{variable}} placeholders but spec.deps_schema is not set. "
            "Declare a JSON Schema for the variables or remove the placeholders."
        )
    from initrunner.agent.templating import validate_schema_and_template

    try:
        validate_schema_and_template(prompt, deps_schema)
    except TemplatingError as exc:
        raise RoleLoadError(str(exc)) from exc


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


# Providers whose SDKs route through httpx and accept an injected client.
# bedrock (boto3) and xai (gRPC) keep their SDKs' native retry handling and
# are built as plain ``provider:name`` strings.
_HTTPX_PROVIDERS = frozenset({"openai", "anthropic", "google", "groq", "mistral", "cohere"})


def _build_retrying_provider_model(model_config: ModelConfig, http_client, api_key: str | None):
    """Construct an explicit Model + Provider with a retrying httpx client.

    ``api_key`` is the key InitRunner already resolved (vault/.env/shell). It
    is passed explicitly so a custom ``api_key_env`` works for standard
    providers too -- the SDKs only read their canonical env var (e.g.
    ``OPENAI_API_KEY``) otherwise. When ``None`` the provider falls back to
    reading its own env var.
    """
    name = model_config.name
    provider = model_config.provider
    if provider == "openai":
        # Default OpenAI to the Responses API. It is a superset of Chat
        # Completions and required for reasoning_effort + tools, builtin
        # capabilities (WebSearch, ImageGeneration), and newer models.
        from pydantic_ai.models.openai import OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIResponsesModel(
            name, provider=OpenAIProvider(api_key=api_key, http_client=http_client)
        )
    if provider == "anthropic":
        from pydantic_ai.models.anthropic import AnthropicModel  # type: ignore[import-not-found]
        from pydantic_ai.providers.anthropic import (  # type: ignore[import-not-found]
            AnthropicProvider,
        )

        return AnthropicModel(
            name, provider=AnthropicProvider(api_key=api_key, http_client=http_client)
        )
    if provider == "google":
        from pydantic_ai.models.google import GoogleModel  # type: ignore[import-not-found]
        from pydantic_ai.providers.google import GoogleProvider  # type: ignore[import-not-found]

        return GoogleModel(name, provider=GoogleProvider(api_key=api_key, http_client=http_client))
    if provider == "groq":
        from pydantic_ai.models.groq import GroqModel  # type: ignore[import-not-found]
        from pydantic_ai.providers.groq import GroqProvider  # type: ignore[import-not-found]

        return GroqModel(name, provider=GroqProvider(api_key=api_key, http_client=http_client))
    if provider == "mistral":
        from pydantic_ai.models.mistral import MistralModel  # type: ignore[import-not-found]
        from pydantic_ai.providers.mistral import MistralProvider  # type: ignore[import-not-found]

        return MistralModel(
            name, provider=MistralProvider(api_key=api_key, http_client=http_client)
        )
    if provider == "cohere":
        from pydantic_ai.models.cohere import CohereModel  # type: ignore[import-not-found]
        from pydantic_ai.providers.cohere import CohereProvider  # type: ignore[import-not-found]

        return CohereModel(name, provider=CohereProvider(api_key=api_key, http_client=http_client))
    raise ValueError(f"Provider '{provider}' is not in _HTTPX_PROVIDERS")


def _build_single_model(
    model_config: ModelConfig,
    *,
    http_retries: int = 3,
    http_retry_max_wait: float = 60.0,
):
    """Build one PydanticAI model with transport-level HTTP retries.

    This is the single construction point for both the primary model and any
    FallbackModel entries.  API keys are resolved and injected into
    ``os.environ`` here, so every Model-like returned by this function is
    immediately usable. Providers that route through httpx get an
    ``AsyncTenacityTransport`` client (backoff + Retry-After on 429/5xx);
    bedrock and xai keep their SDKs' native retry handling.
    """
    from initrunner.agent.executor_retry import build_retrying_async_client
    from initrunner.credentials import get_resolver

    resolver = get_resolver()
    if not model_config.needs_custom_provider():
        env_var = model_config.api_key_env or _PROVIDER_API_KEY_ENVS.get(model_config.provider)
        resolved_key: str | None = None
        if env_var:
            resolved = resolver.get(env_var)
            if not resolved:
                raise MissingApiKeyError(
                    env_var=env_var,
                    provider=model_config.provider,
                    message=(
                        f"API key not found. Set the {env_var} environment variable:\n"
                        f"  export {env_var}=your-key-here\n"
                        f"Or store it in the vault: initrunner vault set {env_var}\n"
                        f"Or add it to a .env file in your role directory or ~/.initrunner/.env"
                    ),
                )
            resolved_key = resolved
            # Standard-provider SDKs (OpenAI, Anthropic, Google, ...) read the
            # API key from os.environ at client construction time. If the value
            # came from the vault rather than the shell, inject it so the SDK
            # sees it. Only set when absent -- a real shell export always wins.
            if not os.environ.get(env_var):
                os.environ[env_var] = resolved
        if model_config.provider in _HTTPX_PROVIDERS:
            try:
                return _build_retrying_provider_model(
                    model_config,
                    build_retrying_async_client(
                        attempts=http_retries, max_wait=http_retry_max_wait
                    ),
                    resolved_key,
                )
            except ImportError:
                # Provider SDK not installed. Fall back to the plain
                # ``provider:name`` string so PydanticAI raises its own
                # "install the X package" error at run time, exactly as
                # before this transport-level retry refactor. ``require_provider``
                # already gates this for the primary build path; this only
                # matters for un-gated callers (e.g. role-generation wizards).
                logger.debug(
                    "Provider '%s' SDK unavailable; using string model without "
                    "transport-level retries.",
                    model_config.provider,
                )
        return f"{model_config.provider}:{model_config.name}"

    from pydantic_ai.providers.openai import OpenAIProvider

    base_url = model_config.base_url
    if model_config.provider == "ollama":
        from initrunner.services.providers import OLLAMA_DEFAULT_BASE_URL

        base_url = base_url or OLLAMA_DEFAULT_BASE_URL
        api_key = "ollama"
    elif model_config.api_key_env:
        api_key = resolver.get(model_config.api_key_env)
        if not api_key:
            raise MissingApiKeyError(
                env_var=model_config.api_key_env,
                provider=model_config.provider,
                message=(
                    f"API key '{model_config.api_key_env}' not set (required by model config). "
                    f"Export the env var or run: initrunner vault set {model_config.api_key_env}"
                ),
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

    # Custom OpenAI-compatible endpoints (Ollama, vLLM, OpenRouter, ...) also
    # route through httpx, so they get the same retrying transport.
    provider = OpenAIProvider(
        base_url=base_url,
        api_key=api_key,
        http_client=build_retrying_async_client(
            attempts=http_retries, max_wait=http_retry_max_wait
        ),
    )

    from pydantic_ai.models.openai import OpenAIChatModel

    return OpenAIChatModel(model_config.name, provider=provider)


def _apply_prompt_cache(settings: dict[str, Any], model: ModelConfig) -> None:
    """Map ``model.prompt_cache`` onto provider-native cache settings.

    Anthropic and Bedrock expose parallel ``{provider}_cache_instructions`` /
    ``{provider}_cache_tool_definitions`` settings whose value is the TTL. These
    are provider-specific ``ModelSettings`` keys (validated only for anthropic /
    bedrock by the schema), so we inject them by name into the settings dict.
    """
    cache = model.prompt_cache
    if cache is None:
        return
    prefix = model.provider.lower()  # "anthropic" or "bedrock" (schema-enforced)
    if cache.instructions:
        settings[f"{prefix}_cache_instructions"] = cache.ttl
    if cache.tools:
        settings[f"{prefix}_cache_tool_definitions"] = cache.ttl


def _build_model(model_config: ModelConfig, execution: ExecutionConfig | None = None):
    """Build the agent model, wrapping with FallbackModel when fallbacks are declared.

    When ``model_config.fallback`` is empty, returns the primary model
    directly.  When non-empty, returns a ``FallbackModel`` that walks the
    primary first, then each fallback in declaration order on any
    ``ModelAPIError``.  Each fallback entry is a ``provider:model`` string
    (validated at schema time); it is built through
    ``_build_single_model`` so vault-sourced API keys are injected into
    ``os.environ`` before ``FallbackModel.__init__`` constructs the
    per-provider clients.

    ``execution`` carries the HTTP-retry knobs (``http_retries``,
    ``http_retry_max_wait``); when omitted, ``_build_single_model`` defaults
    apply.
    """
    retry_kwargs: dict[str, Any] = {}
    if execution is not None:
        retry_kwargs = {
            "http_retries": execution.http_retries,
            "http_retry_max_wait": execution.http_retry_max_wait,
        }

    primary = _build_single_model(model_config, **retry_kwargs)
    if not model_config.fallback:
        return _apply_concurrency_limit(primary, model_config)

    from initrunner.agent.schema.base import _split_provider_and_name

    fallback_models = []
    for entry in model_config.fallback:
        prov, name = _split_provider_and_name(entry)
        fallback_models.append(
            _build_single_model(ModelConfig(provider=prov, name=name), **retry_kwargs)
        )

    from pydantic_ai.models.fallback import FallbackModel

    if model_config.fallback_on:
        built = FallbackModel(
            primary, *fallback_models, fallback_on=_resolve_fallback_on(model_config.fallback_on)
        )
    else:
        built = FallbackModel(primary, *fallback_models)
    return _apply_concurrency_limit(built, model_config)


def _resolve_fallback_on(names: list[str]) -> tuple[type[Exception], ...]:
    """Map ``fallback_on`` exception names (schema-validated) to their classes."""
    import pydantic_ai.exceptions as exc

    return tuple(getattr(exc, name) for name in names)


# Process-global registry of named shared concurrency limiters. Agents whose
# model config uses the same ``concurrency.share`` name coordinate against one
# limiter instance (compose services, team personas, flow nodes in one process).
_LIMITER_REGISTRY: dict[str, Any] = {}
_LIMITER_LOCK = threading.Lock()


def _get_concurrency_limiter(cfg: Any) -> Any:
    """Return a ConcurrencyLimiter, reusing a named one from the registry."""
    from pydantic_ai import ConcurrencyLimiter

    if cfg.share is None:
        return ConcurrencyLimiter(cfg.max_running, max_queued=cfg.max_queued)
    with _LIMITER_LOCK:
        existing = _LIMITER_REGISTRY.get(cfg.share)
        if existing is None:
            existing = ConcurrencyLimiter(
                cfg.max_running, max_queued=cfg.max_queued, name=cfg.share
            )
            _LIMITER_REGISTRY[cfg.share] = existing
        return existing


def _apply_concurrency_limit(model: Any, model_config: ModelConfig) -> Any:
    """Wrap *model* in a ConcurrencyLimitedModel when ``model.concurrency`` is set."""
    cfg = model_config.concurrency
    if cfg is None:
        return model
    from pydantic_ai.models.concurrency import ConcurrencyLimitedModel

    return ConcurrencyLimitedModel(model, _get_concurrency_limiter(cfg))


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
    """Check the provider SDK is installed for the primary model and every fallback."""
    from initrunner.agent.schema.base import _split_provider_and_name

    model = role.spec.model
    providers = [model.provider]  # type: ignore[union-attr]
    providers.extend(_split_provider_and_name(entry)[0] for entry in model.fallback)  # type: ignore[union-attr]
    for prov in providers:
        try:
            require_provider(prov)
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
        raise RoleLoadError(
            "reasoning.pattern 'reflexion' requires reflection_rounds > 0 "
            "or non-empty reflection_dimensions"
        )


def _resolve_skills_and_merge(
    role: RoleDefinition,
    role_dir: Path | None,
    extra_skill_dirs: list[Path] | None,
) -> tuple[str, list, set[Path]]:
    """Resolve skills, log warnings, merge tools, and compose the agent instructions.

    Returns ``(instructions, all_tools, explicit_skill_paths)``.
    """
    instructions = role.spec.role
    all_tools = list(role.spec.tools)
    explicit_paths: set[Path] = set()

    if not role.spec.skills:
        return instructions, all_tools, explicit_paths

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
        instructions = f"{role.spec.role}\n\n{skill_prompt}"

    return instructions, all_tools, explicit_paths


def _create_agent(
    role: RoleDefinition,
    instructions: str,
    toolsets: list,
    output_type: Any,
    instrument: Any = None,
    prepare_tools: Any = None,
    capabilities: list | None = None,
) -> Agent:
    """Build the model and construct the PydanticAI Agent."""
    model = role.spec.model
    model_settings_kwargs: dict[str, Any] = {"max_tokens": model.max_tokens}  # type: ignore[union-attr]
    if not model.is_reasoning_model():  # type: ignore[union-attr]
        model_settings_kwargs["temperature"] = model.temperature  # type: ignore[union-attr]
        # Sampling knobs are dropped alongside temperature: OpenAI reasoning
        # models reject them just like temperature.
        for sampling_field in (
            "top_p",
            "top_k",
            "presence_penalty",
            "frequency_penalty",
            "logit_bias",
        ):
            value = getattr(model, sampling_field)
            if value is not None:
                model_settings_kwargs[sampling_field] = value
    for passthrough_field in (
        "seed",
        "stop_sequences",
        "parallel_tool_calls",
        "extra_headers",
        "extra_body",
        "tool_choice",
        "thinking",
    ):
        value = getattr(model, passthrough_field)
        if value is not None:
            model_settings_kwargs[passthrough_field] = value
    if model.prompt_cache is not None:  # type: ignore[union-attr]
        _apply_prompt_cache(model_settings_kwargs, model)  # type: ignore[arg-type]
    kwargs: dict[str, Any] = {
        "output_type": output_type,
        "instructions": instructions,
        "model_settings": ModelSettings(**model_settings_kwargs),
        "toolsets": toolsets if toolsets else None,
    }
    if instrument is not None:
        kwargs["instrument"] = instrument
    if capabilities:
        kwargs["capabilities"] = capabilities
    if prepare_tools is not None:
        from pydantic_ai.capabilities.prepare_tools import PrepareTools

        kwargs.setdefault("capabilities", []).append(PrepareTools(prepare_tools))

    execution = role.spec.execution
    if execution.output_retries is not None:
        kwargs["retries"] = {
            "tools": execution.retries,
            "output": execution.output_retries,
        }
    else:
        kwargs["retries"] = execution.retries
    kwargs["end_strategy"] = execution.end_strategy
    if execution.tool_timeout_seconds is not None:
        kwargs["tool_timeout"] = execution.tool_timeout_seconds
    if execution.max_concurrency is not None:
        from pydantic_ai import ConcurrencyLimit

        kwargs["max_concurrency"] = ConcurrencyLimit(
            max_running=execution.max_concurrency.max_running,
            max_queued=execution.max_concurrency.max_queued,
        )

    from pydantic_ai.capabilities import ProcessHistory

    from initrunner.agent.history_summarizer import build_history_processor

    kwargs.setdefault("capabilities", []).append(
        ProcessHistory(build_history_processor(role.spec.model))  # type: ignore[arg-type]
    )

    return Agent(_build_model(role.spec.model, role.spec.execution), **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# build_agent helpers
# ---------------------------------------------------------------------------


def _build_capabilities(role: RoleDefinition) -> list | None:
    """Load PydanticAI capabilities, inject fallbacks, add input guard if configured."""
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

        _inject_local_fallbacks(caps)
        validate_capability_tool_conflicts(role)

        cap_names = {spec.name for spec in role.spec.capabilities if hasattr(spec, "name")}
        model = role.spec.model
        if "Thinking" in cap_names and getattr(model, "thinking", None) is not None:
            logger.warning(
                "Both a Thinking capability and model.thinking are declared. "
                "model.thinking sets ModelSettings['thinking'] directly; "
                "the Thinking capability does the same at the capability layer. "
                "Prefer model.thinking and remove the capability to avoid confusion.",
            )
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

    return capabilities


@dataclass(frozen=True, slots=True)
class _AutoToolsResult:
    """Result of auto-skill and tool-search setup."""

    extra_toolsets: list
    prompt_addendum: str
    prepare_tools: Callable | None


def _build_auto_tools(
    role: RoleDefinition,
    role_dir: Path | None,
    explicit_paths: set[Path],
    extra_skill_dirs: list[Path] | None,
) -> _AutoToolsResult:
    """Build auto-skill and tool-search toolsets (already wrapped with wrap_observable)."""
    extra_toolsets: list = []
    prompt_addendum = ""
    prepare_tools = None

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

            prompt_addendum += f"\n\n{build_catalog_prompt(discovered)}"
            ts = build_activate_skill_toolset(discovered, auto_skill_activated)
            extra_toolsets.append(wrap_observable(ts))

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

        extra_toolsets.append(wrap_observable(build_tool_search_toolset(manager)))
        prepare_tools = manager.prepare_tools_callback
        prompt_addendum += (
            "\n\nIMPORTANT: You have many tools available beyond what you currently see. "
            "Most are hidden to save context. When no visible tool obviously fits the "
            "user's request, ALWAYS call `search_tools` before saying you cannot do "
            "something (e.g. search_tools('send slack message'), search_tools('read csv')). "
            "Matching tools will then become available for you to call."
        )

    return _AutoToolsResult(
        extra_toolsets=extra_toolsets,
        prompt_addendum=prompt_addendum,
        prepare_tools=prepare_tools,
    )


def build_agent(
    role: RoleDefinition,
    role_dir: Path | None = None,
    output_type: Any = None,
    extra_skill_dirs: list[Path] | None = None,
) -> Agent:
    """Construct a PydanticAI Agent from a validated RoleDefinition."""
    # Ensure spec.model is a concrete ModelConfig (not PartialModelConfig)
    model = role.spec.model
    if model is None or (hasattr(model, "is_resolved") and not model.is_resolved()):
        raise RoleLoadError(
            "Model must be resolved before building an agent. Call resolve_role_model() first."
        )
    if not isinstance(role.spec.model, ModelConfig):
        role = _set_model(role, ModelConfig(**role.spec.model.model_dump()))  # type: ignore[union-attr]
    _validate_provider(role)
    _validate_reasoning(role)

    instructions, all_tools, explicit_paths = _resolve_skills_and_merge(
        role, role_dir, extra_skill_dirs
    )

    # When the role prompt uses {{var}} templates, defer its substitution to a
    # dynamic system prompt hook so the raw placeholders never reach the model.
    # We strip the role prompt from ``instructions`` here (leaving skill prompts
    # + auto-tool addendum intact) and re-inject it below via @agent.system_prompt.
    from initrunner.agent.templating import has_templates as _has_templates

    templating_active = role.spec.deps_schema is not None and _has_templates(role.spec.role)
    if templating_active:
        prefix = role.spec.role
        if instructions.startswith(prefix):
            instructions = instructions[len(prefix) :].lstrip()

    if output_type is None:
        from initrunner.agent.output import resolve_output_type

        output_type = resolve_output_type(role.spec.output, role_dir)

    # Widen output_type to a union with DeferredToolRequests when any tool
    # requires human approval, so PydanticAI can surface pending calls
    # instead of executing them. Only widens when the caller didn't supply
    # an explicit output_type to preserve caller intent.
    if any(t.approval == "required" for t in all_tools):
        from pydantic_ai import DeferredToolRequests

        output_type = [output_type, DeferredToolRequests]

    from initrunner.agent.tools import build_toolsets

    toolsets = build_toolsets(all_tools, role, role_dir=role_dir)

    capabilities = _build_capabilities(role)

    auto = _build_auto_tools(role, role_dir, explicit_paths, extra_skill_dirs)
    toolsets.extend(auto.extra_toolsets)
    instructions += auto.prompt_addendum

    instrument = None
    if role.spec.observability is not None:
        from initrunner.observability import get_instrumentation_settings

        instrument = get_instrumentation_settings(role.spec.observability)

    agent = _create_agent(
        role,
        instructions,
        toolsets,
        output_type,
        instrument=instrument,
        prepare_tools=auto.prepare_tools,
        capabilities=capabilities,
    )

    if templating_active:
        from initrunner.agent.templating import env_values as _env_template_values
        from initrunner.agent.templating import render as _render_template

        @agent.system_prompt
        def _render_role_prompt() -> str:
            schema = role.spec.deps_schema or {}
            # Non-CLI runtimes (daemon/trigger/bot) have no --var; fall back to
            # INITRUNNER_VAR_<KEY> env vars so required placeholders resolve and
            # the prompt is never sent with literal {{var}} text. CLI values win.
            explicit = getattr(agent, "_template_values", {}) or {}
            values = {**_env_template_values(schema), **explicit}
            return _render_template(role.spec.role, schema, values)

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

    Preserves tuning fields (temperature, max_tokens, context_window) and the
    fallback list from the existing model config.  Clears base_url/api_key_env
    when provider changes.
    """
    partial = role.spec.model
    base: dict[str, Any] = {}
    if partial is not None:
        base = {
            "temperature": partial.temperature,
            "max_tokens": partial.max_tokens,
            "context_window": partial.context_window,
            "fallback": partial.fallback,
            "thinking": partial.thinking,
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
    from initrunner.run_config import load_run_config

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
        fallback=base.fallback,
        thinking=base.thinking,
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
