"""Endpoint job: snapshot, aliran SSE, pembatalan, dan riwayat."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ..jobs import stream_events
from . import jobs_of

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def history(request: Request) -> dict[str, Any]:
    return {"jobs": jobs_of(request).history()}


@router.get("/{job_id}")
def snapshot(
    job_id: str,
    request: Request,
    include_log: bool = Query(default=True),
) -> dict[str, Any]:
    return jobs_of(request).snapshot(job_id, include_log=include_log)


@router.get("/{job_id}/stream")
def stream(
    job_id: str,
    request: Request,
    index: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """Aliran SSE: ``log`` per baris, lalu ``state`` dan ``end``."""
    job = jobs_of(request).get(job_id)
    return StreamingResponse(
        stream_events(job, index),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{job_id}/cancel")
def cancel(job_id: str, request: Request) -> dict[str, Any]:
    return jobs_of(request).cancel(job_id)
