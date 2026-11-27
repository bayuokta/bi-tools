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
from pathlib import Path
from typing import Any, Iterable, Mapping

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
        raise ValueError("Isi gambar lineage kosong.")
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
