"""Tabel SQLite untuk analisa pemakaian kolom + ukuran semantic model.

Memakai database yang sama dengan lineage (``data\\bi_tools.db``) tetapi tabel
sendiri, mengikuti pola tabel ``workspace``: katalog lineage dan analisa kolom
tidak saling menonaktifkan item.

Isi:

- ``usage_scan_run``  : riwayat satu kali analisa (status, cakupan, ringkasan),
- ``usage_report``    : status scan per report (cache by ``modified_at``),
- ``usage_field``     : baris pemakaian field per report/halaman/visual,
- ``usage_column``    : snapshot ukuran + metadata kolom per dataset,
- ``usage_m_query``   : M query/parameter terakhir per dataset.

Modul ini hanya mengurus skema dan SQL; orkestrasi ada di
:mod:`core.usage_service`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .metadata_common import reference_depth
from .report_usage import ReportUsage, UsageRecord

M_QUERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_m_query (
  dataset_id TEXT, entry_key TEXT, name TEXT, kind TEXT, source TEXT,
  expression TEXT, warning TEXT, detail TEXT, analyzed_at TEXT,
  PRIMARY KEY (dataset_id, entry_key)
);
"""

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
  coverage TEXT, model_json TEXT,
  fetch_ms INTEGER DEFAULT 0, scan_ms INTEGER DEFAULT 0,
  scan_workers INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS usage_report (
  report_id TEXT PRIMARY KEY,
  workspace_id TEXT, dataset_id TEXT, name TEXT,
  report_format TEXT, modified_at TEXT, scanned_at TEXT,
  status TEXT, message TEXT,
  page_count INTEGER DEFAULT 0, visual_count INTEGER DEFAULT 0,
  container_count INTEGER DEFAULT 0,
  field_count INTEGER DEFAULT 0, unresolved_count INTEGER DEFAULT 0,
  theme TEXT,
  practice_score INTEGER DEFAULT 0, practice_label TEXT,
  practice_passed INTEGER DEFAULT 0, practice_total INTEGER DEFAULT 0,
  practice_failed INTEGER DEFAULT 0, practice_rules TEXT,
  is_active INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_usage_report_dataset ON usage_report(dataset_id);
CREATE TABLE IF NOT EXISTS usage_page (
  report_id TEXT, dataset_id TEXT, page_id TEXT, page_name TEXT,
  order_index INTEGER DEFAULT 0, is_hidden INTEGER DEFAULT 0,
  visual_count INTEGER DEFAULT 0,
  PRIMARY KEY (report_id, page_id)
);
CREATE INDEX IF NOT EXISTS ix_usage_page_dataset ON usage_page(dataset_id);
CREATE TABLE IF NOT EXISTS usage_field (
  report_id TEXT, dataset_id TEXT,
  page_id TEXT, page_name TEXT,
  visual_id TEXT, visual_type TEXT, visual_title TEXT,
  usage_kind TEXT, field_kind TEXT,
  table_name TEXT, field_name TEXT,
  aggregation TEXT, detail TEXT,
  is_hidden INTEGER DEFAULT 0,
  order_index INTEGER DEFAULT 0,
  PRIMARY KEY (report_id, page_id, visual_id, usage_kind, table_name, field_name, detail)
);
CREATE INDEX IF NOT EXISTS ix_usage_field_dataset ON usage_field(dataset_id);
CREATE INDEX IF NOT EXISTS ix_usage_field_column ON usage_field(table_name, field_name);
CREATE TABLE IF NOT EXISTS usage_visual (
  report_id TEXT, dataset_id TEXT,
  page_id TEXT, page_name TEXT,
  visual_id TEXT, visual_type TEXT, visual_title TEXT,
  parent_id TEXT, is_group INTEGER DEFAULT 0, is_hidden INTEGER DEFAULT 0,
  order_index INTEGER DEFAULT 0,
  PRIMARY KEY (report_id, page_id, visual_id)
);
CREATE INDEX IF NOT EXISTS ix_usage_visual_dataset ON usage_visual(dataset_id);
CREATE TABLE IF NOT EXISTS usage_column (
  dataset_id TEXT, table_name TEXT, column_name TEXT,
  column_id INTEGER, column_type TEXT, data_type TEXT,
  format_string TEXT, display_folder TEXT,
  is_hidden INTEGER DEFAULT 0, is_calculated INTEGER DEFAULT 0,
  sort_by_column TEXT, expression TEXT,
  size_data_bytes INTEGER DEFAULT 0, size_hierarchy_bytes INTEGER DEFAULT 0,
  size_dictionary_bytes INTEGER DEFAULT 0,
  cardinality INTEGER DEFAULT 0, data_category TEXT, summarize_by TEXT,
  is_key INTEGER DEFAULT 0, is_available_in_mdx INTEGER DEFAULT 1,
  source_column TEXT, description TEXT, lineage_tag TEXT,
  row_count INTEGER DEFAULT 0, error_message TEXT, analyzed_at TEXT,
  PRIMARY KEY (dataset_id, table_name, column_name)
);
CREATE TABLE IF NOT EXISTS usage_model_ref (
  dataset_id TEXT, table_name TEXT, column_name TEXT,
  kind TEXT, object TEXT, detail TEXT, blocking INTEGER DEFAULT 1,
  depth INTEGER DEFAULT 1,
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
  measure_id INTEGER DEFAULT 0,
  data_type TEXT, format_string TEXT, display_folder TEXT,
  is_hidden INTEGER DEFAULT 0, expression TEXT, error_message TEXT,
  description TEXT, lineage_tag TEXT, refs_json TEXT, analyzed_at TEXT,
  PRIMARY KEY (dataset_id, table_name, measure_name)
);
CREATE TABLE IF NOT EXISTS usage_hierarchy (
  dataset_id TEXT, table_name TEXT, hierarchy_name TEXT,
  is_hidden INTEGER DEFAULT 0, display_folder TEXT,
  levels TEXT, level_count INTEGER DEFAULT 0, analyzed_at TEXT,
  PRIMARY KEY (dataset_id, table_name, hierarchy_name)
);
""" + M_QUERY_SCHEMA + """
CREATE INDEX IF NOT EXISTS ix_usage_m_query_dataset ON usage_m_query(dataset_id);
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
        "fetch_ms": "INTEGER DEFAULT 0",
        "scan_ms": "INTEGER DEFAULT 0",
        "scan_workers": "INTEGER DEFAULT 1",
    },
    "usage_column": {
        "error_message": "TEXT",
        "size_dictionary_bytes": "INTEGER DEFAULT 0",
        "cardinality": "INTEGER DEFAULT 0",
        "data_category": "TEXT",
        "summarize_by": "TEXT",
        "is_key": "INTEGER DEFAULT 0",
        "is_available_in_mdx": "INTEGER DEFAULT 1",
        "source_column": "TEXT",
        "description": "TEXT",
        "lineage_tag": "TEXT",
    },
    "usage_measure": {
        "description": "TEXT",
        "measure_id": "INTEGER DEFAULT 0",
        "lineage_tag": "TEXT",
    },
    "usage_model_ref": {
        "depth": "INTEGER DEFAULT 1",
    },
    "usage_report": {
        "theme": "TEXT",
        "container_count": "INTEGER DEFAULT 0",
        "practice_score": "INTEGER DEFAULT 0",
        "practice_label": "TEXT",
        "practice_passed": "INTEGER DEFAULT 0",
        "practice_total": "INTEGER DEFAULT 0",
        "practice_failed": "INTEGER DEFAULT 0",
        "practice_rules": "TEXT",
    },
    "usage_field": {
        "order_index": "INTEGER DEFAULT 0",
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


def _migrate_m_query(conn: sqlite3.Connection) -> None:
    """Pindahkan ``usage_m_query`` versi lama ke skema ber-``entry_key``.

    Tabel ini cache analisa, jadi salinan baris lama dipertahankan dengan
    ``entry_key = kind:name``; label lama dinormalkan agar filter tab M tetap
    bekerja sebelum analisa berikutnya dijalankan.
    """
    existing = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(usage_m_query)")
    }
    if not existing or "entry_key" in existing:
        return
    conn.execute("DROP INDEX IF EXISTS ix_usage_m_query_dataset")
    conn.execute("DROP TABLE IF EXISTS usage_m_query_legacy")
    conn.execute("ALTER TABLE usage_m_query RENAME TO usage_m_query_legacy")
    conn.execute(M_QUERY_SCHEMA)
    rows = conn.execute("SELECT * FROM usage_m_query_legacy").fetchall()
    for row in rows:
        kind = str(row["kind"] or "")
        if kind == "Expression":
            kind = "M Query"
        elif kind.casefold() == "m parameter":
            kind = "M Parameter"
        entry_key = f"{kind}:{row['name']}"
        conn.execute(
            """
            INSERT OR REPLACE INTO usage_m_query (
              dataset_id, entry_key, name, kind, source, expression, warning,
              detail, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["dataset_id"],
                entry_key,
                row["name"],
                kind,
                row["source"],
                row["expression"],
                row["warning"],
                row["detail"],
                row["analyzed_at"],
            ),
        )
    conn.execute("DROP TABLE usage_m_query_legacy")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_usage_m_query_dataset "
        "ON usage_m_query(dataset_id)"
    )


def initialize(conn: sqlite3.Connection) -> None:
    """Buat tabel analisa bila belum ada (aman dipanggil berulang)."""
    conn.executescript(SCHEMA)
    _migrate_m_query(conn)
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
    theme: str = "",
) -> None:
    """Simpan status satu report beserta baris pemakaiannya (replace)."""
    page_count = int(usage.pages) if usage else 0
    visual_count = int(usage.visuals) if usage else 0
    container_count = len(usage.visual_rows) if usage else 0
    unresolved = len(usage.unresolved) if usage else 0
    records = list(usage.records) if usage else []
    theme_name = theme or (str(usage.theme) if usage else "")
    practice = usage.practice if usage and isinstance(usage.practice, Mapping) else {}
    practice_rules = json.dumps(practice.get("rules") or [], ensure_ascii=False)

    conn.execute(
        """
        INSERT INTO usage_report (
          report_id, workspace_id, dataset_id, name, report_format, modified_at,
          scanned_at, status, message, page_count, visual_count, container_count,
          field_count, unresolved_count, theme, practice_score, practice_label,
          practice_passed, practice_total, practice_failed, practice_rules,
          is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(report_id) DO UPDATE SET
          workspace_id=excluded.workspace_id, dataset_id=excluded.dataset_id,
          name=excluded.name, report_format=excluded.report_format,
          modified_at=excluded.modified_at, scanned_at=excluded.scanned_at,
          status=excluded.status, message=excluded.message,
          page_count=excluded.page_count, visual_count=excluded.visual_count,
          container_count=excluded.container_count,
          field_count=excluded.field_count,
          unresolved_count=excluded.unresolved_count,
          theme=excluded.theme,
          practice_score=excluded.practice_score,
          practice_label=excluded.practice_label,
          practice_passed=excluded.practice_passed,
          practice_total=excluded.practice_total,
          practice_failed=excluded.practice_failed,
          practice_rules=excluded.practice_rules,
          is_active=1
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
            container_count,
            len(records),
            unresolved,
            theme_name,
            int(practice.get("score") or 0),
            str(practice.get("label") or ""),
            int(practice.get("passed") or 0),
            int(practice.get("total") or 0),
            int(practice.get("failed") or 0),
            practice_rules,
        ),
    )
    conn.execute("DELETE FROM usage_page WHERE report_id = ?", (report_id,))
    page_rows = list(usage.page_rows) if usage else []
    if page_rows:
        conn.executemany(
            """
            INSERT OR REPLACE INTO usage_page (
              report_id, dataset_id, page_id, page_name, order_index,
              is_hidden, visual_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    report_id,
                    dataset_id,
                    str(row.get("page_id") or ""),
                    str(row.get("page_name") or ""),
                    int(row.get("order_index") or 0),
                    1 if row.get("is_hidden") else 0,
                    int(row.get("visual_count") or 0),
                )
                for row in page_rows
                if str(row.get("page_id") or "")
            ],
        )
    conn.execute("DELETE FROM usage_visual WHERE report_id = ?", (report_id,))
    visual_rows = list(usage.visual_rows) if usage else []
    if visual_rows:
        conn.executemany(
            """
            INSERT OR REPLACE INTO usage_visual (
              report_id, dataset_id, page_id, page_name, visual_id,
              visual_type, visual_title, parent_id, is_group, is_hidden,
              order_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    report_id,
                    dataset_id,
                    str(row.get("page_id") or ""),
                    str(row.get("page_name") or ""),
                    str(row.get("visual_id") or ""),
                    str(row.get("visual_type") or ""),
                    str(row.get("visual_title") or ""),
                    str(row.get("parent_id") or ""),
                    1 if row.get("is_group") else 0,
                    1 if row.get("is_hidden") else 0,
                    int(row.get("order_index") or 0),
                )
                for row in visual_rows
                if str(row.get("visual_id") or "")
            ],
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
            index,
        )
        for index, record in enumerate(records)
    ]
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO usage_field (
          report_id, dataset_id, page_id, page_name, visual_id, visual_type,
          visual_title, usage_kind, field_kind, table_name, field_name,
          aggregation, detail, is_hidden, order_index
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
               r.report_format, r.modified_at, p.order_index AS page_order
          FROM usage_field f
          JOIN usage_report r ON r.report_id = f.report_id
          LEFT JOIN usage_page p
            ON p.report_id = f.report_id AND p.page_id = f.page_id
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


def report_pages(
    conn: sqlite3.Connection, dataset_id: str
) -> dict[str, list[dict[str, Any]]]:
    """Halaman per report: metadata halaman + jumlah visual/field.

    Memakai ``usage_page`` (termasuk halaman tersembunyi dan jumlah visual dari
    definisi) lalu melengkapi jumlah field dari ``usage_field``. Database lama
    tanpa ``usage_page`` tetap terbaca lewat hitungan dari ``usage_field``.
    """
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for row in conn.execute(
        """
        SELECT report_id, page_id,
               COUNT(DISTINCT visual_id) AS visual_count,
               COUNT(*) AS field_count
          FROM usage_field
         WHERE dataset_id = ? AND page_id <> ''
         GROUP BY report_id, page_id
        """,
        (dataset_id,),
    ):
        counts[(str(row["report_id"]), str(row["page_id"]))] = {
            "visual_count": int(row["visual_count"] or 0),
            "field_count": int(row["field_count"] or 0),
        }
    container_counts: dict[tuple[str, str], int] = {
        (str(row["report_id"]), str(row["page_id"])): int(row["container_count"] or 0)
        for row in conn.execute(
            """
            SELECT report_id, page_id, COUNT(*) AS container_count
              FROM usage_visual
             WHERE dataset_id = ?
             GROUP BY report_id, page_id
            """,
            (dataset_id,),
        )
    }

    grouped: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str]] = set()
    for row in conn.execute(
        """
        SELECT report_id, page_id, page_name, order_index, is_hidden, visual_count
          FROM usage_page
         WHERE dataset_id = ?
         ORDER BY report_id, order_index, page_name
        """,
        (dataset_id,),
    ):
        report_id = str(row["report_id"])
        page_id = str(row["page_id"])
        seen.add((report_id, page_id))
        stat = counts.get((report_id, page_id)) or {}
        grouped.setdefault(report_id, []).append(
            {
                "page_id": page_id,
                "page_name": str(row["page_name"] or ""),
                "order_index": int(row["order_index"] or 0),
                "is_hidden": bool(row["is_hidden"]),
                "visual_count": int(row["visual_count"] or 0),
                "container_count": int(
                    container_counts.get(
                        (report_id, page_id), int(row["visual_count"] or 0)
                    )
                ),
                "field_count": int(stat.get("field_count") or 0),
            }
        )

    # Cadangan database lama: halaman hanya dari baris pemakaian field.
    for (report_id, page_id), stat in counts.items():
        if (report_id, page_id) in seen:
            continue
        name_row = conn.execute(
            """
            SELECT page_name FROM usage_field
             WHERE report_id = ? AND page_id = ? AND page_name <> ''
             LIMIT 1
            """,
            (report_id, page_id),
        ).fetchone()
        grouped.setdefault(report_id, []).append(
            {
                "page_id": page_id,
                "page_name": str(name_row["page_name"] if name_row else ""),
                "order_index": 0,
                "is_hidden": False,
                "visual_count": int(stat.get("visual_count") or 0),
                "container_count": int(
                    container_counts.get(
                        (report_id, page_id), int(stat.get("visual_count") or 0)
                    )
                ),
                "field_count": int(stat.get("field_count") or 0),
            }
        )
    for pages in grouped.values():
        pages.sort(key=lambda item: (item["order_index"], item["page_name"]))
    return grouped


def _hierarchy_name(field: str) -> str:
    """Nama hierarchy dari field level ``Date.Year``."""
    text = str(field or "")
    return text.split(".", 1)[0] if "." in text else text


def _field_ref(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "table": str(row.get("table_name") or ""),
        "field": str(row.get("field_name") or ""),
        "kind": str(row.get("field_kind") or ""),
    }


def _field_type(
    row: Mapping[str, Any],
    column_types: Mapping[tuple[str, str], str],
    measure_names: set[tuple[str, str]],
) -> str:
    kind = str(row.get("field_kind") or "")
    table = str(row.get("table_name") or "")
    name = str(row.get("field_name") or "")
    key = (table.casefold(), name.casefold())
    if kind == "HierarchyLevel":
        return "Hierarchy"
    if kind == "Hierarchy":
        return "Hierarchy"
    if kind == "Measure" or key in measure_names:
        return "Measure"
    if str(column_types.get(key) or "").casefold() == "calculated":
        return "Calculated Column"
    return "Column"


def _resolve_field(
    row: Mapping[str, Any],
    column_types: Mapping[tuple[str, str], str],
    measure_names: set[tuple[str, str]],
) -> dict[str, Any]:
    table = str(row.get("table_name") or "")
    name = str(row.get("field_name") or "")
    kind = str(row.get("field_kind") or "")
    if kind == "HierarchyLevel":
        name = _hierarchy_name(name)
    return {
        "table": table,
        "field": name,
        "kind": _field_type(row, column_types, measure_names),
        "order": int(row.get("order_index") or 0),
    }


def _filter_parts(detail: Any, fallback: str = "") -> tuple[str, str]:
    parts = [part.strip() for part in str(detail or "").split(" \u00b7 ") if part.strip()]
    kind = parts[0] if parts else "Filter"
    name = parts[-1] if len(parts) > 1 else (fallback or kind)
    return kind, name


def _filter_entries(
    rows: Iterable[Mapping[str, Any]],
    column_types: Mapping[tuple[str, str], str],
    measure_names: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        kind, name = _filter_parts(
            row.get("detail"), str(row.get("field_name") or "")
        )
        key = f"{kind}\u0000{name}"
        if key not in grouped:
            grouped[key] = {
                "name": name,
                "type": kind,
                "detail": str(row.get("detail") or ""),
                "columns": [],
                "fields": [],
                "_order": int(row.get("order_index") or 0),
            }
            order.append(key)
        entry = grouped[key]
        field = _resolve_field(row, column_types, measure_names)
        if not field["field"]:
            continue
        fingerprint = (
            field["table"].casefold(),
            field["field"].casefold(),
            field["kind"],
        )
        if any(
            (
                str(item.get("table") or "").casefold(),
                str(item.get("field") or "").casefold(),
                str(item.get("kind") or ""),
            )
            == fingerprint
            for item in entry["fields"]
        ):
            continue
        entry["fields"].append(field)
        entry["columns"].append(
            {
                "table": field["table"],
                "field": field["field"],
                "kind": field["kind"],
            }
        )
        entry["_order"] = min(entry["_order"], field["order"])
    entries = [grouped[key] for key in order]
    for entry in entries:
        entry.pop("_order", None)
    return entries


def _visual_fields(
    fields: Iterable[Mapping[str, Any]],
    formats: Iterable[Mapping[str, Any]],
    column_types: Mapping[tuple[str, str], str],
    measure_names: set[tuple[str, str]],
    model_tables: set[str],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    names: set[str] = set()
    for row in fields:
        item = _resolve_field(row, column_types, measure_names)
        if not item["field"]:
            continue
        key = (
            item["table"].casefold(),
            item["field"].casefold(),
            item["kind"],
        )
        if key in seen:
            continue
        seen.add(key)
        names.add(item["field"].casefold())
        resolved.append(item)

    extras: list[dict[str, Any]] = []
    extra_seen: set[tuple[str, str, str]] = set()
    for row in formats:
        table = str(row.get("table_name") or "")
        if not table or table.casefold() not in model_tables:
            continue
        item = _resolve_field(row, column_types, measure_names)
        if not item["field"] or item["field"].casefold() in names:
            continue
        key = (
            item["table"].casefold(),
            item["field"].casefold(),
            item["kind"],
        )
        if key in extra_seen:
            continue
        extra_seen.add(key)
        extras.append(item)
    return extras + resolved


def report_detail(
    conn: sqlite3.Connection, dataset_id: str, report_id: str
) -> dict[str, Any]:
    """Detail satu report untuk tab Report results (halaman/visual/filter)."""
    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM usage_field
             WHERE dataset_id = ? AND report_id = ?
             ORDER BY order_index, rowid
            """,
            (dataset_id, report_id),
        ).fetchall()
    ]
    pages = report_pages(conn, dataset_id).get(report_id, [])
    visual_rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM usage_visual
             WHERE dataset_id = ? AND report_id = ?
             ORDER BY page_id, order_index
            """,
            (dataset_id, report_id),
        ).fetchall()
    ]
    if not visual_rows:
        seen_visuals: set[tuple[str, str]] = set()
        for row in rows:
            visual_id = str(row.get("visual_id") or "")
            page_id = str(row.get("page_id") or "")
            if not visual_id or (page_id, visual_id) in seen_visuals:
                continue
            seen_visuals.add((page_id, visual_id))
            visual_rows.append(
                {
                    "page_id": page_id,
                    "page_name": str(row.get("page_name") or ""),
                    "visual_id": visual_id,
                    "visual_type": str(row.get("visual_type") or ""),
                    "visual_title": str(row.get("visual_title") or ""),
                    "parent_id": "",
                    "is_group": 0,
                    "is_hidden": int(row.get("is_hidden") or 0),
                    "order_index": len(seen_visuals),
                }
            )

    column_types = {
        (str(row["table_name"]).casefold(), str(row["column_name"]).casefold()):
        str(row["column_type"] or "")
        for row in conn.execute(
            "SELECT table_name, column_name, column_type FROM usage_column "
            "WHERE dataset_id = ?",
            (dataset_id,),
        )
    }
    measure_names = {
        (str(row["table_name"]).casefold(), str(row["measure_name"]).casefold())
        for row in conn.execute(
            "SELECT table_name, measure_name FROM usage_measure WHERE dataset_id = ?",
            (dataset_id,),
        )
    }
    model_tables = {
        str(row["table_name"]).casefold()
        for row in conn.execute(
            "SELECT table_name FROM usage_column WHERE dataset_id = ? "
            "UNION SELECT table_name FROM usage_measure WHERE dataset_id = ?",
            (dataset_id, dataset_id),
        )
    }
    broken = {
        str(row["visual_id"])
        for row in conn.execute(
            "SELECT visual_id FROM usage_unresolved WHERE dataset_id = ? "
            "AND report_id = ?",
            (dataset_id, report_id),
        )
    }

    field_rows: dict[str, list[dict[str, Any]]] = {}
    format_rows: dict[str, list[dict[str, Any]]] = {}
    visual_filters: dict[str, list[dict[str, Any]]] = {}
    page_filters: dict[str, list[dict[str, Any]]] = {}
    report_filter_rows: list[dict[str, Any]] = []
    for row in rows:
        kind = str(row.get("usage_kind") or "")
        if kind == "filter-report":
            report_filter_rows.append(row)
            continue
        page_id = str(row.get("page_id") or "")
        if kind == "filter-page":
            page_filters.setdefault(page_id, []).append(row)
            continue
        visual_id = str(row.get("visual_id") or "")
        if kind == "filter-visual":
            visual_filters.setdefault(visual_id, []).append(row)
        elif kind == "field":
            field_rows.setdefault(visual_id, []).append(row)
        elif kind == "format":
            format_rows.setdefault(visual_id, []).append(row)

    page_map: dict[str, dict[str, Any]] = {}
    for page in pages:
        page_map[str(page["page_id"])] = {
            "page_id": str(page["page_id"]),
            "page_name": str(page["page_name"]),
            "is_hidden": bool(page.get("is_hidden")),
            "order_index": int(page.get("order_index") or 0),
            "visual_count": int(page.get("visual_count") or 0),
            "container_count": int(
                page.get("container_count") or page.get("visual_count") or 0
            ),
            "field_count": int(page.get("field_count") or 0),
            "visuals": [],
            "page_filters": [],
        }
    for row in visual_rows:
        page_id = str(row.get("page_id") or "")
        page_name = str(row.get("page_name") or "")
        if page_id not in page_map:
            page_map[page_id or page_name] = {
                "page_id": page_id,
                "page_name": page_name or page_id,
                "is_hidden": False,
                "order_index": 0,
                "visual_count": 0,
                "container_count": 0,
                "field_count": 0,
                "visuals": [],
                "page_filters": [],
            }
        page = page_map[page_id or page_name]
        visual_id = str(row.get("visual_id") or "")
        visual = {
            "visual_id": visual_id,
            "parent_id": str(row.get("parent_id") or ""),
            "visual_type": str(row.get("visual_type") or ""),
            "visual_title": str(row.get("visual_title") or ""),
            "is_group": bool(row.get("is_group")),
            "is_hidden": bool(row.get("is_hidden")),
            "is_broken": visual_id in broken,
            "order_index": int(row.get("order_index") or 0),
            "artifacts": [],
            "fields": [],
            "filters": [],
        }
        fields = _visual_fields(
            field_rows.get(visual_id, []),
            format_rows.get(visual_id, []),
            column_types,
            measure_names,
            model_tables,
        )
        visual["fields"] = fields
        visual["artifacts"] = fields
        visual["filters"] = _filter_entries(
            visual_filters.get(visual_id, []), column_types, measure_names
        )
        page["visuals"].append(visual)

    output_pages: list[dict[str, Any]] = []
    for page in page_map.values():
        visuals = sorted(
            page["visuals"], key=lambda item: (item["order_index"], item["visual_id"])
        )
        page["visuals"] = visuals
        page["page_filters"] = _filter_entries(
            page_filters.get(page["page_id"], []), column_types, measure_names
        )
        page["broken_visuals"] = len(
            {item["visual_id"] for item in visuals if item["is_broken"]}
        )
        output_pages.append(page)
    output_pages.sort(
        key=lambda item: (int(item.get("order_index") or 0), item["page_name"])
    )
    report_filters = _filter_entries(
        report_filter_rows, column_types, measure_names
    )
    container_count = sum(
        int(page.get("container_count") or 0) for page in output_pages
    )
    return {
        "report_id": report_id,
        "page_count": len(output_pages),
        "visual_count": sum(int(page.get("visual_count") or 0) for page in output_pages),
        "container_count": container_count,
        "broken_visuals": len(broken),
        "pages": output_pages,
        "report_filters": report_filters,
    }


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
          size_dictionary_bytes, cardinality, data_category, summarize_by,
          is_key, is_available_in_mdx, source_column, description,
          lineage_tag, row_count, error_message, analyzed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                int(getattr(column, "cardinality", 0) or 0),
                getattr(column, "data_category", ""),
                getattr(column, "summarize_by", ""),
                1 if getattr(column, "is_key", False) else 0,
                1 if getattr(column, "is_available_in_mdx", True) else 0,
                getattr(column, "source_column", ""),
                getattr(column, "description", ""),
                getattr(column, "lineage_tag", ""),
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
                int(getattr(measure, "measure_id", 0) or 0),
                measure.data_type,
                measure.format_string,
                measure.display_folder,
                1 if measure.is_hidden else 0,
                measure.expression,
                measure.error_message,
                getattr(measure, "description", ""),
                getattr(measure, "lineage_tag", ""),
                json.dumps((refs or {}).get(key, []), ensure_ascii=False),
                stamp,
            )
        )
    conn.execute("DELETE FROM usage_measure WHERE dataset_id = ?", (dataset_id,))
    if payload:
        conn.executemany(
            """
            INSERT OR REPLACE INTO usage_measure (
              dataset_id, table_name, measure_name, measure_id, data_type,
              format_string, display_folder, is_hidden, expression,
              error_message, description, lineage_tag, refs_json, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    conn.commit()


def save_hierarchies(
    conn: sqlite3.Connection,
    dataset_id: str,
    hierarchies: Iterable[Any],
    *,
    analyzed_at: str | None = None,
) -> None:
    """Simpan definisi hierarchy (objek + level) untuk snapshot/ekspor."""
    stamp = analyzed_at or utc_now()
    payload = []
    for item in hierarchies:
        definition = getattr(item, "hierarchy", None)
        if not isinstance(definition, Mapping):
            definition = item if isinstance(item, Mapping) else {}
        payload.append(
            (
                dataset_id,
                str(definition.get("table") or ""),
                str(definition.get("hierarchy") or ""),
                1 if definition.get("is_hidden") else 0,
                str(definition.get("display_folder") or ""),
                str(definition.get("levels") or ""),
                int(definition.get("level_count") or 0),
                stamp,
            )
        )
    conn.execute("DELETE FROM usage_hierarchy WHERE dataset_id = ?", (dataset_id,))
    if payload:
        conn.executemany(
            """
            INSERT OR REPLACE INTO usage_hierarchy (
              dataset_id, table_name, hierarchy_name, is_hidden,
              display_folder, levels, level_count, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    conn.commit()


def hierarchies(conn: sqlite3.Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM usage_hierarchy WHERE dataset_id = ? "
        "ORDER BY table_name, hierarchy_name",
        (dataset_id,),
    ).fetchall()
    return [
        {
            "table": str(row["table_name"] or ""),
            "hierarchy": str(row["hierarchy_name"] or ""),
            "is_hidden": bool(row["is_hidden"]),
            "display_folder": str(row["display_folder"] or ""),
            "levels": str(row["levels"] or ""),
            "level_count": int(row["level_count"] or 0),
        }
        for row in rows
    ]


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
            int(row.get("depth") or 1),
        )
        for row in rows
    ]
    if payload:
        conn.executemany(
            """
            INSERT OR REPLACE INTO usage_model_ref (
              dataset_id, table_name, column_name, kind, object, detail,
              blocking, depth
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                "depth": max(
                    int(row["depth"] or 1),
                    reference_depth(str(row["detail"] or "")),
                ),
            }
        )
    return grouped


# ---------------------------------------------------------------------------
# M query / parameter (snapshot untuk tab M queries)
# ---------------------------------------------------------------------------
def save_m_queries(
    conn: sqlite3.Connection,
    dataset_id: str,
    rows: Iterable[dict[str, Any]],
    *,
    analyzed_at: str | None = None,
) -> None:
    """Simpan M query tabel/parameter terakhir untuk satu dataset (replace)."""
    stamp = analyzed_at or utc_now()
    payload = []
    used: set[str] = set()
    for row in rows:
        name = str(row.get("name") or "")
        kind = str(row.get("kind") or "")
        entry_key = str(row.get("entry_key") or "").strip()
        if not entry_key:
            base = f"{kind}:{name}"
            entry_key = base
            index = 1
            while entry_key in used:
                index += 1
                entry_key = f"{base}:{index}"
        used.add(entry_key)
        payload.append(
            (
                dataset_id,
                entry_key,
                name,
                kind,
                str(row.get("source") or ""),
                str(row.get("expression") or ""),
                str(row.get("warning") or ""),
                str(row.get("detail") or ""),
                stamp,
            )
        )
    conn.execute("DELETE FROM usage_m_query WHERE dataset_id = ?", (dataset_id,))
    if payload:
        conn.executemany(
            """
            INSERT OR REPLACE INTO usage_m_query (
              dataset_id, entry_key, name, kind, source, expression, warning,
              detail, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
    conn.commit()


def m_queries(conn: sqlite3.Connection, dataset_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM usage_m_query WHERE dataset_id = ?
        ORDER BY CASE WHEN kind = 'Table' THEN 0 ELSE 1 END, name, entry_key
        """,
        (dataset_id,),
    ).fetchall()
    return [dict(row) for row in rows]


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
        "fetch_ms",
        "scan_ms",
        "scan_workers",
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
