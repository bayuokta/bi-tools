"""Presenter ekstraksi metadata untuk web.

Alur: validasi sumber di request HTTP (agar kesalahan sederhana dijawab 400),
lalu jalankan ``core.jobs.run_metadata_job`` di thread job dengan log live.
Pemetaan argumen memakai DTO ``core.requests`` supaya web/CLI tidak
menyusun kwargs sendiri.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from core.auth import EntraTokens, fabric_provider
from core.errors import ExtractionError
from core.jobs import run_metadata_job
from core.lineage_service import workspace_detail
from core.lineage_store import DEFAULT_DB
from core.paths import outputs_dir
from core.pbix import PbixSourceInfo, detect_pbix_source
from core.requests import (
    SCOPES,
    LocalMetadataRequest,
    ServiceMetadataRequest,
    split_scope,
)
from core.xmla_client import list_instances, workspace_endpoint

from .. import settings as keys
from ..settings_store import SettingsStore
from .service_picker import (
    is_paginated,
    report_label,
    workspace_contents,
    workspace_label,
    workspace_picklist,
)


def effective_out_dir(store: SettingsStore) -> Path:
    text = store.get_str(keys.SETTINGS_OUT_DIR_KEY).strip()
    return Path(text).expanduser() if text else outputs_dir()


def _database(store: SettingsStore) -> str:
    return store.lineage_db() or str(DEFAULT_DB)


# -- data untuk pemilih --------------------------------------------------
def instances_payload() -> dict[str, Any]:
    """Daftar instance Power BI Desktop yang terbuka."""
    try:
        items = list(list_instances())
    except Exception as exc:  # noqa: BLE001 - dilaporkan ke halaman
        return {
            "instances": [],
            "hint": f"Instance Power BI Desktop tidak bisa dibaca: {exc}",
        }
    if not items:
        hint = (
            "Tidak ada instance Power BI Desktop yang terbuka. "
            "Buka file .pbix lalu muat ulang."
        )
    elif len(items) > 1:
        hint = (
            "Ada lebih dari satu instance Power BI Desktop. "
            "Pilih instance yang sesuai sebelum menjalankan."
        )
    else:
        hint = "Satu instance ditemukan dan dipakai otomatis."
    return {
        "instances": [
            {
                "port": item.port,
                "catalog": item.catalog,
                "file_name": item.file_name,
                "model_name": item.model_name,
                "modified": item.modified,
                "label": item.label,
            }
            for item in items
        ],
        "hint": hint,
    }


def _pbix_detail(info: PbixSourceInfo) -> str:
    if info.has_local_model:
        return (
            "Metadata model tersimpan di dalam .pbix. Ekstraksi model memakai "
            "XMLA, jadi Power BI Desktop harus terbuka."
        )
    if info.is_live_connection:
        dataset = f" Dataset: {info.dataset_id}." if info.dataset_id else ""
        return (
            f"Thin report ke dataset remote.{dataset} Metadata model tidak "
            "tersedia di file; hanya report yang diekstrak."
        )
    return "Jenis sumber tidak dikenali. Report tetap bisa dicoba bila PBIR tersedia."


def pbix_payload(path: str) -> dict[str, Any]:
    """Deteksi jenis satu file ``.pbix`` tanpa menjalankan ekstraksi."""
    text = str(path or "").strip().strip('"')
    empty = {
        "path": "",
        "exists": False,
        "kind": "",
        "label": "Belum ada file .pbix dipilih.",
        "detail": "",
        "has_pbir": False,
        "has_local_model": False,
        "is_live_connection": False,
        "dataset_id": "",
    }
    if not text:
        return empty
    target = Path(text).expanduser()
    if not target.exists():
        return {
            **empty,
            "path": str(target),
            "label": f"File tidak ditemukan: {target}",
        }
    try:
        info = detect_pbix_source(target)
    except Exception as exc:  # noqa: BLE001 - file rusak/legacy
        return {
            **empty,
            "path": str(target),
            "exists": True,
            "label": f"Tidak bisa dibaca: {exc}",
        }
    label = info.label
    if not info.has_pbir:
        label += " - Report/definition tidak ditemukan (format legacy?)"
    return {
        "path": str(info.path),
        "exists": True,
        "kind": info.kind,
        "label": label,
        "detail": _pbix_detail(info),
        "has_pbir": info.has_pbir,
        "has_local_model": info.has_local_model,
        "is_live_connection": info.is_live_connection,
        "dataset_id": info.dataset_id,
    }


def workspaces_payload(store: SettingsStore) -> dict[str, Any]:
    """Workspace dari katalog SQLite (hasil sinkronisasi)."""
    database = _database(store)
    options, _duplicates, hint = workspace_picklist(database)
    return {
        "database": database,
        "hint": hint,
        "workspaces": [
            {
                "id": option.workspace_id,
                "name": option.name,
                "type": option.type,
                "active": option.is_active,
                "label": workspace_label(option),
            }
            for option in options
        ],
    }


def contents_payload(
    store: SettingsStore,
    workspace_id: str,
    *,
    datasets: bool = True,
    reports: bool = True,
) -> dict[str, Any]:
    """Dataset dan/atau report satu workspace, plus endpoint XMLA turunannya.

    Workspace model dan workspace report bisa berbeda, jadi pemanggil hanya
    meminta daftar yang dibutuhkan: satu panggilan untuk dataset, satu panggilan
    lain untuk report. Ini juga menghindari 401 dari endpoint yang tidak dipakai.
    """
    workspace = str(workspace_id or "").strip()
    if not workspace:
        raise ExtractionError("Workspace belum dipilih.")
    principal = store.principal()
    principal.validate()
    database = _database(store)
    option = workspace_detail(database, workspace)
    if option is None:
        raise ExtractionError(
            "Workspace tidak ada di katalog SQLite. Jalankan Sinkronisasi "
            "katalog workspace di Pengaturan, lalu muat ulang daftar."
        )
    if not option.name:
        raise ExtractionError("Nama workspace kosong; tidak bisa membuat endpoint XMLA.")
    _options, duplicates, _hint = workspace_picklist(database)
    endpoint = workspace_endpoint("myorg", option.name, option.workspace_id, disambiguate=option.name in duplicates)
    payload = workspace_contents(
        principal, workspace, datasets=bool(datasets), reports=bool(reports)
    )

    datasets = [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
        }
        for item in payload.get("datasets") or []
    ]
    reports = []
    for item in payload.get("reports") or []:
        reports.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or item.get("id") or ""),
                "label": report_label(item),
                "report_type": str(item.get("reportType") or ""),
                "dataset_id": str(item.get("datasetId") or ""),
                "is_paginated": is_paginated(item),
            }
        )
    return {
        "workspace": {
            "id": option.workspace_id,
            "name": option.name,
            "label": workspace_label(option),
            "endpoint": endpoint,
        },
        "datasets": datasets,
        "reports": reports,
    }


# -- validasi dan eksekusi ----------------------------------------------
def _out_dir(store: SettingsStore, value: Any) -> Path:
    text = str(value or "").strip().strip('"')
    if not text:
        return effective_out_dir(store)
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ExtractionError("Folder output harus absolut.")
    return path


def _local_request(
    store: SettingsStore, payload: Mapping[str, Any], scope: str, out_dir: Path
) -> LocalMetadataRequest:
    text = str(payload.get("pbix") or "").strip().strip('"')
    if not text:
        raise ExtractionError("Pilih file .pbix sumber terlebih dahulu.")
    path = Path(text).expanduser()
    if not path.exists():
        raise ExtractionError(f"File .pbix tidak ditemukan: {path}")
    try:
        info = detect_pbix_source(path)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"File .pbix tidak bisa dibaca: {exc}") from exc

    wants_report, wants_model = split_scope(scope)
    if wants_report and not info.has_pbir:
        raise ExtractionError(
            "Report/definition tidak ditemukan di .pbix ini; hanya report PBIR "
            "yang bisa diekstrak."
        )
    if wants_model and not info.has_local_model:
        raise ExtractionError(
            "File .pbix ini tidak menyimpan model lokal (live connection). "
            "Pilih cakupan Report saja."
        )
    port: int | None = None
    if wants_model:
        raw_port = payload.get("port")
        try:
            port = int(raw_port) if raw_port not in (None, "", 0) else None
        except (TypeError, ValueError) as exc:
            raise ExtractionError(f"Port instance Desktop tidak valid: {raw_port}") from exc
        if port is None:
            raise ExtractionError(
                "Pilih instance Power BI Desktop yang memuat file ini "
                "(Power BI Desktop harus terbuka)."
            )
    return LocalMetadataRequest(
        out_dir=out_dir,
        scope=scope,
        pbix=path,
        port=port,
        catalog=str(payload.get("catalog") or "").strip() or None,
        include_usage=info.has_pbir,
    )


def _service_request(
    store: SettingsStore, payload: Mapping[str, Any], scope: str, out_dir: Path
) -> ServiceMetadataRequest:
    wants_report, wants_model = split_scope(scope)
    legacy_workspace = str(payload.get("workspace_id") or "").strip()
    legacy_name = str(payload.get("workspace_name") or "").strip()
    model_workspace = (
        str(payload.get("model_workspace_id") or "").strip() or legacy_workspace
    )
    model_name = (
        str(payload.get("model_workspace_name") or "").strip() or legacy_name
    )
    report_workspace = (
        str(payload.get("report_workspace_id") or "").strip() or legacy_workspace
    )
    report_id = str(payload.get("report_id") or "").strip()
    raw_ids = payload.get("report_ids") or []
    report_ids = (
        tuple(str(item or "").strip() for item in raw_ids)
        if isinstance(raw_ids, (list, tuple))
        else ()
    )
    raw_names = payload.get("report_names") or {}
    report_names = (
        tuple((str(key), str(value)) for key, value in raw_names.items())
        if isinstance(raw_names, dict)
        else ()
    )
    endpoint = str(payload.get("endpoint") or "").strip()
    if not endpoint and model_name:
        endpoint = workspace_endpoint("myorg", model_name, model_workspace)
    report_type = str(payload.get("report_type") or "")
    if wants_report and report_type == "PaginatedReport":
        raise ExtractionError(
            "Report paginated (RDL) tidak didukung; pilih report Power BI biasa."
        )
    catalog = str(payload.get("catalog") or "").strip()
    if wants_model:
        if not model_workspace or not model_name:
            raise ExtractionError(
                "Pilih workspace semantic model lebih dulu (boleh sama atau "
                "berbeda dengan workspace report)."
            )
        if not catalog:
            raise ExtractionError(
                "Pilih catalog (dataset) semantic model di workspace model."
            )
    request = ServiceMetadataRequest(
        out_dir=out_dir,
        workspace_id=report_workspace,
        report_id=report_id,
        report_ids=report_ids,
        report_names=report_names,
        endpoint=endpoint,
        catalog=catalog,
        scope=scope,
        include_usage=scope == "both",
    )
    principal = store.principal()
    if not principal.is_complete:
        raise ExtractionError(
            "Kredensial service principal belum lengkap: "
            + ", ".join(principal.missing)
            + " (isi di Pengaturan)."
        )
    return request


def build_request(store: SettingsStore, payload: Mapping[str, Any]):
    """DTO request tervalidasi; dipakai untuk 400 dini dan untuk job."""
    source = str(payload.get("source") or "local").strip()
    scope = str(payload.get("scope") or "both").strip()
    if scope not in SCOPES:
        raise ExtractionError(f"Cakupan ekstraksi tidak dikenal: {scope}")
    out_dir = _out_dir(store, payload.get("out_dir"))
    if source == "service":
        return _service_request(store, payload, scope, out_dir)
    if source == "local":
        return _local_request(store, payload, scope, out_dir)
    raise ExtractionError(f"Sumber ekstraksi tidak dikenal: {source}")


def run_job(store: SettingsStore, payload: Mapping[str, Any], log: Any, cancel: Any) -> dict[str, Any]:
    """Jalankan ekstraksi metadata di thread job."""
    request = build_request(store, payload)
    if isinstance(request, ServiceMetadataRequest):
        tokens = EntraTokens(store.principal())
        result = run_metadata_job(
            **request.to_job_kwargs(),
            tokens=tokens,
            token_provider=fabric_provider(tokens),
            log=log,
            should_stop=cancel.is_set if cancel is not None else None,
            progress=lambda index, total, name: log(
                f"Batch {index}/{total}: {name}"
            ),
        )
    else:
        result = run_metadata_job(**request.to_job_kwargs(), log=log)
    return result_summary(result, request.out_dir)


def result_summary(result: Any, out_dir: Path) -> dict[str, Any]:
    source = result.source
    return {
        "source": getattr(source, "label", "") or "Power BI Service",
        "kind": getattr(source, "kind", ""),
        "report": result.report,
        "model": result.model,
        "model_error": result.model_error,
        "report_out": str(result.report_out) if result.report_out else "",
        "model_out": str(result.model_out) if result.model_out else "",
        "outputs": [str(path) for path in result.outputs],
        "out_dir": str(out_dir),
        "batch": [dict(row) for row in getattr(result, "batch", ()) or ()],
        "summary_out": (
            str(result.summary_out) if getattr(result, "summary_out", None) else ""
        ),
    }
