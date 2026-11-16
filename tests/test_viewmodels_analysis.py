"""Uji view model Analisa Semantic Model (tanpa widget, tanpa jaringan)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - tergantung environment
    QT_AVAILABLE = False

if QT_AVAILABLE:
    from core.auth import ServicePrincipal
    from core.column_stats import ColumnStat, MeasureStat, ModelStats, TableStat
    from core.errors import ExtractionError
    from core.lineage_store import (
        close_quietly,
        connect,
        initialize,
        save_workspaces,
    )
    from core.usage_service import (
        STATUS_UNUSED,
        STATUS_USED,
        build_analysis,
    )

    from app.settings import (
        SETTINGS_ANALYSIS_OBJECT_FILTER_KEY,
        SETTINGS_ANALYSIS_OTHER_WS_KEY,
        SETTINGS_ANALYSIS_PERSONAL_KEY,
        SETTINGS_ANALYSIS_UNUSED_ONLY_KEY,
        SETTINGS_ANALYSIS_WORKSPACE_KEY,
    )
    from app.settings_store import AppSettings
    from app.viewmodels.analysis import AnalysisViewModel

WORKSPACE = "33333333-3333-4333-8333-333333333333"
DATASET = "77777777-7777-4777-8777-777777777777"


class FakeRunner:
    def __init__(self, *, accept: bool = True, run: bool = True) -> None:
        self.calls: list[str] = []
        self.accept = accept
        self.run = run

    def submit(self, title, job, on_success=None):
        self.calls.append(title)
        if not self.accept:
            return False
        if self.run:
            result = job(lambda _message: None)
            if on_success is not None:
                on_success(result)
        return True


def column(name: str, *, size: int = 1024) -> ColumnStat:
    return ColumnStat(
        table="Sales",
        column=name,
        column_id=1,
        column_type="data",
        data_type="string",
        format_string="",
        display_folder="",
        is_hidden=False,
        is_calculated=False,
        sort_by_column="",
        expression="",
        size_data_bytes=size,
        size_hierarchy_bytes=0,
        rows=10,
    )


def make_result(dataset_id: str = DATASET):
    stats = ModelStats(
        model_name="Model",
        compatibility_level=1600,
        last_update="2026-01-01",
        columns=[column("Customer"), column("Qty", size=2048)],
        tables=[TableStat("Sales", 2, 10, 3072, 0)],
        segment_bytes=3072,
        artifact_bytes=0,
        measures=[MeasureStat(table="Sales", measure="Total", expression="SUM(Sales[Qty])")],
    )
    usage_rows = [
        {
            "report_id": "r1",
            "report_name": "Report A",
            "report_workspace": WORKSPACE,
            "table_name": "Sales",
            "field_name": "Customer",
            "usage_kind": "field",
            "field_kind": "Column",
            "page_name": "Overview",
            "visual_title": "List",
            "visual_type": "tableEx",
            "detail": "Values",
        }
    ]
    return build_analysis(
        stats=stats,
        usage_rows=usage_rows,
        model_refs={},
        reports=[],
        dataset_id=dataset_id,
        dataset_name="Uji",
        workspace_id=WORKSPACE,
        workspace_name="Contoh - SO",
        method="admin",
        report_total=1,
        report_scanned=1,
        report_skipped=0,
        report_failed=0,
        coverage_complete=True,
        coverage="1 report · 1 dipindai",
    )


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class AnalysisViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.db = self.folder / "data" / "bi_tools.db"
        conn = connect(self.db)
        try:
            initialize(conn)
            save_workspaces(
                conn,
                "sync-1",
                [
                    {
                        "id": WORKSPACE,
                        "name": "Contoh - SO",
                        "state": "Active",
                        "type": "Workspace",
                    }
                ],
            )
        finally:
            close_quietly(conn)
        raw = QSettings(
            str(self.folder / "settings.ini"), QSettings.Format.IniFormat
        )
        self.settings = AppSettings(raw)
        self.settings.set_lineage_db(self.db)
        self.runner = FakeRunner(accept=False)

    def make(self) -> AnalysisViewModel:
        vm = AnalysisViewModel(self.settings, self.runner)
        vm.start()
        return vm

    # -- katalog -----------------------------------------------------------
    def test_workspaces_read_from_catalog(self) -> None:
        state = self.make().build_state()

        self.assertEqual(
            state.workspaces, (("Contoh - SO (33333333)", WORKSPACE),)
        )
        self.assertEqual(state.workspace_id, "")
        self.assertFalse(state.can_run)

    def test_set_workspace_persists_and_clears_dataset(self) -> None:
        vm = self.make()

        vm.set_workspace(WORKSPACE)

        self.assertEqual(
            self.settings.value(SETTINGS_ANALYSIS_WORKSPACE_KEY), WORKSPACE
        )
        self.assertEqual(vm.build_state().dataset_id, "")

    def test_load_datasets_uses_worker_payload(self) -> None:
        vm = self.make()
        vm.set_workspace(WORKSPACE)
        self.settings.set_principal(
            ServicePrincipal.from_values("t", "c", "s")
        )
        self.runner.accept = True
        self.runner.run = True
        with patch(
            "app.viewmodels.service_picker.PowerBILineageClient"
        ) as client_cls:
            client_cls.return_value.datasets_in_group.return_value = [
                {"id": DATASET, "name": "Uji"}
            ]
            vm.load_datasets()

        state = vm.build_state()
        self.assertEqual(
            state.datasets, (("Uji (77777777)", DATASET),)
        )
        self.assertIn("1 semantic model", state.status)

    def test_missing_credentials_blocks_analysis(self) -> None:
        vm = self.make()
        vm.set_workspace(WORKSPACE)
        vm.apply_contents(WORKSPACE, {"datasets": [{"id": DATASET, "name": "D"}]})
        vm.set_dataset(DATASET)

        self.assertFalse(vm.analyze())
        self.assertIn("Kredensial", vm.build_state().status)
        self.assertEqual(self.runner.calls, [])

    def test_request_requires_selection(self) -> None:
        vm = self.make()
        with self.assertRaises(ExtractionError):
            vm.request()

    def test_request_uses_catalog_names(self) -> None:
        vm = self.make()
        vm.set_workspace(WORKSPACE)
        vm.apply_contents(WORKSPACE, {"datasets": [{"id": DATASET, "name": "D"}]})
        vm.set_dataset(DATASET)
        with patch(
            "app.viewmodels.analysis.resolve_names",
            return_value=("Contoh - SO", "Uji"),
        ):
            request = vm.request()

        self.assertEqual(request.workspace_name, "Contoh - SO")
        self.assertEqual(request.dataset_name, "Uji")
        self.assertTrue(request.include_other_workspaces)
        self.assertFalse(request.include_personal)

    # -- analisa -----------------------------------------------------------
    def prepare(self, *, run: bool = True) -> AnalysisViewModel:
        self.settings.set_principal(
            ServicePrincipal.from_values("t", "c", "s")
        )
        vm = self.make()
        vm.set_workspace(WORKSPACE)
        vm.apply_contents(WORKSPACE, {"datasets": [{"id": DATASET, "name": "Uji"}]})
        vm.set_dataset(DATASET)
        self.runner.accept = True
        self.runner.run = run
        return vm

    def test_analyze_stores_result_and_state(self) -> None:
        vm = self.prepare()
        result = make_result()
        with patch(
            "app.viewmodels.analysis.resolve_names",
            return_value=("Contoh - SO", "Uji"),
        ), patch(
            "app.viewmodels.analysis.analyze_dataset", return_value=result
        ) as analyze:
            self.assertTrue(vm.analyze())

        self.assertIs(vm.result, result)
        state = vm.build_state()
        self.assertTrue(state.has_result)
        self.assertIn("2 kolom", state.summary)
        self.assertIn("1 tidak dipakai", state.summary)
        self.assertIn("selesai", state.status.lower())
        kwargs = analyze.call_args.kwargs
        self.assertEqual(kwargs["workspace_name"], "Contoh - SO")
        self.assertEqual(kwargs["dataset_name"], "Uji")
        self.assertEqual(
            self.settings.value("analysis/dataset_id"), DATASET
        )

    def test_object_filter_columns_and_measures(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())

        self.assertEqual(len(vm.visible_objects()), 3)
        vm.set_object_filter("columns")
        self.assertEqual([row["type"] for row in vm.visible_objects()], ["data", "data"])
        vm.set_object_filter("measures")
        self.assertEqual([row["name"] for row in vm.visible_objects()], ["Total"])
        self.assertEqual(
            self.settings.value(SETTINGS_ANALYSIS_OBJECT_FILTER_KEY), "measures"
        )

    def test_sort_by_size_descending_first_click(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())
        vm.set_sort("size")

        rows = vm.visible_objects()
        self.assertEqual([row["name"] for row in rows], ["Qty", "Customer", "Total"])
        state = vm.build_state()
        self.assertEqual(state.sort_column, "size")
        self.assertTrue(state.sort_desc)
        self.assertTrue(self.settings.value("analysis/sort_desc", type=bool))

    def test_sort_toggles_on_second_click(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())
        vm.set_sort("size")
        vm.set_sort("size")

        self.assertEqual(
            [row["name"] for row in vm.visible_objects()],
            ["Total", "Customer", "Qty"],
        )
        self.assertFalse(vm.build_state().sort_desc)

    def test_sort_text_and_uses(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())
        vm.set_sort("name")
        self.assertEqual(
            [row["name"] for row in vm.visible_objects()],
            ["Customer", "Qty", "Total"],
        )
        vm.set_sort("uses")
        self.assertEqual(vm.visible_objects()[0]["name"], "Customer")
        self.assertTrue(vm.build_state().sort_desc)

    def test_sort_status_uses_rank(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())
        vm.set_sort("status")

        rows = vm.visible_objects()
        self.assertEqual([row["status"] for row in rows][-1], "Dipakai")
        self.assertEqual(rows[0]["status"], "Tidak dipakai")

    def test_sort_persists_and_resets(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())
        vm.set_sort("table")

        other = self.make()
        self.assertEqual(other.build_state().sort_column, "table")

        other.reset_sort()
        self.assertEqual(other.build_state().sort_column, "default")
        self.assertEqual(
            self.settings.value("analysis/sort_column"), "default"
        )

    def test_summary_counts_measures(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())

        summary = vm.build_state().summary
        self.assertIn("2 kolom", summary)
        self.assertIn("1 measure", summary)
        self.assertIn("1 measure tidak dipakai", summary)

    def test_unused_only_filters_visible_rows(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())

        self.assertEqual(len(vm.visible_columns()), 2)
        vm.set_unused_only(True)

        rows = vm.visible_columns()
        self.assertEqual([row["name"] for row in rows], ["Qty"])
        self.assertEqual(rows[0]["status"], STATUS_UNUSED)
        self.assertTrue(self.settings.value(SETTINGS_ANALYSIS_UNUSED_ONLY_KEY))

    def test_used_column_status_is_reported(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())
        rows = {row["name"]: row for row in vm.visible_columns()}

        self.assertEqual(rows["Customer"]["status"], STATUS_USED)
        self.assertEqual(rows["Customer"]["reports"], 1)

    def test_stop_requests_stop_between_reports(self) -> None:
        vm = self.prepare(run=False)
        self.runner.accept = True
        with patch(
            "app.viewmodels.analysis.resolve_names",
            return_value=("Contoh - SO", "Uji"),
        ), patch("app.viewmodels.analysis.analyze_dataset") as analyze:
            self.assertTrue(vm.analyze())
            vm.stop()

        self.assertIn("Menghentikan", vm.build_state().status)
        analyze.assert_not_called()

    def test_busy_rejection_clears_running_state(self) -> None:
        vm = self.prepare()
        with patch(
            "app.viewmodels.analysis.resolve_names",
            return_value=("Contoh - SO", "Uji"),
        ), patch("app.viewmodels.analysis.analyze_dataset"):
            self.runner.accept = False
            self.assertFalse(vm.analyze())

        self.assertIn("masih berjalan", vm.build_state().status)
        self.assertFalse(vm.build_state().running)

    def test_failure_resets_running_state(self) -> None:
        vm = self.prepare(run=False)
        with patch(
            "app.viewmodels.analysis.resolve_names",
            return_value=("Contoh - SO", "Uji"),
        ), patch("app.viewmodels.analysis.analyze_dataset"):
            self.assertTrue(vm.analyze())
            vm.set_busy(False)

        self.assertIn("tanpa hasil", vm.build_state().status)

    def test_export_writes_workbook(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())
        target = self.folder / "hasil.xlsx"

        written = vm.export(target)

        self.assertTrue(written.exists())
        self.assertEqual(written.suffix, ".xlsx")

    def test_export_without_result_raises(self) -> None:
        vm = self.make()
        with self.assertRaises(ExtractionError):
            vm.export(self.folder / "x.xlsx")

    def test_output_name_uses_dataset(self) -> None:
        vm = self.prepare(run=False)
        vm.apply_result(make_result())

        name = vm.default_output_path().name
        self.assertTrue(name.startswith("Analisa_Semantic_Model_Uji_77777777"))

    def test_include_personal_flag_persists(self) -> None:
        vm = self.make()
        vm.set_include_personal(True)

        self.assertTrue(self.settings.value(SETTINGS_ANALYSIS_PERSONAL_KEY))
        self.assertTrue(vm.build_state().include_personal)

    def test_request_passes_include_personal(self) -> None:
        vm = self.prepare(run=False)
        vm.set_include_personal(True)
        with patch(
            "app.viewmodels.analysis.resolve_names",
            return_value=("Contoh - SO", "Uji"),
        ):
            request = vm.request()

        self.assertTrue(request.include_personal)

    def test_include_other_flag_persists(self) -> None:
        vm = self.make()
        vm.set_include_other(False)

        self.assertFalse(self.settings.value(SETTINGS_ANALYSIS_OTHER_WS_KEY))
        self.assertFalse(vm.build_state().include_other_workspaces)

    def test_snapshot_restored_on_start(self) -> None:
        from core.report_usage import ReportUsage, UsageRecord
        from core.usage_service import model_snapshot
        from core.usage_store import (
            initialize,
            save_columns,
            save_report,
            save_run,
        )

        result = make_result()
        conn = connect(self.db)
        try:
            initialize(conn)
            save_columns(conn, DATASET, result.stats.columns)
            save_report(
                conn,
                report_id="r1",
                workspace_id=WORKSPACE,
                dataset_id=DATASET,
                name="Report A",
                report_format="PBIR",
                modified_at="2026-01-01T00:00:00Z",
                status="ok",
                usage=ReportUsage(
                    report_format="PBIR",
                    records=[
                        UsageRecord("field", "Column", "Sales", "Customer")
                    ],
                ),
            )
            save_run(
                conn,
                {
                    "scan_id": "s1",
                    "dataset_id": DATASET,
                    "workspace_id": WORKSPACE,
                    "dataset_name": "Uji",
                    "started_at": "2026-01-01T09:59:00+00:00",
                    "finished_at": "2026-01-01T10:00:00+00:00",
                    "status": "Succeeded",
                    "report_total": 1,
                    "report_scanned": 1,
                    "coverage_complete": 1,
                    "model_json": model_snapshot(result.stats),
                    "column_count": 2,
                    "coverage": "1 report · 1 dipindai",
                },
            )
        finally:
            close_quietly(conn)
        self.settings.set_value("analysis/dataset_id", DATASET)

        vm = self.make()

        self.assertIsNotNone(vm.result)
        state = vm.build_state()
        self.assertTrue(state.has_result)
        self.assertIn("tersimpan", state.status)
        self.assertIn("2 kolom", state.summary)

    def test_string_false_flags_are_read_as_false(self) -> None:
        # QSettings menyimpan bool sebagai string; jangan memakai bool("false").
        self.settings.set_value("analysis/unused_only", "false")
        self.settings.set_value("analysis/include_other_workspaces", "false")
        self.settings.set_value("analysis/include_personal", "false")

        state = self.make().build_state()

        self.assertFalse(state.unused_only)
        self.assertFalse(state.include_other_workspaces)
        self.assertFalse(state.include_personal)

    def test_reload_drops_unknown_workspace(self) -> None:
        self.settings.set_value(
            SETTINGS_ANALYSIS_WORKSPACE_KEY,
            "00000000-0000-0000-0000-000000000000",
        )
        vm = self.make()

        self.assertEqual(vm.build_state().workspace_id, "")


if __name__ == "__main__":
    unittest.main()
