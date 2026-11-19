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
    report_detail,
    report_pages,
    report_cache,
    reports,
    save_columns,
    save_m_queries,
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

    def test_report_pages_groups_per_page(self) -> None:
        self.save()

        pages = report_pages(self.conn, "ds")["r1"]

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["page_name"], "Overview")
        self.assertEqual(pages[0]["visual_count"], 1)
        self.assertEqual(pages[0]["field_count"], 2)

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
        )
        save_columns(self.conn, "ds", [column], analyzed_at="2026-01-01T00:00:00Z")

        rows = columns(self.conn, "ds")
        self.assertEqual(len(rows), 1)
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
            },
        )

        last = last_run(self.conn, "ds")
        self.assertEqual(last["scan_id"], "s1")
        self.assertEqual(last["unused_count"], 2)
        self.assertEqual(last["report_personal"], 3)
        self.assertEqual(last["report_inaccessible"], 1)

    def test_m_query_snapshot_is_replaced_per_dataset(self) -> None:
        save_m_queries(
            self.conn,
            "ds",
            [
                {
                    "name": "Sales",
                    "kind": "Tabel",
                    "source": "Import",
                    "expression": "let Source = 1 in Source",
                    "warning": "",
                    "detail": "2 partisi",
                },
                {
                    "name": "ServerURL",
                    "kind": "M parameter",
                    "source": "Param",
                    "expression": '"server"',
                    "warning": "",
                    "detail": "Text",
                },
            ],
        )

        rows = m_queries(self.conn, "ds")
        self.assertEqual([row["name"] for row in rows], ["ServerURL", "Sales"])
        self.assertEqual(rows[1]["detail"], "2 partisi")

        save_m_queries(
            self.conn,
            "ds",
            [{"name": "Dates", "kind": "Tabel", "expression": "1"}],
        )

        rows = m_queries(self.conn, "ds")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Dates")


if __name__ == "__main__":
    unittest.main()
