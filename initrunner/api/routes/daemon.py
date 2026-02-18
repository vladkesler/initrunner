"""Daemon trigger management — WebSocket event stream and start/stop."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from initrunner.api._helpers import BUILD_TIMEOUT, load_role_async, resolve_role_path

router = APIRouter(prefix="/api/daemon", tags=["daemon"])
_logger = logging.getLogger(__name__)


@dataclass
class _DaemonState:
    """Tracks a daemon through its startup → running lifecycle."""

    status: str  # "starting" | "running"
    cancel: threading.Event = field(default_factory=threading.Event)
    dispatcher: object | None = None


# Active daemons keyed by role_id
_dispatchers: dict[str, _DaemonState] = {}
_dispatcher_lock = threading.Lock()


@router.post("/{role_id}/start")
async def start_daemon(role_id: str, request: Request):
    """Start triggers for a role."""
    with _dispatcher_lock:
        existing = _dispatchers.get(role_id)
        if existing is not None:
            status = "already_running" if existing.status == "running" else "already_starting"
            return {"status": status}
        state = _DaemonState(status="starting")
        _dispatchers[role_id] = state

    try:
        role_path = await resolve_role_path(request, role_id)

        if state.cancel.is_set():
            with _dispatcher_lock:
                if _dispatchers.get(role_id) is state:
                    del _dispatchers[role_id]
            return {"status": "cancelled"}

        role = await load_role_async(role_path)
        if not role.spec.triggers:
            with _dispatcher_lock:
                if _dispatchers.get(role_id) is state:
                    del _dispatchers[role_id]
            raise HTTPException(status_code=400, detail="No triggers configured")

        if state.cancel.is_set():
            with _dispatcher_lock:
                if _dispatchers.get(role_id) is state:
                    del _dispatchers[role_id]
            return {"status": "cancelled"}

        from initrunner.services.operations import start_triggers_sync

        def on_event(event):
            _logger.info("Trigger event for %s: %s", role_id, event)

        dispatcher = await asyncio.wait_for(
            asyncio.to_thread(start_triggers_sync, role, on_event),
            timeout=BUILD_TIMEOUT,
        )

        with _dispatcher_lock:
            if _dispatchers.get(role_id) is not state or state.cancel.is_set():
                # Cancelled or replaced during build — tear down immediately
                stop_all = getattr(dispatcher, "stop_all", None)
                if stop_all is not None:
                    try:
                        await asyncio.wait_for(asyncio.to_thread(stop_all), timeout=BUILD_TIMEOUT)
                    except Exception:
                        _logger.exception("Error stopping cancelled dispatcher for %s", role_id)
                if _dispatchers.get(role_id) is state:
                    del _dispatchers[role_id]
                return {"status": "cancelled"}
            state.dispatcher = dispatcher
            state.status = "running"

        return {"status": "started"}
    except Exception:
        with _dispatcher_lock:
            if _dispatchers.get(role_id) is state:
                del _dispatchers[role_id]
        raise


@router.post("/{role_id}/stop")
async def stop_daemon(role_id: str):
    """Stop triggers for a role."""
    with _dispatcher_lock:
        state = _dispatchers.pop(role_id, None)

    if state is None:
        return {"status": "not_running"}

    # Signal cancellation (handles in-progress starts)
    state.cancel.set()

    if state.dispatcher is not None:
        stop_all = getattr(state.dispatcher, "stop_all", None)
        if stop_all is not None:
            try:
                await asyncio.wait_for(asyncio.to_thread(stop_all), timeout=BUILD_TIMEOUT)
            except TimeoutError:
                _logger.warning("Timeout stopping dispatcher for %s", role_id)
            except Exception:
                _logger.exception("Error stopping dispatcher for %s", role_id)

    return {"status": "stopped"}


@router.websocket("/{role_id}")
async def daemon_websocket(websocket: WebSocket, role_id: str):
    """WebSocket stream of trigger events.

    Server sends: {"type": "event", "data": {"trigger": "...", "prompt": "...", "timestamp": "..."}}
                  {"type": "started"}
                  {"type": "stopped"}
    """
    from initrunner.api.auth import verify_websocket_auth

    if not await verify_websocket_auth(websocket):
        return

    await websocket.accept()

    registry = websocket.app.state.role_registry
    role_path = await asyncio.to_thread(registry.find_path, role_id)
    if role_path is None:
        await websocket.send_json({"type": "error", "data": {"message": "Role not found"}})
        await websocket.close()
        return

    role = await load_role_async(role_path)
    if not role.spec.triggers:
        await websocket.send_json({"type": "error", "data": {"message": "No triggers configured"}})
        await websocket.close()
        return

    event_queue: asyncio.Queue[dict | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_event(event):
        import time

        data = {
            "trigger": getattr(event, "trigger_type", "unknown"),
            "prompt": getattr(event, "prompt", ""),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        loop.call_soon_threadsafe(event_queue.put_nowait, data)

    from initrunner.services.operations import start_triggers_sync

    # Prevent duplicate dispatcher creation via sentinel
    with _dispatcher_lock:
        if role_id in _dispatchers:
            await websocket.send_json(
                {"type": "error", "data": {"message": "Daemon already running"}}
            )
            await websocket.close()
            return
        state = _DaemonState(status="starting")
        _dispatchers[role_id] = state

    try:
        dispatcher = await asyncio.wait_for(
            asyncio.to_thread(start_triggers_sync, role, on_event),
            timeout=BUILD_TIMEOUT,
        )
    except Exception:
        with _dispatcher_lock:
            if _dispatchers.get(role_id) is state:
                del _dispatchers[role_id]
        raise

    with _dispatcher_lock:
        if _dispatchers.get(role_id) is not state or state.cancel.is_set():
            # Cancelled during build
            stop_all = getattr(dispatcher, "stop_all", None)
            if stop_all is not None:
                try:
                    await asyncio.wait_for(asyncio.to_thread(stop_all), timeout=BUILD_TIMEOUT)
                except Exception:
                    _logger.exception("Error stopping cancelled WS dispatcher for %s", role_id)
            if _dispatchers.get(role_id) is state:
                del _dispatchers[role_id]
            await websocket.send_json({"type": "stopped"})
            await websocket.close()
            return
        state.dispatcher = dispatcher
        state.status = "running"

    await websocket.send_json({"type": "started"})

    try:
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                if event is not None:
                    await websocket.send_json({"type": "event", "data": event})
            except TimeoutError:
                # Send keepalive ping
                pass
    except WebSocketDisconnect:
        _logger.debug("Daemon WebSocket disconnected for role %s", role_id)
    finally:
        with _dispatcher_lock:
            if _dispatchers.get(role_id) is state:
                del _dispatchers[role_id]
        stop_all = getattr(dispatcher, "stop_all", None)
        if stop_all is not None:
            try:
                await asyncio.wait_for(asyncio.to_thread(stop_all), timeout=BUILD_TIMEOUT)
            except Exception:
                _logger.exception("Error stopping dispatcher for %s", role_id)
        try:
            await websocket.send_json({"type": "stopped"})
        except Exception:
            pass  # Client already gone
