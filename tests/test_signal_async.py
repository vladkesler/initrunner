"""Tests for the async shutdown signal handler."""

from __future__ import annotations

import asyncio
import os
import signal

import pytest

from initrunner._signal import install_async_shutdown_handler


class TestInstallAsyncShutdownHandler:
    @pytest.mark.asyncio
    async def test_first_signal_sets_event_and_calls_callback(self):
        """First signal sets the stop event and calls on_first_signal."""
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()
        called = []

        def _on_first():
            called.append(True)

        install_async_shutdown_handler(loop, stop, on_first_signal=_on_first)

        # Send SIGINT to ourselves
        os.kill(os.getpid(), signal.SIGINT)

        # Wait for the event
        await asyncio.wait_for(stop.wait(), timeout=2)

        assert stop.is_set()
        assert len(called) == 1

    @pytest.mark.asyncio
    async def test_double_signal_force_exits(self):
        """Second signal calls os._exit."""
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()

        install_async_shutdown_handler(loop, stop)

        # First signal
        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.wait_for(stop.wait(), timeout=2)

        # Second signal should call os._exit
        import unittest.mock

        with unittest.mock.patch("initrunner._signal.os._exit") as mock_exit:
            os.kill(os.getpid(), signal.SIGINT)
            # Give the event loop a chance to process
            await asyncio.sleep(0.1)
            mock_exit.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_without_callback(self):
        """Works when no on_first_signal callback is provided."""
        loop = asyncio.get_running_loop()
        stop = asyncio.Event()

        install_async_shutdown_handler(loop, stop)

        os.kill(os.getpid(), signal.SIGINT)
        await asyncio.wait_for(stop.wait(), timeout=2)

        assert stop.is_set()
