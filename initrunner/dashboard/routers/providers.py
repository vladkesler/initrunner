"""Provider detection routes."""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter

from initrunner.dashboard.schemas import ProviderResponse

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def list_providers() -> list[ProviderResponse]:
    from initrunner.dashboard.routers._provider_options import CUSTOM_PRESETS
    from initrunner.services.providers import list_available_providers

    providers = await asyncio.to_thread(list_available_providers)
    result = [ProviderResponse(provider=p.provider, model=p.model) for p in providers]

    for preset in CUSTOM_PRESETS:
        if preset.api_key_env and os.environ.get(preset.api_key_env):
            result.append(ProviderResponse(provider=preset.name, model=preset.placeholder))

    return result
