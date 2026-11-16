"""Sinkronisasi katalog workspace Power BI ke SQLite.

Hanya workspace yang disimpan; dataset dan report diambil saat dipilih di GUI
(lewat :class:`core.lineage_api.PowerBILineageClient`) supaya sinkronisasi tetap
1-2 request. Mode ``admin`` memakai ``admin/groups`` (seluruh tenant, atribut
lengkap) dan boleh menonaktifkan workspace yang tidak muncul lagi. Mode
``member`` hanya melihat workspace milik service principal, jadi tidak pernah
menonaktifkan apa pun.
"""

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
    close_quietly,
    connect,
    initialize,
    save_workspace_sync_run,
    save_workspaces,
    workspace_sync_stats,
)

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
        raise ExtractionError(f"Mode sinkronisasi workspace tidak dikenal: {mode}")
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
            lambda value, log=log: PowerBILineageClient(value, log=log)
        )
        client = factory(settings, log=log)

        if mode == "auto":
            resolved_mode = "admin" if client.probe_admin() else "member"
            log(f"Mode terpilih otomatis: {resolved_mode}")

        if resolved_mode == "admin":
            rows = client.admin_workspaces()
            log(f"{len(rows)} workspace dari Admin API.")
        elif resolved_mode == "member":
            rows = _rows_for_member(client)
            log(
                f"{len(rows)} workspace yang dapat diakses service principal "
                "(mode member)."
            )
        else:
            raise ExtractionError(
                f"Mode sinkronisasi workspace tidak dikenal: {resolved_mode}"
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
        log(f"Workspace       : {workspace_count} diterima, {added} baru, {updated} diperbarui")
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
        raise ExtractionError(f"Sinkronisasi workspace gagal: {exc}") from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
        if conn is not None:
            close_quietly(conn)
