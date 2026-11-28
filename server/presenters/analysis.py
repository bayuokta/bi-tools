"""Presenter Analisa Semantic Model untuk web.

Alurnya: daftar workspace dari katalog, daftar dataset per workspace, analisa
via ``usage_service.analyze_dataset``, lalu hasil disimpan di sesi SQLite
in-memory (tidak ditulis ke database) agar halaman selalu memakai data baru.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Mapping

from core.auth import EntraTokens, fabric_provider
from core.analysis_details import item_details
from core.best_practice import build_best_practice
from core.analysis_export import (
    dependency_rows,
    write_dependencies_csv,
    write_lineage_files,
    write_lineage_image,
    write_object_json,
    write_uses_xlsx,
)
from core.fabric_api import FabricReportClient
from core.analysis_lineage import build_lineage, build_table_lineage
from core.analysis_query import (
    DEFAULT_ROWS,
    QUERY_TIMEOUT,
    build_raw_query,
    preview_payload as build_preview_payload,
)
from core.errors import ExtractionError
from core.lineage_store import close_quietly, connect, workspace_by_id
from core.usage_store import initialize as initialize_usage, report_detail
from core.model_health import broken_visual_counts, build_health
from core.paths import outputs_dir
from core.requests import AnalysisRequest
from core.usage_service import (
    analyze_dataset,
    format_bytes,
    display_data_type,
    is_counted_record,
    is_counted_reference,
    output_file_name,
    report_url,
    resolve_names,
    snapshot_from_connection,
    write_workbook,
)
from core.xmla_client import XmlaError, open_client, workspace_endpoint
from core.raw_metadata import (
    COLUMN_DMV,
    FUNCTION_DMV,
    HIERARCHY_DMV,
    MEASURE_DMV,
    TABLE_DMV,
    find_row,
    metadata_payload,
)
from core.result_export import write_result_export
from core.table_export import (
    GROUP_ICONS as TABLE_GROUP_ICONS,
    build_table_groups,
    write_table_export,
)

from .. import settings as keys
from ..settings_store import SettingsStore
from .service_picker import workspace_picklist
from . import metadata as metadata_presenter

OBJECT_FILTERS = ("all", "columns", "measures", "hierarchies", "functions")
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
    "from_table",
    "to_table",
    "cross_filtering",
    "from_cardinality",
    "to_cardinality",
    "security_filtering",
    "is_active",
    "cross",
    "cardinality",
    "auto",
    "used",
    "workspace_name",
    "format",
    "pages",
    "visuals",
    "fields",
    "unresolved",
    "modified_at",
    "kind",
    "source",
    "warning",
)
SORT_DESC_DEFAULT = {"size", "uses", "has_error"}
GROUP_MODEL = "Used in artifacts"
GROUP_INDIRECT = "Indirect references"
GROUP_CALC_TABLE = "Used in calculated tables"
GROUP_VISUALS = "Used in visuals"
GROUP_VISUAL_FILTERS = "Used in visual level filters"
GROUP_REPORT_FILTERS = "Used in report level filters"
GROUP_HIERARCHY = "Used in hierarchy"
GROUP_POWER_QUERY = "Used in Power Query"
GROUP_DEFAULT_LABEL = "Used as default label"
GROUP_KEY_COLUMN = "Used as key column"
GROUP_RELATIONSHIPS = "Used in relationships"
GROUP_SECURITY = "Used in row/object level security"
GROUP_PAGE_FILTERS = "Used in page level filters"
GROUP_SORTING = "Used in column sorting"
GROUP_FIELD_PARAMETERS = "Used in field parameters"

GROUP_ORDER = (
    GROUP_VISUALS,
    GROUP_MODEL,
    GROUP_INDIRECT,
    GROUP_VISUAL_FILTERS,
    GROUP_PAGE_FILTERS,
    GROUP_REPORT_FILTERS,
    GROUP_RELATIONSHIPS,
    GROUP_SECURITY,
    GROUP_POWER_QUERY,
    GROUP_DEFAULT_LABEL,
    GROUP_CALC_TABLE,
    GROUP_HIERARCHY,
    GROUP_KEY_COLUMN,
    GROUP_SORTING,
    GROUP_FIELD_PARAMETERS,
)

ARTIFACT_TYPES = {
    "measure": "Measure",
    "calculated column": "Calculated column",
    "calculated table": "Calculated table",
    "calculated table column": "Calculated column",
    "calculation item": "Calculation item",
    "KPI": "KPI",
    "hierarchy": "Hierarchy",
    "langkah M": "M step",
}
SECURITY_TYPES = {"RLS": "RLS", "column permission": "OLS"}
KIND_SORT = "sort by"
KIND_FIELD_PARAMETER = "field parameter"

USAGE_LABELS = {
    "field": "Visual field",
    "filter-report": "Report filter",
    "filter-page": "Page filter",
    "filter-visual": "Visual filter",
    "filter-query": "Visual query filter",
    "sort": "Sort",
    "format": "Format",
    "calculation": "Visual calculation",
}


def database_path(store: SettingsStore) -> Path:
    from ..shared_db import active_database_path

    return active_database_path(store)


# ---------------------------------------------------------------------------
# Sesi analisa in-memory (tidak menulis tabel usage_* ke database)
# ---------------------------------------------------------------------------
MAX_SESSION_DATASETS = 3
_SESSION_LOCK = threading.RLock()
_SESSIONS: dict[str, "_AnalysisSession"] = {}


class _AnalysisSession:
    """Koneksi SQLite in-memory milik satu dataset selama server hidup."""

    def __init__(self, dataset_id: str) -> None:
        self.dataset_id = dataset_id
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        initialize_usage(self.conn)


def _session(dataset_id: str, *, create: bool = True) -> _AnalysisSession | None:
    dataset = str(dataset_id or "").strip()
    if not dataset:
        return None
    with _SESSION_LOCK:
        session = _SESSIONS.get(dataset)
        if session is None and create:
            session = _AnalysisSession(dataset)
            _SESSIONS[dataset] = session
            while len(_SESSIONS) > MAX_SESSION_DATASETS:
                stale_id = next(
                    key for key in list(_SESSIONS) if key != dataset
                )
                stale = _SESSIONS.pop(stale_id)
                with stale.lock:
                    close_quietly(stale.conn)
        return session


def reset_sessions() -> None:
    """Tutup semua sesi analisa (dipakai uji dan saat server berhenti)."""
    with _SESSION_LOCK:
        for session in list(_SESSIONS.values()):
            with session.lock:
                close_quietly(session.conn)
        _SESSIONS.clear()


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
        "include_reports": store.get_bool(
            keys.SETTINGS_ANALYSIS_REPORTS_KEY, True
        ),
        "sort_column": sort_column,
        "sort_desc": store.get_bool(keys.SETTINGS_ANALYSIS_SORT_DESC_KEY, False),
    }


def save_preferences(store: SettingsStore, payload: Mapping[str, Any]) -> dict[str, Any]:
    current = analysis_settings(store)
    object_filter = str(payload.get("object_filter", current["object_filter"]))
    if object_filter not in OBJECT_FILTERS:
        raise ExtractionError(f"Unknown object filter: {object_filter}")
    sort_column = str(payload.get("sort_column", current["sort_column"]))
    if sort_column not in SORT_KEYS:
        raise ExtractionError(f"Unknown sort column: {sort_column}")
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
            keys.SETTINGS_ANALYSIS_REPORTS_KEY: bool(
                payload.get("include_reports", current["include_reports"])
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
        "credentials_missing": store.auth().missing,
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
    session = _session(dataset, create=False)
    if session is None:
        return {"result": None}
    with session.lock:
        result = snapshot_from_connection(session.conn, dataset)
    if result is None:
        return {"result": None}
    return {"result": serialize_result(result, _report_workspace_names(store, result))}


def _report_workspace_names(store: SettingsStore, result: Any) -> dict[str, str]:
    """Nama workspace untuk report lintas workspace, dibaca dari katalog lokal."""
    ids = {
        str(item.get("workspace_id") or "")
        for item in getattr(result, "reports", []) or []
        if isinstance(item, Mapping)
    }
    ids.discard("")
    if not ids:
        return {}
    database = database_path(store)
    if not Path(database).exists():
        return {}
    names: dict[str, str] = {}
    conn = connect(database)
    try:
        for workspace_id in ids:
            row = workspace_by_id(conn, workspace_id)
            if row:
                names[workspace_id] = str(row.get("name") or "")
    finally:
        close_quietly(conn)
    return names


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
        "detail": str(record.get("detail") or ""),
        "is_hidden": bool(record.get("is_hidden")),
        "url": report_url(workspace_id, report_id),
    }


GROUP_COLUMNS = {
    GROUP_MODEL: (
        (1, "Type"),
        (2, "Table"),
        (3, "Source"),
        (4, "Data type"),
        (5, "Size"),
        (6, "Status"),
        (7, "# of uses"),
        (8, "Format string"),
        (10, "Display folder"),
    ),
    GROUP_INDIRECT: (
        (1, "Type"),
        (2, "Table"),
        (3, "Source"),
        (4, "Data type"),
        (5, "Size"),
        (6, "Status"),
        (7, "# of uses"),
        (8, "Format string"),
        (10, "Display folder"),
    ),
    GROUP_CALC_TABLE: (
        (1, "Type"),
        (2, "Table"),
        (3, "Source"),
        (5, "Size"),
        (6, "Status"),
        (7, "# of uses"),
    ),
    GROUP_VISUALS: ((1, "Type"), (2, "Page"), (3, "Report"), (10, "Used as")),
    GROUP_VISUAL_FILTERS: ((1, "Type"), (2, "Page"), (3, "Report"), (10, "Used as")),
    GROUP_REPORT_FILTERS: ((1, "Type"), (2, "Page"), (3, "Report"), (10, "Used as")),
    GROUP_HIERARCHY: ((1, "Type"), (2, "Table"), (3, "Source")),
    GROUP_POWER_QUERY: ((1, "Type"), (2, "Table"), (3, "Source")),
    GROUP_DEFAULT_LABEL: ((1, "Type"), (2, "Table"), (3, "Source")),
    GROUP_KEY_COLUMN: (
        (1, "Type"),
        (2, "Table"),
        (3, "Source"),
        (5, "Size"),
        (6, "Status"),
        (7, "# of uses"),
    ),
    GROUP_RELATIONSHIPS: ((1, "Type"), (2, "Table"), (3, "Source")),
    GROUP_SECURITY: ((1, "Type"), (2, "Table"), (3, "Source")),
    GROUP_PAGE_FILTERS: ((1, "Type"), (2, "Page"), (3, "Report")),
    GROUP_SORTING: (
        (1, "Type"),
        (2, "Table"),
        (3, "Source"),
        (4, "Data type"),
        (5, "Size"),
        (6, "Status"),
        (7, "# of uses"),
        (8, "Format string"),
    ),
    GROUP_FIELD_PARAMETERS: ((1, "Type"), (2, "Table"), (3, "Source")),
}

GROUP_ICONS = {
    GROUP_MODEL: "measure",
    GROUP_INDIRECT: "dependencies",
    GROUP_CALC_TABLE: "table",
    GROUP_VISUALS: "page",
    GROUP_VISUAL_FILTERS: "filter",
    GROUP_REPORT_FILTERS: "filter",
    GROUP_HIERARCHY: "group",
    GROUP_POWER_QUERY: "query",
    GROUP_DEFAULT_LABEL: "column",
    GROUP_KEY_COLUMN: "link",
    GROUP_RELATIONSHIPS: "link",
    GROUP_SECURITY: "filter",
    GROUP_PAGE_FILTERS: "filter",
    GROUP_SORTING: "group",
    GROUP_FIELD_PARAMETERS: "group",
}


def _owner(analysis: Any) -> tuple[str, str]:
    """Nama dan tabel objek yang sedang dianalisa (kolom atau measure)."""
    node = getattr(analysis, "column", None) or getattr(analysis, "measure", None)
    if node is None:
        return "", ""
    name = getattr(node, "column", "") or getattr(node, "measure", "")
    return str(name or ""), str(getattr(node, "table", "") or "")


def _parse_object(text: str) -> tuple[str, str]:
    """Baca ``'Tabel'[Kolom]`` menjadi pasangan tabel/kolom."""
    value = str(text or "").strip()
    match = re.match(r"^'((?:[^']|'')+)'\s*\[([^\]]+)\]$", value)
    if not match:
        match = re.match(r"^([^\[\]]+?)\s*\[([^\]]+)\]$", value)
    if not match:
        return "", ""
    return match.group(1).replace("''", "'"), match.group(2)


def _m_query_table(text: str) -> str:
    """Nama tabel dari object referensi ``query 'Tabel'``."""
    value = str(text or "").strip()
    if value.lower().startswith("query "):
        value = value[6:].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.replace("''", "'")


def _child(
    name: str, icon: str, cells: Mapping[int, Any], href: str = ""
) -> dict[str, Any]:
    payload: dict[str, str] = {}
    for index, value in cells.items():
        text = str(value if value is not None else "").strip()
        if text:
            payload[str(index)] = text
    return {
        "name": str(name or ""),
        "icon": icon,
        "href": str(href or ""),
        "cells": payload,
    }


def _relationship_label(relation: Mapping[str, Any]) -> str:
    name = str(relation.get("name") or "")
    generated = bool(re.match(r"^AutoDetected_", name, re.IGNORECASE)) or bool(
        re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            name,
            re.IGNORECASE,
        )
    )
    if name and not generated:
        return name
    return (
        f"{relation.get('from_table')}[{relation.get('from_column')}] \u2192 "
        f"{relation.get('to_table')}[{relation.get('to_column')}]"
    )


def _relation_sides(relation: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [
        (
            str(relation.get(f"{side}_table") or "").casefold(),
            str(relation.get(f"{side}_column") or "").casefold(),
        )
        for side in ("from", "to")
    ]


def _filter_type(detail: str) -> str:
    return str(detail or "").split(" \u00b7 ")[0].strip()


def _security_table(detail: str) -> str:
    text = str(detail or "")
    match = re.search(r"table '((?:[^']|'')+)'", text)
    if match:
        return match.group(1).replace("''", "'")
    object_match = re.search(r"'((?:[^']|'')+)'\s*\[[^\]]+\]", text)
    return object_match.group(1).replace("''", "'") if object_match else ""


def _usage_groups(
    analysis: Any, context: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Kelompok pemakaian untuk baris anak tab "Semua hasil".

    Setiap grup membawa daftar kolom sendiri (``columns``: indeks kolom utama +
    label) dan baris anak menyimpan nilai pada indeks tersebut, sehingga
    sub-header dan isi baris selalu sejajar.
    """
    ctx = context or {}
    relations = [row for row in ctx.get("relationships") or [] if isinstance(row, Mapping)]
    columns = ctx.get("columns") or {}
    measures = ctx.get("measures") or {}
    name, table = _owner(analysis)
    own_table = table.casefold()
    mine = [
        relation
        for relation in relations
        if (own_table, name.casefold()) in _relation_sides(relation)
    ]
    records = [_record_payload(record) for record in (analysis.report_records or [])]
    refs_all = [
        {
            "kind": str(ref.kind or ""),
            "object": str(ref.object or ""),
            "detail": str(ref.detail or ""),
            "depth": int(getattr(ref, "depth", 1) or 1),
        }
        for ref in (analysis.model_refs or [])
    ]
    refs = [ref for ref in refs_all if is_counted_reference(ref)]
    direct_refs = [ref for ref in refs if ref["depth"] <= 1]
    indirect_refs = [ref for ref in refs if ref["depth"] > 1]
    groups: dict[str, list[dict[str, Any]]] = {key: [] for key in GROUP_ORDER}

    def reference_child(
        ref: dict[str, Any], *, indirect: bool = False
    ) -> dict[str, Any] | None:
        label = ARTIFACT_TYPES.get(ref["kind"])
        if not label:
            return None
        ref_table, ref_column = _parse_object(ref["object"])
        key = (ref_table.casefold(), ref_column.casefold())
        item = None
        if ref["kind"] == "measure":
            item = measures.get(key)
        elif ref["kind"] in ("calculated column", "calculated table column"):
            item = columns.get(key)
        if item:
            cells: dict[int, Any] = {
                1: label,
                2: item.get("table", ""),
                3: "Model",
                4: item.get("data_type", ""),
                5: "0 B" if ref["kind"] == "measure" else item.get("size", ""),
                6: item.get("status", ""),
                7: item.get("uses", 0),
                8: item.get("format_string", ""),
                10: item.get("display_folder", ""),
            }
        else:
            cells = {1: label, 2: ref_table, 3: "Model"}
        if indirect:
            cells[1] = f"{label} \u00b7 depth {ref['depth']}"
        return _child(
            ref["object"] or ref["detail"],
            "measure" if ref["kind"] == "measure" else "code",
            cells,
        )

    for ref in direct_refs:
        if ref["kind"] in {"calculated table", "hierarchy"}:
            continue
        child = reference_child(ref)
        if child is not None:
            groups[GROUP_MODEL].append(child)
    for ref in indirect_refs:
        child = reference_child(ref, indirect=True)
        if child is not None:
            groups[GROUP_INDIRECT].append(child)
    for ref in direct_refs:
        if ref["kind"] == "calculated table":
            groups[GROUP_CALC_TABLE].append(
                _child(
                    ref["object"] or ref["detail"],
                    "table",
                    {1: "Calculated table", 3: "Model"},
                )
            )
        elif ref["kind"] == "hierarchy":
            ref_table, _ = _parse_object(ref["object"])
            groups[GROUP_HIERARCHY].append(
                _child(
                    ref["object"] or ref["detail"],
                    "group",
                    {1: "Hierarchy", 2: ref_table, 3: "Model"},
                )
            )
        elif ref["kind"] == "default label":
            ref_table, _ = _parse_object(ref["object"])
            groups[GROUP_DEFAULT_LABEL].append(
                _child(
                    ref["object"] or ref["detail"],
                    "column",
                    {1: "Default label", 2: ref_table, 3: "Model"},
                )
            )
    for ref in refs_all:
        if ref["kind"] not in {"langkah M", "Power Query"}:
            continue
        if (
            ref["kind"] == "langkah M"
            and _m_query_table(ref["object"]).casefold() == table.casefold()
        ):
            # Query M tabel sendiri bukan pemakaian oleh objek lain.
            continue
        groups[GROUP_POWER_QUERY].append(
            _child(
                ref["object"] or ref["detail"],
                "query",
                {1: "Power Query", 3: "Model"},
            )
        )

    for record in records:
        if record["usage_kind"] not in {"field", "format"}:
            continue
        groups[GROUP_VISUALS].append(
            _child(
                record["visual_title"] or record["visual_type"] or "(visual)",
                "page",
                {
                    1: record["visual_type"],
                    2: record["page_name"],
                    3: record["report_name"],
                    10: record["detail"],
                },
                record["url"],
            )
        )

    # Key column hanya berasal dari IsKey (ModelReference "key column").
    # Relasi tidak boleh menambah grup ini: sisi many adalah foreign key, bukan
    # key column, dan Measure Killer juga hanya melaporkan IsKey di sini.
    for ref in refs:
        if ref["kind"] != "key column":
            continue
        ref_table, _ref_column = _parse_object(ref["object"])
        groups[GROUP_KEY_COLUMN].append(
            _child(
                ref["object"] or ref["detail"],
                "table",
                {1: "Key column", 2: ref_table, 3: "Model"},
            )
        )

    for relation in mine:
        if (str(relation.get("from_table") or "").casefold(),
                str(relation.get("from_column") or "").casefold()) == (own_table, name.casefold()):
            other = str(relation.get("to_table") or "")
        else:
            other = str(relation.get("from_table") or "")
        groups[GROUP_RELATIONSHIPS].append(
            _child(
                str(relation.get("label") or _relationship_label(relation)),
                "link",
                {
                    1: "Active" if relation.get("is_active") else "Inactive",
                    2: other,
                    3: "Model",
                },
            )
        )

    for ref in refs:
        label = SECURITY_TYPES.get(ref["kind"])
        if not label:
            continue
        groups[GROUP_SECURITY].append(
            _child(
                ref["object"] or label,
                "filter",
                {1: label, 2: _security_table(ref["detail"]), 3: "Model"},
            )
        )

    for record in records:
        if record["usage_kind"] != "filter-visual":
            continue
        groups[GROUP_VISUAL_FILTERS].append(
            _child(
                record["visual_title"] or record["visual_type"] or "(visual)",
                "filter",
                {
                    1: record["visual_type"],
                    2: record["page_name"],
                    3: record["report_name"],
                    10: record["detail"],
                },
                record["url"],
            )
        )

    for record in records:
        if record["usage_kind"] != "filter-report":
            continue
        groups[GROUP_REPORT_FILTERS].append(
            _child(
                record["report_name"] or "(report)",
                "filter",
                {1: "Filter report", 3: record["report_name"], 10: record["detail"]},
                record["url"],
            )
        )

    for record in records:
        if record["usage_kind"] != "filter-page":
            continue
        groups[GROUP_PAGE_FILTERS].append(
            _child(
                name,
                "filter",
                {
                    1: _filter_type(record["detail"]) or USAGE_LABELS["filter-page"],
                    2: record["page_name"],
                    3: record["report_name"],
                },
                record["url"],
            )
        )

    for ref in refs:
        if ref["kind"] != KIND_SORT:
            continue
        owner_table, owner_column = _parse_object(ref["object"])
        item = columns.get((owner_table.casefold(), owner_column.casefold())) or measures.get(
            (owner_table.casefold(), owner_column.casefold())
        ) or {}
        groups[GROUP_SORTING].append(
            _child(
                ref["object"],
                "group",
                {
                    1: "Sort by",
                    2: owner_table,
                    3: "Model",
                    4: item.get("data_type", ""),
                    5: item.get("size", ""),
                    6: item.get("status", ""),
                    7: item.get("uses", 0),
                    8: item.get("format_string", ""),
                },
            )
        )

    for ref in refs:
        if ref["kind"] != KIND_FIELD_PARAMETER:
            continue
        parameter_table = ref["object"].strip("'")
        groups[GROUP_FIELD_PARAMETERS].append(
            _child(
                parameter_table,
                "group",
                {1: "Field parameter", 2: table, 3: "Model"},
            )
        )

    return _groups_payload(groups)


def _function_groups(
    analysis: Any, context: Mapping[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Grup pemakaian untuk user-defined function (pemanggil di model)."""
    ctx = context or {}
    measures = ctx.get("measures") or {}
    columns = ctx.get("columns") or {}
    groups: dict[str, list[dict[str, Any]]] = {key: [] for key in GROUP_ORDER}
    for ref in getattr(analysis, "model_refs", []) or []:
        kind = str(getattr(ref, "kind", "") or "")
        if kind not in {"measure", "calculated column", "user-defined function"}:
            continue
        label = {
            "measure": "Measure",
            "calculated column": "Calculated column",
            "user-defined function": "User-defined function",
        }[kind]
        ref_table, ref_column = _parse_object(str(getattr(ref, "object", "")))
        key = (ref_table.casefold(), ref_column.casefold())
        item = measures.get(key) if kind == "measure" else columns.get(key)
        cells: dict[int, Any] = {1: label, 2: ref_table, 3: "Model"}
        if item:
            cells.update(
                {
                    4: item.get("data_type", ""),
                    5: "0 B" if kind == "measure" else item.get("size", ""),
                    6: item.get("status", ""),
                    7: item.get("uses", 0),
                    8: item.get("format_string", ""),
                    10: item.get("display_folder", ""),
                }
            )
        groups[GROUP_MODEL].append(
            _child(
                str(getattr(ref, "object", "") or getattr(ref, "detail", "")),
                "measure" if kind == "measure" else "code",
                cells,
            )
        )
    return _groups_payload(groups)


def _groups_payload(
    groups: Mapping[str, list[dict[str, Any]]]
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for key in GROUP_ORDER:
        if not groups.get(key):
            continue
        payload.append(
            {
                "label": key,
                "icon": GROUP_ICONS[key],
                "count": len(groups[key]),
                "columns": [
                    {"index": index, "label": label}
                    for index, label in GROUP_COLUMNS[key]
                ],
                "rows": groups[key],
            }
        )
    return payload


def _ref_counts(analysis: Any) -> tuple[int, int]:
    refs = [
        ref
        for ref in (getattr(analysis, "model_refs", []) or [])
        if is_counted_reference(ref)
    ]
    direct = sum(
        1 for ref in refs if int(getattr(ref, "depth", 1) or 1) <= 1
    )
    return direct, len(refs) - direct


def _column_row(
    analysis: Any,
    context: Mapping[str, Any] | None = None,
    *,
    with_children: bool = True,
) -> dict[str, Any]:
    column = analysis.column
    size_bytes = int(getattr(column, "size_total_bytes", 0) or 0)
    direct_refs, transitive_refs = _ref_counts(analysis)
    return {
        "name": str(getattr(column, "column", "")),
        "type": str(getattr(column, "column_type", "")),
        "table": str(getattr(column, "table", "")),
        "source": "Model",
        "data_type": display_data_type(getattr(column, "data_type", "")),
        "size": format_bytes(size_bytes),
        "size_bytes": size_bytes,
        "status": str(analysis.status or ""),
        "uses": len(
            [row for row in (analysis.report_records or []) if is_counted_record(row)]
        ) + direct_refs,
        "direct_refs": direct_refs,
        "transitive_refs": transitive_refs,
        "reports": len(
            {str(row.get("report_id") or "") for row in analysis.report_records or []}
        ),
        "format_string": str(getattr(column, "format_string", "")),
        "has_error": bool(getattr(column, "has_error", False)),
        "display_folder": str(getattr(column, "display_folder", "")),
        "is_hidden": bool(getattr(column, "is_hidden", False)),
        "is_calculated": bool(getattr(column, "is_calculated", False)),
        "is_available_in_mdx": bool(
            getattr(column, "is_available_in_mdx", True)
        ),
        "reason": str(analysis.reason or ""),
        "rows": int(getattr(column, "rows", 0) or 0),
        "size_breakdown": {
            "data": int(getattr(column, "size_data_bytes", 0) or 0),
            "hierarchy": int(getattr(column, "size_hierarchy_bytes", 0) or 0),
            "dictionary": int(getattr(column, "size_dictionary_bytes", 0) or 0),
        },
        "expression": str(getattr(column, "expression", "")),
        "children": _usage_groups(analysis, context) if with_children else [],
    }


def _measure_row(
    analysis: Any,
    context: Mapping[str, Any] | None = None,
    *,
    with_children: bool = True,
) -> dict[str, Any]:
    measure = analysis.measure
    direct_refs, transitive_refs = _ref_counts(analysis)
    return {
        "name": str(getattr(measure, "measure", "")),
        "type": "measure (hidden)" if getattr(measure, "is_hidden", False) else "measure",
        "table": str(getattr(measure, "table", "")),
        "source": "Model",
        "data_type": display_data_type(getattr(measure, "data_type", "")),
        "size": "-",
        "size_bytes": 0,
        "status": str(analysis.status or ""),
        "uses": len(
            [row for row in (analysis.report_records or []) if is_counted_record(row)]
        ) + direct_refs,
        "direct_refs": direct_refs,
        "transitive_refs": transitive_refs,
        "reports": len(
            {str(row.get("report_id") or "") for row in analysis.report_records or []}
        ),
        "format_string": str(getattr(measure, "format_string", "")),
        "has_error": bool(getattr(measure, "has_error", False)),
        "display_folder": str(getattr(measure, "display_folder", "")),
        "is_hidden": bool(getattr(measure, "is_hidden", False)),
        "reason": str(analysis.reason or ""),
        "rows": 0,
        "size_breakdown": {"data": 0, "hierarchy": 0, "dictionary": 0},
        "expression": str(getattr(measure, "expression", "")),
        "children": _usage_groups(analysis, context) if with_children else [],
    }


def _function_row(
    analysis: Any,
    context: Mapping[str, Any] | None = None,
    *,
    with_children: bool = True,
) -> dict[str, Any]:
    function = analysis.function
    refs = list(getattr(analysis, "model_refs", []) or [])
    return {
        "name": str(getattr(function, "name", "")),
        "type": "User-defined function",
        "table": "",
        "source": "Model",
        "data_type": "",
        "size": "-",
        "size_bytes": 0,
        "status": str(analysis.status or ""),
        "uses": len(refs),
        "direct_refs": len(refs),
        "transitive_refs": 0,
        "reports": 0,
        "format_string": "",
        "has_error": bool(getattr(function, "has_error", False)),
        "display_folder": "",
        "is_hidden": bool(getattr(function, "is_hidden", False)),
        "is_calculated": False,
        "reason": str(analysis.reason or ""),
        "rows": 0,
        "size_breakdown": {"data": 0, "hierarchy": 0, "dictionary": 0},
        "expression": str(getattr(function, "expression", "")),
        "children": _function_groups(analysis, context) if with_children else [],
    }


def _hierarchy_groups(analysis: Any) -> list[dict[str, Any]]:
    """Grup pemakaian untuk objek hierarchy (visual + filter)."""
    records = [_record_payload(record) for record in (analysis.report_records or [])]
    groups: dict[str, list[dict[str, Any]]] = {key: [] for key in GROUP_ORDER}
    for record in records:
        kind = record["usage_kind"]
        if kind in {"field", "format", "calculation"}:
            groups[GROUP_VISUALS].append(
                _child(
                    record["visual_title"] or record["visual_type"] or "(visual)",
                    "page",
                    {
                        1: record["visual_type"],
                        2: record["page_name"],
                        3: record["report_name"],
                        10: record["detail"],
                    },
                    record["url"],
                )
            )
        elif kind == "filter-visual":
            groups[GROUP_VISUAL_FILTERS].append(
                _child(
                    record["visual_title"] or record["visual_type"] or "(visual)",
                    "filter",
                    {
                        1: record["visual_type"],
                        2: record["page_name"],
                        3: record["report_name"],
                        10: record["detail"],
                    },
                    record["url"],
                )
            )
        elif kind == "filter-page":
            groups[GROUP_PAGE_FILTERS].append(
                _child(
                    analysis.name,
                    "filter",
                    {
                        1: _filter_type(record["detail"])
                        or USAGE_LABELS["filter-page"],
                        2: record["page_name"],
                        3: record["report_name"],
                    },
                    record["url"],
                )
            )
        elif kind == "filter-report":
            groups[GROUP_REPORT_FILTERS].append(
                _child(
                    record["report_name"] or "(report)",
                    "filter",
                    {
                        1: "Filter report",
                        3: record["report_name"],
                        10: record["detail"],
                    },
                    record["url"],
                )
            )
    return [
        {
            "label": key,
            "icon": GROUP_ICONS[key],
            "count": len(groups[key]),
            "columns": [
                {"index": index, "label": label}
                for index, label in GROUP_COLUMNS[key]
            ],
            "rows": groups[key],
        }
        for key in GROUP_ORDER
        if groups[key]
    ]


def _hierarchy_row(analysis: Any) -> dict[str, Any]:
    definition = getattr(analysis, "hierarchy", {}) or {}
    return {
        "name": str(getattr(analysis, "name", "")),
        "type": "Hierarchy",
        "table": str(getattr(analysis, "table", "")),
        "source": "Model",
        "data_type": "",
        "size": "0 B",
        "size_bytes": 0,
        "status": str(analysis.status or ""),
        "uses": int(getattr(analysis, "use_count", 0) or 0),
        "direct_refs": 0,
        "transitive_refs": 0,
        "reports": int(getattr(analysis, "report_count", 0) or 0),
        "format_string": "",
        "has_error": False,
        "display_folder": str(definition.get("display_folder") or ""),
        "is_hidden": bool(definition.get("is_hidden")),
        "is_calculated": False,
        "reason": str(analysis.reason or ""),
        "rows": 0,
        "size_breakdown": {"data": 0, "hierarchy": 0, "dictionary": 0},
        "expression": "",
        "levels": str(definition.get("levels") or ""),
        "children": _hierarchy_groups(analysis),
    }


def _table_children(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Kelompokkan baris ekspor tabel untuk tampilan tab Tables."""
    order: list[str] = []
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get("usage_type") or "")
        if not label:
            continue
        if label not in groups:
            groups[label] = []
            order.append(label)
        has_error = row.get("has_error")
        if has_error is True:
            has_error_text = "Yes"
        elif has_error is False:
            has_error_text = "No"
        else:
            has_error_text = str(has_error or "")
        kind = str(row.get("kind") or "")
        item = (
            {
                "kind": kind,
                "table": str(row.get("table") or ""),
                "name": str(row.get("name") or ""),
            }
            if kind
            else None
        )
        uses = row.get("uses")
        uses_text = "" if uses is None else str(uses)
        groups[label].append(
            {
                "name": str(row.get("name") or ""),
                "icon": str(row.get("icon") or "group"),
                "status": str(row.get("status") or ""),
                "item": item,
                "cells": {
                    "1": str(row.get("object_type") or ""),
                    "2": str(row.get("table") or ""),
                    "3": "Model",
                    "4": str(row.get("data_type") or ""),
                    "5": str(row.get("size") or ""),
                    "6": str(row.get("status") or ""),
                    "7": uses_text,
                    "8": has_error_text,
                },
            }
        )
    return [
        {
            "label": label,
            "icon": TABLE_GROUP_ICONS.get(label, "group"),
            "count": len(groups[label]),
            "rows": groups[label],
        }
        for label in order
    ]


def _table_rows(result: Any) -> list[dict[str, Any]]:
    """Ringkasan per tabel (dipakai tab Tables dan graph relasi)."""
    columns_by_table: dict[str, list[Any]] = {}
    for column in result.columns:
        columns_by_table.setdefault(column.column.table.casefold(), []).append(column)
    measures_by_table: dict[str, list[Any]] = {}
    for measure in result.measures:
        measures_by_table.setdefault(measure.measure.table.casefold(), []).append(measure)
    table_groups = {
        str(group.get("table") or "").casefold(): group
        for group in build_table_groups(result)
    }
    rows: list[dict[str, Any]] = []
    for table in getattr(result.stats, "tables", []) or []:
        key = table.table.casefold()
        columns = columns_by_table.get(key, [])
        measures = measures_by_table.get(key, [])
        items = list(columns) + list(measures)
        counts: dict[str, int] = {}
        for item in items:
            counts[item.status] = counts.get(item.status, 0) + 1
        used = sum(1 for item in items if item.status != "Unused")
        size_bytes = int(table.size_total_bytes)
        group = table_groups.get(key) or {}
        table_uses = group.get("uses")
        if table_uses is None:
            table_uses = used
        total_items = group.get("total")
        if total_items is None:
            total_items = len(items)
        used_items = group.get("used")
        if used_items is None:
            used_items = used
        rows.append(
            {
                "name": table.table,
                "id": int(getattr(table, "table_id", 0) or 0),
                "type_label": str(group.get("type_label") or "Table"),
                "column_count": len(columns),
                "measure_count": len(measures),
                "rows": int(table.rows),
                "size": format_bytes(size_bytes),
                "size_bytes": size_bytes,
                "storage_mode": str(table.storage_mode or ""),
                "partition_count": int(table.partition_count or 0),
                "uses": int(table_uses),
                "table_uses": int(table_uses),
                "status_label": str(group.get("status") or ""),
                "has_error": bool(group.get("has_error", False)),
                "total_items": int(total_items),
                "used_items": int(used_items),
                "statuses": counts,
                "children": _table_children(group.get("rows") or []),
            }
        )
    return rows


def _cardinality_code(value: Any) -> str:
    return {"one": "1", "many": "N", "none": "0"}.get(
        str(value or "").casefold(), str(value or "") or "?"
    )


def _relationship_row(item: Mapping[str, Any]) -> dict[str, Any]:
    from_table = str(item.get("from_table") or "")
    from_column = str(item.get("from_column") or "")
    to_table = str(item.get("to_table") or "")
    to_column = str(item.get("to_column") or "")
    cardinality = (
        f"{_cardinality_code(item.get('from_cardinality'))} \u2190 "
        f"{_cardinality_code(item.get('to_cardinality'))}"
    )
    cross_filtering = str(item.get("cross_filtering") or "")
    cross = {
        "oneDirection": "Single",
        "bothDirections": "Both",
        "automatic": "Auto",
    }.get(cross_filtering, cross_filtering)
    is_active = bool(item.get("is_active"))
    return {
        "name": str(item.get("name") or ""),
        "label": (
            f"'{from_table}'[{from_column}] {cardinality} "
            f"'{to_table}'[{to_column}]"
        ),
        "from_table": from_table,
        "from_column": from_column,
        "to_table": to_table,
        "to_column": to_column,
        "type": "Active" if is_active else "Inactive",
        "cross": cross,
        "cross_filtering": cross_filtering,
        "cardinality": cardinality,
        "status": "Used" if is_active else "Unused",
        "auto": "Yes" if item.get("is_auto") else "No",
        "used": int(item.get("dependent_count") or 0),
        "security_filtering": str(item.get("security_filtering") or ""),
        "is_active": is_active,
        "join_on_date_behavior": str(item.get("join_on_date_behavior") or ""),
        "from_cardinality": str(item.get("from_cardinality") or ""),
        "to_cardinality": str(item.get("to_cardinality") or ""),
    }


def serialize_result(
    result: Any, workspace_names: Mapping[str, str] | None = None
) -> dict[str, Any]:
    stats = result.stats
    names = workspace_names or {}
    health = build_health(result)
    broken_counts = broken_visual_counts(result)
    reports = []
    pages_map = dict(getattr(result, "report_pages", {}) or {})
    for item in result.reports or []:
        if not isinstance(item, Mapping):
            continue
        workspace_id = str(item.get("workspace_id") or "")
        report_id = str(item.get("report_id") or item.get("id") or "")
        reports.append(
            {
                "report_id": report_id,
                "report_name": str(item.get("report_name") or item.get("name") or ""),
                "workspace_id": workspace_id,
                "workspace_name": str(
                    item.get("workspace_name") or names.get(workspace_id) or ""
                ),
                "format": str(
                    item.get("report_format") or item.get("format") or ""
                ),
                "status": str(item.get("status") or ""),
                "message": str(item.get("message") or ""),
                "modified_at": str(item.get("modified_at") or ""),
                "page_count": int(item.get("page_count") or 0),
                "visual_count": int(item.get("visual_count") or 0),
                "field_count": int(item.get("field_count") or 0),
                "unresolved_count": int(item.get("unresolved_count") or 0),
                "broken_visuals": int(broken_counts.get(report_id, 0)),
                "health_score": (health["practice"].get(report_id) or {}).get("score"),
                "is_active": bool(item.get("is_active", 1)),
                "theme": str(item.get("theme") or ""),
                "pages": [
                    {
                        "page_id": str(page.get("page_id") or ""),
                        "page_name": str(page.get("page_name") or ""),
                        "order_index": int(page.get("order_index") or 0),
                        "is_hidden": bool(page.get("is_hidden")),
                        "visual_count": int(page.get("visual_count") or 0),
                        "field_count": int(page.get("field_count") or 0),
                    }
                    for page in pages_map.get(report_id, [])
                    if isinstance(page, Mapping)
                ],
            }
        )
    unused_bytes = int(result.unused_bytes)
    hidden_columns = sum(
        1 for column in result.columns if bool(getattr(column.column, "is_hidden", False))
    )
    helper_measures = sum(
        1
        for measure in result.measures
        if measure.measure.table.casefold() == "_measures"
    )
    page_total = sum(int(item.get("page_count") or 0) for item in reports)
    visual_total = sum(int(item.get("visual_count") or 0) for item in reports)
    table_rows = _table_rows(result)
    relationship_rows = [
        _relationship_row(item)
        for item in (getattr(result, "relationships", []) or [])
        if isinstance(item, Mapping)
    ]
    child_context = {
        "relationships": relationship_rows,
        "tables": {row["name"].casefold(): row for row in table_rows},
    }
    column_rows = [
        _column_row(column, with_children=False) for column in result.columns
    ]
    measure_rows = [
        _measure_row(measure, with_children=False) for measure in result.measures
    ]
    hierarchy_rows = [
        _hierarchy_row(hierarchy)
        for hierarchy in (getattr(result, "hierarchies", []) or [])
    ]
    function_rows = [
        _function_row(function, with_children=False)
        for function in (getattr(result, "functions", []) or [])
    ]
    child_context["columns"] = {
        (row["table"].casefold(), row["name"].casefold()): row
        for row in column_rows
    }
    child_context["measures"] = {
        (row["table"].casefold(), row["name"].casefold()): row
        for row in measure_rows
    }
    for analysis, row in zip(result.columns, column_rows):
        row["children"] = _usage_groups(analysis, child_context)
    for analysis, row in zip(result.measures, measure_rows):
        row["children"] = _usage_groups(analysis, child_context)
    for analysis, row in zip(
        getattr(result, "functions", []) or [], function_rows
    ):
        row["children"] = _function_groups(analysis, child_context)
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
        "reports_included": bool(getattr(result, "reports_included", True)),
        "totals": {
            "model_bytes": int(result.dataset_bytes),
            "data_bytes": int(stats.data_bytes),
            "hierarchy_bytes": int(stats.hierarchy_bytes),
            "dictionary_bytes": int(stats.dictionary_bytes),
            "columns": len(result.columns),
            "measures": len(result.measures),
            "hierarchies": len(hierarchy_rows),
            "functions": len(function_rows),
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
            "pages": page_total,
            "visuals": visual_total,
            "hidden_columns": hidden_columns,
            "helper_measures": helper_measures,
            "tables": len(getattr(result.stats, "tables", []) or []),
        },
        "counts": {
            "columns": dict(result.status_counts),
            "measures": dict(result.measure_status_counts),
            "functions": dict(getattr(result, "function_status_counts", {}) or {}),
        },
        "columns": column_rows,
        "measures": measure_rows,
        "hierarchies": hierarchy_rows,
        "functions": function_rows,
        "reports": reports,
        "health": health,
        "best_practice": build_best_practice(result),
        "tables": table_rows,
        "relationships": relationship_rows,
        "roles": list(getattr(result, "roles", []) or []),
        "m_queries": [
            {
                "name": str(item.get("name") or ""),
                "kind": str(item.get("kind") or ""),
                "source": str(item.get("source") or ""),
                "expression": str(item.get("expression") or ""),
                "warning": str(item.get("warning") or ""),
                "detail": str(item.get("detail") or ""),
            }
            for item in (getattr(result, "m_queries", []) or [])
            if isinstance(item, Mapping)
        ],
        "messages": list(result.messages),
    }


def report_detail_payload(
    store: SettingsStore, dataset_id: str, report_id: str
) -> dict[str, Any]:
    dataset = str(dataset_id or "").strip()
    report = str(report_id or "").strip()
    if not dataset or not report:
        raise ExtractionError("Choose a dataset and report.")
    session = _session(dataset, create=False)
    if session is None:
        raise ExtractionError(
            "No analysis results in this session yet. Run the analysis first "
            "(results are not saved to the database)."
        )
    with session.lock:
        return report_detail(session.conn, dataset, report)


def lineage_payload(
    store: SettingsStore,
    dataset_id: str,
    kind: str,
    table: str,
    name: str,
    *,
    direction: str = "both",
    depth: int = 4,
    category: str = "all",
    outline_mode: str = "compact",
) -> dict[str, Any]:
    """Graph lineage satu kolom/measure dari sesi analisa in-memory."""
    dataset = str(dataset_id or "").strip()
    if not dataset:
        raise ExtractionError("Choose a dataset.")
    session = _session(dataset, create=False)
    if session is None:
        raise ExtractionError(
            "No analysis results in this session yet. Run the analysis first "
            "(results are not saved to the database)."
        )
    with session.lock:
        result = snapshot_from_connection(session.conn, dataset)
    if result is None:
        raise ExtractionError(
            "No analysis results for this dataset yet. Run the analysis first "
            "(results are not saved to the database)."
        )
    try:
        if str(kind).strip().lower() == "table":
            return build_table_lineage(
                result,
                table=table,
                direction=direction,
                depth=depth,
                outline_mode=outline_mode,
            )
        return build_lineage(
            result,
            kind=kind,
            table=table,
            name=name,
            direction=direction,
            depth=depth,
            category=category,
            outline_mode=outline_mode,
        )
    except ValueError as exc:
        raise ExtractionError(str(exc)) from exc


def _session_result(dataset_id: str) -> Any:
    dataset = str(dataset_id or "").strip()
    if not dataset:
        raise ExtractionError("Choose a dataset.")
    session = _session(dataset, create=False)
    if session is None:
        raise ExtractionError(
            "No analysis results in this session yet. Run the analysis first "
            "(results are not saved to the database)."
        )
    with session.lock:
        result = snapshot_from_connection(session.conn, dataset)
    if result is None:
        raise ExtractionError(
            "No analysis results for this dataset yet. Run the analysis first "
            "(results are not saved to the database)."
        )
    return result


def _find_analysis(result: Any, kind: str, table: str, name: str) -> Any:
    wanted_kind = str(kind or "").strip().lower()
    wanted_table = str(table or "").casefold()
    wanted_name = str(name or "").casefold()
    if wanted_kind == "function":
        for item in getattr(result, "functions", []) or []:
            function = getattr(item, "function", None)
            if (
                function is not None
                and str(getattr(function, "name", "")).casefold() == wanted_name
            ):
                return item
        raise ExtractionError(
            "User-defined function was not found in the analysis results. "
            "Run the analysis again."
        )
    if wanted_kind == "hierarchy":
        for item in getattr(result, "hierarchies", []) or []:
            if (
                str(getattr(item, "table", "")).casefold() == wanted_table
                and str(getattr(item, "name", "")).casefold() == wanted_name
            ):
                return item
        raise ExtractionError(
            "Hierarchy was not found in the analysis results. "
            "Run the analysis again."
        )
    items = getattr(
        result, "measures" if wanted_kind == "measure" else "columns", []
    ) or []
    for item in items:
        node = getattr(item, "measure", None) or getattr(item, "column", None)
        if node is None:
            continue
        node_name = getattr(node, "measure", "") or getattr(node, "column", "")
        if (
            str(getattr(node, "table", "")).casefold() == wanted_table
            and str(node_name).casefold() == wanted_name
        ):
            return item
    raise ExtractionError(
        "Column/measure was not found in the analysis results. Run the analysis again."
    )


def preview_payload(
    store: SettingsStore,
    dataset_id: str,
    kind: str,
    table: str,
    name: str,
    *,
    limit: int = DEFAULT_ROWS,
) -> dict[str, Any]:
    """Preview nilai satu kolom/measure (read-only, job thread)."""
    result = _session_result(dataset_id)
    analysis = _find_analysis(result, kind, table, name)
    node = getattr(analysis, "measure", None) or getattr(analysis, "column", None)
    node_table = str(getattr(node, "table", "") or table)
    node_name = str(
        getattr(node, "measure", "") or getattr(node, "column", "") or name
    )
    principal: Any = store.auth()
    principal.validate()
    query = build_raw_query(
        "measure" if str(kind).lower() == "measure" else "column",
        node_table,
        node_name,
        limit=limit,
    )
    tokens = EntraTokens(principal)
    endpoint = workspace_endpoint(
        principal.tenant_id or "myorg", result.workspace_name
    )
    try:
        client = open_client(
            endpoint=endpoint,
            catalog=result.dataset_name,
            tokens=tokens,
            interactive=getattr(principal, "interactive_xmla", False),
        )
    except XmlaError as exc:
        raise ExtractionError(
            f"Cannot connect to the XMLA workspace '{result.workspace_name}': "
            f"{exc}\nMake sure XMLA Read is enabled and the account can access the workspace."
        ) from exc
    try:
        rows = client.query_sql(query, timeout=QUERY_TIMEOUT)
    except XmlaError as exc:
        raise ExtractionError(f"Raw data query failed: {exc}") from exc
    finally:
        client.close()
    return build_preview_payload(rows, query=query, limit=limit)


def details_payload(
    store: SettingsStore,
    dataset_id: str,
    kind: str,
    table: str,
    name: str,
) -> dict[str, Any]:
    """Objek detail kolom/measure dari sesi analisa (tanpa XMLA)."""
    result = _session_result(dataset_id)
    analysis = _find_analysis(result, kind, table, name)
    try:
        return {"details": item_details(result, analysis, kind=kind)}
    except ValueError as exc:
        raise ExtractionError(str(exc)) from exc


def raw_metadata_payload(
    store: SettingsStore,
    dataset_id: str,
    kind: str,
    table: str,
    name: str,
) -> dict[str, Any]:
    """Baris mentah TMSCHEMA untuk satu objek (read-only)."""
    result = _session_result(dataset_id)
    wanted_kind = str(kind or "").strip().lower()
    if wanted_kind not in {"column", "measure", "function", "hierarchy", "table"}:
        raise ExtractionError("Raw metadata kind must be column, measure, function, hierarchy, or table.")
    node_table = str(table or "")
    node_name = str(name or "")
    column_id: int | None = None
    dmv = COLUMN_DMV
    if wanted_kind == "table":
        node_table = table
        node_name = name
        dmv = TABLE_DMV
    else:
        analysis = _find_analysis(result, wanted_kind, table, name)
        if wanted_kind == "function":
            node = analysis.function
            node_table = ""
            node_name = str(getattr(node, "name", "") or name)
            dmv = FUNCTION_DMV
        elif wanted_kind == "hierarchy":
            node = analysis.hierarchy
            node_table = str(getattr(analysis, "table", "") or table)
            node_name = str(getattr(analysis, "name", "") or name)
            dmv = HIERARCHY_DMV
        elif wanted_kind == "measure":
            node = analysis.measure
            node_table = str(getattr(node, "table", "") or table)
            node_name = str(getattr(node, "measure", "") or name)
            dmv = MEASURE_DMV
        else:
            node = analysis.column
            node_table = str(getattr(node, "table", "") or table)
            node_name = str(getattr(node, "column", "") or name)
            column_id = int(getattr(node, "column_id", 0) or 0)
            dmv = COLUMN_DMV
    principal: Any = store.auth()
    principal.validate()
    tokens = EntraTokens(principal)
    endpoint = workspace_endpoint(
        principal.tenant_id or "myorg", result.workspace_name
    )
    try:
        client = open_client(
            endpoint=endpoint,
            catalog=result.dataset_name,
            tokens=tokens,
            interactive=getattr(principal, "interactive_xmla", False),
        )
    except XmlaError as exc:
        raise ExtractionError(
            f"Cannot connect to the XMLA workspace '{result.workspace_name}': "
            f"{exc}\nMake sure XMLA Read is enabled and the account can access the workspace."
        ) from exc
    try:
        tables = client.query(TABLE_DMV)
        rows = client.query(dmv)
    except XmlaError as exc:
        raise ExtractionError(f"TMSCHEMA metadata could not be read: {exc}") from exc
    finally:
        client.close()
    row = find_row(
        rows,
        kind=wanted_kind,
        table=node_table,
        name=node_name,
        column_id=column_id,
        tables=tables,
    )
    payload = metadata_payload(
        row, kind=wanted_kind, dmv=dmv, table=node_table, name=node_name
    )
    if not payload["found"]:
        label = f"'{node_table}'[{node_name}]" if node_table else f"'{node_name}'"
        raise ExtractionError(
            f"{dmv} row for {label} was not found. "
            "Run the analysis again or check the object name."
        )
    return payload


def tmsl_payload(
    store: SettingsStore, dataset_id: str, log: Any = None
) -> dict[str, Any]:
    """Ambil TMSL semantic model dari Fabric API (bukan TOM)."""
    result = _session_result(dataset_id)
    principal: Any = store.auth()
    principal.validate()
    tokens = EntraTokens(principal)
    client = FabricReportClient(
        fabric_provider(tokens), poll_wait=1, log=log or (lambda _m: None)
    )
    try:
        data = client.get_semantic_model_tmsl(
            result.workspace_id, result.dataset_id
        )
    finally:
        client.close()
    text = json.dumps(data, indent=2, ensure_ascii=False)
    return {
        "model": result.dataset_name,
        "workspace": result.workspace_name,
        "tmsl": text,
        "bytes": len(text.encode("utf-8")),
    }


def export_object(
    store: SettingsStore, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Tulis detail objek (full/simple/no_dax) ke JSON di ``outputs``."""
    dataset_id = str(payload.get("dataset_id") or "").strip()
    kind = str(payload.get("kind") or "column").strip().lower()
    table = str(payload.get("table") or "")
    name = str(payload.get("name") or "")
    mode = str(payload.get("mode") or "full").strip().lower()
    result = _session_result(dataset_id)
    try:
        path = write_object_json(
            result,
            outputs_dir(),
            kind=kind,
            table=table,
            name=name,
            mode=mode,
        )
    except OSError as exc:
        raise ExtractionError(
            f"Could not write the export file: {exc}. Close the open file "
            "and try again."
        ) from exc
    return {"path": str(path), "bytes": path.stat().st_size}


def export_uses(
    store: SettingsStore, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Tulis pemakaian objek ke Excel di ``outputs``."""
    dataset_id = str(payload.get("dataset_id") or "").strip()
    kind = str(payload.get("kind") or "column").strip().lower()
    table = str(payload.get("table") or "")
    name = str(payload.get("name") or "")
    result = _session_result(dataset_id)
    try:
        path = write_uses_xlsx(
            result,
            outputs_dir(),
            kind=kind,
            table=table,
            name=name,
        )
    except OSError as exc:
        raise ExtractionError(
            f"Could not write the export file: {exc}. Close the open file "
            "and try again."
        ) from exc
    return {"path": str(path), "bytes": path.stat().st_size}


def export_lineage(
    store: SettingsStore, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Tulis node/edge/JSON lineage ke ``outputs``."""
    dataset_id = str(payload.get("dataset_id") or "").strip()
    kind = str(payload.get("kind") or "column").strip().lower()
    table = str(payload.get("table") or "")
    name = str(payload.get("name") or "")
    direction = str(payload.get("direction") or "both").strip().lower()
    category = str(payload.get("category") or "all").strip().lower()
    export_format = str(payload.get("format") or "all").strip().lower()
    if export_format not in {"all", "csv", "json"}:
        raise ExtractionError("Export format must be csv, json, or all.")
    result = _session_result(dataset_id)
    try:
        if kind == "table":
            data = build_table_lineage(
                result,
                table=table or name,
                direction=direction,
            )
        else:
            data = build_lineage(
                result,
                kind=kind,
                table=table,
                name=name,
                direction=direction,
                category=category,
            )
    except ValueError as exc:
        raise ExtractionError(str(exc)) from exc
    formats = {"csv", "json"} if export_format == "all" else {export_format}
    try:
        return write_lineage_files(
            data, outputs_dir(), table=table, name=name, formats=formats
        )
    except OSError as exc:
        raise ExtractionError(
            f"Could not write the export file: {exc}. Close the open file "
            "and try again."
        ) from exc


def export_lineage_image(
    store: SettingsStore, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Tulis gambar lineage (SVG/PNG) dari payload klien ke ``outputs``."""
    table = str(payload.get("table") or "")
    name = str(payload.get("name") or "")
    image_format = str(payload.get("format") or "").strip().lower()
    content = payload.get("content")
    try:
        return write_lineage_image(
            str(content or ""),
            outputs_dir(),
            table=table,
            name=name,
            image_format=image_format,
        )
    except ValueError as exc:
        raise ExtractionError(str(exc)) from exc
    except OSError as exc:
        raise ExtractionError(
            f"Could not write the lineage image: {exc}. Close the open file "
            "and try again."
        ) from exc


def export_dependencies(
    store: SettingsStore, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Tulis dependensi model + pemakaian report ke ``outputs``."""
    dataset_id = str(payload.get("dataset_id") or "").strip()
    kind = str(payload.get("kind") or "column").strip().lower()
    table = str(payload.get("table") or "")
    name = str(payload.get("name") or "")
    result = _session_result(dataset_id)
    rows = dependency_rows(result, kind=kind, table=table, name=name)
    try:
        path = write_dependencies_csv(
            rows, outputs_dir(), table=table, name=name
        )
    except OSError as exc:
        raise ExtractionError(
            f"Could not write the export file: {exc}. Close the open file "
            "and try again."
        ) from exc
    return {"path": str(path), "rows": len(rows)}


def run_job(
    store: SettingsStore, payload: Mapping[str, Any], log: Any, cancel: Any
) -> dict[str, Any]:
    workspace_id = str(payload.get("workspace_id") or "").strip()
    dataset_id = str(payload.get("dataset_id") or "").strip()
    if not workspace_id or not dataset_id:
        raise ExtractionError("Choose a workspace and semantic model first.")
    principal: Any = store.auth()
    principal.validate()
    database = database_path(store)
    workspace_name, dataset_name = resolve_names(database, workspace_id, dataset_id)
    include_reports = bool(payload.get("include_reports", True))
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
        include_reports=include_reports,
        refresh=bool(payload.get("refresh", False)),
        max_reports=payload.get("max_reports"),
        scan_workers=int(payload.get("scan_workers") or 2),
    )

    def progress(index: int, total: int, name: str) -> None:
        log(f"Report {index}/{total}: {name}")

    session = _session(dataset_id)
    with session.lock:
        result = analyze_dataset(
            **request.to_run_kwargs(),
            principal=principal,
            session=session.conn,
            log=log,
            progress=progress,
            should_stop=cancel.is_set,
        )
    return serialize_result(result, _report_workspace_names(store, result))


def export(payload: Mapping[str, Any], store: SettingsStore) -> dict[str, Any]:
    dataset_id = str(payload.get("dataset_id") or "").strip()
    if not dataset_id:
        raise ExtractionError("No semantic model selected.")
    tab = str(payload.get("tab") or "all").strip().lower() or "all"
    session = _session(dataset_id, create=False)
    if session is None:
        raise ExtractionError(
            "No analysis results for this dataset yet. Run the analysis first "
            "(results are not saved to the database)."
        )
    with session.lock:
        result = snapshot_from_connection(session.conn, dataset_id)
    if result is None:
        raise ExtractionError(
            "No analysis results for this dataset yet. Run the analysis first "
            "(results are not saved to the database)."
        )
    text = str(payload.get("output") or "").strip().strip('"')
    if text:
        target = Path(text).expanduser()
        if not target.is_absolute():
            raise ExtractionError("Export path must be absolute.")
    else:
        suffix = dataset_id.replace("-", "")[:8]
        safe = re.sub(r'[<>:"/\\|?*]+', " ", str(result.dataset_name or ""))
        safe = re.sub(r"\s+", " ", safe).strip() or "Semantic Model"
        if tab in {"all", "result"}:
            target = outputs_dir() / f"Result_{safe}_{suffix}.xlsx"
        elif tab == "tables":
            target = outputs_dir() / f"Table_Result_{safe}_{suffix}.xlsx"
        else:
            target = outputs_dir() / output_file_name(
                result.dataset_name, result.dataset_id
            )
    if tab in {"all", "result"}:
        write_result_export(result, target)
    elif tab == "tables":
        write_table_export(result, target)
    elif tab in {"full", "workbook"}:
        write_workbook(result, target)
    elif tab in {
        "relationships",
        "roles",
        "report",
        "dax",
        "m",
        "health",
        "bestpractice",
    }:
        raise ExtractionError(
            "Export for this tab is not available yet (coming soon)."
        )
    else:
        raise ExtractionError(f"Unknown export tab: {tab}")
    return {
        "path": str(target),
        "size": target.stat().st_size if target.exists() else 0,
    }
