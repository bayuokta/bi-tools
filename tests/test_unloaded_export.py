"""Uji ekspor tab Unloaded M queries mengikuti template Measure Killer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.unloaded_export import (
    UNLOADED_COLUMNS,
    build_unloaded_rows,
    write_unloaded_export,
)
from tests.test_unloaded_queries import SAMPLE_QUERIES, analysis_result


class UnloadedExportTests(unittest.TestCase):
    def test_rows_match_template_columns(self) -> None:
        rows = build_unloaded_rows(analysis_result(SAMPLE_QUERIES))
        self.assertEqual(list(rows[0].keys()), UNLOADED_COLUMNS)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIn(row["Type"], {"M Query", "M Parameter"})
            self.assertEqual(row["Source"], "Model Uji")

    def test_unused_row_has_empty_usage_columns(self) -> None:
        rows = build_unloaded_rows(analysis_result(SAMPLE_QUERIES))
        unused = next(row for row in rows if row["Name"] == "Pages Testing")
        self.assertEqual(unused["Status"], "Unused")
        self.assertEqual(unused["Number_of_uses"], 0)
        self.assertEqual(unused["Usage_name"], "")
        self.assertEqual(unused["Usage_type"], "")
        self.assertEqual(unused["Usage_source"], "")
        self.assertEqual(unused["Usage_status"], "")
        self.assertEqual(unused["Usage_number_of_uses"], "")

    def test_usage_rows_repeat_root_and_use_table_status(self) -> None:
        rows = build_unloaded_rows(analysis_result(SAMPLE_QUERIES))
        range_start = [row for row in rows if row["Name"] == "RangeStart"]
        self.assertEqual(len(range_start), 1)
        row = range_start[0]
        self.assertEqual(row["Type"], "M Parameter")
        self.assertEqual(row["Status"], "Used")
        self.assertEqual(row["Number_of_uses"], 1)
        self.assertEqual(row["Usage_name"], "Sales")
        self.assertEqual(row["Usage_type"], "Table")
        self.assertEqual(row["Usage_source"], "Model Uji")
        self.assertEqual(row["Usage_status"], "Used 50.0% (1/2)")
        self.assertEqual(row["Usage_number_of_uses"], 1)

    def test_root_order_follows_positions(self) -> None:
        rows = build_unloaded_rows(analysis_result(SAMPLE_QUERIES))
        names = []
        for row in rows:
            if not names or names[-1] != row["Name"]:
                names.append(row["Name"])
        self.assertEqual(
            names,
            [
                "RangeStart",
                "ServerURL",
                "projectID",
                "DataSize",
                "LimitClause",
                "Base Query",
                "Pages Testing",
            ],
        )

    def test_write_unloaded_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Unloaded.xlsx"
            write_unloaded_export(analysis_result(SAMPLE_QUERIES), target)
            frame = pd.read_excel(
                target, "Unloaded power query", keep_default_na=False
            )
        self.assertEqual(list(frame.columns), UNLOADED_COLUMNS)
        self.assertGreater(len(frame), 0)


if __name__ == "__main__":
    unittest.main()
