"""Uji ekspor tab Relationships mengikuti template Measure Killer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.relationship_export import (
    RELATIONSHIP_RESULT_COLUMNS,
    build_relationship_rows,
    relationship_label,
    relationship_row,
    write_relationship_export,
)


def result() -> SimpleNamespace:
    return SimpleNamespace(
        relationships=[
            {
                "name": "e859c681-77f7-63ab-02a9-84db2d28ded4",
                "relationship_id": "e859c681-77f7-63ab-02a9-84db2d28ded4",
                "from_table": "Data Revenue",
                "from_column": "Dealer Code Old",
                "to_table": "Master Dealer",
                "to_column": "Dealer Code Old",
                "cross_filtering": "oneDirection",
                "is_active": True,
                "is_auto": False,
                "from_cardinality": "many",
                "to_cardinality": "one",
                "dependent_count": 3,
            },
            {
                "name": "1c2a0375-9d36-3e67-bf11-21c5c13a1d2d",
                "relationship_id": "1c2a0375-9d36-3e67-bf11-21c5c13a1d2d",
                "from_table": "Prev Dates",
                "from_column": "Dates Key",
                "to_table": "Dates",
                "to_column": "Dates Key",
                "cross_filtering": "oneDirection",
                "is_active": False,
                "is_auto": False,
                "from_cardinality": "many",
                "to_cardinality": "one",
                "dependent_count": 0,
            },
            {
                "name": "1f4d3a81-69e1-f83d-f24f-a3e1c867fe1b",
                "relationship_id": "1f4d3a81-69e1-f83d-f24f-a3e1c867fe1b",
                "from_table": "RLS Dealer",
                "from_column": "Dealer Code New",
                "to_table": "Master Dealer New",
                "to_column": "Dealer Code New",
                "cross_filtering": "bothDirections",
                "is_active": True,
                "is_auto": True,
                "from_cardinality": "many",
                "to_cardinality": "one",
                "dependent_count": 1,
            },
        ]
    )


class RelationshipExportTests(unittest.TestCase):
    def test_label_and_cardinality(self) -> None:
        item = result().relationships[0]
        self.assertEqual(
            relationship_label(item),
            "'Data Revenue'[Dealer Code Old] N <- 1 "
            "'Master Dealer'[Dealer Code Old]",
        )
        self.assertEqual(relationship_row(item)["cardinality"], "N <- 1")
        both = relationship_row(result().relationships[2])
        self.assertEqual(both["cardinality"], "N <-> 1")
        self.assertEqual(
            both["label"],
            "'RLS Dealer'[Dealer Code New] N <-> 1 "
            "'Master Dealer New'[Dealer Code New]",
        )

    def test_rows_match_template(self) -> None:
        rows = build_relationship_rows(result())
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            [row["Name"] for row in rows],
            [
                "'Data Revenue'[Dealer Code Old] N <- 1 "
                "'Master Dealer'[Dealer Code Old]",
                "'Prev Dates'[Dates Key] N <- 1 'Dates'[Dates Key]",
                "'RLS Dealer'[Dealer Code New] N <-> 1 "
                "'Master Dealer New'[Dealer Code New]",
            ],
        )
        first = rows[0]
        self.assertEqual(
            first["ID"], "e859c681-77f7-63ab-02a9-84db2d28ded4"
        )
        self.assertEqual(first["Is_active"], "Active")
        self.assertEqual(first["Cross_filter"], "Single")
        self.assertEqual(first["Cardinality"], " N <- 1 ")
        self.assertEqual(first["Status"], "Used")
        self.assertEqual(first["Auto_created"], "No")
        self.assertEqual(first["DAX_uses"], 3)
        self.assertEqual(first["From_column"], "Data Revenue[Dealer Code Old]")
        self.assertEqual(first["To_column"], "Master Dealer[Dealer Code Old]")

        inactive = rows[1]
        self.assertEqual(inactive["Is_active"], "Inactive")
        self.assertEqual(inactive["Status"], "Unused")

        both = rows[2]
        self.assertEqual(both["Cross_filter"], "Both")
        self.assertEqual(both["Cardinality"], " N <-> 1 ")
        self.assertEqual(both["Auto_created"], "Yes")
        self.assertEqual(both["DAX_uses"], 1)

    def test_userelationship_usage_adds_rows_and_status(self) -> None:
        measure = SimpleNamespace(
            measure=SimpleNamespace(
                table="Sales",
                measure="Rel Measure",
                measure_id=99,
                expression=(
                    "CALCULATE(SUM(Sales[Qty]), "
                    "USERELATIONSHIP('Prev Dates'[Dates Key], "
                    "'Dates'[Dates Key]))"
                ),
            ),
            status="Used",
            use_count=4,
        )
        data = SimpleNamespace(
            relationships=result().relationships, measures=[measure]
        )
        rows = build_relationship_rows(data)
        prev = [
            row for row in rows
            if row["Name"].startswith("'Prev Dates'[Dates Key]")
        ]
        self.assertEqual(len(prev), 1)
        row = prev[0]
        self.assertEqual(row["Status"], "Used")
        self.assertEqual(row["DAX_uses"], 1)
        self.assertEqual(row["used_in_name"], "Rel Measure")
        self.assertEqual(row["used_in_ID"], 99)
        self.assertEqual(row["used_in_type"], "Measure")
        self.assertEqual(row["used_in_table"], "Sales")
        self.assertEqual(row["used_in_status"], "Used")
        self.assertEqual(row["used_in_number_of_uses"], 4)

    def test_write_relationship_export_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Relationships.xlsx"
            write_relationship_export(result(), target)
            frame = pd.read_excel(target, "Relationships", keep_default_na=False)
        self.assertEqual(list(frame.columns), RELATIONSHIP_RESULT_COLUMNS)
        self.assertEqual(len(frame), 3)


if __name__ == "__main__":
    unittest.main()
