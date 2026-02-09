"""Ingestion endpoints — SSE-based progress streaming."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from initrunner.api._helpers import BUILD_TIMEOUT, resolve_role_path
from initrunner.api.models import IngestSourceResponse, IngestSourcesResponse

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.get("/{role_id}/sources", response_model=IngestSourcesResponse)
async def list_sources(role_id: str, request: Request):
    """List files that would be ingested for this role."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import load_role

    role = await asyncio.wait_for(asyncio.to_thread(load_role, role_path), timeout=BUILD_TIMEOUT)
    if role.spec.ingest is None:
        raise HTTPException(status_code=400, detail="No ingest config in this role")

    from initrunner.ingestion.pipeline import resolve_sources

    files, urls = await asyncio.to_thread(
        resolve_sources, role.spec.ingest.sources, base_dir=role_path.parent
    )

    sources = []
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        sources.append(IngestSourceResponse(path=str(f), name=f.name, size_bytes=size))
    for url in urls:
        sources.append(IngestSourceResponse(path=url, name=url, size_bytes=0))

    return IngestSourcesResponse(sources=sources)


@router.post("/{role_id}")
async def run_ingestion(
    role_id: str,
    request: Request,
    force: bool = Query(False, description="Force re-ingestion of all files"),
):
    """Run ingestion pipeline with SSE progress updates."""
    role_path = await resolve_role_path(request, role_id)

    from initrunner.agent.loader import load_role

    role = await asyncio.wait_for(asyncio.to_thread(load_role, role_path), timeout=BUILD_TIMEOUT)
    if role.spec.ingest is None:
        raise HTTPException(status_code=400, detail="No ingest config in this role")

    from initrunner.ingestion.pipeline import resolve_sources

    files, urls = await asyncio.to_thread(
        resolve_sources, role.spec.ingest.sources, base_dir=role_path.parent
    )
    total = len(files) + len(urls)

    async def event_stream():
        progress_queue: asyncio.Queue[dict | None] = asyncio.Queue(maxsize=500)
        loop = asyncio.get_event_loop()

        def on_progress(path: Path, status) -> None:
            try:
                loop.call_soon_threadsafe(
                    progress_queue.put_nowait,
                    {
                        "file": path.name,
                        "status": status.value if hasattr(status, "value") else str(status),
                    },
                )
            except asyncio.QueueFull:
                pass  # client is slow or gone, drop progress update

        def run_ingest():
            from initrunner.services import run_ingest_sync

            return run_ingest_sync(role, role_path, force=force, progress_callback=on_progress)

        ingest_task = asyncio.get_event_loop().run_in_executor(None, run_ingest)

        current = 0
        while not ingest_task.done():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                if event is not None:
                    current += 1
                    event["current"] = current
                    event["total"] = total
                    yield f"event: progress\ndata: {json.dumps(event)}\n\n"
            except TimeoutError:
                pass

        # Drain remaining events
        while not progress_queue.empty():
            event = progress_queue.get_nowait()
            if event is not None:
                current += 1
                event["current"] = current
                event["total"] = total
                yield f"event: progress\ndata: {json.dumps(event)}\n\n"

        try:
            stats = await ingest_task
            if stats is not None:
                done_data = {
                    "new": stats.new,
                    "updated": stats.updated,
                    "skipped": stats.skipped,
                    "errored": stats.errored,
                    "total_chunks": stats.total_chunks,
                }
                yield f"event: done\ndata: {json.dumps(done_data)}\n\n"
            else:
                yield f"event: done\ndata: {json.dumps({'total_chunks': 0})}\n\n"
        except RuntimeError as e:
            # Concurrent ingestion guard
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
