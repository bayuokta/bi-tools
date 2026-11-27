"""
Helper bersama untuk ekstraksi metadata: pemakaian report (PBIR di dalam .pbix),
graf dependency DAX, dan penulisan sheet Excel.

Tidak bergantung pada XMLA, jadi dapat dipakai ulang oleh script lain.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------
def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def split_outside_quotes(text: str, sep: str = ",") -> list[str]:
    """Pisah argumen tanpa memecah string di dalam tanda kutip."""
    parts: list[str] = []
    buffer: list[str] = []
    in_quote = False
    for char in text:
        if char == '"':
            in_quote = not in_quote
            buffer.append(char)
        elif char == sep and not in_quote:
            parts.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    parts.append("".join(buffer))
    return [part.strip() for part in parts if part.strip()]


# ---------------------------------------------------------------------------
# Report usage (read-only, PBIR)
# ---------------------------------------------------------------------------
# Aggregation.Function pada PBIR (semanticQuery schema).
# 0=Sum, 1=Average, 2=Distinct count, 3=Min, 4=Max, 5=Count,
# 6=Median, 7=StandardDeviation, 8=Variance.
QUERY_AGGREGATE_FUNCTION = {
    0: "Sum",
    1: "Average",
    2: "Distinct count",
    3: "Min",
    4: "Max",
    5: "Count",
    6: "Median",
    7: "Standard deviation",
    8: "Variance",
}

# queryRef agregasi berbentuk "Min(Tabel.Kolom)"; jangan dipecah sebagai tabel/kolom.
AGGREGATED_QUERY_REF = re.compile(r"^[A-Za-z][A-Za-z0-9]*\(")


def parse_report_field(field: dict[str, Any]) -> tuple[str, str, str]:
    """Kembalikan kind, tabel, dan nama field proyeksi PBIR.

    ``Aggregation`` adalah agregasi level visual (implicit measure): kolom
    dasarnya tetap objek model, bukan objek baru.
    """
    if "Measure" in field:
        kind, node = "Measure", field["Measure"]
    elif "Column" in field:
        kind, node = "Column", field["Column"]
    elif "Aggregation" in field:
        kind, node = "Aggregation", field["Aggregation"]
        column = (node.get("Expression") or {}).get("Column") or {}
        source = (column.get("Expression") or {}).get("SourceRef") or {}
        table = source.get("Entity", "")
        name = column.get("Property") or node.get("Property", "")
        return kind, table, name
    else:
        return "Other", "", ""
    source = (node.get("Expression") or {}).get("SourceRef") or {}
    return kind, source.get("Entity", ""), node.get("Property", "")


def report_aggregation_label(field: dict[str, Any]) -> str:
    """Nama fungsi agregasi visual; kosong bila bukan agregasi atau tak dikenal."""
    node = field.get("Aggregation") or {}
    try:
        function = int(node.get("Function"))
    except (TypeError, ValueError):
        return ""
    return QUERY_AGGREGATE_FUNCTION.get(function, "")


def scan_report_usage(
    report_def: Path | None,
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]]]:
    """Kumpulkan measure/kolom yang dipakai langsung oleh visual."""
    measures: dict[str, dict[str, Any]] = {}
    columns: dict[tuple[str, str], dict[str, Any]] = {}

    if report_def is None:
        return measures, columns
    pages_file = report_def / "pages" / "pages.json"
    if not pages_file.exists():
        return measures, columns

    pages_meta = read_json(pages_file)
    for order, page_id in enumerate(pages_meta.get("pageOrder", []), start=1):
        page_dir = report_def / "pages" / page_id
        page_json = read_json(page_dir / "page.json")
        page_name = page_json.get("displayName") or page_id
        visuals_dir = page_dir / "visuals"
        if not visuals_dir.exists():
            continue
        for visual_dir in sorted(path for path in visuals_dir.iterdir() if path.is_dir()):
            visual_json = read_json(visual_dir / "visual.json")
            visual = visual_json.get("visual") or {}
            query_state = (visual.get("query") or {}).get("queryState") or {}
            for role_content in query_state.values():
                for projection in (role_content or {}).get("projections") or []:
                    field = projection.get("field") or {}
                    kind, table, name = parse_report_field(field)
                    if not name:
                        query_ref = projection.get("queryRef") or ""
                        if "." in query_ref and not AGGREGATED_QUERY_REF.match(query_ref):
                            table, name = query_ref.split(".", 1)
                    if not name:
                        continue
                    if kind == "Measure":
                        entry = measures.setdefault(name, {"pages": set(), "visuals": set()})
                    elif kind in {"Column", "Aggregation"}:
                        entry = columns.setdefault((table, name), {"pages": set(), "visuals": set()})
                        aggregation = report_aggregation_label(field)
                        if aggregation:
                            entry.setdefault("aggregations", set()).add(aggregation)
                    else:
                        continue
                    entry["pages"].add((order, page_name))
                    entry["visuals"].add((page_id, visual_dir.name))

    return measures, columns


def fmt_pages(pages: set[tuple[int, str]]) -> str:
    return " | ".join(f"{order}. {name}" for order, name in sorted(pages))


# ---------------------------------------------------------------------------
# DAX dependency graph
# ---------------------------------------------------------------------------
_DEPENDENCY_DEPTH = re.compile(r"\(depth\s+(\d+)\)")


def reference_depth(detail: str) -> int:
    """Baca depth referensi dari teks detail (fallback snapshot lama)."""
    match = _DEPENDENCY_DEPTH.search(str(detail or ""))
    if not match:
        return 1
    try:
        return max(1, int(match.group(1)))
    except (TypeError, ValueError):
        return 1


def strip_dax_literals(code: str) -> str:
    out: list[str] = []
    i = 0
    n = len(code)
    while i < n:
        char = code[i]
        if char == '"':
            i += 1
            while i < n:
                if code[i] == '"':
                    if i + 1 < n and code[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if char == "/" and i + 1 < n and code[i + 1] == "/":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if char == "-" and i + 1 < n and code[i + 1] == "-":
            while i < n and code[i] != "\n":
                i += 1
            continue
        if char == "/" and i + 1 < n and code[i + 1] == "*":
            i += 2
            while i + 1 < n and not (code[i] == "*" and code[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def find_dax_refs(code: str, table_names: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    cleaned = strip_dax_literals(code)
    spans: list[tuple[int, int, str, str]] = []
    for table in sorted(table_names, key=len, reverse=True):
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            pattern = rf"(?:'{re.escape(table)}'|{re.escape(table)})\s*\[\s*([^\]]+?)\s*\]"
        else:
            quoted = re.escape("'" + table.replace("'", "''") + "'")
            pattern = rf"{quoted}\s*\[\s*([^\]]+?)\s*\]"
        for match in re.finditer(pattern, cleaned):
            spans.append((match.start(), match.end(), table, match.group(1).strip()))

    masked = list(cleaned)
    for start, end, _, _ in spans:
        for index in range(start, end):
            masked[index] = " "
    measure_names = [match.group(1).strip() for match in re.finditer(r"\[([^\]]+)\]", "".join(masked))]

    columns: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for _, _, table, column in spans:
        key = (table, column)
        if key not in seen:
            seen.add(key)
            columns.append(key)
    return columns, measure_names


def build_dependencies(
    measures: list[dict[str, Any]],
    columns: list[dict[str, Any]],
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    table_names = [table["table"] for table in tables]
    measure_set = {measure["measure"] for measure in measures}
    measure_map = {
        (str(measure["table"]).casefold(), str(measure["measure"]).casefold()): str(
            measure["measure"]
        )
        for measure in measures
    }
    column_set = {(column["table"], column["column"]) for column in columns}

    edges: dict[str, list[tuple[str, str, str]]] = {}
    for measure in measures:
        column_refs, measure_refs = find_dax_refs(measure["expression"], table_names)
        refs: list[tuple[str, str, str]] = []
        for table, column in column_refs:
            if (table, column) not in column_set:
                # Referensi berkualifikasi tabel yang menunjuk measure
                # (mis. 'Pages'[Max Pages]) bukan kolom.
                target = measure_map.get((table.casefold(), column.casefold()))
                if target:
                    refs.append(("Measure", "", target))
                    continue
            refs.append(("Column", table, column))
        refs += [("Measure", "", name) for name in measure_refs]
        edges[measure["measure"]] = refs

    rows: list[dict[str, Any]] = []
    for measure in measures:
        origin = measure["measure"]
        depth: dict[tuple[str, str, str], int] = {}
        frontier = [(origin, 0)]
        visited = {origin}
        while frontier:
            current, level = frontier.pop(0)
            for ref in edges.get(current, []):
                if ref not in depth or level + 1 < depth[ref]:
                    depth[ref] = level + 1
                if ref[0] == "Measure" and ref[2] not in visited:
                    visited.add(ref[2])
                    frontier.append((ref[2], level + 1))

        for (kind, table, name), level in sorted(depth.items(), key=lambda item: (item[1], item[0][0], item[0][2])):
            if kind == "Measure":
                resolved = name in measure_set
                target_table = next(
                    (measure["table"] for measure in measures if measure["measure"] == name), ""
                )
            else:
                resolved = (table, name) in column_set
                target_table = table
            rows.append(
                {
                    "measure": origin,
                    "measure_table": measure["table"],
                    "referenced_type": kind,
                    "referenced_table": target_table,
                    "referenced_object": name,
                    "depth": level,
                    "resolved_in_model": resolved,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def write_sheet(writer, df: pd.DataFrame, sheet: str, width_map: dict[str, int] | None = None) -> None:
    df.to_excel(writer, sheet_name=sheet, index=False)
    ws = writer.sheets[sheet]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 28

    for idx, column in enumerate(df.columns, start=1):
        cell = ws.cell(row=1, column=idx)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER

        width = (width_map or {}).get(column)
        if width is None:
            sample = df[column].astype(str).head(200)
            longest = max([len(column)] + [min(len(value), 60) for value in sample]) if len(df) else len(column)
            width = min(max(longest + 2, 10), 70)
        ws.column_dimensions[get_column_letter(idx)].width = width

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(df.columns)):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=False)
            cell.border = BORDER
