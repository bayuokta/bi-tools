"""
Ekstraksi metadata report dari file .pbix (PBIR GA) + validasi model opsional.

Modul inti tanpa I/O terminal; dipakai oleh CLI dan GUI.
Input : Report/definition hasil ekstraksi .pbix, dan workbook model opsional.
Output: Report_Metadata.xlsx
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .errors import ExtractionError
from .metadata_common import QUERY_AGGREGATE_FUNCTION
from .pbix import ROOT, display_path
from .paths import APP_DIR, OUTPUTS_DIR

OUT_DIR = OUTPUTS_DIR
MODEL_WORKBOOK_NAME = "Semantic_Model_Metadata.xlsx"
DEFAULT_MODEL_WORKBOOK = OUT_DIR / MODEL_WORKBOOK_NAME
OUT_FILE = OUT_DIR / "Report_Metadata.xlsx"

COMPARISON_KIND = {
    0: "=",
    1: ">",
    2: ">=",
    3: "<",
    4: "<=",
    5: "<>",
}

# Tipe interaksi visual pada PBIR (page.json -> visualInteractions).
# DataFilter adalah perilaku default Power BI, NoFilter berarti interaksi dimatikan.
INTERACTION_TYPES = {
    "DataFilter": ("Filter", True),
    "HighlightFilter": ("Highlight", False),
    "NoFilter": ("No filter", False),
}

# Visual calculation disimpan PBIR sebagai NativeVisualCalculation.
VISUAL_CALCULATION_KINDS = {"NativeVisualCalculation", "VisualCalculation"}


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig") as fh:
        return json.load(fh)


def clean_literal(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.startswith("datetime'"):
        return text[len("datetime'") :].rstrip("'").replace("T", " ")
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1].replace("''", "'")
    return text


def literal_from_expr(expr: Any) -> Any:
    """Ambil nilai Literal dari struktur expr PBIR."""
    if isinstance(expr, dict):
        if "Literal" in expr and isinstance(expr["Literal"], dict):
            return expr["Literal"].get("Value")
        for value in expr.values():
            found = literal_from_expr(value)
            if found is not None:
                return found
    elif isinstance(expr, list):
        for item in expr:
            found = literal_from_expr(item)
            if found is not None:
                return found
    return None


def object_property(visual: dict[str, Any], group: str, prop: str) -> Any:
    """objects.<group> bisa berupa array atau object tunggal."""
    objects = visual.get("objects") or {}
    entries = objects.get(group)
    if isinstance(entries, dict):
        entries = [entries]
    for entry in entries or []:
        props = entry.get("properties") or {}
        if prop in props:
            return literal_from_expr(props[prop])
    return None


def deep_entity_property(node: Any) -> tuple[str | None, str | None]:
    """Cari pasangan SourceRef.Entity + Property secara rekursif."""
    if isinstance(node, dict):
        source = node.get("SourceRef")
        if isinstance(source, dict) and source.get("Entity"):
            return source.get("Entity"), node.get("Property")
        for value in node.values():
            table, field = deep_entity_property(value)
            if table or field:
                return table, field
    elif isinstance(node, list):
        for item in node:
            table, field = deep_entity_property(item)
            if table or field:
                return table, field
    return None, None


def parse_field(field: dict[str, Any]) -> dict[str, Any]:
    """Kembalikan kind, table, field, agregasi, dan ekspresi tambahan."""
    kind = next((key for key in field if key != "Expression"), "Unknown")
    node = field.get(kind) or {}
    table = None
    name = None
    aggregation = ""
    expression = ""

    if kind in VISUAL_CALCULATION_KINDS:
        kind = "VisualCalculation"
        table = ""
        name = node.get("Name") or node.get("Property")
        expression = node.get("Expression") or ""
    elif kind in {"Column", "Measure"}:
        source = (node.get("Expression") or {}).get("SourceRef") or {}
        table = source.get("Entity")
        name = node.get("Property")
    elif kind == "Aggregation":
        column = (node.get("Expression") or {}).get("Column") or {}
        table = ((column.get("Expression") or {}).get("SourceRef") or {}).get("Entity")
        name = column.get("Property")
        if not name:
            table, name = deep_entity_property(node)
        if not name:
            name = node.get("Property")
        function = node.get("Function")
        try:
            function = int(function)
        except (TypeError, ValueError):
            function = None
        aggregation = QUERY_AGGREGATE_FUNCTION.get(function, "")
    elif kind == "HierarchyLevel":
        table, _ = deep_entity_property(node)
        hierarchy = None
        level = node.get("Level")
        hierarchy_node = (node.get("Expression") or {}).get("Hierarchy") or {}
        hierarchy = hierarchy_node.get("Property")
        name = f"{hierarchy}.{level}" if hierarchy and level else (level or hierarchy)
    else:
        table, name = deep_entity_property(node)

    return {
        "field_kind": kind,
        "table": table or "",
        "field": name or "",
        "aggregation": aggregation,
        "expression": expression,
    }


def parse_filter_field(filter_obj: dict[str, Any]) -> tuple[str, str, str]:
    field = filter_obj.get("field") or {}
    if not field:
        return "", "", ""
    info = parse_field(field)
    return info["field_kind"], info["table"], info["field"]


def collect_filter_values(node: Any) -> list[str]:
    values: list[str] = []
    if isinstance(node, dict):
        if "Literal" in node and isinstance(node["Literal"], dict):
            values.append(clean_literal(node["Literal"].get("Value")))
        if "Comparison" in node and isinstance(node["Comparison"], dict):
            comp = node["Comparison"]
            kind = comp.get("ComparisonKind")
            operator = COMPARISON_KIND.get(kind, f"kind {kind}")
            literal = literal_from_expr(comp.get("Right"))
            if literal is not None:
                values.append(f"{operator} {clean_literal(literal)}")
        for key, value in node.items():
            if key in {"Literal", "Comparison"}:
                continue
            values.extend(collect_filter_values(value))
    elif isinstance(node, list):
        for item in node:
            values.extend(collect_filter_values(item))
    return [v for v in values if v != ""]


def visual_title(visual: dict[str, Any], visual_id: str) -> tuple[str, str]:
    container = visual.get("visualContainerObjects") or {}
    title_entries = container.get("title") or []
    for entry in title_entries:
        text = literal_from_expr((entry.get("properties") or {}).get("text"))
        if text:
            cleaned = clean_literal(text)
            if cleaned:
                return cleaned, "title"
    return f"(untitled) {visual.get('visualType', 'visual')} {visual_id[:8]}", "fallback"


# ----------------------------------------------------------------------------
# Bookmark & interaction helpers
# ----------------------------------------------------------------------------
def resolve_visual(
    visual_id: str, visual_lookup: dict[str, dict[str, str]]
) -> dict[str, str]:
    return visual_lookup.get(
        visual_id,
        {
            "page_name": "",
            "page_id": "",
            "visual_name": f"(visual tidak ditemukan) {visual_id[:8]}",
            "visual_type": "",
        },
    )


def filter_state_containers(state: Any) -> list[dict[str, Any]]:
    """Ambil semua filter container dari struktur FiltersState bookmark."""
    containers: list[dict[str, Any]] = []
    if not isinstance(state, dict):
        return containers
    for key in ("byName", "byExpr", "byType", "byTransientState"):
        value = state.get(key)
        if isinstance(value, dict):
            containers.extend(v for v in value.values() if isinstance(v, dict))
        elif isinstance(value, list):
            containers.extend(v for v in value if isinstance(v, dict))
    return containers


def bookmark_filter_entries(exploration: dict[str, Any]) -> list[str]:
    """Ringkas filter yang tersimpan di bookmark (report + per halaman)."""
    entries: list[str] = []

    def describe(container: dict[str, Any], scope: str) -> str:
        expression = container.get("expression") or {}
        table = field = ""
        if isinstance(expression, dict) and expression:
            info = parse_field(expression)
            table, field = info["table"], info["field"]
        if not table and not field:
            table, field = deep_entity_property(container.get("filter") or {})
        values = collect_filter_values(container.get("filter") or {})
        parts = [scope] if scope else []
        parts.append(container.get("type") or "Filter")
        field_ref = ".".join(part for part in (table, field) if part)
        if field_ref:
            parts.append(field_ref)
        if container.get("name"):
            parts.append(f"[{container['name']}]")
        text = " ".join(parts)
        if values:
            text += " = " + "; ".join(values)
        return text

    for container in filter_state_containers(exploration.get("filters")):
        entries.append(describe(container, "Report"))

    for page_id, section in (exploration.get("sections") or {}).items():
        if not isinstance(section, dict):
            continue
        for container in filter_state_containers(section.get("filters")):
            entries.append(describe(container, f"Page {page_id}"))

    return entries


def blank_bookmark_row(note: str, source_file: str) -> dict[str, Any]:
    return {
        "status": "TIDAK ADA BOOKMARK",
        "bookmark_order": "",
        "bookmark_name": "",
        "display_name": "",
        "group_name": "",
        "group_display_name": "",
        "page_name": "",
        "page_id": "",
        "apply_only_to_target_visuals": "",
        "suppress_active_section": "",
        "suppress_data": "",
        "suppress_display": "",
        "target_visual_count": "",
        "target_visuals": "",
        "filter_count": "",
        "filters": "",
        "visual_state_count": "",
        "hidden_visuals": "",
        "source_file": source_file,
        "note": note,
    }


def extract_bookmarks(
    visual_lookup: dict[str, dict[str, str]],
    page_lookup: dict[str, str],
    report_def: Path,
) -> list[dict[str, Any]]:
    bookmark_dir = report_def / "bookmarks"
    bookmark_files = (
        {p.name[: -len(".bookmark.json")]: p for p in bookmark_dir.glob("*.bookmark.json")}
        if bookmark_dir.is_dir()
        else {}
    )

    if not bookmark_files:
        return [
            blank_bookmark_row(
                "Report tidak memiliki folder definition/bookmarks, sehingga tidak ada "
                "bookmark yang tersimpan di file PBIR. Bookmark yang dibuat di Power BI "
                "Desktop akan muncul di sheet ini setelah file .pbix disimpan ulang.",
                "definition/bookmarks (tidak ditemukan)",
            )
        ]

    metadata_path = bookmark_dir / "bookmarks.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {}
    ordered_names: list[str] = []
    group_of: dict[str, tuple[str, str]] = {}
    for item in metadata.get("items") or []:
        if not isinstance(item, dict):
            continue
        children = item.get("children")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, str):
                    ordered_names.append(child)
                    group_of[child] = (
                        item.get("name", ""),
                        item.get("displayName", ""),
                    )
        elif item.get("name"):
            ordered_names.append(item["name"])
            group_of.setdefault(item["name"], ("", ""))

    # Bookmark yang tidak tercatat di bookmarks.json tetap didokumentasikan.
    remaining = sorted(set(bookmark_files) - set(ordered_names))
    names = [name for name in ordered_names if name in bookmark_files] + remaining

    rows: list[dict[str, Any]] = []
    for order, name in enumerate(names, start=1):
        path = bookmark_files[name]
        data = read_json(path)
        exploration = data.get("explorationState") or {}
        options = data.get("options") or {}

        active_section = exploration.get("activeSection") or ""
        sections = exploration.get("sections") or {}
        target_ids = [str(v) for v in (options.get("targetVisualNames") or [])]
        target_visuals = []
        for target_id in target_ids:
            info = resolve_visual(target_id, visual_lookup)
            label = f"{info['page_name']} > {info['visual_name']}" if info["page_name"] else info["visual_name"]
            target_visuals.append(f"{label} ({target_id})")

        filter_entries = bookmark_filter_entries(exploration)
        visual_state_count = 0
        hidden_visuals: list[str] = []
        for page_id, section in sections.items():
            if not isinstance(section, dict):
                continue
            containers = section.get("visualContainers") or {}
            if isinstance(containers, dict):
                visual_state_count += len(containers)
                for visual_id, state in containers.items():
                    display = ((state or {}).get("singleVisual") or {}).get("display") or {}
                    if display.get("mode") == "hidden":
                        info = resolve_visual(visual_id, visual_lookup)
                        hidden_visuals.append(
                            f"{page_lookup.get(page_id, page_id)} > {info['visual_name']}"
                        )

        group_name, group_display = group_of.get(name, ("", ""))
        try:
            source_file = path.relative_to(ROOT).as_posix()
        except ValueError:
            source_file = path.as_posix()
        rows.append(
            {
                "status": "OK",
                "bookmark_order": order,
                "bookmark_name": data.get("name") or name,
                "display_name": data.get("displayName", ""),
                "group_name": group_name,
                "group_display_name": group_display,
                "page_name": page_lookup.get(active_section, active_section),
                "page_id": active_section,
                "apply_only_to_target_visuals": bool(
                    options.get("applyOnlyToTargetVisuals", False)
                ),
                "suppress_active_section": bool(options.get("suppressActiveSection", False)),
                "suppress_data": bool(options.get("suppressData", False)),
                "suppress_display": bool(options.get("suppressDisplay", False)),
                "target_visual_count": len(target_ids),
                "target_visuals": " | ".join(target_visuals),
                "filter_count": len(filter_entries),
                "filters": " | ".join(filter_entries),
                "visual_state_count": visual_state_count,
                "hidden_visuals": " | ".join(hidden_visuals),
                "source_file": source_file,
                "note": "" if metadata_path.exists() else "bookmarks.json tidak ditemukan; urutan memakai nama file.",
            }
        )

    return rows


# ----------------------------------------------------------------------------
# Sync slicer helpers
# ----------------------------------------------------------------------------
def blank_sync_slicer_row(note: str) -> dict[str, Any]:
    return {
        "sync_group": "",
        "page_order": "",
        "page_name": "",
        "page_id": "",
        "slicer_name": "",
        "visual_id": "",
        "table": "",
        "column": "",
        "field_kind": "",
        "field_changes": "",
        "filter_changes": "",
        "group_size": "",
        "group_pages": "",
        "note": note,
    }


def extract_sync_slicers(report_def: Path) -> list[dict[str, Any]]:
    """Ambil konfigurasi sync slicer dari tiap visual.json (visual.syncGroup).

    Slicer dengan groupName sama saling menyinkronkan seleksi antar halaman.
    Hanya slicer yang punya syncGroup yang dimasukkan; baris diurutkan per
    sync_group lalu urutan halaman agar anggota satu grup berdampingan.
    """
    pages_meta = read_json(report_def / "pages" / "pages.json")
    page_order = pages_meta.get("pageOrder", [])

    rows: list[dict[str, Any]] = []
    for order, page_id in enumerate(page_order, start=1):
        page_dir = report_def / "pages" / page_id
        page_json = read_json(page_dir / "page.json")
        page_name = page_json.get("displayName") or page_id

        visuals_dir = page_dir / "visuals"
        if not visuals_dir.is_dir():
            continue
        for vdir in sorted(p for p in visuals_dir.iterdir() if p.is_dir()):
            vjson = read_json(vdir / "visual.json")
            visual = vjson.get("visual") or {}
            if visual.get("visualType") != "slicer":
                continue
            sync = visual.get("syncGroup")
            if not isinstance(sync, dict) or not sync.get("groupName"):
                continue

            visual_id = vjson.get("name") or vdir.name
            title, _title_source = visual_title(visual, visual_id)

            # Field yang dibinding slicer (syncGroup hanya berlaku satu field).
            query_state = (visual.get("query") or {}).get("queryState") or {}
            tables: list[str] = []
            columns: list[str] = []
            kinds: list[str] = []
            for role_content in query_state.values():
                for projection in (role_content or {}).get("projections") or []:
                    info = parse_field(projection.get("field") or {})
                    if info["table"] and info["table"] not in tables:
                        tables.append(info["table"])
                    if info["field"] and info["field"] not in columns:
                        columns.append(info["field"])
                    if info["field_kind"] and info["field_kind"] not in kinds:
                        kinds.append(info["field_kind"])

            rows.append(
                {
                    "sync_group": sync.get("groupName", ""),
                    "page_order": order,
                    "page_name": page_name,
                    "page_id": page_id,
                    "slicer_name": title,
                    "visual_id": visual_id,
                    "table": "; ".join(tables),
                    "column": "; ".join(columns),
                    "field_kind": "; ".join(kinds),
                    "field_changes": bool(sync.get("fieldChanges", False)),
                    "filter_changes": bool(sync.get("filterChanges", False)),
                }
            )

    if not rows:
        return [
            blank_sync_slicer_row(
                "TIDAK ADA SYNC SLICER: report tidak memiliki slicer dengan "
                "syncGroup, sehingga tidak ada seleksi slicer yang sync antar "
                "halaman. Sync slicer dibuat lewat pane Sync slicers di Power BI "
                "Desktop dan disimpan di visual.json sebagai syncGroup."
            )
        ]

    members: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        members.setdefault(str(row["sync_group"]), []).append(row)

    enriched: list[dict[str, Any]] = []
    for group_name in sorted(members):
        group_rows = sorted(
            members[group_name],
            key=lambda r: (r["page_order"], str(r["slicer_name"])),
        )
        ordered_pages: list[str] = []
        for member in group_rows:
            if member["page_name"] not in ordered_pages:
                ordered_pages.append(member["page_name"])
        for row in group_rows:
            other_pages = [name for name in ordered_pages if name != row["page_name"]]
            note = ""
            if len(group_rows) == 1:
                note = "Grup hanya berisi 1 slicer; tidak ada slicer lain yang sync."
            enriched.append(
                {
                    **row,
                    "group_size": len(group_rows),
                    "group_pages": "; ".join(other_pages),
                    "note": note,
                }
            )

    return enriched


# ----------------------------------------------------------------------------
# Model inventory (workbook)
# ----------------------------------------------------------------------------
def as_bool(value: Any) -> bool:
    """Konversi nilai sel Excel (True/False/"True"/1) menjadi bool."""
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def page_is_hidden(page_json: dict[str, Any]) -> bool:
    """Halaman tidak tampil di view mode.

    PBIR menyimpan halaman tersembunyi sebagai ``visibility="HiddenInViewMode"``.
    Halaman tooltip juga tidak muncul di navigasi walau kadang tanpa
    ``visibility``, jadi keduanya dihitung tersembunyi.
    """
    visibility = str(page_json.get("visibility") or "").strip().lower()
    if visibility == "hiddeninviewmode":
        return True
    if str(page_json.get("type") or "").strip().lower() == "tooltip":
        return True
    return bool(page_json.get("isHidden", False))


def load_model_inventory_from_workbook(
    path: Path,
) -> tuple[dict[str, dict[str, dict[str, bool]]], list[dict[str, Any]]]:
    """Fallback offline: bangun inventory model dari Semantic_Model_Metadata.xlsx."""
    if not path.exists():
        raise ExtractionError(
            f"Workbook model tidak ditemukan: {path}. "
            "Jalankan extract_model_metadata.py atau tentukan --model-workbook."
        )

    tables: dict[str, dict[str, dict[str, bool]]] = {}
    inventory: list[dict[str, Any]] = []

    columns_df = pd.read_excel(path, sheet_name="03_Columns")
    for record in columns_df.to_dict("records"):
        table = str(record.get("table") or "").strip()
        name = str(record.get("column") or "").strip()
        if not table or not name:
            continue
        hidden = as_bool(record.get("is_hidden"))
        tables.setdefault(table, {"columns": {}, "measures": {}})
        tables[table]["columns"].setdefault(name, {"hidden": hidden})
        inventory.append(
            {"table": table, "object_type": "Column", "name": name, "is_hidden": hidden}
        )

    measures_df = pd.read_excel(path, sheet_name="04_Measures")
    for record in measures_df.to_dict("records"):
        table = str(record.get("table") or "").strip()
        name = str(record.get("measure") or "").strip()
        if not name:
            continue
        hidden = as_bool(record.get("is_hidden"))
        tables.setdefault(table, {"columns": {}, "measures": {}})
        tables[table]["measures"].setdefault(name, {"hidden": hidden})
        inventory.append(
            {"table": table, "object_type": "Measure", "name": name, "is_hidden": hidden}
        )

    return tables, inventory


# ----------------------------------------------------------------------------
# Report extraction
# ----------------------------------------------------------------------------
def extract_report(
    report_def: Path,
):
    pages_meta = read_json(report_def / "pages" / "pages.json")
    report_meta = read_json(report_def / "report.json")

    page_order = pages_meta.get("pageOrder", [])
    active_page = pages_meta.get("activePageName", "")

    page_rows: list[dict[str, Any]] = []
    field_rows: list[dict[str, Any]] = []
    slicer_rows: list[dict[str, Any]] = []
    filter_rows: list[dict[str, Any]] = []
    visual_rows: list[dict[str, Any]] = []
    interaction_rows: list[dict[str, Any]] = []
    visual_lookup: dict[str, dict[str, str]] = {}
    page_lookup: dict[str, str] = {}

    # report-level filters
    for ordinal, flt in enumerate((report_meta.get("filterConfig") or {}).get("filters", [])):
        kind, table, field = parse_filter_field(flt)
        values = collect_filter_values(flt.get("filter"))
        filter_rows.append(
            {
                "scope": "Report",
                "page_order": "",
                "page_name": "(semua halaman)",
                "page_id": "",
                "visual_name": "(semua visual)",
                "visual_id": "",
                "field_kind": kind,
                "table": table,
                "field": field,
                "filter_type": flt.get("type", ""),
                "values": "; ".join(values),
                "how_created": flt.get("howCreated", ""),
                "hidden_in_view_mode": bool(flt.get("isHiddenInViewMode", False)),
                "locked_in_view_mode": bool(flt.get("isLockedInViewMode", False)),
                "has_filter_definition": bool(flt.get("filter")),
                "ordinal": ordinal,
            }
        )

    for order, page_id in enumerate(page_order, start=1):
        page_dir = report_def / "pages" / page_id
        page_json = read_json(page_dir / "page.json")
        page_name = page_json.get("displayName") or page_id
        page_lookup[page_id] = page_name

        page_filters = (page_json.get("filterConfig") or {}).get("filters", [])
        for ordinal, flt in enumerate(page_filters):
            kind, table, field = parse_filter_field(flt)
            values = collect_filter_values(flt.get("filter"))
            filter_rows.append(
                {
                    "scope": "Page",
                    "page_order": order,
                    "page_name": page_name,
                    "page_id": page_id,
                    "visual_name": "(semua visual di halaman)",
                    "visual_id": "",
                    "field_kind": kind,
                    "table": table,
                    "field": field,
                    "filter_type": flt.get("type", ""),
                    "values": "; ".join(values),
                    "how_created": flt.get("howCreated", ""),
                    "hidden_in_view_mode": bool(flt.get("isHiddenInViewMode", False)),
                    "locked_in_view_mode": bool(flt.get("isLockedInViewMode", False)),
                    "has_filter_definition": bool(flt.get("filter")),
                    "ordinal": ordinal,
                }
            )

        visual_dirs = sorted(
            [p for p in (page_dir / "visuals").iterdir() if p.is_dir()]
        )
        group_names: dict[str, str] = {}
        group_hidden: dict[str, bool] = {}
        group_parent: dict[str, str] = {}
        group_position: dict[str, dict[str, Any]] = {}
        parsed_visuals: list[tuple[Path, dict[str, Any]]] = []

        for vdir in visual_dirs:
            vjson = read_json(vdir / "visual.json")
            if "visualGroup" in vjson:
                group_id = vjson.get("name", vdir.name)
                group_names[group_id] = (vjson.get("visualGroup") or {}).get(
                    "displayName", vdir.name
                )
                group_hidden[group_id] = bool(vjson.get("isHidden", False))
                group_parent[group_id] = str(vjson.get("parentGroupName") or "")
                group_position[group_id] = vjson.get("position") or {}
                visual_lookup[group_id] = {
                    "page_name": page_name,
                    "page_id": page_id,
                    "visual_name": group_names[group_id],
                    "visual_type": "visualGroup",
                }
            elif "visual" in vjson:
                parsed_visuals.append((vdir, vjson))

        def group_is_hidden(group_id: str) -> bool:
            """Group induk yang disembunyikan ikut menyembunyikan isinya."""
            seen: set[str] = set()
            current = group_id
            while current and current not in seen:
                seen.add(current)
                if group_hidden.get(current):
                    return True
                current = group_parent.get(current, "")
            return False

        def absolute_position(
            position: Mapping[str, Any] | None,
            group_id: str,
        ) -> tuple[float, float]:
            """Posisi absolut visual terhadap halaman.

            PBIR menyimpan posisi visual di dalam group relatif terhadap group
            tersebut, sedangkan embed API (dan screenshot DOM) memakai koordinat
            absolut. Jumlahkan posisi seluruh group induk agar posisi bisa
            dipakai untuk mencocokkan elemen DOM saat capture.
            """
            x = float((position or {}).get("x", 0) or 0)
            y = float((position or {}).get("y", 0) or 0)
            seen: set[str] = set()
            current = group_id
            while current and current not in seen:
                seen.add(current)
                parent = group_position.get(current) or {}
                x += float(parent.get("x", 0) or 0)
                y += float(parent.get("y", 0) or 0)
                current = group_parent.get(current, "")
            return x, y

        real_visual_count = 0
        for vdir, vjson in parsed_visuals:
            real_visual_count += 1
            visual = vjson.get("visual") or {}
            visual_id = vjson.get("name") or vdir.name
            visual_type = visual.get("visualType", "")
            title, title_source = visual_title(visual, visual_id)
            visual_lookup[visual_id] = {
                "page_name": page_name,
                "page_id": page_id,
                "visual_name": title,
                "visual_type": visual_type,
            }
            position = vjson.get("position") or {}
            parent_id = vjson.get("parentGroupName") or ""
            parent_name = group_names.get(parent_id, parent_id)

            query = visual.get("query") or {}
            query_state = query.get("queryState") or {}

            # sort lookup by queryRef
            sort_map: dict[str, str] = {}
            for sort_item in (query.get("sortDefinition") or {}).get("sort", []):
                ref = sort_item.get("queryRef")
                if not ref:
                    info = parse_field(sort_item.get("field") or {})
                    ref = f"{info['table']}.{info['field']}" if info["table"] else info["field"]
                sort_map[ref] = sort_item.get("direction", "")

            visual_field_refs: list[str] = []
            visual_field_count = 0
            roles_used: list[str] = []

            for role, role_content in query_state.items():
                projections = (role_content or {}).get("projections") or []
                if not projections:
                    continue
                roles_used.append(role)
                for proj in projections:
                    info = parse_field(proj.get("field") or {})
                    native_ref = proj.get("nativeQueryRef", "") or info["field"]
                    if info["field_kind"] == "VisualCalculation":
                        query_ref = info["field"] or native_ref
                    else:
                        query_ref = proj.get("queryRef") or (
                            f"{info['table']}.{info['field']}"
                            if info["table"]
                            else info["field"]
                        )
                        if "." in query_ref and (not info["table"] or not info["field"]):
                            ref_table, ref_field = query_ref.split(".", 1)
                            info["table"] = info["table"] or ref_table
                            info["field"] = info["field"] or ref_field
                    display_name = (
                        proj.get("displayName", "")
                        or native_ref
                        or info["field"]
                    )
                    visual_field_refs.append(f"{role}: {query_ref}")
                    visual_field_count += 1
                    field_rows.append(
                        {
                            "page_order": order,
                            "page_name": page_name,
                            "page_id": page_id,
                            "visual_name": title,
                            "visual_name_source": title_source,
                            "visual_id": visual_id,
                            "visual_type": visual_type,
                            "parent_group": parent_name,
                            "field_role": role,
                            "field_kind": info["field_kind"],
                            "table": info["table"],
                            "field": info["field"],
                            "query_ref": query_ref,
                            "display_name": display_name,
                            "native_query_ref": native_ref,
                            "aggregation": info["aggregation"],
                            "expression": info["expression"],
                            "sort_direction": sort_map.get(query_ref, ""),
                            "position_x": round(float(position.get("x", 0)), 2),
                            "position_y": round(float(position.get("y", 0)), 2),
                            "width": round(float(position.get("width", 0)), 2),
                            "height": round(float(position.get("height", 0)), 2),
                        }
                    )

            # visual-level filters
            for ordinal, flt in enumerate((vjson.get("filterConfig") or {}).get("filters", [])):
                kind, table, field = parse_filter_field(flt)
                values = collect_filter_values(flt.get("filter"))
                filter_rows.append(
                    {
                        "scope": "Visual",
                        "page_order": order,
                        "page_name": page_name,
                        "page_id": page_id,
                        "visual_name": title,
                        "visual_id": visual_id,
                        "field_kind": kind,
                        "table": table,
                        "field": field,
                        "filter_type": flt.get("type", ""),
                        "values": "; ".join(values),
                        "how_created": flt.get("howCreated", ""),
                        "hidden_in_view_mode": bool(flt.get("isHiddenInViewMode", False)),
                        "locked_in_view_mode": bool(flt.get("isLockedInViewMode", False)),
                        "has_filter_definition": bool(flt.get("filter")),
                        "ordinal": ordinal,
                    }
                )

            # slicer details
            if visual_type == "slicer":
                mode = object_property(visual, "data", "mode")
                start_date = object_property(visual, "data", "startDate")
                end_date = object_property(visual, "data", "endDate")
                single_select = object_property(visual, "selection", "singleSelect")
                select_all = object_property(visual, "selection", "selectAllCheckboxEnabled")
                slicer_values = collect_filter_values(
                    (vjson.get("filterConfig") or {}).get("filters", [])
                )
                if start_date or end_date:
                    slicer_values.extend(
                        [v for v in [clean_literal(start_date), clean_literal(end_date)] if v]
                    )

                slicer_fields = [
                    row
                    for row in field_rows
                    if row["page_id"] == page_id and row["visual_id"] == visual_id
                ]
                if not slicer_fields:
                    slicer_rows.append(
                        {
                            "page_order": order,
                            "page_name": page_name,
                            "page_id": page_id,
                            "slicer_name": title,
                            "visual_id": visual_id,
                            "table": "",
                            "column": "",
                            "field_kind": "",
                            "slicer_mode": clean_literal(mode) if mode else "",
                            "single_select": clean_literal(single_select) if single_select is not None else "",
                            "select_all_enabled": clean_literal(select_all) if select_all is not None else "",
                            "active_filter_values": "; ".join(slicer_values),
                        }
                    )
                for row in slicer_fields:
                    slicer_rows.append(
                        {
                            "page_order": order,
                            "page_name": page_name,
                            "page_id": page_id,
                            "slicer_name": title,
                            "visual_id": visual_id,
                            "table": row["table"],
                            "column": row["field"],
                            "field_kind": row["field_kind"],
                            "slicer_mode": clean_literal(mode) if mode else "",
                            "single_select": clean_literal(single_select) if single_select is not None else "",
                            "select_all_enabled": clean_literal(select_all) if select_all is not None else "",
                            "active_filter_values": "; ".join(slicer_values),
                        }
                    )

            # action / navigation button
            action = ""
            visual_link = ((visual.get("visualContainerObjects") or {}).get("visualLink") or [])
            for entry in visual_link:
                props = entry.get("properties") or {}
                link_type = clean_literal(literal_from_expr(props.get("type")))
                target = clean_literal(literal_from_expr(props.get("target")))
                if link_type or target:
                    action = f"{link_type} {target}".strip()
            if not action and visual.get("link"):
                action = json.dumps(visual.get("link"), ensure_ascii=False)

            abs_x, abs_y = absolute_position(position, parent_id)
            visual_rows.append(
                {
                    "page_order": order,
                    "page_name": page_name,
                    "page_id": page_id,
                    "visual_name": title,
                    "visual_name_source": title_source,
                    "visual_id": visual_id,
                    "visual_type": visual_type,
                    "parent_group": parent_name,
                    "is_hidden": bool(vjson.get("isHidden", False))
                    or group_is_hidden(parent_id),
                    "field_count": visual_field_count,
                    "roles_used": ", ".join(roles_used),
                    "fields": " | ".join(visual_field_refs),
                    "filter_count": len((vjson.get("filterConfig") or {}).get("filters", [])),
                    "action_link": action,
                    "position_x": round(float(position.get("x", 0)), 2),
                    "position_y": round(float(position.get("y", 0)), 2),
                    "position_x_abs": round(abs_x, 2),
                    "position_y_abs": round(abs_y, 2),
                    "width": round(float(position.get("width", 0)), 2),
                    "height": round(float(position.get("height", 0)), 2),
                }
            )

        for interaction_order, interaction in enumerate(
            page_json.get("visualInteractions") or [], start=1
        ):
            source_id = str(interaction.get("source", ""))
            target_id = str(interaction.get("target", ""))
            raw_type = interaction.get("type", "")
            type_label, is_default = INTERACTION_TYPES.get(
                raw_type, (raw_type or "(tidak diketahui)", False)
            )
            source_info = resolve_visual(source_id, visual_lookup)
            target_info = resolve_visual(target_id, visual_lookup)
            if raw_type == "DataFilter":
                note = "Default Power BI: visual target ikut terfilter."
            elif raw_type == "NoFilter":
                note = "Interaksi dimatikan: visual target tidak terfilter."
            elif raw_type == "HighlightFilter":
                note = "Cross-highlight antar visual."
            else:
                note = ""

            interaction_rows.append(
                {
                    "page_order": order,
                    "page_name": page_name,
                    "page_id": page_id,
                    "interaction_order": interaction_order,
                    "source_visual_id": source_id,
                    "source_visual_name": source_info["visual_name"],
                    "source_visual_type": source_info["visual_type"],
                    "target_visual_id": target_id,
                    "target_visual_name": target_info["visual_name"],
                    "target_visual_type": target_info["visual_type"],
                    "interaction_type": raw_type,
                    "interaction_label": type_label,
                    "is_default": is_default,
                    "note": note,
                }
            )

        page_rows.append(
            {
                "page_order": order,
                "page_name": page_name,
                "page_id": page_id,
                "display_option": page_json.get("displayOption", ""),
                "is_hidden": page_is_hidden(page_json),
                "width": page_json.get("width", ""),
                "height": page_json.get("height", ""),
                "visual_count": real_visual_count,
                "group_count": len(group_names),
                "page_filter_count": len(page_filters),
                "visual_interaction_count": len(page_json.get("visualInteractions", [])),
                "is_active_page": page_id == active_page,
            }
        )

    return (
        page_rows,
        field_rows,
        slicer_rows,
        filter_rows,
        visual_rows,
        interaction_rows,
        visual_lookup,
        page_lookup,
    )


# ----------------------------------------------------------------------------
# Usage & validation
# ----------------------------------------------------------------------------
def inventory_from_fields(field_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turunkan daftar objek model dari field report saat inventory tidak tersedia."""
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in field_rows:
        kind = row["field_kind"]
        name = row["field"]
        if kind not in {"Column", "Measure", "Aggregation"} or not name:
            continue
        object_type = "Measure" if kind == "Measure" else "Column"
        key = (row["table"], object_type, name)
        seen.setdefault(
            key,
            {
                "table": row["table"],
                "object_type": object_type,
                "name": name,
                "is_hidden": "",
            },
        )
    return list(seen.values())


def build_usage(field_rows: list[dict[str, Any]], inventory: list[dict[str, Any]]):
    measure_rows: list[dict[str, Any]] = []
    column_rows: list[dict[str, Any]] = []

    if not inventory:
        inventory = inventory_from_fields(field_rows)

    for item in inventory:
        table = item["table"]
        name = item["name"]
        if item["object_type"] == "Measure":
            matches = [
                row
                for row in field_rows
                if row["field_kind"] == "Measure" and row["field"] == name
            ]
            target = measure_rows
            key = {"measure": name}
        else:
            matches = [
                row
                for row in field_rows
                if row["field_kind"] in {"Column", "Aggregation"}
                and row["table"] == table
                and row["field"] == name
            ]
            target = column_rows
            key = {"table": table, "column": name}

        pages = sorted({(row["page_order"], row["page_name"]) for row in matches})
        visuals = sorted({(row["page_name"], row["visual_name"]) for row in matches})
        target.append(
            {
                **key,
                "is_hidden": item["is_hidden"],
                "visual_usage_count": len({(r["page_id"], r["visual_id"]) for r in matches}),
                "page_usage_count": len(pages),
                "pages": " | ".join(f"{o}. {n}" for o, n in pages),
                "visuals": " | ".join(f"{p} > {v}" for p, v in visuals),
                "roles_used": ", ".join(sorted({r["field_role"] for r in matches})),
            }
        )

    return measure_rows, column_rows


def validate(field_rows: list[dict[str, Any]], tables) -> list[dict[str, Any]]:
    all_measures = {
        name
        for content in tables.values()
        for name in content["measures"]
    }
    model_available = bool(tables)

    rows: list[dict[str, Any]] = []
    for row in field_rows:
        status = "OK"
        note = ""
        if not model_available:
            status = "TIDAK DIVALIDASI"
            note = (
                "Metadata model tidak tersedia. Jalankan dengan --model-workbook "
                "Semantic_Model_Metadata.xlsx untuk validasi penuh."
            )
        elif row["field_kind"] == "Measure":
            if row["field"] not in all_measures:
                status = "TIDAK ADA DI MODEL"
            elif tables.get(row["table"], {}).get("measures", {}).get(row["field"], {}).get("hidden"):
                status = "MEASURE HIDDEN"
        elif row["field_kind"] in {"Column", "Aggregation"}:
            if row["table"] not in tables:
                status = "TABEL TIDAK ADA"
            elif row["field"] not in tables[row["table"]]["columns"]:
                status = "TIDAK ADA DI MODEL"
            elif tables[row["table"]]["columns"][row["field"]]["hidden"]:
                status = "KOLOM HIDDEN"
        elif row["field_kind"] == "VisualCalculation":
            note = "Visual calculation; tidak divalidasi terhadap model"
        else:
            note = "Tipe field tidak divalidasi"

        rows.append(
            {
                "status": status,
                "page_name": row["page_name"],
                "visual_name": row["visual_name"],
                "visual_type": row["visual_type"],
                "visual_id": row["visual_id"],
                "field_role": row["field_role"],
                "field_kind": row["field_kind"],
                "table": row["table"],
                "field": row["field"],
                "query_ref": row["query_ref"],
                "note": note,
            }
        )
    return rows


# ----------------------------------------------------------------------------
# Excel writer
# ----------------------------------------------------------------------------
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
STATUS_FILLS = {
    "OK": PatternFill("solid", fgColor="E2EFDA"),
    "MEASURE HIDDEN": PatternFill("solid", fgColor="FFF2CC"),
    "KOLOM HIDDEN": PatternFill("solid", fgColor="FFF2CC"),
    "TIDAK ADA DI MODEL": PatternFill("solid", fgColor="F8CBAD"),
    "TABEL TIDAK ADA": PatternFill("solid", fgColor="F8CBAD"),
    "TIDAK DIVALIDASI": PatternFill("solid", fgColor="D9E1F2"),
}


def write_sheet(writer, df: pd.DataFrame, sheet: str, width_map: dict[str, int] | None = None):
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
            longest = max([len(column)] + [min(len(v), 60) for v in sample]) if len(df) else len(column)
            width = min(max(longest + 2, 10), 70)
        ws.column_dimensions[get_column_letter(idx)].width = width

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(df.columns)):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=False)
            cell.border = BORDER


def run_report(
    report_def: Path,
    report_source: str,
    tables: dict[str, dict[str, dict[str, bool]]],
    inventory: list[dict[str, Any]],
    model_source: str,
    out_file: Path,
    report_kind: str = "",
    log: Callable[[str], None] = _silent,
) -> dict[str, Any]:
    (
        page_rows,
        field_rows,
        slicer_rows,
        filter_rows,
        visual_rows,
        interaction_rows,
        visual_lookup,
        page_lookup,
    ) = extract_report(report_def)
    bookmark_rows = extract_bookmarks(visual_lookup, page_lookup, report_def)
    sync_slicer_rows = extract_sync_slicers(report_def)
    measure_usage, column_usage = build_usage(field_rows, inventory)
    validation_rows = validate(field_rows, tables)

    pages_df = pd.DataFrame(page_rows)
    fields_df = pd.DataFrame(field_rows)
    slicers_df = pd.DataFrame(slicer_rows)
    filters_df = pd.DataFrame(filter_rows)
    visuals_df = pd.DataFrame(visual_rows)
    measures_df = pd.DataFrame(measure_usage)
    columns_df = pd.DataFrame(column_usage)
    validation_df = pd.DataFrame(validation_rows)
    inventory_df = pd.DataFrame(inventory)
    bookmarks_df = pd.DataFrame(bookmark_rows)
    interactions_df = pd.DataFrame(interaction_rows)
    sync_slicers_df = pd.DataFrame(sync_slicer_rows)

    # urutkan validasi: masalah dulu
    if not validation_df.empty:
        priority = {
            "TIDAK ADA DI MODEL": 0,
            "TABEL TIDAK ADA": 0,
            "MEASURE HIDDEN": 1,
            "KOLOM HIDDEN": 1,
            "OK": 2,
        }
        validation_df["_p"] = validation_df["status"].map(priority).fillna(3)
        validation_df = validation_df.sort_values(
            ["_p", "page_name", "visual_name", "field_role"], kind="stable"
        ).drop(columns="_p")

    readme_rows = [
        ("Tujuan", "Metadata seluruh visual & slicer pada report PBIR, dipisah per halaman."),
        ("Sumber report", report_source),
        ("Sumber model", model_source),
        ("01_Pages", "Daftar halaman sesuai urutan report, jumlah visual & filter halaman."),
        ("02_Bookmarks", "Bookmark beserta halaman target, visual target, filter, dan visual yang disembunyikan. Jika tidak ada folder definition/bookmarks, sheet berisi 1 baris catatan."),
        ("03_Interactions", "Interaksi antar visual per halaman (Edit interactions): sumber, target, dan tipe interaksi."),
        ("04_Visual_Fields", "INTI: 1 baris = 1 field pada 1 visual. Berisi nama page + nama visual + role field. Kolom aggregation diisi fungsi agregasi visual (Sum, Average, Distinct count, Min, Max, Count, Median, Standard deviation, Variance); kolom expression berisi DAX visual calculation."),
        ("05_Slicers", "Slicer per halaman: kolom yang dipakai, mode, dan nilai filter aktif."),
        ("06_Sync_Slicers", "Slicer yang sync antar halaman (syncGroup): nama grup, kolom, halaman lain dalam grup, dan status sync field/filter."),
        ("07_Filters", "Filter level Report, Page, dan Visual beserta nilainya."),
        ("08_Visual_Summary", "Ringkasan 1 baris per visual: daftar field, jumlah filter, aksi tombol."),
        ("09_Usage_Measures", "Semua measure model + jumlah pemakaian (termasuk yang 0 pemakaian)."),
        ("10_Usage_Columns", "Semua kolom model + jumlah pemakaian (termasuk yang 0 pemakaian)."),
        ("11_Validation", "Cek setiap field report terhadap model. Status TIDAK DIVALIDASI berarti metadata model tidak tersedia. Masalah diurutkan paling atas."),
        ("12_Model_Inventory", "Inventaris tabel/kolom/measure model beserta status hidden."),
        ("Catatan usage", "Jumlah pemakaian = pemakaian LANGSUNG oleh visual. Measure yang dipakai measure lain bisa tampil 0."),
        ("Catatan filter", "has_filter_definition=False berarti kartu filter ada di pane tapi tanpa definisi/nilai (tidak memfilter)."),
        ("Catatan action_link", "Hanya menampilkan tipe aksi dan target objek (mis. Bookmark). Detail state bookmark ada di sheet 02_Bookmarks."),
        ("Catatan interaction", "interaction_type DataFilter = default Power BI (target terfilter); NoFilter = interaksi dimatikan; HighlightFilter = cross-highlight."),
        ("Catatan agregasi visual", "field_kind=Aggregation berarti kolom dipakai dengan fungsi agregasi eksplisit pada visual; fungsi aslinya ada di kolom aggregation (Function PBIR: 0=Sum, 1=Average, 2=Distinct count, 3=Min, 4=Max, 5=Count, 6=Median, 7=Standard deviation, 8=Variance)."),
        ("Catatan visual calculation", "field_kind=VisualCalculation berasal dari NativeVisualCalculation; nama ada di kolom field, DAX ada di kolom expression, dan query_ref memakai nama visual calculation (bukan 'select')."),
        ("Catatan sync slicer", "Sync dibaca dari visual.syncGroup pada visual.json: groupName sama = satu grup sync; field_changes = sync saat kolom berubah; filter_changes = sync saat seleksi berubah. group_pages berisi halaman lain dalam grup yang sama; baris tanpa anggota lain diberi catatan."),
        ("Catatan bookmark", "Bookmark disimpan PBIR di definition/bookmarks/<name>.bookmark.json; urutan & grup di bookmarks.json."),
        ("Catatan sumber report", "Report dibaca langsung dari Report/definition di dalam file .pbix (PBIR GA). File .pbix legacy yang masih memakai Report/Layout tidak didukung; simpan ulang dari Power BI Desktop."),
        ("Catatan validasi model", "Validasi field memakai workbook Semantic_Model_Metadata.xlsx (--model-workbook), atau dilewati dengan --no-model."),
        ("Catatan nama visual", "Jika visual tidak punya judul, dipakai fallback '(untitled) <type> <id>'."),
        ("Catatan kolom", "page_id & visual_id selalu diisi agar visual bernama sama tidak tertukar."),
        ("Dibuat", pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    if report_kind:
        readme_rows.insert(2, ("Jenis report", report_kind))
    readme_df = pd.DataFrame(readme_rows, columns=["Bagian", "Penjelasan"])

    with pd.ExcelWriter(out_file, engine="openpyxl") as writer:
        write_sheet(writer, readme_df, "00_README", {"Bagian": 24, "Penjelasan": 95})
        write_sheet(writer, pages_df, "01_Pages")
        write_sheet(
            writer,
            bookmarks_df,
            "02_Bookmarks",
            {
                "status": 22,
                "bookmark_name": 30,
                "display_name": 34,
                "group_name": 24,
                "group_display_name": 28,
                "page_name": 30,
                "target_visuals": 80,
                "filters": 80,
                "hidden_visuals": 50,
                "source_file": 60,
                "note": 70,
            },
        )
        write_sheet(
            writer,
            interactions_df,
            "03_Interactions",
            {
                "page_name": 30,
                "source_visual_name": 42,
                "source_visual_type": 28,
                "target_visual_name": 42,
                "target_visual_type": 28,
                "interaction_type": 20,
                "interaction_label": 20,
                "note": 55,
            },
        )
        write_sheet(
            writer,
            fields_df,
            "04_Visual_Fields",
            {
                "page_name": 30,
                "visual_name": 42,
                "visual_type": 30,
                "field_role": 14,
                "table": 34,
                "field": 46,
                "query_ref": 52,
                "display_name": 30,
                "native_query_ref": 30,
                "aggregation": 18,
                "expression": 70,
                "parent_group": 26,
            },
        )
        write_sheet(
            writer,
            slicers_df,
            "05_Slicers",
            {
                "page_name": 30,
                "slicer_name": 38,
                "table": 32,
                "column": 46,
                "active_filter_values": 45,
            },
        )
        write_sheet(
            writer,
            sync_slicers_df,
            "06_Sync_Slicers",
            {
                "sync_group": 30,
                "page_name": 30,
                "slicer_name": 38,
                "table": 32,
                "column": 46,
                "group_pages": 70,
                "note": 70,
            },
        )
        write_sheet(
            writer,
            filters_df,
            "07_Filters",
            {
                "page_name": 30,
                "visual_name": 42,
                "table": 32,
                "field": 46,
                "values": 50,
            },
        )
        write_sheet(
            writer,
            visuals_df,
            "08_Visual_Summary",
            {
                "page_name": 30,
                "visual_name": 42,
                "visual_type": 30,
                "fields": 90,
                "roles_used": 30,
                "action_link": 30,
                "parent_group": 26,
                "is_hidden": 12,
                "position_x_abs": 14,
                "position_y_abs": 14,
            },
        )
        write_sheet(
            writer,
            measures_df,
            "09_Usage_Measures",
            {"measure": 46, "pages": 45, "visuals": 80, "roles_used": 30},
        )
        write_sheet(
            writer,
            columns_df,
            "10_Usage_Columns",
            {"table": 34, "column": 46, "pages": 45, "visuals": 80, "roles_used": 30},
        )
        write_sheet(
            writer,
            validation_df,
            "11_Validation",
            {
                "status": 22,
                "page_name": 30,
                "visual_name": 42,
                "visual_type": 30,
                "field_role": 14,
                "table": 34,
                "field": 46,
                "query_ref": 52,
            },
        )
        write_sheet(
            writer,
            inventory_df,
            "12_Model_Inventory",
            {"table": 34, "object_type": 14, "name": 50},
        )

        # warna status di sheet validasi
        ws = writer.sheets["11_Validation"]
        if "status" in validation_df.columns:
            status_col = list(validation_df.columns).index("status") + 1
            for row_idx in range(2, ws.max_row + 1):
                cell = ws.cell(row=row_idx, column=status_col)
                fill = STATUS_FILLS.get(str(cell.value))
                if fill:
                    cell.fill = fill
                    cell.font = Font(bold=True)

        # sorot baris catatan jika report tidak punya bookmark
        ws = writer.sheets["02_Bookmarks"]
        status_col = list(bookmarks_df.columns).index("status") + 1
        for row_idx in range(2, ws.max_row + 1):
            cell = ws.cell(row=row_idx, column=status_col)
            if str(cell.value) == "TIDAK ADA BOOKMARK":
                cell.fill = PatternFill("solid", fgColor="FFF2CC")
                cell.font = Font(bold=True)

    if validation_df.empty:
        validation_issues = 0
        validation_skipped = 0
    else:
        status_values = validation_df["status"].astype(str)
        validation_issues = int((~status_values.isin(["OK", "TIDAK DIVALIDASI"])).sum())
        validation_skipped = int((status_values == "TIDAK DIVALIDASI").sum())

    # baris catatan "TIDAK ADA SYNC SLICER" tidak dihitung sebagai slicer sync
    sync_slicer_count = int(
        (sync_slicers_df["sync_group"].astype(str) != "").sum()
        if not sync_slicers_df.empty
        else 0
    )

    log(f"OK  -> {out_file}")
    log(f"Sumber report    : {report_source}")
    log(f"Sumber model     : {model_source}")
    log(f"Pages            : {len(pages_df)}")
    log(f"Visual (real)    : {len(visuals_df)}")
    log(f"Visual groups    : {int(pages_df['group_count'].sum()) if not pages_df.empty else 0}")
    log(f"Field rows       : {len(fields_df)}")
    log(f"Slicers          : {len(slicers_df)}")
    log(f"Sync slicers     : {sync_slicer_count}")
    log(f"Filters          : {len(filters_df)}")
    log(f"Bookmarks        : {len(bookmarks_df) if bookmarks_df['status'].iloc[0] == 'OK' else 0}")
    log(f"Interactions     : {len(interactions_df)}")
    log(f"Measures in model: {len(measures_df)}")
    log(f"Columns in model : {len(columns_df)}")
    if validation_skipped and not validation_issues:
        log(f"Validation       : dilewati ({validation_skipped} field TIDAK DIVALIDASI)")
    else:
        log(f"Validation issues: {validation_issues}")
        if validation_skipped:
            log(f"  tidak divalidasi : {validation_skipped} field")
    return {
        "out_file": out_file,
        "pages": len(pages_df),
        "visuals": len(visuals_df),
        "fields": len(fields_df),
        "slicers": len(slicers_df),
        "sync_slicers": sync_slicer_count,
        "filters": len(filters_df),
        "bookmarks": len(bookmarks_df) if bookmarks_df["status"].iloc[0] == "OK" else 0,
        "interactions": len(interactions_df),
        "measures": len(measures_df),
        "columns": len(columns_df),
        "validation_issues": validation_issues,
        "validation_skipped": validation_skipped,
    }


def find_validation_workbook(search_dir: Path | None = None) -> Path | None:
    """Cari workbook model untuk validasi: folder output, outputs, lalu folder aplikasi."""
    candidates: list[Path] = []
    if search_dir is not None:
        candidates.append(Path(search_dir) / MODEL_WORKBOOK_NAME)
    candidates.append(OUT_DIR / MODEL_WORKBOOK_NAME)
    candidates.append(APP_DIR / MODEL_WORKBOOK_NAME)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def validation_workbook_label(path: Path) -> str:
    """Deskripsi workbook validasi beserta waktu modifikasi agar usang terlihat."""
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return f"workbook {display_path(path)}"
    return f"workbook {display_path(path)} ({stamp})"


def resolve_validation_model(
    no_model: bool,
    workbook: Path | None,
    search_dir: Path | None = None,
) -> tuple[dict[str, dict[str, dict[str, bool]]], list[dict[str, Any]], str]:
    """Pilih sumber validasi model: workbook eksplisit -> folder output -> tooling -> dilewati."""
    if no_model:
        return {}, [], "tidak dipakai (validasi dimatikan): validasi field dilewati"

    if workbook is not None:
        tables, inventory = load_model_inventory_from_workbook(workbook)
        return tables, inventory, validation_workbook_label(workbook)

    found = find_validation_workbook(search_dir)
    if found is not None:
        tables, inventory = load_model_inventory_from_workbook(found)
        return tables, inventory, validation_workbook_label(found)

    return (
        {},
        [],
        "tidak tersedia: validasi field dilewati (pilih workbook model untuk validasi penuh)",
    )
