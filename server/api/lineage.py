"""Endpoint Lineage: state, pencarian, detail/kanvas, ekspor CSV."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from ..presenters import lineage as presenter
from . import settings_of

router = APIRouter(prefix="/api/lineage", tags=["lineage"])


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    return presenter.build_state(settings_of(request))


@router.get("/search")
def search(
    request: Request,
    q: str = Query(default=""),
    workspace: str = Query(default=""),
    type: str = Query(default=""),
    limit: int = Query(default=presenter.SEARCH_LIMIT, ge=1, le=500),
) -> dict[str, Any]:
    return presenter.search(settings_of(request), q, workspace, type, limit)


@router.get("/node/{node_id}")
def node(
    node_id: str,
    request: Request,
    direction: str = Query(default="upstream"),
    depth: int = Query(default=presenter.DEFAULT_DEPTH, ge=1, le=presenter.MAX_DEPTH),
) -> dict[str, Any]:
    return presenter.node_payload(settings_of(request), node_id, direction, depth)


@router.post("/export")
def export(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload or {}
    return presenter.export(
        settings_of(request),
        str(data.get("node_id") or ""),
        str(data.get("direction") or "upstream"),
        int(data.get("depth") or presenter.DEFAULT_DEPTH),
    )
