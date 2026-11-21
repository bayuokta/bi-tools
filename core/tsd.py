"""Generate dokumen TSD (Technical Specification Design) dari workbook metadata.

Template berasal dari repo ``..\\template-tsd`` dan disalin apa adanya ke
``templates\\tsd.template.html``. Modul ini hanya membaca workbook lalu menyusun
konteks Jinja; semua transformasi data berada di sini agar ``cli`` dan ``app``
tetap tipis.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

import pandas as pd
from jinja2 import BaseLoader, ChainableUndefined, Environment
from markupsafe import Markup, escape

from .errors import ExtractionError
from .m_lineage import build_lineage
from .pbix import ROOT
from .pbi_capture.assets import (
    DECORATIVE_VISUAL_TYPES,
    ScreenshotSet,
    data_uri,
)
from .report import OUT_FILE

if TYPE_CHECKING:
    from .pbi_capture.runner import CaptureOptions

Log = Callable[[str], None]

TEMPLATE_PATH = ROOT / "templates" / "tsd.template.html"
MODEL_WORKBOOK_NAME = "Semantic_Model_Metadata.xlsx"
OUT_PREFIX = "TSD_"
SCREENSHOT_ASSET_DIR = "TSD_assets"

REPORT_SHEETS = (
    "01_Pages",
    "02_Bookmarks",
    "03_Interactions",
    "04_Visual_Fields",
    "06_Sync_Slicers",
    "07_Filters",
    "08_Visual_Summary",
)

MODEL_SHEETS = (
    "02_Tables",
    "03_Columns",
    "04_Measures",
    "05_Partitions",
    "06_Expressions_Params",
    "07_Relationships",
    "08_Roles_RLS",
    "15_Data_Sources",
    "18_Hierarchies",
)

INTERACTION_LABELS = {
    "DataFilter": "Filter",
    "NoFilter": "None",
    "HighlightFilter": "Highlight",
}

# Tipe field pada 04_Visual_Fields -> label yang dipakai tabel TSD.
FIELD_KIND_LABELS = {
    "Column": "Column",
    "Measure": "Measure",
    "Aggregation": "Column",
    "HierarchyLevel": "Hierarchy Level",
    "VisualCalculation": "Visual Calculation",
    "NativeVisualCalculation": "Visual Calculation",
}

# Nama fungsi untuk Query Ref saat kolom memakai agregasi eksplisit.
AGGREGATION_QUERY_NAMES = {
    "Sum": "Sum",
    "Average": "Average",
    "Distinct count": "Count",
    "Min": "Min",
    "Max": "Max",
    "Count": "CountNonNull",
    "Median": "Median",
    "Standard deviation": "StandardDeviation",
    "Variance": "Variance",
}

FILE_CONNECTORS = (
    "excel",
    "csv",
    "tsv",
    "txt",
    "text",
    "file",
    "folder",
    "sharepoint",
    "pdf",
    "json",
    "access",
    "xml",
    "parquet",
    "google sheet",
    "azure storage",
)

LIVE_CONNECTORS = (
    "dataflow",
    "dataset",
    "powerplatform",
    "power bi",
    "usage metric",
)

# Query yang dibuat di dalam Power BI (Enter Data / M murni) tidak punya sumber
# eksternal: masuk bucket ``mquery`` (section 2.2.1.4 M Language Queries).
INLINE_CONNECTORS = (
    "inline",
    "enter data",
)

# Penanda M untuk Enter Data / tabel inline. Diperiksa lebih dulu karena Enter
# Data membungkus tabel dengan Json.Document(Binary.Decompress(Binary.FromText)).
INLINE_PATTERNS_EARLY = (
    "#table(",
    "Binary.FromText(",
)
INLINE_PATTERNS_LATE = (
    "Table.FromRows(",
    "Table.FromValue(",
    "Table.FromList(",
    "Table.FromRecords(",
)

# Partisi yang bukan tabel biasa: calculated table (2.2.3) dan calculation
# group (2.2.11), jadi tidak dimasukkan ke bucket 2.2.1.x.
NON_TABLE_PARTITIONS = frozenset({"calculated", "calculationGroup"})

MONTHS_ID = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)

# Hanya blok/komentar Jinja yang dicek. ``{{`` bisa muncul sah di dalam M
# (mis. ``Table.RenameColumns(..., {{"a", "A"}})``), jadi bukan penanda sisa token.
LEFTOVER_TOKEN = re.compile(r"\{%|\{#")
REQUIRED_ANCHORS = (
    "doc-version",
    "toc",
    "overview",
    "solution-design",
    "web-layout",
    "serving",
)

TODO_MARKER = 'class="todo"'


def _silent(_message: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Normalisasi nilai workbook
# ---------------------------------------------------------------------------
def _blank(value: Any) -> bool:
    """True untuk None/NaN/NaT/teks kosong tanpa mengganggu list dan dict."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, float) and math.isnan(value):
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _text(value: Any) -> str:
    """Teks bersih; newline di dalam nilai dipertahankan (untuk DAX/M)."""
    if _blank(value):
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    stripped = text.strip()
    if stripped.lower() in {"nan", "nat", "none", "<na>"}:
        return ""
    return stripped


def _flag(value: Any) -> bool | None:
    """Boolean tiga nilai: True/False/None (tidak diketahui)."""
    if _blank(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "y"}:
        return True
    if text in {"false", "no", "0", "n"}:
        return False
    return None


def _yes_no(value: Any) -> str:
    flag = _flag(value)
    if flag is None:
        return ""
    return "Yes" if flag else "No"


def _number_text(value: Any) -> str:
    if _blank(value):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    return str(int(number)) if number.is_integer() else str(number)


def _row_text(row: Mapping[str, Any], key: str) -> str:
    return _text(row.get(key, ""))


# ---------------------------------------------------------------------------
# Baca workbook
# ---------------------------------------------------------------------------
def _read_sheets(path: Path, sheets: tuple[str, ...], log: Log) -> dict[str, pd.DataFrame]:
    try:
        with pd.ExcelFile(path) as book:
            names = set(book.sheet_names)
    except Exception as exc:  # pandas melempar beberapa tipe berbeda
        raise ExtractionError(f"Workbook tidak bisa dibaca: {path} ({exc}).") from exc
    missing = [name for name in sheets if name not in names]
    for name in missing:
        log(f"WARNING: sheet {name} tidak ada di {path.name}; bagian TSD terkait kosong.")
    present = [name for name in sheets if name in names]
    if not present:
        return {}
    frames = pd.read_excel(path, sheet_name=present)
    if isinstance(frames, pd.DataFrame):
        return {present[0]: frames}
    return {str(name): frame for name, frame in frames.items()}


def _sort_frame(frame: pd.DataFrame | None, column: str) -> pd.DataFrame:
    if frame is None or frame.empty or column not in frame.columns:
        return pd.DataFrame() if frame is None else frame
    result = frame.copy()
    result["_sort_key"] = pd.to_numeric(result[column], errors="coerce")
    result = result.sort_values("_sort_key", kind="stable", na_position="last")
    return result.drop(columns="_sort_key")


def _rows(frame: pd.DataFrame | None) -> list[Mapping[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [row for _, row in frame.iterrows()]


def _match(frame: pd.DataFrame | None, **columns: str) -> list[Mapping[str, Any]]:
    """Baris dengan kolom bernilai sama (perbandingan teks), urutan file dipertahankan."""
    result: list[Mapping[str, Any]] = []
    for row in _rows(frame):
        if all(_row_text(row, key) == value for key, value in columns.items()):
            result.append(row)
    return result


# ---------------------------------------------------------------------------
# Bagian report
# ---------------------------------------------------------------------------
def _filters(
    frame: pd.DataFrame | None,
    scope: str,
    *,
    page_id: str | None = None,
    visual_id: str | None = None,
) -> list[dict[str, Any]]:
    conditions: dict[str, str] = {"scope": scope}
    if page_id is not None:
        conditions["page_id"] = page_id
    if visual_id is not None:
        conditions["visual_id"] = visual_id
    result: list[dict[str, Any]] = []
    for row in _match(frame, **conditions):
        # Kartu filter tanpa definisi (tanpa Where) tidak memfilter apa pun,
        # jadi tidak ditampilkan sebagai filter. Workbook lama tanpa kolom
        # has_filter_definition tetap dirender apa adanya.
        if _flag(row.get("has_filter_definition")) is False:
            continue
        result.append(
            {
                "field": _row_text(row, "field"),
                "table": _row_text(row, "table"),
                "filter_type": _row_text(row, "filter_type"),
                "values": _row_text(row, "values"),
                "hidden": _yes_no(row.get("hidden_in_view_mode")),
                "locked": _yes_no(row.get("locked_in_view_mode")),
            }
        )
    return result


def _split_fields(value: Any) -> list[str]:
    text = _text(value)
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def _model_expressions(
    model_frames: Mapping[str, pd.DataFrame],
) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], str]]:
    """Peta (tabel, nama) -> DAX untuk measure dan calculated column."""
    measures: dict[tuple[str, str], str] = {}
    for row in _rows(model_frames.get("04_Measures")):
        table = _row_text(row, "table")
        name = _row_text(row, "measure")
        if table and name:
            measures[(table, name)] = _text(row.get("expression"))

    columns: dict[tuple[str, str], str] = {}
    for row in _rows(model_frames.get("03_Columns")):
        if not _flag(row.get("is_calculated")):
            continue
        table = _row_text(row, "table")
        name = _row_text(row, "column")
        if table and name:
            columns[(table, name)] = _text(row.get("expression"))
    return measures, columns


def _visual_field_details(
    fields_frame: pd.DataFrame | None,
    visual_id: str,
    measures: Mapping[tuple[str, str], str],
    columns: Mapping[tuple[str, str], str],
) -> list[dict[str, Any]]:
    """Rincian field visual untuk tabel Column/Measure/Visual Calculation."""
    details: list[dict[str, Any]] = []
    for row in _match(fields_frame, visual_id=visual_id):
        kind = _row_text(row, "field_kind")
        table = _row_text(row, "table")
        field = _row_text(row, "field")
        display_name = _row_text(row, "display_name") or field
        expression = _text(row.get("expression"))
        if not expression:
            if kind == "Measure":
                expression = measures.get((table, field), "")
            elif kind == "Column":
                expression = columns.get((table, field), "")
        query_ref = _row_text(row, "query_ref")
        aggregation = _row_text(row, "aggregation")
        if aggregation and table and field:
            function = AGGREGATION_QUERY_NAMES.get(
                aggregation, aggregation.replace(" ", "")
            )
            query_ref = f"{function}({table}.{field})"
        if kind in {"VisualCalculation", "NativeVisualCalculation"} and query_ref in {
            "",
            "select",
        }:
            query_ref = field or display_name
        details.append(
            {
                "table": table,
                "field": field,
                "type": FIELD_KIND_LABELS.get(kind, kind),
                "display_name": display_name,
                "expression": expression,
                "aggregation": aggregation,
                "query_ref": query_ref,
            }
        )
    return details


def _interaction_text(frame: pd.DataFrame | None, visual_id: str) -> str:
    if not visual_id:
        return ""
    labels: list[str] = []
    for row in _match(frame, source_visual_id=visual_id):
        raw = _row_text(row, "interaction_type")
        if not raw:
            continue
        label = INTERACTION_LABELS.get(raw, raw)
        if label not in labels:
            labels.append(label)
    if len(labels) > 1 and "None" in labels:
        labels.remove("None")  # "None" hanya bermakna bila tidak ada interaksi lain
    return ", ".join(labels)


def _interaction_rows(
    frame: pd.DataFrame | None,
    page_id: str,
    visual_id: str,
) -> list[dict[str, str]]:
    """Interaksi keluar visual (source) untuk tabel Source/Target/Type."""
    if not visual_id:
        return []
    rows: list[dict[str, str]] = []
    for row in _match(frame, source_visual_id=visual_id):
        row_page = _row_text(row, "page_id")
        if page_id and row_page and row_page != page_id:
            continue
        rows.append(
            {
                "source": _row_text(row, "source_visual_name")
                or _row_text(row, "source_visual_id"),
                "target": _row_text(row, "target_visual_name")
                or _row_text(row, "target_visual_id"),
                "type": _row_text(row, "interaction_type"),
            }
        )
    return rows


def _visuals(
    visuals_frame: pd.DataFrame | None,
    fields_frame: pd.DataFrame | None,
    interactions: pd.DataFrame | None,
    filters: pd.DataFrame | None,
    page_id: str,
    measures: Mapping[tuple[str, str], str],
    columns: Mapping[tuple[str, str], str],
    include_decorative: bool = False,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _match(visuals_frame, page_id=page_id):
        visual_id = _row_text(row, "visual_id")
        visual_type = _row_text(row, "visual_type")
        if not include_decorative and visual_type in DECORATIVE_VISUAL_TYPES:
            continue
        result.append(
            {
                "visual_id": visual_id,
                "name": _row_text(row, "visual_name") or visual_id,
                "type": visual_type,
                "is_hidden": _flag(row.get("is_hidden", "")),
                "screenshot": "",
                "fields": _split_fields(row.get("fields", "")),
                "field_details": _visual_field_details(
                    fields_frame, visual_id, measures, columns
                )
                if visual_id
                else [],
                "tooltip": "",
                "interaction": _interaction_text(interactions, visual_id),
                "interactions": _interaction_rows(interactions, page_id, visual_id)
                if visual_id
                else [],
                "filters": _filters(filters, "Visual", visual_id=visual_id)
                if visual_id
                else [],
            }
        )
    return result


def _pages(
    frames: Mapping[str, pd.DataFrame],
    model_frames: Mapping[str, pd.DataFrame] | None = None,
    include_decorative: bool = False,
) -> list[dict[str, Any]]:
    pages_frame = _sort_frame(frames.get("01_Pages"), "page_order")
    visuals_frame = frames.get("08_Visual_Summary")
    fields_frame = frames.get("04_Visual_Fields")
    interactions = frames.get("03_Interactions")
    filters = frames.get("07_Filters")
    measures, columns = _model_expressions(model_frames or {})
    result: list[dict[str, Any]] = []
    for row in _rows(pages_frame):
        page_id = _row_text(row, "page_id")
        result.append(
            {
                "page_id": page_id,
                "title": _row_text(row, "page_name") or page_id,
                "is_hidden": _flag(row.get("is_hidden", "")),
                "screenshot": "",
                "workspace": "",
                "folder": "",
                "report_name": "",
                "sharepoint": "",
                "page_filters": _filters(filters, "Page", page_id=page_id)
                if page_id
                else [],
                "visuals": _visuals(
                    visuals_frame,
                    fields_frame,
                    interactions,
                    filters,
                    page_id,
                    measures,
                    columns,
                    include_decorative=include_decorative,
                )
                if page_id
                else [],
            }
        )
    return result


def _report_page_size(
    report_workbook: Path, log: Log = _silent
) -> tuple[int, int]:
    """Ukuran halaman terbesar dari ``01_Pages`` untuk viewport capture.

    Viewport yang sama dengan ukuran halaman menghindari letterbox putih pada
    screenshot page/visual. Kembalikan ``(0, 0)`` bila tidak bisa dibaca.
    """
    try:
        frames = _read_sheets(Path(report_workbook), ("01_Pages",), log)
    except ExtractionError:
        return 0, 0
    frame = frames.get("01_Pages")
    if frame is None or frame.empty:
        return 0, 0
    if "width" not in frame.columns or "height" not in frame.columns:
        return 0, 0
    widths = pd.to_numeric(frame["width"], errors="coerce").dropna()
    heights = pd.to_numeric(frame["height"], errors="coerce").dropna()
    if widths.empty or heights.empty:
        return 0, 0
    width = int(round(float(widths.max())))
    height = int(round(float(heights.max())))
    if width <= 0 or height <= 0:
        return 0, 0
    return width, height


def _attach_screenshots(
    pages: list[dict[str, Any]],
    screenshots: ScreenshotSet | None,
    log: Log = _silent,
) -> tuple[dict[str, int], list[dict[str, str]]]:
    """Tempel screenshot ke page/visual berbasis page_id/visual_id.

    ID yang tidak ada di cache dibiarkan kosong supaya template memakai
    placeholder (halaman yang hanya ada di file .pbix, visual tersembunyi).
    Juga menyusun daftar screenshot mobile layout untuk 2.2.7.2.
    """
    stats = {
        "pages": 0,
        "visuals": 0,
        "mobile": 0,
        "missing_pages": 0,
        "missing_visuals": 0,
    }
    mobile_shots: list[dict[str, str]] = []
    if screenshots is None:
        return stats, mobile_shots

    encoded: dict[str, str] = {}

    def src(path: Path) -> str:
        key = str(path)
        if key not in encoded:
            encoded[key] = data_uri(path)
        return encoded[key]

    for ordinal, page in enumerate(pages, start=1):
        page_id = _row_text(page, "page_id")
        title = _row_text(page, "title")
        page_path = screenshots.page(page_id, title)
        if page_path:
            page["screenshot"] = src(page_path)
            stats["pages"] += 1
        else:
            stats["missing_pages"] += 1
        mobile_path = screenshots.mobile_page(page_id, title)
        if mobile_path:
            mobile_shots.append(
                {
                    "src": src(mobile_path),
                    "caption": f"{ordinal:02d}. {title or page_id}",
                }
            )
            stats["mobile"] += 1
        for visual in page.get("visuals", []):
            visual_path = screenshots.visual(
                page_id,
                _row_text(visual, "visual_id"),
                _row_text(visual, "name"),
                title,
            )
            if visual_path:
                visual["screenshot"] = src(visual_path)
                stats["visuals"] += 1
            else:
                stats["missing_visuals"] += 1

    log(
        f"Screenshot       : {stats['pages']}/{len(pages)} page, "
        f"{stats['visuals']} visual, {stats['mobile']} mobile; "
        f"{stats['missing_pages']} page & {stats['missing_visuals']} visual "
        "tanpa gambar (placeholder)."
    )
    return stats, mobile_shots


def _bookmarks(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _rows(frame):
        name = _row_text(row, "bookmark_name") or _row_text(row, "display_name")
        if not name:
            continue
        parts: list[str] = []
        page_name = _row_text(row, "page_name")
        if page_name:
            parts.append(f"Page: {page_name}")
        targets = _row_text(row, "target_visuals")
        if targets:
            parts.append(f"Target visuals: {targets}")
        for key, label in (
            ("apply_only_to_target_visuals", "Apply only to target visuals"),
            ("suppress_active_section", "Suppress active section"),
            ("suppress_data", "Suppress data"),
            ("suppress_display", "Suppress display"),
        ):
            if _flag(row.get(key, "")):
                parts.append(label)
        result.append(
            {
                "name": name,
                "configuration": "; ".join(parts),
                "selection": "",
            }
        )
    return result


def _sync_slicers(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    labels: dict[tuple[str, str], str] = {}
    for row in _rows(frame):
        page_name = _row_text(row, "page_name")
        order = _number_text(row.get("page_order", ""))
        group = _row_text(row, "sync_group")
        table = _row_text(row, "table")
        column = _row_text(row, "column")
        slicer = f"{table}[{column}]" if table and column else ""
        if not any((page_name, order, group, slicer, _row_text(row, "group_pages"))):
            continue  # baris NaN saat tidak ada sync slicer
        key = (order, page_name)
        labels.setdefault(key, f"{order}. {page_name}" if order else page_name)
        if not (slicer or group):
            continue
        grouped.setdefault(key, []).append(
            {
                "slicer": slicer or _row_text(row, "slicer_name"),
                "pages": _row_text(row, "group_pages"),
                "group": group,
            }
        )
    return [
        {"label": labels[key], "items": items}
        for key, items in grouped.items()
        if items
    ]


# ---------------------------------------------------------------------------
# Bagian model
# ---------------------------------------------------------------------------
def _relationships(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _rows(frame):
        from_table = _row_text(row, "from_table")
        from_column = _row_text(row, "from_column")
        to_table = _row_text(row, "to_table")
        to_column = _row_text(row, "to_column")
        if not (from_table or to_table):
            continue
        from_card = _row_text(row, "from_cardinality")
        to_card = _row_text(row, "to_cardinality")
        remarks: list[str] = []
        cross = _row_text(row, "cross_filtering")
        if cross:
            remarks.append(f"Cross filter: {cross}")
        security = _row_text(row, "security_filtering")
        if security and security != cross:
            remarks.append(f"Security filter: {security}")
        result.append(
            {
                "relationship": (
                    f"{from_table}[{from_column}] → {to_table}[{to_column}]"
                ),
                "type": f"{from_card}-to-{to_card}"
                if from_card or to_card
                else "",
                "active": _yes_no(row.get("is_active", "")).replace("Yes", "Active").replace(
                    "No", "Inactive"
                ),
                "remarks": "; ".join(remarks),
            }
        )
    return result


def _measures(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _rows(frame):
        name = _row_text(row, "measure")
        if not name:
            continue
        result.append(
            {
                "table": _row_text(row, "table"),
                "name": name,
                "formula": _text(row.get("expression", "")),
                "purpose": _row_text(row, "description"),
            }
        )
    return result


def _calculated_columns(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _rows(frame):
        if not _flag(row.get("is_calculated", "")):
            continue
        column = _row_text(row, "column")
        if not column:
            continue
        result.append(
            {
                "table": _row_text(row, "table"),
                "column": column,
                "dax": _text(row.get("expression", "")),
                "purpose": _row_text(row, "description"),
            }
        )
    return result


def _compact_expression(value: Any) -> str:
    """Padatkan ekspresi multi-baris tanpa mengubah isi string literal."""
    text = _text(value)
    if not text:
        return ""
    result: list[str] = []
    quote = ""
    pending_space = False
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            result.append(char)
            if char == quote:
                if index + 1 < len(text) and text[index + 1] == quote:
                    result.append(text[index + 1])
                    index += 2
                    continue
                quote = ""
            index += 1
            continue
        if char in {'"', "'"}:
            if pending_space and result:
                result.append(" ")
            pending_space = False
            quote = char
            result.append(char)
            index += 1
            continue
        if char.isspace():
            pending_space = True
            index += 1
            continue
        if pending_space and result:
            result.append(" ")
        pending_space = False
        result.append(char)
        index += 1
    return "".join(result).strip()


def _m_column_logic(
    frame: pd.DataFrame | None, table: str
) -> dict[str, str]:
    """Logika M per kolom hasil Table.AddColumn/Duplicate/Combine/Group."""
    expression = ""
    for row in _match(frame, table=table):
        if _row_text(row, "source_type") not in {"m", "policyRange"}:
            continue
        candidate = _text(row.get("source", ""))
        if len(candidate) > len(expression):
            expression = candidate
    if not expression:
        return {}
    try:
        lineage = build_lineage(expression)
    except Exception:  # dokumen TSD tidak boleh gagal karena parser M
        return {}
    return {
        name: column.logic
        for name, column in lineage.columns.items()
        if column.logic
    }


def _columns_data(
    frame: pd.DataFrame | None,
    table: str,
    m_logic: Mapping[str, str] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    logic_map = m_logic or {}
    columns: list[str] = []
    details: list[dict[str, Any]] = []
    for row in _match(frame, table=table):
        column = _row_text(row, "column")
        if not column:
            continue
        columns.append(column)
        calculated = bool(_flag(row.get("is_calculated", "")))
        logic = (
            _text(row.get("expression", ""))
            if calculated
            else logic_map.get(column, "")
        )
        details.append(
            {
                "source_column": _row_text(row, "source_column") or column,
                "column_name": column,
                "data_type": _row_text(row, "data_type"),
                "custom_logic": _compact_expression(logic),
                "is_hidden": _flag(row.get("is_hidden", "")),
            }
        )
    return columns, details


def _partition_expression(frame: pd.DataFrame | None, table: str) -> str:
    """Ekspresi partisi terpanjang milik tabel.

    Kolom ``source`` berisi M/DAX partisi; ``source_expression`` hanya ekspresi
    refresh policy, jadi dipakai sebagai cadangan.
    """
    longest = ""
    for row in _match(frame, table=table):
        expression = _text(row.get("source", ""))
        if len(expression) > len(longest):
            longest = expression
    if longest:
        return longest
    for row in _match(frame, table=table):
        expression = _text(row.get("source_expression", ""))
        if len(expression) > len(longest):
            longest = expression
    return longest


def _incremental_text(frame: pd.DataFrame | None, table: str) -> str:
    for row in _match(frame, table=table):
        granularity = _row_text(row, "incremental_granularity")
        periods = _number_text(row.get("incremental_periods", ""))
        if granularity:
            return f"Yes — {periods} {granularity}".strip()
        if periods:
            return f"Yes — {periods}"
    return "No"


def _calculated_tables(
    tables_frame: pd.DataFrame | None,
    partitions: pd.DataFrame | None,
    columns: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _rows(tables_frame):
        table = _row_text(row, "table")
        if not table:
            continue
        parts = [
            part
            for part in _match(partitions, table=table)
            if _row_text(part, "source_type") == "calculated"
        ]
        if not parts:
            continue
        dax = ""
        for part in parts:
            expression = _text(part.get("source", "")) or _text(
                part.get("source_expression", "")
            )
            if len(expression) > len(dax):
                dax = expression
        column_names, details = _columns_data(columns, table)
        result.append(
            {
                "table_name": table,
                "description": _row_text(row, "description"),
                "dax": dax,
                "columns": column_names,
                "column_details": details,
            }
        )
    return result


def _m_output(expression: str) -> str:
    """Tebak jenis output query M untuk kolom Output di 2.2.1.4."""
    text = (expression or "").strip()
    if not text:
        return ""
    if re.match(r"^\(\s*[\w\s,]*\)\s*=>", text):
        return "Function"
    if text.startswith("{") and text.endswith("}"):
        return "List"
    if text.startswith("[") and text.endswith("]"):
        return "Record"
    table_markers = (
        "#table(",
        "Table.FromRows(",
        "Table.FromValue(",
        "Table.FromList(",
        "Table.FromRecords(",
    )
    if any(marker in text for marker in table_markers):
        return "Table"
    return ""


def _m_queries(
    inline_tables: list[Mapping[str, Any]] | None,
    expressions: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    """Query yang dibuat di Power BI untuk 2.2.1.4.

    Isinya tabel inline (Enter Data) dari bucket ``mquery`` ditambah shared M
    expression (fungsi/record/scalar) dari ``06_Expressions_Params``. Parameter
    tidak ikut karena sudah tampil di 2.2.2 Parameters Dataset.
    """
    result: list[dict[str, Any]] = []
    for table in inline_tables or []:
        result.append(
            {
                "name": _text(table.get("table_name", "")),
                "purpose": "",
                "output": "Table",
                "expression": _text(table.get("expression", "")),
            }
        )
    for row in _rows(expressions):
        if _row_text(row, "kind") != "Expression":
            continue
        name = _row_text(row, "name")
        if not name:
            continue
        expression = _text(row.get("expression", "")) or _text(
            row.get("value", "")
        )
        result.append(
            {
                "name": name,
                "purpose": "",
                "output": _m_output(expression),
                "expression": expression,
            }
        )
    return result


def _parameters(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _rows(frame):
        if _row_text(row, "kind") != "Parameter":
            continue
        name = _row_text(row, "name")
        if not name:
            continue
        result.append({"name": name, "value": _row_text(row, "value")})
    return result


def _used_parameters(
    frame: pd.DataFrame | None, expression: str
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _rows(frame):
        if _row_text(row, "kind") != "Parameter":
            continue
        name = _row_text(row, "name")
        if not name:
            continue
        pattern = rf'(?<![A-Za-z0-9_])#?"?{re.escape(name)}"?(?![A-Za-z0-9_])'
        if not expression or not re.search(pattern, expression):
            continue
        result.append({"name": name, "value": _row_text(row, "value")})
    return result


def _hierarchies(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _rows(frame):
        name = _row_text(row, "hierarchy")
        if not name:
            continue
        raw = _text(row.get("levels", ""))
        levels = [item.strip() for item in raw.splitlines() if item.strip()]
        if len(levels) <= 1 and "," in raw:
            levels = [item.strip() for item in raw.split(",") if item.strip()]
        result.append(
            {
                "name": name,
                "table": _row_text(row, "table"),
                "levels": levels,
                "capture": "",
            }
        )
    return result


def _rls(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in _rows(frame):
        role = _row_text(row, "role")
        if not role:
            continue
        entry = grouped.setdefault(role, {"role": role, "tables": [], "expressions": []})
        expression = _text(row.get("table_permission_expression", ""))
        table = _row_text(row, "table")
        if not expression or expression.upper() == "TRUE()":
            continue
        entry["tables"].append(table)
        entry["expressions"].append(f"{table}: {expression}" if table else expression)
    return [
        {
            "role": role,
            "tables": entry["tables"],
            "expression": "\n\n".join(entry["expressions"]),
            "capture": "",
        }
        for role, entry in grouped.items()
        if entry["expressions"]
    ]


def _connector_kind(connector: str) -> tuple[str, str]:
    """(bucket tabel, label source_type) dari nama connector.

    Query tanpa sumber eksternal (connector kosong, ``(inline)``, atau Enter
    Data) masuk bucket ``mquery`` supaya tidak dianggap tabel database.
    """
    text = connector.strip()
    low = text.lower()
    if any(hint in low for hint in INLINE_CONNECTORS):
        return "mquery", "M / Inline"
    if any(hint in low for hint in LIVE_CONNECTORS):
        label = "Dataflow" if "dataflow" in low else "Dataset"
        return "live", label
    if any(hint in low for hint in FILE_CONNECTORS):
        return "file", text or "File"
    if not low:
        return "mquery", "M / custom"
    return "database", text or "Database"


CONNECTOR_PATTERNS = (
    ("PowerPlatform.Dataflows", "PowerPlatform.Dataflows"),
    ("PowerBI.Dataflows", "Power BI Dataflows"),
    ("PowerPlatform.Datasets", "PowerPlatform.Datasets"),
    ("Fabric.Dataflows", "Fabric Dataflows"),
    ("Fabric.Datasets", "Fabric Datasets"),
    ("UsageMetricsDataConnector.GetMetricsData", "Usage Metrics"),
    ("AnalysisServices.Database", "Analysis Services"),
    ("AzureSynapseAnalytics.Database", "Azure Synapse"),
    ("AzureSql.Database", "Azure SQL"),
    ("GoogleBigQuery", "Google BigQuery"),
    ("Snowflake.Databases", "Snowflake"),
    ("PostgreSQL.Database", "PostgreSQL"),
    ("MySQL.Database", "MySQL"),
    ("Oracle.Database", "Oracle"),
    ("Teradata.Database", "Teradata"),
    ("SapHana.Database", "SAP HANA"),
    ("SapBusinessWarehouse.Cubes", "SAP BW"),
    ("DB2.Database", "DB2"),
    ("Sybase.Database", "Sybase"),
    ("Informix.Database", "Informix"),
    ("Odbc.Query", "ODBC"),
    ("Odbc.DataSource", "ODBC"),
    ("Dataverse.Contents", "Dataverse"),
    ("CommonDataService.Database", "Dataverse"),
    ("Sql.Database", "SQL Server"),
    ("Sql.Databases", "SQL Server"),
    ("OData.Feed", "OData"),
    ("SharePoint.Tables", "SharePoint"),
    ("SharePoint.Files", "SharePoint"),
    ("SharePoint.Contents", "SharePoint"),
    ("Excel.Workbook", "Excel"),
    ("Excel.CurrentWorkbook", "Excel"),
    ("Csv.Document", "CSV"),
    ("Folder.Files", "Folder"),
    ("Pdf.Tables", "PDF"),
    ("Pdf.Data", "PDF"),
    ("Parquet.Document", "Parquet"),
    ("GoogleSheets.Contents", "Google Sheets"),
    ("AzureStorage.Blobs", "Azure Storage"),
    ("AzureStorage.DataLake", "Azure Storage"),
    ("Json.Document", "JSON"),
    ("Xml.Tables", "XML"),
    ("Html.Table", "Web"),
    ("File.Contents", "File"),
    ("Web.Contents", "Web"),
    ("Web.Page", "Web"),
)


def _infer_connector(expression: str) -> str:
    """Tebak connector dari fungsi M saat datanya tidak ada di 15_Data_Sources.

    Penanda Enter Data diperiksa lebih dulu (``#table``/``Binary.FromText``)
    karena ekspresinya juga memuat ``Json.Document``. Penanda inline lain
    (``Table.FromRows`` dst.) diperiksa setelah connector eksternal supaya query
    database yang berakhir dengan ``Table.FromValue`` tidak salah bucket.
    """
    text = expression or ""
    if not text.strip():
        return ""
    if any(pattern in text for pattern in INLINE_PATTERNS_EARLY):
        return "Inline"
    for pattern, label in CONNECTOR_PATTERNS:
        if pattern in text:
            return label
    if any(pattern in text for pattern in INLINE_PATTERNS_LATE):
        return "Inline"
    return ""


def _source_row(frame: pd.DataFrame | None, table: str) -> Mapping[str, Any] | None:
    matches = _match(frame, table=table)
    for row in matches:
        connector = _row_text(row, "connector")
        if connector and not connector.startswith("("):
            return row
    return matches[0] if matches else None


def _tables(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, list[dict[str, Any]]]:
    tables_frame = frames.get("02_Tables")
    partitions = frames.get("05_Partitions")
    sources = frames.get("15_Data_Sources")
    columns = frames.get("03_Columns")
    params = frames.get("06_Expressions_Params")
    buckets: dict[str, list[dict[str, Any]]] = {
        "database": [],
        "live": [],
        "file": [],
        "mquery": [],
    }
    for row in _rows(tables_frame):
        table = _row_text(row, "table")
        if not table:
            continue
        table_partitions = _match(partitions, table=table)
        if table_partitions and all(
            _row_text(part, "source_type") in NON_TABLE_PARTITIONS
            for part in table_partitions
        ):
            continue  # calculated table (2.2.3) / calculation group (2.2.11)
        source = _source_row(sources, table)
        expression = _partition_expression(partitions, table)
        connector = _row_text(source, "connector") if source is not None else ""
        if not connector or connector.startswith("("):
            connector = _infer_connector(expression) or connector
        bucket, source_type = _connector_kind(connector)
        column_names, details = _columns_data(
            columns, table, _m_column_logic(partitions, table)
        )
        host = ""
        if source is not None:
            server = _row_text(source, "server")
            database = _row_text(source, "database")
            host = server or database
        entry: dict[str, Any] = {
            "table_name": table,
            "source_type": source_type,
            "source_application": connector,
            "source_name": _row_text(source, "table") if source is not None else "",
            "source_host": host,
            "gateway": "",
            "retention": "",
            "incremental": _incremental_text(partitions, table),
            "columns": column_names,
            "expression": expression,
            "parameters": _used_parameters(params, expression),
            "column_details": details,
        }
        if bucket == "live":
            entry.update(
                {
                    "kind": source_type,
                    "dataset_name": "",
                    "workspace": "",
                    "refresh_schedule": "",
                    "doc_link": "",
                }
            )
        buckets[bucket].append(entry)
    return buckets


# ---------------------------------------------------------------------------
# Konteks
# ---------------------------------------------------------------------------
def _empty_context() -> dict[str, Any]:
    return {
        "meta": {
            "template_version": "1.1",
            "draft": True,
            "expand_all": False,
            "generated_at": "",
        },
        "document": {
            "title": "Technical Specification Design Business Intelligence",
            "subtitle": "",
            "confidentiality": "Confidential",
            "prepared_for": "",
            "history": [
                {
                    "version": "v.1",
                    "date": "",
                    "author": "",
                    "comment": "Initial draft",
                }
            ],
            "author": {"name": "", "role": "", "date": ""},
            "authorizer": {"name": "", "role": "", "date": ""},
        },
        "report": {
            "name": "",
            "workspace": "",
            "folder": "",
            "apps_name": "",
            "apps_tsd_link": "",
            "sharepoint": "",
            "navigation_menu": "",
            "filters": [],
            "info_rows": [],
            "overview": "",
            "insight": [],
        },
        "bps": [],
        "datasets": [],
        "relationships": [],
        "objects": {
            "tables": {"database": [], "live": [], "file": [], "mquery": []},
            "m_queries": [],
            "parameters": [],
            "calculated_tables": [],
            "calculated_columns": [],
            "measures": [],
            "hierarchies": [],
            "pages": [],
            "mobile": {"note": "", "screenshots": []},
            "custom_visuals": [],
            "rls": [],
            "bookmarks": [],
            "sync_slicers": [],
            "serving": {"applications": [], "embedded_pages": []},
        },
    }


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result


def _ignore_override(key: str, value: Any) -> bool:
    """Override yang berarti 'pakai nilai otomatis'.

    Skeleton sidecar menulis ``"screenshot": ""`` dan ``"is_hidden": null``
    untuk setiap halaman/visual. Tanpa aturan ini, merge manual akan menghapus
    data URI hasil capture dan status hidden dari workbook.
    """
    if key == "screenshot":
        return not str(value or "").strip()
    if key == "is_hidden":
        return value is None or not str(value).strip()
    return False


def _apply_page_overrides(
    pages: list[dict[str, Any]], overrides: Mapping[str, Any], log: Log
) -> list[dict[str, Any]]:
    by_id = {page.get("page_id", ""): page for page in pages if page.get("page_id")}
    unknown_pages: list[str] = []
    unknown_visuals = 0
    for page_id, values in overrides.items():
        page = by_id.get(str(page_id))
        if page is None:
            unknown_pages.append(str(page_id))
            continue
        if not isinstance(values, Mapping):
            continue
        visual_overrides = values.get("visuals")
        for key, value in values.items():
            if key == "visuals" or _ignore_override(key, value):
                continue
            page[key] = value
        if not isinstance(visual_overrides, Mapping):
            continue
        visual_by_id = {
            visual.get("visual_id", ""): visual
            for visual in page.get("visuals", [])
            if visual.get("visual_id")
        }
        for visual_id, changes in visual_overrides.items():
            visual = visual_by_id.get(str(visual_id))
            if visual is None:
                unknown_visuals += 1
                continue
            if isinstance(changes, Mapping):
                for key, value in changes.items():
                    if _ignore_override(key, value):
                        continue
                    visual[key] = value
    if unknown_pages:
        preview = ", ".join(unknown_pages[:3])
        rest = (
            f", +{len(unknown_pages) - 3} lainnya"
            if len(unknown_pages) > 3
            else ""
        )
        log(
            f"WARNING: {len(unknown_pages)} override halaman tidak cocok dengan "
            f"workbook ({preview}{rest}); dilewati. Sidecar mungkin milik report lain."
        )
    if unknown_visuals:
        log(
            f"WARNING: {unknown_visuals} override visual tidak cocok dengan "
            "workbook; dilewati (termasuk visual dekoratif yang kini tidak "
            "ditampilkan)."
        )
    return pages


def _merge_objects(
    base: Mapping[str, Any], override: Mapping[str, Any], log: Log
) -> dict[str, Any]:
    result = {key: value for key, value in base.items()}
    for key, value in override.items():
        current = result.get(key)
        if key == "pages" and isinstance(value, Mapping):
            result["pages"] = _apply_page_overrides(
                list(current or []), value, log
            )
        elif key == "tables" and isinstance(value, Mapping) and isinstance(current, Mapping):
            merged = dict(current)
            merged.update(value)
            result[key] = merged
        elif key == "serving" and isinstance(value, Mapping) and isinstance(current, Mapping):
            result[key] = _deep_merge(current, value)
        elif key == "mobile" and isinstance(value, Mapping) and isinstance(current, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result


def _merge_manual(
    base: dict[str, Any], manual: Mapping[str, Any], log: Log
) -> dict[str, Any]:
    result = {key: value for key, value in base.items()}
    for key, value in manual.items():
        current = result.get(key)
        if key == "objects" and isinstance(value, Mapping):
            result["objects"] = _merge_objects(
                current if isinstance(current, Mapping) else {}, value, log
            )
        elif isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result


def build_context(
    report_workbook: Path,
    model_workbook: Path | None = None,
    manual: Mapping[str, Any] | None = None,
    report_name: str = "",
    draft: bool = True,
    expand_all: bool = False,
    generated_at: str | None = None,
    screenshots: ScreenshotSet | None = None,
    include_decorative_visuals: bool = False,
    log: Log = _silent,
) -> dict[str, Any]:
    """Susun konteks TSD dari workbook report (wajib) dan model (opsional)."""
    report_path = Path(report_workbook)
    if not report_path.exists():
        raise ExtractionError(
            f"Workbook report tidak ditemukan: {report_path}. Jalankan ekstraksi report dulu."
        )
    if report_path.suffix.lower() != ".xlsx":
        raise ExtractionError(f"Workbook report harus file .xlsx: {report_path}")

    report_frames = _read_sheets(report_path, REPORT_SHEETS, log)
    model_frames: dict[str, pd.DataFrame] = {}
    model_path = Path(model_workbook) if model_workbook else None
    if model_path is not None:
        if model_path.exists():
            model_frames = _read_sheets(model_path, MODEL_SHEETS, log)
        else:
            log(
                f"WARNING: workbook model tidak ditemukan: {model_path.name}; "
                "bagian model TSD dikosongkan."
            )

    context = _empty_context()
    context["report"]["name"] = report_name
    context["report"]["filters"] = _filters(report_frames.get("07_Filters"), "Report")
    pages = _pages(report_frames, model_frames, include_decorative=include_decorative_visuals)
    screenshot_stats, mobile_shots = _attach_screenshots(
        pages, screenshots, log
    )
    context["objects"]["pages"] = pages
    mobile = context["objects"]["mobile"]
    mobile["screenshots"] = mobile_shots
    if screenshots is not None and screenshots.mobile_enabled and not mobile_shots:
        mobile["note"] = (
            "Report belum memiliki mobile layout (phone layout) atau gambar "
            "mobile gagal diambil; tidak ada gambar mobile di 2.2.7.2."
        )
    context["objects"]["bookmarks"] = _bookmarks(report_frames.get("02_Bookmarks"))
    context["objects"]["sync_slicers"] = _sync_slicers(
        report_frames.get("06_Sync_Slicers")
    )

    if model_frames:
        context["relationships"] = _relationships(
            model_frames.get("07_Relationships")
        )
        context["objects"]["measures"] = _measures(model_frames.get("04_Measures"))
        context["objects"]["calculated_columns"] = _calculated_columns(
            model_frames.get("03_Columns")
        )
        context["objects"]["calculated_tables"] = _calculated_tables(
            model_frames.get("02_Tables"),
            model_frames.get("05_Partitions"),
            model_frames.get("03_Columns"),
        )
        context["objects"]["parameters"] = _parameters(
            model_frames.get("06_Expressions_Params")
        )
        context["objects"]["hierarchies"] = _hierarchies(
            model_frames.get("18_Hierarchies")
        )
        context["objects"]["rls"] = _rls(model_frames.get("08_Roles_RLS"))
        tables = _tables(model_frames)
        context["objects"]["tables"] = tables
        context["objects"]["m_queries"] = _m_queries(
            tables.get("mquery"), model_frames.get("06_Expressions_Params")
        )

    if manual:
        context = _merge_manual(context, manual, log)

    if report_name:
        context["report"]["name"] = report_name
    elif not context["report"].get("name"):
        context["report"]["name"] = ""
    meta = context.setdefault("meta", {})
    meta["template_version"] = meta.get("template_version") or "1.1"
    meta["draft"] = bool(draft)
    meta["expand_all"] = bool(expand_all)
    meta["generated_at"] = generated_at or format_date()
    meta["screenshot_stats"] = screenshot_stats
    return context


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------
DAX_KEYWORDS = {
    "VAR",
    "RETURN",
    "EVALUATE",
    "DEFINE",
    "MEASURE",
    "COLUMN",
    "TABLE",
    "IF",
    "ELSE",
    "SWITCH",
    "TRUE",
    "FALSE",
    "BLANK",
    "NOT",
    "IN",
    "AND",
    "OR",
    "ASC",
    "DESC",
    "START",
    "AT",
    "ORDER",
    "BY",
}
M_KEYWORDS = {
    "let",
    "in",
    "each",
    "if",
    "then",
    "else",
    "try",
    "otherwise",
    "error",
    "type",
    "meta",
    "section",
    "shared",
    "as",
    "is",
    "and",
    "or",
    "not",
    "true",
    "false",
    "null",
}
TOKEN_RE = re.compile(
    r"""
    (?P<comment>//[^\n]*|/\*.*?\*/)
    |(?P<string>"(?:[^"]|"")*")
    |(?P<table>'(?:[^']|'')*')
    |(?P<column>\[[^\]]*\])
    |(?P<number>\b\d+(?:\.\d+)?\b)
    |(?P<word>[A-Za-z_][A-Za-z0-9_.]*)
    """,
    re.S | re.X,
)
TOKEN_CLASS = {
    "comment": "tok-comment",
    "string": "tok-str",
    "table": "tok-ref",
    "column": "tok-ref",
    "number": "tok-num",
}


def highlight_code(value: Any, language: str) -> Markup:
    """Pewarnaan DAX/M ringan; fragmen di-escape sebelum ditandai Markup."""
    if value is None:
        return Markup("")
    text = str(value)
    parts: list[str] = []
    position = 0
    for match in TOKEN_RE.finditer(text):
        parts.append(str(escape(text[position : match.start()])))
        token = match.group(0)
        kind = match.lastgroup or ""
        following = text[match.end() : match.end() + 8].lstrip()
        css_class = TOKEN_CLASS.get(kind)
        if kind == "word":
            upper = token.upper()
            if following.startswith("("):
                css_class = "tok-fn"
            elif language == "dax" and upper in DAX_KEYWORDS:
                css_class = "tok-kw"
            elif language == "m" and token.lower() in M_KEYWORDS:
                css_class = "tok-kw"
            elif following.startswith("["):
                css_class = "tok-ref"
        if css_class:
            parts.append(f'<span class="{css_class}">{escape(token)}</span>')
        else:
            parts.append(str(escape(token)))
        position = match.end()
    parts.append(str(escape(text[position:])))
    return Markup("".join(parts))


def nl2br(value: Any) -> Markup:
    if value is None:
        return Markup("")
    lines = str(value).splitlines()
    return Markup("<br>\n".join(str(escape(line)) for line in lines))


def build_environment() -> Environment:
    env = Environment(
        loader=BaseLoader(),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
        undefined=ChainableUndefined,
        keep_trailing_newline=True,
    )
    env.filters["nl2br"] = nl2br
    env.filters["dax"] = lambda value: highlight_code(value, "dax")
    env.filters["mcode"] = lambda value: highlight_code(value, "m")
    return env


def normalize_meta(value: Mapping[str, Any] | None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "template_version": "1.1",
        "draft": False,
        "expand_all": False,
        "generated_at": "",
    }
    if isinstance(value, Mapping):
        meta.update(value)
    return meta


def format_date(value: Any = None) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, date):
        return f"{value.day} {MONTHS_ID[value.month - 1]} {value.year}"
    today = date.today()
    return f"{today.day} {MONTHS_ID[today.month - 1]} {today.year}"


def render_tsd(
    context: Mapping[str, Any], template_path: Path | None = None
) -> str:
    """Render konteks menjadi HTML mandiri dan validasi hasilnya."""
    path = Path(template_path) if template_path else TEMPLATE_PATH
    if not path.exists():
        raise ExtractionError(
            f"Template TSD tidak ditemukan: {path}. Salin dari "
            r"..\template-tsd\templates\tsd.template.html."
        )
    template_text = path.read_text(encoding="utf-8")
    environment = build_environment()
    data = dict(context)
    data["meta"] = normalize_meta(context.get("meta"))
    html = environment.from_string(template_text).render(**data)
    validate_html(html)
    return html


def validate_html(html: str) -> None:
    leftover = LEFTOVER_TOKEN.search(html)
    if leftover:
        line = html.count("\n", 0, leftover.start()) + 1
        raise ExtractionError(
            f"Token Jinja belum dirender di baris {line}: {leftover.group(0)}"
        )
    if "<html" not in html or "</html>" not in html:
        raise ExtractionError("Hasil render bukan dokumen HTML lengkap.")
    for anchor in REQUIRED_ANCHORS:
        if f'id="{anchor}"' not in html:
            raise ExtractionError(f"Section TSD wajib tidak ditemukan: {anchor}")


def write_tsd(
    context: Mapping[str, Any],
    out_path: Path,
    template_path: Path | None = None,
) -> Path:
    html = render_tsd(context, template_path)
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8", newline="\r\n")
    return path


# ---------------------------------------------------------------------------
# Alur kerja
# ---------------------------------------------------------------------------
def slug(value: str) -> str:
    """Nama file aman dari nama report."""
    cleaned = re.sub(r'[<>:"/\\|?*]+', "", value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "Report"


def output_file_name(report_name: str, report_id: str = "") -> str:
    """Nama file TSD bawaan: ``TSD_<nama>_<id8>.html``.

    Delapan karakter pertama report ID mencegah dua report dengan nama sama
    (mis. dua report bernama "Report Uji") saling menimpa HTML
    dan sidecar manual. Local ``.pbix`` tanpa report ID tetap memakai nama saja.
    """
    stem = slug(report_name or "Report")
    suffix = (report_id or "").strip()[:8]
    if suffix:
        stem = f"{stem}_{suffix}"
    return f"{OUT_PREFIX}{stem}.html"


def manual_skeleton(context: Mapping[str, Any]) -> dict[str, Any]:
    """Kerangka sidecar berisi override kosong agar mudah diisi."""
    pages: dict[str, Any] = {}
    for page in context.get("objects", {}).get("pages", []):
        page_id = page.get("page_id", "")
        if not page_id:
            continue
        visuals = {
            visual.get("visual_id", ""): {"tooltip": "", "screenshot": ""}
            for visual in page.get("visuals", [])
            if visual.get("visual_id")
        }
        pages[page_id] = {
            "is_hidden": None,
            "screenshot": "",
            "visuals": visuals,
        }
    return {
        "meta": {"draft": True, "expand_all": False},
        "document": {
            "subtitle": "",
            "prepared_for": "",
            "author": {"name": "", "role": "", "date": ""},
            "authorizer": {"name": "", "role": "", "date": ""},
        },
        "report": {
            "name": context.get("report", {}).get("name", ""),
            "workspace": "",
            "folder": "",
            "apps_name": "",
            "apps_tsd_link": "",
            "sharepoint": "",
            "navigation_menu": "",
            "overview": "",
            "insight": [],
        },
        "bps": [],
        "datasets": [],
        "objects": {"pages": pages},
    }


def load_manual(path: Path, log: Log = _silent) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Konteks manual tidak bisa dibaca: {path} ({exc}).") from exc
    if not isinstance(data, dict):
        raise ExtractionError(f"Konteks manual harus objek JSON: {path}")
    return data


def write_manual(path: Path, data: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8", newline="\r\n")
    return path


def run_tsd(
    report_workbook: Path | None = None,
    model_workbook: Path | None = None,
    out_file: Path | None = None,
    manual_path: Path | None = None,
    manual: Mapping[str, Any] | None = None,
    report_name: str = "",
    report_id: str = "",
    draft: bool = True,
    expand_all: bool = False,
    generated_at: str | None = None,
    template_path: Path | None = None,
    save_manual: bool = True,
    capture: "CaptureOptions | None" = None,
    include_decorative_visuals: bool = False,
    log: Log = _silent,
) -> dict[str, Any]:
    """Bangun konteks, render HTML, dan simpan sidecar manual bila diminta."""
    report_path = Path(report_workbook) if report_workbook else Path(OUT_FILE)
    if not report_path.exists():
        raise ExtractionError(
            f"Workbook report tidak ditemukan: {report_path}. Jalankan ekstraksi report dulu."
        )
    model_path = Path(model_workbook) if model_workbook else None
    if model_path is not None and not model_path.exists():
        log(f"WARNING: workbook model tidak ditemukan: {model_path}; dilewati.")
        model_path = None

    explicit_manual = dict(manual or {})
    had_manual = bool(explicit_manual)
    manual_file = Path(manual_path) if manual_path else None
    if manual_file is None and out_file is not None:
        manual_file = Path(out_file).with_suffix(".json")
    if manual_file is not None:
        loaded = load_manual(manual_file, log)
        explicit_manual = _deep_merge(loaded, explicit_manual)
    manual_report = explicit_manual.get("report")
    if not isinstance(manual_report, dict):
        manual_report = {}
    name = report_name or _text(manual_report.get("name", ""))
    if name:
        explicit_manual["report"] = {**manual_report, "name": name}

    if out_file is not None:
        path = Path(out_file)
    else:
        effective_id = (report_id or "").strip()
        if not effective_id and capture is not None:
            effective_id = str(getattr(capture, "report_id", "") or "").strip()
        path = Path(OUT_FILE).parent / output_file_name(
            name or "Report", effective_id
        )
    if manual_file is None:
        manual_file = path.with_suffix(".json")

    log(f"Report workbook  : {report_path}")
    log(f"Model workbook   : {model_path if model_path else 'tidak ada'}")
    log(f"Konteks manual   : {manual_file}")
    log(f"Template         : {Path(template_path) if template_path else TEMPLATE_PATH}")

    screenshots: ScreenshotSet | None = None
    if capture is not None:
        from .pbi_capture.cache import cache_dir
        from .pbi_capture.runner import load_or_capture

        assets_root = (
            Path(capture.output_root)
            if capture.output_root
            else cache_dir(path.parent, name or "Report", capture.report_id)
        )
        options = replace(capture, output_root=assets_root, hints_workbook=report_path)
        if not include_decorative_visuals:
            options = replace(
                options,
                exclude_visual_types=tuple(
                    sorted(
                        set(options.exclude_visual_types)
                        | DECORATIVE_VISUAL_TYPES
                    )
                ),
            )
        if (options.viewport_width, options.viewport_height) == (1600, 1000):
            width, height = _report_page_size(report_path, log)
            if width and height:
                options = replace(
                    options, viewport_width=width, viewport_height=height
                )
                log(f"Viewport capture  : {width}x{height} (ukuran halaman report)")
        log(f"Screenshot assets: {assets_root}")
        screenshots = load_or_capture(options, log=log)

    context = build_context(
        report_path,
        model_path,
        manual=explicit_manual,
        report_name=name,
        draft=draft,
        expand_all=expand_all,
        generated_at=generated_at,
        screenshots=screenshots,
        include_decorative_visuals=include_decorative_visuals,
        log=log,
    )
    output = write_tsd(context, path, template_path)

    if save_manual:
        saved = False
        if not had_manual and not manual_file.exists():
            write_manual(manual_file, _deep_merge(manual_skeleton(context), explicit_manual))
            saved = True
        elif explicit_manual:
            to_save = dict(explicit_manual)
            objects = to_save.get("objects")
            if not isinstance(objects, dict) or "pages" not in objects:
                skeleton = manual_skeleton(context)["objects"]
                merged = dict(objects) if isinstance(objects, dict) else {}
                merged.setdefault("pages", skeleton["pages"])
                to_save["objects"] = merged
            write_manual(manual_file, to_save)
            saved = True
        if saved:
            log(f"Konteks manual disimpan: {manual_file}")

    html = output.read_text(encoding="utf-8")
    pages = context.get("objects", {}).get("pages", [])
    visuals = sum(len(page.get("visuals", [])) for page in pages)
    objects = context.get("objects", {})
    table_buckets = objects.get("tables", {})
    table_count = sum(
        len(items) for items in table_buckets.values() if isinstance(items, list)
    )
    shot_stats = context.get("meta", {}).get("screenshot_stats") or {}
    summary = {
        "output": output,
        "manual": manual_file,
        "report_workbook": report_path,
        "model_workbook": model_path,
        "pages": len(pages),
        "visuals": visuals,
        "tables": table_count,
        "measures": len(objects.get("measures") or []),
        "todos": html.count(TODO_MARKER),
        "size": output.stat().st_size,
        "screenshot_pages": shot_stats.get("pages", 0),
        "screenshot_visuals": shot_stats.get("visuals", 0),
        "screenshot_mobile": shot_stats.get("mobile", 0),
        "screenshot_missing": shot_stats.get("missing_pages", 0)
        + shot_stats.get("missing_visuals", 0),
        "screenshot_root": screenshots.root if screenshots is not None else None,
    }
    log("")
    log(f"TSD dibuat        : {output}")
    log(f"Halaman / visual  : {summary['pages']} / {summary['visuals']}")
    if summary["screenshot_root"] is not None:
        log(
            f"Screenshot        : {summary['screenshot_pages']} page / "
            f"{summary['screenshot_visuals']} visual / "
            f"{summary['screenshot_mobile']} mobile "
            f"({summary['screenshot_missing']} tanpa gambar)"
        )
    log(f"Ukuran / TODO     : {summary['size'] / 1024:.1f} KB / {summary['todos']}")
    return summary
