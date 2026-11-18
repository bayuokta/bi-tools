"""Endpoint API server web."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException, Request

from ..jobs import BusyError, Job, JobManager
from ..settings_store import SettingsStore


def settings_of(request: Request) -> SettingsStore:
    return request.app.state.settings


def jobs_of(request: Request) -> JobManager:
    return request.app.state.jobs


def submit_job(
    request: Request,
    kind: str,
    label: str,
    func: Callable[..., Any],
) -> dict[str, Any]:
    """Mulai pekerjaan atau jawab 409 bila masih ada yang berjalan."""
    manager = jobs_of(request)
    try:
        job: Job = manager.submit(kind, func, label=label)
    except BusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "job_id": job.id,
        "kind": job.kind,
        "label": job.label,
        "status": job.status,
    }
