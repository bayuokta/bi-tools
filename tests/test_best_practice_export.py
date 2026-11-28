"""Uji ekspor tab Best practice mengikuti template Measure Killer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from core.best_practice_export import (
    BEST_PRACTICE_COLUMNS,
    build_best_practice_rows,
    write_best_practice_export,
)
from tests.test_best_practice import column, measure, relationship, result, table


def sample():
    return result(
        columns=[
            column("Customer", description=""),
            column("Start of Month", data_type="datetime", format_string="General Date"),
        ],
        measures=[measure("Total", description="")],
        tables=[table("Sales", description=""), table("Calc", calculated=True)],
        relationships=[
            relationship(
                "Rel",
                "Sales",
                "Customer",
                "Dim",
                "Customer",
                cross="bothDirections",
            )
        ],
    )


class BestPracticeExportTests(unittest.TestCase):
    def test_rows_match_template_columns(self) -> None:
        rows = build_best_practice_rows(sample())
        self.assertEqual(list(rows[0].keys()), BEST_PRACTICE_COLUMNS)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertTrue(row["Rule"].startswith("["))
            self.assertIsInstance(row["Violation Score"], int)
            self.assertIn(row["Severity"], {1, 2, 3})
            self.assertTrue(row["Object"])

    def test_rule_names_are_not_double_prefixed(self) -> None:
        rows = build_best_practice_rows(sample())
        rules = {row["Rule"] for row in rows}
        self.assertIn("[Maintenance] Visible objects with no description", rules)
        self.assertFalse(any(rule.startswith("[[") for rule in rules))
        self.assertFalse(any("] [" in rule for rule in rules))

    def test_rows_sorted_by_rule_score(self) -> None:
        rows = build_best_practice_rows(sample())
        scores = [row["Violation Score"] for row in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_object_labels_and_rule_score_repeat(self) -> None:
        rows = build_best_practice_rows(sample())
        objects = {row["Object"] for row in rows}
        self.assertIn("'Sales'[Customer]", objects)
        self.assertIn("'Sales'[Total]", objects)
        self.assertIn("Sales (Table)", objects)
        self.assertIn("Calc (Calculated Table)", objects)
        maintenance = [
            row for row in rows
            if row["Rule"] == "[Maintenance] Visible objects with no description"
        ]
        self.assertGreater(len(maintenance), 1)
        self.assertEqual(
            len({row["Violation Score"] for row in maintenance}), 1
        )

    def test_write_best_practice_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Best.xlsx"
            write_best_practice_export(sample(), target)
            frame = pd.read_excel(target, "Best practice", keep_default_na=False)
        self.assertEqual(list(frame.columns), BEST_PRACTICE_COLUMNS)
        self.assertGreater(len(frame), 0)


if __name__ == "__main__":
    unittest.main()
