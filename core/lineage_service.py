"""Akses baca database lineage untuk GUI dan CLI.

Semua fungsi membuka koneksi read-only sendiri (``open_read_only``) lalu
menutupnya, dan menerjemahkan ``sqlite3.Error`` menjadi :class:`ExtractionError`.
Widget dan view model tidak boleh menyentuh ``sqlite3`` atau SQL langsung.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .errors import ExtractionError
from .lineage_export import write_lineage_csv
from .lineage_layout import LayoutGraph, build_graph
from .lineage_store import (
    close_quietly,
    lineage,
    node_info,
    open_read_only,
    search,
    stats,
    workspace_by_id,
    workspace_by_name,
    workspace_list,
    workspace_sync_stats,
)

DEFAULT_SEARCH_LIMIT = 300


@dataclass(frozen=True)
class DatabaseSummary:
    """Ringkasan database lineage untuk label status."""

    path: Path
    exists: bool
    readable: bool
    items: int = 0
    workspaces: int = 0
    last_scan: str = ""
    modified: str = ""
    error: str = ""


@contextmanager
def read_connection(database: Path | str) -> Iterator[sqlite3.Connection]:
    """Koneksi read-only dengan penutupan otomatis dan error seragam."""
    path = Path(database).expanduser()
    conn = open_read_only(path)
    try:
        yield conn
    except sqlite3.Error as exc:
        raise ExtractionError(
            f"Database lineage tidak bisa dibaca: {path} ({exc})"
        ) from exc
    finally:
        close_quietly(conn)


def database_summary(database: Path | str) -> DatabaseSummary:
    """Baca jumlah node, workspace, scan terakhir, dan waktu file."""
    path = Path(database).expanduser()
    if not path.exists():
        return DatabaseSummary(path=path, exists=False, readable=False)
    try:
        with read_connection(path) as conn:
            data = stats(conn)
        modified = datetime.fromtimestamp(path.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M"
        )
    except (ExtractionError, OSError) as exc:
        return DatabaseSummary(
            path=path, exists=True, readable=False, error=str(exc)
        )

    counts = {
        str(item["node_type"]): int(item["n"] or 0)
        for item in data.get("types", [])
    }
    workspaces = counts.get("Workspace", 0)
    items = sum(count for name, count in counts.items() if name != "Workspace")
    return DatabaseSummary(
        path=path,
        exists=True,
        readable=True,
        items=items,
        workspaces=workspaces,
        last_scan=str(data.get("last_scan") or ""),
        modified=modified,
    )


@dataclass(frozen=True)
class WorkspaceOption:
    """Satu workspace hasil sinkronisasi katalog, untuk picker GUI/CLI."""

    workspace_id: str
    name: str
    state: str = ""
    type: str = ""
    capacity_id: str = ""
    is_active: bool = True

    @property
    def label(self) -> str:
        return self.name or self.workspace_id


def _option(row: dict[str, Any]) -> WorkspaceOption:
    return WorkspaceOption(
        workspace_id=str(row.get("workspace_id") or ""),
        name=str(row.get("name") or ""),
        state=str(row.get("state") or ""),
        type=str(row.get("type") or ""),
        capacity_id=str(row.get("capacity_id") or ""),
        is_active=bool(row.get("is_active", 1)),
    )


@contextmanager
def _workspace_connection(database: Path | str) -> Iterator[sqlite3.Connection]:
    """Koneksi read-only untuk tabel katalog (database harus sudah ada)."""
    with read_connection(database) as conn:
        yield conn


def workspace_options(
    database: Path | str,
    *,
    active_only: bool = True,
    include_personal: bool = False,
) -> list[WorkspaceOption]:
    """Daftar workspace tersimpan; kosong bila database/belum pernah sinkron."""
    path = Path(database).expanduser()
    if not path.exists():
        return []
    with _workspace_connection(path) as conn:
        try:
            rows = workspace_list(
                conn, active_only=active_only, include_personal=include_personal
            )
        except sqlite3.OperationalError:
            return []
    return [_option(row) for row in rows]


def workspace_lookup(database: Path | str, name: str) -> list[WorkspaceOption]:
    """Cari workspace berdasarkan nama (bisa lebih dari satu bila duplikat)."""
    path = Path(database).expanduser()
    if not path.exists():
        return []
    with _workspace_connection(path) as conn:
        try:
            rows = workspace_by_name(conn, name)
        except sqlite3.OperationalError:
            return []
    return [_option(row) for row in rows]


def workspace_detail(
    database: Path | str, workspace_id: str
) -> WorkspaceOption | None:
    path = Path(database).expanduser()
    if not path.exists():
        return None
    with _workspace_connection(path) as conn:
        try:
            row = workspace_by_id(conn, workspace_id)
        except sqlite3.OperationalError:
            return None
    return _option(row) if row else None


def node_detail(database: Path | str, node_id: str) -> dict[str, Any] | None:
    """Satu node (dataset/report) dari hasil scan lineage."""
    path = Path(database).expanduser()
    if not path.exists() or not node_id:
        return None
    with read_connection(path) as conn:
        try:
            rows = node_info(conn, [node_id])
        except sqlite3.OperationalError:
            return None
    return rows.get(str(node_id))


def workspace_status(database: Path | str) -> dict[str, Any]:
    """Ringkasan katalog workspace untuk label status tab Pengaturan."""
    path = Path(database).expanduser()
    empty = {
        "total": 0,
        "active": 0,
        "selectable": 0,
        "last_sync": "",
        "last_mode": "",
    }
    if not path.exists():
        return empty
    with _workspace_connection(path) as conn:
        try:
            return workspace_sync_stats(conn)
        except sqlite3.OperationalError:
            return empty


def search_nodes(
    database: Path | str,
    query: str = "",
    workspace: str = "",
    node_type: str = "",
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[dict[str, Any]]:
    with read_connection(database) as conn:
        return search(conn, query, workspace, node_type, limit=limit)


def reports_using_dataset(
    database: Path | str, dataset_id: str
) -> list[dict[str, Any]]:
    """Report yang memakai dataset menurut scan lineage.

    Dipakai analisa kolom sebagai pelengkap katalog snapshot ``report_catalog``.
    Hasil bisa lebih lama dari katalog hasil sync; pemanggil mencatat sumber
    daftar report agar cakupan transparan.
    """
    path = Path(database).expanduser()
    if not path.exists() or not dataset_id:
        return []
    with read_connection(path) as conn:
        try:
            rows = conn.execute(
                """
                SELECT n.node_id AS report_id, n.name AS name,
                       n.workspace_id AS workspace_id,
                       n.last_modified_at AS modified_at
                  FROM edges e
                  JOIN nodes n ON n.node_id = e.target_id
                 WHERE e.edge_type = 'uses_dataset'
                   AND e.source_id = ?
                   AND e.is_active = 1
                 ORDER BY n.name
                """,
                (str(dataset_id),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(row) for row in rows]


def node_lineage(
    database: Path | str,
    node_id: str,
    direction: str = "downstream",
    max_depth: int = 15,
) -> dict[str, Any] | None:
    with read_connection(database) as conn:
        return lineage(conn, node_id, direction, max_depth=max_depth)


def two_way_lineage(
    database: Path | str,
    node_id: str,
    max_depth: int = 15,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Telusuri downstream dan upstream dalam satu koneksi (untuk kanvas)."""
    with read_connection(database) as conn:
        downstream = lineage(conn, node_id, "downstream", max_depth=max_depth)
        upstream = lineage(conn, node_id, "upstream", max_depth=max_depth)
    return downstream, upstream


def graph_for(
    database: Path | str, node_id: str, max_depth: int = 15
) -> LayoutGraph:
    """Susun graph dua arah untuk kanvas visual lineage."""
    downstream, upstream = two_way_lineage(database, node_id, max_depth)
    return build_graph(downstream=downstream, upstream=upstream)


def export_csv(target: Path | str, result: dict[str, Any]) -> Path:
    """Tulis lineage satu arah ke CSV; error OSError diteruskan ke pemanggil."""
    return write_lineage_csv(Path(target), result)
