"""Uji ekspor tab Tables mengikuti template Measure Killer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.column_stats import ColumnStat, MeasureStat, ModelStats, TableStat
from core.table_export import (
    TABLE_RESULT_COLUMNS,
    build_table_groups,
    write_table_export,
)
from core.usage_service import (
    AnalysisResult,
    ColumnAnalysis,
    HierarchyAnalysis,
    MeasureAnalysis,
    ModelReference,
)


def column(
    table: str,
    name: str,
    column_id: int,
    size: int,
    *,
    column_type: str = "data",
) -> ColumnStat:
    return ColumnStat(
        table=table,
        column=name,
        column_id=column_id,
        column_type=column_type,
        data_type="Text",
        format_string="",
        display_folder="",
        is_hidden=False,
        is_calculated=column_type == "calculated",
        sort_by_column="",
        expression="",
        size_data_bytes=size,
        size_hierarchy_bytes=0,
        rows=10,
    )


def record(kind: str = "field") -> dict:
    return {
        "report_id": "r1",
        "report_name": "Report",
        "page_name": "Page 1",
        "visual_id": "v1",
        "visual_type": "tableEx",
        "visual_title": "",
        "usage_kind": kind,
        "detail": "Values",
    }


class TableExportTests(unittest.TestCase):
    def result(self) -> AnalysisResult:
        amount = column("Sales", "Amount", 10, 1536)
        customer = column("Sales", "Customer", 11, 512)
        date = column("Dates", "Date", 20, 2048)
        day = column("Dates", "Day", 21, 10, column_type="calculated")
        prev_key = column("Prev Dates", "Dates Key", 30, 100)
        parameter = column(
            "Parameter Posisi", "Parameter", 40, 100, column_type="Field parameter"
        )
        time_column = column("Time Intelligence", "Time Calculation", 50, 100)
        total = MeasureStat(
            table="Sales",
            measure="Total",
            measure_id=60,
            data_type="Double",
            format_string="#,0",
        )
        stats = ModelStats(
            model_name="Model",
            compatibility_level=1600,
            last_update="",
            columns=[
                amount,
                customer,
                date,
                day,
                prev_key,
                parameter,
                time_column,
            ],
            tables=[
                TableStat(
                    table="Sales",
                    table_id=1,
                    column_count=2,
                    rows=10,
                    size_data_bytes=2048,
                    size_hierarchy_bytes=0,
                    storage_mode="Import",
                    measure_count=1,
                    partition_count=1,
                ),
                TableStat(
                    table="Dates",
                    table_id=2,
                    column_count=2,
                    rows=10,
                    size_data_bytes=2048,
                    size_hierarchy_bytes=0,
                    storage_mode="Import",
                    partition_count=1,
                ),
                TableStat(
                    table="Prev Dates",
                    table_id=3,
                    column_count=1,
                    rows=10,
                    size_data_bytes=100,
                    size_hierarchy_bytes=0,
                    storage_mode="Import",
                    is_calculated_table=True,
                    partition_count=1,
                ),
                TableStat(
                    table="Parameter Posisi",
                    table_id=4,
                    column_count=1,
                    rows=10,
                    size_data_bytes=100,
                    size_hierarchy_bytes=0,
                    storage_mode="Import",
                    is_calculated_table=True,
                    partition_count=1,
                ),
                TableStat(
                    table="Time Intelligence",
                    table_id=5,
                    column_count=1,
                    rows=10,
                    size_data_bytes=100,
                    size_hierarchy_bytes=0,
                    storage_mode="Import",
                    is_calculated_table=True,
                    is_calculation_group=True,
                    partition_count=1,
                ),
            ],
            segment_bytes=0,
            artifact_bytes=0,
            measures=[total],
        )
        dependencies = [
            {
                "OBJECT_TYPE": "MEASURE",
                "TABLE": "Sales",
                "OBJECT": "Total",
                "REFERENCED_OBJECT_TYPE": "TABLE",
                "REFERENCED_TABLE": "Sales",
                "REFERENCED_OBJECT": "Sales",
            },
            {
                "OBJECT_TYPE": "MEASURE",
                "TABLE": "Sales",
                "OBJECT": "Total",
                "REFERENCED_OBJECT_TYPE": "MEASURE",
                "REFERENCED_TABLE": "Sales",
                "REFERENCED_OBJECT": "Other",
            },
            {
                "OBJECT_TYPE": "CALC_TABLE",
                "TABLE": "Parameter Posisi",
                "OBJECT": "Parameter Posisi",
                "REFERENCED_OBJECT_TYPE": "TABLE",
                "REFERENCED_TABLE": "Sales",
                "REFERENCED_OBJECT": "Sales",
            },
            {
                "OBJECT_TYPE": "CALC_COLUMN",
                "TABLE": "Dates",
                "OBJECT": "Day",
                "REFERENCED_OBJECT_TYPE": "COLUMN",
                "REFERENCED_TABLE": "Dates",
                "REFERENCED_OBJECT": "Date",
            },
            {
                "OBJECT_TYPE": "CALC_TABLE",
                "TABLE": "Prev Dates",
                "OBJECT": "Prev Dates",
                "REFERENCED_OBJECT_TYPE": "TABLE",
                "REFERENCED_TABLE": "Dates",
                "REFERENCED_OBJECT": "Dates",
            },
            {
                "OBJECT_TYPE": "CALCULATION_ITEM",
                "TABLE": "Time Intelligence",
                "OBJECT": "MTD",
                "REFERENCED_OBJECT_TYPE": "TABLE",
                "REFERENCED_TABLE": "Dates",
                "REFERENCED_OBJECT": "Dates",
            },
            {
                "OBJECT_TYPE": "HIERARCHY",
                "TABLE": "Dates",
                "OBJECT": "Calendar",
                "REFERENCED_OBJECT_TYPE": "TABLE",
                "REFERENCED_TABLE": "Dates",
                "REFERENCED_OBJECT": "Dates",
            },
        ]
        roles = [
            {
                "name": "Dealer",
                "permissions": [
                    {
                        "table": "Sales",
                        "expression": "[Email] = USERPRINCIPALNAME()",
                        "has_ols": False,
                    },
                    {"table": "Dates", "expression": "", "has_ols": True},
                ],
            },
            {
                "name": "HO",
                "permissions": [
                    {"table": "Sales", "expression": "TRUE()", "has_ols": False}
                ],
            },
        ]
        return AnalysisResult(
            dataset_id="ds",
            dataset_name="Model Uji",
            workspace_id="ws",
            workspace_name="Workspace",
            analyzed_at="2026-01-01T00:00:00",
            stats=stats,
            columns=[
                ColumnAnalysis(
                    column=amount,
                    status="Used",
                    reason="",
                    report_records=[record(), record()],
                ),
                ColumnAnalysis(column=customer, status="Unused", reason=""),
                ColumnAnalysis(
                    column=date,
                    status="Used",
                    reason="",
                    model_refs=[
                        ModelReference(
                            "calculation item",
                            "calculation item 'MTD'",
                            "",
                            source_table="Time Intelligence",
                            source_id=700,
                        )
                    ],
                ),
                ColumnAnalysis(
                    column=day,
                    status="Used",
                    reason="",
                    report_records=[record()],
                ),
                ColumnAnalysis(
                    column=prev_key,
                    status="Used",
                    reason="",
                    report_records=[record()],
                ),
                ColumnAnalysis(
                    column=parameter,
                    status="Used",
                    reason="",
                    model_refs=[
                        ModelReference(
                            "field parameter", "'Parameter Posisi'", ""
                        )
                    ],
                ),
                ColumnAnalysis(
                    column=time_column,
                    status="Used",
                    reason="",
                    report_records=[record()],
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
                    measure=total,
                    status="Used",
                    reason="",
                    report_records=[record(), record(), record()],
                )
            ],
            hierarchies=[
                HierarchyAnalysis(
                    hierarchy={"table": "Dates", "hierarchy": "Calendar"},
                    status="Used",
                    reason="",
                    report_records=[record()],
                )
            ],
            roles=roles,
            table_dependencies=dependencies,
        )

    def groups(self) -> dict[str, dict]:
        return {group["table"]: group for group in build_table_groups(self.result())}

    def test_table_header_and_uses(self) -> None:
        sales = self.groups()["Sales"]
        self.assertEqual(sales["type_label"], "Table")
        self.assertEqual(sales["size"], "2.0 kB")
        self.assertEqual(sales["status"], "Used 66.7% (2/3)")
        # own uses: Amount 2 + Total 3; usage rows: Total artifact, field
        # parameter, Dealer RLS, HO RLS.
        self.assertEqual(sales["uses"], 9)
        self.assertTrue(sales["has_error"] is False)

        dates = self.groups()["Dates"]
        self.assertEqual(dates["type_label"], "Table")
        self.assertEqual(dates["status"], "Used")
        # own uses: Date 1 + Day 1 (hierarchy excluded); usage rows:
        # Day artifact, Prev Dates, MTD, Dealer OLS.
        self.assertEqual(dates["uses"], 6)
        self.assertTrue(dates["has_error"] is False)

    def test_group_order_and_rows(self) -> None:
        sales = self.groups()["Sales"]
        labels = []
        for row in sales["rows"]:
            if not labels or labels[-1] != row["usage_type"]:
                labels.append(row["usage_type"])
        self.assertEqual(
            labels,
            [
                "Used in artifacts",
                "Used in field parameters",
                "Columns",
                "Measures",
                "Used in row/object level security",
            ],
        )
        artifact = sales["rows"][0]
        self.assertEqual(artifact["name"], "Total")
        self.assertEqual(artifact["object_type"], "Measure")
        self.assertEqual(artifact["object_id"], 60)
        self.assertEqual(artifact["uses"], 3)
        self.assertEqual(artifact["table"], "Sales")

        columns = [
            row for row in sales["rows"] if row["usage_type"] == "Columns"
        ]
        self.assertEqual([row["name"] for row in columns], ["Amount", "Customer"])

        security = [
            row
            for row in sales["rows"]
            if row["usage_type"] == "Used in row/object level security"
        ]
        self.assertEqual(
            [(row["name"], row["object_type"]) for row in security],
            [("Dealer", "Row level security"), ("HO", "Row level security")],
        )

    def test_calculated_table_field_parameter_and_calculation_item(self) -> None:
        groups = self.groups()
        dates = groups["Dates"]
        calculated = [
            row
            for row in dates["rows"]
            if row["usage_type"] == "Used in calculated tables"
        ]
        self.assertEqual(len(calculated), 1)
        self.assertEqual(calculated[0]["name"], "Prev Dates")
        self.assertEqual(calculated[0]["object_type"], "Calculated Table")
        self.assertEqual(calculated[0]["object_id"], 3)
        self.assertEqual(calculated[0]["uses"], 1)
        self.assertEqual(calculated[0]["status"], "Used")

        items = [
            row
            for row in dates["rows"]
            if row["usage_type"] == "Used in calculation items"
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "MTD")
        self.assertEqual(items[0]["object_id"], 700)
        self.assertEqual(items[0]["table"], "Time Intelligence")

        field_parameter = [
            row
            for row in groups["Sales"]["rows"]
            if row["usage_type"] == "Used in field parameters"
        ]
        self.assertEqual(len(field_parameter), 1)
        self.assertEqual(field_parameter[0]["name"], "Parameter Posisi")
        self.assertEqual(field_parameter[0]["object_type"], "Field param. table")
        self.assertEqual(field_parameter[0]["object_id"], 4)
        self.assertEqual(field_parameter[0]["uses"], 1)

        self.assertEqual(
            groups["Parameter Posisi"]["type_label"], "Field param. table"
        )
        self.assertEqual(groups["Prev Dates"]["type_label"], "Calculated Table")
        self.assertEqual(
            groups["Time Intelligence"]["type_label"], "Calculation group"
        )

    def test_security_includes_ols(self) -> None:
        dates = self.groups()["Dates"]
        security = [
            row
            for row in dates["rows"]
            if row["usage_type"] == "Used in row/object level security"
        ]
        self.assertEqual(len(security), 1)
        self.assertEqual(security[0]["name"], "Dealer")
        self.assertEqual(security[0]["object_type"], "Object level security")
        self.assertEqual(security[0]["object_id"], "")

    def test_hierarchy_row_uses_na_and_is_not_counted(self) -> None:
        dates = self.groups()["Dates"]
        hierarchies = [
            row for row in dates["rows"] if row["usage_type"] == "Hierarchies"
        ]
        self.assertEqual(len(hierarchies), 1)
        self.assertEqual(hierarchies[0]["name"], "Calendar")
        self.assertEqual(hierarchies[0]["uses"], 1)
        self.assertEqual(hierarchies[0]["has_error"], "N/A")
        self.assertEqual(dates["uses"], 6)

    def test_write_table_export_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Tables.xlsx"
            write_table_export(self.result(), target)
            frame = pd.read_excel(target, "Tables", keep_default_na=False)

        self.assertEqual(list(frame.columns), TABLE_RESULT_COLUMNS)
        self.assertEqual(len(frame), 17)
        sales = frame[frame["Table_name"] == "Sales"].iloc[0]
        self.assertEqual(sales["Table_type"], "Table")
        self.assertEqual(sales["Table_status"], "Used 66.7% (2/3)")
        self.assertEqual(int(sales["Table_uses"]), 9)
        self.assertEqual(sales["Table_storage_mode"], "Import")
        artifact = frame[
            (frame["Table_name"] == "Sales")
            & (frame["Used_in_name"] == "Total")
        ].iloc[0]
        self.assertEqual(artifact["Usage_sub_level_type"], "Used in artifacts")
        self.assertEqual(int(artifact["Used_in_ID"]), 60)
        self.assertEqual(artifact["Used_in_object_type"], "Measure")
        self.assertEqual(int(artifact["Used_in_number_of_uses"]), 3)
        hierarchy = frame[
            (frame["Table_name"] == "Dates")
            & (frame["Used_in_name"] == "Calendar")
        ].iloc[0]
        self.assertEqual(hierarchy["Has_error"], "N/A")
        ols = frame[
            (frame["Table_name"] == "Dates")
            & (frame["Used_in_object_type"] == "Object level security")
        ].iloc[0]
        self.assertEqual(ols["Used_in_name"], "Dealer")
        field_parameter = frame[
            (frame["Table_name"] == "Sales")
            & (frame["Usage_sub_level_type"] == "Used in field parameters")
        ].iloc[0]
        self.assertEqual(field_parameter["Used_in_object_type"], "Field param. table")
        self.assertEqual(int(field_parameter["Used_in_number_of_uses"]), 1)
        table_order = list(dict.fromkeys(frame["Table_name"]))
        self.assertEqual(
            table_order,
            ["Dates", "Sales", "Parameter Posisi", "Prev Dates", "Time Intelligence"],
        )


if __name__ == "__main__":
    unittest.main()
