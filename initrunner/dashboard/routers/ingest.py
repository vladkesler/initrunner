"""Ingestion management routes -- document listing, upload, URL add, re-ingest."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import (  # type: ignore[import-not-found]
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import StreamingResponse  # type: ignore[import-not-found]

from initrunner.dashboard.deps import RoleCache, get_role_cache
from initrunner.dashboard.schemas import (
    AddUrlRequest,
    IngestDocumentResponse,
    IngestStatsResponse,
    IngestSummaryResponse,
)

router = APIRouter(prefix="/api/agents", tags=["ingest"])


def _resolve_role(agent_id: str, role_cache: RoleCache):
    """Resolve agent_id to a RoleDefinition or raise 404."""
    dr = role_cache.get(agent_id)
    if dr is None or dr.role is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if dr.role.spec.ingest is None:
        raise HTTPException(status_code=400, detail="Agent has no ingest configuration")
    return dr


async def _save_upload_capped(f: UploadFile, dest: Path, max_bytes: int) -> bool:
    """Stream *f* to *dest* in chunks, aborting if it exceeds *max_bytes*.

    Returns True on success, or False (deleting the partial file) when the
    upload is too large -- so a huge file is never fully buffered in memory.
    """
    total = 0
    chunk_size = 1024 * 1024
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    out.close()
                    dest.unlink(missing_ok=True)
                    return False
                out.write(chunk)
    except OSError:
        dest.unlink(missing_ok=True)
        raise
    return True


@router.get("/{agent_id}/ingest/documents")
async def list_documents(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> list[IngestDocumentResponse]:
    from initrunner.services.ingestion import list_ingested_documents_sync

    dr = _resolve_role(agent_id, role_cache)
    docs = await asyncio.to_thread(list_ingested_documents_sync, dr.role)
    return [
        IngestDocumentResponse(
            source=d.source,
            chunk_count=d.chunk_count,
            ingested_at=d.ingested_at,
            content_hash=d.content_hash,
            is_url=d.source.startswith("http://") or d.source.startswith("https://"),
            is_managed=d.is_managed,
        )
        for d in docs
    ]


@router.get("/{agent_id}/ingest/summary")
async def ingest_summary(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
) -> IngestSummaryResponse:
    from initrunner.services.ingestion import get_ingest_summary_sync

    dr = _resolve_role(agent_id, role_cache)
    info = await asyncio.to_thread(get_ingest_summary_sync, dr.role)
    return IngestSummaryResponse(
        total_documents=info.total_documents,
        total_chunks=info.total_chunks,
        store_path=info.store_path,
        sources_config=info.sources_config,
        managed_count=info.managed_count,
        last_ingested_at=info.last_ingested_at,
    )


@router.post("/{agent_id}/ingest/run")
async def run_ingestion(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    force: bool = Query(False),
) -> StreamingResponse:
    from pathlib import Path

    from initrunner.dashboard.streaming import stream_ingest_sse

    dr = _resolve_role(agent_id, role_cache)
    role_path = Path(dr.path)

    return StreamingResponse(
        stream_ingest_sse(role_path, force=force),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{agent_id}/ingest/upload")
async def upload_files(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    files: Annotated[list[UploadFile], File(...)],
) -> IngestStatsResponse:
    from pathlib import Path

    from initrunner.ingestion.manifest import uploads_dir
    from initrunner.services.ingestion import run_ingest_managed_sync

    dr = _resolve_role(agent_id, role_cache)
    role_path = Path(dr.path)
    upload_dir = uploads_dir(dr.role.metadata.name)

    max_mb = dr.role.spec.security.resources.max_file_size_mb
    max_bytes = int(max_mb * 1024 * 1024)

    saved: list[Path] = []
    for f in files:
        if not f.filename:
            continue
        safe_name = Path(f.filename).name
        if not safe_name:
            continue
        dest = (upload_dir / safe_name).resolve()
        if not dest.is_relative_to(upload_dir.resolve()):
            continue
        # Stream to disk with a hard byte ceiling instead of buffering the whole
        # upload, so an oversized file (or a decompression-bomb archive) cannot
        # exhaust server memory or bypass the role's max_file_size_mb limit.
        if not await _save_upload_capped(f, dest, max_bytes):
            raise HTTPException(
                status_code=413,
                detail=f"File '{safe_name}' exceeds the {max_mb} MB limit",
            )
        saved.append(dest)

    if not saved:
        raise HTTPException(status_code=400, detail="No valid files uploaded")

    stats = await asyncio.to_thread(run_ingest_managed_sync, dr.role, role_path, files=saved)
    if stats is None:
        raise HTTPException(status_code=400, detail="Ingestion not configured")

    return _stats_response(stats)


@router.post("/{agent_id}/ingest/add-url")
async def add_url(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    body: AddUrlRequest,
) -> IngestStatsResponse:
    from pathlib import Path

    from initrunner.services.ingestion import run_ingest_managed_sync

    dr = _resolve_role(agent_id, role_cache)
    role_path = Path(dr.path)

    stats = await asyncio.to_thread(run_ingest_managed_sync, dr.role, role_path, urls=[body.url])
    if stats is None:
        raise HTTPException(status_code=400, detail="Ingestion not configured")

    return _stats_response(stats)


@router.delete("/{agent_id}/ingest/documents")
async def delete_document(
    agent_id: str,
    role_cache: Annotated[RoleCache, Depends(get_role_cache)],
    source: str = Query(...),
) -> dict[str, int]:
    from initrunner.services.ingestion import delete_ingested_source_sync

    dr = _resolve_role(agent_id, role_cache)
    deleted = await asyncio.to_thread(delete_ingested_source_sync, dr.role, source)
    return {"chunks_deleted": deleted}


def _stats_response(stats) -> IngestStatsResponse:
    from initrunner.dashboard.schemas import IngestFileResultResponse

    return IngestStatsResponse(
        new=stats.new,
        updated=stats.updated,
        skipped=stats.skipped,
        errored=stats.errored,
        total_chunks=stats.total_chunks,
        file_results=[
            IngestFileResultResponse(
                path=str(r.path),
                status=str(r.status),
                chunks=r.chunks,
                error=r.error,
            )
            for r in stats.file_results
        ],
    )
