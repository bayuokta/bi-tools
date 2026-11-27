"""Resolusi snapshot database bersama untuk aplikasi interaktif."""

from __future__ import annotations

from pathlib import Path

from core.errors import ExtractionError
from core.lineage_store import DEFAULT_DB
from core.paths import data_dir
from core.snapshot import prepare_local_snapshot, read_meta

from .settings_store import SettingsStore


def local_snapshot_path(store: SettingsStore) -> Path:
    value = store.shared_db_local()
    if value:
        return Path(value).expanduser()
    return data_dir() / "shared" / "bi_tools.db"


def active_database_path(store: SettingsStore) -> Path:
    """Snapshot bersama bila ada; jika tidak, database lineage lama."""
    shared = local_snapshot_path(store)
    if shared.exists():
        return shared
    return Path(store.lineage_db() or DEFAULT_DB).expanduser()


def snapshot_status(store: SettingsStore) -> dict[str, object]:
    path = local_snapshot_path(store)
    source = store.shared_db_source()
    if not path.exists():
        return {
            "configured": bool(source),
            "source": source,
            "local": str(path),
            "exists": False,
            "generated_at": "",
            "schema_version": "",
            "size": 0,
        }
    meta = read_meta(path)
    return {
        "configured": bool(source),
        "source": source,
        "local": str(path),
        "exists": True,
        "generated_at": str(meta.get("generated_at") or ""),
        "schema_version": str(meta.get("schema_version") or ""),
        "size": path.stat().st_size,
    }


def download_snapshot(store: SettingsStore) -> dict[str, object]:
    source = store.shared_db_source()
    if not source:
        raise ExtractionError(
            "Shared snapshot location is not set (SharePoint/OneDrive folder)."
        )
    local = local_snapshot_path(store)
    result = prepare_local_snapshot(source, local)
    store.set_shared_db_local(str(local))
    return {**snapshot_status(store), **result}
