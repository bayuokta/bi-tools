"""Metadata mentah TMSCHEMA untuk satu kolom/measure (read-only).

Baris DMV tidak disimpan di sesi analisa; presenter mengambilnya saat pengguna
meminta raw data, lalu fungsi ini memilih baris yang cocok dan menormalkan nilai
.NET menjadi JSON yang aman. Tidak ada data nilai model yang dibaca.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .analysis_query import normalize_value

COLUMN_DMV = "TMSCHEMA_COLUMNS"
MEASURE_DMV = "TMSCHEMA_MEASURES"
TABLE_DMV = "TMSCHEMA_TABLES"
FUNCTION_DMV = "TMSCHEMA_FUNCTIONS"
HIERARCHY_DMV = "TMSCHEMA_HIERARCHIES"


def normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): normalize_value(value) for key, value in row.items()}


def table_lookup(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[int, str], dict[str, int]]:
    """Peta ``TableID -> nama`` dan ``nama casefold -> TableID``."""
    by_id: dict[int, str] = {}
    by_name: dict[str, int] = {}
    for row in rows:
        try:
            table_id = int(row.get("ID"))
        except (TypeError, ValueError):
            continue
        name = str(row.get("Name") or row.get("ExplicitName") or "")
        if not name:
            continue
        by_id[table_id] = name
        by_name.setdefault(name.casefold(), table_id)
    return by_id, by_name


def _name_matches(row: Mapping[str, Any], name: str, *, column: bool) -> bool:
    wanted = str(name or "").casefold()
    if not wanted:
        return False
    keys = ("ExplicitName", "InferredName") if column else ("Name", "ExplicitName")
    return any(str(row.get(key) or "").casefold() == wanted for key in keys)


def _table_id(row: Mapping[str, Any]) -> int | None:
    try:
        return int(row.get("TableID"))
    except (TypeError, ValueError):
        return None


def find_row(
    rows: Iterable[Mapping[str, Any]],
    *,
    kind: str,
    table: str,
    name: str,
    column_id: int | None = None,
    tables: Iterable[Mapping[str, Any]] | None = None,
) -> Mapping[str, Any] | None:
    """Cari baris TMSCHEMA untuk kolom/measure/function/hierarchy/table."""
    rows = list(rows)
    wanted_kind = str(kind or "").lower()
    is_column = wanted_kind == "column"
    by_id, by_name = table_lookup(tables or [])
    wanted_table = by_name.get(str(table or "").casefold())

    if is_column and column_id is not None:
        for row in rows:
            try:
                if int(row.get("ID")) == int(column_id):
                    return row
            except (TypeError, ValueError):
                continue

    candidates = [row for row in rows if _name_matches(row, name, column=is_column)]
    if wanted_table is not None and wanted_kind != "table":
        matched = [
            row for row in candidates if _table_id(row) == wanted_table
        ]
        if matched:
            candidates = matched
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        # Nama sama di beberapa tabel: pilih yang tabelnya cocok, jika tidak ada
        # biarkan pemanggil melaporkan kegagalan daripada menebak.
        return None
    return None


def metadata_payload(
    row: Mapping[str, Any] | None,
    *,
    kind: str,
    dmv: str,
    table: str,
    name: str,
) -> dict[str, Any]:
    """Payload dialog raw metadata (seluruh baris DMV)."""
    wanted = str(kind or "").lower()
    if wanted not in {"measure", "column", "function", "hierarchy", "table"}:
        wanted = "column"
    if row is None:
        return {
            "found": False,
            "kind": wanted,
            "dmv": dmv,
            "table": table,
            "name": name,
            "row": None,
        }
    return {
        "found": True,
        "kind": wanted,
        "dmv": dmv,
        "table": table,
        "name": name,
        "row": normalize_row(row),
    }
