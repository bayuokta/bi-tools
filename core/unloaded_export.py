"""Ekspor tab Unloaded M queries mengikuti template Measure Killer.

Satu baris per tabel pemakai; objek tanpa pemakaian mendapat satu baris dengan
kolom ``Usage_*`` kosong. Kolom ``Usage_status``/``Usage_number_of_uses`` sama
dengan ``Table_status``/``Table_uses`` di tab Tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .metadata_common import write_sheet
from .unloaded_queries import build_unloaded_queries

UNLOADED_COLUMNS = [
    "Name",
    "Type",
    "Source",
    "Status",
    "Number_of_uses",
    "Usage_name",
    "Usage_type",
    "Usage_source",
    "Usage_status",
    "Usage_number_of_uses",
]


def build_unloaded_rows(result: Any) -> list[dict[str, Any]]:
    """Susun 10 kolom template dari hasil ``build_unloaded_queries``."""
    rows: list[dict[str, Any]] = []
    for item in build_unloaded_queries(result):
        usages = list(item.get("usages") or [])
        if not usages:
            rows.append(
                {
                    "Name": str(item.get("name") or ""),
                    "Type": str(item.get("type") or ""),
                    "Source": str(item.get("source") or ""),
                    "Status": str(item.get("status") or ""),
                    "Number_of_uses": int(item.get("uses") or 0),
                    "Usage_name": "",
                    "Usage_type": "",
                    "Usage_source": "",
                    "Usage_status": "",
                    "Usage_number_of_uses": "",
                }
            )
            continue
        for usage in usages:
            rows.append(
                {
                    "Name": str(item.get("name") or ""),
                    "Type": str(item.get("type") or ""),
                    "Source": str(item.get("source") or ""),
                    "Status": str(item.get("status") or ""),
                    "Number_of_uses": int(item.get("uses") or 0),
                    "Usage_name": str(usage.get("name") or ""),
                    "Usage_type": str(usage.get("type") or ""),
                    "Usage_source": str(usage.get("source") or ""),
                    "Usage_status": str(usage.get("status") or ""),
                    "Usage_number_of_uses": int(usage.get("uses") or 0),
                }
            )
    return rows


def write_unloaded_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet Unloaded power query dengan 10 kolom template."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(build_unloaded_rows(result), columns=UNLOADED_COLUMNS)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Unloaded power query")
    return target
