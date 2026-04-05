"""Utility for running async coroutines from synchronous code."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, TypeVar, cast

import anyio

T = TypeVar("T")


def run_sync(coro: Coroutine[Any, Any, T]) -> T:
    """Run *coro* from synchronous code.

    If no event loop is running, starts a new one via ``anyio.run``.
    If an event loop is already running (e.g. inside compose or daemon
    mode), offloads to a worker thread that starts its own loop.
    """

    async def _wrapper() -> T:
        return await coro

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return cast(T, pool.submit(anyio.run, _wrapper).result())
    return anyio.run(_wrapper)
