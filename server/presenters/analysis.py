"""Presenter Analisa Semantic Model untuk web.

Alurnya: daftar workspace dari katalog,
daftar dataset per workspace, analisa via ``usage_service.analyze_dataset``,
snapshot SQLite tanpa XMLA, dan ekspor XLSX.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from core.auth import ServicePrincipal
from core.errors import ExtractionError
from core.lineage_store import DEFAULT_DB
from core.paths import outputs_dir
from core.requests import AnalysisRequest
from core.usage_service import (
    analyze_dataset,
    format_bytes,
    load_snapshot,
    output_file_name,
    report_url,
    resolve_names,
    write_workbook,
)

from .. import settings as keys
from ..settings_store import SettingsStore
from .service_picker import workspace_picklist
from . import metadata as metadata_presenter

OBJECT_FILTERS = ("all", "columns", "measures")
SORT_KEYS = (
    "default",
    "name",
    "type",
    "table",
    "data_type",
    "size",
    "status",
    "uses",
    "format_string",
    "has_error",
    "display_folder",
)
SORT_DESC_DEFAULT = {"size", "uses", "has_error"}
USAGE_GROUPS = (
    ("Dipakai di visual", ("field",)),
    ("Dipakai di filter", ("filter-report", "filter-page", "filter-visual", "filter-query")),
    ("Dipakai di sorting & format", ("sort", "format", "calculation")),
)
USAGE_LABELS = {
    "field": "Field",
    "filter-report": "Filter report",
    "filter-page": "Filter halaman",
    "filter-visual": "Filter visual",
    "filter-query": "Filter query",
    "sort": "Sort",
    "format": "Format",
    "calculation": "Visual calculation",
}


def database_path(store: SettingsStore) -> Path:
    return Path(store.lineage_db() or DEFAULT_DB).expanduser()


def analysis_settings(store: SettingsStore) -> dict[str, Any]:
    object_filter = store.get_str(keys.SETTINGS_ANALYSIS_OBJECT_FILTER_KEY, "all")
    if object_filter not in OBJECT_FILTERS:
        object_filter = "all"
    sort_column = store.get_str(keys.SETTINGS_ANALYSIS_SORT_COLUMN_KEY, "default")
    if sort_column not in SORT_KEYS:
        sort_column = "default"
    return {
        "object_filter": object_filter,
        "unused_only": store.get_bool(keys.SETTINGS_ANALYSIS_UNUSED_ONLY_KEY, False),
        "include_other_workspaces": store.get_bool(
            keys.SETTINGS_ANALYSIS_OTHER_WS_KEY, True
        ),
        "include_personal": store.get_bool(keys.SETTINGS_ANALYSIS_PERSONAL_KEY, False),
        "sort_column": sort_column,
        "sort_desc": store.get_bool(keys.SETTINGS_ANALYSIS_SORT_DESC_KEY, False),
    }


def save_preferences(store: SettingsStore, payload: Mapping[str, Any]) -> dict[str, Any]:
    current = analysis_settings(store)
    object_filter = str(payload.get("object_filter", current["object_filter"]))
    if object_filter not in OBJECT_FILTERS:
        raise ExtractionError(f"Filter objek tidak dikenal: {object_filter}")
    sort_column = str(payload.get("sort_column", current["sort_column"]))
    if sort_column not in SORT_KEYS:
        raise ExtractionError(f"Kolom sort tidak dikenal: {sort_column}")
    store.update(
        {
            keys.SETTINGS_ANALYSIS_OBJECT_FILTER_KEY: object_filter,
            keys.SETTINGS_ANALYSIS_UNUSED_ONLY_KEY: bool(
                payload.get("unused_only", current["unused_only"])
            ),
            keys.SETTINGS_ANALYSIS_OTHER_WS_KEY: bool(
                payload.get(
                    "include_other_workspaces", current["include_other_workspaces"]
                )
            ),
            keys.SETTINGS_ANALYSIS_PERSONAL_KEY: bool(
                payload.get("include_personal", current["include_personal"])
            ),
            keys.SETTINGS_ANALYSIS_SORT_COLUMN_KEY: sort_column,
            keys.SETTINGS_ANALYSIS_SORT_DESC_KEY: bool(
                payload.get("sort_desc", current["sort_desc"])
            ),
        }
    )
    return analysis_settings(store)


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
        "settings": analysis_settings(store),
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


def snapshot_payload(store: SettingsStore, dataset_id: str) -> dict[str, Any]:
    dataset = str(dataset_id or "").strip()
    if not dataset:
        return {"result": None}
    result = load_snapshot(database_path(store), dataset)
    return {"result": serialize_result(result) if result is not None else None}


def _record_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(record.get("usage_kind") or "")
    workspace_id = str(record.get("workspace_id") or "")
    report_id = str(record.get("report_id") or "")
    return {
        "usage_kind": kind,
        "usage_label": USAGE_LABELS.get(kind, kind),
        "report_id": report_id,
        "report_name": str(record.get("report_name") or "(report)"),
        "workspace_id": workspace_id,
        "page_name": str(record.get("page_name") or ""),
        "visual_title": str(record.get("visual_title") or ""),
        "visual_type": str(record.get("visual_type") or ""),
        "field_kind": str(record.get("field_kind") or ""),
        "aggregation": str(record.get("aggregation") or ""),
        "is_hidden": bool(record.get("is_hidden")),
        "url": report_url(workspace_id, report_id),
    }


def _usage_groups(analysis: Any) -> list[dict[str, Any]]:
    records = [
        _record_payload(record) for record in (analysis.report_records or [])
    ]
    groups: list[dict[str, Any]] = []
    for label, kinds in USAGE_GROUPS:
        selected = [row for row in records if row["usage_kind"] in kinds]
        if not selected:
            continue
        by_report: dict[str, dict[str, Any]] = {}
        for row in selected:
            key = row["report_id"] or row["report_name"]
            report = by_report.setdefault(
                key,
                {
                    "report_id": row["report_id"],
                    "report_name": row["report_name"],
                    "workspace_id": row["workspace_id"],
                    "url": row["url"],
                    "points": [],
                },
            )
            report["points"].append(row)
        groups.append(
            {
                "kind": "usage",
                "label": label,
                "count": len(selected),
                "reports": list(by_report.values()),
            }
        )
    refs = [
        {
            "kind": str(ref.kind or ""),
            "object": str(ref.object or ""),
            "detail": str(ref.detail or ""),
            "blocking": bool(ref.blocking),
        }
        for ref in (analysis.model_refs or [])
    ]
    if refs:
        groups.append(
            {
                "kind": "model",
                "label": "Referensi model",
                "count": len(refs),
                "refs": refs,
            }
        )
    return groups


def _column_row(analysis: Any) -> dict[str, Any]:
    column = analysis.column
    size_bytes = int(getattr(column, "size_total_bytes", 0) or 0)
    return {
        "name": str(getattr(column, "column", "")),
        "type": str(getattr(column, "column_type", "")),
        "table": str(getattr(column, "table", "")),
        "source": "Model",
        "data_type": str(getattr(column, "data_type", "")),
        "size": format_bytes(size_bytes),
        "size_bytes": size_bytes,
        "status": str(analysis.status or ""),
        "uses": len(analysis.report_records or []) + len(analysis.model_refs or []),
        "reports": len(
            {str(row.get("report_id") or "") for row in analysis.report_records or []}
        ),
        "format_string": str(getattr(column, "format_string", "")),
        "has_error": bool(getattr(column, "has_error", False)),
        "display_folder": str(getattr(column, "display_folder", "")),
        "reason": str(analysis.reason or ""),
        "rows": int(getattr(column, "rows", 0) or 0),
        "size_breakdown": {
            "data": int(getattr(column, "size_data_bytes", 0) or 0),
            "hierarchy": int(getattr(column, "size_hierarchy_bytes", 0) or 0),
            "dictionary": int(getattr(column, "size_dictionary_bytes", 0) or 0),
        },
        "expression": "",
        "children": _usage_groups(analysis),
    }


def _measure_row(analysis: Any) -> dict[str, Any]:
    measure = analysis.measure
    return {
        "name": str(getattr(measure, "measure", "")),
        "type": "measure (hidden)" if getattr(measure, "is_hidden", False) else "measure",
        "table": str(getattr(measure, "table", "")),
        "source": "Model",
        "data_type": str(getattr(measure, "data_type", "")),
        "size": "-",
        "size_bytes": 0,
        "status": str(analysis.status or ""),
        "uses": len(analysis.report_records or []) + len(analysis.model_refs or []),
        "reports": len(
            {str(row.get("report_id") or "") for row in analysis.report_records or []}
        ),
        "format_string": str(getattr(measure, "format_string", "")),
        "has_error": bool(getattr(measure, "has_error", False)),
        "display_folder": str(getattr(measure, "display_folder", "")),
        "reason": str(analysis.reason or ""),
        "rows": 0,
        "size_breakdown": {"data": 0, "hierarchy": 0, "dictionary": 0},
        "expression": str(getattr(measure, "expression", "")),
        "children": _usage_groups(analysis),
    }


def serialize_result(result: Any) -> dict[str, Any]:
    stats = result.stats
    reports = []
    for item in result.reports or []:
        if not isinstance(item, Mapping):
            continue
        reports.append(
            {
                "report_id": str(item.get("report_id") or item.get("id") or ""),
                "report_name": str(item.get("report_name") or item.get("name") or ""),
                "workspace_id": str(item.get("workspace_id") or ""),
                "workspace_name": str(item.get("workspace_name") or ""),
                "format": str(
                    item.get("report_format") or item.get("format") or ""
                ),
                "status": str(item.get("status") or ""),
                "message": str(item.get("message") or ""),
                "modified_at": str(item.get("modified_at") or ""),
            }
        )
    unused_bytes = int(result.unused_bytes)
    return {
        "dataset": {
            "id": result.dataset_id,
            "name": result.dataset_name,
            "workspace_id": result.workspace_id,
            "workspace_name": result.workspace_name,
        },
        "analyzed_at": result.analyzed_at,
        "method": result.method,
        "coverage": result.coverage,
        "coverage_complete": bool(result.coverage_complete),
        "totals": {
            "model_bytes": int(result.dataset_bytes),
            "data_bytes": int(stats.data_bytes),
            "hierarchy_bytes": int(stats.hierarchy_bytes),
            "dictionary_bytes": int(stats.dictionary_bytes),
            "columns": len(result.columns),
            "measures": len(result.measures),
            "unused_columns": len(result.unused),
            "unused_measures": len(result.unused_measures),
            "unused_bytes": unused_bytes,
            "reports": int(result.report_total),
            "reports_scanned": int(result.report_scanned),
            "reports_skipped": int(result.report_skipped),
            "reports_failed": int(result.report_failed),
            "reports_personal": int(result.report_personal),
            "reports_app": int(result.report_app),
            "reports_inaccessible": int(result.report_inaccessible),
            "unresolved": len(result.unresolved),
        },
        "counts": {
            "columns": dict(result.status_counts),
            "measures": dict(result.measure_status_counts),
        },
        "columns": [_column_row(column) for column in result.columns],
        "measures": [_measure_row(measure) for measure in result.measures],
        "reports": reports,
        "messages": list(result.messages),
    }


def run_job(
    store: SettingsStore, payload: Mapping[str, Any], log: Any, cancel: Any
) -> dict[str, Any]:
    workspace_id = str(payload.get("workspace_id") or "").strip()
    dataset_id = str(payload.get("dataset_id") or "").strip()
    if not workspace_id or not dataset_id:
        raise ExtractionError("Pilih workspace dan semantic model dulu.")
    principal: ServicePrincipal = store.principal()
    principal.validate()
    database = database_path(store)
    workspace_name, dataset_name = resolve_names(database, workspace_id, dataset_id)
    request = AnalysisRequest(
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        workspace_name=workspace_name,
        dataset_name=dataset_name,
        database=database,
        include_other_workspaces=bool(
            payload.get("include_other_workspaces", True)
        ),
        include_personal=bool(payload.get("include_personal", False)),
        refresh=bool(payload.get("refresh", False)),
    )

    def progress(index: int, total: int, name: str) -> None:
        log(f"Report {index}/{total}: {name}")

    result = analyze_dataset(
        **request.to_run_kwargs(),
        principal=principal,
        log=log,
        progress=progress,
        should_stop=cancel.is_set,
    )
    return serialize_result(result)


def export(payload: Mapping[str, Any], store: SettingsStore) -> dict[str, Any]:
    dataset_id = str(payload.get("dataset_id") or "").strip()
    if not dataset_id:
        raise ExtractionError("Semantic model belum dipilih.")
    result = load_snapshot(database_path(store), dataset_id)
    if result is None:
        raise ExtractionError(
            "Belum ada hasil analisa tersimpan untuk dataset ini. Jalankan "
            "analisa lebih dulu."
        )
    text = str(payload.get("output") or "").strip().strip('"')
    if text:
        target = Path(text).expanduser()
        if not target.is_absolute():
            raise ExtractionError("Path ekspor harus absolut.")
    else:
        target = outputs_dir() / output_file_name(
            result.dataset_name, result.dataset_id
        )
    write_workbook(result, target)
    return {
        "path": str(target),
        "size": target.stat().st_size if target.exists() else 0,
    }
