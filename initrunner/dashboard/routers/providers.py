"""Provider detection routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from initrunner.dashboard.schemas import ProviderResponse

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def list_providers() -> list[ProviderResponse]:
    from initrunner.services.providers import list_available_providers

    providers = await asyncio.to_thread(list_available_providers)
    return [ProviderResponse(provider=p.provider, model=p.model) for p in providers]
