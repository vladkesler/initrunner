"""Provider detection and key management routes."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException  # type: ignore[import-not-found]

from initrunner.dashboard.schemas import (
    ProviderResponse,
    ProviderStatus,
    ProviderStatusResponse,
    SaveKeyRequest,
    SaveKeyResponse,
)

_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers", tags=["providers"])


# -- Validation-capable providers ---------------------------------------------

_VALIDATABLE_PROVIDERS = frozenset({"openai", "anthropic"})


# -- GET /api/providers -------------------------------------------------------


@router.get("")
async def list_providers() -> list[ProviderResponse]:
    from initrunner.credentials import get_resolver
    from initrunner.dashboard.routers._provider_options import CUSTOM_PRESETS
    from initrunner.services.providers import list_available_providers

    providers = await asyncio.to_thread(list_available_providers)
    result = [ProviderResponse(provider=p.provider, model=p.model) for p in providers]

    resolver = get_resolver()
    for preset in CUSTOM_PRESETS:
        if preset.api_key_env and resolver.get(preset.api_key_env):
            result.append(ProviderResponse(provider=preset.name, model=preset.placeholder))

    return result


# -- GET /api/providers/status ------------------------------------------------


def _build_provider_status() -> tuple[list[ProviderStatus], str | None, str | None]:
    """Build full provider status list including standard, presets, and Ollama."""
    from initrunner.credentials import get_resolver
    from initrunner.dashboard.routers._provider_options import CUSTOM_PRESETS
    from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT as _PROVIDER_API_KEY_ENVS
    from initrunner.services.providers import detect_provider_and_model

    statuses: list[ProviderStatus] = []
    resolver = get_resolver()

    # Standard providers
    for prov, env_var in _PROVIDER_API_KEY_ENVS.items():
        statuses.append(
            ProviderStatus(
                provider=prov,
                env_var=env_var,
                is_configured=bool(resolver.get(env_var)),
            )
        )

    # Custom presets (OpenRouter, etc.)
    for preset in CUSTOM_PRESETS:
        if not preset.api_key_env:
            continue
        statuses.append(
            ProviderStatus(
                provider=preset.name,
                env_var=preset.api_key_env,
                is_configured=bool(resolver.get(preset.api_key_env)),
            )
        )

    # Ollama
    try:
        from initrunner.services.providers import is_ollama_running

        if is_ollama_running():
            statuses.append(ProviderStatus(provider="ollama", env_var="", is_configured=True))
    except Exception:
        statuses.append(ProviderStatus(provider="ollama", env_var="", is_configured=False))

    # Detect best provider
    detected_provider: str | None = None
    detected_model: str | None = None
    try:
        detected = detect_provider_and_model()
        if detected is not None:
            detected_provider = detected.provider
            detected_model = detected.model
    except Exception:
        _logger.debug("Provider detection failed", exc_info=True)

    return statuses, detected_provider, detected_model


@router.get("/status")
async def provider_status() -> ProviderStatusResponse:
    statuses, detected_provider, detected_model = await asyncio.to_thread(_build_provider_status)
    return ProviderStatusResponse(
        providers=statuses,
        detected_provider=detected_provider,
        detected_model=detected_model,
    )


# -- POST /api/providers/save-key ---------------------------------------------


@router.post("/save-key")
async def save_key(req: SaveKeyRequest) -> SaveKeyResponse:
    from initrunner.dashboard.routers._provider_options import CUSTOM_PRESETS
    from initrunner.services.providers import PROVIDER_KEY_ENVS_DICT as _PROVIDER_API_KEY_ENVS

    # Resolve env var name
    if req.provider:
        env_name = _PROVIDER_API_KEY_ENVS.get(req.provider)
        if not env_name:
            # Fall through to presets (e.g. OpenRouter)
            preset = next((p for p in CUSTOM_PRESETS if p.name == req.provider), None)
            if preset and preset.api_key_env:
                env_name = preset.api_key_env
            else:
                raise HTTPException(status_code=400, detail=f"Unknown provider: {req.provider}")
    elif req.preset:
        preset = next((p for p in CUSTOM_PRESETS if p.name == req.preset), None)
        if preset is None or not preset.api_key_env:
            raise HTTPException(status_code=400, detail=f"Unknown preset: {req.preset}")
        env_name = preset.api_key_env
    elif req.base_url:
        host = urlparse(req.base_url).hostname or "endpoint"
        sanitized = re.sub(r"[^A-Z0-9]", "_", host.upper()).strip("_")
        env_name = f"INITRUNNER_{sanitized}_KEY"
    else:
        raise HTTPException(
            status_code=400,
            detail="One of provider, preset, or base_url is required",
        )

    # Persist via services layer (vault when available + unlockable, else ~/.initrunner/.env)
    from initrunner.services.setup import save_env_key

    result_path = await asyncio.to_thread(save_env_key, env_name, req.api_key)
    if result_path is None:
        raise HTTPException(status_code=500, detail=f"Failed to write {env_name}")

    # Set in current process so subsequent requests see it immediately
    os.environ[env_name] = req.api_key

    # Optional validation
    validated = False
    validation_supported = req.provider in _VALIDATABLE_PROVIDERS if req.provider else False

    if req.verify and validation_supported:
        from initrunner.services.setup import validate_api_key

        validated = await asyncio.to_thread(validate_api_key, req.provider or "", req.api_key)

    return SaveKeyResponse(
        env_var=env_name,
        validated=validated,
        validation_supported=validation_supported,
    )
