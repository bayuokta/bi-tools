"""Ekspor hasil lineage/dependensi analisa ke ``outputs`` (CSV/JSON).

Seluruh isi berasal dari payload lineage yang sudah dibangun
(``core.analysis_lineage``) atau dari ``AnalysisResult`` di sesi analisa; modul
ini hanya memformat berkas dan tidak menghitung ulang dependensi.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
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
    return safe_name(f"{safe_name(table, 'Tabel')}_{safe_name(name, 'Item')}")


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
