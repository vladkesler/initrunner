"""Setup wizard orchestration layer.

Thin coordination module that provides constants and delegates to existing
services.  CLI, API, and TUI are thin wrappers around this module.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_PROVIDERS: list[str] = [
    "openai",
    "anthropic",
    "google",
    "groq",
    "mistral",
    "cohere",
    "bedrock",
    "xai",
    "ollama",
]

INTENT_DESCRIPTIONS: dict[str, str] = {
    "chatbot": "Conversational AI assistant",
    "knowledge": "Answer questions from your documents (RAG)",
    "memory": "Assistant that remembers across conversations",
    "telegram-bot": "Telegram bot powered by AI",
    "discord-bot": "Discord bot powered by AI",
    "api-agent": "Agent with REST API tool access",
    "daemon": "Runs on a schedule or watches for changes",
    "from-example": "Browse and copy a bundled example",
}

INTENT_TEMPLATE_MAP: dict[str, str] = {
    "chatbot": "basic",
    "knowledge": "rag",
    "memory": "memory",
    "telegram-bot": "telegram",
    "discord-bot": "discord",
    "api-agent": "api",
    "daemon": "daemon",
}

INTENT_DEFAULT_TOOLS: dict[str, list[str]] = {
    "chatbot": ["datetime", "web_reader"],
    "knowledge": ["datetime"],
    "memory": ["datetime", "web_reader"],
    "telegram-bot": ["datetime", "web_reader"],
    "discord-bot": ["datetime", "web_reader"],
    "api-agent": ["http", "datetime"],
    "daemon": ["filesystem", "shell", "datetime"],
}

NO_EMBEDDINGS_PROVIDERS: set[str] = {
    "anthropic",
    "groq",
    "cohere",
    "bedrock",
    "xai",
    "ollama",
}

BOT_TOKEN_ENVS: dict[str, str] = {
    "telegram-bot": "TELEGRAM_BOT_TOKEN",
    "discord-bot": "DISCORD_BOT_TOKEN",
}

# Map legacy --template values to intents
_TEMPLATE_TO_INTENT: dict[str, str] = {
    "chatbot": "chatbot",
    "basic": "chatbot",
    "rag": "knowledge",
    "memory": "memory",
    "daemon": "daemon",
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class SetupConfig:
    """Collected setup wizard state."""

    intent: str
    provider: str
    model: str
    name: str = "my-agent"
    tools: list[dict] = field(default_factory=list)
    enable_memory: bool = False
    ingest_sources: list[str] | None = None
    triggers: list[dict] | None = None
    embedding_provider: str | None = None
    personality: str | None = None


# ---------------------------------------------------------------------------
# Detection helpers — delegate to existing modules
# ---------------------------------------------------------------------------


def needs_setup() -> bool:
    """True if no API key is configured anywhere."""
    from dotenv import dotenv_values

    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS
    from initrunner.config import get_global_env_path

    for env_var in _PROVIDER_API_KEY_ENVS.values():
        if os.environ.get(env_var):
            return False

    env_path = get_global_env_path()
    if env_path.is_file():
        values = dotenv_values(env_path)
        for env_var in _PROVIDER_API_KEY_ENVS.values():
            if values.get(env_var):
                return False

    # Ollama running locally counts as configured
    from initrunner.services.providers import _is_ollama_running

    if _is_ollama_running():
        return False

    return True


def detect_existing_provider() -> tuple[str, str] | None:
    """Detect a configured provider. Returns (provider, env_var) or None."""
    from dotenv import dotenv_values

    from initrunner.agent.loader import _PROVIDER_API_KEY_ENVS
    from initrunner.config import get_global_env_path

    for prov, env_var in _PROVIDER_API_KEY_ENVS.items():
        if os.environ.get(env_var):
            return prov, env_var

    env_path = get_global_env_path()
    if env_path.is_file():
        values = dotenv_values(env_path)
        for prov, env_var in _PROVIDER_API_KEY_ENVS.items():
            if values.get(env_var):
                return prov, env_var

    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_api_key(provider: str, api_key: str) -> bool:
    """Lightweight API key validation. Returns True if key appears valid."""
    try:
        if provider == "openai":
            req = urllib.request.Request(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            urllib.request.urlopen(req, timeout=5)
            return True
        if provider == "anthropic":
            body = json.dumps(
                {
                    "model": "claude-sonnet-4-5-20250929",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                }
            ).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=body,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            urllib.request.urlopen(req, timeout=5)
            return True
    except Exception:
        return False
    # Other providers: skip validation
    return True


def provider_needs_embeddings_warning(provider: str, intent: str) -> bool:
    """True when the intent needs embeddings but the provider doesn't offer them."""
    return intent in ("knowledge", "memory") and provider in NO_EMBEDDINGS_PROVIDERS


# ---------------------------------------------------------------------------
# Ollama helpers — delegate to existing service
# ---------------------------------------------------------------------------


def check_ollama_models() -> list[str]:
    """Query Ollama for available models. Returns list of model names."""
    try:
        resp = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def save_env_key(env_var: str, value: str) -> Path | None:
    """Write a key to ``~/.initrunner/.env``. Returns path on success, None on failure."""
    from dotenv import set_key

    from initrunner.config import get_global_env_path, get_home_dir

    try:
        home_dir = get_home_dir()
        home_dir.mkdir(parents=True, exist_ok=True)
        env_path = get_global_env_path()
        set_key(str(env_path), env_var, value)
        env_path.chmod(0o600)
        return env_path
    except (PermissionError, OSError) as exc:
        _logger.warning("Could not write %s: %s", env_var, exc)
        return None


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------


def generate_role_yaml(config: SetupConfig) -> str:
    """Build role YAML from SetupConfig.

    Derives template key from INTENT_TEMPLATE_MAP — NOT from provider.
    This fixes the Ollama override bug where provider=='ollama' would force
    the 'ollama' template regardless of the user's intent.
    """
    from initrunner.templates import TEMPLATES, build_role_yaml

    template_key = INTENT_TEMPLATE_MAP.get(config.intent)

    # For telegram/discord/api intents, use the dedicated template function
    if template_key in ("telegram", "discord", "api"):
        builder = TEMPLATES[template_key]
        return builder(config.name, config.provider, config.model)

    # For chatbot/knowledge/memory/daemon, use build_role_yaml for full control
    system_prompt = "You are a helpful assistant."
    memory = False
    ingest = None
    triggers = None
    tools = config.tools or None

    if config.intent == "knowledge":
        system_prompt = (
            "You are a knowledge assistant. Use search_documents to find relevant\n"
            "content before answering. Always cite your sources."
        )
        sources = config.ingest_sources or ["./docs/**/*.md", "./docs/**/*.txt"]
        ingest = {
            "sources": sources,
            "chunking": {
                "strategy": "fixed",
                "chunk_size": 512,
                "chunk_overlap": 50,
            },
        }
    elif config.intent == "memory":
        system_prompt = (
            "You are a helpful assistant with long-term memory.\n"
            "Use the remember() tool to save important information.\n"
            "Use the recall() tool to search your memories before answering."
        )
        memory = True
    elif config.intent == "daemon":
        system_prompt = "You are a monitoring assistant that responds to events."
        if config.triggers:
            triggers = config.triggers
        else:
            triggers = [
                {
                    "type": "file_watch",
                    "paths": ["./watched"],
                    "extensions": [".md", ".txt"],
                    "prompt_template": "File changed: {path}. Summarize the changes.",
                }
            ]
    elif config.personality:
        system_prompt = config.personality

    return build_role_yaml(
        name=config.name,
        provider=config.provider,
        model_name=config.model,
        system_prompt=system_prompt,
        tools=tools,
        memory=memory,
        ingest=ingest,
        triggers=triggers,
    )


def generate_chat_yaml(config: SetupConfig) -> str:
    """Generate chat.yaml content from SetupConfig.

    Uses ChatConfig schema to avoid drift.
    """
    import yaml

    from initrunner.cli.chat_config import ChatConfig

    chat = ChatConfig(
        provider=config.provider,
        model=config.model,
        personality=config.personality,
    )
    data = chat.model_dump(exclude_none=True)
    return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)


def save_chat_yaml(config: SetupConfig) -> Path:
    """Write chat.yaml to the standard config path."""
    from initrunner.cli.chat_config import _get_chat_config_path
    from initrunner.config import get_home_dir

    path = _get_chat_config_path()
    get_home_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(generate_chat_yaml(config))
    return path


# ---------------------------------------------------------------------------
# Post-generation actions
# ---------------------------------------------------------------------------


def run_connectivity_test(role_path: Path) -> tuple[bool, str]:
    """Run a quick agent test. Returns (success, message)."""
    try:
        from initrunner.agent.executor import execute_run
        from initrunner.agent.loader import _load_dotenv, load_and_build

        _load_dotenv(role_path.parent)
        role, agent = load_and_build(role_path)
        result, _ = execute_run(agent, role, "Hello, respond in one sentence.")
        if result.success:
            return True, result.output[:200]
        return False, result.error or "Unknown error"
    except Exception as exc:
        return False, str(exc)


def run_ingest_for_role(role_path: Path) -> bool:
    """Run ingestion for a role. Returns True on success."""
    try:
        from initrunner.agent.loader import load_role
        from initrunner.services.operations import run_ingest_sync

        role = load_role(role_path)
        stats = run_ingest_sync(role, role_path)
        return stats is not None
    except Exception as exc:
        _logger.warning("Ingestion failed: %s", exc)
        return False


def template_to_intent(template: str) -> str:
    """Map a legacy --template value to an intent name."""
    return _TEMPLATE_TO_INTENT.get(template, template)
