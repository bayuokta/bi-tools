"""Uji lapisan baca lineage: ringkasan database, pencarian, lineage, ekspor."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from core.errors import ExtractionError
from core.lineage_service import (
    database_summary,
    export_csv,
    graph_for,
    node_lineage,
    read_connection,
    search_nodes,
    two_way_lineage,
)

from tests.test_lineage import seed_database


class LineageServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.db = self.folder / "lineage.db"
        seed_database(self.db)

    def test_missing_database_summary(self) -> None:
        summary = database_summary(self.folder / "tidak-ada.db")

        self.assertFalse(summary.exists)
        self.assertFalse(summary.readable)
        self.assertEqual(summary.items, 0)

    def test_unreadable_database_summary(self) -> None:
        broken = self.folder / "rusak.db"
        broken.write_text("bukan sqlite", encoding="utf-8")

        summary = database_summary(broken)

        self.assertTrue(summary.exists)
        self.assertFalse(summary.readable)
        self.assertIn("could not be read", summary.error.lower())

    def test_seeded_summary_counts_nodes(self) -> None:
        summary = database_summary(self.db)

        self.assertTrue(summary.readable)
        self.assertEqual(summary.items, 6)
        self.assertEqual(summary.workspaces, 1)
        self.assertEqual(summary.last_scan, "2026-01-01T00:00:00.0000000Z")
        self.assertRegex(summary.modified, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")

    def test_read_connection_wraps_missing_database(self) -> None:
        with self.assertRaises(ExtractionError):
            with read_connection(self.folder / "tidak-ada.db"):
                pass

    def test_search_filters_query_workspace_and_type(self) -> None:
        rows = search_nodes(self.db, "Sales")
        names = {row["name"] for row in rows}
        self.assertIn("Sales Report", names)

        self.assertEqual(
            [row["node_id"] for row in search_nodes(self.db, "Sales", node_type="Dashboard")],
            ["dash-1"],
        )
        self.assertEqual(
            [row["node_id"] for row in search_nodes(self.db, "", node_type="Report")],
            ["rep-1"],
        )

    def test_node_lineage_respects_direction_and_depth(self) -> None:
        downstream = node_lineage(self.db, "rep-1", "downstream")
        upstream = node_lineage(self.db, "rep-1", "upstream", max_depth=1)

        self.assertEqual(downstream["root"]["node_id"], "rep-1")
        self.assertEqual([node["node_id"] for node in downstream["nodes"]], ["dash-1"])
        self.assertEqual(len(upstream["nodes"]), 1)
        self.assertIsNone(node_lineage(self.db, "tidak-ada"))

    def test_two_way_lineage_and_graph(self) -> None:
        downstream, upstream = two_way_lineage(self.db, "rep-1")

        self.assertIsNotNone(downstream)
        self.assertIsNotNone(upstream)
        graph = graph_for(self.db, "rep-1")
        self.assertEqual(len(graph.nodes), 6)

    def test_export_csv_writes_header_and_rows(self) -> None:
        result = node_lineage(self.db, "rep-1", "downstream")
        target = self.folder / "lineage.csv"

        written = export_csv(target, result)

        self.assertEqual(written, target)
        with target.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertGreater(len(rows), 1)
        self.assertIn("node_id", rows[0])


if __name__ == "__main__":
    unittest.main()
