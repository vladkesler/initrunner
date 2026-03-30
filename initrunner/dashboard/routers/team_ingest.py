"""Team shared-document ingestion routes -- listing, upload, URL add, re-ingest."""

from __future__ import annotations

import asyncio
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

from initrunner.dashboard.deps import TeamCache, get_team_cache
from initrunner.dashboard.schemas import (
    AddUrlRequest,
    IngestDocumentResponse,
    IngestStatsResponse,
    IngestSummaryResponse,
)

router = APIRouter(prefix="/api/teams", tags=["team-ingest"])


def _resolve_team(team_id: str, team_cache: TeamCache):
    """Return (DiscoveredTeam, ingest-capable RoleDefinition) or raise."""
    from initrunner.team.stores import resolve_team_ingest_role

    dt = team_cache.get(team_id)
    if dt is None or dt.team is None:
        raise HTTPException(status_code=404, detail="Team not found")

    role = resolve_team_ingest_role(dt.team)
    if role is None:
        raise HTTPException(status_code=400, detail="Team has no shared documents enabled")
    return dt, role


@router.get("/{team_id}/ingest/documents")
async def list_documents(
    team_id: str,
    team_cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> list[IngestDocumentResponse]:
    from initrunner.services.ingestion import list_ingested_documents_sync

    _, role = _resolve_team(team_id, team_cache)
    docs = await asyncio.to_thread(list_ingested_documents_sync, role)
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


@router.get("/{team_id}/ingest/summary")
async def ingest_summary(
    team_id: str,
    team_cache: Annotated[TeamCache, Depends(get_team_cache)],
) -> IngestSummaryResponse:
    from initrunner.services.ingestion import get_ingest_summary_sync

    _, role = _resolve_team(team_id, team_cache)
    info = await asyncio.to_thread(get_ingest_summary_sync, role)
    return IngestSummaryResponse(
        total_documents=info.total_documents,
        total_chunks=info.total_chunks,
        store_path=info.store_path,
        sources_config=info.sources_config,
        managed_count=info.managed_count,
        last_ingested_at=info.last_ingested_at,
    )


@router.post("/{team_id}/ingest/run")
async def run_ingestion(
    team_id: str,
    team_cache: Annotated[TeamCache, Depends(get_team_cache)],
    force: bool = Query(False),
) -> StreamingResponse:
    from initrunner.dashboard.streaming import stream_team_ingest_sse

    dt = team_cache.get(team_id)
    if dt is None or dt.team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if not dt.team.spec.shared_documents.enabled:
        raise HTTPException(status_code=400, detail="Team has no shared documents enabled")

    team_dir = dt.path.parent
    return StreamingResponse(
        stream_team_ingest_sse(dt.team, team_dir, force=force),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{team_id}/ingest/upload")
async def upload_files(
    team_id: str,
    team_cache: Annotated[TeamCache, Depends(get_team_cache)],
    files: Annotated[list[UploadFile], File(...)],
) -> IngestStatsResponse:
    from pathlib import Path

    from initrunner.ingestion.manifest import uploads_dir
    from initrunner.services.ingestion import run_ingest_managed_sync

    dt, role = _resolve_team(team_id, team_cache)
    upload_dir = uploads_dir(dt.team.metadata.name)  # type: ignore[union-attr]

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
        content = await f.read()
        await asyncio.to_thread(dest.write_bytes, content)
        saved.append(dest)

    if not saved:
        raise HTTPException(status_code=400, detail="No valid files uploaded")

    stats = await asyncio.to_thread(run_ingest_managed_sync, role, dt.path, files=saved)
    if stats is None:
        raise HTTPException(status_code=400, detail="Ingestion not configured")

    return _stats_response(stats)


@router.post("/{team_id}/ingest/add-url")
async def add_url(
    team_id: str,
    team_cache: Annotated[TeamCache, Depends(get_team_cache)],
    body: AddUrlRequest,
) -> IngestStatsResponse:
    from initrunner.services.ingestion import run_ingest_managed_sync

    dt, role = _resolve_team(team_id, team_cache)
    stats = await asyncio.to_thread(run_ingest_managed_sync, role, dt.path, urls=[body.url])
    if stats is None:
        raise HTTPException(status_code=400, detail="Ingestion not configured")

    return _stats_response(stats)


@router.delete("/{team_id}/ingest/documents")
async def delete_document(
    team_id: str,
    team_cache: Annotated[TeamCache, Depends(get_team_cache)],
    source: str = Query(...),
) -> dict[str, int]:
    from initrunner.services.ingestion import delete_ingested_source_sync

    _, role = _resolve_team(team_id, team_cache)
    deleted = await asyncio.to_thread(delete_ingested_source_sync, role, source)
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
