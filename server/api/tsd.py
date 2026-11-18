"""Endpoint Generate TSD: state, render, capture, cache, sidecar, preview."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core.errors import ExtractionError

from ..presenters import tsd as presenter
from . import settings_of, submit_job

router = APIRouter(prefix="/api/tsd", tags=["tsd"])


class ManualSaveIn(BaseModel):
    path: str = ""
    data: Any = None


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    return presenter.build_state(settings_of(request))


@router.post("/state")
def inspect(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return presenter.build_state(settings_of(request), payload or {})


@router.post("/run", status_code=202)
def run(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    store = settings_of(request)
    data = payload or {}
    try:
        presenter.build_request(store, presenter.normalize(store, data))
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return submit_job(
        request,
        "tsd",
        "Generate TSD",
        lambda log, cancel: presenter.run_job(store, data, log, cancel),
    )


@router.post("/capture", status_code=202)
def capture(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    store = settings_of(request)
    data = payload or {}
    try:
        presenter.build_capture_options(
            store, presenter.normalize(store, data), refresh=True
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return submit_job(
        request,
        "tsd_capture",
        "Ambil screenshot report",
        lambda log, cancel: presenter.capture_job(store, data, log, cancel),
    )


@router.post("/cache/clear")
def clear_cache(
    request: Request, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return presenter.clear_cache(settings_of(request), payload or {})


@router.get("/manual")
def manual(request: Request, path: str = Query(default="")) -> dict[str, Any]:
    store = settings_of(request)
    return presenter.manual_state(store, {"manual_path": path} if path else {})


@router.put("/manual")
def save_manual(payload: ManualSaveIn, request: Request) -> dict[str, Any]:
    return presenter.save_manual_file(
        settings_of(request), payload.path, payload.data if payload.data is not None else {}
    )


@router.get("/preview")
def preview(request: Request, path: str = Query(default="")) -> FileResponse:
    target = presenter.preview_path(settings_of(request), path)
    return FileResponse(
        target,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
                "font-src data:"
            ),
            "Cache-Control": "no-store",
        },
    )
