"""Picker workspace/report untuk API web.

Katalog workspace dibaca dari SQLite hasil sinkronisasi; daftar dataset/report
diambil per workspace lewat Power BI REST saat workspace dipilih.
"""

from __future__ import annotations

from typing import Any, Callable

from core.errors import ExtractionError
from core.lineage_api import PowerBILineageClient
from core.lineage_service import WorkspaceOption, workspace_options

EMPTY_CATALOG_HINT = (
    "No saved workspace yet. Open Settings and run "
    "Workspace catalog sync."
)
MISSING_CREDENTIALS = (
    "Not signed in or credentials are incomplete; open Settings."
)


def workspace_picklist(
    database: str,
) -> tuple[tuple[WorkspaceOption, ...], set[str], str]:
    """``(options, nama duplikat, hint)`` dari katalog workspace."""
    try:
        options = tuple(workspace_options(database))
    except ExtractionError as exc:
        return (), set(), f"Catalog database could not be read: {exc}"
    names = [option.name for option in options]
    duplicates = {name for name in set(names) if names.count(name) > 1}
    return options, duplicates, "" if options else EMPTY_CATALOG_HINT


def workspace_label(option: WorkspaceOption) -> str:
    return f"{option.name} ({option.workspace_id[:8]})"


def report_label(item: dict[str, Any]) -> str:
    name = str(item.get("name") or item.get("id") or "")
    report_id = str(item.get("id") or "")
    label = f"{name} ({report_id[:8]})" if report_id else name
    return f"{label} [Paginated]" if is_paginated(item) else label


def is_paginated(item: dict[str, Any]) -> bool:
    return str(item.get("reportType") or "") == "PaginatedReport"


def workspace_contents(
    principal: Any,
    workspace_id: str,
    *,
    datasets: bool,
    reports: bool,
) -> dict[str, Any]:
    """Baca dataset/report satu workspace; dipanggil dari thread request."""
    client = PowerBILineageClient(principal)
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


def contents_loader(
    principal: Any,
    workspace_id: str,
    *,
    datasets: bool,
    reports: bool,
) -> Callable[[], dict[str, Any]]:
    """Pembungkus agar mudah diganti di uji."""
    return lambda: workspace_contents(
        principal, workspace_id, datasets=datasets, reports=reports
    )
