"""Shared helpers for API routes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from fastapi import HTTPException, Request

if TYPE_CHECKING:
    from collections.abc import Callable

    from initrunner.agent.schema.role import RoleDefinition

BUILD_TIMEOUT = 60.0

T = TypeVar("T")


async def run_in_thread(
    fn: Callable[..., T],
    *args: object,
    timeout: float = BUILD_TIMEOUT,
    error_msg: str = "Operation failed",
) -> T:
    """Run *fn* in a thread with timeout and HTTP error wrapping."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=timeout)
    except TimeoutError:
        raise HTTPException(status_code=504, detail=f"{error_msg}: timed out") from None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{error_msg}: {e}") from None


async def resolve_role_path(request: Request, role_id: str) -> Path:
    """Look up a role path by ID, raising 404 if not found."""
    registry = request.app.state.role_registry
    path = await asyncio.to_thread(registry.find_path, role_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Role not found")
    return path


async def load_role_with_memory(role_id: str, request: Request) -> tuple[RoleDefinition, Path]:
    """Load a role by ID, raising 400 if it has no memory config."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import load_role

    role = await asyncio.to_thread(load_role, role_path)
    if role.spec.memory is None:
        raise HTTPException(status_code=400, detail="No memory config in this role")
    return role, role_path
