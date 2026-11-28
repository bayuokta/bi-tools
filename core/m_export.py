"""Ekspor tab M queries mengikuti template Measure Killer.

Satu baris per ekspresi M: partisi tabel, ekspresi refresh policy, shared
M query, dan parameter. ``Source`` berisi nama dataset (bukan mode partisi),
dan ``Warnings`` berisi status error partisi bila ada.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .metadata_common import write_sheet

M_RESULT_COLUMNS = ["Name", "Type", "Source", "Warnings", "Expression"]


def build_m_rows(result: Any) -> list[dict[str, Any]]:
    """Susun 5 kolom template dari ``AnalysisResult.m_queries``."""
    source = str(getattr(result, "dataset_name", "") or "")
    rows: list[dict[str, Any]] = []
    for item in getattr(result, "m_queries", []) or []:
        if not isinstance(item, Mapping):
            continue
        rows.append(
            {
                "Name": str(item.get("name") or ""),
                "Type": str(item.get("kind") or ""),
                "Source": source,
                "Warnings": str(item.get("warning") or ""),
                "Expression": str(item.get("expression") or ""),
            }
        )
    return rows


def write_m_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet M expressions dengan 5 kolom template."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(build_m_rows(result), columns=M_RESULT_COLUMNS)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "M expressions")
    return target
