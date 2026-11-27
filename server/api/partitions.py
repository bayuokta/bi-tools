"""Endpoint Partisi: state, dataset, inventaris, dan refresh via XMLA."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core.errors import ExtractionError

from ..presenters import partitions as presenter
from . import settings_of, submit_job

router = APIRouter(prefix="/api/partitions", tags=["partitions"])


class InventoryIn(BaseModel):
    workspace_id: str = ""
    dataset_id: str = ""


class TargetIn(BaseModel):
    table: str = ""
    partition: str = ""


class RefreshIn(InventoryIn):
    targets: list[TargetIn] = Field(default_factory=list)
    refresh_type: str = "full"
    confirmation: str = ""


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    return presenter.build_state(settings_of(request))


@router.get("/workspaces/{workspace_id}/datasets")
def datasets(workspace_id: str, request: Request) -> dict[str, Any]:
    return presenter.datasets_payload(settings_of(request), workspace_id)


@router.post("/inventory", status_code=202)
def inventory(
    payload: InventoryIn, request: Request
) -> dict[str, Any]:
    store = settings_of(request)
    data = payload.model_dump()
    try:
        presenter.build_inventory_request(store, data)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return submit_job(
        request,
        "partitions-inventory",
        "Reading partition inventory",
        lambda log, cancel: presenter.run_inventory_job(store, data, log, cancel),
    )


@router.post("/refresh", status_code=202)
def refresh(payload: RefreshIn, request: Request) -> dict[str, Any]:
    store = settings_of(request)
    data = payload.model_dump()
    try:
        presenter.build_refresh_request(store, data)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return submit_job(
        request,
        "partitions-refresh",
        "Refresh partisi",
        lambda log, cancel: presenter.run_refresh_job(store, data, log, cancel),
    )
