"""Endpoint halaman Backup (read-only ke Power BI, tulis ke folder lokal)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from core.errors import ExtractionError
from core.requests import BackupRequest, RestoreRequest

from ..presenters import backup as presenter
from . import settings_of, submit_job

router = APIRouter(prefix="/api/backup", tags=["backup"])


@router.get("/state")
def state(request: Request, folder: str = Query(default="")) -> dict[str, Any]:
    try:
        return presenter.build_state(settings_of(request), folder)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/workspaces/{workspace_id}/items")
def items(workspace_id: str, request: Request) -> dict[str, Any]:
    try:
        return presenter.workspace_items(settings_of(request), workspace_id)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/run", status_code=202)
def run(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    store = settings_of(request)
    try:
        BackupRequest.from_payload(payload or {})
        return submit_job(
            request,
            "backup",
            "Backup model & report",
            lambda log, cancel: presenter.run_job(store, payload or {}, log, cancel),
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/restore/state")
def restore_state(
    request: Request,
    folder: str = Query(default=""),
    workspace_id: str = Query(default=""),
) -> dict[str, Any]:
    try:
        return presenter.restore_state(settings_of(request), folder, workspace_id)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/restore/run", status_code=202)
def restore_run(
    request: Request, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    store = settings_of(request)
    try:
        RestoreRequest.from_payload(payload or {})
        return submit_job(
            request,
            "restore",
            "Restore model & report",
            lambda log, cancel: presenter.restore_job(
                store, payload or {}, log, cancel
            ),
        )
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
