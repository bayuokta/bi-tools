"""Presenter halaman Partisi: katalog, inventaris, dan refresh via XMLA.

Handler API hanya memvalidasi input lalu menyerahkan pekerjaan berat ke
``JobManager``. Semua akses XMLA/TOM berada di :mod:`core.partition_service`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from core.errors import ExtractionError
from core.lineage_store import DEFAULT_DB
from core.partition_service import process_partitions, read_partition_inventory
from core.requests import (
    PARTITION_CONFIRMATION,
    PartitionRefreshRequest,
    PartitionRequest,
)
from core.tom_client import REFRESH_TYPE_ORDER
from core.usage_service import resolve_names

from ..settings_store import SettingsStore
from . import metadata as metadata_presenter
from .service_picker import workspace_picklist


def database_path(store: SettingsStore) -> Path:
    return Path(store.lineage_db() or DEFAULT_DB).expanduser()


def build_state(store: SettingsStore) -> dict[str, Any]:
    database = database_path(store)
    options, _duplicates, hint = workspace_picklist(str(database))
    return {
        "database": str(database),
        "hint": hint,
        "workspaces": [
            {
                "id": option.workspace_id,
                "name": option.name,
                "label": f"{option.name} ({option.workspace_id[:8]})",
            }
            for option in options
        ],
        "refresh_types": list(REFRESH_TYPE_ORDER),
        "confirmation": PARTITION_CONFIRMATION,
        "credentials_missing": store.principal().missing,
    }


def datasets_payload(store: SettingsStore, workspace_id: str) -> dict[str, Any]:
    payload = metadata_presenter.contents_payload(
        store, workspace_id, datasets=True, reports=False
    )
    return {
        "workspace": payload["workspace"],
        "datasets": payload["datasets"],
    }


def _base_request(
    store: SettingsStore, payload: Mapping[str, Any]
) -> PartitionRequest:
    workspace_id = str(payload.get("workspace_id") or "").strip()
    dataset_id = str(payload.get("dataset_id") or "").strip()
    if not workspace_id or not dataset_id:
        raise ExtractionError("Pilih workspace dan semantic model dulu.")
    workspace_name, dataset_name = resolve_names(
        database_path(store), workspace_id, dataset_id
    )
    if not workspace_name:
        raise ExtractionError(
            "Nama workspace tidak ditemukan di katalog SQLite. Jalankan "
            "Sinkronisasi katalog workspace di Pengaturan."
        )
    if not dataset_name:
        raise ExtractionError(
            "Nama semantic model tidak ditemukan di katalog SQLite. Muat ulang "
            "daftar semantic model."
        )
    return PartitionRequest(
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        workspace_name=workspace_name,
        dataset_name=dataset_name,
    )


def build_inventory_request(
    store: SettingsStore, payload: Mapping[str, Any]
) -> PartitionRequest:
    """DTO inventaris tervalidasi untuk jawaban 400 dini dan job."""
    return _base_request(store, payload)


def _targets(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        raise ExtractionError("Target partisi harus berupa daftar table/partition.")
    pairs: list[tuple[str, str]] = []
    for item in value:
        if isinstance(item, Mapping):
            table = str(item.get("table") or "").strip()
            partition = str(item.get("partition") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            table = str(item[0] or "").strip()
            partition = str(item[1] or "").strip()
        else:
            raise ExtractionError(
                "Setiap target partisi harus berisi tabel dan nama partisi."
            )
        if not table or not partition:
            raise ExtractionError("Nama tabel dan partisi tidak boleh kosong.")
        pairs.append((table, partition))
    return tuple(pairs)


def build_refresh_request(
    store: SettingsStore, payload: Mapping[str, Any]
) -> PartitionRefreshRequest:
    """DTO refresh tervalidasi, termasuk konfirmasi ``PROCESS``."""
    base = _base_request(store, payload)
    return PartitionRefreshRequest(
        workspace_id=base.workspace_id,
        dataset_id=base.dataset_id,
        workspace_name=base.workspace_name,
        dataset_name=base.dataset_name,
        targets=_targets(payload.get("targets")),
        refresh_type=str(payload.get("refresh_type") or "full"),
        confirmation=str(payload.get("confirmation") or ""),
    )


def _cancel(cancel: Any) -> Any:
    return getattr(cancel, "is_set", None)


def run_inventory_job(
    store: SettingsStore, payload: Mapping[str, Any], log: Any, cancel: Any
) -> dict[str, Any]:
    request = build_inventory_request(store, payload)
    return read_partition_inventory(
        **request.to_inventory_kwargs(),
        principal=store.principal(),
        log=log,
        should_stop=_cancel(cancel),
    )


def run_refresh_job(
    store: SettingsStore, payload: Mapping[str, Any], log: Any, cancel: Any
) -> dict[str, Any]:
    request = build_refresh_request(store, payload)
    store.principal().validate()
    return process_partitions(
        **request.to_refresh_kwargs(),
        principal=store.principal(),
        log=log,
        should_stop=_cancel(cancel),
    )
