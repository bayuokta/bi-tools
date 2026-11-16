"""Orkestrasi scan lineage Power BI Service ke SQLite."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .auth import ServicePrincipal
from .errors import ExtractionError
from .lineage_api import PowerBILineageClient, now_iso
from .lineage_store import (
    active_counts,
    close_quietly,
    connect,
    initialize,
    save,
    stats,
    unresolved_feed_sources,
)
from .lineage_transform import transform

BATCH_SIZE = 100
MEMBER_BATCH_SIZE = 20
Log = Callable[[str], None]


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


@dataclass(frozen=True)
class LineageScanResult:
    """Ringkasan satu kali scan lineage."""

    database: Path
    scan_id: str
    mode: str
    workspace_count: int
    node_count: int
    edge_count: int
    unresolved_sources: int
    started_at: str
    finished_at: str
    duration_seconds: float


def _record_failed_scan(
    conn: Any,
    mode: str,
    started_at: str,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO scan_run VALUES (?,?,?,?,?,?)",
        (
            f"failed-{uuid.uuid4()}",
            started_at,
            now_iso(),
            mode,
            0,
            "Failed",
        ),
    )
    conn.commit()


def _run_admin_scan(
    conn: Any,
    client: PowerBILineageClient,
    full: bool,
    progress: Log,
    started_at: str,
) -> str:
    last_scan = conn.execute(
        """SELECT MAX(started_at) FROM scan_run
           WHERE status='Succeeded' AND mode IN ('full','incremental')"""
    ).fetchone()[0]
    modified_since = None if (full or not last_scan) else last_scan
    scan_mode = "incremental" if modified_since else "full"

    workspace_ids = client.modified_workspaces(modified_since)
    progress(f"Mode {scan_mode}: {len(workspace_ids)} workspace akan di-scan")

    first_scan_id: str | None = None
    for offset in range(0, len(workspace_ids), BATCH_SIZE):
        batch = workspace_ids[offset : offset + BATCH_SIZE]
        scan_id, result = client.scan(batch)
        first_scan_id = first_scan_id or scan_id
        nodes, edges, datasources = transform(result)
        save(conn, scan_id, batch, nodes, edges, datasources)
        progress(
            f"Batch {offset // BATCH_SIZE + 1}: {len(nodes)} node, {len(edges)} edge"
        )

    resolved_id = first_scan_id or started_at
    conn.execute(
        "INSERT OR REPLACE INTO scan_run VALUES (?,?,?,?,?,?)",
        (
            resolved_id,
            started_at,
            now_iso(),
            scan_mode,
            len(workspace_ids),
            "Succeeded",
        ),
    )
    conn.commit()
    return resolved_id


def _run_member_scan(
    conn: Any,
    client: PowerBILineageClient,
    progress: Log,
    started_at: str,
) -> str:
    scan_id = f"member-{uuid.uuid4()}"
    workspaces = client.member_workspaces()
    progress(
        f"Mode member: {len(workspaces)} workspace yang dapat diakses service principal"
    )

    for offset in range(0, len(workspaces), MEMBER_BATCH_SIZE):
        chunk = workspaces[offset : offset + MEMBER_BATCH_SIZE]
        result = {
            "workspaces": [
                client.member_scan(workspace_id, name)
                for workspace_id, name in chunk
            ]
        }
        nodes, edges, datasources = transform(result)
        save(
            conn,
            scan_id,
            [workspace[0] for workspace in chunk],
            nodes,
            edges,
            datasources,
        )
        progress(
            f"{min(offset + MEMBER_BATCH_SIZE, len(workspaces))}/{len(workspaces)} "
            f"workspace, {len(nodes)} node, {len(edges)} edge"
        )

    conn.execute(
        "INSERT OR REPLACE INTO scan_run VALUES (?,?,?,?,?,?)",
        (scan_id, started_at, now_iso(), "member", len(workspaces), "Succeeded"),
    )
    conn.commit()
    return scan_id


def run_lineage_scan(
    database: Path | str,
    settings: ServicePrincipal,
    *,
    mode: str = "auto",
    full: bool = False,
    log: Log = _silent,
    client_factory: Callable[..., Any] | None = None,
) -> LineageScanResult:
    """Jalankan scan lineage dan simpan hasilnya ke database SQLite.

    Mode ``auto`` mencoba admin lebih dulu, lalu member bila akses admin ditolak.
    ``client_factory`` dipakai oleh uji untuk mengganti client REST.
    """
    if mode not in {"auto", "admin", "member"}:
        raise ExtractionError(f"Mode scan lineage tidak dikenal: {mode}")
    settings.validate()

    database_path = Path(database).expanduser().resolve()
    started_at = now_iso()
    clock = time.perf_counter()
    conn: Any | None = None
    client: Any | None = None
    resolved_mode = mode
    scan_id = ""
    try:
        conn = connect(database_path)
        initialize(conn)
        factory = client_factory or (
            lambda value, log=log: PowerBILineageClient(value, log=log)
        )
        client = factory(settings, log=log)

        if mode == "auto":
            resolved_mode = "admin" if client.probe_admin() else "member"
            log(f"Mode terpilih otomatis: {resolved_mode}")

        if resolved_mode == "admin":
            scan_id = _run_admin_scan(conn, client, full, log, started_at)
        elif resolved_mode == "member":
            if full:
                log(
                    "Mode member memindai seluruh workspace yang dapat diakses; "
                    "opsi full tidak mengubah hasil."
                )
            scan_id = _run_member_scan(conn, client, log, started_at)
        else:
            raise ExtractionError(f"Mode scan lineage tidak dikenal: {resolved_mode}")

        node_count, edge_count = active_counts(conn)
        summary = stats(conn)
        scan_row = conn.execute(
            "SELECT workspace_count FROM scan_run WHERE scan_id=?", (scan_id,)
        ).fetchone()
        workspace_count = int(scan_row[0] or 0) if scan_row else 0
        finished_at = now_iso()
        duration = time.perf_counter() - clock
        log("")
        log(f"Scan selesai    : {scan_id}")
        log(f"Mode            : {resolved_mode}")
        log(f"Node aktif      : {node_count}")
        log(f"Edge aktif      : {edge_count}")
        log(f"Scan terakhir   : {summary.get('last_scan') or '-'}")
        unresolved = unresolved_feed_sources(conn)
        if unresolved:
            log(
                f"WARNING: {unresolved} ID sumber belum memiliki metadata. "
                "Aktifkan detailed metadata untuk admin API lalu jalankan full scan."
            )
        return LineageScanResult(
            database=database_path,
            scan_id=scan_id,
            mode=resolved_mode,
            workspace_count=workspace_count,
            node_count=node_count,
            edge_count=edge_count,
            unresolved_sources=unresolved,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
        )
    except Exception as exc:
        if conn is not None:
            try:
                _record_failed_scan(conn, resolved_mode, started_at)
            except Exception:  # noqa: BLE001 - kegagalan awal tidak boleh menutupi error asli
                pass
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(f"Scan lineage gagal: {exc}") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        if conn is not None:
            close_quietly(conn)
