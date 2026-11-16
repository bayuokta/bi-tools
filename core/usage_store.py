"""Tabel SQLite untuk analisa pemakaian kolom + ukuran semantic model.

Memakai database yang sama dengan lineage (``data\\bi_tools.db``) tetapi tabel
sendiri, mengikuti pola tabel ``workspace``: katalog lineage dan analisa kolom
tidak saling menonaktifkan item.

Isi:

- ``usage_scan_run``  : riwayat satu kali analisa (status, cakupan, ringkasan),
- ``usage_report``    : status scan per report (cache by ``modified_at``),
- ``usage_field``     : baris pemakaian field per report/halaman/visual,
- ``usage_column``    : snapshot ukuran + metadata kolom per dataset.

Modul ini hanya mengurus skema dan SQL; orkestrasi ada di
:mod:`core.usage_service`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .report_usage import ReportUsage, UsageRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_scan_run (
  scan_id TEXT PRIMARY KEY,
  dataset_id TEXT, workspace_id TEXT, dataset_name TEXT,
  started_at TEXT, finished_at TEXT, status TEXT, message TEXT,
  report_total INTEGER DEFAULT 0, report_scanned INTEGER DEFAULT 0,
  report_skipped INTEGER DEFAULT 0, report_failed INTEGER DEFAULT 0,
  report_unsupported INTEGER DEFAULT 0,
  report_personal INTEGER DEFAULT 0, report_inaccessible INTEGER DEFAULT 0,
  report_app INTEGER DEFAULT 0,
  coverage_complete INTEGER DEFAULT 0,
  column_count INTEGER DEFAULT 0, unused_count INTEGER DEFAULT 0,
  measure_count INTEGER DEFAULT 0, unused_measure_count INTEGER DEFAULT 0,
  unused_bytes INTEGER DEFAULT 0, dataset_bytes INTEGER DEFAULT 0,
  coverage TEXT, model_json TEXT
);
CREATE TABLE IF NOT EXISTS usage_report (
  report_id TEXT PRIMARY KEY,
  workspace_id TEXT, dataset_id TEXT, name TEXT,
  report_format TEXT, modified_at TEXT, scanned_at TEXT,
  status TEXT, message TEXT,
  page_count INTEGER DEFAULT 0, visual_count INTEGER DEFAULT 0,
  field_count INTEGER DEFAULT 0, unresolved_count INTEGER DEFAULT 0,
  is_active INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_usage_report_dataset ON usage_report(dataset_id);
CREATE TABLE IF NOT EXISTS usage_field (
  report_id TEXT, dataset_id TEXT,
  page_id TEXT, page_name TEXT,
  visual_id TEXT, visual_type TEXT, visual_title TEXT,
  usage_kind TEXT, field_kind TEXT,
  table_name TEXT, field_name TEXT,
  aggregation TEXT, detail TEXT,
  is_hidden INTEGER DEFAULT 0,
  PRIMARY KEY (report_id, page_id, visual_id, usage_kind, table_name, field_name, detail)
);
CREATE INDEX IF NOT EXISTS ix_usage_field_dataset ON usage_field(dataset_id);
CREATE INDEX IF NOT EXISTS ix_usage_field_column ON usage_field(table_name, field_name);
CREATE TABLE IF NOT EXISTS usage_column (
  dataset_id TEXT, table_name TEXT, column_name TEXT,
  column_id INTEGER, column_type TEXT, data_type TEXT,
  format_string TEXT, display_folder TEXT,
  is_hidden INTEGER DEFAULT 0, is_calculated INTEGER DEFAULT 0,
  sort_by_column TEXT, expression TEXT,
  size_data_bytes INTEGER DEFAULT 0, size_hierarchy_bytes INTEGER DEFAULT 0,
  size_dictionary_bytes INTEGER DEFAULT 0,
  row_count INTEGER DEFAULT 0, error_message TEXT, analyzed_at TEXT,
  PRIMARY KEY (dataset_id, table_name, column_name)
);
CREATE TABLE IF NOT EXISTS usage_model_ref (
  dataset_id TEXT, table_name TEXT, column_name TEXT,
  kind TEXT, object TEXT, detail TEXT, blocking INTEGER DEFAULT 1,
  PRIMARY KEY (dataset_id, table_name, column_name, kind, object)
);
CREATE INDEX IF NOT EXISTS ix_usage_model_ref_column
  ON usage_model_ref(table_name, column_name);
CREATE TABLE IF NOT EXISTS usage_unresolved (
  report_id TEXT, dataset_id TEXT,
  page_id TEXT, page_name TEXT,
  visual_id TEXT, visual_title TEXT,
  query_ref TEXT, reason TEXT,
  PRIMARY KEY (report_id, page_id, visual_id, query_ref, reason)
);
CREATE INDEX IF NOT EXISTS ix_usage_unresolved_dataset
  ON usage_unresolved(dataset_id);
CREATE TABLE IF NOT EXISTS usage_measure (
  dataset_id TEXT, table_name TEXT, measure_name TEXT,
  data_type TEXT, format_string TEXT, display_folder TEXT,
  is_hidden INTEGER DEFAULT 0, expression TEXT, error_message TEXT,
  refs_json TEXT, analyzed_at TEXT,
  PRIMARY KEY (dataset_id, table_name, measure_name)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


MIGRATIONS = {
    "usage_scan_run": {
        "report_unsupported": "INTEGER DEFAULT 0",
        "report_personal": "INTEGER DEFAULT 0",
        "report_inaccessible": "INTEGER DEFAULT 0",
        "report_app": "INTEGER DEFAULT 0",
        "measure_count": "INTEGER DEFAULT 0",
        "unused_measure_count": "INTEGER DEFAULT 0",
        "coverage_complete": "INTEGER DEFAULT 0",
        "model_json": "TEXT",
    },
    "usage_column": {
        "error_message": "TEXT",
        "size_dictionary_bytes": "INTEGER DEFAULT 0",
    },
}


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Tambahkan kolom baru pada database yang dibuat versi sebelumnya."""
    for table, columns in MIGRATIONS.items():
        existing = {
            str(row["name"])
            for row in conn.execute(f"PRAGMA table_info({table})")
        }
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def initialize(conn: sqlite3.Connection) -> None:
    """Buat tabel analisa bila belum ada (aman dipanggil berulang)."""
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
    conn.commit()


# ---------------------------------------------------------------------------
# Report & field usage
# ---------------------------------------------------------------------------
def report_cache(conn: sqlite3.Connection, dataset_id: str) -> dict[str, dict[str, Any]]:
    """Status scan report yang tersimpan untuk satu dataset."""
    rows = conn.execute(
        "SELECT * FROM usage_report WHERE dataset_id = ?", (dataset_id,)
    ).fetchall()
    return {str(row["report_id"]): dict(row) for row in rows}


def save_report(
    conn: sqlite3.Connection,
    *,
    report_id: str,
    workspace_id: str,
    dataset_id: str,
    name: str,
    report_format: str,
    modified_at: str,
    status: str,
    usage: ReportUsage | None = None,
    message: str = "",
) -> None:
    """Simpan status satu report beserta baris pemakaiannya (replace)."""
    page_count = int(usage.pages) if usage else 0
    visual_count = int(usage.visuals) if usage else 0
    unresolved = len(usage.unresolved) if usage else 0
    records = list(usage.records) if usage else []

    conn.execute(
        """
        INSERT INTO usage_report (
          report_id, workspace_id, dataset_id, name, report_format, modified_at,
          scanned_at, status, message, page_count, visual_count, field_count,
          unresolved_count, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(report_id) DO UPDATE SET
          workspace_id=excluded.workspace_id, dataset_id=excluded.dataset_id,
          name=excluded.name, report_format=excluded.report_format,
          modified_at=excluded.modified_at, scanned_at=excluded.scanned_at,
          status=excluded.status, message=excluded.message,
          page_count=excluded.page_count, visual_count=excluded.visual_count,
          field_count=excluded.field_count,
          unresolved_count=excluded.unresolved_count, is_active=1
        """,
        (
            report_id,
            workspace_id,
            dataset_id,
            name,
            report_format,
            modified_at,
            utc_now(),
            status,
            message,
            page_count,
            visual_count,
            len(records),
            unresolved,
        ),
    )
    conn.execute("DELETE FROM usage_field WHERE report_id = ?", (report_id,))
    if records:
        save_fields(conn, report_id, dataset_id, records)
    conn.execute("DELETE FROM usage_unresolved WHERE report_id = ?", (report_id,))
    if usage is not None and usage.unresolved_rows:
        save_unresolved(conn, report_id, dataset_id, usage.unresolved_rows)
    conn.commit()


def save_fields(
    conn: sqlite3.Connection,
    report_id: str,
    dataset_id: str,
    records: Iterable[UsageRecord],
) -> None:
    rows = [
        (
            report_id,
            dataset_id,
            record.page_id,
            record.page_name,
            record.visual_id,
            record.visual_type,
            record.visual_title,
            record.usage_kind,
            record.field_kind,
            record.table,
            record.field,
            record.aggregation,
            record.detail,
            1 if record.is_hidden else 0,
        )
        for record in records
    ]
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO usage_field (
          report_id, dataset_id, page_id, page_name, visual_id, visual_type,
          visual_title, usage_kind, field_kind, table_name, field_name,
          aggregation, detail, is_hidden
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def save_unresolved(
    conn: sqlite3.Connection,
    report_id: str,
    dataset_id: str,
    rows: Iterable[dict[str, Any]],
) -> None:
    """Simpan referensi field yang tidak bisa dipetakan (untuk sheet 07)."""
    payload = [
        (
            report_id,
            dataset_id,
            str(row.get("page_id") or ""),
            str(row.get("page_name") or ""),
            str(row.get("visual_id") or ""),
            str(row.get("visual_title") or ""),
            str(row.get("query_ref") or ""),
            str(row.get("reason") or ""),
        )
        for row in rows
    ]
    if not payload:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO usage_unresolved (
          report_id, dataset_id, page_id, page_name, visual_id, visual_title,
          query_ref, reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )


def unresolved(
    conn: sqlite3.Connection, dataset_id: str
) -> list[dict[str, Any]]:
    """Daftar field tak terpetakan untuk satu dataset (join nama report)."""
    rows = conn.execute(
        """
        SELECT u.*, r.name AS report_name
          FROM usage_unresolved u
          LEFT JOIN usage_report r ON r.report_id = u.report_id
         WHERE u.dataset_id = ?
         ORDER BY r.name, u.page_name, u.visual_title, u.query_ref
        """,
        (dataset_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def mark_reports_inactive(
    conn: sqlite3.Connection, dataset_id: str, active_ids: Iterable[str]
) -> None:
    """Tandai report yang tidak lagi muncul di daftar dataset."""
    ids = {str(item) for item in active_ids if item}
    rows = conn.execute(
        "SELECT report_id FROM usage_report WHERE dataset_id = ?", (dataset_id,)
    ).fetchall()
    for row in rows:
        report_id = str(row["report_id"])
        if report_id in ids:
            continue
        conn.execute(
            "UPDATE usage_report SET is_active = 0 WHERE report_id = ?",
            (report_id,),
        )
        conn.execute("DELETE FROM usage_field WHERE report_id = ?", (report_id,))
    conn.commit()


def field_usage(
    conn: sqlite3.Connection, dataset_id: str
) -> list[dict[str, Any]]:
    """Semua baris pemakaian aktif untuk satu dataset."""
    rows = conn.execute(
        """
        SELECT f.*, r.name AS report_name, r.workspace_id AS report_workspace,
               r.report_format, r.modified_at
          FROM usage_field f
          JOIN usage_report r ON r.report_id = f.report_id
         WHERE f.dataset_id = ? AND r.is_active = 1
        """,
        (dataset_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def reports(conn: sqlite3.Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM usage_report WHERE dataset_id = ? ORDER BY name, report_id",
        (dataset_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def stored_report(
    conn: sqlite3.Connection, report_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM usage_report WHERE report_id = ?", (report_id,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Snapshot ukuran kolom
# ---------------------------------------------------------------------------
def save_columns(
    conn: sqlite3.Connection,
    dataset_id: str,
    columns: Iterable[Any],
    *,
    analyzed_at: str | None = None,
) -> None:
    stamp = analyzed_at or utc_now()
    conn.execute("DELETE FROM usage_column WHERE dataset_id = ?", (dataset_id,))
    conn.executemany(
        """
        INSERT OR REPLACE INTO usage_column (
          dataset_id, table_name, column_name, column_id, column_type, data_type,
          format_string, display_folder, is_hidden, is_calculated,
          sort_by_column, expression, size_data_bytes, size_hierarchy_bytes,
          size_dictionary_bytes, row_count, error_message, analyzed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                dataset_id,
                column.table,
                column.column,
                int(column.column_id),
                column.column_type,
                column.data_type,
                column.format_string,
                column.display_folder,
                1 if column.is_hidden else 0,
                1 if column.is_calculated else 0,
                column.sort_by_column,
                column.expression,
                int(column.size_data_bytes),
                int(column.size_hierarchy_bytes),
                int(column.size_dictionary_bytes),
                int(column.rows),
                column.error_message,
                stamp,
            )
            for column in columns
        ],
    )
    conn.commit()


def columns(conn: sqlite3.Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM usage_column WHERE dataset_id = ? "
        "ORDER BY table_name, column_name",
        (dataset_id,),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Measure
# ---------------------------------------------------------------------------
def save_measures(
    conn: sqlite3.Connection,
    dataset_id: str,
    measures: Iterable[Any],
    refs: Mapping[tuple[str, str], list[dict[str, Any]]] | None = None,
    *,
    analyzed_at: str | None = None,
) -> None:
    """Simpan metadata measure + referensi artifact yang memakainya."""
    stamp = analyzed_at or utc_now()
    payload = []
    for measure in measures:
        key = measure.key
        payload.append(
            (
                dataset_id,
                measure.table,
                measure.measure,
                measure.data_type,
                measure.format_string,
                measure.display_folder,
                1 if measure.is_hidden else 0,
                measure.expression,
                measure.error_message,
                json.dumps((refs or {}).get(key, []), ensure_ascii=False),
                stamp,
            )
        )
    conn.execute("DELETE FROM usage_measure WHERE dataset_id = ?", (dataset_id,))
    if payload:
        conn.executemany(
            """
            INSERT OR REPLACE INTO usage_measure (
              dataset_id, table_name, measure_name, data_type, format_string,
              display_folder, is_hidden, expression, error_message, refs_json,
              analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    conn.commit()


def measures(conn: sqlite3.Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM usage_measure WHERE dataset_id = ? "
        "ORDER BY table_name, measure_name",
        (dataset_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["refs"] = json.loads(item.get("refs_json") or "[]")
        except json.JSONDecodeError:
            item["refs"] = []
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# Referensi kolom dari objek model (untuk snapshot)
# ---------------------------------------------------------------------------
def save_model_refs(
    conn: sqlite3.Connection, dataset_id: str, rows: Iterable[dict[str, Any]]
) -> None:
    """Simpan referensi kolom dari objek model (measure, relasi, RLS, dst.)."""
    conn.execute("DELETE FROM usage_model_ref WHERE dataset_id = ?", (dataset_id,))
    payload = [
        (
            dataset_id,
            str(row.get("table") or ""),
            str(row.get("column") or ""),
            str(row.get("kind") or ""),
            str(row.get("object") or ""),
            str(row.get("detail") or ""),
            1 if row.get("blocking", True) else 0,
        )
        for row in rows
    ]
    if payload:
        conn.executemany(
            """
            INSERT OR REPLACE INTO usage_model_ref (
              dataset_id, table_name, column_name, kind, object, detail, blocking
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    conn.commit()


def model_refs(
    conn: sqlite3.Connection, dataset_id: str
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Peta ``(tabel, kolom) casefold -> referensi model`` dari snapshot."""
    rows = conn.execute(
        "SELECT * FROM usage_model_ref WHERE dataset_id = ?", (dataset_id,)
    ).fetchall()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["table_name"]).casefold(),
            str(row["column_name"]).casefold(),
        )
        grouped.setdefault(key, []).append(
            {
                "kind": row["kind"],
                "object": row["object"],
                "detail": row["detail"],
                "blocking": bool(row["blocking"]),
            }
        )
    return grouped


# ---------------------------------------------------------------------------
# Riwayat analisa
# ---------------------------------------------------------------------------
def save_run(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    fields = (
        "scan_id",
        "dataset_id",
        "workspace_id",
        "dataset_name",
        "started_at",
        "finished_at",
        "status",
        "message",
        "report_total",
        "report_scanned",
        "report_skipped",
        "report_failed",
        "report_unsupported",
        "report_personal",
        "report_inaccessible",
        "report_app",
        "coverage_complete",
        "column_count",
        "unused_count",
        "measure_count",
        "unused_measure_count",
        "unused_bytes",
        "dataset_bytes",
        "coverage",
        "model_json",
    )
    values = tuple(row.get(field) for field in fields)
    marks = ", ".join("?" for _ in fields)
    conn.execute(
        f"INSERT OR REPLACE INTO usage_scan_run ({', '.join(fields)}) "
        f"VALUES ({marks})",
        values,
    )
    conn.commit()


def last_run(conn: sqlite3.Connection, dataset_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM usage_scan_run WHERE dataset_id = ? "
        "ORDER BY finished_at DESC LIMIT 1",
        (dataset_id,),
    ).fetchone()
    return dict(row) if row else None
