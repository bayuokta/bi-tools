"""Helper bersama ekspor Measure Killer (tab All results dan tab Tables).

Ukuran, label status, pemetaan tipe, dan metadata artefak dipakai dua ekspor
supaya angka pada file dan tampilan tidak melenceng.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .usage_service import (
    STATUS_BLOCKER,
    STATUS_UNKNOWN,
    STATUS_UNUSED,
    STATUS_USED,
    display_data_type,
    is_counted_record,
    is_counted_reference,
)

BLANK = ""


def source_text(result: Any) -> str:
    """Label sumber lokal/Service; fallback ke nama dataset."""
    return str(
        getattr(result, "source_label", "")
        or getattr(result, "dataset_name", "")
        or ""
    )


def report_source_text(result: Any) -> str:
    """Sumber pemakaian report: path file lokal bila tersedia."""
    return str(getattr(result, "source_file", "") or "")

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
    "Field parameter": "Field parameter",
}
CARDINALITY_SYMBOL = {"many": "N", "one": "1", "none": "0"}


def size_text(value: Any) -> str:
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


def status_text(value: Any) -> str:
    text = str(value or "")
    return STATUS_LABELS.get(text, text)


def use_count(analysis: Any) -> int:
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


def type_text(value: Any) -> str:
    return TYPE_LABELS.get(str(value or ""), str(value or "Column"))


def split_object(text: Any) -> tuple[str, str]:
    value = str(text or "").strip()
    match = re.match(r"^'((?:[^']|'')+)'\s*\[([^\]]+)\]$", value)
    if not match:
        match = re.match(r"^([^\[\]]+?)\s*\[([^\]]+)\]$", value)
    if not match:
        return "", ""
    return match.group(1).replace("''", "'"), match.group(2)


def quoted(text: Any) -> str:
    value = str(text or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].replace("''", "'")
    return value


def artifact_meta(
    columns: Mapping[tuple[str, str], Any],
    measures: Mapping[tuple[str, str], Any],
    tables: Mapping[str, Any],
    table: str,
    name: str,
) -> dict[str, Any] | None:
    """Metadata objek model yang dipakai baris ``Used in artifacts``."""
    key = (str(table).casefold(), str(name).casefold())
    analysis = measures.get(key)
    if analysis is not None:
        item = analysis.measure
        return {
            "type": "Measure",
            "id": int(getattr(item, "measure_id", 0) or 0),
            "data_type": display_data_type(getattr(item, "data_type", "")),
            "size": "0 B",
            "status": status_text(analysis.status),
            "uses": use_count(analysis),
            "format_string": str(getattr(item, "format_string", "") or ""),
            "has_error": bool(getattr(item, "has_error", False)),
            "display_folder": str(getattr(item, "display_folder", "") or ""),
            "table": str(getattr(item, "table", "") or table),
        }
    analysis = columns.get(key)
    if analysis is not None:
        item = analysis.column
        return {
            "type": type_text(getattr(item, "column_type", "")),
            "id": int(getattr(item, "column_id", 0) or 0),
            "data_type": display_data_type(getattr(item, "data_type", "")),
            "size": size_text(getattr(item, "size_total_bytes", 0)),
            "status": status_text(analysis.status),
            "uses": use_count(analysis),
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
            "size": size_text(getattr(table_row, "size_total_bytes", 0)),
            "status": "Used",
            "uses": "",
            "format_string": "",
            "has_error": False,
            "display_folder": "",
            "table": str(getattr(table_row, "table", "") or table),
        }
    return None
