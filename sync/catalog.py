"""Sinkronisasi katalog workspace dan katalog report ke SQLite.

Hanya program sync yang memanggil modul ini; aplikasi interaktif membaca hasilnya
dari snapshot lewat :mod:`core.report_catalog` dan :mod:`core.lineage_service`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.auth import ServicePrincipal
from core.errors import ExtractionError
from core.lineage_store import (
    close_quietly,
    connect,
    initialize,
    save_workspace_sync_run,
    save_workspaces,
    workspace_sync_stats,
)
from core.report_catalog import save_report_catalog

from .admin_api import AdminClient, now_iso

Log = Callable[[str], None]
MODES = ("auto", "admin", "member")


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


@dataclass(frozen=True)
class WorkspaceSyncResult:
    """Ringkasan satu kali sinkronisasi katalog workspace."""

    database: Path
    sync_id: str
    mode: str
    workspace_count: int
    active_count: int
    added: int
    updated: int
    started_at: str
    finished_at: str
    duration_seconds: float


def _rows_for_member(client: Any) -> list[dict[str, Any]]:
    return [
        {"id": workspace_id, "name": name}
        for workspace_id, name in client.member_workspaces()
    ]


def run_workspace_sync(
    database: Path | str,
    settings: ServicePrincipal,
    *,
    mode: str = "auto",
    log: Log = _silent,
    client_factory: Callable[..., Any] | None = None,
) -> WorkspaceSyncResult:
    """Tarik daftar workspace dan simpan ke SQLite.

    ``client_factory`` dipakai uji untuk mengganti client REST tanpa network.
    """
    if mode not in MODES:
        raise ExtractionError(f"Unknown workspace sync mode: {mode}")
    settings.validate()

    database_path = Path(database).expanduser().resolve()
    started_at = now_iso()
    sync_id = f"ws-{uuid.uuid4()}"
    clock = time.perf_counter()
    conn: Any | None = None
    client: Any | None = None
    resolved_mode = mode
    workspace_count = 0
    try:
        conn = connect(database_path)
        initialize(conn)
        factory = client_factory or (
            lambda value, log=log: AdminClient(value, log=log)
        )
        client = factory(settings, log=log)

        if mode == "auto":
            resolved_mode = "admin" if client.probe_admin() else "member"
            log(f"Mode terpilih otomatis: {resolved_mode}")

        if resolved_mode == "admin":
            rows = client.admin_workspaces()
            log(f"{len(rows)} workspaces from the Admin API.")
        elif resolved_mode == "member":
            rows = _rows_for_member(client)
            log(
                f"{len(rows)} workspaces accessible to the service principal "
                "(mode member)."
            )
        else:
            raise ExtractionError(
                f"Unknown workspace sync mode: {resolved_mode}"
            )

        workspace_count = len(rows)
        added, updated = save_workspaces(
            conn, sync_id, rows, full=resolved_mode == "admin"
        )
        summary = workspace_sync_stats(conn)
        finished_at = now_iso()
        duration = time.perf_counter() - clock
        save_workspace_sync_run(
            conn,
            sync_id,
            started_at=started_at,
            finished_at=finished_at,
            mode=resolved_mode,
            workspace_count=workspace_count,
            active_count=summary["active"],
            status="Succeeded",
        )
        log("")
        log(f"Mode            : {resolved_mode}")
        log(
            f"Workspace       : {workspace_count} received, "
            f"{added} new, {updated} updated"
        )
        log(f"Workspace aktif : {summary['active']} (total {summary['total']})")
        return WorkspaceSyncResult(
            database=database_path,
            sync_id=sync_id,
            mode=resolved_mode,
            workspace_count=workspace_count,
            active_count=int(summary["active"]),
            added=added,
            updated=updated,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
        )
    except Exception as exc:
        if conn is not None:
            try:
                save_workspace_sync_run(
                    conn,
                    sync_id,
                    started_at=started_at,
                    finished_at=now_iso(),
                    mode=resolved_mode,
                    workspace_count=workspace_count,
                    active_count=0,
                    status="Failed",
                    message=str(exc)[:500],
                )
            except Exception:  # noqa: BLE001 - error asli tidak boleh tertutupi
                pass
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(f"Workspace sync failed: {exc}") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        if conn is not None:
            close_quietly(conn)


def sync_report_catalog(
    principal: Any,
    database: Path | str,
    *,
    full: bool = True,
    log: Log = _silent,
) -> int:
    """Tarik ``admin/reports`` lalu simpan ke tabel katalog bersama."""
    conn = connect(database)
    try:
        initialize(conn)
        client = AdminClient(principal, log=log)
        try:
            rows = client.admin_reports()
        finally:
            client.close()
        log(f"Reports from the Admin API: {len(rows)}")
        count = save_report_catalog(conn, rows, full=full)
        log(f"Report catalog saved: {count}")
        return count
    finally:
        conn.close()
