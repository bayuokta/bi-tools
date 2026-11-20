"""Endpoint ekstraksi metadata: instance, workspace, deteksi .pbix, dan job."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from core.errors import ExtractionError

from ..presenters import metadata as presenter
from . import settings_of, submit_job

router = APIRouter(prefix="/api/metadata", tags=["metadata"])


class RunIn(BaseModel):
    source: str = "local"
    scope: str = "both"
    out_dir: str = ""
    pbix: str = ""
    port: int | None = None
    catalog: str = ""
    workspace_id: str = ""
    workspace_name: str = ""
    model_workspace_id: str = ""
    model_workspace_name: str = ""
    report_workspace_id: str = ""
    report_workspace_name: str = ""
    report_id: str = ""
    report_ids: list[str] = []
    report_names: dict[str, str] = {}
    report_name: str = ""
    report_type: str = ""
    dataset_id: str = ""
    dataset_name: str = ""
    endpoint: str = ""


@router.get("/instances")
def instances() -> dict[str, Any]:
    return presenter.instances_payload()


@router.get("/pbix")
def pbix(path: str = Query(default="")) -> dict[str, Any]:
    return presenter.pbix_payload(path)


@router.get("/workspaces")
def workspaces(request: Request) -> dict[str, Any]:
    return presenter.workspaces_payload(settings_of(request))


@router.get("/workspaces/{workspace_id}/contents")
def contents(
    workspace_id: str,
    request: Request,
    datasets: bool = True,
    reports: bool = True,
) -> dict[str, Any]:
    return presenter.contents_payload(
        settings_of(request),
        workspace_id,
        datasets=datasets,
        reports=reports,
    )


@router.post("/run", status_code=202)
def run(payload: RunIn, request: Request) -> dict[str, Any]:
    store = settings_of(request)
    data = payload.model_dump()
    try:
        presenter.build_request(store, data)
    except ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return submit_job(
        request,
        "metadata",
        "Ekstraksi metadata",
        lambda log, cancel: presenter.run_job(store, data, log, cancel),
    )
