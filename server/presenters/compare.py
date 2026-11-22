"""Presenter perbandingan semantic model (read-only).

Alur: baca metadata dua sumber lewat XMLA/Desktop, bandingkan, simpan hasil
terakhir di memori untuk ekspor/script. Tidak ada jalur tulis ke model.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from core.auth import EntraTokens, ServicePrincipal
from core.compare_export import (
    default_compare_stem,
    write_compare_csv,
    write_compare_script,
)
from core.errors import ExtractionError
from core.model import LiveModel
from core.model_compare import compare_snapshots, snapshot_from_model
from core.paths import outputs_dir
from core.requests import CompareRequest, CompareSide
from core.usage_service import resolve_names
from core.xmla_client import XmlaError, open_client, workspace_endpoint

from ..settings_store import SettingsStore
from .analysis import database_path
from .metadata import instances_payload, workspaces_payload

_LOCK = threading.Lock()
_LAST_RESULT: dict[str, Any] = {}


def build_state(store: SettingsStore) -> dict[str, Any]:
    """Workspace katalog + instance Desktop untuk picker compare."""
    catalog = workspaces_payload(store)
    instances = instances_payload()
    return {
        "database": catalog.get("database") or "",
        "hint": catalog.get("hint") or "",
        "workspaces": catalog.get("workspaces") or [],
        "instances": instances.get("instances") or [],
        "instance_hint": instances.get("hint") or "",
    }


def _side_label(side: CompareSide, snapshot: Mapping[str, Any] | None = None) -> str:
    if side.kind == "desktop":
        name = str((snapshot or {}).get("model") or side.catalog or "Desktop")
        return f"{name} · localhost:{side.port}"
    workspace = side.workspace_name or side.workspace_id
    dataset = side.dataset_name or side.dataset_id
    return f"{workspace} / {dataset}"


def _read_side(
    store: SettingsStore,
    side: CompareSide,
    log: Any,
) -> tuple[dict[str, Any], str]:
    """Baca snapshot satu sisi; Service memakai token, Desktop tanpa token."""
    if side.kind == "desktop":
        try:
            client = open_client(port=side.port, catalog=side.catalog)
        except XmlaError as exc:
            raise ExtractionError(
                f"Tidak bisa terhubung ke Desktop localhost:{side.port}: {exc}"
            ) from exc
        try:
            model = LiveModel(client)
            snapshot = snapshot_from_model(model)
        finally:
            client.close()
        label = _side_label(side, snapshot)
        log(f"Desktop dibaca: {label}")
        return snapshot, label

    principal: ServicePrincipal = store.principal()
    principal.validate()
    body = side.to_payload()
    workspace_name = str(body.get("workspace_name") or "").strip()
    dataset_name = str(body.get("dataset_name") or "").strip()
    if not workspace_name or not dataset_name:
        database = database_path(store)
        workspace_name, dataset_name = resolve_names(
            database, side.workspace_id, side.dataset_id
        )
    endpoint = workspace_endpoint(
        principal.tenant_id or "myorg", workspace_name
    )
    tokens = EntraTokens(principal)
    try:
        client = open_client(
            endpoint=endpoint, catalog=dataset_name, tokens=tokens
        )
    except XmlaError as exc:
        raise ExtractionError(
            f"Tidak bisa terhubung ke XMLA '{workspace_name}' / '{dataset_name}': "
            f"{exc}\nPastikan XMLA Read aktif dan service principal punya akses."
        ) from exc
    try:
        model = LiveModel(client)
        snapshot = snapshot_from_model(model)
    finally:
        client.close()
    label = _side_label(
        CompareSide(
            kind="dataset",
            workspace_id=side.workspace_id,
            dataset_id=side.dataset_id,
            workspace_name=workspace_name,
            dataset_name=dataset_name,
        ),
        snapshot,
    )
    log(f"Dataset dibaca: {label}")
    return snapshot, label


def run_job(
    store: SettingsStore, payload: Mapping[str, Any], log: Any, cancel: Any
) -> dict[str, Any]:
    """Baca dua model dan kembalikan hasil perbandingan read-only."""
    request = CompareRequest.from_payload(payload)
    if cancel.is_set():
        raise ExtractionError("Perbandingan dibatalkan.")
    log(f"Sumber: {_side_label(request.source)}")
    log(f"Target: {_side_label(request.target)}")
    source, source_label = _read_side(store, request.source, log)
    if cancel.is_set():
        raise ExtractionError("Perbandingan dibatalkan.")
    target, target_label = _read_side(store, request.target, log)
    result = compare_snapshots(source, target, request.options)
    result.update(
        {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": {"label": source_label, **request.source.to_payload()},
            "target": {"label": target_label, **request.target.to_payload()},
            "read_only": True,
        }
    )
    stats = result.get("stats") or {}
    log(
        "Perbandingan selesai: "
        f"{stats.get('same', 0)} sama · {stats.get('different', 0)} beda · "
        f"{stats.get('source_only', 0)} hanya sumber · "
        f"{stats.get('target_only', 0)} hanya target."
    )
    with _LOCK:
        _LAST_RESULT.clear()
        _LAST_RESULT.update(result)
    return result


def _last_result() -> dict[str, Any]:
    with _LOCK:
        if not _LAST_RESULT:
            raise ExtractionError(
                "Belum ada hasil perbandingan. Jalankan perbandingan dulu."
            )
        return dict(_LAST_RESULT)


def _target_path(stem: str, suffix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return outputs_dir() / f"{stem}_{stamp}{suffix}"


def export_csv() -> dict[str, Any]:
    """Ekspor seluruh item hasil terakhir ke CSV."""
    result = _last_result()
    source = str((result.get("source") or {}).get("label") or "Source")
    target = str((result.get("target") or {}).get("label") or "Target")
    path = _target_path(default_compare_stem(source, target), ".csv")
    write_compare_csv(result, path)
    return {"path": str(path), "size": path.stat().st_size if path.exists() else 0}


def generate_script() -> dict[str, Any]:
    """Tulis manifest script TMSL pratinjau (tidak dieksekusi)."""
    result = _last_result()
    source = str((result.get("source") or {}).get("label") or "Source")
    target = str((result.get("target") or {}).get("label") or "Target")
    path = _target_path(default_compare_stem(source, target) + "_script", ".json")
    write_compare_script(result, path)
    return {"path": str(path), "size": path.stat().st_size if path.exists() else 0}
