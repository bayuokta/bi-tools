"""Pemeriksaan kesehatan model dan report dari hasil analisa.

Modul ini hanya membaca ``AnalysisResult`` yang sudah ada: tidak ada request
XMLA/REST, tidak menulis berkas, dan tidak mengarang angka. Skor praktik per
report bersifat heuristik; rincian penalti ikut dikirim agar UI dapat
menjelaskan asal angkanya.

Aturan yang butuh sumber lain (subscription, alert, activity/views, tanda
date table) sengaja tidak dibuat di sini.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

RULES_VERSION = 1

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITY_RANK = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_WARNING: 1,
    SEVERITY_INFO: 2,
}

# Nilai kanonik sama dengan ``core.usage_service.STATUS_UNUSED``. Sengaja
# ditulis ulang agar modul ini tidak mengimpor modul analisa yang berat.
UNUSED_STATUS = "Unused"
HELPER_TABLES = {"_measures"}
NON_TABLE_STORAGE = {"calculationgroup", "calculation group"}

# Ambang dictionary: kolom teks ber-kardinalitas tinggi. Bisa diubah tanpa
# mengubah aturan lain.
DICTIONARY_SHARE_WARN = 0.5
DICTIONARY_MIN_BYTES = 1_000_000

# Penalti skor praktik per report: (poin per kejadian, batas total).
PRACTICE_PENALTIES = {
    "broken_visual": (5, 30),
    "page_without_visuals": (3, 15),
    "unresolved_field": (1, 20),
}
PRACTICE_MAX = 100


def build_health(result: Any) -> dict[str, Any]:
    """Susun daftar temuan kesehatan + skor praktik per report."""
    broken = _broken_visuals(result)
    items = _model_items(result) + _report_items(result, broken)
    items.sort(key=_item_sort_key)
    counts = {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 0, SEVERITY_INFO: 0}
    for item in items:
        counts[item["severity"]] += 1
    return {
        "rules_version": RULES_VERSION,
        "reports_included": bool(getattr(result, "reports_included", True)),
        "counts": counts,
        "items": items,
        "practice": _practice(result, broken),
    }


def broken_visual_counts(result: Any) -> dict[str, int]:
    """Jumlah visual unik per report yang punya field tak terpetakan."""
    counts: dict[str, int] = {}
    for report_id, visuals in _broken_visuals(result).items():
        total = sum(1 for _page, visual in visuals if visual)
        if total:
            counts[report_id] = total
    return counts


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
def _model_items(result: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    columns = list(getattr(result, "columns", []) or [])
    measures = list(getattr(result, "measures", []) or [])
    tables = list(getattr(getattr(result, "stats", None), "tables", []) or [])
    relationships = [
        row
        for row in (getattr(result, "relationships", []) or [])
        if isinstance(row, Mapping)
    ]

    for analysis in columns:
        column = analysis.column
        table = str(getattr(column, "table", "") or "")
        name = str(getattr(column, "column", "") or "")
        size_bytes = int(getattr(column, "size_total_bytes", 0) or 0)
        if bool(getattr(column, "has_error", False)):
            items.append(
                _item(
                    rule="column_error",
                    severity=SEVERITY_CRITICAL,
                    area="model",
                    kind="column",
                    object=f"{table}[{name}]",
                    table=table,
                    name=name,
                    detail=_clip(str(getattr(column, "error_message", "") or "")),
                    size_bytes=size_bytes,
                    target={"kind": "column", "table": table, "name": name},
                )
            )
        if (
            str(getattr(analysis, "status", "") or "") == UNUSED_STATUS
            and bool(getattr(column, "is_calculated", False))
            and size_bytes > 0
        ):
            items.append(
                _item(
                    rule="unused_calculated_column",
                    severity=SEVERITY_INFO,
                    area="model",
                    kind="column",
                    object=f"{table}[{name}]",
                    table=table,
                    name=name,
                    size_bytes=size_bytes,
                    metrics={"size": size_bytes},
                    target={"kind": "column", "table": table, "name": name},
                )
            )
        dictionary = int(getattr(column, "size_dictionary_bytes", 0) or 0)
        if (
            size_bytes > 0
            and dictionary >= DICTIONARY_MIN_BYTES
            and dictionary / size_bytes >= DICTIONARY_SHARE_WARN
        ):
            items.append(
                _item(
                    rule="large_dictionary",
                    severity=SEVERITY_WARNING,
                    area="model",
                    kind="column",
                    object=f"{table}[{name}]",
                    table=table,
                    name=name,
                    size_bytes=size_bytes,
                    metrics={
                        "dictionary": dictionary,
                        "size": size_bytes,
                        "share": round(dictionary / size_bytes, 3),
                    },
                    target={"kind": "column", "table": table, "name": name},
                )
            )

    for analysis in measures:
        measure = analysis.measure
        table = str(getattr(measure, "table", "") or "")
        name = str(getattr(measure, "measure", "") or "")
        if bool(getattr(measure, "has_error", False)):
            items.append(
                _item(
                    rule="measure_error",
                    severity=SEVERITY_CRITICAL,
                    area="model",
                    kind="measure",
                    object=f"{table}[{name}]",
                    table=table,
                    name=name,
                    detail=_clip(str(getattr(measure, "error_message", "") or "")),
                    target={"kind": "measure", "table": table, "name": name},
                )
            )

    by_table: dict[str, dict[str, Any]] = {}
    for analysis in columns:
        key = str(getattr(analysis.column, "table", "") or "").casefold()
        entry = by_table.setdefault(key, {"name": "", "columns": [], "measures": []})
        entry["name"] = entry["name"] or str(getattr(analysis.column, "table", ""))
        entry["columns"].append(analysis)
    for analysis in measures:
        key = str(getattr(analysis.measure, "table", "") or "").casefold()
        entry = by_table.setdefault(key, {"name": "", "columns": [], "measures": []})
        entry["name"] = entry["name"] or str(getattr(analysis.measure, "table", ""))
        entry["measures"].append(analysis)

    non_table_keys: set[str] = set()
    table_stats: dict[str, Any] = {}
    for table in tables:
        key = str(getattr(table, "table", "") or "").casefold()
        table_stats[key] = table
        mode = str(getattr(table, "storage_mode", "") or "").casefold()
        if mode in NON_TABLE_STORAGE:
            non_table_keys.add(key)

    related: set[str] = set()
    for index, relationship in enumerate(relationships):
        for side in ("from_table", "to_table"):
            name = str(relationship.get(side) or "")
            if name:
                related.add(name.casefold())
        cross = str(relationship.get("cross_filtering") or "").casefold()
        from_card = str(relationship.get("from_cardinality") or "").casefold()
        to_card = str(relationship.get("to_cardinality") or "").casefold()
        label = _relationship_object(relationship)
        target = {"kind": "relationship", "name": str(relationship.get("name") or "")}
        findings = []
        if cross == "bothdirections":
            findings.append(("bidirectional_relationship", SEVERITY_WARNING))
        if from_card == "many" and to_card == "many":
            findings.append(("many_to_many_relationship", SEVERITY_WARNING))
        if not bool(relationship.get("is_active", True)):
            findings.append(("inactive_relationship", SEVERITY_INFO))
        if bool(relationship.get("is_auto", False)):
            findings.append(("auto_relationship", SEVERITY_INFO))
        for rule, severity in findings:
            item = _item(
                rule=rule,
                severity=severity,
                area="model",
                kind="relationship",
                object=label,
                detail=_clip(str(relationship.get("name") or "")),
                target=target,
            )
            # ``index`` membuat id tetap unik walau nama relasi kembar.
            item["id"] += f":{index}"
            items.append(item)

    for key, entry in by_table.items():
        if key in HELPER_TABLES or key in non_table_keys:
            continue
        analyses = list(entry["columns"]) + list(entry["measures"])
        table_name = str(entry["name"] or "")
        if not analyses:
            continue
        stats = table_stats.get(key)
        size_bytes = (
            int(getattr(stats, "size_total_bytes", 0) or 0) if stats is not None else 0
        )
        if all(
            str(getattr(analysis, "status", "") or "") == UNUSED_STATUS
            for analysis in analyses
        ):
            items.append(
                _item(
                    rule="unused_table",
                    severity=SEVERITY_WARNING,
                    area="model",
                    kind="table",
                    object=table_name,
                    table=table_name,
                    size_bytes=size_bytes,
                    metrics={
                        "columns": len(entry["columns"]),
                        "measures": len(entry["measures"]),
                    },
                    target={"kind": "table", "table": table_name},
                )
            )
        if key not in related:
            items.append(
                _item(
                    rule="isolated_table",
                    severity=SEVERITY_WARNING,
                    area="model",
                    kind="table",
                    object=table_name,
                    table=table_name,
                    size_bytes=size_bytes,
                    metrics={
                        "columns": len(entry["columns"]),
                        "measures": len(entry["measures"]),
                        "rows": int(getattr(stats, "rows", 0) or 0)
                        if stats is not None
                        else 0,
                    },
                    target={"kind": "table", "table": table_name},
                )
            )
    return items


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _broken_visuals(result: Any) -> dict[str, dict[tuple[str, str], list[str]]]:
    broken: dict[str, dict[tuple[str, str], list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in getattr(result, "unresolved", []) or []:
        if not isinstance(row, Mapping):
            continue
        report_id = str(row.get("report_id") or "")
        page_id = str(row.get("page_id") or "")
        visual_id = str(row.get("visual_id") or "")
        if not report_id:
            continue
        broken[report_id][(page_id, visual_id)].append(str(row.get("query_ref") or ""))
    return broken


def _report_items(
    result: Any, broken: Mapping[str, Mapping[tuple[str, str], list[str]]]
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    reports = [
        row for row in (getattr(result, "reports", []) or []) if isinstance(row, Mapping)
    ]
    pages_map = dict(getattr(result, "report_pages", {}) or {})
    titles: dict[tuple[str, str, str], str] = {}
    for row in getattr(result, "unresolved", []) or []:
        if not isinstance(row, Mapping):
            continue
        key = (
            str(row.get("report_id") or ""),
            str(row.get("page_id") or ""),
            str(row.get("visual_id") or ""),
        )
        if key not in titles:
            titles[key] = str(row.get("visual_title") or "")
    for report in reports:
        report_id = str(report.get("report_id") or "")
        report_name = str(
            report.get("report_name") or report.get("name") or report_id or ""
        )
        pages = [
            page
            for page in pages_map.get(report_id, []) or []
            if isinstance(page, Mapping)
        ]
        for page in pages:
            page_id = str(page.get("page_id") or "")
            page_name = str(page.get("page_name") or "")
            visual_count = int(page.get("visual_count") or 0)
            if visual_count == 0:
                items.append(
                    _item(
                        rule="page_without_visuals",
                        severity=SEVERITY_WARNING,
                        area="report",
                        kind="page",
                        object=page_name or page_id,
                        report_id=report_id,
                        report_name=report_name,
                        page_id=page_id,
                        page_name=page_name,
                        target={
                            "kind": "report",
                            "report_id": report_id,
                            "page_id": page_id,
                        },
                    )
                )
            if bool(page.get("is_hidden")) and visual_count > 0:
                items.append(
                    _item(
                        rule="hidden_page_with_visuals",
                        severity=SEVERITY_INFO,
                        area="report",
                        kind="page",
                        object=page_name or page_id,
                        report_id=report_id,
                        report_name=report_name,
                        page_id=page_id,
                        page_name=page_name,
                        metrics={"visuals": visual_count},
                        target={
                            "kind": "report",
                            "report_id": report_id,
                            "page_id": page_id,
                        },
                    )
                )
        if (
            str(report.get("status") or "") == "ok"
            and not str(report.get("theme") or "").strip()
        ):
            items.append(
                _item(
                    rule="missing_theme",
                    severity=SEVERITY_INFO,
                    area="report",
                    kind="report",
                    object=report_name or report_id,
                    report_id=report_id,
                    report_name=report_name,
                    target={"kind": "report", "report_id": report_id},
                )
            )
        for (page_id, visual_id), refs in (broken.get(report_id) or {}).items():
            if not visual_id:
                continue
            page_name = next(
                (
                    str(page.get("page_name") or "")
                    for page in pages
                    if str(page.get("page_id") or "") == page_id
                ),
                "",
            )
            visual_title = titles.get((report_id, page_id, visual_id), "")
            unique = sorted({ref for ref in refs if ref})
            detail = ", ".join(unique[:3])
            if len(unique) > 3:
                detail += f" +{len(unique) - 3}"
            items.append(
                _item(
                    rule="broken_visual",
                    severity=SEVERITY_CRITICAL,
                    area="report",
                    kind="visual",
                    object=visual_title or visual_id[:8],
                    report_id=report_id,
                    report_name=report_name,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_title=visual_title,
                    detail=_clip(detail),
                    metrics={"unresolved": len(refs)},
                    target={
                        "kind": "report",
                        "report_id": report_id,
                        "page_id": page_id,
                        "visual_id": visual_id,
                    },
                )
            )
    return items


def _practice(
    result: Any, broken: Mapping[str, Mapping[tuple[str, str], list[str]]]
) -> dict[str, dict[str, Any]]:
    practice: dict[str, dict[str, Any]] = {}
    pages_map = dict(getattr(result, "report_pages", {}) or {})
    for report in getattr(result, "reports", []) or []:
        if not isinstance(report, Mapping):
            continue
        if str(report.get("status") or "") != "ok":
            continue
        report_id = str(report.get("report_id") or "")
        if not report_id:
            continue
        pages = [
            page
            for page in pages_map.get(report_id, []) or []
            if isinstance(page, Mapping)
        ]
        counts = {
            "broken_visual": len(broken.get(report_id) or {}),
            "page_without_visuals": sum(
                1 for page in pages if int(page.get("visual_count") or 0) == 0
            ),
            "unresolved_field": sum(
                len(refs) for refs in (broken.get(report_id) or {}).values()
            ),
        }
        checks: list[dict[str, Any]] = []
        penalty = 0
        for rule, count in counts.items():
            per_item, cap = PRACTICE_PENALTIES[rule]
            points = min(count * per_item, cap)
            penalty += points
            if count:
                checks.append(
                    {
                        "rule": rule,
                        "count": count,
                        "points": points,
                    }
                )
        checks.sort(key=lambda item: (-item["points"], item["rule"]))
        practice[report_id] = {
            "score": max(0, PRACTICE_MAX - penalty),
            "checks": checks,
        }
    return practice


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _item(**values: Any) -> dict[str, Any]:
    severity = str(values.pop("severity"))
    rule = str(values.pop("rule"))
    object_name = str(values.pop("object", "") or "")
    item: dict[str, Any] = {
        "id": f"{rule}:{object_name.casefold()}",
        "rule": rule,
        "severity": severity,
        "severity_rank": SEVERITY_RANK[severity],
        "area": values.pop("area"),
        "object": object_name,
        "kind": values.pop("kind", ""),
        "table": values.pop("table", ""),
        "name": values.pop("name", ""),
        "report_id": values.pop("report_id", ""),
        "report_name": values.pop("report_name", ""),
        "page_id": values.pop("page_id", ""),
        "page_name": values.pop("page_name", ""),
        "visual_id": values.pop("visual_id", ""),
        "visual_title": values.pop("visual_title", ""),
        "detail": values.pop("detail", ""),
        "size_bytes": int(values.pop("size_bytes", 0) or 0),
        "metrics": values.pop("metrics", {}) or {},
        "target": values.pop("target", {}) or {},
    }
    if values:
        raise TypeError(f"unknown health value: {sorted(values)}")
    return item


def _item_sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        int(item.get("severity_rank") or 0),
        str(item.get("area") or ""),
        str(item.get("rule") or ""),
        str(item.get("object") or "").casefold(),
        str(item.get("id") or ""),
    )


def _relationship_object(relationship: Mapping[str, Any]) -> str:
    return (
        f"'{relationship.get('from_table') or ''}'"
        f"[{relationship.get('from_column') or ''}] -> "
        f"'{relationship.get('to_table') or ''}'"
        f"[{relationship.get('to_column') or ''}]"
    )


def _clip(text: str, limit: int = 500) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: limit - 1] + "\u2026"
