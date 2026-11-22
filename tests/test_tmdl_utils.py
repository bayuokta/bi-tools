"""Uji utilitas TMDL: buang measure/partition/properti tanpa parser properti."""

from __future__ import annotations

import json
import unittest

from core.tmdl_utils import (
    clean_object_definition,
    normalize_definition,
    remove_blocks,
    table_definition,
)

TABLE = """table 'Sales'
\tlineageTag: abc

\tcolumn Amount
\t\tdataType: double

\tmeasure Total = SUM(Sales[Amount])
\t\tformatString: 0

\tpartition Sales = m
\t\tmode: import
\t\tsource =
\t\t\tlet
\t\t\t\tSource = ...
\t\t\tin
\t\t\t\tSource

\tannotation PBI_QueryOrder = ["Sales"]
"""


class TmdlUtilsTests(unittest.TestCase):
    def test_normalize_line_endings_and_trailing_space(self) -> None:
        self.assertEqual(normalize_definition("a\r\nb  \r\n"), "a\nb")

    def test_remove_measure_block(self) -> None:
        text = remove_blocks(TABLE, "measure ", min_level=1)
        self.assertNotIn("measure Total", text)
        self.assertIn("column Amount", text)
        self.assertIn("partition Sales", text)

    def test_remove_partition_block_keeps_column(self) -> None:
        text = remove_blocks(TABLE, "partition ", min_level=1)
        self.assertNotIn("partition Sales", text)
        self.assertIn("measure Total", text)

    def test_clean_removes_annotations_and_lineage(self) -> None:
        text = clean_object_definition(TABLE, annotations=False, lineage_tag=False)
        self.assertNotIn("lineageTag", text)
        self.assertNotIn("annotation ", text)
        self.assertIn("column Amount", text)

    def test_clean_keeps_annotations_and_lineage_when_requested(self) -> None:
        text = clean_object_definition(TABLE, annotations=True, lineage_tag=True)
        self.assertIn("lineageTag: abc", text)
        self.assertIn("annotation PBI_QueryOrder", text)

    def test_table_definition_removes_measure_and_partition(self) -> None:
        text = table_definition(
            TABLE,
            partitions=False,
            annotations=False,
            lineage_tag=False,
        )
        self.assertNotIn("measure Total", text)
        self.assertNotIn("partition Sales", text)
        self.assertIn("column Amount", text)

    def test_table_definition_keeps_partitions_when_requested(self) -> None:
        text = table_definition(
            TABLE,
            partitions=True,
            annotations=True,
            lineage_tag=True,
        )
        self.assertIn("partition Sales", text)
        self.assertIn("annotation PBI_QueryOrder", text)


    def test_tmsl_table_removes_measures_partitions_lineage(self) -> None:
        text = json.dumps(
            {
                "name": "Sales",
                "lineageTag": "abc",
                "columns": [{"name": "Amount"}],
                "measures": [{"name": "Total", "expression": "SUM(Sales[Amount])"}],
                "partitions": [{"name": "Sales", "mode": "import"}],
                "annotations": [{"name": "PBI_QueryOrder", "value": "[]"}],
            }
        )
        cleaned = table_definition(
            text,
            partitions=False,
            annotations=False,
            lineage_tag=False,
            tmsl=True,
        )
        self.assertNotIn("measures", cleaned)
        self.assertNotIn("partitions", cleaned)
        self.assertNotIn("lineageTag", cleaned)
        self.assertNotIn("annotations", cleaned)
        self.assertIn("columns", cleaned)
        self.assertIn("Amount", cleaned)

    def test_tmsl_keeps_values_when_requested(self) -> None:
        text = json.dumps(
            {
                "name": "Sales",
                "lineageTag": "abc",
                "partitions": [{"name": "Sales"}],
            }
        )
        cleaned = clean_object_definition(
            text, annotations=True, lineage_tag=True, tmsl=True
        )
        self.assertIn("lineageTag", cleaned)
        self.assertIn("partitions", cleaned)


if __name__ == "__main__":
    unittest.main()
