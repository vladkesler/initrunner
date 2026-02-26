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

# Explicit priority order — first match wins.
# Do NOT rely on dict insertion order for correctness.
_PROVIDER_PRIORITY: list[tuple[str, str]] = [
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("google", "GOOGLE_API_KEY"),
    ("groq", "GROQ_API_KEY"),
    ("mistral", "MISTRAL_API_KEY"),
    ("cohere", "CO_API_KEY"),
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
    import urllib.request

    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
    except Exception:
        return False
    return True


def _get_first_ollama_model() -> str | None:
    """Return the name of the first available Ollama model, or None."""
    import json
    import urllib.request

    try:
        resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        data = json.loads(resp.read())
        models = data.get("models", [])
        if models:
            return models[0].get("name", "llama3.2")
    except Exception:
        pass
    return None


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


def _check_tool_envs() -> set[str]:
    """Return tool names that should be skipped due to missing env vars."""
    skip: set[str] = set()
    for tool_name, env_vars in TOOL_REQUIRED_ENVS.items():
        missing = [v for v in env_vars if not os.environ.get(v)]
        if missing:
            skip.add(tool_name)
    return skip


def build_quick_chat_role_sync(
    *,
    provider: str | None = None,
    model: str | None = None,
    tool_defs: list[dict] | None = None,
    with_memory: bool = True,
    personality: str | None = None,
    name: str = "ephemeral-chat",
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

    # Build tools: filter out those with missing env vars
    skip = _check_tool_envs()
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
) -> RoleDefinition:
    """Create an in-memory RoleDefinition without writing YAML."""
    from initrunner.agent.schema.base import ApiVersion, Kind, Metadata, ModelConfig
    from initrunner.agent.schema.guardrails import Guardrails
    from initrunner.agent.schema.role import AgentSpec
    from initrunner.agent.schema.role import RoleDefinition as RoleDef

    if memory is not None:
        system_prompt += _MEMORY_SYSTEM_PROMPT

    if ingest is not None:
        system_prompt += _INGEST_SYSTEM_PROMPT

    spec_kwargs: dict = {
        "role": system_prompt,
        "model": ModelConfig(provider=provider, name=model),
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
        metadata=Metadata(name=name, description="Ephemeral chat agent"),
        spec=AgentSpec(**spec_kwargs),
    )
