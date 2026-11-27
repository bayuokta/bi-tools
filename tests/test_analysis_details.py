"""Uji objek detail kolom/measure (flag, dependency, field tak terdeteksi)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.analysis_details import item_details


def ref(kind: str, obj: str, detail: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        kind=kind, object=obj, detail=detail, blocking=False
    )


def column_fixture() -> tuple[SimpleNamespace, SimpleNamespace]:
    column = SimpleNamespace(
        table="Sales",
        column="Amount",
        column_id=10,
        data_type="Double",
        format_string="0.00",
        display_folder="Measures",
        is_hidden=False,
        is_calculated=False,
        expression="",
        rows=100,
        size_total_bytes=2048,
        size_data_bytes=1024,
        size_hierarchy_bytes=512,
        size_dictionary_bytes=512,
        cardinality=1234,
    )
    analysis = SimpleNamespace(
        column=column,
        status="Used",
        reason="Used di 2 titik.",
        model_refs=[
            ref("measure", "'KPI'[Total]"),
            ref("relationship", "'Dim Date'[Date]"),
            ref("sort by", "'Sales'[Amount Sort]"),
            ref("hierarchy", "'Sales'[Geography]"),
            ref("RLS", "role 'Reader'"),
            ref("field parameter", "'Param'"),
            ref("calculation item", "calculation item 'YTD'"),
            ref("KPI", "KPI 'Target'"),
            ref("langkah M", "query 'Sales'"),
        ],
        report_records=[
            {
                "usage_kind": "field",
                "report_name": "Report Uji",
                "page_name": "Halaman 1",
                "visual_title": "Tabel",
                "visual_type": "tableEx",
                "detail": "Values",
                "is_hidden": False,
            },
            {
                "usage_kind": "filter-page",
                "report_name": "Report Uji",
                "page_name": "Halaman 1",
                "visual_title": "",
                "visual_type": "",
                "detail": "Categorical",
                "is_hidden": True,
            },
        ],
    )
    result = SimpleNamespace(
        dataset_name="Model Uji",
        relationships=[
            {
                "name": "Rel",
                "from_table": "Sales",
                "from_column": "Amount",
                "to_table": "Dim Date",
                "to_column": "Date",
                "is_active": True,
                "from_cardinality": "many",
                "to_cardinality": "one",
            },
            {
                "name": "Rel2",
                "from_table": "Dim Date",
                "from_column": "Date",
                "to_table": "Sales",
                "to_column": "Amount",
                "is_active": False,
                "from_cardinality": "one",
                "to_cardinality": "many",
            },
        ],
    )
    return result, analysis


class ColumnDetailsTests(unittest.TestCase):
    def test_flags_and_properties(self) -> None:
        result, analysis = column_fixture()
        details = item_details(result, analysis, kind="column")
        self.assertEqual(details["name"], "Amount")
        self.assertEqual(details["table_name"], "Sales")
        self.assertEqual(details["type"], "Column")
        self.assertEqual(details["size"], 2048)
        self.assertEqual(details["cardinality"], 1234)
        self.assertEqual(details["id"], 10)
        self.assertEqual(details["is_used"], "Used")
        self.assertTrue(details["is_used_relationships"])
        self.assertTrue(details["is_used_sorting"])
        self.assertTrue(details["is_used_hierarchy"])
        self.assertTrue(details["is_used_row_level_security"])
        self.assertTrue(details["is_used_field_parameters"])
        self.assertTrue(details["is_used_calculation_items"])
        self.assertTrue(details["is_used_kpis"])
        self.assertTrue(details["is_used_power_query"])
        self.assertTrue(details["is_used_visuals"])
        self.assertTrue(details["is_used_page_level_filters"])
        self.assertIsNone(details["is_used_excel"])
        self.assertIn("is_used_excel", details["unsupported"])

    def test_dependencies(self) -> None:
        result, analysis = column_fixture()
        details = item_details(result, analysis, kind="column")
        self.assertEqual(details["model_dependencies"][0]["object"], "'KPI'[Total]")
        self.assertEqual(
            details["model_dependencies"][0]["target_kind"], "measure"
        )
        self.assertEqual(
            details["model_dependencies"][0]["target_name"], "Total"
        )
        self.assertEqual(len(details["relationship_dependencies"]), 2)
        self.assertEqual(
            details["relationship_dependencies"][0]["relationship_type"],
            "Active Many to One",
        )
        self.assertEqual(
            details["relationship_dependencies"][0]["target_kind"], "column"
        )
        self.assertTrue(
            details["relationship_dependencies"][0]["target_table"]
        )
        self.assertEqual(details["key_column_dependencies"][0]["table"], "Dim Date")
        self.assertEqual(
            details["key_column_dependencies"][0]["target_kind"], "column"
        )
        self.assertEqual(
            details["key_column_dependencies"][0]["target_name"], "Date"
        )
        self.assertEqual(details["visual_dependencies"][0]["page"], "Halaman 1")
        self.assertEqual(
            details["page_level_filters_dependencies"][0]["detail"], "Categorical"
        )
        self.assertIsNone(details["mobile_layout_dependencies"])


class MeasureDetailsTests(unittest.TestCase):
    def test_measure_details(self) -> None:
        measure = SimpleNamespace(
            table="KPI",
            measure="Total",
            data_type="Double",
            format_string="0",
            display_folder="KPI",
            is_hidden=False,
            expression="SUM('Sales'[Amount])",
        )
        analysis = SimpleNamespace(
            measure=measure,
            status="Must keep",
            reason="Dirujuk objek model.",
            model_refs=[
                ref("measure", "'KPI'[Other]"),
                ref("calculation item", "calculation item 'YTD'"),
                ref("KPI", "KPI 'Target'"),
            ],
            report_records=[],
        )
        result = SimpleNamespace(dataset_name="Model Uji", relationships=[])
        details = item_details(result, analysis, kind="measure")
        self.assertEqual(details["type"], "Measure")
        self.assertEqual(details["size"], 0)
        self.assertEqual(details["expression"], "SUM('Sales'[Amount])")
        self.assertEqual(details["is_used"], "Must keep")
        self.assertEqual(details["model_dependencies"][0]["object"], "'KPI'[Other]")
        self.assertEqual(len(details["calculation_item_dependencies"]), 1)
        self.assertEqual(len(details["kpi_dependencies"]), 1)
        self.assertFalse(details["is_used_visuals"])


if __name__ == "__main__":
    unittest.main()
