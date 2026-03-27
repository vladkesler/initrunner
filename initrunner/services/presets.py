"""Shared custom-provider preset definitions.

Provides preset metadata for OpenAI-compatible providers (e.g. OpenRouter)
that are not first-class entries in ``ALL_PROVIDERS`` but can be auto-detected
from environment variables and configured via the setup wizard.

The dashboard layer converts these dataclasses into its own Pydantic response
models; CLI and services import directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    """A custom-endpoint provider preset (e.g. OpenRouter)."""

    name: str  # internal key, e.g. "openrouter"
    label: str  # human-readable, e.g. "OpenRouter"
    runtime_provider: str  # canonical PydanticAI provider, e.g. "openai"
    base_url: str  # e.g. "https://openrouter.ai/api/v1"
    api_key_env: str  # e.g. "OPENROUTER_API_KEY"
    default_model: str  # e.g. "anthropic/claude-sonnet-4"


CUSTOM_PRESETS: list[ProviderPreset] = [
    ProviderPreset(
        name="openrouter",
        label="OpenRouter",
        runtime_provider="openai",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_model="anthropic/claude-sonnet-4",
    ),
]

PRESET_BY_NAME: dict[str, ProviderPreset] = {p.name: p for p in CUSTOM_PRESETS}


def resolve_preset(name: str) -> ProviderPreset | None:
    """Look up a preset by name. Returns ``None`` for unknown names."""
    return PRESET_BY_NAME.get(name)
