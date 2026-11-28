"""Uji ekspor tab Report results mengikuti template Measure Killer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.report_export import (
    REPORT_RESULT_COLUMNS,
    build_report_rows,
    visual_name,
    write_report_export,
)


def result() -> SimpleNamespace:
    return SimpleNamespace(
        method="local",
        reports=[
            {
                "report_id": "r1",
                "report_name": "Dragon - NMS - Niguri Part",
                "report_format": "PBIR",
                "workspace_id": "local",
                "status": "ok",
                "page_count": 1,
                "visual_count": 2,
                "container_count": 3,
                "theme": "CY24SU10",
                "practice_score": 60,
                "practice_label": "Critical",
                "practice_passed": 6,
                "practice_total": 10,
            }
        ],
    )


def details() -> dict:
    return {
        "r1": {
            "report_id": "r1",
            "page_count": 1,
            "visual_count": 2,
            "container_count": 3,
            "broken_visuals": 1,
            "pages": [
                {
                    "page_id": "p1",
                    "page_name": "Overview",
                    "is_hidden": False,
                    "order_index": 1,
                    "visual_count": 2,
                    "container_count": 3,
                    "field_count": 3,
                    "broken_visuals": 1,
                    "visuals": [
                        {
                            "visual_id": "g1",
                            "parent_id": "",
                            "visual_type": "visualGroup",
                            "visual_title": "Header",
                            "is_group": True,
                            "is_hidden": False,
                            "is_broken": False,
                            "order_index": 0,
                            "fields": [],
                            "filters": [],
                        },
                        {
                            "visual_id": "v1",
                            "parent_id": "g1",
                            "visual_type": "slicer",
                            "visual_title": "Dealer",
                            "is_group": False,
                            "is_hidden": False,
                            "is_broken": False,
                            "order_index": 1,
                            "fields": [
                                {"table": "Sales", "field": "Dealer", "kind": "Column"}
                            ],
                            "filters": [
                                {
                                    "name": "f1",
                                    "type": "Categorical",
                                    "fields": [
                                        {
                                            "table": "Sales",
                                            "field": "Region",
                                            "kind": "Column",
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "visual_id": "v2",
                            "parent_id": "",
                            "visual_type": "pivotTable",
                            "visual_title": "Summary",
                            "is_group": False,
                            "is_hidden": False,
                            "is_broken": True,
                            "order_index": 2,
                            "fields": [],
                            "filters": [],
                        },
                    ],
                    "page_filters": [
                        {
                            "name": "pf1",
                            "type": "Categorical",
                            "fields": [
                                {
                                    "table": "Sales",
                                    "field": "Segment",
                                    "kind": "Column",
                                }
                            ],
                        }
                    ],
                }
            ],
            "report_filters": [
                {
                    "name": "rf1",
                    "type": "Advanced",
                    "fields": [
                        {"table": "Sales", "field": "Channel", "kind": "Column"}
                    ],
                }
            ],
        }
    }


class ReportExportTests(unittest.TestCase):
    def test_visual_name_quotes_only_titled_leaves(self) -> None:
        self.assertEqual(
            visual_name(
                {
                    "is_group": True,
                    "visual_title": "Header",
                    "visual_type": "visualGroup",
                }
            ),
            "Header",
        )
        self.assertEqual(
            visual_name(
                {
                    "is_group": False,
                    "visual_title": "Summary",
                    "visual_type": "pivotTable",
                }
            ),
            "'Summary'",
        )
        self.assertEqual(
            visual_name(
                {
                    "is_group": False,
                    "visual_title": "(untitled) tableEx 12345678",
                    "visual_type": "tableEx",
                }
            ),
            "tableEx",
        )

    def test_build_rows_follows_report_tree(self) -> None:
        rows = build_report_rows(result(), details())
        self.assertEqual(len(rows), 5)
        self.assertEqual(
            [
                (
                    row["Obj1_name"],
                    row["Obj2_name"],
                    row["Obj3_name"],
                    row["Obj4_name"],
                    row["Obj5_name"],
                )
                for row in rows
            ],
            [
                ("Overview", "Header", "'Dealer'", "Dealer", ""),
                ("Overview", "Header", "'Dealer'", "f1", "Region"),
                ("Overview", "'Summary'", "", "", ""),
                ("Overview", "pf1", "Segment", "", ""),
                ("rf1", "Channel", "", "", ""),
            ],
        )
        first = rows[0]
        self.assertEqual(first["Report_name"], "Dragon - NMS - Niguri Part")
        self.assertEqual(first["Report_type"], "Local report")
        self.assertEqual(first["Report_source"], "File")
        self.assertEqual(first["Report_no_of_visuals"], 3)
        self.assertEqual(first["Report_no_of_broken_visuals"], 1)
        self.assertEqual(first["Report_no_of_views"], "-")
        self.assertEqual(first["Report_pages"], 1)
        self.assertEqual(first["Report_theme"], "CY24SU10")
        self.assertEqual(first["Report_best_practices_score"], "60 (Critical)")
        self.assertEqual(first["Obj1_type"], "Page")
        self.assertEqual(first["Obj1_source"], "Dragon - NMS - Niguri Part")
        self.assertEqual(first["Obj1_no_of_visuals"], 3)
        self.assertEqual(first["Obj1_no_of_broken_visuals"], 1)
        self.assertEqual(first["Obj1_no_of_views"], "-")
        self.assertEqual(first["Obj2_type"], "visualGroup")
        self.assertEqual(first["Obj2_source"], "Overview")
        self.assertEqual(first["Obj2_is_broken"], "0")
        self.assertEqual(first["Obj3_type"], "slicer")
        self.assertEqual(first["Obj4_type"], "Column")
        self.assertEqual(first["Obj4_source"], "Sales")

        filter_row = rows[1]
        self.assertEqual(filter_row["Obj4_name"], "f1")
        self.assertEqual(filter_row["Obj4_type"], "Categorical")
        self.assertEqual(filter_row["Obj4_source"], "")
        self.assertEqual(filter_row["Obj5_source"], "Sales")

        broken = rows[2]
        self.assertEqual(broken["Obj2_name"], "'Summary'")
        self.assertEqual(broken["Obj2_is_broken"], "1")

        page_filter = rows[3]
        self.assertEqual(page_filter["Obj2_name"], "pf1")
        self.assertEqual(page_filter["Obj2_source"], "Overview")
        self.assertEqual(page_filter["Obj2_is_broken"], "")

        report_filter = rows[4]
        self.assertEqual(report_filter["Obj1_name"], "rf1")
        self.assertEqual(report_filter["Obj1_type"], "Advanced")
        self.assertEqual(report_filter["Obj1_source"], "Dragon - NMS - Niguri Part")

    def test_write_report_export_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Reports.xlsx"
            write_report_export(result(), details(), target)
            frame = pd.read_excel(target, "Reports", keep_default_na=False)
        self.assertEqual(list(frame.columns), REPORT_RESULT_COLUMNS)
        self.assertEqual(len(frame), 5)


if __name__ == "__main__":
    unittest.main()
