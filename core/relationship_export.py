"""Ekspor tab Relationships mengikuti template Measure Killer.

Satu baris per relationship. Label memakai panah ASCII (``<-``/``<->``), ID
memakai GUID dari ``TMSCHEMA_RELATIONSHIPS.Name``, dan ``DAX_uses`` adalah
jumlah objek model yang bergantung pada relasi (``DISCOVER_CALC_DEPENDENCY``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .metadata_common import write_sheet

RELATIONSHIP_RESULT_COLUMNS = [
    "Name",
    "ID",
    "Is_active",
    "Cross_filter",
    "Cardinality",
    "Status",
    "Auto_created",
    "DAX_uses",
    "From_column",
    "To_column",
    "used_in_name",
    "used_in_ID",
    "used_in_type",
    "used_in_table",
    "used_in_status",
    "used_in_number_of_uses",
]

CARDINALITY_SYMBOL = {"many": "N", "one": "1", "none": "0"}
CROSS_LABELS = {
    "onedirection": "Single",
    "single": "Single",
    "bothdirections": "Both",
    "both": "Both",
    "automatic": "Auto",
    "auto": "Auto",
}


def _cardinality_code(value: Any) -> str:
    text = str(value or "").casefold()
    return CARDINALITY_SYMBOL.get(text, str(value or "") or "?")


def _cross_text(value: Any) -> str:
    text = str(value or "")
    return CROSS_LABELS.get(text.casefold(), text)


def cardinality_text(item: Mapping[str, Any]) -> str:
    """Cardinality ASCII, mis. ``N <- 1`` atau ``N <-> 1``."""
    from_code = _cardinality_code(item.get("from_cardinality"))
    to_code = _cardinality_code(item.get("to_cardinality"))
    if from_code == "N" and to_code == "N":
        to_code = "M"
    cross = _cross_text(item.get("cross_filtering") or item.get("cross"))
    arrow = "<->" if cross == "Both" else "<-"
    return f"{from_code} {arrow} {to_code}"


def relationship_label(item: Mapping[str, Any]) -> str:
    """Nama relationship gaya template dengan kutip tabel."""
    from_table = str(item.get("from_table") or "")
    from_column = str(item.get("from_column") or "")
    to_table = str(item.get("to_table") or "")
    to_column = str(item.get("to_column") or "")
    return (
        f"'{from_table}'[{from_column}] {cardinality_text(item)} "
        f"'{to_table}'[{to_column}]"
    )


def relationship_row(item: Mapping[str, Any]) -> dict[str, Any]:
    """Payload satu relationship untuk UI dan ekspor."""
    from_table = str(item.get("from_table") or "")
    from_column = str(item.get("from_column") or "")
    to_table = str(item.get("to_table") or "")
    to_column = str(item.get("to_column") or "")
    is_active = bool(item.get("is_active"))
    cross = _cross_text(item.get("cross_filtering") or item.get("cross"))
    relationship_id = str(
        item.get("relationship_id") or item.get("name") or item.get("id") or ""
    )
    return {
        "name": str(item.get("name") or relationship_id),
        "relationship_id": relationship_id,
        "label": relationship_label(item),
        "from_table": from_table,
        "from_column": from_column,
        "to_table": to_table,
        "to_column": to_column,
        "type": "Active" if is_active else "Inactive",
        "cross": cross,
        "cross_filtering": str(item.get("cross_filtering") or ""),
        "cardinality": cardinality_text(item),
        "status": "Used" if is_active else "Unused",
        "auto": "Yes" if item.get("is_auto") else "No",
        "used": int(item.get("dependent_count") or 0),
        "security_filtering": str(item.get("security_filtering") or ""),
        "is_active": is_active,
        "join_on_date_behavior": str(item.get("join_on_date_behavior") or ""),
        "from_cardinality": str(item.get("from_cardinality") or ""),
        "to_cardinality": str(item.get("to_cardinality") or ""),
    }


_USER_RELATIONSHIP = re.compile(
    r"USERELATIONSHIP\s*\(\s*"
    r"((?:'[^']+'|[A-Za-z_][\w ]*)\[[^\]]+\])\s*,\s*"
    r"((?:'[^']+'|[A-Za-z_][\w ]*)\[[^\]]+\])\s*\)",
    re.IGNORECASE,
)


def _dax_reference(text: str) -> tuple[str, str]:
    token = text.strip()
    if token.startswith("'"):
        table, rest = token[1:].split("'", 1)
        return table.strip(), rest[1:-1].strip()
    table, rest = token.split("[", 1)
    return table.strip(), rest[:-1].strip()


def _relationship_key(item: Mapping[str, Any]) -> str:
    return str(
        item.get("relationship_id")
        or item.get("name")
        or item.get("id")
        or ""
    )


def relationship_usage(result: Any) -> dict[str, list[dict[str, Any]]]:
    """Wrapper publik untuk pemakaian relasi (Measure Killer)."""
    return _relationship_usage(result)


def _relationship_usage(result: Any) -> dict[str, list[dict[str, Any]]]:
    """Measure yang memakai relasi lewat ``USERELATIONSHIP`` di DAX."""
    pairs: dict[frozenset[tuple[str, str]], str] = {}
    for relationship in getattr(result, "relationships", []) or []:
        if not isinstance(relationship, Mapping):
            continue
        pair = frozenset(
            (
                (
                    str(relationship.get("from_table") or "").casefold(),
                    str(relationship.get("from_column") or "").casefold(),
                ),
                (
                    str(relationship.get("to_table") or "").casefold(),
                    str(relationship.get("to_column") or "").casefold(),
                ),
            )
        )
        pairs[pair] = _relationship_key(relationship)

    usage: dict[str, list[dict[str, Any]]] = {}
    for analysis in getattr(result, "measures", []) or []:
        measure = getattr(analysis, "measure", None)
        if measure is None:
            continue
        expression = str(getattr(measure, "expression", "") or "")
        for match in _USER_RELATIONSHIP.finditer(expression):
            left = _dax_reference(match.group(1))
            right = _dax_reference(match.group(2))
            pair = frozenset(
                (
                    (left[0].casefold(), left[1].casefold()),
                    (right[0].casefold(), right[1].casefold()),
                )
            )
            relationship = pairs.get(pair)
            if not relationship:
                continue
            entry = {
                "name": str(getattr(measure, "measure", "") or ""),
                "id": int(getattr(measure, "measure_id", 0) or 0),
                "type": "Measure",
                "table": str(getattr(measure, "table", "") or ""),
                "status": str(getattr(analysis, "status", "") or ""),
                "uses": int(getattr(analysis, "use_count", 0) or 0),
            }
            bucket = usage.setdefault(relationship, [])
            if entry not in bucket:
                bucket.append(entry)
    for bucket in usage.values():
        bucket.sort(
            key=lambda item: (item["table"].casefold(), item["name"].casefold())
        )
    return usage


def build_relationship_rows(result: Any) -> list[dict[str, Any]]:
    """Susun 16 kolom template; satu baris per pemakaian measure."""
    relationships = [
        relationship_row(item)
        for item in (getattr(result, "relationships", []) or [])
        if isinstance(item, Mapping)
    ]
    relationships.sort(key=lambda item: item["label"].casefold())
    usage = _relationship_usage(result)
    rows: list[dict[str, Any]] = []
    for item in relationships:
        entries = usage.get(item["relationship_id"], [])
        status = item["status"]
        dax_uses = int(item["used"])
        if entries:
            dax_uses = max(dax_uses, len(entries))
            status = (
                "Used"
                if any(entry["status"] != "Unused" for entry in entries)
                else "Used by unused"
            )
        base = {
            "Name": item["label"],
            "ID": item["relationship_id"],
            "Is_active": item["type"],
            "Cross_filter": item["cross"],
            "Cardinality": f" {item['cardinality']} ",
            "Status": status,
            "Auto_created": item["auto"],
            "DAX_uses": dax_uses,
            "From_column": f"{item['from_table']}[{item['from_column']}]",
            "To_column": f"{item['to_table']}[{item['to_column']}]",
        }
        if not entries:
            rows.append(
                {
                    **base,
                    "used_in_name": "",
                    "used_in_ID": "",
                    "used_in_type": "",
                    "used_in_table": "",
                    "used_in_status": "",
                    "used_in_number_of_uses": "",
                }
            )
            continue
        for entry in entries:
            rows.append(
                {
                    **base,
                    "used_in_name": entry["name"],
                    "used_in_ID": entry["id"],
                    "used_in_type": entry["type"],
                    "used_in_table": entry["table"],
                    "used_in_status": entry["status"],
                    "used_in_number_of_uses": entry["uses"],
                }
            )
    return rows


def write_relationship_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet Relationships dengan 16 kolom template."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        build_relationship_rows(result), columns=RELATIONSHIP_RESULT_COLUMNS
    )
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Relationships")
    return target
