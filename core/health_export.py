"""Ekspor tab Health dalam format internal BI Tools.

Health tidak memakai template Measure Killer. Enam kolom pertama sama dengan
tabel UI; kolom berikutnya menambah konteks (Rule ID, Kind, report/page/visual)
dan ukuran numerik agar hasilnya bisa difilter atau di-pivot di Excel.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .export_common import size_text
from .metadata_common import write_sheet
from .model_health import build_health

HEALTH_COLUMNS = [
    "Severity",
    "Area",
    "Rule",
    "Object",
    "Detail",
    "Size",
    "Rule ID",
    "Kind",
    "Report",
    "Page",
    "Visual",
    "Size_bytes",
]

RULE_LABELS = {
    "column_error": "Column has an error",
    "measure_error": "Measure has an error",
    "unused_table": "Unused table",
    "isolated_table": "Table has no relationship",
    "bidirectional_relationship": "Bidirectional relationship",
    "many_to_many_relationship": "Many-to-many relationship",
    "inactive_relationship": "Inactive relationship",
    "auto_relationship": "Auto-detected relationship",
    "large_dictionary": "Large column dictionary",
    "unused_calculated_column": "Unused calculated column",
    "page_without_visuals": "Page has no visuals",
    "hidden_page_with_visuals": "Hidden page with visuals",
    "missing_theme": "Report has no theme",
    "broken_visual": "Visual has unmapped fields",
}

SEVERITY_LABELS = {
    "critical": "Critical",
    "warning": "Warning",
    "info": "Info",
}

AREA_LABELS = {
    "model": "Model",
    "report": "Report",
}


def _detail_text(item: dict[str, Any]) -> str:
    """Gabungkan detail dan metrics seperti kolom Detail di UI."""
    parts: list[str] = []
    detail = str(item.get("detail") or "").strip()
    if detail:
        parts.append(detail)
    metrics = item.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    rule = str(item.get("rule") or "")
    if rule in {"unused_table", "isolated_table"}:
        parts.append(
            f"{int(metrics.get('columns') or 0):,} columns \u00b7 "
            f"{int(metrics.get('measures') or 0):,} measures"
        )
    elif rule == "large_dictionary":
        share = float(metrics.get("share") or 0)
        parts.append(
            f"dictionary {round(share * 100)}% \u00b7 "
            f"{size_text(metrics.get('dictionary'))}"
        )
    elif rule == "hidden_page_with_visuals":
        parts.append(f"{int(metrics.get('visuals') or 0):,} visuals")
    elif rule == "broken_visual":
        parts.append(
            f"{int(metrics.get('unresolved') or 0):,} unmapped fields"
        )
    return " \u00b7 ".join(part for part in parts if part)


def build_health_rows(result: Any) -> list[dict[str, Any]]:
    """Susun 12 kolom Health dari ``build_health`` (urut yang sama dengan UI)."""
    health = build_health(result)
    rows: list[dict[str, Any]] = []
    for item in health.get("items") or []:
        if not isinstance(item, dict):
            continue
        rule = str(item.get("rule") or "")
        severity = str(item.get("severity") or "")
        area = str(item.get("area") or "")
        size_bytes = int(item.get("size_bytes") or 0)
        rows.append(
            {
                "Severity": SEVERITY_LABELS.get(severity, severity),
                "Area": AREA_LABELS.get(area, area),
                "Rule": RULE_LABELS.get(rule, rule),
                "Object": str(item.get("object") or ""),
                "Detail": _detail_text(item),
                "Size": size_text(size_bytes) if size_bytes else "",
                "Rule ID": rule,
                "Kind": str(item.get("kind") or ""),
                "Report": str(item.get("report_name") or ""),
                "Page": str(item.get("page_name") or ""),
                "Visual": str(item.get("visual_title") or ""),
                "Size_bytes": size_bytes,
            }
        )
    return rows


def write_health_export(result: Any, path: Path | str) -> Path:
    """Tulis satu sheet Health dengan 12 kolom internal."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(build_health_rows(result), columns=HEALTH_COLUMNS)
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Health")
    return target
