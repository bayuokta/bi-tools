"""Uji pemilihan baris TMSCHEMA mentah untuk kolom/measure."""

from __future__ import annotations

import unittest
from datetime import datetime

from core.raw_metadata import (
    COLUMN_DMV,
    metadata_payload,
    find_row,
    normalize_row,
    table_lookup,
)


TABLES = [
    {"ID": 1, "Name": "Sales"},
    {"ID": 2, "Name": "KPI"},
]

COLUMNS = [
    {"ID": 10, "TableID": 1, "ExplicitName": "Amount", "InferredName": "Amount"},
    {"ID": 11, "TableID": 1, "ExplicitName": "Qty", "InferredName": "Qty"},
    {"ID": 12, "TableID": 2, "ExplicitName": "Amount", "InferredName": "Amount"},
]

MEASURES = [
    {"ID": 20, "TableID": 2, "Name": "Total"},
    {"ID": 21, "TableID": 2, "Name": "Other"},
]

FUNCTIONS = [
    {"ID": 30, "Name": "PercentageGrowth", "Expression": "(x) => x"},
]

HIERARCHIES = [
    {"ID": 40, "TableID": 1, "Name": "Date"},
    {"ID": 41, "TableID": 1, "Name": "Product"},
]


class TableLookupTests(unittest.TestCase):
    def test_lookup(self) -> None:
        by_id, by_name = table_lookup(TABLES)
        self.assertEqual(by_id[1], "Sales")
        self.assertEqual(by_name["kpi"], 2)


class FindRowTests(unittest.TestCase):
    def test_column_by_id_wins(self) -> None:
        row = find_row(
            COLUMNS,
            kind="column",
            table="KPI",
            name="Amount",
            column_id=10,
            tables=TABLES,
        )
        self.assertEqual(row["ID"], 10)

    def test_column_by_table_and_name(self) -> None:
        row = find_row(
            COLUMNS, kind="column", table="KPI", name="Amount", tables=TABLES
        )
        self.assertEqual(row["ID"], 12)

    def test_measure_by_table_and_name(self) -> None:
        row = find_row(
            MEASURES, kind="measure", table="KPI", name="Total", tables=TABLES
        )
        self.assertEqual(row["ID"], 20)

    def test_missing_row(self) -> None:
        self.assertIsNone(
            find_row(
                COLUMNS, kind="column", table="Sales", name="Nope", tables=TABLES
            )
        )

    def test_function_by_name(self) -> None:
        row = find_row(
            FUNCTIONS, kind="function", table="", name="PercentageGrowth"
        )
        self.assertEqual(row["ID"], 30)

    def test_hierarchy_by_table_and_name(self) -> None:
        row = find_row(
            HIERARCHIES, kind="hierarchy", table="Sales", name="Date", tables=TABLES
        )
        self.assertEqual(row["ID"], 40)

    def test_table_by_name(self) -> None:
        rows = [{"ID": 1, "Name": "Sales"}, {"ID": 2, "Name": "KPI"}]
        row = find_row(rows, kind="table", table="", name="KPI")
        self.assertEqual(row["ID"], 2)


class PayloadTests(unittest.TestCase):
    def test_normalize_row(self) -> None:
        row = normalize_row(
            {"ID": 1, "ModifiedTime": datetime(2026, 1, 2, 3, 4, 5), "Name": "X"}
        )
        self.assertEqual(row["ModifiedTime"], "2026-01-02 03:04:05")
        self.assertEqual(row["ID"], 1)

    def test_found_payload(self) -> None:
        payload = metadata_payload(
            COLUMNS[0], kind="column", dmv=COLUMN_DMV, table="Sales", name="Amount"
        )
        self.assertTrue(payload["found"])
        self.assertEqual(payload["row"]["ExplicitName"], "Amount")

    def test_missing_payload(self) -> None:
        payload = metadata_payload(
            None, kind="measure", dmv="TMSCHEMA_MEASURES", table="KPI", name="X"
        )
        self.assertFalse(payload["found"])
        self.assertIsNone(payload["row"])

    def test_function_payload_keeps_kind(self) -> None:
        payload = metadata_payload(
            FUNCTIONS[0],
            kind="function",
            dmv="TMSCHEMA_FUNCTIONS",
            table="",
            name="PercentageGrowth",
        )
        self.assertEqual(payload["kind"], "function")
        self.assertEqual(payload["row"]["Name"], "PercentageGrowth")


if __name__ == "__main__":
    unittest.main()
