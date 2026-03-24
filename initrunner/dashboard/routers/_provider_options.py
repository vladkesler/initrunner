"""Shared provider/model/preset detection for builder endpoints."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os

from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.schemas import ModelOption, ProviderModels, ProviderPreset

_logger = logging.getLogger(__name__)


# Custom provider presets (OpenRouter, custom endpoint).
CUSTOM_PRESETS = [
    ProviderPreset(
        name="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        placeholder="anthropic/claude-sonnet-4",
    ),
    ProviderPreset(
        name="custom",
        label="Custom endpoint",
        base_url="",
        api_key_env="",
        placeholder="model-name",
    ),
]

CUSTOM_PROVIDER_NAMES = {p.name for p in CUSTOM_PRESETS}


def resolve_custom_provider(
    provider: str,
    base_url: str | None,
    api_key_env: str | None,
) -> tuple[str, str | None, str | None]:
    """Normalize a custom/preset provider to canonical runtime fields.

    Returns ``(runtime_provider, resolved_base_url, resolved_api_key_env)``.
    Custom preset names (e.g. ``"openrouter"``) are mapped to ``"openai"``
    with their preset ``base_url`` / ``api_key_env`` injected when not
    explicitly provided.  Standard providers pass through unchanged.
    """
    if provider not in CUSTOM_PROVIDER_NAMES:
        return provider, base_url, api_key_env

    runtime_provider = "openai"
    if base_url is None:
        preset = next((p for p in CUSTOM_PRESETS if p.name == provider), None)
        if preset and preset.base_url:
            base_url = preset.base_url
            api_key_env = api_key_env or preset.api_key_env

    return runtime_provider, base_url, api_key_env


@dataclasses.dataclass
class ProviderOptions:
    """Provider/model data shared between agent and compose builders."""

    providers: list[ProviderModels]
    detected_provider: str | None
    detected_model: str | None
    custom_presets: list[ProviderPreset]
    ollama_models: list[str]
    ollama_base_url: str
    save_dirs: list[str]


async def gather_provider_options(settings: DashboardSettings) -> ProviderOptions:
    """Detect providers, query Ollama, check presets, resolve save dirs."""
    from initrunner.services.providers import OLLAMA_DEFAULT_BASE_URL
    from initrunner.templates import PROVIDER_MODELS

    providers = [
        ProviderModels(
            provider=prov,
            models=[ModelOption(name=m, description=d) for m, d in models],
        )
        for prov, models in PROVIDER_MODELS.items()
    ]

    detected_provider: str | None = None
    detected_model: str | None = None
    try:
        from initrunner.services.providers import detect_provider_and_model

        detected = await asyncio.to_thread(detect_provider_and_model)
        if detected is not None:
            detected_provider = detected.provider
            detected_model = detected.model
    except Exception:
        _logger.debug("Provider detection failed", exc_info=True)

    ollama_models: list[str] = []
    try:
        from initrunner.services.providers import list_ollama_models

        ollama_models = await asyncio.to_thread(list_ollama_models)
    except Exception:
        _logger.debug("Ollama model detection failed", exc_info=True)

    from initrunner.config import get_roles_dir

    save_dir = get_roles_dir()
    save_dir.mkdir(parents=True, exist_ok=True)
    save_dirs = [str(save_dir)]
    for d in settings.extra_role_dirs:
        ds = str(d)
        if ds not in save_dirs:
            save_dirs.append(ds)

    presets = []
    for p in CUSTOM_PRESETS:
        configured = bool(p.api_key_env and os.environ.get(p.api_key_env))
        presets.append(
            ProviderPreset(
                name=p.name,
                label=p.label,
                base_url=p.base_url,
                api_key_env=p.api_key_env,
                placeholder=p.placeholder,
                key_configured=configured,
            )
        )

    return ProviderOptions(
        providers=providers,
        detected_provider=detected_provider,
        detected_model=detected_model,
        custom_presets=presets,
        ollama_models=ollama_models,
        ollama_base_url=OLLAMA_DEFAULT_BASE_URL,
        save_dirs=save_dirs,
    )
