"""Uji tab Unloaded M queries: pemakaian parameter/shared query dan status tabel."""

from __future__ import annotations

import unittest

from core.column_stats import ModelStats, TableStat
from core.unloaded_queries import build_unloaded_queries
from core.usage_service import AnalysisResult, ColumnAnalysis
from tests.test_table_export import column, record


def analysis_result(m_queries=None) -> AnalysisResult:
    amount = column("Sales", "Amount", 1, 100)
    qty = column("Sales", "Qty", 2, 100)
    material = column("Master Material", "Code", 3, 100)
    dim = column("Dim", "Code", 4, 100)
    local = column("Local", "X", 5, 100)
    stats = ModelStats(
        model_name="Model",
        compatibility_level=1600,
        last_update="",
        columns=[amount, qty, material, dim, local],
        tables=[
            TableStat(
                table="Sales", table_id=1, column_count=2, rows=10,
                size_data_bytes=200, size_hierarchy_bytes=0,
                storage_mode="Import", partition_count=1,
            ),
            TableStat(
                table="Master Material", table_id=2, column_count=1, rows=10,
                size_data_bytes=100, size_hierarchy_bytes=0,
                storage_mode="Import", partition_count=1,
            ),
            TableStat(
                table="Dim", table_id=3, column_count=1, rows=10,
                size_data_bytes=100, size_hierarchy_bytes=0,
                storage_mode="Import", partition_count=1,
            ),
            TableStat(
                table="Local", table_id=4, column_count=1, rows=10,
                size_data_bytes=100, size_hierarchy_bytes=0,
                storage_mode="Import", partition_count=1,
            ),
        ],
        segment_bytes=500,
        artifact_bytes=0,
    )
    return AnalysisResult(
        dataset_id="ds",
        dataset_name="Model Uji",
        workspace_id="ws",
        workspace_name="Workspace",
        analyzed_at="2026-01-01T00:00:00",
        stats=stats,
        columns=[
            ColumnAnalysis(column=amount, status="Used", reason="", report_records=[record()]),
            ColumnAnalysis(column=qty, status="Unused", reason=""),
            ColumnAnalysis(
                column=material, status="Used",
                reason="", report_records=[record(), record()],
            ),
            ColumnAnalysis(column=dim, status="Used", reason="", report_records=[record()]),
            ColumnAnalysis(column=local, status="Unused", reason=""),
        ],
        reports=[],
        report_total=0,
        report_scanned=0,
        report_skipped=0,
        report_failed=0,
        method="test",
        coverage="",
        coverage_complete=True,
        m_queries=list(m_queries or []),
    )


SAMPLE_QUERIES = [
    {"name": "RangeStart", "kind": "M Parameter", "expression": "#datetime(2026,1,1,0,0,0)", "position": 0},
    {"name": "ServerURL", "kind": "M Parameter", "expression": '"server"', "position": 1},
    {"name": "projectID", "kind": "M Parameter", "expression": '"project"', "position": 2},
    {"name": "DataSize", "kind": "M Parameter", "expression": '"All"', "position": 3},
    {"name": "LimitClause", "kind": "M Parameter", "expression": '"limit"', "position": 4},
    {"name": "Base Query", "kind": "M Query", "expression": 'let Source = Sql.Database(projectID) in Source', "position": 5},
    {"name": "Pages Testing", "kind": "M Query", "expression": "let Source = 1 in Source", "position": 6},
    {
        "name": "Sales",
        "kind": "Table",
        "expression": (
            'let Source = Sql.Database(projectID), '
            'Filtered = if DataSize = "Small" then Source else Source, '
            'Start = DateTime.ToText(RangeStart) in Filtered'
        ),
        "position": 0,
    },
    {
        "name": "Sales",
        "kind": "Table",
        "expression": 'let Start = DateTime.ToText(RangeStart) in Start',
        "position": 0,
    },
    {
        "name": "Master Material",
        "kind": "Table",
        "expression": (
            'let LimitClause = if DataSize = "Small" then " LIMIT 1" else "", '
            'Source = Sql.Database(projectID), '
            "Query = \"SELECT 1\" & LimitClause in Source"
        ),
        "position": 0,
    },
    {
        "name": "Dim",
        "kind": "Table",
        "expression": 'let Source = #"Base Query" in Source',
        "position": 0,
    },
    {
        "name": "Local",
        "kind": "Table",
        "expression": "let ServerURL = 1, Source = ServerURL in Source",
        "position": 0,
    },
]


class UnloadedQueryTests(unittest.TestCase):
    def by_name(self, rows) -> dict[str, dict]:
        return {row["name"]: row for row in rows}

    def test_roots_and_usage_match_template_semantics(self) -> None:
        rows = self.by_name(build_unloaded_queries(analysis_result(SAMPLE_QUERIES)))
        self.assertEqual(
            [row["name"] for row in build_unloaded_queries(analysis_result(SAMPLE_QUERIES))],
            [
                "Base Query",
                "Pages Testing",
                "RangeStart",
                "ServerURL",
                "projectID",
                "DataSize",
                "LimitClause",
            ],
        )
        self.assertEqual(rows["Pages Testing"]["status"], "Unused")
        self.assertEqual(rows["Pages Testing"]["uses"], 0)
        self.assertEqual(rows["Pages Testing"]["usages"], [])
        self.assertEqual(rows["ServerURL"]["status"], "Unused")
        self.assertEqual(rows["LimitClause"]["status"], "Unused")
        self.assertEqual(rows["Base Query"]["uses"], 1)
        self.assertEqual(rows["Base Query"]["status"], "Used")
        self.assertEqual(
            [usage["name"] for usage in rows["Base Query"]["usages"]],
            ["Dim"],
        )
        self.assertEqual(
            [usage["name"] for usage in rows["RangeStart"]["usages"]],
            ["Sales"],
        )
        self.assertEqual(
            [usage["name"] for usage in rows["DataSize"]["usages"]],
            ["Master Material", "Sales"],
        )
        self.assertEqual(
            [usage["name"] for usage in rows["projectID"]["usages"]],
            ["Dim", "Master Material", "Sales"],
        )

    def test_usage_status_and_uses_follow_table_groups(self) -> None:
        rows = self.by_name(build_unloaded_queries(analysis_result(SAMPLE_QUERIES)))
        sales = rows["RangeStart"]["usages"][0]
        self.assertEqual(sales["type"], "Table")
        self.assertEqual(sales["source"], "Model Uji")
        self.assertEqual(sales["status"], "Used 50.0% (1/2)")
        self.assertEqual(sales["uses"], 1)
        material = rows["DataSize"]["usages"][0]
        self.assertEqual(material["status"], "Used")
        self.assertEqual(material["uses"], 2)

    def test_parameter_inside_if_and_local_binding_are_distinguished(self) -> None:
        rows = self.by_name(build_unloaded_queries(analysis_result(SAMPLE_QUERIES)))
        self.assertEqual(
            [usage["name"] for usage in rows["DataSize"]["usages"]],
            ["Master Material", "Sales"],
        )
        self.assertEqual(rows["LimitClause"]["usages"], [])

    def test_shared_query_usage_is_transitive_and_cycle_safe(self) -> None:
        rows = self.by_name(
            build_unloaded_queries(
                analysis_result(
                    [
                        {"name": "StartParam", "kind": "M Parameter", "expression": "1"},
                        {"name": "A", "kind": "M Query", "expression": '#"B"'},
                        {"name": "B", "kind": "M Query", "expression": '#"A"'},
                        {
                            "name": "Sales",
                            "kind": "Table",
                            "expression": (
                                'let Source = #"A", First = StartParam in Source'
                            ),
                        },
                    ]
                )
            )
        )
        self.assertEqual([usage["name"] for usage in rows["A"]["usages"]], ["Sales"])
        self.assertEqual([usage["name"] for usage in rows["B"]["usages"]], ["Sales"])
        self.assertEqual(rows["StartParam"]["uses"], 1)

    def test_policy_expression_is_scanned(self) -> None:
        rows = self.by_name(
            build_unloaded_queries(
                analysis_result(
                    [
                        {"name": "RangeStart", "kind": "M Parameter", "expression": "1"},
                        {
                            "name": "Sales",
                            "kind": "Table",
                            "expression": "let Source = 1 in Source",
                        },
                        {
                            "name": "Sales",
                            "kind": "Table",
                            "expression": (
                                "let Start = DateTime.ToText(RangeStart) in Start"
                            ),
                        },
                    ]
                )
            )
        )
        self.assertEqual([usage["name"] for usage in rows["RangeStart"]["usages"]], ["Sales"])


if __name__ == "__main__":
    unittest.main()
