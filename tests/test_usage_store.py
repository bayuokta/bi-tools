"""Uji tabel SQLite analisa kolom."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.column_stats import ColumnStat
from core.lineage_store import close_quietly, connect
from core.report_usage import ReportUsage, UsageRecord
from core.usage_store import (
    columns,
    field_usage,
    initialize,
    last_run,
    m_queries,
    mark_reports_inactive,
    model_refs,
    report_detail,
    report_pages,
    report_cache,
    reports,
    save_columns,
    save_m_queries,
    save_model_refs,
    unresolved,
    save_report,
    save_run,
)


def usage(records: list[UsageRecord]) -> ReportUsage:
    return ReportUsage(report_format="PBIR", pages=1, visuals=1, records=records)


def record(field: str) -> UsageRecord:
    return UsageRecord(
        usage_kind="field",
        field_kind="Column",
        table="Sales",
        field=field,
        page_id="p1",
        page_name="Overview",
        visual_id="v1",
        visual_type="tableEx",
        visual_title="List",
        detail="Values",
    )


class UsageStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "data" / "bi_tools.db"
        self.conn = connect(self.db)
        self.addCleanup(lambda: close_quietly(self.conn))
        initialize(self.conn)

    def save(self, name: str = "Report A") -> None:
        save_report(
            self.conn,
            report_id="r1",
            workspace_id="ws",
            dataset_id="ds",
            name=name,
            report_format="PBIR",
            modified_at="2026-01-01T00:00:00Z",
            status="ok",
            usage=usage([record("Customer"), record("Qty")]),
        )

    def test_save_and_read_usage(self) -> None:
        self.save()

        rows = field_usage(self.conn, "ds")
        self.assertEqual({row["field_name"] for row in rows}, {"Customer", "Qty"})
        self.assertEqual(rows[0]["report_name"], "Report A")
        cached = report_cache(self.conn, "ds")["r1"]
        self.assertEqual(cached["status"], "ok")
        self.assertEqual(cached["field_count"], 2)

    def test_model_ref_depth_roundtrip_and_legacy_fallback(self) -> None:
        save_model_refs(
            self.conn,
            "ds",
            [
                {
                    "table": "Sales",
                    "column": "Qty",
                    "kind": "measure",
                    "object": "'Sales'[Total]",
                    "detail": "measure 'Total' (depth 1)",
                    "blocking": False,
                    "depth": 1,
                },
                {
                    "table": "Sales",
                    "column": "Qty",
                    "kind": "measure",
                    "object": "'Sales'[Helper]",
                    "detail": "measure 'Helper' (depth 2)",
                    "blocking": False,
                    "depth": 2,
                },
            ],
        )
        refs = model_refs(self.conn, "ds")[("sales", "qty")]
        by_object = {row["object"]: row for row in refs}
        self.assertEqual(by_object["'Sales'[Total]"]["depth"], 1)
        self.assertEqual(by_object["'Sales'[Helper]"]["depth"], 2)

        self.conn.execute(
            "UPDATE usage_model_ref SET depth = 1 WHERE object = ?",
            ("'Sales'[Helper]",),
        )
        legacy = model_refs(self.conn, "ds")[("sales", "qty")]
        legacy_by_object = {row["object"]: row for row in legacy}
        self.assertEqual(legacy_by_object["'Sales'[Helper]"]["depth"], 2)

    def test_report_pages_groups_per_page(self) -> None:
        self.save()

        pages = report_pages(self.conn, "ds")["r1"]

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["page_name"], "Overview")
        self.assertEqual(pages[0]["visual_count"], 1)
        self.assertEqual(pages[0]["field_count"], 2)

    def test_report_detail_includes_bookmarks(self) -> None:
        usage_value = ReportUsage(
            report_format="PBIR",
            records=[
                UsageRecord(
                    "bookmark", "bookmark", "All visuals", "True",
                    page_name="Bookmark 1", visual_id="b1",
                    visual_type="bookmark", detail="Bookmark 1",
                ),
                UsageRecord(
                    "bookmark", "bookmark", "Selected visuals", "False",
                    page_name="Bookmark 1", visual_id="b1",
                    visual_type="bookmark", detail="Bookmark 1",
                ),
            ],
        )
        save_report(
            self.conn,
            report_id="r1",
            workspace_id="ws",
            dataset_id="ds",
            name="Report A",
            report_format="PBIR",
            modified_at="2026-01-01T00:00:00Z",
            status="ok",
            usage=usage_value,
        )

        detail = report_detail(self.conn, "ds", "r1")

        self.assertEqual(
            detail["bookmarks"],
            [
                {
                    "name": "Bookmark 1",
                    "attributes": [
                        {"name": "All visuals", "value": "True"},
                        {"name": "Selected visuals", "value": "False"},
                    ],
                }
            ],
        )

    def test_report_detail_groups_visuals_and_filters(self) -> None:
        usage_value = ReportUsage(
            report_format="PBIR",
            pages=1,
            visuals=1,
            theme="Corporate",
            page_rows=[
                {
                    "page_id": "p1",
                    "page_name": "Overview",
                    "order_index": 1,
                    "is_hidden": False,
                    "visual_count": 2,
                }
            ],
            records=[
                UsageRecord(
                    "field", "Column", "Sales", "Region",
                    page_id="p1", page_name="Overview",
                    visual_id="v1", visual_type="tableEx", visual_title="Tabel",
                    detail="Values",
                ),
                UsageRecord(
                    "filter-visual", "Column", "Sales", "Region",
                    page_id="p1", page_name="Overview",
                    visual_id="v1", visual_type="tableEx", visual_title="Tabel",
                    detail="Categorical \u00b7 A",
                ),
                UsageRecord(
                    "filter-page", "Column", "Sales", "Segment",
                    page_id="p1", page_name="Overview",
                    visual_title="(semua visual di halaman)",
                    detail="Categorical",
                ),
                UsageRecord(
                    "filter-report", "Column", "Sales", "Channel",
                    page_name="(semua halaman)", visual_title="(semua visual)",
                    detail="Advanced",
                ),
            ],
        )
        save_report(
            self.conn,
            report_id="r1",
            workspace_id="ws",
            dataset_id="ds",
            name="Report A",
            report_format="PBIR",
            modified_at="2026-01-01T00:00:00Z",
            status="ok",
            usage=usage_value,
        )

        detail = report_detail(self.conn, "ds", "r1")

        self.assertEqual(detail["pages"][0]["page_name"], "Overview")
        self.assertEqual(detail["pages"][0]["visual_count"], 2)
        visual = detail["pages"][0]["visuals"][0]
        self.assertEqual(visual["artifacts"][0]["field"], "Region")
        self.assertEqual(visual["filters"][0]["type"], "Categorical")
        self.assertEqual(
            detail["pages"][0]["page_filters"][0]["columns"][0]["field"], "Segment"
        )
        self.assertEqual(detail["report_filters"][0]["columns"][0]["field"], "Channel")
        self.assertEqual(reports(self.conn, "ds")[0]["theme"], "Corporate")

    def test_report_detail_visual_tree_practice_and_order(self) -> None:
        save_columns(
            self.conn,
            "ds",
            [
                ColumnStat(
                    table="Sales",
                    column="Region",
                    column_id=10,
                    column_type="data",
                    data_type="string",
                    format_string="",
                    display_folder="",
                    is_hidden=False,
                    is_calculated=False,
                    sort_by_column="",
                    expression="",
                    size_data_bytes=100,
                    size_hierarchy_bytes=0,
                    rows=10,
                ),
                ColumnStat(
                    table="Sales",
                    column="Zone",
                    column_id=11,
                    column_type="calculated",
                    data_type="string",
                    format_string="",
                    display_folder="",
                    is_hidden=False,
                    is_calculated=True,
                    sort_by_column="",
                    expression="[Region]",
                    size_data_bytes=100,
                    size_hierarchy_bytes=0,
                    rows=10,
                ),
            ],
        )
        usage_value = ReportUsage(
            report_format="PBIR",
            pages=1,
            visuals=2,
            page_rows=[
                {
                    "page_id": "p1",
                    "page_name": "Overview",
                    "order_index": 1,
                    "is_hidden": False,
                    "visual_count": 2,
                }
            ],
            visual_rows=[
                {
                    "page_id": "p1",
                    "page_name": "Overview",
                    "visual_id": "g1",
                    "visual_type": "visualGroup",
                    "visual_title": "Header",
                    "parent_id": "",
                    "is_group": True,
                    "is_hidden": False,
                    "order_index": 0,
                },
                {
                    "page_id": "p1",
                    "page_name": "Overview",
                    "visual_id": "v1",
                    "visual_type": "tableEx",
                    "visual_title": "(untitled) tableEx 12345678",
                    "parent_id": "g1",
                    "is_group": False,
                    "is_hidden": False,
                    "order_index": 1,
                },
                {
                    "page_id": "p1",
                    "page_name": "Overview",
                    "visual_id": "v2",
                    "visual_type": "pivotTable",
                    "visual_title": "Summary",
                    "parent_id": "",
                    "is_group": False,
                    "is_hidden": False,
                    "order_index": 2,
                },
            ],
            records=[
                UsageRecord(
                    "field", "Column", "Sales", "Region",
                    page_id="p1", page_name="Overview",
                    visual_id="v1", visual_type="tableEx", visual_title="Tabel",
                    detail="Values",
                ),
                UsageRecord(
                    "field", "Column", "Sales", "Zone",
                    page_id="p1", page_name="Overview",
                    visual_id="v1", visual_type="tableEx", visual_title="Tabel",
                    detail="Tooltip",
                ),
                UsageRecord(
                    "filter-visual", "Column", "Sales", "Region",
                    page_id="p1", page_name="Overview",
                    visual_id="v1", visual_type="tableEx", visual_title="Tabel",
                    detail="Categorical \u00b7 A \u00b7 f1",
                ),
                UsageRecord(
                    "format", "Column", "Sales", "Region",
                    page_id="p1", page_name="Overview",
                    visual_id="v1", visual_type="tableEx", visual_title="Tabel",
                    detail="formatting objects",
                ),
            ],
            practice={
                "available": True,
                "score": 90,
                "label": "Warning",
                "passed": 9,
                "total": 10,
                "failed": 1,
                "rules": [{"id": "REDUCE_PAGES", "passed": False}],
            },
        )
        save_report(
            self.conn,
            report_id="r1",
            workspace_id="ws",
            dataset_id="ds",
            name="Report A",
            report_format="PBIR",
            modified_at="2026-01-01T00:00:00Z",
            status="ok",
            usage=usage_value,
        )

        detail = report_detail(self.conn, "ds", "r1")
        page = detail["pages"][0]
        self.assertEqual(page["container_count"], 3)
        self.assertEqual(
            [visual["visual_id"] for visual in page["visuals"]],
            ["g1", "v1", "v2"],
        )
        self.assertTrue(page["visuals"][0]["is_group"])
        self.assertEqual(page["visuals"][1]["parent_id"], "g1")
        fields = page["visuals"][1]["fields"]
        self.assertEqual(
            [(field["field"], field["kind"]) for field in fields],
            [("Region", "Column"), ("Zone", "Calculated Column")],
        )
        filters = page["visuals"][1]["filters"]
        self.assertEqual(filters[0]["name"], "f1")
        self.assertEqual(filters[0]["type"], "Categorical")
        self.assertEqual(filters[0]["fields"][0]["field"], "Region")
        stored = reports(self.conn, "ds")[0]
        self.assertEqual(stored["practice_score"], 90)
        self.assertEqual(stored["practice_label"], "Warning")
        self.assertEqual(stored["container_count"], 3)
        self.assertEqual(stored["visual_count"], 2)

    def test_rescan_replaces_fields(self) -> None:
        self.save()
        save_report(
            self.conn,
            report_id="r1",
            workspace_id="ws",
            dataset_id="ds",
            name="Report A",
            report_format="PBIR",
            modified_at="2026-01-02T00:00:00Z",
            status="ok",
            usage=usage([record("Year")]),
        )

        rows = field_usage(self.conn, "ds")
        self.assertEqual([row["field_name"] for row in rows], ["Year"])
        self.assertEqual(report_cache(self.conn, "ds")["r1"]["modified_at"], "2026-01-02T00:00:00Z")

    def test_mark_inactive_clears_fields(self) -> None:
        self.save()
        mark_reports_inactive(self.conn, "ds", [])

        self.assertEqual(field_usage(self.conn, "ds"), [])
        self.assertEqual(reports(self.conn, "ds")[0]["is_active"], 0)

    def test_column_snapshot_roundtrip(self) -> None:
        column = ColumnStat(
            table="Sales",
            column="Customer",
            column_id=10,
            column_type="data",
            data_type="string",
            format_string="",
            display_folder="",
            is_hidden=False,
            is_calculated=False,
            sort_by_column="",
            expression="",
            size_data_bytes=1024,
            size_hierarchy_bytes=512,
            size_dictionary_bytes=256,
            rows=100,
            lineage_tag="customer-lineage",
        )
        save_columns(self.conn, "ds", [column], analyzed_at="2026-01-01T00:00:00Z")

        rows = columns(self.conn, "ds")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lineage_tag"], "customer-lineage")
        self.assertEqual(rows[0]["size_data_bytes"], 1024)
        self.assertEqual(rows[0]["size_hierarchy_bytes"], 512)
        self.assertEqual(rows[0]["size_dictionary_bytes"], 256)
        self.assertEqual(rows[0]["row_count"], 100)

    def test_unresolved_rows_roundtrip(self) -> None:
        save_report(
            self.conn,
            report_id="r1",
            workspace_id="ws",
            dataset_id="ds",
            name="Report A",
            report_format="PBIR",
            modified_at="2026-01-01T00:00:00Z",
            status="ok",
            usage=ReportUsage(
                report_format="PBIR",
                unresolved=["x"],
                unresolved_rows=[
                    {
                        "page_id": "p1",
                        "page_name": "Overview",
                        "visual_id": "v1",
                        "visual_title": "List",
                        "query_ref": "Sales.X (Y)",
                        "reason": "tidak bisa dipetakan",
                    }
                ],
            ),
        )

        rows = unresolved(self.conn, "ds")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["report_name"], "Report A")
        self.assertEqual(rows[0]["query_ref"], "Sales.X (Y)")

    def test_scan_run_history(self) -> None:
        save_run(
            self.conn,
            {
                "scan_id": "s1",
                "dataset_id": "ds",
                "status": "Succeeded",
                "finished_at": "2026-01-01T10:00:00+00:00",
                "column_count": 10,
                "unused_count": 2,
                "report_personal": 3,
                "report_inaccessible": 1,
                "fetch_ms": 1250,
                "scan_ms": 300,
                "scan_workers": 2,
            },
        )

        last = last_run(self.conn, "ds")
        self.assertEqual(last["scan_id"], "s1")
        self.assertEqual(last["unused_count"], 2)
        self.assertEqual(last["report_personal"], 3)
        self.assertEqual(last["report_inaccessible"], 1)
        self.assertEqual(last["fetch_ms"], 1250)
        self.assertEqual(last["scan_ms"], 300)
        self.assertEqual(last["scan_workers"], 2)

    def test_m_query_snapshot_is_replaced_per_dataset(self) -> None:
        save_m_queries(
            self.conn,
            "ds",
            [
                {
                    "name": "Sales",
                    "kind": "Table",
                    "source": "Import",
                    "expression": "let Source = 1 in Source",
                    "warning": "",
                    "detail": "Sales",
                    "entry_key": "table:Sales:p:Sales",
                },
                {
                    "name": "Sales",
                    "kind": "Table",
                    "source": "Import",
                    "expression": "let Source = 1 in Source",
                    "warning": "",
                    "detail": "refresh policy",
                    "entry_key": "table:Sales:z:policy",
                },
                {
                    "name": "ServerURL",
                    "kind": "M Parameter",
                    "source": "Param",
                    "expression": '"server"',
                    "warning": "",
                    "detail": "Text",
                    "entry_key": "parameter:ServerURL",
                },
            ],
        )

        rows = m_queries(self.conn, "ds")
        self.assertEqual(
            [row["name"] for row in rows], ["Sales", "Sales", "ServerURL"]
        )
        self.assertEqual(
            [row["detail"] for row in rows[:2]], ["Sales", "refresh policy"]
        )
        self.assertEqual(rows[1]["entry_key"], "table:Sales:z:policy")

        save_m_queries(
            self.conn,
            "ds",
            [{"name": "Dates", "kind": "Table", "expression": "1"}],
        )

        rows = m_queries(self.conn, "ds")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Dates")
        self.assertEqual(rows[0]["entry_key"], "Table:Dates")

    def test_m_query_legacy_table_is_migrated(self) -> None:
        legacy = Path(self._tmp.name) / "legacy.db"
        conn = connect(legacy)
        self.addCleanup(lambda: close_quietly(conn))
        conn.executescript(
            """
            CREATE TABLE usage_m_query (
              dataset_id TEXT, name TEXT, kind TEXT, source TEXT,
              expression TEXT, warning TEXT, detail TEXT, analyzed_at TEXT,
              PRIMARY KEY (dataset_id, kind, name)
            );
            CREATE INDEX ix_usage_m_query_dataset
              ON usage_m_query(dataset_id);
            """
        )
        conn.executemany(
            """
            INSERT INTO usage_m_query (
              dataset_id, name, kind, source, expression, warning, detail,
              analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("ds", "Sales", "Table", "Import", "let 1 in 1", "", "1 partisi", "x"),
                ("ds", "Helper", "Expression", "", "1", "", "", "x"),
                ("ds", "ServerURL", "M parameter", "Param", '"server"', "", "Text", "x"),
            ],
        )
        conn.commit()

        initialize(conn)

        rows = m_queries(conn, "ds")
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Sales"]["entry_key"], "Table:Sales")
        self.assertEqual(by_name["Helper"]["kind"], "M Query")
        self.assertEqual(by_name["Helper"]["entry_key"], "M Query:Helper")
        self.assertEqual(by_name["ServerURL"]["kind"], "M Parameter")
        self.assertEqual(by_name["ServerURL"]["expression"], '"server"')


if __name__ == "__main__":
    unittest.main()
