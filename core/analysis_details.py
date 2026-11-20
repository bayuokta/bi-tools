"""Objek detail kolom/measure untuk dialog analisa.

Bagian yang bisa dihitung dari ``AnalysisResult`` diisi; field yang tidak
dideteksi tool ini sengaja ``None`` (bukan ``false``) dan dicatat di
``unsupported`` agar tidak menyesatkan.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

STATUS_LABELS = {
    "Dipakai": "Used",
    "Tidak dipakai": "Unused",
    "Perlu dicek": "Needs review",
    "Wajib dipertahankan": "Must keep",
}

UNSUPPORTED_FLAGS = (
    "is_used_default_label",
    "is_used_visual_calculations",
    "is_used_mobile",
    "is_used_paginated",
    "is_used_excel",
    "is_used_dynamic_param",
    "is_used_change_detection",
    "is_used_udf",
    "is_used_calendars",
    "is_used_group_by_columns",
    "is_used_model_extension",
    "ignored_in_build_dependencies",
)

UNSUPPORTED_ARRAYS = (
    "default_label_dependencies",
    "mobile_layout_dependencies",
    "visual_calculations_dependencies",
    "dynamic_param_dependencies",
    "change_detection_dependencies",
    "udf_dependencies",
    "calendar_dependencies",
    "group_by_columns_dependencies",
    "model_extension_dependencies",
)


def _refs(analysis: Any) -> list[Any]:
    return list(getattr(analysis, "model_refs", []) or [])


def _records(analysis: Any) -> list[Mapping[str, Any]]:
    return [
        row
        for row in (getattr(analysis, "report_records", []) or [])
        if isinstance(row, Mapping)
    ]


def _parse_object(text: str) -> tuple[str, str]:
    value = str(text or "").strip()
    match = re.match(r"^'((?:[^']|'')+)'\s*\[([^\]]+)\]$", value)
    if not match:
        match = re.match(r"^([^\[\]]+?)\s*\[([^\]]+)\]$", value)
    if not match:
        return "", ""
    return match.group(1).replace("''", "'"), match.group(2)


def _target_for_ref(kind: str, object_text: str) -> dict[str, str]:
    key = str(kind or "").casefold()
    table, name = _parse_object(object_text)
    if key == "measure" and table and name:
        return {
            "target_kind": "measure",
            "target_table": table,
            "target_name": name,
        }
    if key in {"calculated column", "calculated table column"} and table and name:
        return {
            "target_kind": "column",
            "target_table": table,
            "target_name": name,
        }
    if key == "calculated table":
        name = str(object_text or "").strip().strip("'")
        if name:
            return {
                "target_kind": "table",
                "target_table": name,
                "target_name": name,
            }
    return {}


def _ref_rows(refs: Iterable[Any], kinds: Iterable[str]) -> list[dict[str, Any]]:
    wanted = {kind.casefold() for kind in kinds}
    rows: list[dict[str, Any]] = []
    for ref in refs:
        kind = str(getattr(ref, "kind", "") or "")
        if kind.casefold() not in wanted:
            continue
        object_text = str(getattr(ref, "object", "") or "")
        row = {
            "kind": kind,
            "object": object_text,
            "detail": str(getattr(ref, "detail", "") or ""),
            "blocking": bool(getattr(ref, "blocking", False)),
        }
        row.update(_target_for_ref(kind, object_text))
        rows.append(row)
    return rows


def _record_rows(
    records: Iterable[Mapping[str, Any]], usage_kinds: Iterable[str]
) -> list[dict[str, Any]]:
    wanted = set(usage_kinds)
    return [
        {
            "report": str(record.get("report_name") or ""),
            "page": str(record.get("page_name") or ""),
            "visual": str(
                record.get("visual_title") or record.get("visual_type") or ""
            ),
            "type": str(record.get("visual_type") or ""),
            "detail": str(record.get("detail") or ""),
            "hidden": bool(record.get("is_hidden")),
        }
        for record in records
        if str(record.get("usage_kind") or "") in wanted
    ]


def _relationship_rows(
    relationships: Iterable[Mapping[str, Any]],
    *,
    table: str,
    name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mine: list[dict[str, Any]] = []
    keys: list[dict[str, Any]] = []
    for relation in relationships:
        from_table = str(relation.get("from_table") or "")
        from_column = str(relation.get("from_column") or "")
        to_table = str(relation.get("to_table") or "")
        to_column = str(relation.get("to_column") or "")
        is_from = (
            from_table.casefold() == table.casefold()
            and from_column.casefold() == name.casefold()
        )
        is_to = (
            to_table.casefold() == table.casefold()
            and to_column.casefold() == name.casefold()
        )
        if not (is_from or is_to):
            continue
        active = "Active" if relation.get("is_active", True) else "Inactive"
        from_card = str(relation.get("from_cardinality") or "").capitalize()
        to_card = str(relation.get("to_cardinality") or "").capitalize()
        label = f"{active} {from_card} to {to_card}".strip()
        mine.append(
            {
                "column1": from_column,
                "table1": from_table,
                "column2": to_column,
                "table2": to_table,
                "relationship_id": str(relation.get("name") or ""),
                "relationship_type": label,
                "target_kind": "column",
                "target_table": to_table if is_from else from_table,
                "target_name": to_column if is_from else from_column,
            }
        )
        if is_to:
            keys.append(
                {
                    "table": from_table,
                    "column": from_column,
                    "relationship": str(relation.get("name") or ""),
                    "target_kind": "column",
                    "target_table": from_table,
                    "target_name": from_column,
                }
            )
    return mine, keys


def _flag_common(analysis: Any, refs: list[Any], records: list[Mapping[str, Any]]) -> dict[str, Any]:
    kinds = {str(getattr(ref, "kind", "") or "").casefold() for ref in refs}
    usage = {str(record.get("usage_kind") or "") for record in records}
    return {
        "is_used": STATUS_LABELS.get(str(getattr(analysis, "status", "")), ""),
        "is_used_model": bool(refs),
        "is_used_artifacts": bool(records),
        "is_used_relationships": "relationship" in kinds,
        "is_used_sorting": "sort by" in kinds,
        "is_used_calc_tables": bool(
            kinds & {"calculated table", "calculated table column"}
        ),
        "is_used_hierarchy": "hierarchy" in kinds,
        "is_used_field_parameters": "field parameter" in kinds,
        "is_used_calculation_items": "calculation item" in kinds,
        "is_used_visuals": "field" in usage,
        "is_used_visual_level_filters": "filter-visual" in usage,
        "is_used_page_level_filters": "filter-page" in usage,
        "is_used_report_level_filters": "filter-report" in usage,
        "is_used_row_level_security": "rls" in kinds,
        "is_used_kpis": "kpi" in kinds,
        "is_used_power_query": "langkah m" in kinds,
        "is_used_key": False,
    }


def item_details(
    result: Any,
    analysis: Any,
    *,
    kind: str,
) -> dict[str, Any]:
    """Susun objek detail (properti + flag + dependency) untuk satu item."""
    is_measure = str(kind).lower() == "measure"
    node = getattr(analysis, "measure", None) if is_measure else getattr(
        analysis, "column", None
    )
    if node is None:
        raise ValueError("Objek analisa tidak dikenal.")
    table = str(getattr(node, "table", "") or "")
    name = str(
        getattr(node, "measure", "") if is_measure else getattr(node, "column", "")
    )
    refs = _refs(analysis)
    records = _records(analysis)
    relationships = [
        row
        for row in (getattr(result, "relationships", []) or [])
        if isinstance(row, Mapping)
    ]
    relationship_rows, key_rows = _relationship_rows(
        relationships, table=table, name=name
    )

    size = int(getattr(node, "size_total_bytes", 0) or 0) if not is_measure else 0
    details: dict[str, Any] = {
        "name": name,
        "model_name": str(getattr(result, "dataset_name", "") or ""),
        "original_name": name,
        "table_name": table,
        "table_original_name": "",
        "lineage_tag": None,
        "source_lineage_tag": None,
        "description": None,
        "database_id": None,
        "type": "Measure" if is_measure else (
            "Calculated column"
            if bool(getattr(node, "is_calculated", False))
            else "Column"
        ),
        "expression": str(getattr(node, "expression", "") or ""),
        "size": size,
        "size_data": int(getattr(node, "size_data_bytes", 0) or 0),
        "size_hierarchy": int(getattr(node, "size_hierarchy_bytes", 0) or 0),
        "size_dictionary": int(getattr(node, "size_dictionary_bytes", 0) or 0),
        "cardinality": int(getattr(node, "cardinality", 0) or 0),
        "rows": int(getattr(node, "rows", 0) or 0),
        "id": None if is_measure else int(getattr(node, "column_id", 0) or 0),
        "data_type": None,
        "data_type_str": str(getattr(node, "data_type", "") or ""),
        "summarize_by": None,
        "summarize_by_str": "",
        "data_category": "",
        "display_folder": str(getattr(node, "display_folder", "") or ""),
        "format_string": str(getattr(node, "format_string", "") or ""),
        "dynamic_format": False,
        "is_hidden": bool(getattr(node, "is_hidden", False)),
        "is_user_aware": None,
        "table": table,
        "kpi": None,
        "annotation": str(getattr(result, "dataset_name", "") or ""),
        "status": str(getattr(analysis, "status", "") or ""),
        "reason": str(getattr(analysis, "reason", "") or ""),
        "unsupported": list(UNSUPPORTED_FLAGS) + list(UNSUPPORTED_ARRAYS),
        "model_dependencies": _ref_rows(
            refs,
            {
                "measure",
                "calculated column",
                "calculated table column",
                "calculated table",
            },
        ),
        "artifact_dependencies": _record_rows(records, {"field"}),
        "sorting_dependencies": _ref_rows(refs, {"sort by"}),
        "relationship_dependencies": relationship_rows,
        "hierarchy_dependencies": _ref_rows(refs, {"hierarchy"}),
        "field_parameter_dependencies": _ref_rows(refs, {"field parameter"}),
        "calculation_item_dependencies": _ref_rows(refs, {"calculation item"}),
        "calc_table_dependencies": _ref_rows(
            refs, {"calculated table", "calculated table column"}
        ),
        "calc_table_column_dependencies": _ref_rows(
            refs, {"calculated table column"}
        ),
        "visual_dependencies": _record_rows(records, {"field"}),
        "visual_level_filters_dependencies": _record_rows(
            records, {"filter-visual"}
        ),
        "page_level_filters_dependencies": _record_rows(
            records, {"filter-page"}
        ),
        "report_level_filters_dependencies": _record_rows(
            records, {"filter-report"}
        ),
        "row_level_security_dependencies": _ref_rows(refs, {"rls"}),
        "key_column_dependencies": key_rows,
        "kpi_dependencies": _ref_rows(refs, {"kpi"}),
        "power_query_dependencies": _ref_rows(refs, {"langkah m"}),
        "sort_dependencies": _record_rows(records, {"sort"}),
    }
    details.update(_flag_common(analysis, refs, records))
    details["is_used_key"] = bool(key_rows)
    for key in UNSUPPORTED_FLAGS:
        details[key] = None
    for key in UNSUPPORTED_ARRAYS:
        details[key] = None
    return details
