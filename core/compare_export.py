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


def _property_value(item: Mapping[str, Any], name: str) -> str:
    for property_ in item.get("properties") or []:
        if str(property_.get("name") or "") == name:
            return str(property_.get("source") or "")
    return ""


def _tmsl_for(item: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """TMSL pratinjau untuk tipe yang didukung; alasan bila manual."""
    kind = str(item.get("type") or "")
    name = str(item.get("source_name") or item.get("target_name") or item.get("name") or "")
    if kind == "Measure":
        expression = _property_value(item, "Expression")
        if not expression:
            return None, "Ekspresi measure tidak tersedia di snapshot."
        measure: dict[str, Any] = {"name": name, "expression": expression}
        format_string = _property_value(item, "Format string")
        if format_string and format_string != "—":
            measure["formatString"] = format_string
        display_folder = _property_value(item, "Display folder")
        if display_folder and display_folder != "—":
            measure["displayFolder"] = display_folder
        return {"createOrReplace": {"measure": measure}}, ""
    if kind == "Expression":
        expression = str(item.get("source_definition") or "")
        if not expression:
            return None, "Ekspresi M tidak tersedia."
        return {
            "createOrReplace": {
                "expression": {
                    "name": name,
                    "kind": _property_value(item, "Kind") or "m",
                    "expression": expression,
                }
            }
        }, ""
    if kind == "Relationship":
        from_value = _property_value(item, "From")
        to_value = _property_value(item, "To")
        if "[" not in from_value or "[" not in to_value:
            return None, "Kolom relasi tidak lengkap."
        from_table, from_column = from_value.split("[", 1)
        to_table, to_column = to_value.split("[", 1)
        relationship: dict[str, Any] = {
            "fromTable": from_table.strip("' "),
            "fromColumn": from_column.rstrip("]"),
            "toTable": to_table.strip("' "),
            "toColumn": to_column.rstrip("]"),
            "crossFilteringBehavior": _property_value(item, "Cross filter") or "oneDirection",
            "isActive": _property_value(item, "Active") == "Yes",
        }
        return {"createOrReplace": {"relationship": relationship}}, ""
    if kind == "Role":
        role: dict[str, Any] = {
            "name": name,
            "modelPermission": _property_value(item, "Model permission") or "read",
        }
        members = _property_value(item, "Members")
        if members and members != "—":
            role["members"] = [
                {"memberName": member.strip()}
                for member in members.split(",")
                if member.strip()
            ]
        return {"createOrReplace": {"role": role}}, ""
    return None, f"Tipe {kind or 'objek'} belum didukung untuk script otomatis."


def script_manifest(result: Mapping[str, Any]) -> dict[str, Any]:
    """Manifest script pratinjau dari hasil compare."""
    actions: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    for item in result.get("items") or []:
        if item.get("action") not in {"Create", "Update"}:
            continue
        tmsl, reason = _tmsl_for(item)
        entry = {
            "type": item.get("type"),
            "name": item.get("name"),
            "parent": item.get("parent") or "",
            "action": item.get("action"),
            "status": item.get("status"),
        }
        if tmsl is None:
            entry["reason"] = reason
            manual.append(entry)
        else:
            entry["tmsl"] = tmsl
            actions.append(entry)
    return {
        "generated_at": result.get("generated_at") or "",
        "source": result.get("source") or {},
        "target": result.get("target") or {},
        "note": (
            "Pratinjau read-only. Script tidak dijalankan oleh BI Tools; "
            "validasi dan terapkan secara manual."
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
