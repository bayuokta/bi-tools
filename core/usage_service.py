"""Orkestrasi analisa semantic model: ukuran kolom + pemakaian di report.

Alur satu kali analisa:

1. buka XMLA workspace (read-only) lalu baca TMSCHEMA + DMV storage
   (:mod:`core.column_stats`) untuk ukuran per kolom,
2. susun referensi kolom dari objek model (measure, relasi, hierarchy, sort by,
   RLS, calculation item, KPI, langkah M) tanpa koneksi tambahan,
3. daftar report pemakai dataset (admin ``$filter=datasetId``; cadangan
   ``reports_in_group`` dan hasil scan lineage),
4. unduh ``getDefinition`` hanya untuk report baru/berubah lalu scan
   (:mod:`core.report_usage`) dan simpan hasilnya (:mod:`core.usage_store`),
5. agregasi per kolom, verdict, dan ekspor XLSX.

Semua I/O jaringan lewat modul yang sudah ada (``core.open_client``,
``core.FabricReportClient``, ``core.PowerBILineageClient``). Fungsi inti bisa
diuji tanpa jaringan dengan menyuntikkan ``stats``, ``reports``, dan
``definition_loader``.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

import pandas as pd

from .api import ApiError
from .auth import EntraTokens, ServicePrincipal, UserSession, fabric_provider
from .column_stats import (
    ColumnStat,
    MeasureStat,
    ModelStats,
    TableStat,
    read_model_stats,
)
from .errors import ExtractionError
from .fabric_api import (
    PBIR,
    PBIR_LEGACY,
    FabricReportClient,
    ReportDefinition,
    ServiceReportRef,
)
from .lineage_api import PowerBILineageClient
from .lineage_service import reports_using_dataset
from .report_catalog import catalog_reports
from .lineage_store import DEFAULT_DB, close_quietly, connect
from .metadata_common import (
    find_dax_refs,
    reference_depth,
    strip_dax_literals,
    write_sheet,
)
from .best_practice import build_best_practice
from .model_health import build_health
from .model import (
    LiveModel,
    build_columns,
    build_dependencies,
    build_measures,
    build_partitions,
    build_tables,
    clean_expr,
    read_model_metadata,
)
from .report_usage import scan_definition
from .usage_store import (
    columns as stored_columns,
    field_usage,
    initialize,
    last_run,
    m_queries as stored_m_queries,
    mark_reports_inactive,
    measures as stored_measures,
    model_refs as stored_model_refs,
    report_cache,
    report_pages as stored_report_pages,
    reports as stored_reports,
    save_columns,
    save_m_queries,
    save_measures,
    save_model_refs,
    save_report,
    save_run,
    unresolved as stored_unresolved,
    utc_now,
)
from .xmla_client import XmlaError, open_client, workspace_endpoint

Log = Callable[[str], None]
Progress = Callable[[int, int, str], None]

STATUS_UNUSED = "Tidak dipakai"
STATUS_USED = "Dipakai"
STATUS_BLOCKER = "Wajib dipertahankan"
STATUS_UNKNOWN = "Perlu dicek"
COVERAGE_MODEL_ONLY = "report tidak disertakan · metadata model saja"

BLOCKING_KINDS = {
    "relationship",
    "sort by",
    "hierarchy",
    "RLS",
    "column permission",
    "calculation item",
    "KPI",
    "calculated column",
    "calculated table",
    "calculated table column",
    "langkah M",
}
SUPPORTED_FORMATS = {PBIR, PBIR_LEGACY}
FORMAT_RDL = "RDL"
PERSONAL_WORKSPACE_TYPES = {"PersonalGroup", "Personal"}
APP_REPORT_PREFIX = "[app]"
APP_ZERO_WIDTH = {0x200B: None, 0x200C: None, 0x200D: None, 0xFEFF: None}
INACCESSIBLE_STATUSES = {401, 403, 404}
INACCESSIBLE_RETRY_HOURS = 24
REPORT_USAGE_COLUMNS = [
    "Table", "Column", "Report", "Report ID", "Workspace", "Page",
    "Visual", "Visual type", "Usage", "Field kind", "Aggregation",
    "Detail", "Visual hidden",
]
MODEL_USAGE_COLUMNS = [
    "Table", "Column", "Kind", "Object", "Detail", "Depth", "Blocking",
]
REPORT_COLUMNS = [
    "Report", "Report ID", "Workspace ID", "Format", "Modified at",
    "Scanned at", "Status", "Pages", "Visuals", "Fields", "Unresolved",
    "Message", "Active",
]
UNRESOLVED_COLUMNS = [
    "Report", "Page", "Visual", "Query Ref", "Reason",
]
MEASURE_COLUMNS = [
    "Table", "Measure", "Data type", "Status", "Uses", "Reports",
    "Direct references", "Transitive references",
    "Format string", "Hidden", "Display folder", "Expression", "Note",
]
HEALTH_COLUMNS = [
    "Severity", "Area", "Rule", "Object", "Table", "Column", "Measure",
    "Report", "Page", "Visual", "Size", "Detail", "Metrics",
]
BEST_PRACTICE_COLUMNS = [
    "Rule ID", "Rule", "Category", "Severity", "Object", "Table", "Name",
    "Kind", "Detail", "Size", "Rule score",
]
BEST_PRACTICE_RULE_COLUMNS = [
    "Rule ID", "Rule", "Category", "Severity", "Status", "Findings",
    "Score", "Reason",
]


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


def format_bytes(value: Any) -> str:
    """Ukuran biner ringkas: 0 B, 1,4 KB, 20,3 MB."""
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    if size <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    if index == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[index]}".replace(".", ",")


def normalize_report_format(value: Any) -> str:
    """Samakan label format dari REST/Fabric.

    REST memakai ``PBIRLegacy``, Fabric ``_detect_format`` memakai
    ``PBIR-Legacy``; keduanya harus dianggap format yang sama. Nilai kosong
    dikembalikan apa adanya supaya pemanggil bisa mencoba mengunduh definisi
    dan membiarkan isi definisi yang menentukan format sebenarnya.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    key = (
        text.casefold()
        .replace("_", "")
        .replace("-", "")
        .replace(" ", "")
    )
    if key in {"pbirlegacy", "legacy"}:
        return PBIR_LEGACY
    if key.startswith("paginated") or key in {"rdl", "rdlreport"}:
        return FORMAT_RDL
    if key.startswith("pbir"):
        return PBIR
    return text


# ---------------------------------------------------------------------------
# Daftar report
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ReportEntry:
    """Satu report yang memakai dataset (belum tentu sudah dianalisa)."""

    report_id: str
    name: str
    workspace_id: str
    report_format: str = ""
    modified_at: str = ""
    source: str = "member"
    workspace_name: str = ""
    workspace_type: str = ""

    @property
    def personal(self) -> bool:
        """True untuk report di My Workspace (tidak dapat diakses SP)."""
        if self.workspace_type in PERSONAL_WORKSPACE_TYPES:
            return True
        if self.workspace_type:
            return False
        name = self.workspace_name.casefold()
        return name.startswith("personalworkspace ") or name.startswith(
            "my workspace"
        )

    @property
    def workspace_label(self) -> str:
        name = self.workspace_name or self.workspace_id or "workspace"
        kind = f" ({self.workspace_type})" if self.workspace_type else ""
        return f"{name}{kind}"

    @property
    def is_app(self) -> bool:
        """True untuk report yang berasal dari fitur Power BI App (``[App] …``)."""
        name = self.name.translate(APP_ZERO_WIDTH).strip().casefold()
        return name.startswith(APP_REPORT_PREFIX)

    @property
    def supported(self) -> bool:
        """False hanya untuk report RDL/paginated (field tidak bisa dianalisa)."""
        return normalize_report_format(self.report_format) != FORMAT_RDL

    @property
    def label(self) -> str:
        return f"{self.name or self.report_id} ({self.report_id[:8]})"


def _entry_from_rest(row: dict[str, Any], *, source: str) -> ReportEntry | None:
    report_id = str(row.get("id") or row.get("report_id") or "").strip()
    if not report_id:
        return None
    report_type = str(row.get("reportType") or "")
    report_format = normalize_report_format(row.get("format"))
    if report_type == "PaginatedReport":
        report_format = FORMAT_RDL
    return ReportEntry(
        report_id=report_id,
        name=str(row.get("name") or ""),
        workspace_id=str(
            row.get("workspaceId")
            or row.get("workspace_id")
            or row.get("datasetWorkspaceId")
            or ""
        ),
        report_format=report_format,
        modified_at=str(row.get("modifiedDateTime") or row.get("modified_at") or ""),
        source=source,
    )


def discover_reports(
    principal: Any,
    *,
    dataset_id: str,
    workspace_id: str,
    include_other_workspaces: bool = True,
    database: Path | str = DEFAULT_DB,
    log: Log = _silent,
) -> tuple[list[ReportEntry], str, list[str]]:
    """Daftar report pemakai dataset dari workspace, katalog, dan lineage.

    Admin API hanya dipakai program sync; fungsi ini tidak pernah memanggil
    endpoint administratif Power BI.
    """
    notes: list[str] = []
    client = PowerBILineageClient(principal, log=log)
    entries: dict[str, ReportEntry] = {}
    method = "workspace"
    try:
        try:
            workspace_reports = client.reports_in_group(workspace_id)
        except ApiError as exc:
            workspace_reports = []
            notes.append(
                f"Daftar report workspace tidak bisa dibaca ({exc.status_code}); "
                "memakai katalog snapshot."
            )
            log(notes[-1])
        for row in workspace_reports:
            if str(row.get("datasetId") or "") != dataset_id:
                continue
            entry = _entry_from_rest(row, source="workspace")
            if entry:
                entries.setdefault(entry.report_id, entry)
        if include_other_workspaces:
            for row in catalog_reports(database, dataset_id):
                entry = _entry_from_rest(
                    {
                        "id": row.get("report_id"),
                        "workspaceId": row.get("workspace_id"),
                        "name": row.get("name"),
                        "reportType": row.get("report_type"),
                        "format": row.get("report_format"),
                        "modifiedDateTime": row.get("modified_at"),
                    },
                    source="catalog",
                )
                if entry and entry.report_id not in entries:
                    entries[entry.report_id] = entry
                    method = "catalog"
            if entries:
                notes.append(
                    "Daftar report memakai snapshot hasil sync dan lineage; "
                    "report baru atau perubahan terakhir bisa belum terlihat."
                )
            for row in reports_using_dataset(database, dataset_id):
                entry = _entry_from_rest(row, source="lineage")
                if entry and entry.report_id not in entries:
                    entries[entry.report_id] = entry
    finally:
        client.close()
    ordered = sorted(entries.values(), key=lambda item: (item.name, item.report_id))
    ordered = _with_workspace_info(ordered, database)
    personal = sum(1 for entry in ordered if entry.personal)
    if personal:
        log(
            f"Report di My Workspace (personal): {personal}; dilewati secara "
            "default karena service principal tidak punya akses ke sana."
        )
    return ordered, method, notes


def _with_workspace_info(
    entries: list[ReportEntry], database: Path | str
) -> list[ReportEntry]:
    """Lengkapi nama + tipe workspace dari katalog SQLite."""
    from .lineage_service import workspace_detail

    cache: dict[str, tuple[str, str]] = {}
    enriched: list[ReportEntry] = []
    for entry in entries:
        workspace_id = entry.workspace_id
        if workspace_id not in cache:
            option = workspace_detail(database, workspace_id) if workspace_id else None
            cache[workspace_id] = (
                option.name if option else "",
                option.type if option else "",
            )
        name, kind = cache[workspace_id]
        enriched.append(
            replace(
                entry,
                workspace_name=name,
                workspace_type=kind,
            )
        )
    return enriched


# ---------------------------------------------------------------------------
# Referensi kolom dari objek model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelReference:
    """Satu pemakaian kolom/measure oleh objek di dalam semantic model."""

    kind: str
    object: str
    detail: str
    blocking: bool = True
    source_table: str = ""
    source_measure: str = ""
    depth: int = 1


# Pemakaian yang tidak dihitung di kolom "Uses" (tetap disimpan di detail).
UNCOUNTED_REF_KINDS = frozenset({"langkah M"})
UNCOUNTED_USAGE_KINDS = frozenset({"sort"})


def is_counted_reference(reference: Any) -> bool:
    return str(getattr(reference, "kind", "") or "") not in UNCOUNTED_REF_KINDS


def is_counted_record(record: Mapping[str, Any]) -> bool:
    return str(record.get("usage_kind") or "") not in UNCOUNTED_USAGE_KINDS


@dataclass
class MeasureAnalysis:
    """Measure model + pemakaian report/measure lain + verdict."""

    measure: MeasureStat
    status: str
    reason: str
    model_refs: list[ModelReference] = field(default_factory=list)
    report_records: list[dict[str, Any]] = field(default_factory=list)
    indirect: bool = False

    @property
    def counted_records(self) -> list[dict[str, Any]]:
        return [row for row in self.report_records if is_counted_record(row)]

    @property
    def counted_refs(self) -> list[ModelReference]:
        return [ref for ref in self.direct_refs if is_counted_reference(ref)]

    @property
    def use_count(self) -> int:
        """Pemakaian report + rujukan model langsung (depth <= 1)."""
        return len(self.counted_records) + len(self.counted_refs)

    @property
    def direct_refs(self) -> list[ModelReference]:
        return [
            ref
            for ref in self.model_refs
            if int(getattr(ref, "depth", 1) or 1) <= 1
        ]

    @property
    def transitive_refs(self) -> list[ModelReference]:
        return [
            ref
            for ref in self.model_refs
            if int(getattr(ref, "depth", 1) or 1) > 1
        ]

    @property
    def report_count(self) -> int:
        return len({str(row.get("report_id") or "") for row in self.report_records})

    @property
    def size_bytes(self) -> int:
        return 0


def measure_references(
    model: LiveModel,
) -> dict[tuple[str, str], list[ModelReference]]:
    """Peta ``(tabel, measure) casefold -> referensi`` dari dependency DAX.

    Referensi ``kind="measure"`` menyimpan measure sumber di
    ``source_table``/``source_measure`` sehingga pemakaian tidak langsung
    (measure A memakai B) bisa ditelusuri.
    """
    refs: dict[tuple[str, str], list[ModelReference]] = defaultdict(list)
    seen: set[tuple[str, str, str, str]] = set()

    measures = build_measures(model)
    columns_rows, _excluded, _warnings = build_columns(model)
    tables = build_tables(model)
    table_names = [str(row["table"]) for row in tables]
    measure_keys = {
        (str(row["table"]).casefold(), str(row["measure"]).casefold())
        for row in measures
    }
    table_by_name = {
        str(row["measure"]).casefold(): str(row["table"]) for row in measures
    }

    def add(
        table: str,
        measure: str,
        kind: str,
        obj: str,
        detail: str,
        *,
        blocking: bool,
        source_table: str = "",
        source_measure: str = "",
        depth: int = 1,
    ) -> None:
        key = (str(table).casefold(), str(measure).casefold())
        if key not in measure_keys:
            return
        fingerprint = (key[0], key[1], kind, obj)
        if fingerprint in seen:
            return
        seen.add(fingerprint)
        refs[key].append(
            ModelReference(
                kind=kind,
                object=obj,
                detail=detail,
                blocking=blocking,
                source_table=source_table,
                source_measure=source_measure,
                depth=depth,
            )
        )

    for dependency in build_dependencies(measures, columns_rows, tables):
        if dependency["referenced_type"] != "Measure":
            continue
        if not dependency["resolved_in_model"]:
            continue
        origin_table = str(dependency["measure_table"])
        origin = str(dependency["measure"])
        add(
            str(dependency["referenced_table"]),
            str(dependency["referenced_object"]),
            "measure",
            f"'{origin_table}'[{origin}]",
            f"dipakai measure '{origin_table}'[{origin}] "
            f"(kedalaman {dependency['depth']})",
            blocking=False,
            source_table=origin_table,
            source_measure=origin,
            depth=int(dependency.get("depth") or 1),
        )

    for row in model.raw["TMSCHEMA_CALCULATION_ITEMS"]:
        owner = f"calculation item '{row.get('Name')}'"
        _columns, measure_names = find_dax_refs(
            str(row.get("Expression") or ""), table_names
        )
        for name in measure_names:
            add(
                table_by_name.get(name.casefold(), ""),
                name,
                "calculation item",
                owner,
                owner,
                blocking=True,
            )

    for row in model.raw["TMSCHEMA_KPIS"]:
        owner = f"KPI '{row.get('Name')}'"
        for key in ("TargetExpression", "StatusExpression", "TrendExpression"):
            _columns, measure_names = find_dax_refs(
                str(row.get(key) or ""), table_names
            )
            for name in measure_names:
                add(
                    table_by_name.get(name.casefold(), ""),
                    name,
                    "KPI",
                    owner,
                    owner,
                    blocking=True,
                )

    for row in build_partitions(model):
        if str(row.get("source_type")) != "calculated":
            continue
        table_name = str(row["table"])
        source = str(row["source"])
        named = find_field_parameter_refs(source)
        if named:
            # Field parameter berisi measure: measure itu dipakai parameter.
            for ref_table, ref_column in named:
                key = (ref_table.casefold(), ref_column.casefold())
                if key not in measure_keys:
                    continue
                add(
                    ref_table,
                    ref_column,
                    "field parameter",
                    f"'{table_name}'",
                    f"field parameter '{table_name}'",
                    blocking=False,
                )
            continue
        owner = f"calculated table '{table_name}'"
        _columns, measure_names = find_dax_refs(source, table_names)
        for name in measure_names:
            add(
                table_by_name.get(name.casefold(), ""),
                name,
                "calculated table",
                owner,
                owner,
                blocking=True,
            )

    return refs


def measure_edges(
    measure_refs: dict[tuple[str, str], list[ModelReference]]
) -> dict[tuple[str, str], set[tuple[str, str]]]:
    """Graf ``measure sumber -> measure yang dipakai`` untuk pemakaian transitif."""
    edges: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    for target, items in measure_refs.items():
        for reference in items:
            if reference.kind != "measure":
                continue
            if not reference.source_table or not reference.source_measure:
                continue
            source = (
                reference.source_table.casefold(),
                reference.source_measure.casefold(),
            )
            edges[source].add(target)
    return edges


NAMEOF_CALL = re.compile(
    r"NAMEOF\s*\(\s*"
    r"(?:'(?P<quoted>(?:[^']|'')+)'|\"(?P<double>[^\"]+)\"|(?P<bare>[^\[\](),]+?))"
    r"\s*\[\s*(?P<column>[^\]]+?)\s*\]\s*\)",
    re.IGNORECASE,
)


def find_field_parameter_refs(expression: str) -> list[tuple[str, str]]:
    """Pasangan ``(tabel, kolom)`` yang dirujuk ``NAMEOF(...)``.

    Tabel field parameter disusun sebagai calculated table berisi baris
    ``("Label", NAMEOF('Tabel'[Kolom]), urutan)``; ekspresi itu bukan DAX tabel
    biasa, jadi kolom asalnya dibaca langsung dari ``NAMEOF``.
    """
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in NAMEOF_CALL.finditer(str(expression or "")):
        table = match.group("quoted") or match.group("double") or match.group("bare") or ""
        table = table.replace("''", "'").strip()
        column = (match.group("column") or "").strip()
        if not table or not column:
            continue
        key = (table.casefold(), column.casefold())
        if key in seen:
            continue
        seen.add(key)
        pairs.append((table, column))
    return pairs


def model_references(model: LiveModel) -> dict[tuple[str, str], list[ModelReference]]:
    """Peta ``(tabel, kolom) casefold -> referensi model``."""
    refs: dict[tuple[str, str], list[ModelReference]] = defaultdict(list)
    seen: set[tuple[str, str, str, str]] = set()

    columns_rows, _excluded, _warnings = build_columns(model)
    measures = build_measures(model)
    tables = build_tables(model)
    table_names = [str(row["table"]) for row in tables]

    def add(
        table: Any,
        column: Any,
        kind: str,
        obj: str,
        detail: str,
        *,
        blocking: bool = True,
        depth: int = 1,
    ) -> None:
        table_name = str(table or "")
        column_name = str(column or "")
        if not table_name or not column_name:
            return
        key = (table_name.casefold(), column_name.casefold(), kind, obj)
        if key in seen:
            return
        seen.add(key)
        refs[(key[0], key[1])].append(
            ModelReference(
                kind=kind,
                object=obj,
                detail=detail,
                blocking=blocking,
                depth=depth,
            )
        )

    for dependency in build_dependencies(measures, columns_rows, tables):
        if dependency["referenced_type"] != "Column":
            continue
        if not dependency["resolved_in_model"]:
            continue
        measure = str(dependency["measure"])
        measure_table = str(dependency["measure_table"])
        add(
            dependency["referenced_table"],
            dependency["referenced_object"],
            "measure",
            f"'{measure_table}'[{measure}]",
            f"measure '{measure_table}'[{measure}] "
            f"(kedalaman {dependency['depth']})",
            blocking=False,
            depth=int(dependency.get("depth") or 1),
        )

    for row in columns_rows:
        if not row.get("is_calculated"):
            continue
        owner = f"'{row['table']}'[{row['column']}]"
        for table, column in find_dax_refs(str(row["expression"]), table_names)[0]:
            add(
                table,
                column,
                "calculated column",
                owner,
                f"calculated column {owner}",
            )

    model_columns = {
        (table.casefold(), name.casefold())
        for table, name in model.column_name.values()
    }
    for row in build_partitions(model):
        if str(row.get("source_type")) != "calculated":
            continue
        table_name = str(row.get("table") or "")
        source = str(row.get("source") or "")
        named = find_field_parameter_refs(source)
        if named:
            # Field parameter: kolom asal dipakai parameter, bukan tabel
            # calculated biasa. Jangan dicatat ganda.
            for ref_table, ref_column in named:
                if (ref_table.casefold(), ref_column.casefold()) not in model_columns:
                    continue
                add(
                    ref_table,
                    ref_column,
                    "field parameter",
                    f"'{table_name}'",
                    f"field parameter '{table_name}'",
                )
            # Measure Killer juga menandai kolom tabel parameter itu sendiri
            # (Parameter/Parameter Fields/Parameter Order) sebagai pemakaian.
            for col_table, col_name in model.column_name.values():
                if col_table != table_name:
                    continue
                if (col_table.casefold(), col_name.casefold()) not in model_columns:
                    continue
                add(
                    col_table,
                    col_name,
                    "field parameter",
                    f"'{table_name}'",
                    f"field parameter '{table_name}'",
                )
            continue
        owner = f"calculated table '{table_name}'"
        for table, column in find_dax_refs(source, table_names)[0]:
            add(table, column, "calculated table", owner, owner)

    for row in model.raw["TMSCHEMA_RELATIONSHIPS"]:
        from_table, from_column = model.column_name.get(
            int(row["FromColumnID"]), ("", "")
        )
        to_table, to_column = model.column_name.get(int(row["ToColumnID"]), ("", ""))
        if from_table and from_column and to_table and to_column:
            add(
                from_table,
                from_column,
                "relationship",
                f"'{to_table}'[{to_column}]",
                f"relasi ke '{to_table}'[{to_column}]",
            )
            add(
                to_table,
                to_column,
                "relationship",
                f"'{from_table}'[{from_column}]",
                f"relasi ke '{from_table}'[{from_column}]",
            )

    for column_id, column in model.column_by_id.items():
        if not column.get("IsKey"):
            continue
        table, name = model.column_name.get(column_id, ("", ""))
        if not table or not name:
            continue
        if (table.casefold(), name.casefold()) not in model_columns:
            continue
        add(
            table,
            name,
            "key column",
            f"'{table}'[{name}]",
            f"kolom kunci tabel '{table}'",
        )

    for column_id, column in model.column_by_id.items():
        sort_id = column.get("SortByColumnID")
        if sort_id is None:
            continue
        table, name = model.column_name.get(int(sort_id), ("", ""))
        owner_table, owner_name = model.column_name.get(column_id, ("", ""))
        add(
            table,
            name,
            "sort by",
            f"'{owner_table}'[{owner_name}]",
            f"mengurutkan '{owner_table}'[{owner_name}]",
        )

    for row in model.raw["TMSCHEMA_LEVELS"]:
        table, name = model.column_name.get(int(row["ColumnID"]), ("", ""))
        hierarchy = model.hierarchy_by_id.get(int(row["HierarchyID"]), {})
        owner = f"'{table}'[{hierarchy.get('Name')}]"
        add(
            table,
            name,
            "hierarchy",
            owner,
            f"level '{row.get('Name')}' di hierarchy {owner}",
        )

    for row in model.raw["TMSCHEMA_TABLE_PERMISSIONS"]:
        table = model.table_name.get(int(row["TableID"]), "")
        role = model.role_by_id.get(int(row["RoleID"]), {})
        role_name = str(role.get("Name") or "")
        filter_text = str(row.get("FilterExpression") or "")
        for ref_table, ref_column in find_dax_refs(filter_text, table_names)[0]:
            add(
                ref_table,
                ref_column,
                "RLS",
                f"role '{role_name}'",
                f"filter RLS role '{role_name}' pada tabel '{table}'",
            )
        # Kolom tanpa kualifikasi tabel (mis. [Email] = USERPRINCIPALNAME())
        # berlaku pada tabel permission itu sendiri.
        for match in re.finditer(r"\[([^\]]+)\]", filter_text):
            name = match.group(1).strip()
            if (table.casefold(), name.casefold()) not in model_columns:
                continue
            add(
                table,
                name,
                "RLS",
                f"role '{role_name}'",
                f"filter RLS role '{role_name}' pada tabel '{table}'",
            )

    for row in model.raw["TMSCHEMA_COLUMN_PERMISSIONS"]:
        table, name = model.column_name.get(int(row["ColumnID"]), ("", ""))
        add(
            table,
            name,
            "column permission",
            "OLS",
            f"column permission (OLS) '{table}'[{name}]",
        )

    for row in model.raw["TMSCHEMA_CALCULATION_ITEMS"]:
        owner = f"calculation item '{row.get('Name')}'"
        for table, column in find_dax_refs(
            str(row.get("Expression") or ""), table_names
        )[0]:
            add(table, column, "calculation item", owner, owner)

    for row in model.raw["TMSCHEMA_KPIS"]:
        owner = f"KPI '{row.get('Name')}'"
        for key in ("TargetExpression", "StatusExpression", "TrendExpression"):
            for table, column in find_dax_refs(
                str(row.get(key) or ""), table_names
            )[0]:
                add(table, column, "KPI", owner, owner)

    for column_id, column in model.column_by_id.items():
        if int(column.get("Type") or 0) != 4:
            continue
        origin = column.get("ColumnOriginID")
        if origin is None:
            continue
        table, name = model.column_name.get(int(origin), ("", ""))
        owner_table, owner_name = model.column_name.get(column_id, ("", ""))
        add(
            table,
            name,
            "calculated table column",
            f"'{owner_table}'[{owner_name}]",
            f"kolom calculated table '{owner_table}'[{owner_name}]",
        )

    columns_by_table: dict[str, set[str]] = defaultdict(set)
    for row in columns_rows:
        columns_by_table[str(row["table"])].add(str(row["column"]).casefold())
    for row in model.raw["TMSCHEMA_PARTITIONS"]:
        source = clean_expr(row.get("QueryDefinition"))
        if not source:
            continue
        table = model.table_name.get(int(row["TableID"]), "")
        names = columns_by_table.get(table, set())
        if not names:
            continue
        for match in re.finditer(r"\[([^\[\]]+)\]", strip_dax_literals(source)):
            name = match.group(1).strip()
            if name.casefold() not in names:
                continue
            add(
                table,
                name,
                "langkah M",
                f"query '{table}'",
                f"langkah Power Query tabel '{table}' (indikatif)",
            )

    return refs


# ---------------------------------------------------------------------------
# Analisa
# ---------------------------------------------------------------------------
@dataclass
class ColumnAnalysis:
    """Kolom model + pemakaian report/model + verdict."""

    column: ColumnStat
    status: str
    reason: str
    model_refs: list[ModelReference] = field(default_factory=list)
    report_records: list[dict[str, Any]] = field(default_factory=list)

    @property
    def counted_records(self) -> list[dict[str, Any]]:
        return [row for row in self.report_records if is_counted_record(row)]

    @property
    def counted_refs(self) -> list[ModelReference]:
        return [ref for ref in self.direct_refs if is_counted_reference(ref)]

    @property
    def use_count(self) -> int:
        """Pemakaian report + rujukan model langsung (depth <= 1)."""
        return len(self.counted_records) + len(self.counted_refs)

    @property
    def direct_refs(self) -> list[ModelReference]:
        return [
            ref
            for ref in self.model_refs
            if int(getattr(ref, "depth", 1) or 1) <= 1
        ]

    @property
    def transitive_refs(self) -> list[ModelReference]:
        return [
            ref
            for ref in self.model_refs
            if int(getattr(ref, "depth", 1) or 1) > 1
        ]

    @property
    def report_count(self) -> int:
        return len({str(row.get("report_id") or "") for row in self.report_records})

    @property
    def hidden_only(self) -> bool:
        records = self.report_records
        return bool(records) and all(bool(row.get("is_hidden")) for row in records)

    @property
    def size_bytes(self) -> int:
        return self.column.size_total_bytes


@dataclass
class AnalysisResult:
    """Hasil satu kali analisa (dipakai GUI, CLI, dan ekspor)."""

    dataset_id: str
    dataset_name: str
    workspace_id: str
    workspace_name: str
    analyzed_at: str
    stats: ModelStats
    columns: list[ColumnAnalysis]
    reports: list[dict[str, Any]]
    report_total: int
    report_scanned: int
    report_skipped: int
    report_failed: int
    method: str
    coverage: str
    coverage_complete: bool
    report_personal: int = 0
    report_inaccessible: int = 0
    report_app: int = 0
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    measures: list[MeasureAnalysis] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    m_queries: list[dict[str, Any]] = field(default_factory=list)
    roles: list[dict[str, Any]] = field(default_factory=list)
    report_pages: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reports_included: bool = True

    @property
    def unused(self) -> list[ColumnAnalysis]:
        return [column for column in self.columns if column.status == STATUS_UNUSED]

    @property
    def unused_measures(self) -> list[MeasureAnalysis]:
        return [
            measure for measure in self.measures if measure.status == STATUS_UNUSED
        ]

    @property
    def unused_bytes(self) -> int:
        return sum(column.size_bytes for column in self.unused)

    @property
    def dataset_bytes(self) -> int:
        return self.stats.dataset_bytes

    @property
    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for column in self.columns:
            counts[column.status] += 1
        return dict(counts)

    @property
    def measure_status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for measure in self.measures:
            counts[measure.status] += 1
        return dict(counts)


def verdict(
    column: ColumnStat,
    model_refs: list[ModelReference],
    records: list[dict[str, Any]],
    *,
    coverage_complete: bool,
) -> tuple[str, str]:
    """Tentukan status satu kolom beserta alasannya (konservatif)."""
    blocking = [ref for ref in model_refs if ref.blocking]
    if blocking:
        kinds = sorted({ref.kind for ref in blocking})
        return (
            STATUS_BLOCKER,
            "Dipakai objek model: " + ", ".join(kinds) + ".",
        )
    if records:
        reports = len({str(row.get("report_id") or "") for row in records})
        return (
            STATUS_USED,
            f"Dipakai di {len(records)} titik pada {reports} report.",
        )
    if model_refs:
        kinds = sorted({ref.kind for ref in model_refs})
        return (
            STATUS_USED,
            "Dipakai measure/model: " + ", ".join(kinds) + ".",
        )
    if not coverage_complete:
        return (
            STATUS_UNKNOWN,
            "Belum ada referensi, tetapi cakupan report belum lengkap.",
        )
    return (STATUS_UNUSED, "Tidak ada referensi di report maupun model.")


def measure_verdict(
    refs: list[ModelReference],
    records: list[dict[str, Any]],
    *,
    coverage_complete: bool,
    indirect: bool,
) -> tuple[str, str]:
    """Verdict measure (konservatif, mengikuti aturan kolom)."""
    blocking = [ref for ref in refs if ref.blocking]
    if blocking:
        kinds = sorted({ref.kind for ref in blocking})
        return (
            STATUS_BLOCKER,
            "Dirujuk objek model: " + ", ".join(kinds) + ".",
        )
    if records:
        reports = len({str(row.get("report_id") or "") for row in records})
        return (
            STATUS_USED,
            f"Dipakai di {len(records)} titik pada {reports} report.",
        )
    if indirect:
        sources = sorted(
            {
                f"'{ref.source_table}'[{ref.source_measure}]"
                for ref in refs
                if ref.kind == "measure" and ref.source_measure
            }
        )
        suffix = f" ({', '.join(sources[:3])})" if sources else ""
        return (
            STATUS_USED,
            "Dipakai tidak langsung oleh measure yang dipakai report" + suffix + ".",
        )
    if refs:
        if not coverage_complete:
            return (
                STATUS_UNKNOWN,
                "Hanya dirujuk measure lain; cakupan report belum lengkap.",
            )
        return (
            STATUS_UNUSED,
            "Hanya dirujuk measure lain yang juga tidak dipakai.",
        )
    if not coverage_complete:
        return (
            STATUS_UNKNOWN,
            "Belum ada referensi, tetapi cakupan report belum lengkap.",
        )
    return (STATUS_UNUSED, "Tidak ada referensi di report maupun model.")


def _measure_usage_key(
    row: dict[str, Any],
    keys: set[tuple[str, str]],
    by_name: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    """Cocokkan baris usage ke measure; fallback untuk Field/Arithmetic legacy."""
    table = str(row.get("table_name") or "").casefold()
    name = str(row.get("field_name") or "").casefold()
    if (table, name) in keys:
        return (table, name)
    if name in by_name:
        return by_name[name]
    if str(row.get("field_kind") or "") == "Arithmetic":
        text = f"{table} {name}"
        for candidate in sorted(by_name, key=len, reverse=True):
            if candidate and candidate in text:
                return by_name[candidate]
    return None


def _build_measure_analyses(
    *,
    stats: ModelStats,
    usage_rows: Iterable[dict[str, Any]],
    measure_refs: dict[tuple[str, str], list[ModelReference]],
    coverage_complete: bool,
) -> list[MeasureAnalysis]:
    """Susun baris measure + pemakaian langsung/tidak langsung."""
    if not stats.measures:
        return []
    keys = {measure.key for measure in stats.measures}
    by_name = {measure.measure.casefold(): measure.key for measure in stats.measures}
    direct: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in usage_rows:
        if str(row.get("field_kind") or "") not in {
            "Measure",
            "Field",
            "Arithmetic",
        }:
            continue
        key = _measure_usage_key(row, keys, by_name)
        if key is None:
            continue
        direct[key].append(
            {
                **row,
                "report_url": report_url(
                    str(row.get("report_workspace") or ""),
                    str(row.get("report_id") or ""),
                ),
            }
        )

    edges = measure_edges(measure_refs)
    used = set(direct)
    indirect: set[tuple[str, str]] = set()
    frontier = list(used)
    while frontier:
        current = frontier.pop()
        for target in edges.get(current, set()):
            if target in used:
                continue
            used.add(target)
            indirect.add(target)
            frontier.append(target)

    analyses: list[MeasureAnalysis] = []
    for measure in stats.measures:
        refs = measure_refs.get(measure.key, [])
        records = direct.get(measure.key, [])
        transitive = measure.key in indirect and not records
        status, reason = measure_verdict(
            refs,
            records,
            coverage_complete=coverage_complete,
            indirect=transitive,
        )
        analyses.append(
            MeasureAnalysis(
                measure=measure,
                status=status,
                reason=reason,
                model_refs=list(refs),
                report_records=list(records),
                indirect=transitive,
            )
        )
    analyses.sort(
        key=lambda item: (
            item.status != STATUS_UNUSED,
            item.measure.table.casefold(),
            item.measure.measure.casefold(),
        )
    )
    return analyses


def build_analysis(
    *,
    stats: ModelStats,
    usage_rows: Iterable[dict[str, Any]],
    model_refs: dict[tuple[str, str], list[ModelReference]],
    reports: list[dict[str, Any]],
    dataset_id: str,
    dataset_name: str,
    workspace_id: str,
    workspace_name: str,
    method: str,
    report_total: int,
    report_scanned: int,
    report_skipped: int,
    report_failed: int,
    coverage_complete: bool,
    coverage: str,
    report_personal: int = 0,
    report_inaccessible: int = 0,
    report_app: int = 0,
    unresolved: list[dict[str, Any]] | None = None,
    measure_refs: dict[tuple[str, str], list[ModelReference]] | None = None,
    messages: list[str] | None = None,
    analyzed_at: str | None = None,
    relationships: list[dict[str, Any]] | None = None,
    m_queries: list[dict[str, Any]] | None = None,
    roles: list[dict[str, Any]] | None = None,
    report_pages: dict[str, list[dict[str, Any]]] | None = None,
    reports_included: bool = True,
) -> AnalysisResult:
    """Gabungkan ukuran kolom, measure, pemakaian report, dan referensi model."""
    rows = list(usage_rows)
    columns_by_table: dict[str, dict[str, str]] = defaultdict(dict)
    for column in stats.columns:
        columns_by_table[column.table.casefold()][
            column.column.casefold()
        ] = column.column
    parameter_tables = {
        table
        for table, columns in columns_by_table.items()
        if "parameter fields" in columns
        and ("parameter" in columns or "parameter order" in columns)
    }
    seen_usage = {
        (
            row.get("report_id"),
            row.get("page_id"),
            row.get("visual_id"),
            row.get("usage_kind"),
            str(row.get("table_name") or "").casefold(),
            str(row.get("field_name") or "").casefold(),
        )
        for row in rows
    }
    extra: list[dict[str, Any]] = []
    for row in rows:
        table = str(row.get("table_name") or "").casefold()
        if table not in parameter_tables:
            continue
        if str(row.get("usage_kind") or "") != "field":
            continue
        if str(row.get("field_name") or "").casefold() != "parameter":
            continue
        if str(row.get("detail") or "") != "field parameter":
            continue
        field_name = columns_by_table[table]["parameter fields"]
        key = (
            row.get("report_id"),
            row.get("page_id"),
            row.get("visual_id"),
            "field",
            table,
            field_name.casefold(),
        )
        if key in seen_usage:
            continue
        seen_usage.add(key)
        extra.append(
            {
                **row,
                "field_kind": "Column",
                "field_name": field_name,
                "detail": "column grouping",
            }
        )
    rows.extend(extra)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("field_kind") or "") == "Measure":
            continue
        key = (
            str(row.get("table_name") or "").casefold(),
            str(row.get("field_name") or "").casefold(),
        )
        grouped[key].append(row)

    measures = _build_measure_analyses(
        stats=stats,
        usage_rows=rows,
        measure_refs=measure_refs or {},
        coverage_complete=coverage_complete,
    )

    columns: list[ColumnAnalysis] = []
    for column in stats.columns:
        refs = model_refs.get(column.key, [])
        records = [
            {
                **row,
                "report_url": report_url(
                    str(row.get("report_workspace") or ""),
                    str(row.get("report_id") or ""),
                ),
            }
            for row in grouped.get(column.key, [])
        ]
        status, reason = verdict(
            column, refs, records, coverage_complete=coverage_complete
        )
        columns.append(
            ColumnAnalysis(
                column=column,
                status=status,
                reason=reason,
                model_refs=list(refs),
                report_records=list(records),
            )
        )
    columns.sort(
        key=lambda item: (
            item.status != STATUS_UNUSED,
            -item.size_bytes,
            item.column.table.casefold(),
            item.column.column.casefold(),
        )
    )
    return AnalysisResult(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        analyzed_at=analyzed_at or utc_now(),
        stats=stats,
        columns=columns,
        reports=reports,
        report_total=report_total,
        report_scanned=report_scanned,
        report_skipped=report_skipped,
        report_failed=report_failed,
        method=method,
        coverage=coverage,
        coverage_complete=coverage_complete,
        report_personal=report_personal,
        report_inaccessible=report_inaccessible,
        report_app=report_app,
        unresolved=list(unresolved or []),
        measures=measures,
        messages=list(messages or []),
        relationships=list(relationships or []),
        m_queries=list(m_queries or []),
        roles=list(roles or []),
        report_pages=dict(report_pages or {}),
        reports_included=reports_included,
    )


ERROR_PARTITION_STATES = {
    "semanticerror",
    "evaluationerror",
    "dependencyerror",
    "incomplete",
}


def m_query_rows(
    partitions: Iterable[dict[str, Any]],
    expressions: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Susun baris tab M queries dari partisi + shared expression.

    Satu baris per tabel (M partisi pertama yang tidak kosong) dan satu baris
    per shared expression/parameter. Tidak ada teks yang dikarang: ekspresi
    kosong tetap kosong.
    """
    grouped: dict[str, dict[str, Any]] = {}
    for row in partitions:
        table = str(row.get("table") or "")
        if not table:
            continue
        # Partisi calculated/calculation group berisi DAX, bukan M; jangan
        # ditampilkan sebagai M query.
        if str(row.get("source_type") or "") in {"calculated", "calculationGroup"}:
            continue
        entry = grouped.setdefault(
            table,
            {
                "name": table,
                "kind": "Tabel",
                "source": "",
                "expression": "",
                "warning": "",
                "detail": "",
                "count": 0,
            },
        )
        entry["count"] += 1
        # Partisi incremental menyimpan M query di SourceExpression refresh
        # policy, bukan di QueryDefinition. Pakai sebagai fallback agar
        # lineage/tab M queries tidak kehilangan langkah.
        expression = str(
            row.get("source") or row.get("source_expression") or ""
        ).strip()
        if expression and not entry["expression"]:
            entry["expression"] = expression
        mode = str(row.get("mode") or "")
        if mode and not entry["source"]:
            entry["source"] = mode
        state = str(row.get("state") or "")
        if state and state.casefold() in ERROR_PARTITION_STATES and not entry["warning"]:
            entry["warning"] = state
    rows: list[dict[str, Any]] = []
    for entry in grouped.values():
        count = entry.pop("count")
        entry["detail"] = f"{count} partisi"
        rows.append(entry)
    for row in expressions:
        kind = str(row.get("kind") or "Expression")
        rows.append(
            {
                "name": str(row.get("name") or ""),
                "kind": "M parameter" if kind == "Parameter" else "Expression",
                "source": str(row.get("query_group") or "Model"),
                "expression": str(row.get("expression") or ""),
                "warning": "",
                "detail": str(row.get("data_type") or ""),
            }
        )
    rows.sort(key=lambda item: (item["kind"] != "Tabel", item["name"].casefold()))
    return rows


def relationship_dependency_counts(
    rows: Iterable[dict[str, Any]],
) -> dict[str, int]:
    """Jumlah objek model yang bergantung pada relasi (``DISCOVER_CALC_DEPENDENCY``).

    Baris DMV dengan ``REFERENCED_OBJECT_TYPE`` relasi muncul saat measure atau
    objek calculated memakai relasi tersebut (mis. ``USERELATIONSHIP``). Semua
    relationship tetap punya baris ``OBJECT_TYPE = ACTIVE_RELATIONSHIP`` yang
    menunjuk kolom; baris itu bukan pemakaian dan tidak dihitung.
    """
    owners: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for row in rows:
        kind = str(row.get("REFERENCED_OBJECT_TYPE") or "").casefold().replace("_", " ")
        if kind not in {"relationship", "active relationship"}:
            continue
        name = str(row.get("REFERENCED_OBJECT") or "")
        if not name:
            continue
        owners[name].add(
            (
                str(row.get("OBJECT_TYPE") or ""),
                str(row.get("TABLE") or ""),
                str(row.get("OBJECT") or ""),
            )
        )
    return {name: len(items) for name, items in owners.items()}


# ---------------------------------------------------------------------------
# Scan report (cache + simpan)
# ---------------------------------------------------------------------------
@dataclass
class ScanCounters:
    total: int = 0
    scanned: int = 0
    skipped: int = 0
    failed: int = 0
    unsupported: int = 0
    personal: int = 0
    inaccessible: int = 0
    app: int = 0
    unresolved: int = 0
    cancelled: bool = False
    incomplete: int = 0
    fetch_ms: int = 0
    scan_ms: int = 0
    workers: int = 1

    @property
    def complete(self) -> bool:
        """True bila semua report yang bisa dianalisa sudah dipindai.

        Report di My Workspace (personal) dan RDL tidak dihitung karena
        memang tidak bisa dianalisa; report inaccessible tetap menghalangi.
        """
        return (
            not self.cancelled
            and self.failed == 0
            and self.inaccessible == 0
            and self.unresolved == 0
            and self.incomplete == 0
        )


def scan_reports(
    conn: Any,
    entries: list[ReportEntry],
    *,
    dataset_id: str,
    table_names: Iterable[str],
    refresh: bool = False,
    max_reports: int | None = None,
    include_personal: bool = False,
    definition_loader: Callable[[ReportEntry], ReportDefinition] | None = None,
    scan_workers: int = 1,
    log: Log = _silent,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> ScanCounters:
    """Unduh + scan report yang baru/berubah, simpan ke SQLite.

    Report di My Workspace (``PersonalGroup``) dilewati kecuali
    ``include_personal=True``. Report yang ditolak 401/403/404 dicatat
    ``inaccessible`` dan tidak dicoba ulang selama
    ``INACCESSIBLE_RETRY_HOURS`` kecuali ``refresh=True``.

    ``scan_workers`` > 1 mengunduh definisi beberapa report sekaligus.
    Penulisan SQLite, log, progress, dan urutan hasil tetap di thread utama,
    jadi isi database sama dengan mode serial. ``max_reports`` membatasi jumlah
    unduhan yang dijadwalkan, termasuk yang di-prefetch.
    """
    counters = ScanCounters(total=len(entries))
    cache = {} if refresh else report_cache(conn, dataset_id)
    names = [str(item) for item in table_names if item]
    if definition_loader is None:
        raise ExtractionError(
            "Loader definisi report tidak tersedia untuk analisa ini."
        )
    loader = definition_loader
    workers = max(1, min(4, int(scan_workers or 1)))
    counters.workers = workers
    executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
    prefetch: list[tuple[str, Future]] = []
    prefetch_index = 0
    concurrency_ok = True
    processed = 0

    def budget_left() -> bool:
        if max_reports is None:
            return True
        return processed + len(prefetch) + 1 < max_reports

    def should_fetch(candidate: ReportEntry) -> bool:
        if not budget_left():
            return False
        if candidate.personal and not include_personal:
            return False
        if candidate.is_app:
            return False
        if not candidate.supported:
            return False
        cached = cache.get(candidate.report_id)
        if (
            cached
            and not refresh
            and cached.get("status") == "ok"
            and str(cached.get("modified_at") or "") == candidate.modified_at
            and candidate.modified_at
        ):
            return False
        if (
            cached
            and not refresh
            and cached.get("status") == "inaccessible"
            and _recently_scanned(cached.get("scanned_at"))
        ):
            return False
        return True

    def fill_prefetch(start: int) -> None:
        nonlocal prefetch_index
        if executor is None or not concurrency_ok:
            return
        if prefetch_index < start:
            prefetch_index = start
        while (
            len(prefetch) < max(1, workers - 1)
            and prefetch_index < len(entries)
            and budget_left()
        ):
            candidate = entries[prefetch_index]
            prefetch_index += 1
            if should_fetch(candidate):
                prefetch.append(
                    (candidate.report_id, executor.submit(loader, candidate))
                )

    def take_future(entry: ReportEntry) -> Future | None:
        for position, (report_id, future) in enumerate(prefetch):
            if report_id == entry.report_id:
                prefetch.pop(position)
                return future
        return None

    def drop_future(entry: ReportEntry) -> None:
        for position, (report_id, future) in enumerate(prefetch):
            if report_id == entry.report_id:
                prefetch.pop(position)
                future.cancel()
                return

    def cancel_prefetch() -> None:
        while prefetch:
            _report_id, future = prefetch.pop()
            future.cancel()

    for index, entry in enumerate(entries, start=1):
        if should_stop is not None and should_stop():
            counters.cancelled = True
            log("Analisa dihentikan atas permintaan pengguna.")
            break
        fill_prefetch(index)
        if entry.personal and not include_personal:
            save_report(
                conn,
                report_id=entry.report_id,
                workspace_id=entry.workspace_id,
                dataset_id=dataset_id,
                name=entry.name,
                report_format=entry.report_format,
                modified_at=entry.modified_at,
                status="personal",
                message=(
                    "Dilewati: report berada di My Workspace (personal) dan "
                    "tidak dapat diakses service principal."
                ),
            )
            counters.personal += 1
            continue
        if entry.is_app:
            save_report(
                conn,
                report_id=entry.report_id,
                workspace_id=entry.workspace_id,
                dataset_id=dataset_id,
                name=entry.name,
                report_format=entry.report_format,
                modified_at=entry.modified_at,
                status="app",
                message=(
                    "Dilewati: report berasal dari fitur Power BI App "
                    "([App] …); report sumbernya sudah dianalisa."
                ),
            )
            counters.app += 1
            continue
        cached = cache.get(entry.report_id)
        if (
            cached
            and not refresh
            and cached.get("status") == "ok"
            and str(cached.get("modified_at") or "") == entry.modified_at
            and entry.modified_at
        ):
            counters.skipped += 1
            continue
        if (
            cached
            and not refresh
            and cached.get("status") == "inaccessible"
            and _recently_scanned(cached.get("scanned_at"))
        ):
            counters.inaccessible += 1
            log(
                f"[{index}/{counters.total}] {entry.label} dilewati "
                "(inaccessible; coba lagi setelah cooldown)."
            )
            continue
        if not entry.supported:
            save_report(
                conn,
                report_id=entry.report_id,
                workspace_id=entry.workspace_id,
                dataset_id=dataset_id,
                name=entry.name,
                report_format=FORMAT_RDL,
                modified_at=entry.modified_at,
                status="unsupported",
                message=(
                    "Report RDL/paginated tidak dianalisa field-nya "
                    "(definisinya bukan PBIR/PBIR-Legacy)."
                ),
            )
            counters.unsupported += 1
            continue
        if max_reports is not None and processed >= max_reports:
            remaining = counters.total - index + 1
            counters.incomplete = max(counters.incomplete, remaining)
            log(
                f"Batas {max_reports} report tercapai; {remaining} report belum "
                "dipindai sehingga kolom tanpa referensi berstatus 'Perlu dicek'."
            )
            break
        if progress is not None:
            progress(index, counters.total, entry.name)
        log(f"[{index}/{counters.total}] {entry.label} ({entry.report_format})")
        future = take_future(entry)
        try:
            fetch_started = time.perf_counter()
            if future is None:
                definition = loader(entry)
            else:
                definition = future.result()
            counters.fetch_ms += int((time.perf_counter() - fetch_started) * 1000)
            scan_started = time.perf_counter()
            usage = scan_definition(definition, table_names=names, log=log)
            counters.scan_ms += int((time.perf_counter() - scan_started) * 1000)
        except ApiError as exc:
            status_code = int(getattr(exc, "status_code", 0) or 0)
            if status_code == 429 and concurrency_ok:
                concurrency_ok = False
                cancel_prefetch()
            message = str(exc).splitlines()[0][:300]
            if status_code in INACCESSIBLE_STATUSES:
                save_report(
                    conn,
                    report_id=entry.report_id,
                    workspace_id=entry.workspace_id,
                    dataset_id=dataset_id,
                    name=entry.name,
                    report_format=entry.report_format,
                    modified_at=entry.modified_at,
                    status="inaccessible",
                    message=(
                        f"HTTP {status_code} saat getDefinition; "
                        f"workspace {entry.workspace_label}. {message}"
                    )[:400],
                )
                counters.inaccessible += 1
                log(
                    f"  TIDAK DAPAT DIAKSES (HTTP {status_code}, "
                    f"{entry.workspace_label})"
                )
            else:
                save_report(
                    conn,
                    report_id=entry.report_id,
                    workspace_id=entry.workspace_id,
                    dataset_id=dataset_id,
                    name=entry.name,
                    report_format=entry.report_format,
                    modified_at=entry.modified_at,
                    status="failed",
                    message=f"HTTP {status_code}: {message}"[:300],
                )
                counters.failed += 1
                log(f"  GAGAL: HTTP {status_code}: {message[:150]}")
            processed += 1
            continue
        except (ExtractionError, XmlaError) as exc:
            message = str(exc).splitlines()[0][:300]
            save_report(
                conn,
                report_id=entry.report_id,
                workspace_id=entry.workspace_id,
                dataset_id=dataset_id,
                name=entry.name,
                report_format=entry.report_format,
                modified_at=entry.modified_at,
                status="failed",
                message=message,
            )
            counters.failed += 1
            log(f"  GAGAL: {message}")
            processed += 1
            continue
        except Exception as exc:  # noqa: BLE001 - jangan hentikan analisa
            message = f"{type(exc).__name__}: {exc}"[:300]
            save_report(
                conn,
                report_id=entry.report_id,
                workspace_id=entry.workspace_id,
                dataset_id=dataset_id,
                name=entry.name,
                report_format=entry.report_format,
                modified_at=entry.modified_at,
                status="failed",
                message=message,
            )
            counters.failed += 1
            log(f"  GAGAL: {message}")
            processed += 1
            continue

        if usage.report_format not in SUPPORTED_FORMATS:
            message = "; ".join(usage.unresolved) or (
                f"Format definisi tidak dikenali: {usage.report_format or '(kosong)'}"
            )
            save_report(
                conn,
                report_id=entry.report_id,
                workspace_id=entry.workspace_id,
                dataset_id=dataset_id,
                name=entry.name,
                report_format=usage.report_format or entry.report_format,
                modified_at=entry.modified_at,
                status="failed",
                message=message[:300],
            )
            counters.failed += 1
            processed += 1
            log(f"  GAGAL: {message[:180]}")
            continue

        save_report(
            conn,
            report_id=entry.report_id,
            workspace_id=entry.workspace_id,
            dataset_id=dataset_id,
            name=entry.name,
            report_format=entry.report_format,
            modified_at=entry.modified_at,
            status="ok",
            usage=usage,
            message="; ".join(usage.unresolved[:3]),
        )
        counters.scanned += 1
        counters.unresolved += len(usage.unresolved)
        processed += 1

    cancel_prefetch()
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)
    if entries:
        mark_reports_inactive(
            conn, dataset_id, [entry.report_id for entry in entries]
        )
    if counters.incomplete == 0 and not counters.cancelled:
        analyzed = (
            counters.scanned
            + counters.skipped
            + counters.failed
            + counters.unsupported
            + counters.personal
            + counters.app
            + counters.inaccessible
        )
        counters.incomplete = max(0, counters.total - analyzed)
    return counters


def _recently_scanned(
    value: Any, hours: int = INACCESSIBLE_RETRY_HOURS
) -> bool:
    """True bila ``scanned_at`` masih di dalam cooldown retry."""
    text = str(value or "")
    if not text:
        return False
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - stamp < timedelta(hours=hours)


DEFINITION_POLL_WAIT = 1.0


class DefinitionLoader:
    """Unduh definisi report dengan satu klien Fabric per thread.

    Sesi ``requests`` tidak dijamin aman dipakai banyak thread sekaligus, jadi
    setiap worker mendapat kliennya sendiri. Dengan satu worker, objek ini tetap
    memakai ulang satu sesi untuk seluruh scan (menghindari handshake TLS per
    report). ``poll_wait`` tetap 1 dtk: polling lebih rapat membuat Fabric
    mengirim ``Retry-After``/throttling sehingga totalnya justru jauh lebih lama
    (diukur: 24-37 dtk/report untuk poll 0,35 dtk vs 6-12 dtk untuk 1 dtk).
    """

    def __init__(self, tokens: EntraTokens) -> None:
        self._tokens = tokens
        self._local = threading.local()
        self._clients: list[FabricReportClient] = []
        self._lock = threading.Lock()

    def __call__(self, entry: ReportEntry) -> ReportDefinition:
        client = getattr(self._local, "client", None)
        if client is None:
            client = FabricReportClient(
                fabric_provider(self._tokens),
                poll_wait=DEFINITION_POLL_WAIT,
                log=_silent,
            )
            self._local.client = client
            with self._lock:
                self._clients.append(client)
        service = ServiceReportRef.from_ids(entry.workspace_id, entry.report_id)
        return client.get_report_definition(service)

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            client.close()
        self._local = threading.local()


def _fetch_definition(
    tokens: EntraTokens, entry: ReportEntry
) -> ReportDefinition:
    """Unduh satu definisi report (tanpa cache sesi; dipakai pemanggil luar)."""
    loader = DefinitionLoader(tokens)
    try:
        return loader(entry)
    finally:
        loader.close()


# ---------------------------------------------------------------------------
# Entry point jaringan
# ---------------------------------------------------------------------------
def analyze_dataset(
    *,
    workspace_id: str,
    workspace_name: str,
    dataset_id: str,
    dataset_name: str,
    principal: ServicePrincipal,
    database: Path | str = DEFAULT_DB,
    include_other_workspaces: bool = True,
    include_personal: bool = False,
    include_reports: bool = True,
    refresh: bool = False,
    max_reports: int | None = None,
    scan_workers: int = 1,
    session: Any = None,
    log: Log = _silent,
    progress: Progress | None = None,
    should_stop: Callable[[], bool] | None = None,
    client_factory: Callable[[], Any] | None = None,
    reports_provider: Callable[..., tuple[list[ReportEntry], str, list[str]]]
    | None = None,
    definition_loader: Callable[[ReportEntry], ReportDefinition] | None = None,
) -> AnalysisResult:
    """Analisa satu semantic model (Service) tanpa mengubah model.

    ``session`` adalah koneksi SQLite in-memory milik pemanggil (web): hasil
    disimpan di sana selama sesi server dan tidak ditulis ke ``data\\*.db``.
    Tanpa ``session`` hasil ditulis ke ``database`` seperti sebelumnya (CLI/uji).
    ``include_reports=False`` melewati daftar + unduhan definisi report; verdict
    yang tidak punya referensi model menjadi ``Perlu dicek`` karena cakupan
    report memang tidak lengkap.
    """
    principal.validate()

    tokens = EntraTokens(principal)
    interactive = isinstance(principal, UserSession)
    started_at = utc_now()
    endpoint = workspace_endpoint(principal.tenant_id or "myorg", workspace_name)
    log(f"Workspace: {workspace_name}")
    log(f"Semantic model: {dataset_name}")
    log(
        f"Auth: {type(principal).__name__}; "
        f"interactive_xmla={interactive}"
    )

    if client_factory is not None:
        client = client_factory()
    else:
        try:
            if interactive:
                from .xmla_worker_client import get_worker_client

                client = get_worker_client(endpoint, dataset_name, log=log)
            else:
                client = open_client(
                    endpoint=endpoint,
                    catalog=dataset_name,
                    tokens=tokens,
                    interactive=False,
                )
        except XmlaError as exc:
            hint = (
                "Akun 365 perlu akses workspace dan XMLA Read."
                if getattr(principal, "is_user", False)
                else "service principal perlu akses ke workspace."
            )
            raise ExtractionError(
                f"Tidak bisa terhubung ke XMLA workspace '{workspace_name}': {exc}\n"
                "Dataset harus berada di kapasitas Premium/PPU/Fabric dengan "
                "XMLA Read, dan " + hint
            ) from exc
    dependencies: list[dict[str, Any]] = []
    try:
        model = LiveModel(client)
        stats = read_model_stats(client, model=model, log=log)
        metadata = read_model_metadata(model)
        try:
            dependencies = client.query("DISCOVER_CALC_DEPENDENCY")
        except XmlaError as exc:
            log(f"Dependency DMV tidak tersedia: {exc}")
    finally:
        client.close()

    if not stats.columns:
        raise ExtractionError(
            f"Semantic model '{dataset_name}' tidak mengembalikan kolom. "
            "Pastikan catalog benar dan service principal punya akses XMLA Read; "
            "snapshot lama tidak diubah."
        )

    references = model_references(model)
    measure_refs = measure_references(model)
    log(
        f"Kolom model: {len(stats.columns)}; measure: {len(stats.measures)}; "
        f"referensi model: "
        f"{sum(len(items) for items in references.values())} + "
        f"{sum(len(items) for items in measure_refs.values())} measure."
    )
    relationships = list(metadata.get("relationships") or [])
    dependency_counts = relationship_dependency_counts(dependencies)
    for relationship in relationships:
        name = str(relationship.get("name") or "")
        relationship["dependent_count"] = dependency_counts.get(name, 0)
    m_rows = m_query_rows(
        metadata.get("partitions") or [], metadata.get("expressions") or []
    )
    log(
        f"Relasi model: {len(relationships)}; dependensi relasi: "
        f"{sum(dependency_counts.values())}; M query/parameter: {len(m_rows)}."
    )

    if include_reports:
        provider = reports_provider or discover_reports
        if provider is discover_reports:
            entries, method, notes = provider(
                principal,
                dataset_id=dataset_id,
                workspace_id=workspace_id,
                include_other_workspaces=include_other_workspaces,
                database=database,
                log=log,
            )
        else:
            entries, method, notes = provider()
    else:
        entries = []
        method = "model"
        notes = [
            "Report tidak disertakan: analisa hanya memakai metadata model, "
            "jadi kolom/measure tanpa referensi model berstatus 'Perlu dicek'."
        ]
        log(notes[0])

    conn = session if session is not None else connect(database)
    owns_connection = session is None
    try:
        initialize(conn)
        save_columns(conn, dataset_id, stats.columns)
        save_measures(
            conn,
            dataset_id,
            stats.measures,
            {
                key: [
                    {
                        "kind": reference.kind,
                        "object": reference.object,
                        "detail": reference.detail,
                        "blocking": reference.blocking,
                        "source_table": reference.source_table,
                        "source_measure": reference.source_measure,
                        "depth": reference.depth,
                    }
                    for reference in items
                ]
                for key, items in measure_refs.items()
            },
        )
        save_model_refs(
            conn,
            dataset_id,
            [
                {
                    "table": table,
                    "column": column,
                    "kind": reference.kind,
                    "object": reference.object,
                    "detail": reference.detail,
                    "blocking": reference.blocking,
                    "depth": reference.depth,
                }
                for (table, column), items in references.items()
                for reference in items
            ],
        )
        save_m_queries(conn, dataset_id, m_rows)
        if include_reports:
            own_loader: DefinitionLoader | None = None
            if definition_loader is None:
                own_loader = DefinitionLoader(tokens)
                loader = own_loader
            else:
                loader = definition_loader
            try:
                counters = scan_reports(
                    conn,
                    entries,
                    dataset_id=dataset_id,
                    table_names=[table.table for table in stats.tables],
                    refresh=refresh,
                    max_reports=max_reports,
                    include_personal=include_personal,
                    definition_loader=loader,
                    scan_workers=scan_workers,
                    log=log,
                    progress=progress,
                    should_stop=should_stop,
                )
            finally:
                if own_loader is not None:
                    own_loader.close()
            if counters.scanned:
                log(
                    f"Scan report: {counters.scanned} unduh "
                    f"{counters.fetch_ms / 1000:.1f} dtk · scan definisi "
                    f"{counters.scan_ms / 1000:.1f} dtk · "
                    f"{counters.workers} worker."
                )
            usage_rows = field_usage(conn, dataset_id)
            report_rows = stored_reports(conn, dataset_id)
            page_rows = stored_report_pages(conn, dataset_id)
            unresolved_rows = stored_unresolved(conn, dataset_id)
            coverage_complete = counters.complete
            coverage = coverage_text(counters)
        else:
            counters = ScanCounters()
            usage_rows = []
            report_rows = []
            page_rows = {}
            unresolved_rows = []
            coverage_complete = False
            coverage = COVERAGE_MODEL_ONLY
        result = build_analysis(
            stats=stats,
            usage_rows=usage_rows,
            model_refs=references,
            reports=report_rows,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            method=method,
            report_total=counters.total,
            report_scanned=counters.scanned,
            report_skipped=counters.skipped,
            report_failed=counters.failed,
            coverage_complete=coverage_complete,
            coverage=coverage,
            report_personal=counters.personal,
            report_inaccessible=counters.inaccessible,
            report_app=counters.app,
            unresolved=unresolved_rows,
            measure_refs=measure_refs,
            messages=list(notes),
            relationships=relationships,
            m_queries=m_rows,
            roles=list(metadata.get("roles") or []),
            report_pages=page_rows,
            reports_included=include_reports,
        )
        save_run(
            conn,
            {
                "scan_id": uuid4().hex,
                "dataset_id": dataset_id,
                "workspace_id": workspace_id,
                "dataset_name": dataset_name,
                "started_at": started_at,
                "finished_at": utc_now(),
                "status": "cancelled" if counters.cancelled else "Succeeded",
                "message": "; ".join(result.messages)[:500],
                "report_total": counters.total,
                "report_scanned": counters.scanned,
                "report_skipped": counters.skipped,
                "report_failed": counters.failed,
                "report_unsupported": counters.unsupported,
                "report_personal": counters.personal,
                "report_inaccessible": counters.inaccessible,
                "report_app": counters.app,
                "coverage_complete": 1 if coverage_complete else 0,
                "model_json": model_snapshot(stats, workspace_name, relationships),
                "column_count": len(result.columns),
                "unused_count": len(result.unused),
                "measure_count": len(result.measures),
                "unused_measure_count": len(result.unused_measures),
                "unused_bytes": result.unused_bytes,
                "dataset_bytes": result.dataset_bytes,
                "coverage": coverage,
                "fetch_ms": counters.fetch_ms,
                "scan_ms": counters.scan_ms,
                "scan_workers": counters.workers,
            },
        )
    finally:
        if owns_connection:
            close_quietly(conn)
    log(coverage)
    return result


def model_snapshot(
    stats: ModelStats,
    workspace_name: str = "",
    relationships: Iterable[dict[str, Any]] | None = None,
) -> str:
    """JSON ringkas metadata model untuk memulihkan snapshot tanpa XMLA."""
    payload = {
        "model_name": stats.model_name,
        "workspace_name": workspace_name,
        "compatibility_level": stats.compatibility_level,
        "last_update": stats.last_update,
        "segment_bytes": stats.segment_bytes,
        "artifact_bytes": stats.artifact_bytes,
        "note": stats.note,
        "tables": [
            {
                "table": table.table,
                "column_count": table.column_count,
                "rows": table.rows,
                "size_data_bytes": table.size_data_bytes,
                "size_hierarchy_bytes": table.size_hierarchy_bytes,
                "size_dictionary_bytes": table.size_dictionary_bytes,
                "storage_mode": table.storage_mode,
                "measure_count": table.measure_count,
                "partition_count": table.partition_count,
                "is_hidden": table.is_hidden,
                "data_category": table.data_category,
                "description": table.description,
                "is_calculated_table": table.is_calculated_table,
            }
            for table in stats.tables
        ],
        "relationships": list(relationships or []),
    }
    return json.dumps(payload, ensure_ascii=False)


def load_snapshot(
    database: Path | str, dataset_id: str
) -> AnalysisResult | None:
    """Pulihkan hasil analisa terakhir dari file SQLite (tanpa XMLA/jaringan)."""
    path = Path(database).expanduser()
    if not path.exists():
        return None
    conn = connect(path)
    try:
        return snapshot_from_connection(conn, dataset_id)
    finally:
        close_quietly(conn)


def snapshot_from_connection(
    conn: Any, dataset_id: str
) -> AnalysisResult | None:
    """Susun hasil analisa terakhir dari koneksi (file atau sesi in-memory).

    Dipakai sesi web agar hasil terakhir langsung tampil tanpa menulis ke
    database, dan ekspor tetap memakai data yang sama dengan tampilan.
    """
    initialize(conn)
    run = last_run(conn, dataset_id)
    if not run:
        return None
    rows = stored_columns(conn, dataset_id)
    if not rows:
        return None
    meta: dict[str, Any] = {}
    if run.get("model_json"):
        try:
            meta = json.loads(str(run["model_json"]))
        except json.JSONDecodeError:
            meta = {}
    columns = [
        ColumnStat(
            table=str(row["table_name"]),
            column=str(row["column_name"]),
            column_id=int(row["column_id"] or 0),
            column_type=str(row["column_type"] or ""),
            data_type=str(row["data_type"] or ""),
            format_string=str(row["format_string"] or ""),
            display_folder=str(row["display_folder"] or ""),
            is_hidden=bool(row["is_hidden"]),
            is_calculated=bool(row["is_calculated"]),
            sort_by_column=str(row["sort_by_column"] or ""),
            expression=str(row["expression"] or ""),
            size_data_bytes=int(row["size_data_bytes"] or 0),
            size_hierarchy_bytes=int(row["size_hierarchy_bytes"] or 0),
            rows=int(row["row_count"] or 0),
            error_message=str(row["error_message"] or ""),
            size_dictionary_bytes=int(
                row.get("size_dictionary_bytes") or 0
            ),
            cardinality=int(row.get("cardinality") or 0),
            data_category=str(row.get("data_category") or ""),
            summarize_by=str(row.get("summarize_by") or ""),
            is_key=bool(row.get("is_key")),
            is_available_in_mdx=bool(row.get("is_available_in_mdx", 1)),
            source_column=str(row.get("source_column") or ""),
            description=str(row.get("description") or ""),
        )
        for row in rows
    ]
    tables = [
        TableStat(
            table=str(item.get("table") or ""),
            column_count=int(item.get("column_count") or 0),
            rows=int(item.get("rows") or 0),
            size_data_bytes=int(item.get("size_data_bytes") or 0),
            size_hierarchy_bytes=int(item.get("size_hierarchy_bytes") or 0),
            size_dictionary_bytes=int(
                item.get("size_dictionary_bytes") or 0
            ),
            storage_mode=str(item.get("storage_mode") or ""),
            measure_count=int(item.get("measure_count") or 0),
            partition_count=int(item.get("partition_count") or 0),
            is_hidden=bool(item.get("is_hidden")),
            data_category=str(item.get("data_category") or ""),
            description=str(item.get("description") or ""),
            is_calculated_table=bool(item.get("is_calculated_table")),
        )
        for item in meta.get("tables") or []
    ]
    stats = ModelStats(
        model_name=str(meta.get("model_name") or run.get("dataset_name") or ""),
        compatibility_level=meta.get("compatibility_level"),
        last_update=str(meta.get("last_update") or ""),
        columns=columns,
        tables=tables,
        segment_bytes=int(meta.get("segment_bytes") or 0),
        artifact_bytes=int(meta.get("artifact_bytes") or 0),
        note=str(meta.get("note") or ""),
    )
    references: dict[tuple[str, str], list[ModelReference]] = {
        key: [
            ModelReference(
                kind=str(item.get("kind") or ""),
                object=str(item.get("object") or ""),
                detail=str(item.get("detail") or ""),
                blocking=bool(item.get("blocking")),
                source_table=str(item.get("source_table") or ""),
                source_measure=str(item.get("source_measure") or ""),
                depth=max(
                    int(item.get("depth") or 1),
                    reference_depth(str(item.get("detail") or "")),
                ),
            )
            for item in items
        ]
        for key, items in stored_model_refs(conn, dataset_id).items()
    }
    measure_data = stored_measures(conn, dataset_id)
    measures = [
        MeasureStat(
            table=str(row.get("table_name") or ""),
            measure=str(row.get("measure_name") or ""),
            data_type=str(row.get("data_type") or ""),
            format_string=str(row.get("format_string") or ""),
            display_folder=str(row.get("display_folder") or ""),
            is_hidden=bool(row.get("is_hidden")),
            expression=str(row.get("expression") or ""),
            error_message=str(row.get("error_message") or ""),
            description=str(row.get("description") or ""),
        )
        for row in measure_data
    ]
    stats = replace(stats, measures=measures)
    measure_refs: dict[tuple[str, str], list[ModelReference]] = {
        (
            str(row.get("table_name") or "").casefold(),
            str(row.get("measure_name") or "").casefold(),
        ): [
            ModelReference(
                kind=str(item.get("kind") or ""),
                object=str(item.get("object") or ""),
                detail=str(item.get("detail") or ""),
                blocking=bool(item.get("blocking")),
                source_table=str(item.get("source_table") or ""),
                source_measure=str(item.get("source_measure") or ""),
                depth=max(
                    int(item.get("depth") or 1),
                    reference_depth(str(item.get("detail") or "")),
                ),
            )
            for item in row.get("refs") or []
        ]
        for row in measure_data
    }
    relationships = [
        dict(item)
        for item in (meta.get("relationships") or [])
        if isinstance(item, dict)
    ]
    coverage = str(run.get("coverage") or "")
    reports_included = coverage != COVERAGE_MODEL_ONLY
    result = build_analysis(
        stats=stats,
        usage_rows=field_usage(conn, dataset_id) if reports_included else [],
        model_refs=references,
        reports=stored_reports(conn, dataset_id) if reports_included else [],
        dataset_id=dataset_id,
        dataset_name=str(run.get("dataset_name") or ""),
        workspace_id=str(run.get("workspace_id") or ""),
        workspace_name=str(meta.get("workspace_name") or ""),
        method="cache",
        report_total=int(run.get("report_total") or 0),
        report_scanned=int(run.get("report_scanned") or 0),
        report_skipped=int(run.get("report_skipped") or 0),
        report_failed=int(run.get("report_failed") or 0),
        coverage_complete=bool(run.get("coverage_complete")),
        coverage=coverage,
        report_personal=int(run.get("report_personal") or 0),
        report_inaccessible=int(run.get("report_inaccessible") or 0),
        report_app=int(run.get("report_app") or 0),
        report_pages=(
            stored_report_pages(conn, dataset_id) if reports_included else {}
        ),
        unresolved=(
            stored_unresolved(conn, dataset_id) if reports_included else []
        ),
        measure_refs=measure_refs,
        messages=[],
        analyzed_at=str(run.get("finished_at") or ""),
        relationships=relationships,
        m_queries=stored_m_queries(conn, dataset_id),
        reports_included=reports_included,
    )
    return result


def coverage_text(counters: ScanCounters) -> str:
    parts = [
        f"{counters.total} report",
        f"{counters.scanned} dipindai",
        f"{counters.skipped} dari cache",
    ]
    if counters.failed:
        parts.append(f"{counters.failed} gagal")
    if counters.inaccessible:
        parts.append(f"{counters.inaccessible} tidak dapat diakses")
    if counters.unsupported:
        parts.append(f"{counters.unsupported} format RDL")
    if counters.personal:
        parts.append(f"{counters.personal} personal dilewati")
    if counters.app:
        parts.append(f"{counters.app} App dilewati")
    if counters.unresolved:
        parts.append(f"{counters.unresolved} field tak terpetakan")
    if counters.incomplete:
        parts.append(f"{counters.incomplete} belum dipindai")
    if counters.cancelled:
        parts.append("dibatalkan")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Ekspor
# ---------------------------------------------------------------------------
def column_rows(result: AnalysisResult) -> list[dict[str, Any]]:
    """Baris ringkas per kolom untuk tree GUI (``analysis`` menyimpan objeknya)."""
    rows: list[dict[str, Any]] = []
    for column in result.columns:
        rows.append(
            {
                "name": column.column.column,
                "type": column.column.column_type,
                "table": column.column.table,
                "data_type": column.column.data_type,
                "size": format_bytes(column.size_bytes),
                "size_bytes": column.size_bytes,
                "status": column.status,
                "uses": column.use_count,
                "direct_refs": len(column.counted_refs),
                "transitive_refs": len(column.transitive_refs),
                "reports": column.report_count,
                "format_string": column.column.format_string,
                "has_error": column.column.has_error,
                "display_folder": column.column.display_folder,
                "reason": column.reason,
                "analysis": column,
            }
        )
    return rows


def measure_rows(result: AnalysisResult) -> list[dict[str, Any]]:
    """Baris ringkas per measure untuk tree GUI (``analysis`` objeknya)."""
    rows: list[dict[str, Any]] = []
    for item in result.measures:
        rows.append(
            {
                "name": item.measure.measure,
                "type": (
                    "measure (hidden)"
                    if item.measure.is_hidden
                    else "measure"
                ),
                "table": item.measure.table,
                "data_type": item.measure.data_type,
                "size": "-",
                "size_bytes": 0,
                "status": item.status,
                "uses": item.use_count,
                "direct_refs": len(item.counted_refs),
                "transitive_refs": len(item.transitive_refs),
                "reports": item.report_count,
                "format_string": item.measure.format_string,
                "has_error": item.measure.has_error,
                "display_folder": item.measure.display_folder,
                "reason": item.reason,
                "analysis": item,
            }
        )
    return rows


def report_url(workspace_id: str, report_id: str) -> str:
    """URL report Power BI Service (untuk tombol buka report di GUI)."""
    workspace = str(workspace_id or "").strip()
    report = str(report_id or "").strip()
    if not workspace or not report:
        return ""
    return f"https://app.powerbi.com/groups/{workspace}/reports/{report}"


def write_workbook(result: AnalysisResult, target: Path | str) -> Path:
    """Tulis hasil analisa ke workbook XLSX (header Inggris)."""
    path = Path(target).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    best_practice = build_best_practice(result)

    summary_rows = [
        ("Dataset", result.dataset_name),
        ("Workspace", result.workspace_name),
        ("Dataset ID", result.dataset_id),
        ("Analyzed at", result.analyzed_at),
        ("Model size", format_bytes(result.dataset_bytes)),
        ("Data size", format_bytes(result.stats.data_bytes)),
        ("Hierarchy size", format_bytes(result.stats.hierarchy_bytes)),
        ("Dictionary size", format_bytes(result.stats.dictionary_bytes)),
        ("Columns", len(result.columns)),
        ("Unused columns", len(result.unused)),
        ("Measures", len(result.measures)),
        ("Unused measures", len(result.unused_measures)),
        ("Unused size", format_bytes(result.unused_bytes)),
        ("Reports", result.report_total),
        ("Reports scanned", result.report_scanned),
        ("Reports from cache", result.report_skipped),
        ("Reports failed", result.report_failed),
        ("Reports personal skipped", result.report_personal),
        ("Reports App skipped", result.report_app),
        ("Reports inaccessible", result.report_inaccessible),
        ("Unresolved fields", len(result.unresolved)),
        ("Report list", result.method),
        ("Coverage", result.coverage),
        ("Coverage complete", "Yes" if result.coverage_complete else "No"),
        ("Best practice score", best_practice.get("score", 0)),
        ("Best practice verdict", best_practice.get("verdict", "-")),
        (
            "Best practice rules",
            f"{best_practice.get('evaluated', 0)}/{best_practice.get('rule_count', 0)} evaluated",
        ),
    ]
    for status, count in sorted(result.status_counts.items()):
        summary_rows.append((f"Status column {status}", count))
    for status, count in sorted(result.measure_status_counts.items()):
        summary_rows.append((f"Status measure {status}", count))
    for message in result.messages:
        summary_rows.append(("Note", message))
    summary = pd.DataFrame(summary_rows, columns=["Item", "Value"])

    column_rows = [
        {
            "Table": column.column.table,
            "Column": column.column.column,
            "Type": column.column.column_type,
            "Data type": column.column.data_type,
            "Status": column.status,
            "Size": format_bytes(column.size_bytes),
            "Size bytes": column.size_bytes,
            "Data bytes": column.column.size_data_bytes,
            "Hierarchy bytes": column.column.size_hierarchy_bytes,
            "Dictionary bytes": column.column.size_dictionary_bytes,
            "Rows": column.column.rows,
            "Uses": column.use_count,
            "Reports": column.report_count,
            "Direct references": len(column.counted_refs),
            "Transitive references": len(column.transitive_refs),
            "Format string": column.column.format_string,
            "Has error": "Yes" if column.column.has_error else "No",
            "Hidden": "Yes" if column.column.is_hidden else "No",
            "Display folder": column.column.display_folder,
            "Note": column.reason,
        }
        for column in result.columns
    ]

    report_usage_rows = []
    model_usage_rows = []
    objects = [
        (
            column.column.table,
            column.column.column,
            column.report_records,
            column.model_refs,
        )
        for column in result.columns
    ]
    objects += [
        (
            measure.measure.table,
            measure.measure.measure,
            measure.report_records,
            measure.model_refs,
        )
        for measure in result.measures
    ]
    for table_name, object_name, records, refs in objects:
        for record in records:
            report_usage_rows.append(
                {
                    "Table": table_name,
                    "Column": object_name,
                    "Report": record.get("report_name") or "",
                    "Report ID": record.get("report_id") or "",
                    "Workspace": record.get("report_workspace") or "",
                    "Page": record.get("page_name") or "",
                    "Visual": record.get("visual_title") or "",
                    "Visual type": record.get("visual_type") or "",
                    "Usage": record.get("usage_kind") or "",
                    "Field kind": record.get("field_kind") or "",
                    "Aggregation": record.get("aggregation") or "",
                    "Detail": record.get("detail") or "",
                    "Visual hidden": "Yes" if record.get("is_hidden") else "No",
                }
            )
        for reference in refs:
            model_usage_rows.append(
                {
                    "Table": table_name,
                    "Column": object_name,
                    "Kind": reference.kind,
                    "Object": reference.object,
                    "Detail": reference.detail,
                    "Depth": int(getattr(reference, "depth", 1) or 1),
                    "Blocking": "Yes" if reference.blocking else "No",
                }
            )

    report_rows = [
        {
            "Report": row.get("name") or "",
            "Report ID": row.get("report_id") or "",
            "Workspace ID": row.get("workspace_id") or "",
            "Format": row.get("report_format") or "",
            "Modified at": row.get("modified_at") or "",
            "Scanned at": row.get("scanned_at") or "",
            "Status": row.get("status") or "",
            "Pages": row.get("page_count") or 0,
            "Visuals": row.get("visual_count") or 0,
            "Fields": row.get("field_count") or 0,
            "Unresolved": row.get("unresolved_count") or 0,
            "Message": row.get("message") or "",
            "Active": "Yes" if row.get("is_active") else "No",
        }
        for row in result.reports
    ]

    table_rows = [
        {
            "Table": table.table,
            "Columns": table.column_count,
            "Rows": table.rows,
            "Size": format_bytes(table.size_total_bytes),
            "Size bytes": table.size_total_bytes,
            "Data bytes": table.size_data_bytes,
            "Hierarchy bytes": table.size_hierarchy_bytes,
            "Dictionary bytes": table.size_dictionary_bytes,
        }
        for table in result.stats.tables
    ]

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        write_sheet(writer, summary, "01_Summary", {"Item": 28, "Value": 80})
        write_sheet(
            writer,
            pd.DataFrame(column_rows),
            "02_Columns",
            {"Table": 24, "Column": 34, "Status": 22, "Note": 60},
        )
        write_sheet(
            writer,
            pd.DataFrame(report_usage_rows, columns=REPORT_USAGE_COLUMNS),
            "03_Report_Usage",
            {"Report": 40, "Page": 28, "Visual": 34, "Detail": 40},
        )
        write_sheet(
            writer,
            pd.DataFrame(model_usage_rows, columns=MODEL_USAGE_COLUMNS),
            "04_Model_Usage",
            {"Object": 34, "Detail": 56, "Depth": 8},
        )
        write_sheet(
            writer,
            pd.DataFrame(report_rows, columns=REPORT_COLUMNS),
            "05_Reports",
            {"Report": 40, "Message": 60},
        )
        write_sheet(writer, pd.DataFrame(table_rows), "06_Tables", {"Table": 28})
        write_sheet(
            writer,
            pd.DataFrame(
                [
                    {
                        "Report": row.get("report_name")
                        or row.get("report_id")
                        or "",
                        "Page": row.get("page_name") or "",
                        "Visual": row.get("visual_title") or "",
                        "Query Ref": row.get("query_ref") or "",
                        "Reason": row.get("reason") or "",
                    }
                    for row in result.unresolved
                ],
                columns=UNRESOLVED_COLUMNS,
            ),
            "07_Unresolved",
            {"Report": 40, "Page": 26, "Visual": 34, "Query Ref": 46, "Reason": 50},
        )
        write_sheet(
            writer,
            pd.DataFrame(
                [
                    {
                        "Table": item.measure.table,
                        "Measure": item.measure.measure,
                        "Data type": item.measure.data_type,
                        "Status": item.status,
                        "Uses": item.use_count,
                        "Reports": item.report_count,
                        "Direct references": len(item.counted_refs),
                        "Transitive references": len(item.transitive_refs),
                        "Format string": item.measure.format_string,
                        "Hidden": "Yes" if item.measure.is_hidden else "No",
                        "Display folder": item.measure.display_folder,
                        "Expression": item.measure.expression,
                        "Note": item.reason,
                    }
                    for item in result.measures
                ],
                columns=MEASURE_COLUMNS,
            ),
            "08_Measures",
            {"Table": 24, "Measure": 34, "Expression": 70, "Note": 50},
        )
        health = build_health(result)
        health_rows = []
        for item in health["items"]:
            kind = str(item.get("kind") or "")
            size_bytes = int(item.get("size_bytes") or 0)
            health_rows.append(
                {
                    "Severity": str(item.get("severity") or "").title(),
                    "Area": str(item.get("area") or "").title(),
                    "Rule": str(item.get("rule") or ""),
                    "Object": str(item.get("object") or ""),
                    "Table": str(item.get("table") or ""),
                    "Column": str(item.get("name") or "")
                    if kind == "column"
                    else "",
                    "Measure": str(item.get("name") or "")
                    if kind == "measure"
                    else "",
                    "Report": str(item.get("report_name") or ""),
                    "Page": str(item.get("page_name") or ""),
                    "Visual": str(item.get("visual_title") or ""),
                    "Size": format_bytes(size_bytes) if size_bytes else "",
                    "Detail": str(item.get("detail") or ""),
                    "Metrics": "; ".join(
                        f"{key}={value}"
                        for key, value in (item.get("metrics") or {}).items()
                    ),
                }
            )
        write_sheet(
            writer,
            pd.DataFrame(health_rows, columns=HEALTH_COLUMNS),
            "09_Health",
            {"Object": 40, "Detail": 56, "Metrics": 40},
        )
        best_practice_rows = [
            {
                "Rule ID": str(item.get("rule_id") or ""),
                "Rule": str(item.get("rule_name") or ""),
                "Category": str(item.get("category") or ""),
                "Severity": int(item.get("severity") or 0),
                "Object": str(item.get("object") or ""),
                "Table": str(item.get("table") or ""),
                "Name": str(item.get("name") or ""),
                "Kind": str(item.get("kind") or ""),
                "Detail": str(item.get("detail") or ""),
                "Size": format_bytes(int(item.get("size_bytes") or 0))
                if int(item.get("size_bytes") or 0)
                else "",
                "Rule score": int(item.get("rule_score") or 0),
            }
            for item in best_practice.get("items", [])
        ]
        write_sheet(
            writer,
            pd.DataFrame(best_practice_rows, columns=BEST_PRACTICE_COLUMNS),
            "10_BestPractice_Model",
            {"Rule": 44, "Object": 44, "Detail": 40},
        )
        status_labels = {
            "violation": "Violation",
            "pass": "Pass",
            "not_evaluated": "Not evaluated",
            "needs_coverage": "Needs coverage",
        }
        best_practice_rule_rows = [
            {
                "Rule ID": str(row.get("id") or ""),
                "Rule": str(row.get("name") or ""),
                "Category": str(row.get("category") or ""),
                "Severity": int(row.get("severity") or 0),
                "Status": status_labels.get(
                    str(row.get("status") or ""), str(row.get("status") or "")
                ),
                "Findings": int(row.get("count") or 0),
                "Score": int(row.get("score") or 0),
                "Reason": str(row.get("reason") or ""),
            }
            for row in best_practice.get("rules", [])
        ]
        if not best_practice_rule_rows and best_practice.get("error"):
            best_practice_rule_rows = [
                {
                    "Rule ID": "",
                    "Rule": "Catalog unavailable",
                    "Category": "",
                    "Severity": 0,
                    "Status": "Not evaluated",
                    "Findings": 0,
                    "Score": 0,
                    "Reason": str(best_practice.get("error") or ""),
                }
            ]
        write_sheet(
            writer,
            pd.DataFrame(best_practice_rule_rows, columns=BEST_PRACTICE_RULE_COLUMNS),
            "11_BestPractice_Model_Rules",
            {"Rule": 50, "Reason": 56},
        )
    return path


def output_file_name(dataset_name: str, dataset_id: str) -> str:
    """Nama file bawaan: ``Analisa_Semantic_Model_<nama>_<id8>.xlsx``."""
    name = re.sub(r'[<>:"/\\|?*]+', " ", str(dataset_name or "")).strip()
    name = re.sub(r"\s+", " ", name) or "Semantic Model"
    suffix = str(dataset_id or "").replace("-", "")[:8]
    return f"Analisa_Semantic_Model_{name}_{suffix}.xlsx"


def resolve_names(
    database: Path | str,
    workspace_id: str,
    dataset_id: str,
) -> tuple[str, str]:
    """Nama workspace + dataset dari katalog SQLite (untuk endpoint XMLA/catalog)."""
    from .lineage_service import node_detail, workspace_detail

    workspace = workspace_detail(database, workspace_id)
    dataset = node_detail(database, dataset_id)
    workspace_name = workspace.name if workspace else ""
    dataset_name = str((dataset or {}).get("name") or "")
    missing = [
        label
        for label, value in (
            ("nama workspace", workspace_name),
            ("nama semantic model", dataset_name),
        )
        if not value
    ]
    if missing:
        raise ExtractionError(
            "Tidak bisa menentukan "
            + " dan ".join(missing)
            + " dari katalog. Jalankan Sinkronisasi data di tab Pengaturan "
            "(atau scan lineage), lalu coba lagi."
        )
    return workspace_name, dataset_name



def last_analysis_run(
    database: Path | str, dataset_id: str
) -> dict[str, Any] | None:
    """Riwayat analisa terakhir untuk satu dataset (read-only ringan)."""
    path = Path(database).expanduser()
    if not path.exists():
        return None
    conn = connect(path)
    try:
        initialize(conn)
        return last_run(conn, dataset_id)
    finally:
        close_quietly(conn)
