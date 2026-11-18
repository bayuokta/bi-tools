"""Presenter Lineage untuk web: pencarian, lineage dua arah, kanvas, ekspor."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.errors import ExtractionError
from core.lineage_layout import LayoutGraph, build_graph
from core.lineage_service import (
    database_summary,
    export_csv,
    node_detail,
    read_connection,
    search_nodes,
    two_way_lineage,
)
from core.lineage_store import DEFAULT_DB
from core.paths import outputs_dir

from ..settings_store import SettingsStore

DEFAULT_DEPTH = 3
MAX_DEPTH = 15
SEARCH_LIMIT = 100


def database_path(store: SettingsStore) -> Path:
    return Path(store.lineage_db() or DEFAULT_DB).expanduser()


def _node_types(database: Path) -> list[str]:
    if not database.exists():
        return []
    try:
        with read_connection(database) as conn:
            rows = conn.execute(
                "SELECT DISTINCT node_type FROM nodes "
                "WHERE is_active = 1 AND node_type <> '' ORDER BY node_type"
            ).fetchall()
    except Exception:  # noqa: BLE001 - katalog opsional
        return []
    return [str(row[0]) for row in rows]


def build_state(store: SettingsStore) -> dict[str, Any]:
    database = database_path(store)
    summary = database_summary(database)
    if not summary.exists:
        status = "Database belum ada. Jalankan Sinkronisasi data di Pengaturan."
    elif not summary.readable:
        status = f"Database tidak bisa dibaca: {summary.error}"
    else:
        status = f"{summary.items} item · {summary.workspaces} workspace"
    return {
        "database": str(database),
        "exists": summary.exists,
        "readable": summary.readable,
        "items": summary.items,
        "workspaces": summary.workspaces,
        "last_scan": summary.last_scan,
        "modified": summary.modified,
        "error": summary.error,
        "status": status,
        "node_types": _node_types(database),
        "depth": DEFAULT_DEPTH,
        "direction": "upstream",
    }


def search(
    store: SettingsStore,
    query: str,
    workspace: str = "",
    node_type: str = "",
    limit: int = SEARCH_LIMIT,
) -> dict[str, Any]:
    database = database_path(store)
    if not database_summary(database).readable:
        raise ExtractionError(
            "Database lineage belum siap. Jalankan Sinkronisasi data di Pengaturan."
        )
    text = str(query or "").strip()
    space = str(workspace or "").strip()
    kind = str(node_type or "").strip()
    if not text and not space and not kind:
        return {"results": [], "message": "Isi kata kunci atau filter terlebih dahulu."}
    rows = search_nodes(database, text, space, kind, limit=max(1, int(limit)))
    capped = len(rows) >= limit
    message = f"{len(rows)} hasil" + (
        " (batas tercapai; perjelas kata kunci)" if capped else ""
    )
    return {"results": rows, "message": message}


def _graph_payload(graph: LayoutGraph) -> dict[str, Any]:
    return {
        "root": graph.root.node_id,
        "truncated": int(graph.truncated),
        "nodes": [
            {
                "id": node.node_id,
                "type": node.node_type,
                "name": node.name,
                "workspace": node.workspace_name or "",
                "depth": node.depth,
                "column": node.column,
                "row": node.row,
                "side": node.side,
                "payload": node.payload,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "source": edge.source_id,
                "target": edge.target_id,
                "type": edge.edge_type,
            }
            for edge in graph.edges
        ],
    }


def node_payload(
    store: SettingsStore,
    node_id: str,
    direction: str = "upstream",
    depth: int = DEFAULT_DEPTH,
) -> dict[str, Any]:
    database = database_path(store)
    ident = str(node_id or "").strip()
    if not ident:
        raise ExtractionError("Node lineage belum dipilih.")
    depth = max(1, min(MAX_DEPTH, int(depth)))
    down, up = two_way_lineage(database, ident, depth)
    if down is None and up is None:
        raise ExtractionError(
            "Node tidak ditemukan di database lineage. Jalankan scan ulang."
        )
    selected = down if direction == "downstream" else up
    if selected is None:
        selected = {"root": (down or up or {}).get("root"), "nodes": []}
    detail = node_detail(database, ident) or selected.get("root") or {}
    graph = build_graph(downstream=down, upstream=up)
    return {
        "node": detail,
        "root": selected.get("root") or detail,
        "result": selected,
        "graph": _graph_payload(graph),
        "direction": "downstream" if direction == "downstream" else "upstream",
        "depth": depth,
        "upstream_count": len((up or {}).get("nodes") or []),
        "downstream_count": len((down or {}).get("nodes") or []),
        "truncated": int(graph.truncated),
    }


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._ -]+", "_", value or "").strip(" ._")
    return text[:80] or "lineage"


def export(
    store: SettingsStore,
    node_id: str,
    direction: str = "upstream",
    depth: int = DEFAULT_DEPTH,
) -> dict[str, Any]:
    payload = node_payload(store, node_id, direction, depth)
    result = payload["result"]
    root_name = str((result.get("root") or {}).get("name") or "lineage")
    target = outputs_dir() / f"Lineage_{_safe_name(root_name)}.csv"
    written = export_csv(target, result)
    return {
        "path": str(written),
        "size": written.stat().st_size if written.exists() else 0,
        "items": len(result.get("nodes") or []),
    }
