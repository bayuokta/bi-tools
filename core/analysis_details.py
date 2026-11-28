"""Objek detail kolom/measure untuk dialog analisa.

Bagian yang bisa dihitung dari ``AnalysisResult`` diisi; field yang tidak
dideteksi tool ini sengaja ``None`` (bukan ``false``) dan dicatat di
``unsupported`` agar tidak menyesatkan.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

STATUS_LABELS = {
    "Used": "Used",
    "Unused": "Unused",
    "Needs review": "Needs review",
    "Must keep": "Must keep",
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
            "depth": int(getattr(ref, "depth", 1) or 1),
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
    is_key: bool = False,
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
        if is_key and (is_from or is_to):
            other_table = from_table if is_to else to_table
            other_column = from_column if is_to else to_column
            keys.append(
                {
                    "table": other_table,
                    "column": other_column,
                    "relationship": str(relation.get("name") or ""),
                    "target_kind": "column",
                    "target_table": other_table,
                    "target_name": other_column,
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


def _function_usage_records(result: Any, analysis: Any) -> list[dict[str, Any]]:
    """Pemakaian report dari pemanggil function (langsung + transitif)."""
    measures = {
        (str(getattr(item.measure, "table", "")).casefold(),
         str(getattr(item.measure, "measure", "")).casefold()): item
        for item in (getattr(result, "measures", []) or [])
        if getattr(item, "measure", None) is not None
    }
    columns = {
        (str(getattr(item.column, "table", "")).casefold(),
         str(getattr(item.column, "column", "")).casefold()): item
        for item in (getattr(result, "columns", []) or [])
        if getattr(item, "column", None) is not None
    }
    functions = {
        str(getattr(item.function, "name", "")).casefold(): item
        for item in (getattr(result, "functions", []) or [])
        if getattr(item, "function", None) is not None
    }
    queue = list(getattr(analysis, "model_refs", []) or [])
    seen_refs: set[tuple[str, str]] = set()
    records: list[dict[str, Any]] = []
    seen_records: set[tuple[Any, ...]] = set()
    while queue:
        ref = queue.pop(0)
        kind = str(getattr(ref, "kind", "") or "")
        object_text = str(getattr(ref, "object", "") or "")
        token = (kind, object_text)
        if token in seen_refs:
            continue
        seen_refs.add(token)
        item = None
        if kind == "measure":
            table_name, item_name = _parse_object(object_text)
            item = measures.get((table_name.casefold(), item_name.casefold()))
        elif kind in {"calculated column", "calculated table column"}:
            table_name, item_name = _parse_object(object_text)
            item = columns.get((table_name.casefold(), item_name.casefold()))
        elif kind == "user-defined function":
            match = re.match(r"^function\s+(.+)$", object_text, re.IGNORECASE)
            name = match.group(1).strip().strip("'\"") if match else object_text
            item = functions.get(name.casefold())
            if item is not None:
                queue.extend(getattr(item, "model_refs", []) or [])
        if item is None:
            continue
        for record in getattr(item, "report_records", []) or []:
            if not isinstance(record, Mapping):
                continue
            key = (
                record.get("report_id"),
                record.get("page_id"),
                record.get("visual_id"),
                record.get("usage_kind"),
                record.get("detail"),
            )
            if key in seen_records:
                continue
            seen_records.add(key)
            records.append(dict(record))
    return records


def _function_details(result: Any, analysis: Any) -> dict[str, Any]:
    function = analysis.function
    refs = list(getattr(analysis, "model_refs", []) or [])
    records = _function_usage_records(result, analysis)
    details: dict[str, Any] = {
        "kind": "function",
        "name": str(getattr(function, "name", "")),
        "model_name": str(getattr(result, "dataset_name", "") or ""),
        "original_name": str(getattr(function, "name", "")),
        "table_name": "",
        "table_original_name": "",
        "lineage_tag": str(getattr(function, "lineage_tag", "") or ""),
        "source_lineage_tag": None,
        "description": str(getattr(function, "description", "") or ""),
        "database_id": None,
        "type": "User-defined function",
        "expression": str(getattr(function, "expression", "") or ""),
        "size": 0,
        "size_data": 0,
        "size_hierarchy": 0,
        "size_dictionary": 0,
        "cardinality": 0,
        "rows": 0,
        "id": int(getattr(function, "function_id", 0) or 0),
        "data_type": None,
        "data_type_str": "",
        "summarize_by": None,
        "summarize_by_str": "",
        "data_category": "",
        "display_folder": "",
        "format_string": "",
        "dynamic_format": False,
        "is_hidden": bool(getattr(function, "is_hidden", False)),
        "is_user_aware": None,
        "table": "",
        "kpi": None,
        "annotation": str(getattr(result, "dataset_name", "") or ""),
        "status": str(getattr(analysis, "status", "") or ""),
        "reason": str(getattr(analysis, "reason", "") or ""),
        "unsupported": [],
        "model_dependencies": _ref_rows(
            refs, {"measure", "calculated column", "user-defined function"}
        ),
        "visual_dependencies": _record_rows(
            records, {"field", "format", "calculation"}
        ),
        "visual_level_filters_dependencies": _record_rows(
            records, {"filter-visual"}
        ),
        "page_level_filters_dependencies": _record_rows(
            records, {"filter-page"}
        ),
        "report_level_filters_dependencies": _record_rows(
            records, {"filter-report"}
        ),
        "sort_dependencies": _record_rows(records, {"sort"}),
    }
    details.update(_flag_common(analysis, refs, records))
    details["is_used_key"] = False
    return details


def _hierarchy_details(result: Any, analysis: Any) -> dict[str, Any]:
    definition = getattr(analysis, "hierarchy", {}) or {}
    records = list(getattr(analysis, "report_records", []) or [])
    details: dict[str, Any] = {
        "kind": "hierarchy",
        "name": str(getattr(analysis, "name", "")),
        "model_name": str(getattr(result, "dataset_name", "") or ""),
        "original_name": str(getattr(analysis, "name", "")),
        "table_name": str(getattr(analysis, "table", "")),
        "table_original_name": "",
        "lineage_tag": str(definition.get("lineage_tag") or ""),
        "source_lineage_tag": None,
        "description": str(definition.get("description") or ""),
        "database_id": None,
        "type": "Hierarchy",
        "expression": "",
        "levels": str(definition.get("levels") or ""),
        "level_count": int(definition.get("level_count") or 0),
        "size": 0,
        "size_data": 0,
        "size_hierarchy": 0,
        "size_dictionary": 0,
        "cardinality": 0,
        "rows": 0,
        "id": None,
        "data_type": None,
        "data_type_str": "",
        "summarize_by": None,
        "summarize_by_str": "",
        "data_category": "",
        "display_folder": str(definition.get("display_folder") or ""),
        "format_string": "",
        "dynamic_format": False,
        "is_hidden": bool(definition.get("is_hidden", False)),
        "is_user_aware": None,
        "table": str(getattr(analysis, "table", "")),
        "kpi": None,
        "annotation": str(getattr(result, "dataset_name", "") or ""),
        "status": str(getattr(analysis, "status", "") or ""),
        "reason": str(getattr(analysis, "reason", "") or ""),
        "unsupported": [],
        "visual_dependencies": _record_rows(
            records, {"field", "format", "calculation"}
        ),
        "visual_level_filters_dependencies": _record_rows(
            records, {"filter-visual"}
        ),
        "page_level_filters_dependencies": _record_rows(
            records, {"filter-page"}
        ),
        "report_level_filters_dependencies": _record_rows(
            records, {"filter-report"}
        ),
        "sort_dependencies": _record_rows(records, {"sort"}),
    }
    details.update(_flag_common(analysis, [], records))
    details["is_used_key"] = False
    return details


def item_details(
    result: Any,
    analysis: Any,
    *,
    kind: str,
) -> dict[str, Any]:
    """Susun objek detail (properti + flag + dependency) untuk satu item."""
    kind_key = str(kind or "").strip().lower()
    if kind_key == "function":
        return _function_details(result, analysis)
    if kind_key == "hierarchy":
        return _hierarchy_details(result, analysis)
    is_measure = kind_key == "measure"
    node = getattr(analysis, "measure", None) if is_measure else getattr(
        analysis, "column", None
    )
    if node is None:
        raise ValueError("Unknown analysis object.")
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
    has_key = any(
        str(getattr(ref, "kind", "") or "").casefold() == "key column"
        for ref in refs
    )
    relationship_rows, key_rows = _relationship_rows(
        relationships, table=table, name=name, is_key=has_key
    )

    size = int(getattr(node, "size_total_bytes", 0) or 0) if not is_measure else 0
    details: dict[str, Any] = {
        "kind": "measure" if is_measure else "column",
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
    details["is_used_key"] = has_key
    for key in UNSUPPORTED_FLAGS:
        details[key] = None
    for key in UNSUPPORTED_ARRAYS:
        details[key] = None
    return details
