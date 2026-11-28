"""Ekspor tab Relationships mengikuti template Measure Killer.

Satu baris per relationship. Label memakai panah ASCII (``<-``/``<->``), ID
memakai GUID dari ``TMSCHEMA_RELATIONSHIPS.Name``, dan ``DAX_uses`` adalah
jumlah objek model yang bergantung pada relasi (``DISCOVER_CALC_DEPENDENCY``).
"""

from __future__ import annotations

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


def build_relationship_rows(result: Any) -> list[dict[str, Any]]:
    """Susun 10 kolom template, urut Name alfabetis."""
    relationships = [
        relationship_row(item)
        for item in (getattr(result, "relationships", []) or [])
        if isinstance(item, Mapping)
    ]
    relationships.sort(key=lambda item: item["label"].casefold())
    rows: list[dict[str, Any]] = []
    for item in relationships:
        rows.append(
            {
                "Name": item["label"],
                "ID": item["relationship_id"],
                "Is_active": item["type"],
                "Cross_filter": item["cross"],
                "Cardinality": f" {item['cardinality']} ",
                "Status": item["status"],
                "Auto_created": item["auto"],
                "DAX_uses": int(item["used"]),
                "From_column": (
                    f"{item['from_table']}[{item['from_column']}]"
                ),
                "To_column": f"{item['to_table']}[{item['to_column']}]",
            }
        )
    return rows


def write_relationship_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet Relationships dengan 10 kolom template."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        build_relationship_rows(result), columns=RELATIONSHIP_RESULT_COLUMNS
    )
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Relationships")
    return target
