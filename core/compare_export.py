"""Ekspor hasil perbandingan semantic model (read-only).

CSV memuat seluruh item. Script adalah pratinjau TMSL untuk objek yang aman
dibuat ulang; objek tabel/partisi ditandai ``manual`` karena membutuhkan
keputusan dan validasi tersendiri. Tidak ada eksekusi TMSL di modul ini.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Mapping

from .analysis_export import safe_name

CSV_COLUMNS = (
    "Type",
    "Name",
    "Parent",
    "Status",
    "Action",
    "Source",
    "Target",
    "Properties",
)


def script_manifest(result: Mapping[str, Any]) -> dict[str, Any]:
    """Manifest script dari definisi TOM persis.

    File ini adalah pratinjau; tidak dieksekusi oleh BI Tools. Mode TMSL
    menghasilkan JSON TMSL; mode TMDL menghasilkan blok TMDL persis dari TOM.
    """
    actions: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    options = result.get("options") or {}
    tmsl = bool(options.get("tmsl"))
    for item in result.get("items") or []:
        if item.get("action") not in {"Create", "Update"}:
            continue
        definition = str(item.get("source_definition") or "")
        entry = {
            "type": item.get("type"),
            "name": item.get("name"),
            "parent": item.get("parent") or "",
            "action": item.get("action"),
            "status": item.get("status"),
            "format": "tmsl" if tmsl else "tmdl",
            "definition": definition,
        }
        if item.get("type") in {"Table", "M query", "Data source"}:
            entry["reason"] = (
                "This object definition is included in the TOM block; review it before applying."
            )
            manual.append(entry)
        else:
            actions.append(entry)
    return {
        "generated_at": result.get("generated_at") or "",
        "source": result.get("source") or {},
        "target": result.get("target") or {},
        "note": (
            "Read-only preview from the TOM serializer. The script is not executed "
            "by BI Tools; validate and apply it manually."
        ),
        "actions": actions,
        "manual": manual,
    }


def write_compare_csv(
    result: Mapping[str, Any], target: Path | str
) -> Path:
    """Tulis CSV seluruh item perbandingan (UTF-8 BOM, CRLF)."""
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for item in result.get("items") or []:
            properties = "; ".join(
                f"{property_.get('name')}: {property_.get('source')} -> "
                f"{property_.get('target')}"
                for property_ in item.get("properties") or []
                if property_.get("source") != property_.get("target")
            )
            writer.writerow(
                [
                    item.get("type") or "",
                    item.get("name") or "",
                    item.get("parent") or "",
                    item.get("status") or "",
                    item.get("action") or "",
                    item.get("source_definition") or "",
                    item.get("target_definition") or "",
                    properties,
                ]
            )
    return path


def write_compare_script(
    result: Mapping[str, Any], target: Path | str
) -> Path:
    """Tulis manifest script JSON (pratinjau, bukan eksekusi)."""
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = script_manifest(result)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace("\n", "\r\n") + "\r\n")
    return path


def default_compare_stem(source: str, target: str) -> str:
    """Nama file aman ``Compare_<source>_vs_<target>``."""
    left = safe_name(source, "Source")
    right = safe_name(target, "Target")
    return safe_name(f"Compare_{left}_vs_{right}", "Compare")
