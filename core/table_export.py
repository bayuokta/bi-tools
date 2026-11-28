"""Ekspor tab Tables mengikuti template Measure Killer.

Satu grup baris per tabel: header tabel lalu grup pemakaian (artifacts,
calculated tables, field parameters, Columns, Hierarchies, Measures,
calculation items, security). Data pemakaian berasal dari
``DISCOVER_CALC_DEPENDENCY`` yang disimpan di ``AnalysisResult``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .export_common import (
    source_text,
    BLANK,
    artifact_meta,
    size_text,
    status_text,
    type_text,
    use_count,
)
from .export_status import effective_status_map
from .m_lineage import parse_let, strip_comments
from .metadata_common import write_sheet
from .usage_service import STATUS_BLOCKER, STATUS_USED, display_data_type

TABLE_RESULT_COLUMNS = [
    "Table_name",
    "ID",
    "Table_type",
    "Table_source",
    "Table_size",
    "Table_status",
    "Table_uses",
    "Table_storage_mode",
    "Table_has_data_destination",
    "Usage_sub_level_type",
    "Used_in_name",
    "Used_in_ID",
    "Used_in_object_type",
    "Used_in_table",
    "Used_in_source",
    "Used_in_data_type",
    "Used_in_size",
    "Used_in_status",
    "Used_in_number_of_uses",
    "Used_in_format_string",
    "Has_error",
    "Used_in_display_folder",
]

GROUP_ARTIFACTS = "Used in artifacts"
GROUP_CALC_TABLES = "Used in calculated tables"
GROUP_FIELD_PARAMETERS = "Used in field parameters"
GROUP_COLUMNS = "Columns"
GROUP_HIERARCHIES = "Hierarchies"
GROUP_MEASURES = "Measures"
GROUP_POWER_QUERY = "Used in Power Query"
GROUP_CALC_ITEMS = "Used in calculation items"
GROUP_SECURITY = "Used in row/object level security"

# Urutan grup mengikuti template pembanding.
GROUP_ORDER = (
    GROUP_ARTIFACTS,
    GROUP_CALC_TABLES,
    GROUP_FIELD_PARAMETERS,
    GROUP_COLUMNS,
    GROUP_HIERARCHIES,
    GROUP_MEASURES,
    GROUP_POWER_QUERY,
    GROUP_CALC_ITEMS,
    GROUP_SECURITY,
)

GROUP_ICONS = {
    GROUP_ARTIFACTS: "group",
    GROUP_CALC_TABLES: "table",
    GROUP_FIELD_PARAMETERS: "group",
    GROUP_COLUMNS: "column",
    GROUP_HIERARCHIES: "group",
    GROUP_MEASURES: "measure",
    GROUP_POWER_QUERY: "code",
    GROUP_CALC_ITEMS: "code",
    GROUP_SECURITY: "filter",
}

ARTIFACT_OWNER_TYPES = {"MEASURE", "CALC_COLUMN", "KPI"}
DEPENDENCY_REFERENCE_TYPES = {"TABLE", "COLUMN", "CALC_COLUMN", "CALC_TABLE"}
USED_STATUS_LABELS = {status_text(STATUS_USED), status_text(STATUS_BLOCKER)}


def _row(
    usage_type: str,
    *,
    name: str,
    object_id: Any = BLANK,
    object_type: str = BLANK,
    table: str = BLANK,
    data_type: str = BLANK,
    size: str = BLANK,
    status: str = BLANK,
    uses: Any = BLANK,
    format_string: str = BLANK,
    has_error: Any = BLANK,
    display_folder: str = BLANK,
    kind: str = "",
    icon: str = "group",
    owner_table: str = "",
    target_table: str = "",
    size_bytes: int = 0,
    source: str | None = None,
) -> dict[str, Any]:
    return {
        "usage_type": usage_type,
        "name": str(name or ""),
        "object_id": object_id if object_id is not None else BLANK,
        "object_type": str(object_type or ""),
        "table": str(table or ""),
        "data_type": str(data_type or ""),
        "size": str(size or ""),
        "status": str(status or ""),
        "uses": uses if uses is not None else BLANK,
        "format_string": str(format_string or ""),
        "has_error": has_error,
        "display_folder": str(display_folder or ""),
        "kind": kind,
        "icon": icon,
        "owner_table": str(owner_table or ""),
        "target_table": str(target_table or ""),
        "size_bytes": int(size_bytes or 0),
        "source": source,
    }


def _table_type(table: Any, columns: list[Any]) -> str:
    if bool(getattr(table, "is_calculation_group", False)):
        return "Calculation group"
    if any(
        str(getattr(item.column, "column_type", "")) == "Field parameter"
        for item in columns
    ):
        return "Field param. table"
    if bool(getattr(table, "is_calculated_table", False)):
        return "Calculated Table"
    return "Table"


def _table_status(used: int, total: int) -> str:
    if not total:
        return "Used"
    if used == 0:
        return "Unused"
    if used == total:
        return "Used"
    percent = used / total * 100
    return f"Used {percent:.1f}% ({used}/{total})"


def _has_error_text(value: Any) -> Any:
    if value is None or value is BLANK:
        return BLANK
    return bool(value)


def _column_row(analysis: Any) -> dict[str, Any]:
    item = analysis.column
    return _row(
        GROUP_COLUMNS,
        name=str(item.column),
        object_id=int(getattr(item, "column_id", 0) or 0),
        object_type=type_text(getattr(item, "column_type", "")),
        table=str(item.table),
        data_type=display_data_type(getattr(item, "data_type", "")),
        size=size_text(getattr(item, "size_total_bytes", 0)),
        status=status_text(analysis.status),
        uses=use_count(analysis),
        format_string=str(getattr(item, "format_string", "") or ""),
        has_error=_has_error_text(getattr(item, "has_error", False)),
        display_folder=str(getattr(item, "display_folder", "") or ""),
        kind="column",
        icon="column",
        size_bytes=int(getattr(item, "size_total_bytes", 0) or 0),
    )


def _measure_row(analysis: Any) -> dict[str, Any]:
    item = analysis.measure
    return _row(
        GROUP_MEASURES,
        name=str(item.measure),
        object_id=int(getattr(item, "measure_id", 0) or 0),
        object_type="Measure",
        table=str(item.table),
        data_type=display_data_type(getattr(item, "data_type", "")),
        size="0 B",
        status=status_text(analysis.status),
        uses=use_count(analysis),
        format_string=str(getattr(item, "format_string", "") or ""),
        has_error=_has_error_text(getattr(item, "has_error", False)),
        display_folder=str(getattr(item, "display_folder", "") or ""),
        kind="measure",
        icon="measure",
    )


def _hierarchy_row(analysis: Any) -> dict[str, Any]:
    return _row(
        GROUP_HIERARCHIES,
        name=str(getattr(analysis, "name", "")),
        object_id=str(getattr(analysis, "name", "")),
        object_type="Hierarchy",
        table=str(getattr(analysis, "table", "")),
        size="0 B",
        status=status_text(getattr(analysis, "status", "")),
        uses=use_count(analysis),
        has_error="N/A",
        kind="hierarchy",
        icon="group",
    )


def _calculation_item_ids(result: Any) -> dict[tuple[str, str], int]:
    """Peta ``(tabel grup, nama item) -> ID`` dari referensi model."""
    ids: dict[tuple[str, str], int] = {}
    for analysis in list(result.columns or []) + list(result.measures or []):
        for ref in getattr(analysis, "model_refs", []) or []:
            if str(getattr(ref, "kind", "")) != "calculation item":
                continue
            source_id = int(getattr(ref, "source_id", 0) or 0)
            if not source_id:
                continue
            object_text = str(getattr(ref, "object", ""))
            match = re.match(r"^calculation item '(.+)'$", object_text)
            name = match.group(1) if match else object_text
            ids[
                (
                    str(getattr(ref, "source_table", "")).casefold(),
                    name.casefold(),
                )
            ] = source_id
    return ids


def _security_by_table(result: Any) -> dict[str, list[dict[str, Any]]]:
    """Role per tabel dari permission RLS/OLS (template memuat OLS)."""
    security: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for role in getattr(result, "roles", []) or []:
        if not isinstance(role, Mapping):
            continue
        name = str(role.get("name") or "")
        permissions = [
            item
            for item in (role.get("permissions") or [])
            if isinstance(item, Mapping)
        ]
        has_ols = any(bool(item.get("has_ols")) for item in permissions)
        for permission in permissions:
            table = str(permission.get("table") or "")
            key = (table.casefold(), name.casefold())
            if key in seen:
                continue
            seen.add(key)
            object_type = (
                "Object level security"
                if has_ols and not str(permission.get("expression") or "").strip()
                else "Row level security"
            )
            security.setdefault(table.casefold(), []).append(
                _row(
                    GROUP_SECURITY,
                    name=name,
                    object_type=object_type,
                    icon="filter",
                    source=str(getattr(result, "dataset_name", "") or ""),
                )
            )
    return security


def _power_query_usage(
    result: Any, *, tables: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Tabel yang mereferensikan query tabel lain di ekspresi M-nya.

    Measure Killer menampilkan referensi antartabel Power Query sebagai baris
    ``Used in Power Query`` pada tabel yang direferensikan. Referensi dibaca
    dari ekspresi partisi (``AnalysisResult.m_queries``) dan dicocokkan dengan
    nama tabel; nama lokal ``let`` tidak dihitung.
    """
    usage: dict[str, list[dict[str, Any]]] = {}
    dataset = str(getattr(result, "dataset_name", "") or "")
    rows = [
        row
        for row in (getattr(result, "m_queries", []) or [])
        if isinstance(row, Mapping)
    ]
    expressions: dict[str, str] = {}
    for row in rows:
        if str(row.get("kind") or "").casefold() != "table":
            continue
        name = str(row.get("name") or "")
        expression = str(row.get("expression") or "")
        if not name or not expression:
            continue
        expressions.setdefault(name, expression)
    quoted = re.compile(r'#"[^"]+"')
    for owner, expression in expressions.items():
        text = strip_comments(expression)
        steps, _ = parse_let(expression)
        bindings = {name.casefold() for name, _ in steps}
        candidates = {
            match[2:-1] for match in quoted.findall(text)
        } - bindings
        for target in sorted(candidates, key=str.casefold):
            key = target.casefold()
            if key not in tables or key == owner.casefold():
                continue
            usage.setdefault(key, []).append(
                _row(
                    GROUP_POWER_QUERY,
                    name="Power Query reference",
                    object_type="Reference",
                    table=owner,
                    kind="reference",
                    icon="code",
                    target_table=target,
                    source=dataset,
                )
            )
    return usage


def _usage_by_table(
    result: Any,
    *,
    tables: Mapping[str, Any],
    columns: Mapping[tuple[str, str], Any],
    measures: Mapping[tuple[str, str], Any],
    field_parameters: set[str],
    calc_item_ids: Mapping[tuple[str, str], int],
    status_map: Mapping[tuple[str, str, str], str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Baris pemakaian dari ``DISCOVER_CALC_DEPENDENCY`` per tabel tujuan."""
    usage: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    for dependency in getattr(result, "table_dependencies", []) or []:
        if not isinstance(dependency, Mapping):
            continue
        reference_type = str(dependency.get("REFERENCED_OBJECT_TYPE") or "")
        if reference_type not in DEPENDENCY_REFERENCE_TYPES:
            continue
        table = str(dependency.get("REFERENCED_TABLE") or "")
        if table.casefold() not in tables:
            continue
        owner_type = str(dependency.get("OBJECT_TYPE") or "")
        owner_table = str(dependency.get("TABLE") or "")
        owner_name = str(dependency.get("OBJECT") or "")
        if not owner_name:
            continue
        if owner_type in ARTIFACT_OWNER_TYPES:
            group = GROUP_ARTIFACTS
        elif owner_type == "CALC_TABLE":
            group = (
                GROUP_FIELD_PARAMETERS
                if owner_table.casefold() in field_parameters
                else GROUP_CALC_TABLES
            )
        elif owner_type == "CALCULATION_ITEM":
            group = GROUP_CALC_ITEMS
        else:
            continue
        key = (
            table.casefold(),
            group,
            owner_table.casefold(),
            owner_name.casefold(),
        )
        if key in seen:
            continue
        seen.add(key)

        if group == GROUP_ARTIFACTS:
            meta = artifact_meta(columns, measures, tables, owner_table, owner_name)
            meta = meta or {}
            object_type = (
                meta.get("type")
                or ("Measure" if owner_type == "MEASURE" else "Calculated Column")
            )
            status_value = meta.get("status", BLANK)
            if meta:
                lookup_kind = (
                    "measure" if object_type == "Measure" else "column"
                )
                status_value = (status_map or {}).get(
                    (
                        lookup_kind,
                        str(meta.get("table") or owner_table).casefold(),
                        owner_name.casefold(),
                    ),
                    status_value,
                )
            row = _row(
                group,
                name=owner_name,
                object_id=meta.get("id", BLANK),
                object_type=object_type,
                table=meta.get("table") or owner_table,
                data_type=meta.get("data_type", BLANK),
                size=meta.get("size", BLANK),
                status=status_value,
                uses=meta.get("uses", BLANK),
                format_string=meta.get("format_string", BLANK),
                has_error=_has_error_text(meta.get("has_error", BLANK)),
                display_folder=meta.get("display_folder", BLANK),
                kind="measure" if object_type == "Measure" else "column",
                icon="measure" if object_type == "Measure" else "column",
                target_table=table,
            )
        elif group in {GROUP_CALC_TABLES, GROUP_FIELD_PARAMETERS}:
            table_row = tables.get(owner_table.casefold())
            row = _row(
                group,
                name=owner_name,
                object_id=(
                    int(getattr(table_row, "table_id", 0) or 0)
                    if table_row is not None
                    else BLANK
                ),
                object_type=(
                    "Field param. table"
                    if group == GROUP_FIELD_PARAMETERS
                    else "Calculated Table"
                ),
                icon="group" if group == GROUP_FIELD_PARAMETERS else "table",
                owner_table=owner_table,
                target_table=table,
            )
        else:
            row = _row(
                GROUP_CALC_ITEMS,
                name=owner_name,
                object_id=calc_item_ids.get(
                    (owner_table.casefold(), owner_name.casefold()), BLANK
                ),
                object_type="Calculation item",
                table=owner_table,
                icon="code",
                target_table=table,
            )
        usage.setdefault(table.casefold(), []).append(row)
    return usage


def build_table_groups(
    result: Any, *, sort_by_size: bool = False
) -> list[dict[str, Any]]:
    """Susun header + grup pemakaian untuk setiap tabel di ``AnalysisResult``."""
    columns = {
        (item.column.table.casefold(), item.column.column.casefold()): item
        for item in (result.columns or [])
    }
    measures = {
        (item.measure.table.casefold(), item.measure.measure.casefold()): item
        for item in (result.measures or [])
    }
    tables = {
        table.table.casefold(): table
        for table in (getattr(result.stats, "tables", []) or [])
    }
    field_parameters = {
        item.column.table.casefold()
        for item in (result.columns or [])
        if str(getattr(item.column, "column_type", "")) == "Field parameter"
    }
    columns_by_table: dict[str, list[Any]] = {}
    for item in result.columns or []:
        columns_by_table.setdefault(item.column.table.casefold(), []).append(item)
    calc_item_ids = _calculation_item_ids(result)

    own: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for table_name in tables:
        own[table_name] = {"columns": [], "measures": [], "hierarchies": []}
    for item in result.columns or []:
        own.setdefault(
            item.column.table.casefold(),
            {"columns": [], "measures": [], "hierarchies": []},
        )["columns"].append(_column_row(item))
    for item in result.measures or []:
        own.setdefault(
            item.measure.table.casefold(),
            {"columns": [], "measures": [], "hierarchies": []},
        )["measures"].append(_measure_row(item))
    for item in getattr(result, "hierarchies", []) or []:
        own.setdefault(
            str(getattr(item, "table", "")).casefold(),
            {"columns": [], "measures": [], "hierarchies": []},
        )["hierarchies"].append(_hierarchy_row(item))
    for items in own.values():
        items["columns"].sort(
            key=lambda row: (-int(row.get("size_bytes") or 0), row["name"].casefold())
        )

    status_map = effective_status_map(result)
    usage = _usage_by_table(
        result,
        tables=tables,
        columns=columns,
        measures=measures,
        field_parameters=field_parameters,
        calc_item_ids=calc_item_ids,
        status_map=status_map,
    )
    security = _security_by_table(result)
    power_query = _power_query_usage(result, tables=tables)

    groups: list[dict[str, Any]] = []
    for table_name, table in tables.items():
        items = own.get(table_name, {"columns": [], "measures": [], "hierarchies": []})
        used = 0
        for kind, rows in (("column", items["columns"]), ("measure", items["measures"])):
            for item in rows:
                effective = status_map.get(
                    (kind, table_name, str(item["name"]).casefold()),
                    item["status"],
                )
                item["status"] = status_text(effective)
                if status_text(effective) in USED_STATUS_LABELS:
                    used += 1
        total = (
            len(items["columns"])
            + len(items["measures"])
            + len(items["hierarchies"])
        )
        own_uses = sum(
            int(item["uses"])
            for item in items["columns"] + items["measures"]
            if isinstance(item["uses"], int)
        )
        table_usage = usage.get(table_name, []) + power_query.get(table_name, [])
        table_security = security.get(table_name, [])
        groups.append(
            {
                "table": table.table,
                "table_id": int(getattr(table, "table_id", 0) or 0),
                "type_label": _table_type(
                    table, columns_by_table.get(table_name, [])
                ),
                "source": source_text(result),
                "size": size_text(getattr(table, "size_total_bytes", 0)),
                "size_bytes": int(getattr(table, "size_total_bytes", 0) or 0),
                "storage_mode": str(getattr(table, "storage_mode", "") or ""),
                "partition_count": int(getattr(table, "partition_count", 0) or 0),
                "used": used,
                "total": total,
                "status": _table_status(used, total),
                "uses": own_uses + len(table_usage) + len(table_security),
                "own": items,
                "usage": table_usage + table_security,
            }
        )

    uses_by_table = {group["table"].casefold(): group["uses"] for group in groups}
    status_by_table = {group["table"].casefold(): group["status"] for group in groups}
    for group in groups:
        for row in group["usage"]:
            if row["usage_type"] in {GROUP_CALC_TABLES, GROUP_FIELD_PARAMETERS}:
                owner = str(row.get("owner_table") or "").casefold()
                row["uses"] = uses_by_table.get(owner, BLANK)
                if row["usage_type"] == GROUP_CALC_TABLES:
                    row["status"] = status_by_table.get(owner, BLANK)

    result_groups: list[dict[str, Any]] = []
    for group in groups:
        rows: list[dict[str, Any]] = []
        for label in GROUP_ORDER:
            if label == GROUP_COLUMNS:
                selected = group["own"]["columns"]
            elif label == GROUP_MEASURES:
                selected = group["own"]["measures"]
            elif label == GROUP_HIERARCHIES:
                selected = group["own"]["hierarchies"]
            else:
                selected = [
                    row for row in group["usage"] if row["usage_type"] == label
                ]
            rows.extend(selected)
        payload = {
            key: value
            for key, value in group.items()
            if key not in {"own", "usage"}
        }
        payload["has_error"] = any(row["has_error"] is True for row in rows)
        payload["rows"] = rows
        result_groups.append(payload)

    if sort_by_size:
        result_groups.sort(
            key=lambda group: (
                -int(group["size_bytes"]),
                str(group["table"]).casefold(),
            )
        )
    return result_groups


def write_table_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet tab Tables dengan 22 kolom template."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for group in build_table_groups(result, sort_by_size=True):
        for row in group["rows"]:
            rows.append(
                {
                    "Table_name": group["table"],
                    "ID": group["table_id"],
                    "Table_type": group["type_label"],
                    "Table_source": group["source"],
                    "Table_size": group["size"],
                    "Table_status": group["status"],
                    "Table_uses": group["uses"],
                    "Table_storage_mode": group["storage_mode"],
                    "Table_has_data_destination": BLANK,
                    "Usage_sub_level_type": row["usage_type"],
                    "Used_in_name": row["name"],
                    "Used_in_ID": row["object_id"],
                    "Used_in_object_type": row["object_type"],
                    "Used_in_table": row["table"],
                    "Used_in_source": (
                        row["source"]
                        if row.get("source") is not None
                        else group["source"]
                    ),
                    "Used_in_data_type": row["data_type"],
                    "Used_in_size": row["size"],
                    "Used_in_status": row["status"],
                    "Used_in_number_of_uses": row["uses"],
                    "Used_in_format_string": row["format_string"],
                    "Has_error": row["has_error"],
                    "Used_in_display_folder": row["display_folder"],
                }
            )
    frame = pd.DataFrame(rows, columns=TABLE_RESULT_COLUMNS)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Tables")
    return target
