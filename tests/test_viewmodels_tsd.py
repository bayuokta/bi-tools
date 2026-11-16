"""Uji view model TSD tanpa widget: formulir, path, request, manual, capture."""

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
    from core.errors import ExtractionError
    from core.lineage_store import (
        close_quietly,
        connect,
        initialize,
        save_workspaces,
    )

    from app.settings_store import AppSettings
    from app.viewmodels.tsd import TsdViewModel

WORKSPACE = "44444444-4444-4444-8444-444444444444"
WORKSPACE_NAME = "Contoh - SO"
OTHER_WORKSPACE = "8a5b1c2d-1111-4222-8333-944455556666"
REPORT = "55555555-5555-4555-8555-555555555555"
REPORTS = [
    {
        "id": REPORT,
        "name": "Report Uji",
        "datasetId": "ds-1",
        "reportType": "PowerBIReport",
    }
]

if QT_AVAILABLE:

    def seed_workspaces(database: Path, rows: list[dict]) -> None:
        conn = connect(database)
        try:
            initialize(conn)
            save_workspaces(conn, "test", rows)
        finally:
            close_quietly(conn)


class FakeRunner:
    def __init__(self, *, accept: bool = True) -> None:
        self.calls: list[tuple] = []
        self.accept = accept

    def submit(self, title, job, on_success=None) -> bool:
        self.calls.append((title, job, on_success))
        return self.accept


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class TsdViewModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        raw = QSettings(
            str(self.folder / "settings.ini"), QSettings.Format.IniFormat
        )
        self.settings = AppSettings(raw)
        self.runner = FakeRunner()

    def make(self) -> TsdViewModel:
        return TsdViewModel(self.settings, self.runner)

    def workbook(self) -> Path:
        path = self.folder / "Report_Metadata.xlsx"
        path.write_bytes(b"x")
        return path

    def seed_catalog(self) -> None:
        database = self.folder / "katalog.db"
        seed_workspaces(
            database,
            [
                {
                    "id": WORKSPACE,
                    "name": WORKSPACE_NAME,
                    "state": "Active",
                    "type": "Workspace",
                },
                {
                    "id": OTHER_WORKSPACE,
                    "name": "Lain",
                    "state": "Active",
                    "type": "Workspace",
                },
            ],
        )
        self.settings.set_lineage_db(database)

    def start(self) -> TsdViewModel:
        vm = self.make()
        vm.start()
        return vm

    @staticmethod
    def workspace_index(vm: TsdViewModel, name: str = WORKSPACE_NAME) -> int:
        return next(
            index
            for index, label in enumerate(vm.build_state().workspaces)
            if label.startswith(f"{name} (")
        )

    # -- formulir ----------------------------------------------------------
    def test_defaults_and_auto_output_name(self) -> None:
        vm = self.make()
        self.assertEqual(vm.out_name, "TSD_Report.html")
        self.assertTrue(vm.form.draft)
        self.assertFalse(vm.form.screenshots)

        vm.set_report_name("Uji")
        self.assertEqual(vm.out_name, "TSD_Uji.html")

    def test_custom_out_name_is_not_overwritten(self) -> None:
        vm = self.make()
        vm.set_out_name("custom.html")
        vm.set_report_name("Uji")

        self.assertEqual(vm.out_name, "custom.html")

    def test_apply_strips_and_only_refreshes_on_change(self) -> None:
        vm = self.make()
        emitted: list[object] = []
        vm.state_changed.connect(emitted.append)

        vm.apply(out_dir=f"  {self.folder}  ", draft=False)
        self.assertEqual(vm.form.out_dir, str(self.folder))
        self.assertFalse(vm.form.draft)
        self.assertEqual(len(emitted), 1)

        vm.apply(out_dir=str(self.folder), draft=False)
        self.assertEqual(len(emitted), 1)

    # -- path --------------------------------------------------------------
    def test_paths_follow_name_folder_and_report_id(self) -> None:
        vm = self.make()
        vm.apply(out_dir=str(self.folder), report_id=REPORT)
        vm.set_report_name("Uji")

        self.assertEqual(
            vm.output_path, self.folder / "TSD_Uji_55555555.html"
        )
        self.assertEqual(
            vm.manual_path, self.folder / "TSD_Uji_55555555.json"
        )
        self.assertEqual(
            vm.assets_dir, self.folder / "TSD_assets" / "Uji_55555555"
        )

    def test_custom_out_name_disables_report_id_suffix(self) -> None:
        vm = self.make()
        vm.apply(out_dir=str(self.folder), report_id=REPORT)
        vm.set_out_name("custom.html")
        vm.set_report_name("Uji")

        self.assertEqual(vm.out_name, "custom.html")
        self.assertEqual(vm.output_path, self.folder / "custom.html")
        self.assertEqual(vm.manual_path, self.folder / "custom.json")

    def test_explicit_manual_path_wins(self) -> None:
        vm = self.make()
        custom = self.folder / "manual.json"
        vm.apply(out_dir=str(self.folder), manual_path=str(custom))

        self.assertEqual(vm.manual_path, custom)

    # -- state -------------------------------------------------------------
    def test_state_requires_existing_report_workbook(self) -> None:
        vm = self.make()
        vm.apply(out_dir=str(self.folder), report_workbook="")

        state = vm.build_state()
        self.assertFalse(state.can_run)
        self.assertEqual(state.report_status, "Belum dipilih")

        vm.apply(report_workbook=str(self.workbook()))
        self.assertTrue(vm.build_state().can_run)

    def test_screenshots_need_workspace_and_report_ids(self) -> None:
        vm = self.make()
        vm.apply(
            out_dir=str(self.folder),
            report_workbook=str(self.workbook()),
            screenshots=True,
        )
        self.assertFalse(vm.build_state().can_run)
        self.assertTrue(vm.build_state().can_capture)

        vm.apply(workspace_id=WORKSPACE, report_id=REPORT)
        self.assertTrue(vm.build_state().can_run)

    def test_busy_disables_actions(self) -> None:
        vm = self.make()
        vm.apply(
            out_dir=str(self.folder),
            report_workbook=str(self.workbook()),
            screenshots=True,
        )
        vm.set_busy(True)
        state = vm.build_state()

        self.assertFalse(state.idle)
        self.assertFalse(state.can_run)
        self.assertFalse(state.can_capture)
        self.assertFalse(state.can_clear_cache)

    # -- request -----------------------------------------------------------
    def test_build_request_rejects_missing_report(self) -> None:
        vm = self.make()
        vm.apply(report_workbook="")
        with self.assertRaises(ExtractionError):
            vm.build_request()

        vm.apply(report_workbook=str(self.folder / "hilang.xlsx"))
        with self.assertRaises(ExtractionError):
            vm.build_request()

    def test_build_request_merges_name_and_flags(self) -> None:
        vm = self.make()
        vm.apply(
            out_dir=str(self.folder),
            report_workbook=str(self.workbook()),
            draft=False,
            expand_all=True,
            include_decorative=True,
        )
        vm.set_report_name("Uji")
        vm.set_generated_at("2026-01-02")

        request, capture = vm.build_request({"report": {"name": "Lama"}})

        self.assertIsNone(capture)
        self.assertEqual(request.manual["report"]["name"], "Uji")
        self.assertFalse(request.draft)
        self.assertTrue(request.expand_all)
        self.assertTrue(request.include_decorative)
        self.assertEqual(request.generated_at, "2026-01-02")
        self.assertEqual(request.out_file, self.folder / "TSD_Uji.html")

    def test_missing_model_workbook_is_noted_and_skipped(self) -> None:
        vm = self.make()
        vm.apply(
            out_dir=str(self.folder),
            report_workbook=str(self.workbook()),
            model_workbook=str(self.folder / "model-hilang.xlsx"),
        )
        logs: list[str] = []
        vm.log.connect(logs.append)

        request, _capture = vm.build_request()

        self.assertIsNone(request.model_workbook)
        self.assertTrue(any("model TSD dikosongkan" in line for line in logs))

    def test_capture_request_uses_rls_override(self) -> None:
        self.settings.set_rls("default@user", "HO")
        vm = self.make()
        vm.apply(
            out_dir=str(self.folder),
            report_workbook=str(self.workbook()),
            screenshots=True,
            workspace_id=WORKSPACE,
            report_id=REPORT,
        )
        request, capture = vm.build_request()

        self.assertIsNotNone(capture)
        self.assertEqual(capture.credentials.rls_username, "default@user")
        self.assertEqual(capture.credentials.rls_roles, ("HO",))

        vm.set_rls("run@user", "Region")
        request, capture = vm.build_request()
        self.assertEqual(capture.credentials.rls_username, "run@user")
        self.assertEqual(capture.credentials.rls_roles, ("Region",))

    def test_headless_flag_reaches_capture_options(self) -> None:
        vm = self.make()
        vm.apply(
            out_dir=str(self.folder),
            report_workbook=str(self.workbook()),
            screenshots=True,
            workspace_id=WORKSPACE,
            report_id=REPORT,
        )
        vm.set_headless(False)

        _request, capture = vm.build_request()

        self.assertFalse(capture.headless)

    # -- eksekusi ----------------------------------------------------------
    def test_run_submits_render_job_and_saves_settings(self) -> None:
        vm = self.make()
        vm.apply(out_dir=str(self.folder), report_workbook=str(self.workbook()))
        vm.set_report_name("Uji")
        captured: dict = {}
        with patch(
            "app.viewmodels.tsd.run_tsd",
            side_effect=lambda **kwargs: captured.update(kwargs) or {"ok": True},
        ):
            self.assertTrue(vm.run({}))
            title, job, _on_success = self.runner.calls[0]
            self.assertEqual(job(lambda _message: None), {"ok": True})

        self.assertEqual(title, "Generate TSD")
        self.assertEqual(captured["out_file"], self.folder / "TSD_Uji.html")
        self.assertEqual(self.settings.value("tsd/out_dir"), str(self.folder))

    def test_capture_now_requires_checkbox(self) -> None:
        vm = self.make()
        logs: list[str] = []
        vm.log.connect(logs.append)

        self.assertFalse(vm.capture_now())
        self.assertEqual(self.runner.calls, [])
        self.assertTrue(any("Ambil screenshot" in line for line in logs))

    def test_capture_now_submits_capture_job(self) -> None:
        vm = self.make()
        vm.apply(
            out_dir=str(self.folder),
            screenshots=True,
            workspace_id=WORKSPACE,
            report_id=REPORT,
        )
        with patch("app.viewmodels.tsd.capture_report", return_value="ok"):
            self.assertTrue(vm.capture_now())
            _title, job, _on_success = self.runner.calls[0]
            self.assertEqual(job(lambda _message: None), "ok")

    # -- manual ------------------------------------------------------------
    def test_save_and_load_manual_roundtrip(self) -> None:
        vm = self.make()
        vm.apply(out_dir=str(self.folder))
        vm.set_report_name("Uji")

        path = vm.save_manual({"report": {"name": "Uji"}})

        self.assertTrue(path.exists())
        self.assertEqual(vm.manual_data["report"]["name"], "Uji")
        self.assertEqual(vm.load_manual(quiet=True), {"report": {"name": "Uji"}})

    def test_missing_manual_returns_empty_dict(self) -> None:
        vm = self.make()
        vm.apply(out_dir=str(self.folder))
        self.assertEqual(vm.load_manual(quiet=True), {})

    def test_apply_result_reloads_manual_and_logs(self) -> None:
        vm = self.make()
        vm.apply(out_dir=str(self.folder))
        vm.set_report_name("Uji")
        vm.save_manual({"report": {"name": "Uji"}})
        logs: list[str] = []
        vm.log.connect(logs.append)

        vm.apply_result({"output": "x.html", "pages": 2, "visuals": 7, "todos": 3})

        self.assertEqual(vm.manual_data["report"]["name"], "Uji")
        self.assertTrue(any("TSD" in line and "x.html" in line for line in logs))

    def test_clear_cache_removes_assets_folder(self) -> None:
        vm = self.make()
        vm.apply(out_dir=str(self.folder))
        vm.set_report_name("Uji")
        vm.assets_dir.mkdir(parents=True)

        self.assertTrue(vm.clear_cache())
        self.assertFalse(vm.assets_dir.exists())
        self.assertFalse(vm.clear_cache())

    # -- picker Power BI Service --------------------------------------------
    def test_workspace_picker_reads_catalog(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))

        state = self.start().build_state()

        self.assertEqual(len(state.workspaces), 2)
        self.assertTrue(
            any(
                label.startswith(f"{WORKSPACE_NAME} ({WORKSPACE[:8]})")
                for label in state.workspaces
            )
        )
        self.assertFalse(state.settings_shortcut_visible)
        self.assertEqual(state.workspace_index, -1)
        self.assertFalse(state.picker_active)
        self.assertFalse(state.reports_active)

    def test_empty_catalog_shows_settings_shortcut(self) -> None:
        self.settings.set_lineage_db(self.folder / "kosong.db")

        state = self.start().build_state()

        self.assertEqual(state.workspaces, ())
        self.assertIn("Belum ada workspace", state.workspace_hint)
        self.assertTrue(state.settings_shortcut_visible)

    def test_select_workspace_loads_reports_and_persists(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.start()

        vm.select_workspace(self.workspace_index(vm))

        self.assertEqual(vm.form.workspace_id, WORKSPACE)
        self.assertEqual(self.settings.value("tsd/workspace_id"), WORKSPACE)
        self.assertEqual(self.settings.value("tsd/report_id"), "")
        self.assertEqual(len(self.runner.calls), 1)
        title, _job, on_success = self.runner.calls[0]
        self.assertEqual(title, "Membaca report workspace")
        self.assertIn("Memuat daftar report", vm.build_state().loading_text)

        on_success({"workspace_id": WORKSPACE, "reports": REPORTS})

        state = vm.build_state()
        self.assertEqual(state.loading_text, "")
        self.assertEqual(state.reports, ("Report Uji (55555555)",))
        self.assertEqual(state.reports_active, False)

    def test_select_report_persists_and_fills_report_name(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.start()
        vm.apply(out_dir=str(self.folder))
        vm.select_workspace(self.workspace_index(vm))
        vm.apply_reports({"workspace_id": WORKSPACE, "reports": REPORTS})

        vm.select_report(0)

        state = vm.build_state()
        self.assertEqual(vm.form.report_id, REPORT)
        self.assertEqual(self.settings.value("tsd/report_id"), REPORT)
        self.assertEqual(state.report_index, 0)
        self.assertEqual(vm.report_name, "Report Uji")
        self.assertEqual(vm.out_name, "TSD_Report Uji_55555555.html")
        self.assertEqual(
            vm.output_path, self.folder / "TSD_Report Uji_55555555.html"
        )
        self.assertEqual(
            vm.manual_path, self.folder / "TSD_Report Uji_55555555.json"
        )
        self.assertEqual(
            vm.assets_dir, self.folder / "TSD_assets" / "Report_Uji_55555555"
        )

    def test_saved_selection_is_restored_when_reports_arrive(self) -> None:
        self.seed_catalog()
        self.settings.set_value("tsd/workspace_id", WORKSPACE)
        self.settings.set_value("tsd/report_id", REPORT)
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.start()

        self.assertEqual(vm.build_state().workspace_index, self.workspace_index(vm))
        vm.ensure_reports()
        self.assertEqual(len(self.runner.calls), 1)
        vm.apply_reports({"workspace_id": WORKSPACE, "reports": REPORTS})

        self.assertEqual(vm.build_state().report_index, 0)

    def test_workspace_without_credentials_does_not_submit(self) -> None:
        self.seed_catalog()
        vm = self.start()

        vm.select_workspace(self.workspace_index(vm))

        self.assertEqual(self.runner.calls, [])
        self.assertIn("Kredensial", vm.build_state().message)

    def test_busy_runner_reverts_nothing_but_reports_loading(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        self.runner = FakeRunner(accept=False)
        vm = self.start()

        vm.select_workspace(self.workspace_index(vm))

        self.assertEqual(vm.form.workspace_id, WORKSPACE)
        self.assertIn("masih berjalan", vm.build_state().message)

    def test_stale_report_result_is_ignored(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.start()
        vm.select_workspace(self.workspace_index(vm))

        vm.apply_reports({"workspace_id": OTHER_WORKSPACE, "reports": REPORTS})

        self.assertEqual(vm.build_state().reports, ())

    def test_report_labels_include_id_for_duplicate_names(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.start()
        vm.select_workspace(self.workspace_index(vm))
        other_report = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

        vm.apply_reports(
            {
                "workspace_id": WORKSPACE,
                "reports": [
                    {
                        "id": REPORT,
                        "name": "Report Uji",
                        "reportType": "PowerBIReport",
                    },
                    {
                        "id": other_report,
                        "name": "Report Uji",
                        "reportType": "PowerBIReport",
                    },
                ],
            }
        )

        self.assertEqual(
            vm.build_state().reports,
            ("Report Uji (55555555)", "Report Uji (aaaaaaaa)"),
        )
        vm.select_report(1)
        self.assertEqual(vm.form.report_id, other_report)

    def test_paginated_report_is_flagged(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.start()
        vm.select_workspace(self.workspace_index(vm))
        paginated = [
            {"id": REPORT, "name": "RDL", "reportType": "PaginatedReport"}
        ]

        vm.apply_reports({"workspace_id": WORKSPACE, "reports": paginated})
        vm.select_report(0)

        self.assertEqual(vm.build_state().reports, ("RDL (55555555) [Paginated]",))
        self.assertIn("paginated", vm.build_state().message)

    def test_reload_reports_needs_workspace_and_refetches(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.start()

        vm.reload_reports()
        self.assertIn("Pilih workspace", vm.build_state().message)

        vm.select_workspace(self.workspace_index(vm))
        vm.apply_reports({"workspace_id": WORKSPACE, "reports": REPORTS})
        vm.reload_reports()

        self.assertEqual(vm.build_state().reports, ())
        self.assertEqual(len(self.runner.calls), 2)

    def test_picker_enabled_state_follows_screenshots(self) -> None:
        self.seed_catalog()
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.start()
        vm.apply(screenshots=True)

        state = vm.build_state()
        self.assertTrue(state.picker_active)
        self.assertFalse(state.reports_active)

        vm.select_workspace(self.workspace_index(vm))
        self.assertTrue(vm.build_state().reports_active)

    # -- kredensial default ------------------------------------------------
    def test_default_rls_follows_settings_when_form_empty(self) -> None:
        vm = self.make()
        self.settings.set_rls("baru@user", "HO,Region")

        self.assertEqual((vm.form.rls_username, vm.form.rls_roles), ("baru@user", "HO,Region"))

    def test_settings_change_does_not_overwrite_run_override(self) -> None:
        vm = self.make()
        vm.set_rls("run@user", "Region")

        self.settings.set_rls("lain@user", "HO")

        self.assertEqual((vm.form.rls_username, vm.form.rls_roles), ("run@user", "Region"))


if __name__ == "__main__":
    unittest.main()
