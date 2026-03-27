"""Shared provider/model/preset detection for builder endpoints."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os

from initrunner.dashboard.config import DashboardSettings
from initrunner.dashboard.schemas import (
    ModelOption,
    ProviderModels,
    ProviderStatus,
)
from initrunner.dashboard.schemas import (
    ProviderPreset as ProviderPresetSchema,
)
from initrunner.services.presets import (
    CUSTOM_PRESETS as _SHARED_PRESETS,
)
from initrunner.services.presets import (
    resolve_preset,
)

_logger = logging.getLogger(__name__)


# Dashboard-only presets (custom endpoint has no shared representation).
_DASHBOARD_ONLY_PRESETS = [
    ProviderPresetSchema(
        name="custom",
        label="Custom endpoint",
        base_url="",
        api_key_env="",
        placeholder="model-name",
    ),
]

# Combined presets for dashboard API responses.
CUSTOM_PRESETS: list[ProviderPresetSchema] = [
    ProviderPresetSchema(
        name=p.name,
        label=p.label,
        base_url=p.base_url,
        api_key_env=p.api_key_env,
        placeholder=p.default_model,
    )
    for p in _SHARED_PRESETS
] + _DASHBOARD_ONLY_PRESETS

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

    # Check shared presets first
    shared = resolve_preset(provider)
    if shared is not None:
        runtime_provider = shared.runtime_provider
        if base_url is None and shared.base_url:
            base_url = shared.base_url
            api_key_env = api_key_env or shared.api_key_env
        return runtime_provider, base_url, api_key_env

    # Fallback for dashboard-only presets (custom endpoint)
    return "openai", base_url, api_key_env


@dataclasses.dataclass
class ProviderOptions:
    """Provider/model data shared between agent and compose builders."""

    providers: list[ProviderModels]
    detected_provider: str | None
    detected_model: str | None
    custom_presets: list[ProviderPresetSchema]
    ollama_models: list[str]
    ollama_base_url: str
    save_dirs: list[str]
    provider_status: list[ProviderStatus]


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
            ProviderPresetSchema(
                name=p.name,
                label=p.label,
                base_url=p.base_url,
                api_key_env=p.api_key_env,
                placeholder=p.placeholder,
                key_configured=configured,
            )
        )

    # Build provider status from env var presence (no connectivity test).
    from initrunner.services.providers import _PROVIDER_PRIORITY

    prov_status = [
        ProviderStatus(
            provider=prov,
            env_var=env_var,
            is_configured=bool(os.environ.get(env_var)),
        )
        for prov, env_var in _PROVIDER_PRIORITY
    ]
    # Include custom presets (OpenRouter, etc.)
    for p in CUSTOM_PRESETS:
        if p.api_key_env:
            prov_status.append(
                ProviderStatus(
                    provider=p.name,
                    env_var=p.api_key_env,
                    is_configured=bool(os.environ.get(p.api_key_env)),
                )
            )
    if ollama_models:
        prov_status.append(ProviderStatus(provider="ollama", env_var="", is_configured=True))

    return ProviderOptions(
        providers=providers,
        detected_provider=detected_provider,
        detected_model=detected_model,
        custom_presets=presets,
        ollama_models=ollama_models,
        ollama_base_url=OLLAMA_DEFAULT_BASE_URL,
        save_dirs=save_dirs,
        provider_status=prov_status,
    )
