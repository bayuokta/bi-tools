"""Uji ekspor tab M queries mengikuti template Measure Killer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.m_export import M_RESULT_COLUMNS, build_m_rows, write_m_export


def result() -> SimpleNamespace:
    rows = [
        {
            "name": "Sales",
            "kind": "Table",
            "source": "Import",
            "expression": "let Source = 1 in Source",
            "warning": "",
            "detail": "Sales",
            "entry_key": "table:Sales:p:Sales",
        },
        {
            "name": "Sales",
            "kind": "Table",
            "source": "Import",
            "expression": "let Source = 1 in Source",
            "warning": "",
            "detail": "refresh policy",
            "entry_key": "table:Sales:z:policy",
        },
        {
            "name": "Stock Level",
            "kind": "Table",
            "source": "Import",
            "expression": "let Source = 2 in Source",
            "warning": "evaluationError",
            "detail": "Stock Level",
            "entry_key": "table:Stock Level:p:Stock Level",
        },
        {
            "name": "Pages Testing",
            "kind": "M Query",
            "source": "Model",
            "expression": "let Source = 3 in Source",
            "warning": "",
            "detail": "",
            "entry_key": "query:Pages Testing",
        },
        {
            "name": "RangeStart",
            "kind": "M Parameter",
            "source": "Params",
            "expression": (
                "#datetime(2026, 1, 1, 0, 0, 0) meta "
                '[IsParameterQuery=true, Type="DateTime", '
                "IsParameterQueryRequired=true]"
            ),
            "warning": "",
            "detail": "DateTime",
            "entry_key": "parameter:RangeStart",
        },
    ]
    return SimpleNamespace(dataset_name="Model Uji", m_queries=rows)


class MExportTests(unittest.TestCase):
    def test_build_rows_matches_template(self) -> None:
        rows = build_m_rows(result())
        self.assertEqual(len(rows), 5)
        self.assertEqual([row["Type"] for row in rows], [
            "Table", "Table", "Table", "M Query", "M Parameter",
        ])
        self.assertEqual(
            [row["Name"] for row in rows],
            ["Sales", "Sales", "Stock Level", "Pages Testing", "RangeStart"],
        )
        self.assertEqual(rows[1]["Name"], "Sales")
        self.assertEqual(rows[1]["Expression"], rows[0]["Expression"])
        self.assertEqual(rows[2]["Warnings"], "evaluationError")
        self.assertEqual(rows[3]["Warnings"], "")
        self.assertEqual(rows[0]["Source"], "Model Uji")
        self.assertEqual(rows[3]["Source"], "Model Uji")
        self.assertIn("IsParameterQuery=true", rows[4]["Expression"])
        self.assertIn('Type="DateTime"', rows[4]["Expression"])

    def test_write_m_export_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "M.xlsx"
            write_m_export(result(), target)
            frame = pd.read_excel(target, "M expressions", keep_default_na=False)
        self.assertEqual(list(frame.columns), M_RESULT_COLUMNS)
        self.assertEqual(len(frame), 5)
        self.assertEqual(frame["Type"].value_counts().to_dict(), {
            "Table": 3,
            "M Query": 1,
            "M Parameter": 1,
        })

    def test_empty_result_writes_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "M.xlsx"
            write_m_export(
                SimpleNamespace(dataset_name="", m_queries=[]), target
            )
            frame = pd.read_excel(target, "M expressions", keep_default_na=False)
        self.assertEqual(list(frame.columns), M_RESULT_COLUMNS)
        self.assertEqual(len(frame), 0)


if __name__ == "__main__":
    unittest.main()
