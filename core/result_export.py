"""Ekspor tab All results mengikuti template Measure Killer.

Satu baris per titik pemakaian; objek tanpa pemakaian mendapat satu baris
dasar. Semua nilai berasal dari ``AnalysisResult`` (tanpa koneksi ulang).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .metadata_common import write_sheet
from .usage_service import (
    STATUS_BLOCKER,
    STATUS_UNKNOWN,
    STATUS_UNUSED,
    STATUS_USED,
    is_counted_record,
    is_counted_reference,
)

RESULT_COLUMNS = [
    "Name",
    "ID",
    "Type",
    "Table",
    "Source",
    "Data_type",
    "Size",
    "Status",
    "Number_of_Uses",
    "Format_string",
    "Has_error",
    "Display_folder",
    "Used_in_type",
    "Used_in_name",
    "Used_in_ID",
    "Used_in_object_type",
    "Used_in_table_page",
    "Used_in_source",
    "Used_in_data_type",
    "Used_in_size",
    "Used_in_status",
    "Used_in_number_of_uses",
    "Used_in_format_string",
    "Used_in_has_error",
    "Used_in_display_folder",
]

STATUS_LABELS = {
    STATUS_UNUSED: "Unused",
    STATUS_USED: "Used",
    STATUS_BLOCKER: "Used",
    STATUS_UNKNOWN: "Unknown",
}
TYPE_LABELS = {
    "data": "Column",
    "Column": "Column",
    "calculated": "Calculated Column",
    "Field parameter": "Column",
}
CARDINALITY_SYMBOL = {"many": "N", "one": "1", "none": "0"}
BLANK = ""


def _size_text(value: Any) -> str:
    """Ukuran gaya template: titik desimal dan kB (bukan KB)."""
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return BLANK
    if size <= 0:
        return "0 B"
    units = ("B", "kB", "MB", "GB", "TB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[index]}"


def _status_text(value: Any) -> str:
    text = str(value or "")
    return STATUS_LABELS.get(text, text)


def _use_count(analysis: Any) -> int:
    value = getattr(analysis, "use_count", None)
    if value is not None:
        return int(value)
    records = [
        row
        for row in (getattr(analysis, "report_records", []) or [])
        if is_counted_record(row)
    ]
    refs = [
        ref
        for ref in (getattr(analysis, "model_refs", []) or [])
        if is_counted_reference(ref)
        and int(getattr(ref, "depth", 1) or 1) <= 1
    ]
    return len(records) + len(refs)


def _type_text(value: Any) -> str:
    return TYPE_LABELS.get(str(value or ""), str(value or "Column"))


def _split_object(text: Any) -> tuple[str, str]:
    value = str(text or "").strip()
    match = re.match(r"^'((?:[^']|'')+)'\s*\[([^\]]+)\]$", value)
    if not match:
        match = re.match(r"^([^\[\]]+?)\s*\[([^\]]+)\]$", value)
    if not match:
        return "", ""
    return match.group(1).replace("''", "'"), match.group(2)


def _quoted(text: Any) -> str:
    value = str(text or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].replace("''", "'")
    return value


def _visual_name(record: Mapping[str, Any]) -> str:
    title = str(record.get("visual_title") or "").strip()
    if title.startswith("(tanpa judul) "):
        title = title[len("(tanpa judul) ") :].strip()
        title = re.sub(r"\s+[0-9a-f]{8}$", "", title, flags=re.IGNORECASE)
    return title or str(record.get("visual_type") or "visual")


def _filter_parts(detail: Any) -> tuple[str, str]:
    parts = [part.strip() for part in str(detail or "").split("·")]
    kind = parts[0] if parts else ""
    name = parts[-1] if parts and parts[-1].lower().startswith("filter") else ""
    return kind, name


def _report_urls(result: Any) -> dict[str, str]:
    from .usage_service import report_url

    return {
        str(row.get("report_id") or ""): report_url(
            str(row.get("workspace_id") or ""), str(row.get("report_id") or "")
        )
        for row in (result.reports or [])
        if isinstance(row, Mapping)
    }


def _table_usage(result: Any, table: str) -> tuple[int, int, int]:
    key = str(table or "").casefold()
    columns = [
        item
        for item in (result.columns or [])
        if item.column.table.casefold() == key
    ]
    used = sum(
        1
        for item in columns
        if item.status in {STATUS_USED, STATUS_BLOCKER}
    )
    return used, len(columns), sum(int(item.use_count) for item in columns)


def _table_status(result: Any, table: str) -> str:
    used, total, _uses = _table_usage(result, table)
    if not total:
        return "Used" if used else "Unused"
    percent = used / total * 100
    return f"Used {percent:.1f}% ({used}/{total})"


def _base_row(
    *,
    name: str,
    object_id: Any,
    type_label: str,
    table: str,
    dataset: str,
    data_type: str = BLANK,
    size: str = BLANK,
    status: str = BLANK,
    uses: int = 0,
    format_string: str = BLANK,
    has_error: Any = False,
    display_folder: str = BLANK,
) -> dict[str, Any]:
    return {
        "Name": name,
        "ID": object_id,
        "Type": type_label,
        "Table": table,
        "Source": dataset,
        "Data_type": data_type,
        "Size": size,
        "Status": _status_text(status),
        "Number_of_Uses": int(uses),
        "Format_string": format_string,
        "Has_error": bool(has_error),
        "Display_folder": display_folder,
        "Used_in_type": BLANK,
        "Used_in_name": BLANK,
        "Used_in_ID": BLANK,
        "Used_in_object_type": BLANK,
        "Used_in_table_page": BLANK,
        "Used_in_source": BLANK,
        "Used_in_data_type": BLANK,
        "Used_in_size": BLANK,
        "Used_in_status": BLANK,
        "Used_in_number_of_uses": BLANK,
        "Used_in_format_string": BLANK,
        "Used_in_has_error": BLANK,
        "Used_in_display_folder": BLANK,
    }


def _with_usage(
    base: Mapping[str, Any],
    *,
    usage_type: str,
    name: str,
    object_id: Any = BLANK,
    object_type: str = BLANK,
    page: str = BLANK,
    source: str = BLANK,
    data_type: str = BLANK,
    size: str = BLANK,
    status: str = BLANK,
    uses: Any = BLANK,
    format_string: str = BLANK,
    has_error: Any = BLANK,
    display_folder: str = BLANK,
) -> dict[str, Any]:
    row = dict(base)
    row.update(
        {
            "Used_in_type": usage_type,
            "Used_in_name": name,
            "Used_in_ID": object_id,
            "Used_in_object_type": object_type,
            "Used_in_table_page": page,
            "Used_in_source": source,
            "Used_in_data_type": data_type,
            "Used_in_size": size,
            "Used_in_status": status,
            "Used_in_number_of_uses": uses,
            "Used_in_format_string": format_string,
            "Used_in_has_error": has_error,
            "Used_in_display_folder": display_folder,
        }
    )
    return row


def _record_row(
    base: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    dataset: str,
    urls: Mapping[str, str],
    fallback_name: str,
) -> dict[str, Any] | None:
    kind = str(record.get("usage_kind") or "")
    if kind == "sort":
        return None
    if kind in {"field", "format", "calculation"}:
        usage_type = "Used in visuals"
    elif kind == "filter-visual":
        usage_type = "Used in visual level filters"
    elif kind == "filter-page":
        usage_type = "Used in page level filters"
    elif kind == "filter-report":
        usage_type = "Used in report level filters"
    else:
        return None
    visual = _visual_name(record)
    detail = str(record.get("detail") or "")
    name = visual
    object_type = str(record.get("visual_type") or "")
    data_type = detail
    page = str(record.get("page_name") or "")
    if kind.startswith("filter"):
        filter_type, filter_name = _filter_parts(detail)
        object_type = filter_type or object_type
        data_type = BLANK
        if kind == "filter-visual":
            name = (
                f"{visual} (Filter: {filter_name})"
                if filter_name
                else f"{visual} (Filter)"
            )
        elif kind == "filter-page":
            page_name = page or str(record.get("report_name") or "")
            name = (
                f"{page_name} (Filter: {filter_name})"
                if filter_name
                else f"{page_name} (Filter)"
            )
        else:
            report_name = str(record.get("report_name") or "")
            name = (
                f"{report_name} (Filter: {filter_name})"
                if filter_name
                else f"{report_name} (Filter)"
            )
    report_id = str(record.get("report_id") or "")
    return _with_usage(
        base,
        usage_type=usage_type,
        name=name or fallback_name,
        object_id=str(record.get("visual_id") or BLANK),
        object_type=object_type,
        page=page,
        source=urls.get(report_id) or dataset,
        data_type=data_type,
    )


def _artifact_meta(
    columns: Mapping[tuple[str, str], Any],
    measures: Mapping[tuple[str, str], Any],
    tables: Mapping[str, Any],
    table: str,
    name: str,
) -> dict[str, Any] | None:
    key = (str(table).casefold(), str(name).casefold())
    analysis = measures.get(key)
    if analysis is not None:
        item = analysis.measure
        return {
            "type": "Measure",
            "id": int(getattr(item, "measure_id", 0) or 0),
            "data_type": str(getattr(item, "data_type", "") or ""),
            "size": "0 B",
            "status": _status_text(analysis.status),
            "uses": _use_count(analysis),
            "format_string": str(getattr(item, "format_string", "") or ""),
            "has_error": bool(getattr(item, "has_error", False)),
            "display_folder": str(getattr(item, "display_folder", "") or ""),
            "table": str(getattr(item, "table", "") or table),
        }
    analysis = columns.get(key)
    if analysis is not None:
        item = analysis.column
        return {
            "type": _type_text(getattr(item, "column_type", "")),
            "id": int(getattr(item, "column_id", 0) or 0),
            "data_type": str(getattr(item, "data_type", "") or ""),
            "size": _size_text(getattr(item, "size_total_bytes", 0)),
            "status": _status_text(analysis.status),
            "uses": _use_count(analysis),
            "format_string": str(getattr(item, "format_string", "") or ""),
            "has_error": bool(getattr(item, "has_error", False)),
            "display_folder": str(getattr(item, "display_folder", "") or ""),
            "table": str(getattr(item, "table", "") or table),
        }
    table_row = tables.get(str(table).casefold())
    if table_row is not None:
        return {
            "type": "Table",
            "id": int(getattr(table_row, "table_id", 0) or 0),
            "data_type": "",
            "size": _size_text(getattr(table_row, "size_total_bytes", 0)),
            "status": "Used",
            "uses": "",
            "format_string": "",
            "has_error": False,
            "display_folder": "",
            "table": str(getattr(table_row, "table", "") or table),
        }
    return None


def _relationship_row(
    base: Mapping[str, Any],
    analysis: Any,
    *,
    ref: Any,
    relationships: list[Mapping[str, Any]],
    dataset: str,
) -> dict[str, Any] | None:
    own_table = str(getattr(analysis.column, "table", "") or "")
    own_name = str(getattr(analysis.column, "column", "") or "")
    other_table, other_name = _split_object(getattr(ref, "object", ""))
    for relation in relationships:
        pairs = {
            (
                str(relation.get("from_table") or "").casefold(),
                str(relation.get("from_column") or "").casefold(),
            ),
            (
                str(relation.get("to_table") or "").casefold(),
                str(relation.get("to_column") or "").casefold(),
            ),
        }
        if (own_table.casefold(), own_name.casefold()) not in pairs:
            continue
        if (other_table.casefold(), other_name.casefold()) not in pairs:
            continue
        from_table = str(relation.get("from_table") or "")
        to_table = str(relation.get("to_table") or "")
        from_column = str(relation.get("from_column") or "")
        to_column = str(relation.get("to_column") or "")
        from_card = str(relation.get("from_cardinality") or "")
        to_card = str(relation.get("to_cardinality") or "")
        from_symbol = CARDINALITY_SYMBOL.get(from_card, from_card)
        to_symbol = CARDINALITY_SYMBOL.get(to_card, to_card)
        name = str(relation.get("name") or "").strip()
        if (
            not name
            or relation.get("is_auto")
            or re.fullmatch(r"[0-9a-fA-F-]{36}", name)
        ):
            name = f"{from_column} {from_symbol} <- {to_symbol} {to_column}"
        active = "Active" if relation.get("is_active") else "Inactive"
        object_type = (
            f"{active} {from_card.capitalize()} to {to_card}"
            if from_card or to_card
            else active
        )
        return _with_usage(
            base,
            usage_type="Used in relationships",
            name=name,
            object_id=int(relation.get("id") or 0),
            object_type=object_type,
            page=f"{from_table} {from_symbol} <- {to_symbol} {to_table}",
            source=dataset,
            status="Used",
        )
    return None


def _object_rows(
    analysis: Any,
    *,
    kind: str,
    result: Any,
    columns: Mapping[tuple[str, str], Any],
    measures: Mapping[tuple[str, str], Any],
    tables: Mapping[str, Any],
    relationships: list[Mapping[str, Any]],
    hierarchies: Mapping[tuple[str, str], Any],
    urls: Mapping[str, str],
) -> list[dict[str, Any]]:
    dataset = str(result.dataset_name or "")
    if kind == "measure":
        item = analysis.measure
        name = str(item.measure)
        table = str(item.table)
        type_label = "Measure"
        object_id = int(getattr(item, "measure_id", 0) or 0)
        data_type = str(item.data_type or "")
        size = "0 B"
        format_string = str(item.format_string or "")
        has_error = bool(getattr(item, "has_error", False))
        display_folder = str(item.display_folder or "")
    elif kind == "hierarchy":
        item = analysis.hierarchy
        name = str(getattr(analysis, "name", "") or "")
        table = str(getattr(analysis, "table", "") or "")
        type_label = "Hierarchy"
        object_id = name
        data_type = ""
        size = "0 B"
        format_string = ""
        has_error = False
        display_folder = str(item.get("display_folder") or "")
    else:
        item = analysis.column
        name = str(item.column)
        table = str(item.table)
        type_label = _type_text(str(item.column_type))
        object_id = int(getattr(item, "column_id", 0) or 0)
        data_type = str(item.data_type or "")
        size = _size_text(getattr(item, "size_total_bytes", 0))
        format_string = str(item.format_string or "")
        has_error = bool(getattr(item, "has_error", False))
        display_folder = str(item.display_folder or "")

    base = _base_row(
        name=name,
        object_id=object_id,
        type_label=type_label,
        table=table,
        dataset=dataset,
        data_type=data_type,
        size=size,
        status=getattr(analysis, "status", ""),
        uses=_use_count(analysis),
        format_string=format_string,
        has_error=has_error,
        display_folder=display_folder,
    )
    rows: list[dict[str, Any]] = []
    for record in analysis.report_records or []:
        row = _record_row(
            base, record, dataset=dataset, urls=urls, fallback_name=name
        )
        if row is not None:
            rows.append(row)

    if kind == "hierarchy":
        return rows or [base]

    for ref in analysis.model_refs or []:
        if not is_counted_reference(ref):
            continue
        if int(getattr(ref, "depth", 1) or 1) > 1:
            continue
        ref_kind = str(getattr(ref, "kind", "") or "")
        obj = str(getattr(ref, "object", "") or "")
        detail = str(getattr(ref, "detail", "") or "")
        if ref_kind == "relationship":
            row = _relationship_row(
                base,
                analysis,
                ref=ref,
                relationships=relationships,
                dataset=dataset,
            )
            if row is not None:
                rows.append(row)
            continue
        if ref_kind in {"RLS", "column permission"}:
            role = ""
            match = re.search(r"role '([^']+)'", detail)
            if match:
                role = match.group(1)
            rows.append(
                _with_usage(
                    base,
                    usage_type="Used in row/object level security",
                    name=role or ("OLS" if ref_kind == "column permission" else "RLS"),
                    object_type=(
                        "Object level security"
                        if ref_kind == "column permission"
                        else "Row level security"
                    ),
                    source=dataset,
                )
            )
            continue
        if ref_kind == "sort by":
            sort_table, sort_column = _split_object(obj)
            meta = _artifact_meta(columns, measures, tables, sort_table, sort_column)
            rows.append(
                _with_usage(
                    base,
                    usage_type="Used in column sorting",
                    name=sort_column or obj,
                    object_id=(meta or {}).get("id", BLANK),
                    object_type="Column",
                    page=sort_table,
                    source=dataset,
                    size=(meta or {}).get("size", BLANK),
                    status=(meta or {}).get("status", BLANK),
                    uses=(meta or {}).get("uses", BLANK),
                    format_string=(meta or {}).get("format_string", BLANK),
                    has_error=(meta or {}).get("has_error", BLANK),
                    display_folder=(meta or {}).get("display_folder", BLANK),
                )
            )
            continue
        if ref_kind == "hierarchy":
            ref_table, hierarchy_name = _split_object(obj)
            hierarchy = hierarchies.get(
                (ref_table.casefold(), hierarchy_name.casefold())
            )
            rows.append(
                _with_usage(
                    base,
                    usage_type="Used in hierarchy",
                    name=hierarchy_name or obj,
                    object_id=hierarchy_name or obj,
                    object_type="Hierarchy",
                    page=ref_table,
                    source=dataset,
                    size="0 B",
                    status=(
                        _status_text(hierarchy.status)
                        if hierarchy is not None
                        else "Used"
                    ),
                    uses=(
                        int(hierarchy.use_count)
                        if hierarchy is not None
                        else BLANK
                    ),
                )
            )
            continue
        if ref_kind in {"key column", "default label"}:
            ref_table = _split_object(obj)[0] or table
            table_row = tables.get(ref_table.casefold())
            _used, _total, table_uses = _table_usage(result, ref_table)
            rows.append(
                _with_usage(
                    base,
                    usage_type=(
                        "Used as key column"
                        if ref_kind == "key column"
                        else "Used as default label"
                    ),
                    name=ref_table,
                    object_id=(
                        int(getattr(table_row, "table_id", 0) or 0)
                        if table_row is not None
                        else BLANK
                    ),
                    object_type="Table",
                    source=dataset,
                    size=(
                        _size_text(getattr(table_row, "size_total_bytes", 0))
                        if table_row is not None
                        else BLANK
                    ),
                    status=_table_status(result, ref_table),
                    uses=table_uses,
                )
            )
            continue
        if ref_kind == "calculated table":
            calc_table = _quoted(obj.replace("calculated table ", "", 1))
            table_row = tables.get(calc_table.casefold())
            _used, _total, table_uses = _table_usage(result, calc_table)
            rows.append(
                _with_usage(
                    base,
                    usage_type="Used in calculated tables",
                    name=calc_table or obj,
                    object_id=(
                        int(getattr(table_row, "table_id", 0) or 0)
                        if table_row is not None
                        else BLANK
                    ),
                    object_type="Calculated Table",
                    source=dataset,
                    size=(
                        _size_text(getattr(table_row, "size_total_bytes", 0))
                        if table_row is not None
                        else BLANK
                    ),
                    status=_table_status(result, calc_table),
                    uses=table_uses,
                )
            )
            continue
        if ref_kind == "calculated table column":
            calc_table, _calc_column = _split_object(obj)
            table_row = tables.get(calc_table.casefold())
            _used, _total, table_uses = _table_usage(result, calc_table)
            rows.append(
                _with_usage(
                    base,
                    usage_type="Used in calculated tables",
                    name=calc_table or obj,
                    object_id=(
                        int(getattr(table_row, "table_id", 0) or 0)
                        if table_row is not None
                        else BLANK
                    ),
                    object_type="Calculated Table",
                    source=dataset,
                    size=(
                        _size_text(getattr(table_row, "size_total_bytes", 0))
                        if table_row is not None
                        else BLANK
                    ),
                    status=_table_status(result, calc_table),
                    uses=table_uses,
                )
            )
            continue
        if ref_kind == "Power Query":
            if obj.lower().startswith("query "):
                ref_table = _quoted(obj[6:].strip())
                name = "Power Query reference"
                object_type = "Reference"
            else:
                match = re.search(r"tabel '([^']+)'", obj)
                ref_table = match.group(1) if match else ""
                name = "Incremental refresh"
                object_type = "Incremental refresh"
            rows.append(
                _with_usage(
                    base,
                    usage_type="Used in Power Query",
                    name=name,
                    object_type=object_type,
                    page=ref_table,
                    source=dataset,
                )
            )
            continue
        # Artifact: measure, calculated column/table column, calculation item,
        # KPI, field parameter.
        artifact_table, artifact_name = _split_object(obj)
        if not artifact_name and obj:
            artifact_table = _quoted(obj)
            artifact_name = artifact_table
        meta = _artifact_meta(
            columns, measures, tables, artifact_table, artifact_name
        )
        type_label = (
            (meta or {}).get("type")
            or (
                "Field parameter"
                if ref_kind == "field parameter"
                else "Calculated Column"
                if "column" in ref_kind
                else "Measure"
            )
        )
        rows.append(
            _with_usage(
                base,
                usage_type="Used in artifacts",
                name=artifact_name or obj,
                object_id=(meta or {}).get("id", BLANK),
                object_type=type_label,
                page=(meta or {}).get("table", artifact_table),
                source=dataset,
                data_type=(meta or {}).get("data_type", BLANK),
                size=(meta or {}).get("size", BLANK),
                status=(meta or {}).get("status", BLANK),
                uses=(meta or {}).get("uses", BLANK),
                format_string=(meta or {}).get("format_string", BLANK),
                has_error=(meta or {}).get("has_error", BLANK),
                display_folder=(meta or {}).get("display_folder", BLANK),
            )
        )

    return rows or [base]


def write_result_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet ``Result`` dengan kolom template Measure Killer."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
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
    hierarchies = {
        (item.table.casefold(), item.name.casefold()): item
        for item in (getattr(result, "hierarchies", []) or [])
    }
    relationships = [
        item
        for item in (getattr(result, "relationships", []) or [])
        if isinstance(item, Mapping)
    ]
    urls = _report_urls(result)

    rows: list[dict[str, Any]] = []
    for analysis in result.columns or []:
        rows.extend(
            _object_rows(
                analysis,
                kind="column",
                result=result,
                columns=columns,
                measures=measures,
                tables=tables,
                relationships=relationships,
                hierarchies=hierarchies,
                urls=urls,
            )
        )
    for analysis in result.measures or []:
        rows.extend(
            _object_rows(
                analysis,
                kind="measure",
                result=result,
                columns=columns,
                measures=measures,
                tables=tables,
                relationships=relationships,
                hierarchies=hierarchies,
                urls=urls,
            )
        )
    for analysis in getattr(result, "hierarchies", []) or []:
        rows.extend(
            _object_rows(
                analysis,
                kind="hierarchy",
                result=result,
                columns=columns,
                measures=measures,
                tables=tables,
                relationships=relationships,
                hierarchies=hierarchies,
                urls=urls,
            )
        )

    rows.sort(
        key=lambda row: (
            str(row["Table"]).casefold(),
            str(row["Type"]).casefold(),
            str(row["Name"]).casefold(),
            str(row["Used_in_type"]).casefold(),
            str(row["Used_in_name"]).casefold(),
        )
    )
    frame = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Result")
    return target
