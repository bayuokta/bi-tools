"""Ekspor tab Best practice mengikuti template Measure Killer.

Empat kolom: ``Rule``, ``Violation Score``, ``Severity``, ``Object``; satu baris
per temuan. ``Rule`` memakai nama aturan dari katalog (sudah berprefix kategori)
dan ``Violation Score`` adalah skor aturan yang sama untuk setiap barisnya.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .best_practice import build_best_practice
from .errors import ExtractionError
from .metadata_common import write_sheet

BEST_PRACTICE_COLUMNS = ["Rule", "Violation Score", "Severity", "Object"]


def build_best_practice_rows(result: Any) -> list[dict[str, Any]]:
    """Susun 4 kolom template dari hasil ``build_best_practice``."""
    payload = build_best_practice(result)
    if not payload.get("available", False):
        raise ExtractionError(
            str(payload.get("error") or "Best practice catalog is unavailable.")
        )
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    items.sort(
        key=lambda item: (
            -int(item.get("rule_score") or 0),
            str(item.get("rule_name") or "").casefold(),
            str(item.get("object") or "").casefold(),
        )
    )
    return [
        {
            "Rule": str(item.get("rule_name") or ""),
            "Violation Score": int(item.get("rule_score") or 0),
            "Severity": int(item.get("severity") or 1),
            "Object": str(item.get("object") or ""),
        }
        for item in items
    ]


def write_best_practice_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet Best practice dengan 4 kolom template."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(build_best_practice_rows(result), columns=BEST_PRACTICE_COLUMNS)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Best practice")
    return target
