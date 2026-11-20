"""Uji query data mentah analisa: escaping DAX, batas baris, normalisasi."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from core.analysis_query import (
    DEFAULT_ROWS,
    MAX_ROWS,
    build_raw_query,
    clamp_rows,
    normalize_rows,
    quote_column,
    quote_table,
    raw_payload,
)


class DotNetDate:
    def ToString(self, fmt: str | None = None) -> str:
        return "2026-01-02 03:04:05" if fmt else "02/01/2026"


class QueryBuildTests(unittest.TestCase):
    def test_quote_escapes(self) -> None:
        self.assertEqual(quote_table("Sales 'Baru'"), "'Sales ''Baru'''")
        self.assertEqual(quote_column("Total]Sales"), "[Total]]Sales]")

    def test_column_query_uses_topn_and_selectcolumns(self) -> None:
        query = build_raw_query("column", "Sales 'Baru'", "Jumlah]", limit=50)
        self.assertIn("EVALUATE TOPN(50,", query)
        self.assertIn("SELECTCOLUMNS('Sales ''Baru''',", query)
        self.assertIn('"Jumlah]"', query)
        self.assertIn("'Sales ''Baru'''[Jumlah]]]", query)

    def test_measure_query_uses_row(self) -> None:
        query = build_raw_query("measure", "KPI", "Total Sales", limit=100)
        self.assertEqual(query, 'EVALUATE ROW("Measure", \'KPI\'[Total Sales])')

    def test_clamp_rows(self) -> None:
        self.assertEqual(clamp_rows(None), DEFAULT_ROWS)
        self.assertEqual(clamp_rows("abc"), DEFAULT_ROWS)
        self.assertEqual(clamp_rows(0), 1)
        self.assertEqual(clamp_rows(10_000), MAX_ROWS)
        self.assertEqual(clamp_rows(25), 25)

    def test_normalize_values(self) -> None:
        columns, rows = normalize_rows(
            [
                {
                    "Text": "a",
                    "Empty": None,
                    "Number": 12.5,
                    "Decimal": Decimal("1.25"),
                    "Date": date(2026, 1, 2),
                    "DateTime": datetime(2026, 1, 2, 3, 4, 5),
                    "DotNet": DotNetDate(),
                }
            ]
        )
        self.assertEqual(
            columns,
            ["Text", "Empty", "Number", "Decimal", "Date", "DateTime", "DotNet"],
        )
        self.assertEqual(
            rows[0],
            ["a", "", 12.5, 1.25, "2026-01-02", "2026-01-02 03:04:05",
             "2026-01-02 03:04:05"],
        )

    def test_raw_payload_marks_truncated(self) -> None:
        payload = raw_payload(
            [{"A": 1}, {"A": 2}], query="EVALUATE X", limit=2
        )
        self.assertEqual(payload["columns"], ["A"])
        self.assertEqual(payload["rows"], [[1], [2]])
        self.assertEqual(payload["row_count"], 2)
        self.assertTrue(payload["truncated"])
        payload = raw_payload([{"A": 1}], query="EVALUATE X", limit=10)
        self.assertFalse(payload["truncated"])

    def test_raw_payload_strips_bracketed_column_names(self) -> None:
        payload = raw_payload(
            [{"[Main Dealer]": "A"}], query="EVALUATE X", limit=10
        )
        self.assertEqual(payload["columns"], ["Main Dealer"])
        self.assertEqual(payload["rows"], [["A"]])


if __name__ == "__main__":
    unittest.main()
