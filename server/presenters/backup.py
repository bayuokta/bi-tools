"""Presenter halaman Backup: sumber, item, jalankan job, riwayat."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.backup import (
    BackupOptions,
    default_folder,
    history,
    run_backup,
    safe_name,
)
from core.errors import ExtractionError
from core.lineage_service import workspace_detail
from core.requests import BackupRequest
from core.version import __version__

from .. import settings as keys
from ..shared_db import active_database_path
from ..settings_store import SettingsStore
from .service_picker import workspace_label, workspace_picklist

MAX_HISTORY = 10


def _database(store: SettingsStore) -> str:
    return str(active_database_path(store))


def _folder(store: SettingsStore, value: str = "") -> Path:
    text = str(value or "").strip().strip('"')
    if text:
        folder = Path(text).expanduser()
        if not folder.is_absolute():
            raise ExtractionError("Folder backup harus absolut.")
        return folder
    saved = store.get_str(keys.BACKUP_FOLDER_KEY)
    if saved:
        return Path(saved).expanduser()
    return default_folder()


def build_state(store: SettingsStore, folder: str = "") -> dict[str, Any]:
    """Pilihan workspace, folder, dan riwayat backup."""
    options, _duplicates, hint = workspace_picklist(_database(store))
    try:
        target = _folder(store, folder)
    except ExtractionError as exc:
        target = default_folder()
        hint = str(exc)
    prefix = store.get_str(keys.BACKUP_PREFIX_KEY) or "Backup"
    return {
        "mode": "user",
        "version": __version__,
        "workspaces": [
            {
                "id": option.workspace_id,
                "name": option.name,
                "label": workspace_label(option),
            }
            for option in options
        ],
        "hint": hint,
        "folder": str(target),
        "prefix": prefix,
        "history": history(target, limit=MAX_HISTORY),
    }


def workspace_items(store: SettingsStore, workspace_id: str) -> dict[str, Any]:
    """Daftar semantic model dan report satu workspace (REST member)."""
    from .service_picker import workspace_contents

    principal = store.auth()
    principal.validate()
    data = workspace_contents(
        principal, workspace_id, datasets=True, reports=True
    )
    models = [
        {
            "kind": "model",
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "dataset_id": str(item.get("id") or ""),
            "type": "Semantic model",
        }
        for item in data.get("datasets") or []
        if isinstance(item, dict) and item.get("id")
    ]
    reports = [
        {
            "kind": "report",
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "dataset_id": str(item.get("datasetId") or ""),
            "report_type": str(item.get("reportType") or ""),
            "report_format": str(
                item.get("format") or item.get("reportFormat") or ""
            ),
            "type": "Report",
        }
        for item in data.get("reports") or []
        if isinstance(item, dict) and item.get("id")
    ]
    models.sort(key=lambda row: row["name"].casefold())
    reports.sort(key=lambda row: row["name"].casefold())
    return {
        "workspace_id": str(data.get("workspace_id") or workspace_id),
        "models": models,
        "reports": reports,
        "items": models + reports,
    }


def run_job(
    store: SettingsStore,
    payload: dict[str, Any] | None,
    log: Callable[[str], None],
    cancel: Any,
    *,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Job backup: validasi, jalankan, simpan preferensi folder/prefiks."""
    request = BackupRequest.from_payload(payload)
    principal = store.auth()
    principal.validate()
    # Nama dari katalog selalu menang: payload UI bisa basi/salah ketik, dan
    # endpoint XMLA dibangun dari nama workspace.
    option = workspace_detail(_database(store), request.workspace_id)
    workspace_name = option.name if option and option.name else request.workspace_name
    if not workspace_name:
        raise ExtractionError(
            "Nama workspace tidak ditemukan di katalog; pilih workspace dari daftar."
        )
    options = BackupOptions(
        workspace_id=request.workspace_id,
        workspace_name=workspace_name,
        items=request.items,
        folder=request.folder,
        prefix=safe_name(request.prefix or "Backup"),
    )
    result = run_backup(
        options,
        principal,
        log=log,
        progress=progress,
        cancel=cancel,
    )
    store.update(
        {
            keys.BACKUP_FOLDER_KEY: str(request.folder),
            keys.BACKUP_PREFIX_KEY: request.prefix,
        }
    )
    return result.payload()
