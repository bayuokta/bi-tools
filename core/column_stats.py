"""Ukuran kolom/tabel semantic model dari DMV VertiPaq (read-only).

Used tab **Analisa Semantic Model** dan CLI. Modul ini tidak menulis apa pun
ke model; hanya SELECT ke DMV dan TMSCHEMA.

Sumber angka:

- ``DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS`` -> ``USED_SIZE`` per segmen.
  ``COLUMN_ID`` berisi ``"Nama Kolom (123)"`` pada engine saat ini, dan angka
  dalam kurung adalah ``TMSCHEMA_COLUMNS.ID``; engine lama bisa memberi angka
  langsung. Keduanya ditangani oleh :func:`storage_key`.
- Baris ``POS_TO_ID``/``ID_TO_POS`` adalah hierarki atribut (bukan kolom model).
  Ukurannya diatribusikan ke kolom lewat ``TABLE_ID`` berbentuk
  ``H$Tabel (22)$Nama Kolom (16923)``.
- ``DISCOVER_STORAGE_TABLES``/``TMSCHEMA_PARTITIONS`` tidak dipakai untuk baris:
  satu tabel bisa punya banyak partisi (RLS/incremental), jadi jumlah baris
  dihitung dari ``RECORDS_COUNT`` segmen per kolom.

Kolom ``rowNumber`` (``TMSCHEMA_COLUMNS.Type = 3``) adalah objek internal dan
tidak ditampilkan, sama seperti VertiPaq Analyzer/Bravo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

from .errors import ExtractionError
from .model import LiveModel, build_columns, build_measures, build_tables
from .xmla_client import XmlaError

Log = Callable[[str], None]

STORAGE_DMV = "DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS"
STORAGE_COLUMNS_DMV = "DISCOVER_STORAGE_TABLE_COLUMNS"
STORAGE_TABLES_DMV = "DISCOVER_STORAGE_TABLES"
COLUMN_STORAGES_DMV = "TMSCHEMA_COLUMN_STORAGES"

BASIC_COLUMN_TYPES = {"BASIC_DATA"}
ARTIFACT_IDS = {"POS_TO_ID", "ID_TO_POS", "INDEX"}
STORAGE_ID_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<id>\d+)\)$")


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


# ---------------------------------------------------------------------------
# Pemetaan ID storage
# ---------------------------------------------------------------------------
def storage_key(value: Any) -> tuple[str, int | None]:
    """Pisahkan ``"Nama Kolom (123)"`` menjadi ``("Nama Kolom", 123)``.

    Engine lama memberi ``COLUMN_ID`` sebagai angka; nilai seperti ``POS_TO_ID``
    tidak punya ID dan dikembalikan dengan ``None``.
    """
    if isinstance(value, bool):
        return str(value), None
    if isinstance(value, int):
        return "", value
    text = str(value or "").strip()
    if not text:
        return "", None
    match = STORAGE_ID_RE.match(text)
    if match:
        return match.group("name").strip(), int(match.group("id"))
    if text.isdigit():
        return "", int(text)
    return text, None


def attribute_id(table_id: Any) -> int | None:
    """Ambil ID atribut dari ``TABLE_ID`` hierarki (``H$Tabel (19)$Kolom (16923)``)."""
    text = str(table_id or "").strip()
    if not text:
        return None
    match = STORAGE_ID_RE.match(text)
    if not match:
        return None
    return int(match.group("id"))


def is_artifact(column_id: Any) -> bool:
    """True untuk objek internal storage (POS_TO_ID/ID_TO_POS/INDEX)."""
    text = str(column_id or "").strip().upper()
    return text in ARTIFACT_IDS


# ---------------------------------------------------------------------------
# Agregasi segmen
# ---------------------------------------------------------------------------
@dataclass
class StorageSizes:
    """Hasil agregasi DMV storage per ``TMSCHEMA_COLUMNS.ID``."""

    data_bytes: dict[int, int] = field(default_factory=dict)
    hierarchy_bytes: dict[int, int] = field(default_factory=dict)
    dictionary_bytes: dict[int, int] = field(default_factory=dict)
    rows: dict[int, int] = field(default_factory=dict)
    segment_bytes: int = 0
    unmatched_segments: int = 0
    artifact_bytes: int = 0

    def data(self, column_id: int) -> int:
        return self.data_bytes.get(column_id, 0)

    def hierarchy(self, column_id: int) -> int:
        return self.hierarchy_bytes.get(column_id, 0)

    def dictionary(self, column_id: int) -> int:
        return self.dictionary_bytes.get(column_id, 0)

    def total(self, column_id: int) -> int:
        return (
            self.data(column_id)
            + self.hierarchy(column_id)
            + self.dictionary(column_id)
        )

    def row_count(self, column_id: int) -> int:
        return self.rows.get(column_id, 0)


def _size(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def aggregate_segments(
    segments: list[dict[str, Any]],
    storage_columns: list[dict[str, Any]] | None = None,
) -> StorageSizes:
    """Jumlahkan ``USED_SIZE`` per kolom dari baris segmen VertiPaq.

    ``storage_columns`` dipakai untuk ukuran dictionary per kolom
    (``DICTIONARY_SIZE``) dan sebagai cadangan untuk model Direct Lake yang
    tidak resident (``STRING_INDEX_SIZE``). Dictionary disimpan sekali per
    atribut (baris ``BASIC_DATA``) agar tidak dobel dengan ``POS_TO_ID``.
    """
    result = StorageSizes()
    known_column_ids: set[int] = set()
    for row in storage_columns or []:
        _name, column_id = storage_key(row.get("COLUMN_ID"))
        if column_id is None:
            continue
        known_column_ids.add(column_id)
        if str(row.get("COLUMN_TYPE") or "").upper() not in BASIC_COLUMN_TYPES:
            continue
        dictionary = _size(row.get("DICTIONARY_SIZE"))
        if dictionary:
            result.dictionary_bytes[column_id] = max(
                result.dictionary_bytes.get(column_id, 0), dictionary
            )

    for row in segments:
        size = _size(row.get("USED_SIZE"))
        result.segment_bytes += size
        raw_type = str(row.get("COLUMN_TYPE") or "").upper()
        raw_id = row.get("COLUMN_ID")
        # Segmen hierarki atribut dikenali dari COLUMN_ID (POS_TO_ID/ID_TO_POS);
        # COLUMN_TYPE hanya ada di DISCOVER_STORAGE_TABLE_COLUMNS, bukan di sini.
        if is_artifact(raw_id):
            owner = attribute_id(row.get("TABLE_ID"))
            if owner is not None:
                result.hierarchy_bytes[owner] = (
                    result.hierarchy_bytes.get(owner, 0) + size
                )
            else:
                result.artifact_bytes += size
            continue
        _name, column_id = storage_key(raw_id)
        if column_id is None:
            result.unmatched_segments += 1
            result.artifact_bytes += size
            continue
        if raw_type and raw_type not in BASIC_COLUMN_TYPES:
            result.artifact_bytes += size
            continue
        result.data_bytes[column_id] = result.data_bytes.get(column_id, 0) + size
        records = _size(row.get("RECORDS_COUNT"))
        if records:
            result.rows[column_id] = max(result.rows.get(column_id, 0), records)

    # Cadangan Direct Lake/non-resident: segmen tidak ada tetapi dictionary ada.
    if not result.data_bytes:
        for row in storage_columns or []:
            _name, column_id = storage_key(row.get("COLUMN_ID"))
            if column_id is None or column_id not in known_column_ids:
                continue
            if str(row.get("COLUMN_TYPE") or "").upper() not in BASIC_COLUMN_TYPES:
                continue
            fallback = _size(row.get("DICTIONARY_SIZE")) + _size(
                row.get("STRING_INDEX_SIZE")
            )
            if fallback:
                result.data_bytes[column_id] = fallback
    return result


def table_rows(sizes: StorageSizes, column_ids: list[int]) -> int:
    """Jumlah baris tabel dari kolom dengan ``RECORDS_COUNT`` terbesar."""
    return max((sizes.row_count(column_id) for column_id in column_ids), default=0)


def partition_row_counts(
    segments: Iterable[Mapping[str, Any]],
) -> dict[tuple[str, str], int]:
    """Jumlah baris per partisi dari segmen ``DISCOVER_STORAGE_TABLE_COLUMN_SEGMENTS``.

    Satu partisi punya banyak segmen kolom; jumlah barisnya adalah
    ``RECORDS_COUNT`` terbesar di antara segmen data biasa. Artefak hierarki
    (``POS_TO_ID``/``ID_TO_POS``/``INDEX``) dan segmen non-data dilewati.
    Partisi tanpa segmen tidak diberi entri agar UI bisa membedakan "tidak
    diketahui" dari nol baris.
    """
    counts: dict[tuple[str, str], int] = {}
    for row in segments:
        raw_id = row.get("COLUMN_ID")
        if is_artifact(raw_id):
            continue
        raw_type = str(row.get("COLUMN_TYPE") or "").upper()
        if raw_type and raw_type not in BASIC_COLUMN_TYPES:
            continue
        table = str(
            row.get("MEASURE_GROUP_NAME") or row.get("TABLE_NAME") or ""
        ).strip()
        partition = str(row.get("PARTITION_NAME") or "").strip()
        if not table or not partition:
            continue
        key = (table, partition)
        counts[key] = max(counts.get(key, 0), _size(row.get("RECORDS_COUNT")))
    return counts


# ---------------------------------------------------------------------------
# Hasil
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ColumnStat:
    """Satu kolom model beserta ukuran VertiPaq-nya."""

    table: str
    column: str
    column_id: int
    column_type: str
    data_type: str
    format_string: str
    display_folder: str
    is_hidden: bool
    is_calculated: bool
    sort_by_column: str
    expression: str
    size_data_bytes: int
    size_hierarchy_bytes: int
    rows: int
    error_message: str = ""
    size_dictionary_bytes: int = 0
    cardinality: int = 0
    data_category: str = ""
    summarize_by: str = ""
    is_key: bool = False
    is_available_in_mdx: bool = True
    source_column: str = ""
    description: str = ""

    @property
    def size_total_bytes(self) -> int:
        return (
            self.size_data_bytes
            + self.size_hierarchy_bytes
            + self.size_dictionary_bytes
        )

    @property
    def has_error(self) -> bool:
        return bool(self.error_message)

    @property
    def key(self) -> tuple[str, str]:
        return (self.table.casefold(), self.column.casefold())


@dataclass(frozen=True)
class TableStat:
    """Ringkasan satu tabel model."""

    table: str
    column_count: int
    rows: int
    size_data_bytes: int
    size_hierarchy_bytes: int
    size_dictionary_bytes: int = 0
    storage_mode: str = ""
    measure_count: int = 0
    partition_count: int = 0
    is_hidden: bool = False
    data_category: str = ""
    description: str = ""
    is_calculated_table: bool = False
    table_id: int = 0

    @property
    def size_total_bytes(self) -> int:
        return (
            self.size_data_bytes
            + self.size_hierarchy_bytes
            + self.size_dictionary_bytes
        )


@dataclass(frozen=True)
class MeasureStat:
    """Satu measure model (tanpa ukuran VertiPaq)."""

    table: str
    measure: str
    data_type: str = ""
    format_string: str = ""
    display_folder: str = ""
    is_hidden: bool = False
    expression: str = ""
    error_message: str = ""
    description: str = ""
    measure_id: int = 0

    @property
    def key(self) -> tuple[str, str]:
        return (self.table.casefold(), self.measure.casefold())

    @property
    def has_error(self) -> bool:
        return bool(self.error_message)


@dataclass
class ModelStats:
    """Ukuran semantic model: kolom, tabel, dan total."""

    model_name: str
    compatibility_level: Any
    last_update: str
    columns: list[ColumnStat]
    tables: list[TableStat]
    segment_bytes: int
    artifact_bytes: int
    note: str = ""
    measures: list[MeasureStat] = field(default_factory=list)

    @property
    def data_bytes(self) -> int:
        return sum(column.size_data_bytes for column in self.columns)

    @property
    def hierarchy_bytes(self) -> int:
        return sum(column.size_hierarchy_bytes for column in self.columns)

    @property
    def dictionary_bytes(self) -> int:
        return sum(column.size_dictionary_bytes for column in self.columns)

    @property
    def dataset_bytes(self) -> int:
        return self.data_bytes + self.hierarchy_bytes + self.dictionary_bytes

    def sizes(self) -> dict[tuple[str, str], ColumnStat]:
        return {column.key: column for column in self.columns}


def column_cardinality(
    rows: Iterable[dict[str, Any]] | None,
) -> dict[int, int]:
    """Peta ``COLUMN_ID -> Statistics_DistinctStates`` dari TMSCHEMA."""
    counts: dict[int, int] = {}
    for row in rows or []:
        raw_id = row.get("ColumnID", row.get("COLUMN_ID"))
        _name, column_id = storage_key(raw_id)
        if column_id is None:
            continue
        value = _size(row.get("Statistics_DistinctStates"))
        counts[column_id] = max(counts.get(column_id, 0), value)
    return counts


def build_model_stats(
    model: LiveModel,
    segments: list[dict[str, Any]],
    storage_columns: list[dict[str, Any]] | None = None,
    *,
    column_storages: list[dict[str, Any]] | None = None,
    note: str = "",
) -> ModelStats:
    """Susun :class:`ModelStats` dari ``LiveModel`` + baris DMV storage."""
    sizes = aggregate_segments(segments, storage_columns)
    cardinalities = column_cardinality(column_storages)
    columns, _excluded, _warnings = build_columns(model)
    tables = build_tables(model)
    measures = build_measures(model)

    column_stats: list[ColumnStat] = []
    columns_by_table: dict[str, list[int]] = {}
    for row in columns:
        column_id = _column_id_for(model, row["table"], row["column"])
        if column_id is None:
            continue
        raw = model.column_by_id.get(column_id, {})
        column_stats.append(
            ColumnStat(
                table=str(row["table"]),
                column=str(row["column"]),
                column_id=column_id,
                column_type=str(row.get("column_type") or ""),
                data_type=str(row.get("data_type") or ""),
                format_string=str(row.get("format_string") or ""),
                display_folder=str(row.get("display_folder") or ""),
                is_hidden=bool(row.get("is_hidden")),
                is_calculated=bool(row.get("is_calculated")),
                sort_by_column=str(row.get("sort_by_column") or ""),
                expression=str(row.get("expression") or ""),
                size_data_bytes=sizes.data(column_id),
                size_hierarchy_bytes=sizes.hierarchy(column_id),
                rows=sizes.row_count(column_id),
                error_message=str(raw.get("ErrorMessage") or ""),
                size_dictionary_bytes=sizes.dictionary(column_id),
                cardinality=cardinalities.get(column_id, 0),
                data_category=str(row.get("data_category") or ""),
                summarize_by=str(row.get("summarize_by") or ""),
                is_key=bool(row.get("is_key")),
                is_available_in_mdx=bool(row.get("is_available_in_mdx", True)),
                source_column=str(row.get("source_column") or ""),
                description=str(row.get("description") or ""),
            )
        )
        columns_by_table.setdefault(str(row["table"]), []).append(column_id)

    table_stats: list[TableStat] = []
    for row in tables:
        name = str(row["table"])
        ids = columns_by_table.get(name, [])
        table_stats.append(
            TableStat(
                table=name,
                table_id=int(row.get("table_id") or 0),
                column_count=len(ids),
                rows=table_rows(sizes, ids),
                size_data_bytes=sum(sizes.data(column_id) for column_id in ids),
                size_hierarchy_bytes=sum(
                    sizes.hierarchy(column_id) for column_id in ids
                ),
                size_dictionary_bytes=sum(
                    sizes.dictionary(column_id) for column_id in ids
                ),
                storage_mode=str(row.get("storage_mode") or ""),
                measure_count=int(row.get("measure_count") or 0),
                partition_count=int(row.get("partition_count") or 0),
                is_hidden=bool(row.get("is_hidden")),
                data_category=str(row.get("data_category") or ""),
                description=str(row.get("description") or ""),
                is_calculated_table=bool(row.get("is_calculated_table")),
            )
        )

    return ModelStats(
        model_name=str(model.model_row.get("Name") or model.catalog or ""),
        compatibility_level=model.model_row.get("CompatibilityLevel"),
        last_update=_text_dt(model.model_row.get("LastUpdate")),
        columns=column_stats,
        tables=table_stats,
        segment_bytes=sizes.segment_bytes,
        artifact_bytes=sizes.artifact_bytes,
        note=note,
        measures=[
            MeasureStat(
                table=str(row.get("table") or ""),
                measure=str(row.get("measure") or ""),
                measure_id=int(row.get("measure_id") or 0),
                data_type=str(row.get("data_type") or ""),
                format_string=str(row.get("format_string") or ""),
                display_folder=str(row.get("display_folder") or ""),
                is_hidden=bool(row.get("is_hidden")),
                expression=str(row.get("expression") or ""),
                error_message=str(row.get("error_message") or ""),
                description=str(row.get("description") or ""),
            )
            for row in measures
        ],
    )


def _column_id_for(model: LiveModel, table: str, column: str) -> int | None:
    for column_id, (table_name, column_name) in model.column_name.items():
        if table_name == table and column_name == column:
            return column_id
    return None


def _text_dt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value or "")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def read_model_stats(
    client: Any,
    *,
    model: LiveModel | None = None,
    log: Log = _silent,
) -> ModelStats:
    """Baca TMSCHEMA + DMV storage dari koneksi XMLA yang sudah terbuka."""
    if model is None:
        try:
            model = LiveModel(client)
        except XmlaError as exc:
            raise ExtractionError(str(exc)) from exc

    segments: list[dict[str, Any]] = []
    storage_columns: list[dict[str, Any]] = []
    column_storages: list[dict[str, Any]] = []
    notes: list[str] = []
    try:
        segments = client.query(STORAGE_DMV)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"{STORAGE_DMV}: {str(exc).splitlines()[0]}")
    try:
        storage_columns = client.query(STORAGE_COLUMNS_DMV)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"{STORAGE_COLUMNS_DMV}: {str(exc).splitlines()[0]}")
    try:
        column_storages = client.query(COLUMN_STORAGES_DMV)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"{COLUMN_STORAGES_DMV}: {str(exc).splitlines()[0]}")

    if not segments:
        notes.append(
            "The size DMV returned no data; column size is 0 B. Direct Lake models "
            "that are not resident have no VertiPaq segments."
        )
    log(
        f"Model: {len(model.column_by_id)} raw columns, "
        f"{len(segments)} segmen storage."
    )
    return build_model_stats(
        model,
        segments,
        storage_columns,
        column_storages=column_storages,
        note="; ".join(notes),
    )
