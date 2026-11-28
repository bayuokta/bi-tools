"""Uji ekspor lineage/dependensi analisa ke CSV/JSON."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.analysis_export import (
    dependency_rows,
    object_details_payload,
    output_stem,
    safe_name,
    write_dependencies_csv,
    write_lineage_files,
    write_lineage_image,
    write_object_json,
    write_uses_xlsx,
)


def analysis_fixture() -> SimpleNamespace:
    column = SimpleNamespace(column="Amount", table="Sales")
    column_item = SimpleNamespace(
        column=column,
        status="Used",
        model_refs=[
            SimpleNamespace(
                kind="measure",
                object="'KPI'[Total]",
                detail="measure 'KPI'[Total]",
                blocking=False,
            )
        ],
        report_records=[
            {
                "usage_kind": "field",
                "visual_title": "Tabel",
                "visual_type": "tableEx",
                "detail": "Values",
                "report_name": "Report Uji",
                "page_name": "Halaman 1",
                "is_hidden": False,
            },
            {
                "usage_kind": "filter-page",
                "visual_title": "",
                "visual_type": "",
                "detail": "Categorical",
                "report_name": "Report Uji",
                "page_name": "Halaman 1",
                "is_hidden": True,
            },
        ],
    )
    measure = SimpleNamespace(measure="Total", table="KPI")
    measure_item = SimpleNamespace(
        measure=measure,
        status="Used",
        model_refs=[],
        report_records=[],
    )
    function_item = SimpleNamespace(
        function=SimpleNamespace(
            name="PercentageGrowth",
            function_id=56708,
            expression="(x) => x",
            description="",
            lineage_tag="",
            is_hidden=False,
        ),
        status="Used",
        reason="",
        model_refs=[
            SimpleNamespace(
                kind="measure",
                object="'KPI'[Total]",
                detail="measure 'KPI'[Total]",
                blocking=False,
            )
        ],
        report_records=[],
    )
    hierarchy_item = SimpleNamespace(
        hierarchy={
            "table": "Sales",
            "hierarchy": "Date",
            "levels": "Year > Month",
            "level_count": 2,
            "is_hidden": False,
            "display_folder": "",
            "description": "",
            "lineage_tag": "",
        },
        status="Used",
        reason="",
        report_records=[
            {
                "usage_kind": "field",
                "visual_title": "Tabel",
                "visual_type": "tableEx",
                "detail": "Rows",
                "report_name": "Report Uji",
                "page_name": "Halaman 1",
                "is_hidden": False,
            }
        ],
    )
    hierarchy_item.table = "Sales"
    hierarchy_item.name = "Date"
    return SimpleNamespace(
        columns=[column_item],
        measures=[measure_item],
        functions=[function_item],
        hierarchies=[hierarchy_item],
        dataset_name="Model Uji",
        stats=SimpleNamespace(tables=[]),
        reports=[],
    )


class ExportNameTests(unittest.TestCase):
    def test_safe_name(self) -> None:
        self.assertEqual(safe_name('Sales/2026: "A"'), "Sales_2026_ _A_")
        self.assertEqual(safe_name(""), "Analisa")
        self.assertEqual(output_stem("Sales", "Amount"), "Sales_Amount")
        self.assertEqual(output_stem("Sales", "Sales"), "Sales")


class LineageExportTests(unittest.TestCase):
    def test_writes_nodes_edges_and_json(self) -> None:
        payload = {
            "nodes": [
                {
                    "id": "col:Sales:Amount",
                    "kind": "column",
                    "label": "Amount",
                    "context": "Sales",
                    "status": "Used",
                    "side": "root",
                    "column": 0,
                    "x": 10,
                    "y": 20,
                    "count": 2,
                    "hidden": False,
                }
            ],
            "edges": [
                {"from": "col:Sales:Amount", "to": "col:Sales:Total", "kind": "depend"}
            ],
            "outline": {"upstream": [], "downstream": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            result = write_lineage_files(
                payload, tmp, table="Sales", name="Amount"
            )
            paths = [Path(path) for path in result["paths"]]
            self.assertEqual(result["nodes"], 1)
            self.assertEqual(result["edges"], 1)
            self.assertTrue(all(path.exists() for path in paths))

            nodes_text = paths[0].read_text(encoding="utf-8-sig")
            self.assertTrue(nodes_text.startswith("node_id,kind,label"))
            self.assertIn("col:Sales:Amount", nodes_text)

            edges_text = paths[1].read_text(encoding="utf-8-sig")
            self.assertTrue(edges_text.startswith("from,to,kind"))
            self.assertIn("depend", edges_text)

            data = json.loads(paths[2].read_text(encoding="utf-8"))
            self.assertEqual(data["nodes"][0]["id"], "col:Sales:Amount")

            raw = paths[0].read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertIn(b"\r\n", raw)

    def test_writes_only_requested_format(self) -> None:
        payload = {"nodes": [], "edges": []}
        with tempfile.TemporaryDirectory() as tmp:
            result = write_lineage_files(
                payload, tmp, table="Sales", name="Amount", formats=("json",)
            )
            self.assertEqual(len(result["paths"]), 1)
            self.assertTrue(result["paths"][0].endswith(".json"))
            result = write_lineage_files(
                payload, tmp, table="Sales", name="Amount", formats=("csv",)
            )
            self.assertEqual(len(result["paths"]), 2)
            self.assertTrue(all(path.endswith(".csv") for path in result["paths"]))


class ImageExportTests(unittest.TestCase):
    PNG_1X1 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        "z8BQDwAFgwJ/lK3Z9wAAAABJRU5ErkJggg=="
    )

    def test_writes_svg_and_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svg = write_lineage_image(
                '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                tmp,
                table="Sales",
                name="Amount",
                image_format="svg",
            )
            self.assertTrue(svg["path"].endswith("Lineage_Sales_Amount_lineage.svg"))
            self.assertTrue(Path(svg["path"]).exists())
            png = write_lineage_image(
                "data:image/png;base64," + self.PNG_1X1,
                tmp,
                table="Sales",
                name="Sales",
                image_format="png",
            )
            self.assertTrue(png["path"].endswith("Lineage_Sales_lineage.png"))
            self.assertTrue(
                Path(png["path"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            )

    def test_custom_file_stem_for_lineage_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            svg = write_lineage_image(
                '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                tmp,
                table="",
                name="",
                image_format="svg",
                file_stem="Lineage_Report Uji",
            )
            self.assertEqual(Path(svg["path"]).name, "Lineage_Report Uji.svg")

    def test_rejects_invalid_image_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for content, fmt in (
                ("<div></div>", "svg"),
                ("<svg><script>alert(1)</script></svg>", "svg"),
                ("not-a-png", "png"),
                ("", "svg"),
            ):
                with self.assertRaises(ValueError):
                    write_lineage_image(
                        content,
                        tmp,
                        table="Sales",
                        name="Amount",
                        image_format=fmt,
                    )
            with self.assertRaises(ValueError):
                write_lineage_image(
                    "<svg></svg>",
                    tmp,
                    table="Sales",
                    name="Amount",
                    image_format="gif",
                )


class DependencyExportTests(unittest.TestCase):
    def test_rows_for_column(self) -> None:
        rows = dependency_rows(
            analysis_fixture(), kind="column", table="Sales", name="Amount"
        )
        self.assertEqual([row["type"] for row in rows], ["model", "report", "report"])
        self.assertEqual(rows[0]["kind"], "measure")
        self.assertEqual(rows[1]["report"], "Report Uji")
        self.assertEqual(rows[2]["hidden"], "TRUE")

    def test_rows_for_table_includes_columns_and_measures(self) -> None:
        rows = dependency_rows(
            analysis_fixture(), kind="table", table="Sales", name="Sales"
        )
        self.assertEqual([row["type"] for row in rows], ["model", "report", "report"])
        self.assertTrue(all(row["source"] == "'Sales'[Amount]" for row in rows))
        rows = dependency_rows(
            analysis_fixture(), kind="table", table="KPI", name="KPI"
        )
        self.assertEqual(rows, [])

    def test_rows_for_missing_item(self) -> None:
        self.assertEqual(
            dependency_rows(
                analysis_fixture(), kind="column", table="Sales", name="Nope"
            ),
            [],
        )

    def test_writes_csv(self) -> None:
        rows = dependency_rows(
            analysis_fixture(), kind="measure", table="KPI", name="Total"
        )
        self.assertEqual(rows, [])
        rows = dependency_rows(
            analysis_fixture(), kind="column", table="Sales", name="Amount"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = write_dependencies_csv(
                rows, tmp, table="Sales", name="Amount"
            )
            text = path.read_text(encoding="utf-8-sig")
            self.assertTrue(text.startswith("source,type,kind"))
            self.assertIn("'Sales'[Amount]", text)


class ObjectExportTests(unittest.TestCase):
    def test_function_uses_and_json_modes(self) -> None:
        result = analysis_fixture()
        rows = dependency_rows(
            result,
            kind="function",
            table="",
            name="PercentageGrowth",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "function 'PercentageGrowth'")

        full = object_details_payload(
            result, kind="function", table="", name="PercentageGrowth", mode="full"
        )
        self.assertEqual(full["details"]["kind"], "function")
        self.assertEqual(full["dependencies"][0]["source"], "function 'PercentageGrowth'")

        simple = object_details_payload(
            result, kind="function", table="", name="PercentageGrowth", mode="simple"
        )
        self.assertEqual(simple["expression"], "(x) => x")
        no_dax = object_details_payload(
            result, kind="function", table="", name="PercentageGrowth", mode="no_dax"
        )
        self.assertNotIn("expression", no_dax)

    def test_writes_object_json_and_uses_xlsx(self) -> None:
        result = analysis_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path = write_object_json(
                result,
                tmp,
                kind="function",
                table="",
                name="PercentageGrowth",
                mode="full",
            )
            self.assertTrue(path.name.endswith(".json"))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["details"]["kind"], "function")

            uses = write_uses_xlsx(
                result,
                tmp,
                kind="function",
                table="",
                name="PercentageGrowth",
            )
            self.assertTrue(uses.name.endswith(".xlsx"))
            import pandas as pd

            frame = pd.read_excel(uses, "Uses")
            self.assertEqual(frame.loc[0, "Source"], "function 'PercentageGrowth'")

    def test_hierarchy_dependencies(self) -> None:
        rows = dependency_rows(
            analysis_fixture(), kind="hierarchy", table="Sales", name="Date"
        )
        self.assertEqual(rows[0]["source"], "'Sales'[Date]")
        self.assertEqual(rows[0]["type"], "report")


if __name__ == "__main__":
    unittest.main()
