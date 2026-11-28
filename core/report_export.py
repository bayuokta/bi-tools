"""Ekspor tab Report results mengikuti template Measure Killer.

Satu baris = satu jalur pohon report: page/report filter -> visual/page filter
-> nested visual/filter -> field. Header report diulang di setiap baris.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from .metadata_common import write_sheet
from .report_practice import report_practice_text

REPORT_RESULT_COLUMNS = [
    "Report_name",
    "Report_type",
    "Report_source",
    "Report_no_of_visuals",
    "Report_no_of_broken_visuals",
    "Report_no_of_views",
    "Report_pages",
    "Report_theme",
    "Report_best_practices_score",
    "Obj1_name",
    "Obj1_type",
    "Obj1_source",
    "Obj1_no_of_visuals",
    "Obj1_no_of_broken_visuals",
    "Obj1_no_of_views",
    "Obj2_name",
    "Obj2_type",
    "Obj2_source",
    "Obj2_is_broken",
    "Obj3_name",
    "Obj3_type",
    "Obj3_source",
    "Obj4_name",
    "Obj4_type",
    "Obj4_source",
    "Obj5_name",
    "Obj5_type",
    "Obj5_source",
    "Level13_Name",
    "Level13_Type",
    "Level13_Source",
    "Level13_Visuals",
    "Level13_Broken visuals",
    "Level13_Views",
    "Level13_Pages",
    "Level13_Theme",
    "Level13_Best practices score",
    "Level14_Name",
    "Level14_Type",
    "Level14_Source",
    "Level14_Visuals",
    "Level14_Broken visuals",
    "Level14_Views",
    "Level14_Pages",
    "Level14_Theme",
    "Level14_Best practices score",
]

MAX_OBJECTS = 7


def visual_name(visual: Mapping[str, Any]) -> str:
    """Nama visual/group gaya template (leaf berjudul memakai kutip)."""
    title = str(visual.get("visual_title") or "").strip()
    visual_type = str(visual.get("visual_type") or "visual")
    if visual.get("is_group"):
        return title or "visualGroup"
    if title.startswith("(untitled) "):
        return visual_type or "visual"
    if title:
        return f"'{title}'"
    return visual_type or "visual"


def _node(
    name: str,
    object_type: str,
    source: str,
    *,
    broken: str = "",
    visual_count: Any = "",
    broken_count: Any = "",
    views: Any = "",
) -> dict[str, Any]:
    return {
        "name": str(name or ""),
        "type": str(object_type or ""),
        "source": str(source or ""),
        "is_broken": broken,
        "visuals": visual_count,
        "broken_visuals": broken_count,
        "views": views,
    }


def _field_node(field: Mapping[str, Any]) -> dict[str, Any]:
    return _node(
        str(field.get("field") or ""),
        str(field.get("kind") or "Column"),
        str(field.get("table") or ""),
    )


def _filter_node(entry: Mapping[str, Any], source: str) -> dict[str, Any]:
    return _node(
        str(entry.get("name") or entry.get("detail") or "Filter"),
        str(entry.get("type") or "Filter"),
        source,
    )


def _row(
    report: Mapping[str, Any], slots: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    objects = list(slots)[:MAX_OBJECTS]
    row = {
        "Report_name": report["name"],
        "Report_type": report["type"],
        "Report_source": report["source"],
        "Report_no_of_visuals": report["visuals"],
        "Report_no_of_broken_visuals": report["broken"],
        "Report_no_of_views": "-",
        "Report_pages": report["pages"],
        "Report_theme": report["theme"],
        "Report_best_practices_score": report["practice"],
    }
    for index in range(MAX_OBJECTS):
        prefix = f"Obj{index + 1}" if index < 5 else f"Level{index + 8}"
        node = objects[index] if index < len(objects) else {}
        if index < 5:
            row[f"{prefix}_name"] = str(node.get("name") or "")
            row[f"{prefix}_type"] = str(node.get("type") or "")
            row[f"{prefix}_source"] = str(node.get("source") or "")
        else:
            row[f"{prefix}_Name"] = str(node.get("name") or "")
            row[f"{prefix}_Type"] = str(node.get("type") or "")
            row[f"{prefix}_Source"] = str(node.get("source") or "")
        if index < 5:
            number = index + 1
            if number == 1:
                row["Obj1_no_of_visuals"] = node.get("visuals", "")
                row["Obj1_no_of_broken_visuals"] = node.get("broken_visuals", "")
                row["Obj1_no_of_views"] = node.get("views", "")
            if number == 2:
                row["Obj2_is_broken"] = node.get("is_broken", "")
        else:
            row[f"{prefix}_Visuals"] = ""
            row[f"{prefix}_Broken visuals"] = ""
            row[f"{prefix}_Views"] = ""
            row[f"{prefix}_Pages"] = ""
            row[f"{prefix}_Theme"] = ""
            row[f"{prefix}_Best practices score"] = ""
    return row


def _visual_children(
    visuals: list[Mapping[str, Any]], parent_id: str
) -> list[Mapping[str, Any]]:
    return [
        item
        for item in visuals
        if str(item.get("parent_id") or "") == parent_id
    ]


def _emit_visual(
    visual: Mapping[str, Any],
    prefix: list[Mapping[str, Any]],
    visuals: list[Mapping[str, Any]],
    rows: list[dict[str, Any]],
    report: Mapping[str, Any],
) -> None:
    display = visual_name(visual)
    source = str(prefix[0].get("name") or "") if prefix else ""
    if visual.get("is_group"):
        node = _node(display, "visualGroup", source, broken="0")
        children = _visual_children(visuals, str(visual.get("visual_id") or ""))
        if not children:
            rows.append(_row(report, prefix + [node]))
            return
        for child in children:
            _emit_visual(child, prefix + [node], visuals, rows, report)
        return

    is_broken = "1" if visual.get("is_broken") else "0"
    node = _node(display, str(visual.get("visual_type") or "visual"), source, broken=is_broken)
    path = prefix + [node]
    fields = list(visual.get("fields") or [])
    filters = list(visual.get("filters") or [])
    if fields:
        for field in fields:
            rows.append(_row(report, path + [_field_node(field)]))
    elif not filters:
        rows.append(_row(report, path))
    for entry in filters:
        filter_node = _filter_node(entry, "")
        field_entries = list(entry.get("fields") or [])
        if not field_entries:
            rows.append(_row(report, path + [filter_node]))
            continue
        artifacts = _node("Artifacts used", "Type", "Table")
        for field in field_entries:
            field_node = _field_node(field)
            if len(path) + 2 <= 5:
                rows.append(_row(report, path + [filter_node, field_node]))
            else:
                rows.append(
                    _row(
                        report,
                        path + [filter_node, artifacts, field_node],
                    )
                )


def _report_header(
    result: Any,
    report: Mapping[str, Any],
    detail: Mapping[str, Any] | None,
    practice: Mapping[str, Any] | None,
) -> dict[str, Any]:
    name = str(report.get("report_name") or report.get("name") or "")
    local = str(getattr(result, "method", "") or "").casefold() == "local"
    report_type = "Apps" if "[app]" in name.casefold() else (
        "Local report" if local else "Service report"
    )
    detail = detail or {}
    visuals = int(
        detail.get("container_count")
        or report.get("container_count")
        or report.get("visual_count")
        or 0
    )
    return {
        "name": name,
        "type": report_type,
        "source": "File" if local else "Service",
        "visuals": visuals,
        "broken": int(detail.get("broken_visuals") or 0),
        "pages": int(detail.get("page_count") or report.get("page_count") or 0),
        "theme": str(report.get("theme") or ""),
        "practice": report_practice_text(practice),
    }


def build_report_rows(
    result: Any,
    details: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Susun 28 kolom template untuk semua report di ``AnalysisResult``."""
    details = details or {}
    rows: list[dict[str, Any]] = []
    for report in getattr(result, "reports", []) or []:
        if not isinstance(report, Mapping):
            continue
        report_id = str(report.get("report_id") or report.get("id") or "")
        detail = details.get(report_id) or {}
        practice = {
            "available": bool(report.get("practice_label")),
            "score": report.get("practice_score"),
            "label": str(report.get("practice_label") or ""),
        }
        header = _report_header(result, report, detail, practice)
        pages = list(detail.get("pages") or [])
        if not pages:
            rows.append(_row(header, []))
            continue
        for page in pages:
            page_node = _node(
                str(page.get("page_name") or page.get("page_id") or ""),
                "Page",
                header["name"],
                visual_count=int(page.get("container_count") or page.get("visual_count") or 0),
                broken_count=int(page.get("broken_visuals") or 0),
                views="-",
            )
            visuals = list(page.get("visuals") or [])
            roots = _visual_children(visuals, "")
            for visual in roots:
                _emit_visual(visual, [page_node], visuals, rows, header)
            page_filters = list(page.get("page_filters") or [])
            for entry in page_filters:
                filter_node = _filter_node(entry, str(page.get("page_name") or ""))
                for field in entry.get("fields") or []:
                    rows.append(_row(header, [page_node, filter_node, _field_node(field)]))
            if not roots and not page_filters:
                rows.append(_row(header, [page_node]))

        for entry in detail.get("report_filters") or []:
            filter_node = _filter_node(entry, header["name"])
            for field in entry.get("fields") or []:
                rows.append(_row(header, [filter_node, _field_node(field)]))

        for bookmark in detail.get("bookmarks") or []:
            bookmark_node = _node(
                str(bookmark.get("name") or "Bookmark"), "Bookmark", ""
            )
            for attribute in bookmark.get("attributes") or []:
                rows.append(
                    _row(
                        header,
                        [
                            bookmark_node,
                            _node(
                                str(attribute.get("name") or ""),
                                str(attribute.get("value") or ""),
                                "",
                            ),
                        ],
                    )
                )
    return rows


def write_report_export(
    result: Any,
    details: Mapping[str, Mapping[str, Any]] | None,
    path: Path | str,
) -> Path:
    """Tulis satu sheet Report results dengan 28 kolom template."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        build_report_rows(result, details), columns=REPORT_RESULT_COLUMNS
    )
    with pd.ExcelWriter(target, engine="openpyxl") as writer:
        write_sheet(writer, frame, "Reports")
    return target
