"""Uji view model lineage tanpa widget: status DB, pencarian, lineage, ekspor."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - tergantung environment
    QT_AVAILABLE = False

if QT_AVAILABLE:
    from app.settings_store import AppSettings
    from app.viewmodels.lineage import LineageViewModel

    from tests.test_lineage import seed_database


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class LineageViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.db = self.folder / "lineage.db"
        seed_database(self.db)
        raw = QSettings(
            str(self.folder / "settings.ini"), QSettings.Format.IniFormat
        )
        self.settings = AppSettings(raw)
        self.settings.set_lineage_db(self.db)

    def make(self) -> LineageViewModel:
        vm = LineageViewModel(self.settings)
        vm.start()
        return vm

    # -- status ------------------------------------------------------------
    def test_state_reports_database(self) -> None:
        vm = self.make()
        states: list[object] = []
        vm.state_changed.connect(states.append)
        vm.refresh()
        last = states[-1]

        self.assertTrue(last.has_db)
        self.assertEqual(last.search_status, "Belum ada pencarian.")

    def test_missing_database_disables_search(self) -> None:
        self.settings.set_lineage_db(self.folder / "tidak-ada.db")
        vm = self.make()
        states: list[object] = []
        vm.state_changed.connect(states.append)
        vm.refresh()

        self.assertFalse(states[-1].has_db)
        self.assertIn("Sinkronisasi data", states[-1].search_status)

    def test_busy_disables_search(self) -> None:
        vm = self.make()
        states: list[object] = []
        vm.state_changed.connect(states.append)
        vm.set_busy(True)

        self.assertFalse(states[-1].idle)
        self.assertFalse(states[-1].has_root)
        results: list[object] = []
        vm.results_changed.connect(results.append)
        vm.search("Sales Report")
        self.assertEqual(results, [])

    # -- pencarian ---------------------------------------------------------
    def test_search_loads_results_and_first_root(self) -> None:
        vm = self.make()
        results: list[list] = []
        lineages: list[object] = []
        vm.results_changed.connect(results.append)
        vm.lineage_changed.connect(lineages.append)

        vm.search("Sales Report")

        self.assertEqual(len(results[-1]), 1)
        self.assertEqual(results[-1][0]["node_id"], "rep-1")
        self.assertEqual(vm.root["node_id"], "rep-1")
        self.assertEqual(len(vm.result["nodes"]), 1)
        self.assertIs(lineages[-1], vm.result)

    def test_empty_search_prompts_without_query(self) -> None:
        vm = self.make()
        states: list[object] = []
        vm.state_changed.connect(states.append)

        vm.search("  ")

        self.assertIn("Isi kata kunci", states[-1].search_status)

    def test_direction_and_depth_reload_lineage(self) -> None:
        vm = self.make()
        vm.search("Sales Report")

        vm.set_direction("upstream")
        self.assertEqual(vm.direction, "upstream")
        self.assertEqual(len(vm.result["nodes"]), 4)

        vm.set_depth(1)
        self.assertEqual(vm.depth, 1)
        self.assertEqual(len(vm.result["nodes"]), 1)

    def test_unknown_node_resets_with_note(self) -> None:
        vm = self.make()
        vm.search("Sales Report")
        states: list[object] = []
        vm.state_changed.connect(states.append)

        vm.load_lineage("tidak-ada")

        self.assertIsNone(vm.root)
        self.assertIn("tidak ditemukan", states[-1].lineage_status)

    # -- detail ------------------------------------------------------------
    def test_detail_text_covers_datasource_fields(self) -> None:
        vm = self.make()
        text = vm.detail_text(
            {
                "node_id": "sql-1",
                "node_type": "Datasource",
                "name": "Sql: srv / SalesDB",
                "owner": "owner@contoso.com",
                "datasource_type": "Sql",
                "server": "srv",
                "database_name": "SalesDB",
                "connection_details": {"database": "SalesDB"},
                "is_active": 0,
            }
        )

        self.assertIn("Tipe        : Datasource", text)
        self.assertIn("Datasource:", text)
        self.assertIn(": srv", text)
        self.assertIn("connection details", text.lower())
        self.assertIn("nonaktif", text)
        self.assertIn("Node ID     : sql-1", text)

    # -- visual dan ekspor -------------------------------------------------
    def test_graph_requires_root(self) -> None:
        vm = self.make()
        self.assertIsNone(vm.graph())

        vm.search("Sales Report")
        graph = vm.graph()

        self.assertIsNotNone(graph)
        self.assertEqual(len(graph.nodes), 6)

    def test_export_csv_writes_file_and_status(self) -> None:
        vm = self.make()
        vm.search("Sales Report")
        states: list[object] = []
        vm.state_changed.connect(states.append)
        target = self.folder / "export.csv"

        written = vm.export_csv(target)

        self.assertEqual(written, target)
        self.assertTrue(target.exists())
        self.assertIn("CSV ditulis", states[-1].lineage_status)

    def test_default_export_path_uses_root_name(self) -> None:
        vm = self.make()
        vm.search("Sales Report")

        self.assertEqual(vm.default_export_path().name, "Lineage_Sales Report.csv")

    def test_settings_path_change_is_picked_up(self) -> None:
        vm = self.make()
        other = self.folder / "lain.db"
        self.settings.set_lineage_db(other)

        self.assertEqual(vm.database, other)
        states: list[object] = []
        vm.state_changed.connect(states.append)
        vm.refresh()
        self.assertFalse(states[-1].has_db)


if __name__ == "__main__":
    unittest.main()
