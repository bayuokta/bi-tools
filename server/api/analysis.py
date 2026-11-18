"""Endpoint Analisa Semantic Model: state, dataset, snapshot, run, export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from core.errors import ExtractionError

from ..presenters import analysis as presenter
from . import settings_of, submit_job

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    return presenter.build_state(settings_of(request))


@router.get("/workspaces/{workspace_id}/datasets")
def datasets(workspace_id: str, request: Request) -> dict[str, Any]:
    return presenter.datasets_payload(settings_of(request), workspace_id)


@router.get("/snapshot")
def snapshot(request: Request, dataset_id: str = Query(default="")) -> dict[str, Any]:
    return presenter.snapshot_payload(settings_of(request), dataset_id)


@router.post("/run", status_code=202)
def run(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    store = settings_of(request)
    data = payload or {}
    if not data.get("workspace_id") or not data.get("dataset_id"):
        raise HTTPException(
            status_code=400, detail="Pilih workspace dan semantic model dulu."
        )
    try:
        store.principal().validate()
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return submit_job(
        request,
        "analysis",
        "Analisa Semantic Model",
        lambda log, cancel: presenter.run_job(store, data, log, cancel),
    )


@router.post("/preferences")
def preferences(
    request: Request, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return presenter.save_preferences(settings_of(request), payload or {})


@router.post("/export")
def export(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return presenter.export(payload or {}, settings_of(request))
