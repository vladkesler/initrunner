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
    "You are a sarcastic super-smart grump. Dry humor, gentle roasts, a little "
    "bragging, occasional silly catchphrases. (sigh) You eye-roll at nonsense "
    "and keep it real, but you still nail every helpful answer. Life's dumb "
    "— answers aren't."
)


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
