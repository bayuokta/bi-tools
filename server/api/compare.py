"""Endpoint perbandingan semantic model (read-only)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi import APIRouter

from core.errors import ExtractionError
from core.requests import CompareRequest

from ..presenters import compare as presenter
from . import settings_of, submit_job

router = APIRouter(prefix="/api/compare", tags=["compare"])


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    return presenter.build_state(settings_of(request))


@router.post("/run", status_code=202)
def run(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    store = settings_of(request)
    try:
        CompareRequest.from_payload(payload or {})
        return submit_job(
            request,
            "compare",
            "Compare semantic model",
            lambda log, cancel: presenter.run_job(store, payload or {}, log, cancel),
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/export")
def export(request: Request) -> dict[str, Any]:
    try:
        return presenter.export_csv()
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/script")
def script(request: Request) -> dict[str, Any]:
    try:
        return presenter.generate_script()
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
