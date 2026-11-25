"""Endpoint status katalog workspace (read-only).

Sinkronisasi katalog dan scan lineage tidak lagi tersedia di aplikasi
interaktif: keduanya dijalankan program ``bi-tools-sync`` dengan service
principal, lalu hasilnya diunduh sebagai snapshot.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..presenters import settings as presenter
from . import settings_of

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    return presenter.catalog_status(settings_of(request))
