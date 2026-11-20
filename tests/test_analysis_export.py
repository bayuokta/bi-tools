"""Uji ekspor lineage/dependensi analisa ke CSV/JSON."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.analysis_export import (
    dependency_rows,
    output_stem,
    safe_name,
    write_dependencies_csv,
    write_lineage_files,
)


def analysis_fixture() -> SimpleNamespace:
    column = SimpleNamespace(column="Amount", table="Sales")
    column_item = SimpleNamespace(
        column=column,
        status="Dipakai",
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
        status="Dipakai",
        model_refs=[],
        report_records=[],
    )
    return SimpleNamespace(columns=[column_item], measures=[measure_item])


class ExportNameTests(unittest.TestCase):
    def test_safe_name(self) -> None:
        self.assertEqual(safe_name('Sales/2026: "A"'), "Sales_2026_ _A_")
        self.assertEqual(safe_name(""), "Analisa")
        self.assertEqual(output_stem("Sales", "Amount"), "Sales_Amount")


class LineageExportTests(unittest.TestCase):
    def test_writes_nodes_edges_and_json(self) -> None:
        payload = {
            "nodes": [
                {
                    "id": "col:Sales:Amount",
                    "kind": "column",
                    "label": "Amount",
                    "context": "Sales",
                    "status": "Dipakai",
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


class DependencyExportTests(unittest.TestCase):
    def test_rows_for_column(self) -> None:
        rows = dependency_rows(
            analysis_fixture(), kind="column", table="Sales", name="Amount"
        )
        self.assertEqual([row["type"] for row in rows], ["model", "report", "report"])
        self.assertEqual(rows[0]["kind"], "measure")
        self.assertEqual(rows[1]["report"], "Report Uji")
        self.assertEqual(rows[2]["hidden"], "TRUE")

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


if __name__ == "__main__":
    unittest.main()
