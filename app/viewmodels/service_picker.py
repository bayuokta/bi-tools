"""Picker workspace/report Power BI Service untuk beberapa view model.

Katalog workspace dibaca dari SQLite (hasil ``run_workspace_sync``), sedangkan
daftar report diambil per workspace lewat Power BI REST. Fungsi di sini bebas
``QtWidgets`` supaya sub-tab Power BI Service dan sub-tab Generate TSD memakai
label, pesan, dan alur pemuatan yang sama.
"""

from __future__ import annotations

from typing import Any, Callable

from core.errors import ExtractionError
from core.lineage_api import PowerBILineageClient
from core.lineage_service import WorkspaceOption, workspace_options

EMPTY_CATALOG_HINT = (
    "Belum ada workspace tersimpan. Buka tab Pengaturan lalu jalankan "
    "Sinkronisasi workspace."
)
MISSING_CREDENTIALS = (
    "Kredensial service principal belum lengkap; isi di tab Pengaturan."
)
BUSY_MESSAGE = "Pekerjaan lain masih berjalan; muat ulang setelah selesai."


def workspace_picklist(
    database: str,
) -> tuple[tuple[WorkspaceOption, ...], set[str], str]:
    """``(options, nama duplikat, hint)`` dari katalog workspace di SQLite."""
    try:
        options = tuple(workspace_options(database))
    except ExtractionError as exc:
        return (), set(), f"Database katalog tidak bisa dibaca: {exc}"
    names = [option.name for option in options]
    duplicates = {name for name in set(names) if names.count(name) > 1}
    return options, duplicates, "" if options else EMPTY_CATALOG_HINT


def workspace_label(option: WorkspaceOption) -> str:
    """Label combo workspace: ``Nama (8 karakter ID)``."""
    return f"{option.name} ({option.workspace_id[:8]})"


def report_label(item: dict[str, Any]) -> str:
    """Label combo report: ``Nama (8 karakter ID)``.

    Nama report di Power BI tidak unik, jadi 8 karakter ID ikut ditampilkan
    seperti pada combo workspace. Report paginated ditandai karena tidak
    didukung untuk capture/ekstraksi PBIR.
    """
    name = str(item.get("name") or item.get("id") or "")
    report_id = str(item.get("id") or "")
    label = f"{name} ({report_id[:8]})" if report_id else name
    if is_paginated(item):
        return f"{label} [Paginated]"
    return label


def is_paginated(item: dict[str, Any]) -> bool:
    return str(item.get("reportType") or "") == "PaginatedReport"


def workspace_contents_job(
    principal: Any,
    workspace_id: str,
    *,
    datasets: bool,
    reports: bool,
) -> Callable[[Callable[[str], None]], dict[str, Any]]:
    """Job pembacaan dataset/report satu workspace (dijalankan ``JobRunner``)."""

    def job(log: Callable[[str], None]) -> dict[str, Any]:
        client = PowerBILineageClient(principal, log=log)
        try:
            payload: dict[str, Any] = {"workspace_id": workspace_id}
            payload["datasets"] = (
                client.datasets_in_group(workspace_id) if datasets else []
            )
            payload["reports"] = (
                client.reports_in_group(workspace_id) if reports else []
            )
            return payload
        finally:
            client.close()

    return job
