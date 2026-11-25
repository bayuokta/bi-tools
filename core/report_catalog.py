"""Katalog report per dataset untuk database bersama (hasil program sync).

Aplikasi interaktif tidak boleh memanggil Admin API. Program sync mengisi tabel
``report_catalog`` sekali, lalu Analisa membaca daftar report dari snapshot
SQLite. Definisi report tetap diunduh langsung oleh aplikasi user.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .lineage_api import PowerBILineageClient

REPORT_COLUMNS = (
    "report_id",
    "workspace_id",
    "dataset_id",
    "name",
    "report_type",
    "report_format",
    "modified_at",
    "is_personal",
    "is_app",
    "is_supported",
    "is_active",
    "synced_at",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_format(value: Any, report_type: str = "") -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if report_type == "PaginatedReport" or "rdl" in lowered or "paginated" in lowered:
        return "RDL"
    if lowered in {"pbir", "pbir-legacy", "pbirlegacy"}:
        return "PBIR-Legacy" if lowered != "pbir" else "PBIR"
    return text


def _is_app(name: str) -> bool:
    cleaned = (
        str(name or "")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\ufeff", "")
        .strip()
        .lower()
    )
    return cleaned.startswith("[app]")


def _workspace_info(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT workspace_id, name, type FROM workspace").fetchall()
    return {
        str(row["workspace_id"]): {
            "name": str(row["name"] or ""),
            "type": str(row["type"] or ""),
        }
        for row in rows
    }


def _is_personal(workspace: dict[str, Any] | None) -> bool:
    if not workspace:
        return False
    kind = str(workspace.get("type") or "")
    if kind in {"Personal", "PersonalGroup"}:
        return True
    name = str(workspace.get("name") or "").casefold()
    return name.startswith("personalworkspace ") or name.startswith("my workspace")


def save_report_catalog(
    conn: sqlite3.Connection,
    rows: Iterable[dict[str, Any]],
    *,
    full: bool = True,
    synced_at: str = "",
) -> int:
    """Simpan katalog report; ``full`` menonaktifkan report yang tidak muncul."""
    stamp = synced_at or _now()
    workspaces = _workspace_info(conn)
    if full:
        conn.execute("UPDATE report_catalog SET is_active = 0")
    seen: set[str] = set()
    written = 0
    for row in rows:
        report_id = str(row.get("report_id") or row.get("id") or "").strip()
        if not report_id:
            continue
        workspace_id = str(
            row.get("workspace_id") or row.get("workspaceId") or ""
        ).strip()
        name = str(row.get("name") or "")
        report_type = str(row.get("report_type") or row.get("reportType") or "")
        report_format = _normalize_format(
            row.get("report_format") or row.get("format"), report_type
        )
        dataset_id = str(row.get("dataset_id") or row.get("datasetId") or "").strip()
        modified = str(
            row.get("modified_at") or row.get("modifiedDateTime") or ""
        ).strip()
        workspace = workspaces.get(workspace_id)
        personal = 1 if _is_personal(workspace) else 0
        app = 1 if _is_app(name) else 0
        supported = 0 if report_format == "RDL" else 1
        conn.execute(
            """
            INSERT INTO report_catalog (
                report_id, workspace_id, dataset_id, name, report_type,
                report_format, modified_at, is_personal, is_app, is_supported,
                is_active, synced_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?)
            ON CONFLICT(report_id) DO UPDATE SET
                workspace_id=excluded.workspace_id,
                dataset_id=excluded.dataset_id,
                name=excluded.name,
                report_type=excluded.report_type,
                report_format=excluded.report_format,
                modified_at=excluded.modified_at,
                is_personal=excluded.is_personal,
                is_app=excluded.is_app,
                is_supported=excluded.is_supported,
                is_active=1,
                synced_at=excluded.synced_at
            """,
            (
                report_id,
                workspace_id,
                dataset_id,
                name,
                report_type,
                report_format,
                modified,
                personal,
                app,
                supported,
                stamp,
            ),
        )
        seen.add(report_id)
        written += 1
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('report_catalog_synced_at', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (stamp,),
    )
    conn.commit()
    return written


def catalog_reports(
    database: Path | str, dataset_id: str
) -> list[dict[str, Any]]:
    """Baca report aktif untuk satu dataset dari snapshot read-only."""
    path = Path(database).expanduser()
    if not path.exists() or not dataset_id:
        return []
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                """
                SELECT report_id, workspace_id, dataset_id, name, report_type,
                       report_format, modified_at, is_personal, is_app,
                       is_supported
                  FROM report_catalog
                 WHERE dataset_id = ? AND is_active = 1
                 ORDER BY name, report_id
                """,
                (str(dataset_id),),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()
    return [dict(row) for row in rows]


def sync_report_catalog(
    principal: Any,
    database: Path | str,
    *,
    full: bool = True,
    log: Any = None,
) -> int:
    """Tarik ``admin/reports`` lalu simpan ke tabel katalog.

    Dipanggil hanya oleh program sync (service principal dengan peran Fabric
    administrator). Tidak dipakai oleh server interaktif.
    """
    log = log or (lambda _message: None)
    from .lineage_store import connect, initialize

    conn = connect(database)
    try:
        initialize(conn)
        client = PowerBILineageClient(principal, log=log)
        try:
            rows = client.admin_reports()
        finally:
            client.close()
        log(f"Report dari Admin API: {len(rows)}")
        count = save_report_catalog(conn, rows, full=full)
        log(f"Katalog report disimpan: {count}")
        return count
    finally:
        conn.close()
