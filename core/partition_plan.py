"""Rencana partisi: tipe data, parser range, dan validasi TMSL tanpa CLR.

Modul ini sengaja bebas pythonnet/.NET supaya proses server (yang memakai
ADOMD) bisa membaca daftar refresh type dan memvalidasi target tanpa memuat
TOM. Memuat TOM dan ADOMD dalam satu proses membuat koneksi XMLA gagal dengan
``Specified cast is not valid``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping, Sequence

from .errors import ExtractionError

# Nilai yang diterima TOM/TMSL. Nama kanonik mengikuti JSON TMSL.
REFRESH_TYPES: dict[str, str] = {
    "full": "full",
    "automatic": "automatic",
    "dataonly": "dataOnly",
    "clearvalues": "clearValues",
    "calculate": "calculate",
    "add": "add",
    "defragment": "defragment",
    "indexes": "indexes",
}
REFRESH_TYPE_ORDER = tuple(REFRESH_TYPES.values())


class TomError(ExtractionError):
    """Kegagalan koneksi atau operasi TOM/XMLA."""


# ---------------------------------------------------------------------------
# Range partisi (best-effort)
# ---------------------------------------------------------------------------
_DATE_LITERAL = re.compile(
    r"#(?:datetime|date)\(\s*(\d{4})\s*,\s*(\d{1,2})\s*,\s*(\d{1,2})",
    re.IGNORECASE,
)
_ISO_LITERAL = re.compile(
    r"\b((?:19|20)\d{2})[-/](\d{1,2})[-/](\d{1,2})\b"
)
_MONTH_LITERAL = re.compile(
    r"\b((?:19|20)\d{2})[-/](\d{1,2})(?![-/]\d{1,2})\b"
)
_YEAR_LITERAL = re.compile(r"\b((?:19|20)\d{2})\b")


@dataclass(frozen=True)
class PartitionRange:
    start: str = ""
    end: str = ""
    label: str = ""
    source: str = ""


@dataclass(frozen=True)
class PartitionInfo:
    table: str
    name: str
    state: str
    mode: str
    data_view: str
    source_type: str
    expression: str
    description: str
    modified_time: str
    refreshed_time: str
    is_calculated: bool
    range: PartitionRange = PartitionRange()


def _iso_date(year: str, month: str, day: str) -> str:
    try:
        value = date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return ""
    return value.isoformat()


def _date_tokens(text: str) -> list[tuple[int, str]]:
    tokens: list[tuple[int, str]] = []
    for match in _DATE_LITERAL.finditer(text):
        value = _iso_date(match.group(1), match.group(2), match.group(3))
        if value:
            tokens.append((match.start(), value))
    for match in _ISO_LITERAL.finditer(text):
        value = _iso_date(match.group(1), match.group(2), match.group(3))
        if value:
            tokens.append((match.start(), value))
    tokens.sort(key=lambda item: item[0])
    return tokens


def _literal_after(text: str, marker: str) -> str:
    index = text.find(marker)
    if index < 0:
        return ""
    window = text[index : index + 260]
    tokens = _date_tokens(window)
    return tokens[0][1] if tokens else ""


def _range_label(start: str, end: str, source: str) -> PartitionRange:
    if start and end and start != end:
        label = f"{start} \u2192 {end}"
    elif start and end:
        label = start
    elif start:
        label = f"from {start}"
    elif end:
        label = f"until {end}"
    else:
        label = ""
    return PartitionRange(start=start, end=end, label=label, source=source)


def parse_partition_range(name: str, expression: str) -> PartitionRange:
    """Ambil rentang partisi dari ekspresi M atau nama (best-effort).

    TOM tidak menyediakan properti range. Nilai diambil dari literal tanggal
    di sekitar ``RangeStart``/``RangeEnd``, lalu dari tanggal pada nama partisi.
    Bila tidak ada, hasilnya kosong dan UI menampilkan ``-`` — jangan mengarang
    rentang.
    """
    text = str(expression or "")
    start = _literal_after(text, "RangeStart")
    end = _literal_after(text, "RangeEnd")

    if start or end:
        return _range_label(start, end, "M")

    if "RangeStart" not in text and "RangeEnd" not in text:
        tokens = [value for _index, value in _date_tokens(text)]
        if len(tokens) >= 2:
            return _range_label(tokens[0], tokens[-1], "M")
        if len(tokens) == 1:
            return _range_label(tokens[0], "", "M")

    name_text = str(name or "")
    name_tokens = [value for _index, value in _date_tokens(name_text)]
    if len(name_tokens) >= 2:
        return _range_label(name_tokens[0], name_tokens[-1], "name")
    if len(name_tokens) == 1:
        return _range_label(name_tokens[0], "", "name")

    months = [
        f"{match.group(1)}-{int(match.group(2)):02d}"
        for match in _MONTH_LITERAL.finditer(name_text)
        if 1 <= int(match.group(2)) <= 12
    ]
    if len(months) >= 2:
        return _range_label(months[0], months[-1], "name")
    if len(months) == 1:
        return _range_label(months[0], "", "name")

    year = _YEAR_LITERAL.search(name_text)
    if year:
        return _range_label(year.group(1), "", "name")
    return PartitionRange()


# ---------------------------------------------------------------------------
# TMSL refresh
# ---------------------------------------------------------------------------
def normalize_refresh_type(value: str) -> str:
    """Normalisasi nama refresh type; nilai asing ditolak."""
    key = str(value or "").strip().lower().replace("_", "").replace("-", "")
    try:
        return REFRESH_TYPES[key]
    except KeyError as exc:
        allowed = ", ".join(REFRESH_TYPE_ORDER)
        raise TomError(
            f"Unknown refresh type: {value!r}. Options: {allowed}."
        ) from exc


def _normalize_targets(
    targets: Iterable[tuple[str, str] | Mapping[str, str]],
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in targets:
        if isinstance(item, Mapping):
            table = str(item.get("table") or "").strip()
            partition = str(item.get("partition") or "").strip()
        else:
            try:
                table, partition = item
            except (TypeError, ValueError) as exc:
                raise TomError(
                    "Partition targets must contain (table, partition) pairs."
                ) from exc
            table = str(table or "").strip()
            partition = str(partition or "").strip()
        if not table or not partition:
            raise TomError("Table and partition names cannot be empty.")
        key = (table, partition)
        if key not in seen:
            seen.add(key)
            result.append(key)
    if not result:
        raise TomError("Select at least one partition to process.")
    return result


def validate_refresh_targets(
    refresh_type: str, partitions: Sequence[PartitionInfo]
) -> str:
    """Validasi kombinasi refresh type dan partisi terpilih.

    ``add`` tidak berlaku untuk calculated partition atau partisi DirectQuery.
    ``defragment`` berlaku untuk tabel, jadi targetnya dikirim tanpa nama
    partisi oleh :func:`build_refresh_tmsl`.
    """
    normalized = normalize_refresh_type(refresh_type)
    if normalized != "add":
        return normalized
    for partition in partitions:
        if partition.is_calculated:
            raise TomError(
                f"Refresh 'add' does not apply to calculated partition "
                f"'{partition.table}' / '{partition.name}'."
            )
        if partition.mode.lower() == "directquery":
            raise TomError(
                f"Refresh 'add' does not apply to DirectQuery partition "
                f"'{partition.table}' / '{partition.name}'."
            )
    return normalized


def build_refresh_tmsl(
    dataset: str,
    targets: Iterable[tuple[str, str] | Mapping[str, str]],
    refresh_type: str = "full",
) -> str:
    """Bangun TMSL ``refresh`` untuk satu atau banyak partisi.

    ``defragment`` mengirim objek tabel tanpa ``partition`` karena perintah itu
    berlaku pada level tabel, bukan partisi.
    """
    catalog = str(dataset or "").strip()
    if not catalog:
        raise TomError("TMSL dataset name cannot be empty.")
    normalized = normalize_refresh_type(refresh_type)
    pairs = _normalize_targets(targets)

    if normalized == "defragment":
        tables: list[str] = []
        for table, _partition in pairs:
            if table not in tables:
                tables.append(table)
        objects = [{"database": catalog, "table": table} for table in tables]
    else:
        objects = [
            {"database": catalog, "table": table, "partition": partition}
            for table, partition in pairs
        ]

    payload = {"refresh": {"type": normalized, "objects": objects}}
    return json.dumps(payload, ensure_ascii=False)


def partition_payload(partitions: Iterable[PartitionInfo]) -> list[dict[str, object]]:
    """Serialisasi partisi untuk komunikasi proses anak (tanpa row count)."""
    return [
        {
            "table": item.table,
            "partition": item.name,
            "state": item.state,
            "mode": item.mode,
            "data_view": item.data_view,
            "source_type": item.source_type,
            "expression": item.expression,
            "description": item.description,
            "modified": item.modified_time,
            "last_processed": item.refreshed_time,
            "is_calculated": item.is_calculated,
            "range_start": item.range.start,
            "range_end": item.range.end,
            "range": item.range.label,
            "range_source": item.range.source,
        }
        for item in partitions
    ]


def partitions_from_payload(rows: Iterable[Mapping[str, object]]) -> list[PartitionInfo]:
    """Pulihkan :class:`PartitionInfo` dari JSON proses anak."""
    result: list[PartitionInfo] = []
    for row in rows:
        result.append(
            PartitionInfo(
                table=str(row.get("table") or ""),
                name=str(row.get("partition") or ""),
                state=str(row.get("state") or ""),
                mode=str(row.get("mode") or ""),
                data_view=str(row.get("data_view") or ""),
                source_type=str(row.get("source_type") or ""),
                expression=str(row.get("expression") or ""),
                description=str(row.get("description") or ""),
                modified_time=str(row.get("modified") or ""),
                refreshed_time=str(row.get("last_processed") or ""),
                is_calculated=bool(row.get("is_calculated")),
                range=PartitionRange(
                    start=str(row.get("range_start") or ""),
                    end=str(row.get("range_end") or ""),
                    label=str(row.get("range") or ""),
                    source=str(row.get("range_source") or ""),
                ),
            )
        )
    return result
