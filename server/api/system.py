"""Endpoint sistem: health, ringkasan runtime, dan berhenti server."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from core.paths import data_dir, outputs_dir
from core.version import APP_NAME, __version__

from ..config import web_dir

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health() -> dict[str, str]:
    """Used launcher untuk menunggu server siap (tanpa token)."""
    return {"status": "ok", "app": APP_NAME, "version": __version__}


@router.get("/api/system/state")
def system_state(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "app": APP_NAME,
        "version": __version__,
        "host": request.url.hostname,
        "port": request.url.port,
        "settings": settings.describe(),
        "data_dir": str(data_dir()),
        "outputs_dir": str(outputs_dir()),
        "web_dir": str(web_dir()),
        "shutdown_available": callable(getattr(request.app.state, "shutdown", None)),
    }


@router.post("/api/system/shutdown")
def shutdown(request: Request) -> dict[str, str]:
    """Hentikan server dari halaman Pengaturan."""
    callback = getattr(request.app.state, "shutdown", None)
    if not callable(callback):
        return {"status": "unavailable"}
    callback()
    return {"status": "stopping"}
