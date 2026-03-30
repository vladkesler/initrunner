"""Provider auto-detection and ephemeral role building."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from initrunner.agent.schema.ingestion import IngestConfig
    from initrunner.agent.schema.memory import MemoryConfig
    from initrunner.agent.schema.role import RoleDefinition, ToolSearchConfig
    from initrunner.agent.schema.triggers import TriggerConfig

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ollama connectivity
# ---------------------------------------------------------------------------

OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434/v1"
_OLLAMA_TIMEOUT = 2


def is_ollama_running(*, timeout: int = _OLLAMA_TIMEOUT) -> bool:
    """Return True if Ollama is reachable."""
    import urllib.request

    try:
        urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=timeout)
    except Exception:
        return False
    return True


def list_ollama_models(*, timeout: int = _OLLAMA_TIMEOUT) -> list[str]:
    """Return all available Ollama model names, or [] on failure."""
    import json
    import urllib.request

    try:
        resp = urllib.request.urlopen(OLLAMA_TAGS_URL, timeout=timeout)
        data = json.loads(resp.read())
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


# Explicit priority order — first match wins.
# Do NOT rely on dict insertion order for correctness.
_PROVIDER_PRIORITY: list[tuple[str, str]] = [
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
    ("cohere", "CO_API_KEY"),
    ("xai", "XAI_API_KEY"),
]

_BOT_TOKEN_ENVS: dict[str, str] = {
    "telegram": "TELEGRAM_BOT_TOKEN",
    "discord": "DISCORD_BOT_TOKEN",
}

CHAT_PERSONALITY = (
    "You are a helpful, knowledgeable assistant. Be direct, precise, and concise. "
    "Answer with facts — no filler, no commentary, no personality flourishes. "
    "Shorter is better."
)

# ---------------------------------------------------------------------------
# Ephemeral tool constants (shared by CLI, Web, TUI)
# ---------------------------------------------------------------------------

EPHEMERAL_TOOL_DEFAULTS: dict[str, dict] = {
    "datetime": {"type": "datetime"},
    "web_reader": {"type": "web_reader"},
    "search": {"type": "search"},
    "python": {"type": "python"},
    "filesystem": {"type": "filesystem", "root_path": ".", "read_only": True},
    "slack": {"type": "slack", "webhook_url": "${SLACK_WEBHOOK_URL}"},
    "git": {"type": "git", "repo_path": ".", "read_only": True},
    "shell": {"type": "shell"},
}

TOOL_REQUIRED_ENVS: dict[str, list[str]] = {
    "slack": ["SLACK_WEBHOOK_URL"],
}

TOOL_PROFILES: dict[str, list[dict]] = {
    "none": [],
    "minimal": [
        {"type": "datetime"},
        {"type": "web_reader"},
    ],
    "all": list(EPHEMERAL_TOOL_DEFAULTS.values()),
}


@dataclass(frozen=True)
class DetectedProvider:
    provider: str
    model: str


def _load_env() -> None:
    """Load dotenv files using the same mechanism as the loader."""
    from initrunner.agent.loader import _load_dotenv

    _load_dotenv(Path.cwd())


def _is_ollama_running() -> bool:
    """Return True if Ollama is reachable at localhost:11434."""
    return is_ollama_running()


def _get_first_ollama_model() -> str | None:
    """Return the name of the first available Ollama model, or None."""
    models = list_ollama_models()
    return models[0] if models else None


def detect_provider_and_model() -> DetectedProvider | None:
    """Auto-detect provider from env vars and dotenv files.

    Checks providers in explicit priority order (anthropic first).
    Falls back to Ollama if running locally with no API keys.
    Returns None if nothing is configured.
    """
    from initrunner.templates import _default_model_name

    _load_env()

    for provider, env_var in _PROVIDER_PRIORITY:
        if os.environ.get(env_var):
            return DetectedProvider(provider=provider, model=_default_model_name(provider))

    # Fallback: Ollama running locally
    if _is_ollama_running():
        model = _get_first_ollama_model() or "llama3.2"
        return DetectedProvider(provider="ollama", model=model)

    return None


def detect_bot_tokens() -> dict[str, str]:
    """Return mapping of platform -> env var name for detected bot tokens."""
    _load_env()
    return {
        platform: env_var
        for platform, env_var in _BOT_TOKEN_ENVS.items()
        if os.environ.get(env_var)
    }


def resolve_provider_and_model(
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str]:
    """Detect provider/model, apply overrides. Raises RuntimeError if none found."""
    detected = detect_provider_and_model()
    if detected is None and provider is None:
        raise RuntimeError(
            "No API key found. Run `initrunner setup` or set an API key environment variable."
        )

    prov = provider or detected.provider  # type: ignore[union-attr]
    mod = model or detected.model  # type: ignore[union-attr]

    if provider and not model:
        from initrunner.templates import _default_model_name

        mod = _default_model_name(provider)

    return prov, mod


def list_available_providers() -> list[DetectedProvider]:
    """Return all providers the user has API keys for, in priority order."""
    from initrunner.templates import _default_model_name

    _load_env()

    result: list[DetectedProvider] = []
    for provider, env_var in _PROVIDER_PRIORITY:
        if os.environ.get(env_var):
            result.append(DetectedProvider(provider=provider, model=_default_model_name(provider)))

    if _is_ollama_running():
        model = _get_first_ollama_model() or "llama3.2"
        result.append(DetectedProvider(provider="ollama", model=model))

    return result


# ---------------------------------------------------------------------------
# Provider compatibility checking for installed roles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderCompatibility:
    """Result of checking whether a role's provider matches user configuration."""

    role_provider: str
    role_model: str
    user_has_key: bool
    available_providers: list[DetectedProvider]
    needs_embeddings: bool
    effective_embedding_provider: str
    has_embedding_key: bool


def _effective_embedding_provider(role: object) -> tuple[str, str]:
    """Resolve the effective embedding provider and its required env var.

    Inspects ``ingest.embeddings`` and ``memory.embeddings`` overrides,
    falling back to the default mapping in ``ingestion/embeddings.py``.

    Returns ``(provider_name, env_var_name)``.
    """
    from initrunner.ingestion.embeddings import (
        _DEFAULT_MODELS,
        _default_embedding_key_env,
    )

    spec = getattr(role, "spec", None)
    if spec is None:
        return "", ""

    # Check ingest.embeddings first, then memory.embeddings
    for config_attr in ("ingest", "memory"):
        section = getattr(spec, config_attr, None)
        if section is None:
            continue
        emb = getattr(section, "embeddings", None)
        if emb is None:
            continue
        if getattr(emb, "provider", ""):
            prov = emb.provider
            env = getattr(emb, "api_key_env", "") or _default_embedding_key_env(prov)
            return prov, env

    # No explicit override -- use default based on LLM provider
    llm_prov = spec.model.provider if getattr(spec, "model", None) and spec.model.provider else ""
    default_emb = _DEFAULT_MODELS.get(llm_prov, "openai:text-embedding-3-small")
    emb_prov = default_emb.split(":")[0] if ":" in default_emb else "openai"
    return emb_prov, _default_embedding_key_env(emb_prov)


# ---------------------------------------------------------------------------
# Cached Ollama status (avoids 2s blocking on every /validate debounce)
# ---------------------------------------------------------------------------

_ollama_cache: tuple[float, bool] = (0.0, False)
_OLLAMA_CACHE_TTL = 30.0


def _is_ollama_running_cached() -> bool:
    """Return cached Ollama reachability (30s TTL)."""
    import time

    now = time.monotonic()
    cached_at, cached_val = _ollama_cache
    if now - cached_at < _OLLAMA_CACHE_TTL:
        return cached_val
    # Refresh
    result = is_ollama_running()
    globals()["_ollama_cache"] = (now, result)
    return result


# ---------------------------------------------------------------------------
# Embedding status check for dashboard builder
# ---------------------------------------------------------------------------

# Explicit allowlist of embedding providers surfaced in the builder UI.
# Do NOT derive from _PROVIDER_EMBEDDING_KEY_DEFAULTS (it has "anthropic"
# as an alias for OPENAI_API_KEY, which would be a confusing option).
_SELECTABLE_EMBEDDING_PROVIDERS: list[tuple[str, str]] = [
    ("openai", "OPENAI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("ollama", ""),
]


def check_embedding_status(role: object) -> dict | None:
    """Check if a role needs embeddings and whether the effective provider is usable.

    Returns a dict with warning metadata (matching ``EmbeddingWarning`` schema)
    when the effective embedding provider is unusable, or ``None`` if everything
    is fine or the role doesn't need embeddings.
    """
    spec = getattr(role, "spec", None)
    if spec is None:
        return None

    has_ingest = getattr(spec, "ingest", None) is not None
    has_memory = getattr(spec, "memory", None) is not None
    if not has_ingest and not has_memory:
        return None

    emb_provider, emb_env = _effective_embedding_provider(role)
    if not emb_provider:
        return None

    # Check if effective provider is usable
    if emb_provider == "ollama":
        if _is_ollama_running_cached():
            return None
    elif emb_env and os.environ.get(emb_env):
        return None

    # Effective provider is broken -- build the warning
    llm_provider = ""
    if getattr(spec, "model", None) and getattr(spec.model, "provider", ""):
        llm_provider = spec.model.provider

    if has_ingest and has_memory:
        feature = "RAG and memory"
    elif has_ingest:
        feature = "RAG"
    else:
        feature = "memory"

    # Build selectable options with current status
    options = []
    for prov, env in _SELECTABLE_EMBEDDING_PROVIDERS:
        if prov == "ollama":
            configured = _is_ollama_running_cached()
        else:
            configured = bool(os.environ.get(env))
        options.append(
            {
                "provider": prov,
                "env_var": env,
                "is_configured": configured,
            }
        )

    msg = (
        f"This agent uses {feature}, which requires embeddings. "
        f"{llm_provider.capitalize() if llm_provider else 'The selected provider'} "
        f"doesn't provide them, so {emb_provider.capitalize()} is used instead. "
    )
    if emb_provider == "ollama":
        msg += "Start Ollama to enable local embeddings."
    else:
        msg += f"Set {emb_env} to enable this."

    return {
        "llm_provider": llm_provider,
        "feature": feature,
        "current_provider": emb_provider,
        "options": options,
        "message": msg,
    }


def check_role_provider_compatibility(role_path: Path) -> ProviderCompatibility:
    """Check whether the user has the provider/embedding keys a role needs.

    Loads the role YAML and inspects ``spec.model``, ``spec.ingest.embeddings``,
    and ``spec.memory.embeddings``.
    """
    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS, load_role, resolve_role_model

    _load_env()
    role = resolve_role_model(load_role(role_path), role_path)

    role_provider = role.spec.model.provider  # type: ignore[union-attr]
    role_model = role.spec.model.name  # type: ignore[union-attr]

    # Check if user has the required LLM key
    env_var = role.spec.model.api_key_env or _PROVIDER_API_KEY_ENVS.get(role_provider, "")  # type: ignore[union-attr]
    user_has_key = bool(os.environ.get(env_var)) if env_var else True
    # Ollama needs no key
    if role_provider == "ollama":
        user_has_key = _is_ollama_running()

    available = list_available_providers()

    # Check embeddings
    has_ingest = getattr(role.spec, "ingest", None) is not None
    has_memory = getattr(role.spec, "memory", None) is not None
    needs_embeddings = has_ingest or has_memory

    emb_provider = ""
    has_embedding_key = True
    if needs_embeddings:
        emb_provider, emb_env = _effective_embedding_provider(role)
        if emb_provider == "ollama":
            has_embedding_key = _is_ollama_running()
        elif emb_env:
            has_embedding_key = bool(os.environ.get(emb_env))

    return ProviderCompatibility(
        role_provider=role_provider,
        role_model=role_model,
        user_has_key=user_has_key,
        available_providers=available,
        needs_embeddings=needs_embeddings,
        effective_embedding_provider=emb_provider,
        has_embedding_key=has_embedding_key,
    )


def check_tool_envs() -> dict[str, list[str]]:
    """Return tool names with their missing env vars.

    Returns a mapping of ``tool_name -> [missing_var, ...]`` for tools that
    have at least one required env var unset.
    """
    missing_map: dict[str, list[str]] = {}
    for tool_name, env_vars in TOOL_REQUIRED_ENVS.items():
        missing = [v for v in env_vars if not os.environ.get(v)]
        if missing:
            missing_map[tool_name] = missing
    return missing_map


def build_quick_chat_role_sync(
    *,
    provider: str | None = None,
    model: str | None = None,
    tool_defs: list[dict] | None = None,
    with_memory: bool = True,
    personality: str | None = None,
    name: str = "ephemeral-chat",
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> tuple[RoleDefinition, str, str]:
    """Detect provider, filter tools for missing env, build ephemeral role.

    Returns (role, provider_name, model_name).
    Raises RuntimeError if no provider detected.
    """
    from initrunner.agent.schema.memory import MemoryConfig
    from initrunner.agent.schema.role import RoleDefinition as RoleDef
    from initrunner.agent.schema.role import ToolSearchConfig
    from initrunner.agent.tools.registry import resolve_func_names

    _load_env()

    prov, mod = resolve_provider_and_model(provider, model)

    # Build tools: filter out those with missing env vars
    skip = set(check_tool_envs())
    if tool_defs is None:
        all_tools: list[dict] = [
            t for t in EPHEMERAL_TOOL_DEFAULTS.values() if t["type"] not in skip
        ]
    else:
        all_tools = [t for t in tool_defs if t.get("type") not in skip]

    # Compute always_available from the "all" profile tools (minus skipped)
    always_available = resolve_func_names(
        [t for t in TOOL_PROFILES["all"] if t["type"] not in skip]
    )

    tool_search = ToolSearchConfig(enabled=True, always_available=always_available)

    memory_config = MemoryConfig() if with_memory else None

    build_kwargs: dict = {
        "name": name,
        "tools": all_tools if all_tools else None,
        "memory": memory_config,
        "tool_search": tool_search,
        "base_url": base_url,
        "api_key_env": api_key_env,
    }
    if personality:
        build_kwargs["system_prompt"] = (
            personality + "\n"
            "Never ask clarifying questions — answer directly with your best take. "
            "Keep responses concise."
        )

    role: RoleDef = build_ephemeral_role(prov, mod, **build_kwargs)
    return role, prov, mod


_MEMORY_SYSTEM_PROMPT = (
    "\n\nYou have persistent long-term memory across conversations.\n\n"
    "Before answering, use recall() to check for relevant context about the user or topic.\n"
    "When the user shares preferences, facts, or important decisions, "
    "use remember() to store them.\n"
    "When you learn a useful pattern or policy, use learn_procedure() to record it.\n"
    "Do this naturally without announcing it."
)

_INGEST_SYSTEM_PROMPT = (
    "\n\nYou have access to ingested documents via the search_documents() tool. "
    "When the user asks about document content, ALWAYS call search_documents() "
    "first to find relevant passages before answering. Cite sources when possible."
)


def build_ephemeral_role(
    provider: str,
    model: str,
    *,
    name: str = "ephemeral-chat",
    system_prompt: str = (
        CHAT_PERSONALITY + "\n"
        "Never ask clarifying questions — answer directly with your best take. "
        "Keep responses concise."
    ),
    triggers: list[TriggerConfig] | None = None,
    tools: list[dict] | None = None,
    autonomy: dict | None = None,
    guardrails: dict | None = None,
    memory: MemoryConfig | None = None,
    ingest: IngestConfig | None = None,
    tool_search: ToolSearchConfig | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
) -> RoleDefinition:
    """Create an in-memory RoleDefinition without writing YAML."""
    from initrunner.agent.schema.base import ApiVersion, Kind, ModelConfig, RoleMetadata
    from initrunner.agent.schema.guardrails import Guardrails
    from initrunner.agent.schema.role import AgentSpec
    from initrunner.agent.schema.role import RoleDefinition as RoleDef

    if memory is not None:
        system_prompt += _MEMORY_SYSTEM_PROMPT

    if ingest is not None:
        system_prompt += _INGEST_SYSTEM_PROMPT

    spec_kwargs: dict = {
        "role": system_prompt,
        "model": ModelConfig(
            provider=provider,
            name=model,
            base_url=base_url,
            api_key_env=api_key_env,
        ),
        "guardrails": Guardrails(**(guardrails or {})),
    }

    if triggers:
        spec_kwargs["triggers"] = triggers

    if tools:
        from initrunner.agent.schema.role import parse_tool_list

        spec_kwargs["tools"] = parse_tool_list(tools)

    if autonomy is not None:
        from initrunner.agent.schema.autonomy import AutonomyConfig

        spec_kwargs["autonomy"] = AutonomyConfig(**autonomy)

    if memory is not None:
        spec_kwargs["memory"] = memory

    if ingest is not None:
        spec_kwargs["ingest"] = ingest

    if tool_search is not None:
        spec_kwargs["tool_search"] = tool_search

    return RoleDef(
        apiVersion=ApiVersion.V1,
        kind=Kind.AGENT,
        metadata=RoleMetadata(name=name, description="Ephemeral chat agent"),
        spec=AgentSpec(**spec_kwargs),
    )
