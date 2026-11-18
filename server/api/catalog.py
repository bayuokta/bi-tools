"""Endpoint katalog workspace dan scan lineage (pekerjaan panjang)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..presenters import settings as presenter
from . import settings_of, submit_job

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


class ScanIn(BaseModel):
    full: bool = False


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    return presenter.catalog_status(settings_of(request))


@router.post("/sync", status_code=202)
def sync(request: Request) -> dict[str, Any]:
    store = settings_of(request)
    return submit_job(
        request,
        "catalog_sync",
        "Sinkronisasi katalog workspace",
        lambda log, cancel: presenter.sync_catalog_job(store, log, cancel),
    )


@router.post("/scan", status_code=202)
def scan(payload: ScanIn, request: Request) -> dict[str, Any]:
    store = settings_of(request)
    full = bool(payload.full)
    return submit_job(
        request,
        "lineage_scan",
        "Scan lineage Power BI",
        lambda log, cancel: presenter.scan_lineage_job(store, full, log, cancel),
    )
