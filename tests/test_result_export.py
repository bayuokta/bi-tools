"""Uji ekspor tab Result mengikuti template Measure Killer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.column_stats import ColumnStat, MeasureStat, ModelStats, TableStat
from core.result_export import RESULT_COLUMNS, write_result_export
from core.usage_service import (
    AnalysisResult,
    ColumnAnalysis,
    HierarchyAnalysis,
    MeasureAnalysis,
    ModelReference,
)


def column_stat(column_id: int, name: str) -> ColumnStat:
    return ColumnStat(
        table="Sales",
        column=name,
        column_id=column_id,
        column_type="data",
        data_type="Text",
        format_string="",
        display_folder="",
        is_hidden=False,
        is_calculated=False,
        sort_by_column="",
        expression="",
        size_data_bytes=100,
        size_hierarchy_bytes=0,
        rows=10,
    )


class ResultExportTests(unittest.TestCase):
    def result(self) -> AnalysisResult:
        customer = column_stat(10, "Customer")
        amount = column_stat(11, "Amount")
        measure = MeasureStat(
            table="Sales",
            measure="Total",
            measure_id=20,
            data_type="Double",
            format_string="0",
        )
        stats = ModelStats(
            model_name="Model",
            compatibility_level=1600,
            last_update="",
            columns=[customer, amount],
            tables=[
                TableStat(
                    table="Sales",
                    table_id=1,
                    column_count=2,
                    rows=10,
                    size_data_bytes=200,
                    size_hierarchy_bytes=0,
                )
            ],
            segment_bytes=0,
            artifact_bytes=0,
            measures=[measure],
        )
        record = {
            "report_id": "r1",
            "report_name": "Report",
            "page_id": "p1",
            "page_name": "Page 1",
            "visual_id": "v1",
            "visual_type": "pivotTable",
            "visual_title": "(tanpa judul) pivotTable 12345678",
            "usage_kind": "field",
            "detail": "Values",
        }
        return AnalysisResult(
            dataset_id="ds",
            dataset_name="Model Uji",
            workspace_id="ws",
            workspace_name="Workspace",
            analyzed_at="2026-01-01T00:00:00",
            stats=stats,
            columns=[
                ColumnAnalysis(
                    column=customer,
                    status="Tidak dipakai",
                    reason="",
                ),
                ColumnAnalysis(
                    column=amount,
                    status="Dipakai",
                    reason="",
                    model_refs=[
                        ModelReference(
                            "measure", "'Sales'[Total]", "", blocking=False
                        )
                    ],
                ),
            ],
            reports=[],
            report_total=1,
            report_scanned=1,
            report_skipped=0,
            report_failed=0,
            method="admin",
            coverage="1 report",
            coverage_complete=True,
            measures=[
                MeasureAnalysis(
                    measure=measure,
                    status="Dipakai",
                    reason="",
                    report_records=[record],
                )
            ],
            hierarchies=[
                HierarchyAnalysis(
                    hierarchy={
                        "table": "Sales",
                        "hierarchy": "Calendar",
                        "is_hidden": False,
                        "display_folder": "",
                        "levels": "Year > Month",
                        "level_count": 2,
                    },
                    status="Dipakai",
                    reason="",
                    report_records=[
                        {
                            **record,
                            "visual_id": "v2",
                            "visual_type": "lineChart",
                            "visual_title": "Trend",
                        }
                    ],
                )
            ],
        )

    def test_writes_template_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Result.xlsx"
            write_result_export(self.result(), target)
            frame = pd.read_excel(target, "Result")

        self.assertEqual(list(frame.columns), RESULT_COLUMNS)
        customer = frame[frame["Name"] == "Customer"].iloc[0]
        self.assertEqual(customer["Status"], "Unused")
        self.assertEqual(int(customer["Number_of_Uses"]), 0)
        self.assertTrue(pd.isna(customer["Used_in_type"]))

        amount = frame[
            (frame["Name"] == "Amount")
            & (frame["Used_in_type"] == "Used in artifacts")
        ].iloc[0]
        self.assertEqual(amount["Used_in_name"], "Total")
        self.assertEqual(int(amount["Used_in_ID"]), 20)
        self.assertEqual(amount["Used_in_object_type"], "Measure")
        self.assertEqual(amount["Used_in_status"], "Used")

        total = frame[frame["Name"] == "Total"].iloc[0]
        self.assertEqual(total["Used_in_type"], "Used in visuals")
        self.assertEqual(total["Used_in_ID"], "v1")
        self.assertEqual(total["Used_in_name"], "pivotTable")
        self.assertEqual(total["Used_in_object_type"], "pivotTable")
        self.assertEqual(total["Used_in_table_page"], "Page 1")

        calendar = frame[frame["Name"] == "Calendar"].iloc[0]
        self.assertEqual(calendar["Type"], "Hierarchy")
        self.assertEqual(int(calendar["Number_of_Uses"]), 1)
        self.assertEqual(calendar["Used_in_name"], "Trend")
        self.assertEqual(calendar["Used_in_object_type"], "lineChart")


if __name__ == "__main__":
    unittest.main()
