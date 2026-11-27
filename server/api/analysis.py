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


@router.get("/report-detail")
def report_detail(
    request: Request,
    dataset_id: str = Query(default=""),
    report_id: str = Query(default=""),
) -> dict[str, Any]:
    return presenter.report_detail_payload(settings_of(request), dataset_id, report_id)


@router.get("/lineage")
def lineage(
    request: Request,
    dataset_id: str = Query(default=""),
    kind: str = Query(default="column"),
    table: str = Query(default=""),
    name: str = Query(default=""),
    direction: str = Query(default="both"),
    depth: int = Query(default=4, ge=1, le=8),
    category: str = Query(default="all"),
    outline_mode: str = Query(default="compact"),
) -> dict[str, Any]:
    return presenter.lineage_payload(
        settings_of(request),
        dataset_id,
        kind,
        table,
        name,
        direction=direction,
        depth=depth,
        category=category,
        outline_mode=outline_mode,
    )


@router.post("/lineage/export")
def lineage_export(
    request: Request, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return presenter.export_lineage(settings_of(request), payload or {})


@router.post("/lineage/image")
def lineage_image(
    request: Request, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return presenter.export_lineage_image(settings_of(request), payload or {})


@router.post("/dependencies/export")
def dependencies_export(
    request: Request, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    return presenter.export_dependencies(settings_of(request), payload or {})


@router.get("/details")
def details(
    request: Request,
    dataset_id: str = Query(default=""),
    kind: str = Query(default="column"),
    table: str = Query(default=""),
    name: str = Query(default=""),
) -> dict[str, Any]:
    return presenter.details_payload(
        settings_of(request), dataset_id, kind, table, name
    )


@router.post("/preview", status_code=202)
def preview(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    store = settings_of(request)
    data = payload or {}
    dataset_id = str(data.get("dataset_id") or "").strip()
    table = str(data.get("table") or "").strip()
    name = str(data.get("name") or "").strip()
    kind = str(data.get("kind") or "column").strip().lower()
    if not dataset_id or not table or not name:
        raise HTTPException(
            status_code=400, detail="Select a column or measure first."
        )
    if kind not in {"column", "measure"}:
        raise HTTPException(status_code=400, detail="Item type must be column/measure.")
    limit = data.get("limit", 100)
    return submit_job(
        request,
        "analysis-preview",
        "Preview values",
        lambda log, cancel: presenter.preview_payload(
            store, dataset_id, kind, table, name, limit=limit
        ),
    )


@router.post("/raw-metadata", status_code=202)
def raw_metadata(
    request: Request, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    store = settings_of(request)
    data = payload or {}
    dataset_id = str(data.get("dataset_id") or "").strip()
    table = str(data.get("table") or "").strip()
    name = str(data.get("name") or "").strip()
    kind = str(data.get("kind") or "column").strip().lower()
    if not dataset_id or not table or not name:
        raise HTTPException(
            status_code=400, detail="Select a column or measure first."
        )
    if kind not in {"column", "measure"}:
        raise HTTPException(status_code=400, detail="Item type must be column/measure.")
    return submit_job(
        request,
        "analysis-raw-metadata",
        "Raw metadata",
        lambda log, cancel: presenter.raw_metadata_payload(
            store, dataset_id, kind, table, name
        ),
    )


@router.post("/run", status_code=202)
def run(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    store = settings_of(request)
    data = payload or {}
    if not data.get("workspace_id") or not data.get("dataset_id"):
        raise HTTPException(
            status_code=400, detail="Choose a workspace and semantic model first."
        )
    try:
        store.auth().validate()
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
