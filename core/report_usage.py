"""Pemakaian field di definisi report Power BI Service (PBIR dan PBIR-Legacy).

Scanner ini membaca ``ReportDefinition.parts`` di memori, jadi tidak butuh
folder hasil materialisasi. Format PBIR-Legacy diterima di sini walaupun
ekstraksi report menolaknya: analisa kolom butuh pemakaian dari report lama,
dan membaca ``report.json`` tidak mengubah jalur ekstraksi.

Yang dicatat sebagai pemakaian:

- proyeksi visual (``queryState`` PBIR / ``projections`` + ``prototypeQuery`` legacy),
- filter level report, halaman, dan visual,
- pengurutan (``sortDefinition``/``OrderBy``),
- ekspresi formatting (``objects``/``vcObjects``/``visualContainerObjects``),
- visual calculation (PBIR) beserta kolom model yang dirujuk ekspresinya.

Tidak ada akses jaringan dan tidak ada tulis file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from .fabric_api import PBIR, PBIR_LEGACY, ReportDefinition
from .metadata_common import (
    AGGREGATED_QUERY_REF,
    QUERY_AGGREGATE_FUNCTION,
    find_dax_refs,
)
from .report import collect_filter_values, page_is_hidden, parse_field

Log = Callable[[str], None]

USAGE_FIELD = "field"
USAGE_FILTER_REPORT = "filter-report"
USAGE_FILTER_PAGE = "filter-page"
USAGE_FILTER_VISUAL = "filter-visual"
USAGE_QUERY_FILTER = "filter-query"
USAGE_SORT = "sort"
USAGE_FORMAT = "format"
USAGE_CALCULATION = "calculation"

USAGE_LABELS = {
    USAGE_FIELD: "Field visual",
    USAGE_FILTER_REPORT: "Filter report",
    USAGE_FILTER_PAGE: "Filter halaman",
    USAGE_FILTER_VISUAL: "Filter visual",
    USAGE_QUERY_FILTER: "Filter query visual",
    USAGE_SORT: "Sort",
    USAGE_FORMAT: "Formatting",
    USAGE_CALCULATION: "Visual calculation",
}

_EXPRESSION_KINDS = ("Column", "Measure", "Aggregation")


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


# ---------------------------------------------------------------------------
# Hasil
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class UsageRecord:
    """Satu titik pemakaian field pada report."""

    usage_kind: str
    field_kind: str
    table: str
    field: str
    page_id: str = ""
    page_name: str = ""
    visual_id: str = ""
    visual_type: str = ""
    visual_title: str = ""
    aggregation: str = ""
    detail: str = ""
    is_hidden: bool = False

    @property
    def usage_label(self) -> str:
        return USAGE_LABELS.get(self.usage_kind, self.usage_kind)

    @property
    def column_key(self) -> tuple[str, str]:
        return (self.table.casefold(), self.field.casefold())


@dataclass
class ReportUsage:
    """Hasil scan satu report."""

    report_format: str
    pages: int = 0
    visuals: int = 0
    records: list[UsageRecord] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    unresolved_rows: list[dict[str, str]] = field(default_factory=list)
    theme: str = ""
    page_rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def columns(self) -> dict[tuple[str, str], list[UsageRecord]]:
        grouped: dict[tuple[str, str], list[UsageRecord]] = {}
        for record in self.records:
            if record.field_kind in {"Column", "Aggregation", "Field"} and record.field:
                grouped.setdefault(record.column_key, []).append(record)
        return grouped


class _Parts:
    """Pembaca JSON dari parts getDefinition (tanpa menulis disk)."""

    def __init__(self, parts: Mapping[str, bytes]) -> None:
        self.parts = parts
        self._cache: dict[str, Any] = {}

    def has(self, path: str) -> bool:
        return path in self.parts

    def json(self, path: str) -> Any:
        if path in self._cache:
            return self._cache[path]
        payload = self.parts.get(path)
        if payload is None:
            return {}
        try:
            data = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = {}
        self._cache[path] = data
        return data

    def paths(self, prefix: str, suffix: str = "") -> list[str]:
        return sorted(
            path
            for path in self.parts
            if path.startswith(prefix) and path.endswith(suffix)
        )


def _loads(value: Any) -> Any:
    """Legacy menyimpan banyak blok sebagai string JSON."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {}
    return value


def _shorten(text: str, limit: int = 120) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _aggregation(node: dict[str, Any]) -> str:
    try:
        function = int(node.get("Function"))
    except (TypeError, ValueError):
        return ""
    return QUERY_AGGREGATE_FUNCTION.get(function, "")


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------
class _Collector:
    def __init__(self) -> None:
        self.records: list[UsageRecord] = []
        self.unresolved: list[str] = []
        self.unresolved_rows: list[dict[str, str]] = []
        self.pages = 0
        self.visuals = 0
        self.theme = ""
        self.page_rows: list[dict[str, Any]] = []
        self._seen_format: set[tuple] = set()
        self._seen_field: set[tuple] = set()
        self._seen_filter: set[tuple] = set()

    def add(
        self,
        usage_kind: str,
        *,
        field_kind: str,
        table: str,
        field: str,
        page_id: str = "",
        page_name: str = "",
        visual_id: str = "",
        visual_type: str = "",
        visual_title: str = "",
        aggregation: str = "",
        detail: str = "",
        is_hidden: bool = False,
    ) -> None:
        if not field:
            return
        record = UsageRecord(
            usage_kind=usage_kind,
            field_kind=field_kind,
            table=str(table or ""),
            field=str(field),
            page_id=page_id,
            page_name=page_name,
            visual_id=visual_id,
            visual_type=visual_type,
            visual_title=visual_title,
            aggregation=aggregation,
            detail=_shorten(detail),
            is_hidden=is_hidden,
        )
        if usage_kind == USAGE_FIELD:
            field_key = (
                record.table.casefold(),
                record.field.casefold(),
                page_id,
                visual_id,
            )
            if field_key in self._seen_field:
                return
            self._seen_field.add(field_key)
        if usage_kind in {USAGE_FILTER_REPORT, USAGE_FILTER_PAGE, USAGE_FILTER_VISUAL}:
            filter_key = (
                usage_kind,
                record.table.casefold(),
                record.field.casefold(),
                page_id,
                visual_id,
            )
            if filter_key in self._seen_filter:
                return
            self._seen_filter.add(filter_key)
        if usage_kind == USAGE_FORMAT:
            key = (
                usage_kind,
                record.table.casefold(),
                record.field.casefold(),
                page_id,
                visual_id,
                record.detail,
            )
            if key in self._seen_format:
                return
            self._seen_format.add(key)
        self.records.append(record)

    def finish(self) -> None:
        """Buang format ganda pada visual yang sudah memakai field itu.

        Measure Killer menghitung setiap referensi formatting, tetapi tidak
        menambah hitungan bila field yang sama sudah menjadi field visual.
        """
        visual_fields = {
            (record.table.casefold(), record.field.casefold())
            for record in self.records
            if record.usage_kind == USAGE_FIELD
        }
        if not visual_fields:
            return
        measure_fields = {
            record.field.casefold()
            for record in self.records
            if record.usage_kind == USAGE_FIELD
            and record.field_kind == "Measure"
        }
        self.records = [
            record
            for record in self.records
            if not (
                record.usage_kind == USAGE_FORMAT
                and (
                    (record.table.casefold(), record.field.casefold())
                    in visual_fields
                    or (
                        record.field_kind == "Measure"
                        and record.field.casefold() in measure_fields
                    )
                )
            )
        ]

    def add_field(
        self,
        info: dict[str, Any],
        *,
        usage_kind: str,
        page_id: str = "",
        page_name: str = "",
        visual_id: str = "",
        visual_type: str = "",
        visual_title: str = "",
        detail: str = "",
        is_hidden: bool = False,
    ) -> None:
        self.add(
            usage_kind,
            field_kind=str(info.get("field_kind") or ""),
            table=str(info.get("table") or ""),
            field=str(info.get("field") or ""),
            page_id=page_id,
            page_name=page_name,
            visual_id=visual_id,
            visual_type=visual_type,
            visual_title=visual_title,
            aggregation=str(info.get("aggregation") or ""),
            detail=detail,
            is_hidden=is_hidden,
        )

    def add_expression(
        self,
        node: Any,
        *,
        table_names: Iterable[str],
        page_id: str = "",
        page_name: str = "",
        visual_id: str = "",
        visual_type: str = "",
        visual_title: str = "",
        usage_kind: str = USAGE_FORMAT,
        detail: str = "",
        is_hidden: bool = False,
    ) -> None:
        """Cari referensi Column/Measure/Aggregation di struktur objects/formatting."""
        for info in _expression_fields(node):
            property_name = str(info.get("property") or "")
            detail_text = detail or "formatting"
            if property_name:
                detail_text = f"{detail_text} \u00b7 {property_name}"
            self.add_field(
                info,
                usage_kind=usage_kind,
                page_id=page_id,
                page_name=page_name,
                visual_id=visual_id,
                visual_type=visual_type,
                visual_title=visual_title,
                detail=detail_text,
                is_hidden=is_hidden,
            )
        for info in _visual_calculations(node):
            for table, column in _dax_columns(
                str(info.get("expression") or ""), table_names
            ):
                self.add(
                    USAGE_CALCULATION,
                    field_kind="Column",
                    table=table,
                    field=column,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_type=visual_type,
                    visual_title=visual_title,
                    detail=f"visual calculation {info.get('name') or ''}".strip(),
                    is_hidden=is_hidden,
                )

    def unresolved_field(
        self,
        *,
        page_id: str,
        page_name: str,
        visual_id: str,
        visual_title: str,
        query_ref: str,
    ) -> None:
        """Catat referensi field yang tidak bisa dipetakan (string + baris)."""
        where = f"{page_name} / {visual_id[:8]}"
        ref = str(query_ref or "?")
        reason = f"'{ref}' tidak bisa dipetakan ke tabel/kolom"
        self.unresolved.append(f"{where}: {reason}")
        self.unresolved_rows.append(
            {
                "page_id": str(page_id or ""),
                "page_name": str(page_name or ""),
                "visual_id": str(visual_id or ""),
                "visual_title": str(visual_title or ""),
                "query_ref": ref,
                "reason": reason,
            }
        )


def _format_property(path: tuple[str, ...]) -> str:
    if "properties" in path:
        index = path.index("properties")
        if index + 1 < len(path):
            return str(path[index + 1])
    return str(path[-1]) if path else ""


def _expression_fields(
    node: Any, depth: int = 0, path: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    """Semua field reference di dalam struktur formatting (bukan proyeksi visual)."""
    out: list[dict[str, Any]] = []
    if depth > 40:
        return out
    if isinstance(node, dict):
        for kind in _EXPRESSION_KINDS:
            body = node.get(kind)
            if isinstance(body, dict) and body.get("Property"):
                info = parse_field({kind: body})
                info["property"] = _format_property(path)
                out.append(info)
                break
        else:
            for key, value in node.items():
                out.extend(_expression_fields(value, depth + 1, path + (str(key),)))
    elif isinstance(node, list):
        for item in node:
            out.extend(_expression_fields(item, depth + 1, path))
    return out


def _visual_calculations(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if depth > 20:
        return out
    if isinstance(node, dict):
        for kind in ("NativeVisualCalculation", "VisualCalculation"):
            body = node.get(kind)
            if isinstance(body, dict):
                out.append(
                    {
                        "kind": kind,
                        "name": body.get("Name") or body.get("Property"),
                        "expression": body.get("Expression") or "",
                    }
                )
        for value in node.values():
            out.extend(_visual_calculations(value, depth + 1))
    elif isinstance(node, list):
        for item in node:
            out.extend(_visual_calculations(item, depth + 1))
    return out


def _filter_fields(filter_obj: Any) -> list[tuple[str, str]]:
    """Kolom di filter PBIR v2 (``From``/``Where``) tanpa ``field`` eksplisit."""
    if not isinstance(filter_obj, dict):
        return []
    from_items = [
        item for item in filter_obj.get("From") or [] if isinstance(item, dict)
    ]
    entities = {
        str(item.get("Entity") or "").strip()
        for item in from_items
        if str(item.get("Entity") or "").strip()
    }
    if len(entities) > 1:
        # Filter gabungan lintas tabel tidak dihitung Measure Killer.
        return []
    aliases = {
        str(item.get("Name") or ""): str(item.get("Entity") or "")
        for item in from_items
    }
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "Column" and isinstance(value, dict):
                    expression = value.get("Expression") or {}
                    source = expression.get("SourceRef") or {}
                    table = str(
                        source.get("Entity")
                        or aliases.get(str(source.get("Source") or ""), "")
                    )
                    column = str(value.get("Property") or "")
                    if table and column and (table, column) not in seen:
                        seen.add((table, column))
                        out.append((table, column))
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(filter_obj)
    return out


def _filter_infos(flt: dict[str, Any]) -> list[dict[str, Any]]:
    field = flt.get("field")
    if field:
        return [parse_field(field)]
    return [
        {
            "field_kind": "Column",
            "table": table,
            "field": column,
            "aggregation": "",
            "expression": "",
        }
        for table, column in _filter_fields(flt.get("filter"))
    ]


def _dax_columns(expression: str, table_names: Iterable[str]) -> list[tuple[str, str]]:
    if not expression or not table_names:
        return []
    columns, _measures = find_dax_refs(expression, list(table_names))
    return columns


# ---------------------------------------------------------------------------
# PBIR
# ---------------------------------------------------------------------------
def _scan_pbir(
    parts: _Parts,
    collector: _Collector,
    table_names: list[str],
    log: Log,
) -> None:
    pages_meta = parts.json("definition/pages/pages.json")
    report_meta = parts.json("definition/report.json")
    collector.theme = str(
        ((report_meta.get("themeCollection") or {}).get("baseTheme") or {}).get("name")
        or report_meta.get("theme")
        or ""
    )

    for flt in (report_meta.get("filterConfig") or {}).get("filters") or []:
        values = collect_filter_values(flt.get("filter"))
        detail = " · ".join(
            part
            for part in (
                str(flt.get("type") or "Filter"),
                "; ".join(values[:3]),
            )
            if part
        )
        for info in _filter_infos(flt):
            collector.add_field(
                info,
                usage_kind=USAGE_FILTER_REPORT,
                page_name="(semua halaman)",
                visual_title="(semua visual)",
                detail=detail,
            )

    page_ids = list(pages_meta.get("pageOrder") or [])
    visual_paths = parts.paths("definition/pages/", "visual.json")
    by_page: dict[str, list[str]] = {}
    for path in visual_paths:
        segments = path.split("/")
        if len(segments) < 5:
            continue
        by_page.setdefault(segments[2], []).append(path)

    collector.pages = len(set(page_ids) | set(by_page))
    for order, page_id in enumerate(page_ids or sorted(by_page), start=1):
        page_json = parts.json(f"definition/pages/{page_id}/page.json")
        page_name = str(page_json.get("displayName") or page_id)

        for flt in (page_json.get("filterConfig") or {}).get("filters") or []:
            values = collect_filter_values(flt.get("filter"))
            detail = " · ".join(
                part
                for part in (
                    str(flt.get("type") or "Filter"),
                    "; ".join(values[:3]),
                )
                if part
            )
            for info in _filter_infos(flt):
                collector.add_field(
                    info,
                    usage_kind=USAGE_FILTER_PAGE,
                    page_id=page_id,
                    page_name=page_name,
                    visual_title="(semua visual di halaman)",
                    detail=detail,
                )

        group_parent: dict[str, str] = {}
        group_hidden: dict[str, bool] = {}
        visuals: list[tuple[str, dict[str, Any]]] = []
        for path in by_page.get(page_id, []):
            vjson = parts.json(path)
            visual_id = path.split("/")[4]
            if "visualGroup" in vjson:
                group_parent[visual_id] = str(vjson.get("parentGroupName") or "")
                group_hidden[visual_id] = bool(vjson.get("isHidden", False))
            elif "visual" in vjson:
                visuals.append((visual_id, vjson))

        def hidden(visual_id: str, vjson: dict[str, Any]) -> bool:
            if vjson.get("isHidden"):
                return True
            parent = str(vjson.get("parentGroupName") or "")
            seen: set[str] = set()
            while parent and parent not in seen:
                seen.add(parent)
                if group_hidden.get(parent):
                    return True
                parent = group_parent.get(parent, "")
            return False

        for visual_id, vjson in visuals:
            visual = vjson.get("visual") or {}
            visual_type = str(visual.get("visualType") or "")
            title = _pbir_title(visual, visual_id)
            is_hidden = hidden(visual_id, vjson)
            collector.visuals += 1
            query = visual.get("query") or {}

            for role, role_content in (query.get("queryState") or {}).items():
                for projection in (role_content or {}).get("projections") or []:
                    info = parse_field(projection.get("field") or {})
                    if info["field_kind"] == "VisualCalculation":
                        for table_name, column in _dax_columns(
                            str(info.get("expression") or ""), table_names
                        ):
                            collector.add(
                                USAGE_CALCULATION,
                                field_kind="Column",
                                table=table_name,
                                field=column,
                                page_id=page_id,
                                page_name=page_name,
                                visual_id=visual_id,
                                visual_type=visual_type,
                                visual_title=title,
                                detail=str(info.get("field") or "visual calculation"),
                                is_hidden=is_hidden,
                            )
                        continue
                    if not info["field"]:
                        query_ref = str(projection.get("queryRef") or "")
                        if "." in query_ref:
                            ref_table, ref_field = query_ref.split(".", 1)
                            info = {
                                **info,
                                "table": ref_table,
                                "field": ref_field,
                            }
                    if not info["field"]:
                        collector.unresolved_field(
                            page_id=page_id,
                            page_name=page_name,
                            visual_id=visual_id,
                            visual_title=title,
                            query_ref=str(projection.get("queryRef") or "?"),
                        )
                        continue
                    collector.add_field(
                        info,
                        usage_kind=USAGE_FIELD,
                        page_id=page_id,
                        page_name=page_name,
                        visual_id=visual_id,
                        visual_type=visual_type,
                        visual_title=title,
                        detail=str(role),
                        is_hidden=is_hidden,
                    )
                for parameter in (role_content or {}).get("fieldParameters") or []:
                    info = parse_field(parameter.get("parameterExpr") or {})
                    if not info["field"]:
                        continue
                    collector.add_field(
                        info,
                        usage_kind=USAGE_FIELD,
                        page_id=page_id,
                        page_name=page_name,
                        visual_id=visual_id,
                        visual_type=visual_type,
                        visual_title=title,
                        detail="field parameter",
                        is_hidden=is_hidden,
                    )

            for parameter in query.get("fieldParameters") or []:
                info = parse_field(parameter.get("parameterExpr") or {})
                if info["field"]:
                    collector.add_field(
                        info,
                        usage_kind=USAGE_FIELD,
                        page_id=page_id,
                        page_name=page_name,
                        visual_id=visual_id,
                        visual_type=visual_type,
                        visual_title=title,
                        detail="field parameter",
                        is_hidden=is_hidden,
                    )

            for item in (query.get("sortDefinition") or {}).get("sort") or []:
                info = parse_field(item.get("field") or {})
                if not info["field"] and item.get("queryRef"):
                    info = {**info, "field": str(item["queryRef"])}
                direction = str(item.get("direction") or "")
                collector.add_field(
                    info,
                    usage_kind=USAGE_SORT,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_type=visual_type,
                    visual_title=title,
                    detail=direction,
                    is_hidden=is_hidden,
                )

            for flt in (vjson.get("filterConfig") or {}).get("filters") or []:
                values = collect_filter_values(flt.get("filter"))
                detail = " · ".join(
                    part
                    for part in (
                        str(flt.get("type") or "Filter"),
                        "; ".join(values[:3]),
                    )
                    if part
                )
                for info in _filter_infos(flt):
                    collector.add_field(
                        info,
                        usage_kind=USAGE_FILTER_VISUAL,
                        page_id=page_id,
                        page_name=page_name,
                        visual_id=visual_id,
                        visual_type=visual_type,
                        visual_title=title,
                        detail=detail,
                        is_hidden=is_hidden,
                    )

            for key in ("objects", "visualContainerObjects"):
                collector.add_expression(
                    visual.get(key) or {},
                    table_names=table_names,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_type=visual_type,
                    visual_title=title,
                    usage_kind=USAGE_FORMAT,
                    detail=f"formatting {key}",
                    is_hidden=is_hidden,
                )
        collector.page_rows.append(
            {
                "page_id": page_id,
                "page_name": page_name,
                "is_hidden": page_is_hidden(page_json),
                "visual_count": len(visuals),
                "order_index": order,
            }
        )
        log(f"  PBIR halaman {order}: {page_name} ({len(visuals)} visual)")


def _pbir_title(visual: dict[str, Any], visual_id: str) -> str:
    """Judul visual PBIR; fallback memakai tipe + 8 karakter ID."""
    container = visual.get("visualContainerObjects") or {}
    for entry in container.get("title") or []:
        text = (entry.get("properties") or {}).get("text") or {}
        literal = ((text.get("expr") or {}).get("Literal") or {}).get("Value")
        if literal:
            cleaned = str(literal).strip().strip("'")
            if cleaned:
                return cleaned
    visual_type = str(visual.get("visualType") or "visual")
    return f"(tanpa judul) {visual_type} {visual_id[:8]}"


# ---------------------------------------------------------------------------
# PBIR-Legacy
# ---------------------------------------------------------------------------
def _legacy_field(
    item: dict[str, Any], alias: dict[str, str]
) -> dict[str, Any] | None:
    """Resolusi satu item ``prototypeQuery.Select`` legacy."""
    calculation = item.get("NativeVisualCalculation")
    if isinstance(calculation, dict):
        return {
            "field_kind": "VisualCalculation",
            "table": "",
            "field": calculation.get("Name") or calculation.get("Property") or "",
            "aggregation": "",
            "expression": calculation.get("Expression") or "",
        }
    for kind in ("Column", "Measure", "Aggregation", "HierarchyLevel", "Hierarchy"):
        body = item.get(kind)
        if not isinstance(body, dict):
            continue
        if kind == "Aggregation":
            column = ((body.get("Expression") or {}).get("Column")) or {}
            source = (column.get("Expression") or {}).get("SourceRef") or {}
            table = source.get("Entity") or alias.get(str(source.get("Source") or ""), "")
            return {
                "field_kind": "Aggregation",
                "table": table or "",
                "field": column.get("Property") or "",
                "aggregation": _aggregation(body),
                "expression": "",
            }
        if kind in {"HierarchyLevel", "Hierarchy"}:
            table, name = _deep_entity_property(body)
            level = body.get("Level")
            hierarchy = ((body.get("Expression") or {}).get("Hierarchy") or {}).get(
                "Property"
            )
            field = f"{hierarchy}.{level}" if hierarchy and level else (level or hierarchy)
            return {
                "field_kind": kind,
                "table": table or "",
                "field": field or "",
                "aggregation": "",
                "expression": "",
            }
        source = (body.get("Expression") or {}).get("SourceRef") or {}
        table = source.get("Entity") or alias.get(str(source.get("Source") or ""), "")
        return {
            "field_kind": kind,
            "table": table or "",
            "field": body.get("Property") or "",
            "aggregation": "",
            "expression": "",
        }
    return None


def _deep_entity_property(node: Any) -> tuple[str, str]:
    if isinstance(node, dict):
        source = node.get("SourceRef")
        if isinstance(source, dict) and source.get("Entity"):
            return str(source["Entity"]), str(node.get("Property") or "")
        for value in node.values():
            table, name = _deep_entity_property(value)
            if table or name:
                return table, name
    elif isinstance(node, list):
        for item in node:
            table, name = _deep_entity_property(item)
            if table or name:
                return table, name
    return "", ""


def _legacy_filter_fields(
    node: Any, alias: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Filter legacy: ``{"expression": {Column|Aggregation|...}}``.

    ``Where`` pada ``prototypeQuery`` memakai bentuk ``Condition.Comparison``
    sehingga ekspresinya dicari secara rekursif sebagai cadangan; alias
    ``From`` dipakai untuk mengisi nama tabel.
    """
    out: list[dict[str, Any]] = []
    for flt in _as_list(node):
        if not isinstance(flt, dict):
            continue
        expression = flt.get("expression")
        if isinstance(expression, dict) and expression:
            info = parse_field(expression)
            if not info.get("table") and alias:
                info["table"] = alias.get(_source_alias(expression, alias), "")
            info["detail"] = str(flt.get("type") or "Filter")
            out.append(info)
            continue
        nested = _expression_fields(flt)
        if nested:
            for info in nested:
                info = dict(info)
                if not info.get("table") and alias:
                    info["table"] = alias.get(_source_alias(flt, alias), "")
                info["detail"] = str(flt.get("type") or "Filter")
                out.append(info)
            continue
        for child in flt.get("children") or []:
            out.extend(_legacy_filter_fields(child, alias))
    return out


def _source_alias(node: Any, alias: dict[str, str]) -> str:
    """Alias ``SourceRef.Source`` pertama yang dikenal di daftar ``From``."""
    if isinstance(node, dict):
        source = node.get("SourceRef")
        if isinstance(source, dict):
            name = str(source.get("Source") or "")
            if name in alias:
                return name
        for value in node.values():
            found = _source_alias(value, alias)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _source_alias(item, alias)
            if found:
                return found
    return ""


def _as_list(value: Any) -> list[Any]:
    value = _loads(value)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def _scan_legacy(
    parts: _Parts,
    collector: _Collector,
    table_names: list[str],
    log: Log,
) -> None:
    report = parts.json("report.json")
    if not report:
        collector.unresolved.append("report.json kosong atau tidak bisa dibaca")
        return

    report_config = _loads(report.get("config")) or {}
    collector.theme = str(report.get("theme") or report_config.get("theme") or "")

    for info in _legacy_filter_fields(report.get("filters")):
        collector.add_field(
            info,
            usage_kind=USAGE_FILTER_REPORT,
            page_name="(semua halaman)",
            visual_title="(semua visual)",
            detail=str(info.get("detail") or "Filter"),
        )

    sections = report.get("sections") or []
    collector.pages = len(sections)
    for order, section in enumerate(sections, start=1):
        page_id = str(section.get("name") or f"section{order}")
        page_name = str(section.get("displayName") or page_id)

        for info in _legacy_filter_fields(section.get("filters")):
            collector.add_field(
                info,
                usage_kind=USAGE_FILTER_PAGE,
                page_id=page_id,
                page_name=page_name,
                visual_title="(semua visual di halaman)",
                detail=str(info.get("detail") or "Filter"),
            )

        visuals = 0
        for container in section.get("visualContainers") or []:
            config = _loads(container.get("config"))
            if not isinstance(config, dict):
                continue
            visual = config.get("singleVisual")
            if not isinstance(visual, dict):
                continue
            visuals += 1
            collector.visuals += 1
            visual_id = str(config.get("name") or container.get("name") or f"v{visuals}")
            visual_type = str(visual.get("visualType") or "")
            title = _legacy_title(visual, visual_id)

            query = visual.get("prototypeQuery") or {}
            alias = {
                str(item.get("Name")): str(item.get("Entity") or "")
                for item in query.get("From") or []
                if isinstance(item, dict)
            }
            select: dict[str, dict[str, Any]] = {}
            for item in query.get("Select") or []:
                if not isinstance(item, dict):
                    continue
                info = _legacy_field(item, alias)
                name = str(item.get("Name") or "")
                if info and name:
                    select[name] = info

            used_refs: set[str] = set()
            for role, refs in (visual.get("projections") or {}).items():
                for ref in refs or []:
                    query_ref = str((ref or {}).get("queryRef") or "")
                    if not query_ref:
                        continue
                    used_refs.add(query_ref)
                    info = select.get(query_ref)
                    if info is None:
                        info = _query_ref_field(query_ref, alias)
                    if info is None:
                        collector.unresolved_field(
                            page_id=page_id,
                            page_name=page_name,
                            visual_id=visual_id,
                            visual_title=title,
                            query_ref=query_ref,
                        )
                        continue
                    if info["field_kind"] == "VisualCalculation":
                        for column_table, column_name in _dax_columns(
                            str(info.get("expression") or ""), table_names
                        ):
                            collector.add(
                                USAGE_CALCULATION,
                                field_kind="Column",
                                table=column_table,
                                field=column_name,
                                page_id=page_id,
                                page_name=page_name,
                                visual_id=visual_id,
                                visual_type=visual_type,
                                visual_title=title,
                                detail=str(
                                    info.get("field") or "visual calculation"
                                ),
                            )
                        continue
                    collector.add_field(
                        info,
                        usage_kind=USAGE_FIELD,
                        page_id=page_id,
                        page_name=page_name,
                        visual_id=visual_id,
                        visual_type=visual_type,
                        visual_title=title,
                        detail=str(role),
                    )

            # Select yang tidak muncul di projections tetap dipakai query
            # (mis. filter TopN/OrderBy) -> dihitung agar tidak salah "aman".
            for name, info in select.items():
                if name in used_refs:
                    continue
                if info.get("field_kind") == "VisualCalculation":
                    continue
                collector.add_field(
                    info,
                    usage_kind=USAGE_QUERY_FILTER,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_type=visual_type,
                    visual_title=title,
                    detail="select tanpa proyeksi",
                )

            for field_info in _legacy_filter_fields(container.get("filters"), alias):
                collector.add_field(
                    field_info,
                    usage_kind=USAGE_FILTER_VISUAL,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_type=visual_type,
                    visual_title=title,
                    detail=str(field_info.get("detail") or "Filter"),
                )
            for field_info in _legacy_filter_fields(query.get("Where"), alias):
                collector.add_field(
                    field_info,
                    usage_kind=USAGE_QUERY_FILTER,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_type=visual_type,
                    visual_title=title,
                    detail="query Where",
                )

            for item in query.get("OrderBy") or []:
                expression = (item or {}).get("Expression") or {}
                for key in _EXPRESSION_KINDS:
                    if isinstance(expression.get(key), dict):
                        collector.add_field(
                            parse_field({key: expression[key]}),
                            usage_kind=USAGE_SORT,
                            page_id=page_id,
                            page_name=page_name,
                            visual_id=visual_id,
                            visual_type=visual_type,
                            visual_title=title,
                            detail=str(item.get("Direction") or ""),
                        )
                        break

            for item in (visual.get("sortDefinition") or {}).get("sort") or []:
                info = parse_field(item.get("field") or {})
                collector.add_field(
                    info,
                    usage_kind=USAGE_SORT,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_type=visual_type,
                    visual_title=title,
                    detail=str(item.get("direction") or ""),
                )

            for key in ("objects", "vcObjects", "columnProperties"):
                collector.add_expression(
                    visual.get(key) or {},
                    table_names=table_names,
                    page_id=page_id,
                    page_name=page_name,
                    visual_id=visual_id,
                    visual_type=visual_type,
                    visual_title=title,
                    usage_kind=USAGE_FORMAT,
                    detail=f"formatting {key}",
                )
        section_config = _loads(section.get("config")) or {}
        section_hidden = bool(section.get("isHidden")) or str(
            section.get("visibility") or section_config.get("visibility") or ""
        ).lower() in {"hiddeninviewmode", "hidden"}
        collector.page_rows.append(
            {
                "page_id": page_id,
                "page_name": page_name,
                "is_hidden": section_hidden,
                "visual_count": visuals,
                "order_index": order,
            }
        )
        log(f"  Legacy halaman {order}: {page_name} ({visuals} visual)")


def _query_ref_field(
    query_ref: str, alias: dict[str, str]
) -> dict[str, Any] | None:
    """Cadangan: ``Tabel.Kolom`` / ``Sum(Tabel.Kolom)`` pada queryRef legacy.

    Hanya prefix berbentuk nama fungsi DAX (``Sum(``, ``Min(``, …) yang
    dianggap agregasi. Nama field boleh memuat tanda kurung, mis.
    ``Jumlah Unit Filter (STNK Request Date)``; jangan dipotong sebagai fungsi.
    """
    text = str(query_ref or "").strip()
    if not text:
        return None
    aggregation = ""
    match = AGGREGATED_QUERY_REF.match(text)
    if match and text.endswith(")"):
        function, inner = text.split("(", 1)
        text = inner[:-1]
        aggregation = function.strip()
    if "." not in text:
        return None
    table, name = text.split(".", 1)
    return {
        "field_kind": "Aggregation" if aggregation else "Field",
        "table": alias.get(table, table),
        "field": name,
        "aggregation": aggregation,
        "expression": "",
    }


def _legacy_title(visual: dict[str, Any], visual_id: str) -> str:
    container = visual.get("vcObjects") or {}
    for entry in container.get("title") or []:
        text = (entry.get("properties") or {}).get("text") or {}
        literal = ((text.get("expr") or {}).get("Literal") or {}).get("Value")
        if literal:
            cleaned = str(literal).strip().strip("'")
            if cleaned:
                return cleaned
    visual_type = str(visual.get("visualType") or "visual")
    return f"(tanpa judul) {visual_type} {visual_id[:8]}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def scan_definition(
    definition: ReportDefinition,
    *,
    table_names: Iterable[str] = (),
    log: Log = _silent,
) -> ReportUsage:
    """Scan satu definisi report Power BI Service (PBIR atau PBIR-Legacy)."""
    parts = {part.path: part.payload for part in definition.parts}
    collector = _Collector()
    names = [str(name) for name in table_names if name]
    report_format = str(definition.report_format or "")
    if report_format == PBIR:
        _scan_pbir(_Parts(parts), collector, names, log)
    elif report_format == PBIR_LEGACY:
        _scan_legacy(_Parts(parts), collector, names, log)
    else:
        return ReportUsage(
            report_format=report_format,
            unresolved=[f"Format report tidak dikenal: {report_format or '(kosong)'}"],
        )
    collector.finish()
    if not collector.records:
        collector.unresolved.append(
            "Tidak ada field yang terbaca; report mungkin kosong atau memakai "
            "visual yang tidak memakai field."
        )
    return ReportUsage(
        report_format=report_format,
        pages=collector.pages,
        visuals=collector.visuals,
        records=collector.records,
        unresolved=collector.unresolved,
        unresolved_rows=collector.unresolved_rows,
        theme=collector.theme,
        page_rows=collector.page_rows,
    )
