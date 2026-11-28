"""Uji ekspor tab Health (format internal BI Tools)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.health_export import (
    HEALTH_COLUMNS,
    build_health_rows,
    write_health_export,
)
from tests.test_model_health import REPORT_ID, column, report, result, table


def sample():
    return result(
        columns=[
            column("Broken", "T", size=100, error="DAX error"),
            column(
                "Customer Name", "T", size=10_000_000, dictionary=9_000_000
            ),
            column(
                "Unused Calc", "T", "Unused", size=500, calculated=True
            ),
        ],
        tables=[table("T", size=10_000_000)],
        reports=[report()],
        pages={
            REPORT_ID: [
                {
                    "page_id": "p1",
                    "page_name": "Overview",
                    "visual_count": 1,
                }
            ]
        },
        unresolved=[
            {
                "report_id": REPORT_ID,
                "page_id": "p1",
                "visual_id": "v1",
                "visual_title": "Sales Chart",
                "query_ref": "[Missing]",
            }
        ],
    )


class HealthExportTests(unittest.TestCase):
    def test_rows_match_columns_and_labels(self) -> None:
        rows = build_health_rows(sample())
        self.assertEqual(list(rows[0].keys()), HEALTH_COLUMNS)
        self.assertGreater(len(rows), 0)
        by_rule = {row["Rule ID"]: row for row in rows}
        self.assertEqual(by_rule["column_error"]["Severity"], "Critical")
        self.assertEqual(by_rule["column_error"]["Area"], "Model")
        self.assertEqual(by_rule["column_error"]["Rule"], "Column has an error")
        self.assertEqual(by_rule["column_error"]["Kind"], "column")
        self.assertEqual(by_rule["column_error"]["Object"], "T[Broken]")
        self.assertIn("DAX error", by_rule["column_error"]["Detail"])
        self.assertEqual(by_rule["column_error"]["Size"], "100 B")
        self.assertEqual(by_rule["column_error"]["Size_bytes"], 100)
        self.assertEqual(by_rule["large_dictionary"]["Severity"], "Warning")
        self.assertIn("dictionary 90%", by_rule["large_dictionary"]["Detail"])
        self.assertEqual(by_rule["unused_calculated_column"]["Severity"], "Info")
        self.assertEqual(by_rule["broken_visual"]["Severity"], "Critical")

    def test_report_context_columns_are_filled(self) -> None:
        rows = build_health_rows(sample())
        broken = next(row for row in rows if row["Rule ID"] == "broken_visual")
        self.assertEqual(broken["Report"], "Report Uji")
        self.assertEqual(broken["Page"], "Overview")
        self.assertEqual(broken["Visual"], "Sales Chart")
        self.assertEqual(broken["Kind"], "visual")
        self.assertEqual(broken["Area"], "Report")

    def test_size_is_empty_for_zero(self) -> None:
        rows = build_health_rows(
            result(columns=[column("Broken", "T", error="x")])
        )
        row = next(row for row in rows if row["Rule ID"] == "column_error")
        self.assertEqual(row["Size"], "")
        self.assertEqual(row["Size_bytes"], 0)

    def test_write_health_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Health.xlsx"
            write_health_export(sample(), target)
            frame = pd.read_excel(target, "Health", keep_default_na=False)
        self.assertEqual(list(frame.columns), HEALTH_COLUMNS)
        self.assertGreater(len(frame), 0)

    def test_empty_result_writes_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Health.xlsx"
            write_health_export(result(), target)
            frame = pd.read_excel(target, "Health", keep_default_na=False)
        self.assertEqual(list(frame.columns), HEALTH_COLUMNS)
        self.assertEqual(len(frame), 0)


if __name__ == "__main__":
    unittest.main()
