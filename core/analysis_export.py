"""Ekspor hasil lineage/dependensi analisa ke ``outputs`` (CSV/JSON).

Seluruh isi berasal dari payload lineage yang sudah dibangun
(``core.analysis_lineage``) atau dari ``AnalysisResult`` di sesi analisa; modul
ini hanya memformat berkas dan tidak menghitung ulang dependensi.
"""

from __future__ import annotations

import base64
import binascii
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .errors import ExtractionError
from .metadata_common import write_sheet
from .usage_service import format_bytes

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
IMAGE_FORMATS = {"svg": ".svg", "png": ".png"}
MAX_IMAGE_BYTES = 25 * 1024 * 1024
NODE_FIELDS = (
    "node_id",
    "kind",
    "label",
    "context",
    "status",
    "side",
    "column",
    "x",
    "y",
    "count",
    "hidden",
)
EDGE_FIELDS = ("from", "to", "kind")
DEPENDENCY_FIELDS = (
    "source",
    "type",
    "kind",
    "object",
    "detail",
    "report",
    "page",
    "visual",
    "hidden",
)


def safe_name(value: str, fallback: str = "Analisa") -> str:
    text = ILLEGAL.sub("_", str(value or "")).strip().strip(".")
    text = re.sub(r"\s+", " ", text)
    return (text or fallback)[:80]


def output_stem(table: str, name: str) -> str:
    safe_table = safe_name(table, "Table")
    safe_item = safe_name(name, "Item")
    if safe_item.casefold() == safe_table.casefold():
        return safe_table
    return safe_name(f"{safe_table}_{safe_item}")


def _write_csv(path: Path, fields: Iterable[str], rows: Iterable[Mapping[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(fields),
            extrasaction="ignore",
            lineterminator="\r\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})
    return path


def write_lineage_files(
    payload: Mapping[str, Any],
    directory: Path | str,
    *,
    table: str,
    name: str,
    formats: Iterable[str] = ("csv", "json"),
) -> dict[str, Any]:
    """Tulis node/edge CSV dan/atau payload JSON sesuai ``formats``."""
    target = Path(directory)
    wanted = {str(item).lower() for item in formats}
    stem = output_stem(table, name)
    nodes = [
        {"node_id": node.get("id", ""), **node}
        for node in payload.get("nodes", [])
        if isinstance(node, Mapping)
    ]
    edges = [
        {field: edge.get(field, "") for field in EDGE_FIELDS}
        for edge in payload.get("edges", [])
        if isinstance(edge, Mapping)
    ]
    paths: list[str] = []
    if "csv" in wanted:
        nodes_path = _write_csv(
            target / f"Lineage_{stem}_nodes.csv", NODE_FIELDS, nodes
        )
        edges_path = _write_csv(
            target / f"Lineage_{stem}_edges.csv", EDGE_FIELDS, edges
        )
        paths.extend([str(nodes_path), str(edges_path)])
    if "json" in wanted:
        json_path = target / f"Lineage_{stem}.json"
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        paths.append(str(json_path))
    return {
        "paths": paths,
        "nodes": len(nodes),
        "edges": len(edges),
    }


def write_lineage_image(
    content: str,
    directory: Path | str,
    *,
    table: str,
    name: str,
    image_format: str,
    file_stem: str = "",
) -> dict[str, Any]:
    """Tulis gambar lineage (SVG/PNG) yang dihasilkan klien ke ``outputs``.

    ``file_stem`` mengganti nama berkas bawaan ``Lineage_<tabel>_<item>_lineage``;
    dipakai halaman Lineage agar nama mengikuti node akar, bukan tabel/kolom.
    """
    fmt = str(image_format or "").strip().lower()
    if fmt not in IMAGE_FORMATS:
        raise ValueError("Image format must be svg or png.")
    text = str(content or "").strip()
    if not text:
        raise ValueError("Lineage image content is empty.")
    if fmt == "svg":
        if not text.lower().startswith("<svg"):
            raise ValueError("SVG content is not valid.")
        if "<script" in text.lower():
            raise ValueError("SVG must not contain scripts.")
        data = text.encode("utf-8")
    else:
        if text.startswith("data:image/png;base64,"):
            text = text[len("data:image/png;base64,"):]
        try:
            data = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("PNG data is not valid.") from exc
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG data is not valid.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image size exceeds 25 MB.")
    stem = (
        safe_name(file_stem, "lineage")
        if str(file_stem or "").strip()
        else f"Lineage_{output_stem(table, name)}_lineage"
    )
    path = Path(directory) / f"{stem}{IMAGE_FORMATS[fmt]}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path), "bytes": len(data), "format": fmt}


def _analysis_of(result: Any, kind: str, table: str, name: str) -> Any:
    wanted = str(name or "").casefold()
    wanted_table = str(table or "").casefold()
    wanted_kind = str(kind or "").strip().lower()
    if wanted_kind == "function":
        for item in getattr(result, "functions", []) or []:
            function = getattr(item, "function", None)
            if function is not None and str(function.name).casefold() == wanted:
                return item
        return None
    if wanted_kind == "hierarchy":
        for item in getattr(result, "hierarchies", []) or []:
            if (
                str(getattr(item, "table", "")).casefold() == wanted_table
                and str(getattr(item, "name", "")).casefold() == wanted
            ):
                return item
        return None
    items = getattr(result, "measures" if kind == "measure" else "columns", []) or []
    for item in items:
        node = getattr(item, "measure", None) or getattr(item, "column", None)
        if node is None:
            continue
        node_name = getattr(node, "measure", "") or getattr(node, "column", "")
        if (
            str(getattr(node, "table", "")).casefold() == wanted_table
            and str(node_name).casefold() == wanted
        ):
            return item
    return None


def dependency_rows(
    result: Any,
    *,
    kind: str,
    table: str,
    name: str,
) -> list[dict[str, Any]]:
    """Baris datar dependensi model + pemakaian report untuk satu item."""
    if str(kind or "").strip().lower() == "table":
        wanted_table = str(table or "").casefold()
        rows: list[dict[str, Any]] = []
        for item in getattr(result, "columns", []) or []:
            node = getattr(item, "column", None)
            if node is None or str(node.table).casefold() != wanted_table:
                continue
            rows.extend(
                dependency_rows(
                    result,
                    kind="column",
                    table=node.table,
                    name=node.column,
                )
            )
        for item in getattr(result, "measures", []) or []:
            node = getattr(item, "measure", None)
            if node is None or str(node.table).casefold() != wanted_table:
                continue
            rows.extend(
                dependency_rows(
                    result,
                    kind="measure",
                    table=node.table,
                    name=node.measure,
                )
            )
        return rows
    analysis = _analysis_of(result, kind, table, name)
    if analysis is None:
        return []
    if str(kind or "").strip().lower() == "function":
        source = f"function '{name}'"
    else:
        source = f"'{table}'[{name}]"
    rows: list[dict[str, Any]] = []
    for reference in getattr(analysis, "model_refs", []) or []:
        rows.append(
            {
                "source": source,
                "type": "model",
                "kind": str(getattr(reference, "kind", "") or ""),
                "object": str(getattr(reference, "object", "") or ""),
                "detail": str(getattr(reference, "detail", "") or ""),
                "report": "",
                "page": "",
                "visual": "",
                "hidden": "",
            }
        )
    for record in getattr(analysis, "report_records", []) or []:
        if not isinstance(record, Mapping):
            continue
        rows.append(
            {
                "source": source,
                "type": "report",
                "kind": str(record.get("usage_kind") or ""),
                "object": str(record.get("visual_title") or record.get("visual_type") or ""),
                "detail": str(record.get("detail") or ""),
                "report": str(record.get("report_name") or ""),
                "page": str(record.get("page_name") or ""),
                "visual": str(record.get("visual_type") or ""),
                "hidden": "TRUE" if record.get("is_hidden") else "FALSE",
            }
        )
    rows.sort(
        key=lambda row: (
            row["type"],
            row["kind"],
            row["object"].casefold(),
            row["report"].casefold(),
            row["page"].casefold(),
        )
    )
    return rows


def write_dependencies_csv(
    rows: Iterable[Mapping[str, Any]],
    directory: Path | str,
    *,
    table: str,
    name: str,
) -> Path:
    target = Path(directory)
    stem = output_stem(table, name)
    return _write_csv(
        target / f"Dependencies_{stem}.csv", DEPENDENCY_FIELDS, rows
    )


OBJECT_EXPORT_MODES = {
    "full": "Full",
    "simple": "Simple",
    "no_dax": "SimpleNoDax",
}


def _export_timestamp() -> str:
    return datetime.now().strftime("%d-%m-%Y %H:%M:%S")


def _table_object_details(result: Any, table: str) -> dict[str, Any]:
    wanted = str(table or "").casefold()
    info = next(
        (
            item
            for item in (getattr(result.stats, "tables", []) or [])
            if str(item.table).casefold() == wanted
        ),
        None,
    )
    columns = [
        item
        for item in (getattr(result, "columns", []) or [])
        if str(item.column.table).casefold() == wanted
    ]
    measures = [
        item
        for item in (getattr(result, "measures", []) or [])
        if str(item.measure.table).casefold() == wanted
    ]
    hierarchies = [
        item
        for item in (getattr(result, "hierarchies", []) or [])
        if str(item.table).casefold() == wanted
    ]
    return {
        "name": table,
        "type": "Table",
        "table": table,
        "status": "Used" if columns or measures or hierarchies else "Unused",
        "rows": int(getattr(info, "rows", 0) or 0),
        "size": format_bytes(getattr(info, "size_total_bytes", 0)) if info else "",
        "storage_mode": str(getattr(info, "storage_mode", "") or ""),
        "partition_count": int(getattr(info, "partition_count", 0) or 0),
        "columns": [
            {
                "name": item.column.column,
                "type": item.column.column_type,
                "data_type": item.column.data_type,
                "status": item.status,
                "expression": item.column.expression,
            }
            for item in columns
        ],
        "measures": [
            {
                "name": item.measure.measure,
                "data_type": item.measure.data_type,
                "status": item.status,
                "expression": item.measure.expression,
            }
            for item in measures
        ],
        "hierarchies": [
            {
                "name": item.name,
                "levels": str(item.hierarchy.get("levels") or ""),
                "status": item.status,
            }
            for item in hierarchies
        ],
    }


def object_details_payload(
    result: Any,
    *,
    kind: str,
    table: str,
    name: str,
    mode: str = "full",
) -> dict[str, Any]:
    """Payload JSON satu objek untuk menu Exports."""
    wanted_mode = str(mode or "full").strip().lower()
    if wanted_mode not in OBJECT_EXPORT_MODES:
        raise ExtractionError("Export mode must be full, simple, or no_dax.")
    wanted_kind = str(kind or "").strip().lower()
    rows = dependency_rows(result, kind=wanted_kind, table=table, name=name)
    if wanted_kind == "table":
        details = _table_object_details(result, table)
    else:
        from .analysis_details import item_details

        analysis = _analysis_of(result, wanted_kind, table, name)
        if analysis is None:
            raise ExtractionError(
                "The selected item was not found in the analysis results."
            )
        details = item_details(result, analysis, kind=wanted_kind)
    if wanted_mode in {"simple", "no_dax"}:
        payload = {
            "export_date": _export_timestamp(),
            "kind": wanted_kind,
            "table": table,
            "name": name,
            "type": str(details.get("type") or ""),
            "status": str(details.get("status") or ""),
            "expression": str(details.get("expression") or ""),
            "dependencies": len(rows),
        }
        if wanted_mode == "no_dax":
            payload.pop("expression", None)
        return payload
    return {
        "export_date": _export_timestamp(),
        "kind": wanted_kind,
        "table": table,
        "name": name,
        "details": details,
        "dependencies": rows,
    }


def write_object_json(
    result: Any,
    directory: Path | str,
    *,
    kind: str,
    table: str,
    name: str,
    mode: str = "full",
) -> Path:
    wanted_mode = str(mode or "full").strip().lower()
    payload = object_details_payload(
        result, kind=kind, table=table, name=name, mode=wanted_mode
    )
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    stem = safe_name(f"{kind}_{table}_{name}", "Export")
    path = target / f"Export_{OBJECT_EXPORT_MODES[wanted_mode]}_{stem}.json"
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def write_uses_xlsx(
    result: Any,
    directory: Path | str,
    *,
    kind: str,
    table: str,
    name: str,
) -> Path:
    rows = dependency_rows(result, kind=kind, table=table, name=name)
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    stem = safe_name(f"{kind}_{table}_{name}", "Export")
    path = target / f"Export_Uses_{stem}.xlsx"
    frame = pd.DataFrame(rows, columns=DEPENDENCY_FIELDS)
    frame.columns = [str(column).capitalize() for column in DEPENDENCY_FIELDS]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Uses", {"Object": 40, "Detail": 56})
    return path
