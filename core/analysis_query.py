"""Query data mentah read-only untuk halaman Analisa (DAX via ADOMD).

Modul ini hanya menyusun query dan menormalkan hasil; koneksi tetap dibuat
pemanggil (``core.open_client``) dengan token service principal. Tidak ada
operasi tulis, tidak ada batas baris yang dilanggar, dan tidak ada nama objek
yang dipakai tanpa validasi hasil analisa.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterable

DEFAULT_ROWS = 100
MAX_ROWS = 500
QUERY_TIMEOUT = 60


def quote_table(name: str) -> str:
    """Kutip nama tabel DAX: ``'Nama''Tabel'``."""
    return "'" + str(name or "").replace("'", "''") + "'"


def quote_column(name: str) -> str:
    """Kutip nama kolom/measure DAX: ``[Nama]]Kolom]``."""
    return "[" + str(name or "").replace("]", "]]") + "]"


def clamp_rows(limit: Any) -> int:
    """Batasi jumlah baris ke 1..MAX_ROWS."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_ROWS
    return max(1, min(MAX_ROWS, value))


def build_raw_query(
    kind: str,
    table: str,
    name: str,
    *,
    limit: int = DEFAULT_ROWS,
) -> str:
    """Query DAX read-only untuk satu kolom atau measure."""
    rows = clamp_rows(limit)
    reference = f"{quote_table(table)}{quote_column(name)}"
    if kind == "measure":
        return f'EVALUATE ROW("Measure", {reference})'
    column_name = str(name or "").replace('"', '""')
    return (
        f"EVALUATE TOPN({rows}, "
        f'SELECTCOLUMNS({quote_table(table)}, "{column_name}", {reference}))'
    )


def normalize_value(value: Any) -> Any:
    """Ubah nilai ADOMD/.NET menjadi tipe yang aman untuk JSON/HTML."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    # pythonnet mengembalikan System.DateTime/Decimal tanpa tipe Python.
    to_string = getattr(value, "ToString", None)
    if callable(to_string):
        for fmt in ("yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd", "0.################"):
            try:
                return to_string(fmt)
            except Exception:  # noqa: BLE001 - format tidak didukung objek
                continue
        try:
            return to_string()
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def normalize_rows(
    rows: Iterable[dict[str, Any]],
) -> tuple[list[str], list[list[Any]]]:
    """Ambil nama kolom (urutan pembacaan) dan baris yang sudah dinormalkan."""
    columns: list[str] = []
    normalized: list[list[Any]] = []
    for row in rows:
        if not columns:
            columns = [str(key) for key in row.keys()]
        normalized.append([normalize_value(row.get(key)) for key in columns])
    return columns, normalized


def preview_payload(
    rows: Iterable[dict[str, Any]],
    *,
    query: str,
    limit: int = DEFAULT_ROWS,
) -> dict[str, Any]:
    """Payload siap kirim untuk dialog preview nilai."""
    rows = list(rows)
    columns, values = normalize_rows(rows)
    columns = [
        column[1:-1]
        if column.startswith("[") and column.endswith("]")
        else column
        for column in columns
    ]
    return {
        "columns": columns,
        "rows": values,
        "row_count": len(values),
        "limit": clamp_rows(limit),
        "truncated": len(values) >= clamp_rows(limit),
        "query": query,
    }
