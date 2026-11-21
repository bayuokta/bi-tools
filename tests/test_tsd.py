"""Uji generate TSD dari workbook metadata (tanpa network)."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from core.errors import ExtractionError
from core.m_lineage import CONNECTOR_SPECS, build_lineage
from core.model import CONNECTORS
from core.pbi_capture import CaptureOptions, ScreenshotSet
from core.tsd import (
    SCREENSHOT_ASSET_DIR,
    TEMPLATE_PATH,
    CONNECTOR_PATTERNS,
    _connector_kind,
    _filters,
    _infer_connector,
    _m_output,
    _report_page_size,
    _tables,
    _visuals,
    build_context,
    manual_skeleton,
    output_file_name,
    render_tsd,
    run_tsd,
)


def write_workbook(path: Path, sheets: dict[str, pd.DataFrame]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path) as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
    return path


def report_sheets() -> dict[str, pd.DataFrame]:
    return {
        "01_Pages": pd.DataFrame(
            [
                {
                    "page_order": 2,
                    "page_name": "Detail",
                    "page_id": "p2",
                    "is_hidden": True,
                },
                {
                    "page_order": 1,
                    "page_name": "Overview",
                    "page_id": "p1",
                    "is_hidden": False,
                },
            ]
        ),
        "08_Visual_Summary": pd.DataFrame(
            [
                {
                    "page_order": 1,
                    "page_name": "Overview",
                    "page_id": "p1",
                    "visual_name": "Sales by Region",
                    "visual_id": "v1",
                    "visual_type": "barChart",
                    "fields": "Branch[Region]\nSales[Total]",
                    "is_hidden": True,
                },
                {
                    "page_order": 1,
                    "page_name": "Overview",
                    "page_id": "p1",
                    "visual_name": "KPI",
                    "visual_id": "v2",
                    "visual_type": "card",
                    "fields": "Sales[Total]",
                    "is_hidden": False,
                },
                {
                    "page_order": 2,
                    "page_name": "Detail",
                    "page_id": "p2",
                    "visual_name": "Table",
                    "visual_id": "v3",
                    "visual_type": "tableEx",
                    "fields": "Sales[Amount]",
                    "is_hidden": False,
                },
                {
                    "page_order": 1,
                    "page_name": "Overview",
                    "page_id": "p1",
                    "visual_name": "Background",
                    "visual_id": "v4",
                    "visual_type": "shape",
                    "fields": "",
                    "is_hidden": False,
                },
                {
                    "page_order": 1,
                    "page_name": "Overview",
                    "page_id": "p1",
                    "visual_name": "Logo",
                    "visual_id": "v5",
                    "visual_type": "image",
                    "fields": "",
                    "is_hidden": False,
                },
            ]
        ),
        "03_Interactions": pd.DataFrame(
            [
                {
                    "page_id": "p1",
                    "source_visual_id": "v1",
                    "source_visual_name": "Sales by Region",
                    "target_visual_id": "v2",
                    "target_visual_name": "KPI",
                    "interaction_type": "DataFilter",
                },
                {
                    "page_id": "p1",
                    "source_visual_id": "v1",
                    "source_visual_name": "Sales by Region",
                    "target_visual_id": "v3",
                    "target_visual_name": "Table",
                    "interaction_type": "NoFilter",
                },
                {
                    "page_id": "p1",
                    "source_visual_id": "v2",
                    "source_visual_name": "KPI",
                    "target_visual_id": "v1",
                    "target_visual_name": "Sales by Region",
                    "interaction_type": "HighlightFilter",
                },
            ]
        ),
        "04_Visual_Fields": pd.DataFrame(
            [
                {
                    "page_id": "p1",
                    "visual_id": "v1",
                    "field_role": "Category",
                    "field_kind": "Column",
                    "table": "Branch",
                    "field": "Region",
                    "query_ref": "Branch.Region",
                    "display_name": "Region",
                    "native_query_ref": "Region",
                    "aggregation": "",
                    "expression": "",
                },
                {
                    "page_id": "p1",
                    "visual_id": "v1",
                    "field_role": "Values",
                    "field_kind": "Measure",
                    "table": "Sales",
                    "field": "Total Amount",
                    "query_ref": "Sales.Total Amount",
                    "display_name": "Total",
                    "native_query_ref": "Total",
                    "aggregation": "",
                    "expression": "",
                },
                {
                    "page_id": "p1",
                    "visual_id": "v1",
                    "field_role": "Values",
                    "field_kind": "Aggregation",
                    "table": "Sales",
                    "field": "Amount",
                    "query_ref": "Sum(Sales.Amount)",
                    "display_name": "Amount",
                    "native_query_ref": "Amount",
                    "aggregation": "Sum",
                    "expression": "",
                },
                {
                    "page_id": "p1",
                    "visual_id": "v1",
                    "field_role": "Values",
                    "field_kind": "VisualCalculation",
                    "table": "",
                    "field": "Avg Order",
                    "query_ref": "Avg Order",
                    "display_name": "Avg Order",
                    "native_query_ref": "Avg Order",
                    "aggregation": "",
                    "expression": "[Total] / [Order Count]",
                },
                {
                    "page_id": "p1",
                    "visual_id": "v2",
                    "field_role": "Values",
                    "field_kind": "Measure",
                    "table": "Sales",
                    "field": "Total Amount",
                    "query_ref": "Sales.Total Amount",
                    "display_name": "Total",
                    "native_query_ref": "Total",
                    "aggregation": "",
                    "expression": "",
                },
                {
                    "page_id": "p2",
                    "visual_id": "v3",
                    "field_role": "Values",
                    "field_kind": "Column",
                    "table": "Sales",
                    "field": "Amount",
                    "query_ref": "Sales.Amount",
                    "display_name": "Amount",
                    "native_query_ref": "Amount",
                    "aggregation": "",
                    "expression": "",
                },
            ]
        ),
        "07_Filters": pd.DataFrame(
            [
                {
                    "scope": "Report",
                    "page_id": None,
                    "visual_id": None,
                    "table": "Date",
                    "field": "Year",
                    "filter_type": "Categorical",
                    "values": "is 2026",
                    "hidden_in_view_mode": False,
                    "locked_in_view_mode": False,
                    "has_filter_definition": True,
                },
                {
                    "scope": "Page",
                    "page_id": "p1",
                    "visual_id": None,
                    "table": "Branch",
                    "field": "Region",
                    "filter_type": "Categorical",
                    "values": "is West",
                    "hidden_in_view_mode": True,
                    "locked_in_view_mode": True,
                    "has_filter_definition": True,
                },
                {
                    "scope": "Visual",
                    "page_id": "p1",
                    "visual_id": "v1",
                    "table": "Date",
                    "field": "Month",
                    "filter_type": "Categorical",
                    "values": "is Jan",
                    "hidden_in_view_mode": False,
                    "locked_in_view_mode": False,
                    "has_filter_definition": True,
                },
                {
                    "scope": "Visual",
                    "page_id": "p1",
                    "visual_id": "v2",
                    "table": "Date",
                    "field": "Quarter",
                    "filter_type": "Advanced",
                    "values": "",
                    "hidden_in_view_mode": False,
                    "locked_in_view_mode": True,
                    "has_filter_definition": False,
                },
                {
                    "scope": "Visual",
                    "page_id": "p2",
                    "visual_id": "v3",
                    "table": "Sales",
                    "field": "Amount",
                    "filter_type": "Advanced",
                    "values": "",
                    "hidden_in_view_mode": False,
                    "locked_in_view_mode": False,
                    "has_filter_definition": True,
                },
                {
                    "scope": "Page",
                    "page_id": "p2",
                    "visual_id": None,
                    "table": "Branch",
                    "field": "Region",
                    "filter_type": "Categorical",
                    "values": "is East",
                    "hidden_in_view_mode": False,
                    "locked_in_view_mode": False,
                    "has_filter_definition": True,
                },
            ]
        ),
        "06_Sync_Slicers": pd.DataFrame(
            [
                {
                    "sync_group": "SyncYear",
                    "page_order": 1,
                    "page_name": "Overview",
                    "table": "Date",
                    "column": "Year",
                    "group_pages": "Overview, Detail",
                },
                {
                    "sync_group": "SyncYear",
                    "page_order": 2,
                    "page_name": "Detail",
                    "table": "Date",
                    "column": "Year",
                    "group_pages": "Overview, Detail",
                },
                {"sync_group": None, "page_order": None, "page_name": None},
            ]
        ),
        "02_Bookmarks": pd.DataFrame(
            [
                {
                    "status": "OK",
                    "bookmark_name": "Reset Filters",
                    "display_name": None,
                    "page_name": "Overview",
                    "target_visuals": "v1, v2",
                    "apply_only_to_target_visuals": True,
                    "suppress_data": False,
                },
                {"status": "TIDAK ADA BOOKMARK", "bookmark_name": None},
            ]
        ),
    }


def model_sheets() -> dict[str, pd.DataFrame]:
    return {
        "02_Tables": pd.DataFrame(
            [
                {"table": "Sales", "storage_mode": "Import", "description": "Sales fact"},
                {"table": "Date", "storage_mode": "Import", "description": "Date dim"},
                {"table": "Target", "storage_mode": "Import", "description": ""},
                {"table": "ExchangeRate", "storage_mode": "Import", "description": ""},
                {"table": "Inline", "storage_mode": "Import", "description": ""},
            ]
        ),
        "05_Partitions": pd.DataFrame(
            [
                {
                    "table": "Sales",
                    "partition": "Sales",
                    "source_type": "m",
                    "source": (
                        "let\n"
                        '    Source = Sql.Database("sql-host", "ERP"),\n'
                        '    #"Added Custom" = Table.AddColumn('
                        'Source, "Amount Group", each\n'
                        '        if [Amount] > 0 then "positive" else "other"),\n'
                        '    Filtered = Table.SelectRows(#"Added Custom", '
                        "each [Amount] >= RangeStart)\n"
                        "in\n"
                        "    Filtered"
                    ),
                    "source_expression": None,
                },
                {
                    "table": "Sales",
                    "partition": "2025H1",
                    "source_type": "policyRange",
                    "source": None,
                    "source_expression": "RangeStart",
                    "incremental_granularity": "day",
                    "incremental_periods": 30,
                },
                {
                    "table": "Date",
                    "partition": "Date",
                    "source_type": "calculated",
                    "source": "Date = CALENDAR ( DATE ( 2024, 1, 1 ), DATE ( 2024, 12, 31 ) )",
                    "source_expression": None,
                },
                {
                    "table": "Target",
                    "partition": "Target",
                    "source_type": "m",
                    "source": "let Source = PowerPlatform.Dataflows(null) in Source",
                    "source_expression": None,
                },
                {
                    "table": "ExchangeRate",
                    "partition": "ExchangeRate",
                    "source_type": "m",
                    "source": "let Source = Excel.Workbook(Web.Contents(SourceFile), null, true) in Source",
                    "source_expression": None,
                },
                {
                    "table": "Inline",
                    "partition": "Inline",
                    "source_type": "m",
                    "source": "let Source = #table({\"A\"}, {{\"x\"}}) in Source",
                    "source_expression": None,
                },
            ]
        ),
        "15_Data_Sources": pd.DataFrame(
            [
                {"table": "Sales", "connector": "Sql.Database", "server": "sql-host", "database": "ERP"},
                {
                    "table": "Target",
                    "connector": "PowerPlatform.Dataflows",
                    "server": "ws-guid",
                    "database": "df-guid",
                },
                {
                    "table": "ExchangeRate",
                    "connector": "Excel.Workbook",
                    "server": "sharepoint",
                    "database": "",
                },
            ]
        ),
        "03_Columns": pd.DataFrame(
            [
                {
                    "table": "Sales",
                    "column": "Amount",
                    "source_column": "amount",
                    "data_type": "decimal",
                    "description": None,
                    "m_transform_chain": None,
                    "is_hidden": False,
                    "is_calculated": False,
                    "expression": None,
                },
                {
                    "table": "Sales",
                    "column": "Amount Group",
                    "source_column": None,
                    "data_type": "decimal",
                    "description": None,
                    "m_transform_chain": "amount -> Amount Group",
                    "is_hidden": False,
                    "is_calculated": False,
                    "expression": None,
                },
                {
                    "table": "Sales",
                    "column": "Amount Label",
                    "source_column": None,
                    "data_type": "string",
                    "description": "Label for slicer",
                    "m_transform_chain": None,
                    "is_hidden": True,
                    "is_calculated": True,
                    "expression": '[Amount] & ""',
                },
            ]
        ),
        "04_Measures": pd.DataFrame(
            [
                {
                    "table": "Sales",
                    "measure": "Total Amount",
                    "expression": "SUM ( Sales[Amount] )",
                    "description": "Total sales",
                }
            ]
        ),
        "07_Relationships": pd.DataFrame(
            [
                {
                    "from_table": "Sales",
                    "from_column": "DateKey",
                    "to_table": "Date",
                    "to_column": "DateKey",
                    "cross_filtering": "oneDirection",
                    "security_filtering": "oneDirection",
                    "is_active": True,
                    "from_cardinality": "many",
                    "to_cardinality": "one",
                },
                {
                    "from_table": "Sales",
                    "from_column": "AltDateKey",
                    "to_table": "Date",
                    "to_column": "DateKey",
                    "cross_filtering": "oneDirection",
                    "security_filtering": "bothDirections",
                    "is_active": False,
                    "from_cardinality": "many",
                    "to_cardinality": "one",
                },
            ]
        ),
        "08_Roles_RLS": pd.DataFrame(
            [
                {
                    "role": "Branch Manager",
                    "table": "Branch",
                    "table_permission_expression": "[BranchCode] = USERPRINCIPALNAME ()",
                },
                {
                    "role": "Branch Manager",
                    "table": "Sales",
                    "table_permission_expression": "TRUE()",
                },
                {
                    "role": "Reader",
                    "table": "Sales",
                    "table_permission_expression": "FALSE()",
                },
            ]
        ),
        "18_Hierarchies": pd.DataFrame(
            [{"table": "Branch", "hierarchy": "Geography", "levels": "RegionName\nAreaName"}]
        ),
        "06_Expressions_Params": pd.DataFrame(
            [
                {"name": "RangeStart", "kind": "Parameter", "value": "2024-01-01"},
                {"name": "SourceFile", "kind": "Parameter", "value": "rates.xlsx"},
                {"name": "NotParameter", "kind": "Expression", "value": "x"},
            ]
        ),
    }


class OutputNameTests(unittest.TestCase):
    """Nama file TSD bawaan memakai akhiran report ID untuk report Service."""

    def test_name_without_report_id(self) -> None:
        self.assertEqual(output_file_name("Uji"), "TSD_Uji.html")
        self.assertEqual(output_file_name(""), "TSD_Report.html")

    def test_name_includes_id8(self) -> None:
        self.assertEqual(
            output_file_name(
                "Report Uji",
                "66666666-6666-4666-8666-666666666666",
            ),
            "TSD_Report Uji_66666666.html",
        )


class TsdTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.report_path = write_workbook(self.tmp / "Report_Metadata.xlsx", report_sheets())
        self.model_path = write_workbook(
            self.tmp / "Semantic_Model_Metadata.xlsx", model_sheets()
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def context(self, **kwargs):
        options = {
            "report_workbook": self.report_path,
            "model_workbook": self.model_path,
            "report_name": "Uji",
            "generated_at": "13 November 2026",
            "log": lambda _message: None,
        }
        options.update(kwargs)
        return build_context(**options)


class DefaultOutputTests(TsdTestCase):
    def test_default_output_uses_report_id(self) -> None:
        folder = self.tmp / "default"
        folder.mkdir()
        with patch("core.tsd.OUT_FILE", folder / "Report_Metadata.xlsx"):
            summary = run_tsd(
                report_workbook=self.report_path,
                report_name="Uji",
                report_id="66666666-6666-4666-8666-666666666666",
                save_manual=False,
                log=lambda _message: None,
            )
        self.assertEqual(summary["output"].name, "TSD_Uji_66666666.html")
        self.assertEqual(summary["manual"].name, "TSD_Uji_66666666.json")
        self.assertTrue(summary["output"].exists())

    def test_default_output_uses_capture_report_id(self) -> None:
        folder = self.tmp / "default_capture"
        folder.mkdir()
        options = CaptureOptions(
            workspace_id="11111111-1111-4111-8111-111111111111",
            report_id="22222222-2222-4222-8222-222222222222",
        )
        with patch("core.tsd.OUT_FILE", folder / "Report_Metadata.xlsx"), patch(
            "core.pbi_capture.runner.load_or_capture", return_value=None
        ):
            summary = run_tsd(
                report_workbook=self.report_path,
                report_name="Uji",
                capture=options,
                save_manual=False,
                log=lambda _message: None,
            )
        self.assertEqual(summary["output"].name, "TSD_Uji_22222222.html")

    def test_explicit_out_file_wins(self) -> None:
        output = self.tmp / "custom" / "TSD.html"
        summary = run_tsd(
            report_workbook=self.report_path,
            out_file=output,
            report_name="Uji",
            report_id="66666666-6666-4666-8666-666666666666",
            save_manual=False,
            log=lambda _message: None,
        )
        self.assertEqual(summary["output"], output)


class ContextTests(TsdTestCase):
    def test_pages_are_sorted_and_mapped(self) -> None:
        context = self.context()
        pages = context["objects"]["pages"]
        self.assertEqual([page["title"] for page in pages], ["Overview", "Detail"])
        self.assertEqual(pages[0]["page_id"], "p1")
        self.assertFalse(pages[0]["is_hidden"])
        self.assertTrue(pages[1]["is_hidden"])

    def test_missing_is_hidden_column_stays_unknown(self) -> None:
        path = write_workbook(
            self.tmp / "pages_tanpa_hidden.xlsx",
            {
                "01_Pages": pd.DataFrame(
                    [{"page_order": 1, "page_name": "Overview", "page_id": "p1"}]
                )
            },
        )
        context = self.context(report_workbook=path, model_workbook=None)
        self.assertIsNone(context["objects"]["pages"][0]["is_hidden"])

    def test_visual_hidden_flags(self) -> None:
        visuals = self.context()["objects"]["pages"][0]["visuals"]
        self.assertTrue(visuals[0]["is_hidden"])
        self.assertFalse(visuals[1]["is_hidden"])

    def test_visual_without_is_hidden_column_stays_unknown(self) -> None:
        frame = report_sheets()["08_Visual_Summary"].drop(columns=["is_hidden"])
        visuals = _visuals(frame, None, None, None, "p1", {}, {})
        self.assertIsNone(visuals[0]["is_hidden"])

    def test_page_and_visual_filters(self) -> None:
        pages = self.context()["objects"]["pages"]
        overview = pages[0]
        self.assertEqual(len(overview["page_filters"]), 1)
        page_filter = overview["page_filters"][0]
        self.assertEqual(page_filter["field"], "Region")
        self.assertEqual(page_filter["filter_type"], "Categorical")
        self.assertEqual(page_filter["hidden"], "Yes")
        self.assertEqual(page_filter["locked"], "Yes")
        visual = overview["visuals"][0]
        self.assertEqual(len(visual["filters"]), 1)
        self.assertEqual(visual["filters"][0]["field"], "Month")
        self.assertEqual(visual["filters"][0]["hidden"], "No")
        self.assertEqual(visual["filters"][0]["locked"], "No")
        # Kartu filter tanpa definisi (tidak memfilter) tidak ditampilkan.
        self.assertEqual(overview["visuals"][1]["filters"], [])

    def test_decorative_visuals_are_filtered_by_default(self) -> None:
        default_visuals = self.context()["objects"]["pages"][0]["visuals"]
        self.assertEqual(
            [visual["visual_id"] for visual in default_visuals], ["v1", "v2"]
        )
        kept = self.context(include_decorative_visuals=True)["objects"]["pages"][0][
            "visuals"
        ]
        self.assertEqual(
            [visual["visual_id"] for visual in kept], ["v1", "v2", "v4", "v5"]
        )

    def test_visual_fields_and_interactions(self) -> None:
        pages = self.context()["objects"]["pages"]
        visuals = pages[0]["visuals"]
        self.assertEqual(visuals[0]["fields"], ["Branch[Region]", "Sales[Total]"])
        self.assertEqual(visuals[0]["interaction"], "Filter")
        self.assertEqual(visuals[1]["interaction"], "Highlight")
        self.assertEqual(visuals[0]["type"], "barChart")

    def test_visual_field_details_and_interaction_rows(self) -> None:
        visuals = self.context()["objects"]["pages"][0]["visuals"]
        details = visuals[0]["field_details"]
        self.assertEqual(
            [item["type"] for item in details],
            ["Column", "Measure", "Column", "Visual Calculation"],
        )
        self.assertEqual(details[1]["expression"], "SUM ( Sales[Amount] )")
        self.assertEqual(details[2]["aggregation"], "Sum")
        self.assertEqual(details[2]["query_ref"], "Sum(Sales.Amount)")
        self.assertEqual(details[3]["expression"], "[Total] / [Order Count]")
        self.assertEqual(details[3]["query_ref"], "Avg Order")
        self.assertEqual(
            visuals[0]["interactions"],
            [
                {
                    "source": "Sales by Region",
                    "target": "KPI",
                    "type": "DataFilter",
                },
                {
                    "source": "Sales by Region",
                    "target": "Table",
                    "type": "NoFilter",
                },
            ],
        )

    def test_report_filters_and_bookmarks(self) -> None:
        context = self.context()
        self.assertEqual(len(context["report"]["filters"]), 1)
        self.assertEqual(context["report"]["filters"][0]["field"], "Year")
        bookmarks = context["objects"]["bookmarks"]
        self.assertEqual(len(bookmarks), 1)
        self.assertEqual(bookmarks[0]["name"], "Reset Filters")
        self.assertIn("Page: Overview", bookmarks[0]["configuration"])
        self.assertIn("Target visuals: v1, v2", bookmarks[0]["configuration"])

    def test_sync_slicers_are_grouped(self) -> None:
        groups = self.context()["objects"]["sync_slicers"]
        self.assertEqual([group["label"] for group in groups], ["1. Overview", "2. Detail"])
        self.assertEqual(groups[0]["items"][0]["slicer"], "Date[Year]")
        self.assertEqual(groups[0]["items"][0]["pages"], "Overview, Detail")

    def test_model_sections(self) -> None:
        context = self.context()
        relationship = context["relationships"][0]
        self.assertEqual(
            relationship["relationship"], "Sales[DateKey] → Date[DateKey]"
        )
        self.assertEqual(relationship["type"], "many-to-one")
        self.assertEqual(relationship["active"], "Active")
        self.assertEqual(context["relationships"][1]["active"], "Inactive")

        measures = context["objects"]["measures"]
        self.assertEqual(measures[0]["name"], "Total Amount")
        self.assertEqual(measures[0]["formula"], "SUM ( Sales[Amount] )")

        calculated = context["objects"]["calculated_columns"]
        self.assertEqual(len(calculated), 1)
        self.assertEqual(calculated[0]["column"], "Amount Label")

        tables = context["objects"]["calculated_tables"]
        self.assertEqual([table["table_name"] for table in tables], ["Date"])
        self.assertIn("CALENDAR", tables[0]["dax"])

        queries = {query["name"]: query for query in context["objects"]["m_queries"]}
        # 2.2.1.4 hanya query yang dibuat di Power BI, bukan tabel bersumber
        # eksternal seperti Sales (SQL Server).
        self.assertNotIn("Sales", queries)
        self.assertIn("Inline", queries)
        self.assertIn("#table", queries["Inline"]["expression"])
        self.assertEqual(queries["Inline"]["output"], "Table")
        self.assertIn("NotParameter", queries)

        self.assertEqual(context["objects"]["parameters"][0]["name"], "RangeStart")
        hierarchies = context["objects"]["hierarchies"]
        self.assertEqual(hierarchies[0]["levels"], ["RegionName", "AreaName"])

        rls = {role["role"]: role for role in context["objects"]["rls"]}
        self.assertEqual(rls["Branch Manager"]["tables"], ["Branch"])
        self.assertNotIn("TRUE()", rls["Branch Manager"]["expression"])
        self.assertIn("Reader", rls)

    def test_table_classification(self) -> None:
        buckets = self.context()["objects"]["tables"]
        self.assertEqual(
            [table["table_name"] for table in buckets["database"]], ["Sales"]
        )
        self.assertEqual([table["table_name"] for table in buckets["live"]], ["Target"])
        self.assertEqual(
            [table["table_name"] for table in buckets["file"]], ["ExchangeRate"]
        )
        self.assertEqual(
            [table["table_name"] for table in buckets["mquery"]], ["Inline"]
        )
        sales = buckets["database"][0]
        self.assertEqual(sales["source_application"], "Sql.Database")
        self.assertEqual(sales["source_host"], "sql-host")
        self.assertEqual(sales["incremental"], "Yes — 30 day")
        self.assertEqual(buckets["live"][0]["kind"], "Dataflow")
        self.assertEqual(buckets["mquery"][0]["source_type"], "M / Inline")

    def test_inline_and_unknown_sources_go_to_mquery(self) -> None:
        self.assertEqual(_connector_kind("(inline table)")[0], "mquery")
        self.assertEqual(_connector_kind("(inline)")[0], "mquery")
        self.assertEqual(_connector_kind("")[0], "mquery")
        self.assertEqual(_connector_kind("Sql.Database")[0], "database")
        self.assertEqual(_connector_kind("PowerPlatform.Dataflows")[0], "live")
        self.assertEqual(_connector_kind("Csv.Document")[0], "file")
        # Enter Data membungkus tabel dengan Json.Document; tetap inline.
        enter_data = (
            'let Source = Table.FromRows(Json.Document(Binary.Decompress('
            'Binary.FromText("i44FAA==", BinaryEncoding.Base64), '
            "Compression.Deflate)), let _t = 1 in _t) in Source"
        )
        self.assertEqual(_infer_connector(enter_data), "Inline")
        self.assertEqual(_infer_connector("#table({\"A\"}, {{\"x\"}})"), "Inline")
        # Query database yang berakhir dengan Table.FromValue tetap database.
        self.assertEqual(
            _infer_connector(
                'let Source = Sql.Database("h", "db"), '
                "T = Table.FromValue(Source) in T"
            ),
            "SQL Server",
        )
        self.assertEqual(
            _infer_connector('let Source = File.Contents("data.txt") in Source'),
            "File",
        )
        self.assertEqual(_infer_connector(""), "")

    def test_file_connectors_cover_csv_excel_json(self) -> None:
        for connector, bucket in (
            ("Csv.Document", "file"),
            ("Excel.Workbook", "file"),
            ("Json.Document", "file"),
            ("Xml.Tables", "file"),
            ("File.Contents", "file"),
        ):
            self.assertEqual(_connector_kind(connector)[0], bucket, connector)
        self.assertEqual(
            _infer_connector('let S = Csv.Document(Web.Contents("a.csv")) in S'),
            "CSV",
        )

    def test_infer_connector_for_database_families(self) -> None:
        for expression, label in (
            ("let S = GoogleBigQuery.Database(null) in S", "Google BigQuery"),
            ('let S = Snowflake.Databases("a", "w") in S', "Snowflake"),
            ('let S = Teradata.Database("h") in S', "Teradata"),
            ('let S = AzureSql.Database("h", "d") in S', "Azure SQL"),
            ("let S = Odbc.Query(\"dsn=X\", \"select 1\") in S", "ODBC"),
            ('let S = SapBusinessWarehouse.Cubes("h") in S', "SAP BW"),
            ('let S = GoogleSheets.Contents("https://x") in S', "Google Sheets"),
            ("let S = Parquet.Document(File.Contents(\"a.parquet\")) in S", "Parquet"),
            ("let S = PowerBI.Dataflows(null) in S", "Power BI Dataflows"),
            (
                "let S = UsageMetricsDataConnector.GetMetricsData(null) in S",
                "Usage Metrics",
            ),
        ):
            self.assertEqual(_infer_connector(expression), label, expression)

    def test_infer_connector_buckets(self) -> None:
        for expression, bucket in (
            ("let S = Odbc.Query(\"dsn=X\", \"select 1\") in S", "database"),
            ('let S = SapBusinessWarehouse.Cubes("h") in S', "database"),
            ('let S = GoogleSheets.Contents("https://x") in S', "file"),
            ("let S = Parquet.Document(File.Contents(\"a.parquet\")) in S", "file"),
            ("let S = PowerBI.Dataflows(null) in S", "live"),
            (
                "let S = UsageMetricsDataConnector.GetMetricsData(null) in S",
                "live",
            ),
        ):
            label = _infer_connector(expression)
            self.assertEqual(_connector_kind(label)[0], bucket, expression)

    def test_calculated_and_calculation_group_tables_are_skipped(self) -> None:
        frames = {
            "02_Tables": pd.DataFrame(
                [
                    {"table": "Calc", "storage_mode": "Import"},
                    {"table": "CalcGroup", "storage_mode": "Import"},
                    {"table": "Plain", "storage_mode": "Import"},
                ]
            ),
            "05_Partitions": pd.DataFrame(
                [
                    {
                        "table": "Calc",
                        "partition": "Calc",
                        "source_type": "calculated",
                        "source": "CALENDAR(...)",
                    },
                    {
                        "table": "CalcGroup",
                        "partition": "CalcGroup",
                        "source_type": "calculationGroup",
                        "source": None,
                    },
                    {
                        "table": "Plain",
                        "partition": "Plain",
                        "source_type": "m",
                        "source": 'let Source = Csv.Document(File.Contents("a.csv")) in Source',
                    },
                ]
            ),
        }
        buckets = _tables(frames)
        self.assertEqual(
            [table["table_name"] for table in buckets["file"]], ["Plain"]
        )
        self.assertEqual(buckets["database"], [])
        self.assertEqual(buckets["mquery"], [])

    def test_m_query_output_guessing(self) -> None:
        self.assertEqual(_m_output("(x as text) => x"), "Function")
        self.assertEqual(_m_output('{"a", "b"}'), "List")
        self.assertEqual(_m_output('[a = 1]'), "Record")
        self.assertEqual(_m_output("#table({\"A\"})"), "Table")
        self.assertEqual(_m_output("DateTime.LocalNow()"), "")

    def test_custom_column_logic_only_for_created_columns(self) -> None:
        sales = self.context()["objects"]["tables"]["database"][0]
        logic = {
            detail["column_name"]: detail["custom_logic"]
            for detail in sales["column_details"]
        }
        self.assertEqual(logic["Amount"], "")  # hanya rename, bukan kolom baru
        self.assertEqual(logic["Amount Label"], '[Amount] & ""')  # calculated DAX
        self.assertEqual(
            logic["Amount Group"],
            'each if [Amount] > 0 then "positive" else "other"',
        )

    def test_table_parameters_are_filled_for_every_bucket(self) -> None:
        buckets = self.context()["objects"]["tables"]
        database = {table["table_name"]: table for table in buckets["database"]}
        self.assertEqual(
            [item["name"] for item in database["Sales"]["parameters"]],
            ["RangeStart"],
        )
        self.assertEqual(
            [item["name"] for item in buckets["file"][0]["parameters"]],
            ["SourceFile"],
        )
        self.assertIn("parameters", buckets["live"][0])

    def test_missing_model_keeps_empty_state(self) -> None:
        context = self.context(model_workbook=None)
        self.assertEqual(context["relationships"], [])
        self.assertEqual(context["objects"]["measures"], [])
        self.assertEqual(
            context["objects"]["tables"],
            {"database": [], "live": [], "file": [], "mquery": []},
        )
        self.assertEqual(len(context["objects"]["pages"]), 2)

    def test_meta_defaults(self) -> None:
        context = self.context()
        self.assertEqual(context["meta"]["generated_at"], "13 November 2026")
        self.assertTrue(context["meta"]["draft"])
        self.assertFalse(context["meta"]["expand_all"])


class ManualMergeTests(TsdTestCase):
    def test_page_overrides_by_id(self) -> None:
        manual = {
            "report": {"overview": "Ringkasan report."},
            "objects": {
                "pages": {
                    "p1": {
                        "is_hidden": False,
                        "screenshot": "assets/overview.png",
                        "visuals": {"v1": {"tooltip": "Tooltip page", "screenshot": "v1.png"}},
                    }
                }
            },
        }
        context = self.context(manual=manual)
        page = context["objects"]["pages"][0]
        self.assertFalse(page["is_hidden"])
        self.assertEqual(page["screenshot"], "assets/overview.png")
        self.assertEqual(page["visuals"][0]["tooltip"], "Tooltip page")
        self.assertEqual(page["visuals"][0]["name"], "Sales by Region")
        self.assertEqual(context["report"]["overview"], "Ringkasan report.")

    def test_unknown_ids_are_reported_not_fatal(self) -> None:
        messages: list[str] = []
        manual = {
            "objects": {
                "pages": {
                    "tidak-ada": {"screenshot": "x.png"},
                    "juga-tidak-ada": {"screenshot": "y.png"},
                }
            }
        }
        context = self.context(manual=manual, log=messages.append)
        self.assertEqual(len(context["objects"]["pages"]), 2)
        warnings = [message for message in messages if "override halaman" in message]
        self.assertEqual(len(warnings), 1)
        self.assertIn("2 override halaman", warnings[0])
        self.assertIn("tidak cocok dengan workbook", warnings[0])

    def test_nested_document_merge_keeps_other_fields(self) -> None:
        manual = {"document": {"author": {"name": "Budi"}}}
        context = self.context(manual=manual)
        self.assertEqual(context["document"]["author"]["name"], "Budi")
        self.assertEqual(
            context["document"]["title"],
            "Technical Specification Design Business Intelligence",
        )

    def test_explicit_options_win_over_manual_meta(self) -> None:
        manual = {"meta": {"draft": True, "expand_all": True}}
        context = self.context(manual=manual, draft=False, expand_all=False)
        self.assertFalse(context["meta"]["draft"])
        self.assertFalse(context["meta"]["expand_all"])

    def test_manual_tables_replace_bucket(self) -> None:
        manual = {"objects": {"tables": {"file": [{"table_name": "Manual", "columns": []}]}}}
        context = self.context(manual=manual)
        self.assertEqual(
            [table["table_name"] for table in context["objects"]["tables"]["file"]],
            ["Manual"],
        )
        self.assertTrue(context["objects"]["tables"]["database"])


class RenderTests(TsdTestCase):
    def test_render_contains_required_sections(self) -> None:
        html = render_tsd(self.context())
        for anchor in ("doc-version", "toc", "overview", "solution-design", "web-layout", "serving"):
            self.assertIn(f'id="{anchor}"', html)
        self.assertNotIn("{%", html)
        self.assertIn("Sales by Region", html)
        self.assertIn("Click here to expand parameter list", html)
        self.assertIn("RangeStart", html)

    def test_render_field_and_interaction_tables(self) -> None:
        html = render_tsd(self.context(draft=False))
        for header in (
            "<th>Table</th>",
            "<th>Field</th>",
            "<th>Type</th>",
            "<th>Display Name</th>",
            "<th>Expression</th>",
            "<th>Aggregation</th>",
            "<th>Query Ref</th>",
        ):
            self.assertIn(header, html)
        self.assertIn("<th>Source</th>", html)
        self.assertIn("<th>Target</th>", html)
        self.assertIn("Visual Calculation", html)
        self.assertIn(">Sum<", html)
        self.assertIn(">NoFilter<", html)
        self.assertIn("[Total] / [Order Count]", html)
        self.assertIn("Click here to expand field list", html)

    def test_filter_tables_only_show_active_filters(self) -> None:
        html = render_tsd(self.context(draft=False))
        for header in (
            "<th>Column / Measure Name</th>",
            "<th>Table Name</th>",
            "<th>Type</th>",
            "<th>Values</th>",
            "<th>is hidden</th>",
            "<th>is locked</th>",
        ):
            self.assertIn(header, html)
        self.assertNotIn("<th>Defined</th>", html)
        self.assertNotIn("<th>Purpose</th>", html)
        self.assertNotIn('class="filter-note"', html)
        self.assertIn("is Jan", html)
        self.assertNotIn("<td>Quarter</td>", html)
        self.assertIn("<td>Advanced</td>", html)
        self.assertIn("<td>—</td>", html)

    def test_filters_without_definition_column_are_kept(self) -> None:
        frame = report_sheets()["07_Filters"].drop(
            columns=["has_filter_definition"]
        )
        rows = _filters(frame, "Visual", visual_id="v2")
        self.assertEqual([row["field"] for row in rows], ["Quarter"])

    def test_page_hidden_flag_is_rendered(self) -> None:
        html = render_tsd(self.context(draft=False))
        first = html.split('id="page-1"', 1)[1].split('id="page-2"', 1)[0]
        second = html.split('id="page-2"', 1)[1]
        self.assertIn("<td>FALSE</td>", first)
        self.assertIn("<td>TRUE</td>", second)

    def test_visual_hidden_column_is_rendered(self) -> None:
        html = render_tsd(self.context(draft=False))
        self.assertIn("<strong>Is hidden</strong>", html)
        first = html.split('id="page-1"', 1)[1].split('id="page-2"', 1)[0]
        self.assertIn("<td>TRUE</td>", first)
        self.assertIn("<td>FALSE</td>", first)

    def test_draft_and_final_modes(self) -> None:
        draft = render_tsd(self.context(draft=True))
        final = render_tsd(self.context(draft=False))
        self.assertIn('class="todo"', draft)
        self.assertNotIn('class="instruction"', draft)
        self.assertNotIn("**", draft)
        self.assertNotIn('class="todo"', final)
        self.assertNotIn('class="instruction"', final)
        self.assertNotIn("**", final)

    def test_expand_panels_closed_by_default(self) -> None:
        closed = render_tsd(self.context(expand_all=False))
        opened = render_tsd(self.context(expand_all=True))
        self.assertNotIn('<details class="expand" open', closed)
        self.assertIn('<details class="expand" open', opened)

    def test_values_are_escaped(self) -> None:
        manual = {"report": {"overview": "<script>alert(1)</script>"}}
        html = render_tsd(self.context(manual=manual))
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_code_blocks_keep_newlines(self) -> None:
        manual = {
            "objects": {
                "m_queries": [
                    {
                        "name": "Q",
                        "purpose": "",
                        "output": "Table",
                        "expression": "let\n    x = 1\nin\n    x",
                    }
                ]
            }
        }
        html = render_tsd(self.context(manual=manual))
        plain = re.sub(r"<[^>]+>", "", html)
        self.assertIn('class="code-text"', html)
        self.assertIn("let", plain)
        self.assertIn("in", plain)
        self.assertIn("x = 1", plain)

    def test_empty_pages_render_empty_state(self) -> None:
        manual = {"objects": {"pages": []}}
        html = render_tsd(self.context(manual=manual))
        self.assertIn("No pages available", html)

    def test_missing_template_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            render_tsd(self.context(), template_path=self.tmp / "tidak-ada.html")


class RunTsdTests(TsdTestCase):
    def test_writes_html_and_manual(self) -> None:
        output = self.tmp / "out" / "TSD_Uji.html"
        summary = run_tsd(
            report_workbook=self.report_path,
            model_workbook=self.model_path,
            out_file=output,
            report_name="Uji",
            log=lambda _message: None,
        )
        self.assertTrue(output.exists())
        self.assertTrue(output.with_suffix(".json").exists())
        self.assertEqual(summary["pages"], 2)
        self.assertEqual(summary["visuals"], 3)
        self.assertIn(b"\r\n", output.read_bytes())
        manual = output.with_suffix(".json").read_text(encoding="utf-8")
        self.assertIn('"pages"', manual)
        self.assertIn('"p1"', manual)

    def test_manual_edits_survive_regeneration(self) -> None:
        output = self.tmp / "out" / "TSD_Uji.html"
        run_tsd(
            report_workbook=self.report_path,
            out_file=output,
            report_name="Uji",
            log=lambda _message: None,
        )
        manual_path = output.with_suffix(".json")
        data = manual_path.read_text(encoding="utf-8")
        manual_path.write_text(
            data.replace('"overview": ""', '"overview": "Catatan manual tetap."'),
            encoding="utf-8",
        )
        run_tsd(
            report_workbook=self.report_path,
            out_file=output,
            report_name="Uji",
            log=lambda _message: None,
        )
        self.assertIn("Catatan manual tetap.", output.read_text(encoding="utf-8"))
        self.assertIn("Catatan manual tetap.", manual_path.read_text(encoding="utf-8"))

    def test_missing_report_workbook_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            run_tsd(
                report_workbook=self.tmp / "tidak-ada.xlsx",
                out_file=self.tmp / "out" / "TSD.html",
                log=lambda _message: None,
            )
        self.assertIn("tidak ditemukan", str(ctx.exception))

    def test_manual_skeleton_has_page_and_visual_ids(self) -> None:
        skeleton = manual_skeleton(self.context())
        self.assertIn("p1", skeleton["objects"]["pages"])
        self.assertIn("v1", skeleton["objects"]["pages"]["p1"]["visuals"])


class ScreenshotContextTests(TsdTestCase):
    """Screenshot Power BI Service menempel ke page/visual lewat ID."""

    def screenshot_set(self) -> ScreenshotSet:
        root = self.tmp / "shots"
        (root / "pages").mkdir(parents=True)
        (root / "visuals" / "01_Overview").mkdir(parents=True)
        (root / "mobile").mkdir(parents=True)
        page = root / "pages" / "01_Overview.png"
        page.write_bytes(b"\x89PNG\r\n\x1a\npage")
        visual = root / "visuals" / "01_Overview" / "KPI.png"
        visual.write_bytes(b"\x89PNG\r\n\x1a\nvisual")
        mobile = root / "mobile" / "01_Overview.png"
        mobile.write_bytes(b"\x89PNG\r\n\x1a\nmobile")
        return ScreenshotSet(
            root=root,
            pages={"p1": page},
            visuals={("p1", "v2"): visual},
            mobile={"p1": mobile},
            page_titles={"p1": "Overview"},
            visual_titles={("p1", "v2"): "KPI"},
            captured_at="2026-11-14T00:00:00+00:00",
            workspace_id="w",
            report_id="r",
            scope="both",
            mobile_enabled=True,
        )

    def test_screenshot_fills_page_and_visual(self) -> None:
        context = self.context(screenshots=self.screenshot_set())
        pages = context["objects"]["pages"]
        self.assertTrue(pages[0]["screenshot"].startswith("data:image/png;base64,"))
        self.assertTrue(
            pages[0]["visuals"][1]["screenshot"].startswith("data:image/png;base64,")
        )
        self.assertEqual(pages[0]["visuals"][0]["screenshot"], "")
        self.assertEqual(pages[1]["screenshot"], "")
        stats = context["meta"]["screenshot_stats"]
        self.assertEqual(
            (
                stats["pages"],
                stats["visuals"],
                stats["missing_pages"],
                stats["missing_visuals"],
            ),
            (1, 1, 1, 2),
        )

    def test_mobile_screenshot_fills_2_2_7_2(self) -> None:
        context = self.context(screenshots=self.screenshot_set())
        shots = context["objects"]["mobile"]["screenshots"]
        self.assertEqual(len(shots), 1)
        self.assertEqual(shots[0]["caption"], "01. Overview")
        self.assertTrue(shots[0]["src"].startswith("data:image/png;base64,"))
        self.assertEqual(context["meta"]["screenshot_stats"]["mobile"], 1)
        html = render_tsd(context)
        self.assertIn('class="screenshot-mobile"', html)

    def test_no_mobile_layout_sets_note(self) -> None:
        shots = self.screenshot_set()
        shots.mobile = {}
        context = self.context(screenshots=shots)
        self.assertIn("belum memiliki mobile layout", context["objects"]["mobile"]["note"])
        self.assertEqual(context["objects"]["mobile"]["screenshots"], [])
        html = render_tsd(context)
        self.assertIn("belum memiliki mobile layout", html)

    def test_include_decorative_visuals_keeps_them(self) -> None:
        output = self.tmp / "out" / "TSD_Uji.html"
        options = CaptureOptions(
            workspace_id="11111111-1111-4111-8111-111111111111",
            report_id="22222222-2222-4222-8222-222222222222",
        )
        with patch(
            "core.pbi_capture.runner.load_or_capture",
            return_value=self.screenshot_set(),
        ) as loader:
            summary = run_tsd(
                report_workbook=self.report_path,
                out_file=output,
                report_name="Uji",
                capture=options,
                include_decorative_visuals=True,
                save_manual=False,
                log=lambda _message: None,
            )
        passed = loader.call_args[0][0]
        self.assertNotIn("shape", passed.exclude_visual_types)
        self.assertEqual(passed.hints_workbook, self.report_path)
        self.assertEqual(summary["visuals"], 5)

    def test_sidecar_override_wins_over_screenshot(self) -> None:
        manual = {
            "objects": {
                "pages": {
                    "p1": {
                        "screenshot": "manual.png",
                        "visuals": {"v2": {"screenshot": "manual-visual.png"}},
                    }
                },
                "mobile": {
                    "screenshots": [
                        {"src": "manual-mobile.png", "caption": "Mobile"}
                    ]
                },
            }
        }
        html = render_tsd(
            self.context(manual=manual, screenshots=self.screenshot_set())
        )
        self.assertIn('src="manual.png"', html)
        self.assertIn('src="manual-visual.png"', html)
        self.assertIn('src="manual-mobile.png"', html)
        self.assertNotIn("data:image/png;base64,", html)

    def test_viewport_follows_largest_page(self) -> None:
        path = write_workbook(
            self.tmp / "pages.xlsx",
            {
                "01_Pages": pd.DataFrame(
                    [
                        {"page_order": 1, "page_name": "A", "page_id": "a", "width": 1280, "height": 720},
                        {"page_order": 2, "page_name": "B", "page_id": "b", "width": 1600, "height": 900},
                    ]
                )
            },
        )
        self.assertEqual(_report_page_size(path), (1600, 900))
        self.assertEqual(_report_page_size(self.tmp / "tidak-ada.xlsx"), (0, 0))

    def test_blank_sidecar_screenshot_keeps_capture(self) -> None:
        manual = {
            "objects": {
                "pages": {
                    "p1": {
                        "is_hidden": None,
                        "screenshot": "",
                        "visuals": {"v2": {"tooltip": "", "screenshot": ""}},
                    }
                }
            }
        }
        context = self.context(manual=manual, screenshots=self.screenshot_set())
        page = context["objects"]["pages"][0]
        self.assertFalse(page["is_hidden"])
        self.assertTrue(page["screenshot"].startswith("data:image/png;base64,"))
        self.assertTrue(
            page["visuals"][1]["screenshot"].startswith("data:image/png;base64,")
        )
        self.assertEqual(page["visuals"][1]["tooltip"], "")

    def test_run_tsd_uses_capture_options(self) -> None:
        output = self.tmp / "out" / "TSD_Uji.html"
        options = CaptureOptions(
            workspace_id="11111111-1111-4111-8111-111111111111",
            report_id="22222222-2222-4222-8222-222222222222",
        )
        with patch(
            "core.pbi_capture.runner.load_or_capture",
            return_value=self.screenshot_set(),
        ) as loader:
            summary = run_tsd(
                report_workbook=self.report_path,
                out_file=output,
                report_name="Uji",
                capture=options,
                save_manual=False,
                log=lambda _message: None,
            )
        self.assertTrue(loader.called)
        passed = loader.call_args[0][0]
        self.assertEqual(
            Path(passed.output_root),
            output.parent / SCREENSHOT_ASSET_DIR / "Uji_22222222",
        )
        self.assertIn("shape", passed.exclude_visual_types)
        self.assertIn("image", passed.exclude_visual_types)
        self.assertEqual(summary["screenshot_pages"], 1)
        self.assertEqual(summary["screenshot_visuals"], 1)
        self.assertEqual(summary["screenshot_missing"], 3)
        html = output.read_text(encoding="utf-8")
        self.assertIn("data:image/png;base64,", html)
        self.assertIn('loading="lazy"', html)


class ConnectorRegistryTests(unittest.TestCase):
    """Tiga daftar konektor (lineage, model, TSD) tidak boleh melenceng."""

    def test_lineage_and_model_connector_lists_match(self) -> None:
        specs = {name.casefold() for name in CONNECTOR_SPECS}
        model = {name.casefold() for name in CONNECTORS}

        self.assertEqual(sorted(model - specs), [])
        self.assertEqual(sorted(specs - model), [])

    def test_tsd_patterns_cover_all_lineage_connectors(self) -> None:
        patterns = [name.casefold() for name, _label in CONNECTOR_PATTERNS]
        missing = sorted(
            name
            for name in CONNECTOR_SPECS
            if not any(pattern in name.casefold() for pattern in patterns)
        )

        self.assertEqual(missing, [])


class MColumnLogicTests(unittest.TestCase):
    """Logika kolom dari parser M untuk kolom Custom Column Logic."""

    def columns(self, text: str) -> dict:
        return build_lineage(text).columns

    def test_add_column_keeps_expression(self) -> None:
        columns = self.columns(
            "let\n"
            '    Source = #table({"A"}, {{1}}),\n'
            '    Added = Table.AddColumn(Source, "B", each [A] * 2)\n'
            "in\n"
            "    Added"
        )
        self.assertEqual(columns["B"].logic, "each [A] * 2")
        self.assertEqual(columns["A"].logic, "")

    def test_duplicate_column_reports_source(self) -> None:
        columns = self.columns(
            "let\n"
            '    Source = #table({"A"}, {{1}}),\n'
            '    Duplicated = Table.DuplicateColumn(Source, "A", "A Copy")\n'
            "in\n"
            "    Duplicated"
        )
        self.assertEqual(columns["A Copy"].logic, "Duplicate of [A]")

    def test_combine_columns_keeps_combiner(self) -> None:
        columns = self.columns(
            "let\n"
            '    Source = #table({"A", "B"}, {{1, "x"}}),\n'
            '    Combined = Table.CombineColumns(Source, {"A", "B"}, '
            'Combiner.CombineTextByDelimiter(" - "), "Merged")\n'
            "in\n"
            "    Combined"
        )
        self.assertEqual(
            columns["Merged"].logic, 'Combiner.CombineTextByDelimiter(" - ")'
        )

    def test_group_aggregation_keeps_expression(self) -> None:
        columns = self.columns(
            "let\n"
            '    Source = #table({"A", "B"}, {{1, 2}}),\n'
            '    Grouped = Table.Group(Source, {"A"}, '
            '{{"Total", each List.Sum([B]), type number}})\n'
            "in\n"
            "    Grouped"
        )
        self.assertEqual(columns["Total"].logic, "each List.Sum([B])")


class TemplateCopyTests(unittest.TestCase):
    def test_template_is_available(self) -> None:
        self.assertTrue(TEMPLATE_PATH.exists(), "salin template dari repo template-tsd")
        text = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertIn("Technical Specification Design", text)
        self.assertIn('<details class="expand', text)
