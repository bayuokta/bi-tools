"""Uji struktur tab Metadata & TSD (offscreen, tanpa network dan tanpa .pbix)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - tergantung environment
    QT_AVAILABLE = False

if QT_AVAILABLE:
    from core.auth import ServicePrincipal
    from core.lineage_store import (
        close_quietly,
        connect,
        initialize,
        save_workspaces,
    )
    from core.paths import outputs_dir
    from core.requests import SCOPE_BOTH, SCOPE_MODEL

    from app.settings import (
        SETTINGS_ACTIVE_TAB_KEY,
        SETTINGS_CATALOG_MODE_KEY,
        SETTINGS_REPORT_SOURCE_KEY,
        SETTINGS_SCOPE_KEY,
        SETTINGS_SCOPE_LOCAL_KEY,
        SETTINGS_SCOPE_SERVICE_KEY,
        SETTINGS_SUB_TAB_KEY,
    )
    from app.settings_store import AppSettings
    from app.tabs import TAB_LOCAL, TAB_SERVICE, TAB_TSD, MetadataTab
    from app.tsd_tab import TsdTab

WORKSPACE = "33333333-3333-4333-8333-333333333333"
WORKSPACE_NAME = "Contoh - SO"
OTHER_WORKSPACE = "8a5b1c2d-1111-4222-8333-944455556666"
REPORT = "66666666-6666-4666-8666-666666666666"
DATASETS = [{"id": "ds-1", "name": "Model A"}]
REPORTS = [
    {
        "id": REPORT,
        "name": "Report Uji",
        "datasetId": "ds-1",
        "reportType": "PowerBIReport",
    }
]


class FakeWindow:
    def __init__(self, *, run_jobs: bool = False) -> None:
        self.messages: list[str] = []
        self.jobs: list[str] = []
        self.run_jobs = run_jobs

    def log(self, message: str) -> None:
        self.messages.append(str(message))

    def is_busy(self) -> bool:
        return False

    def start_job(self, title, job, on_success) -> None:
        self.jobs.append(title)
        if self.run_jobs:
            on_success(job(self.log))

    def open_settings_tab(self) -> None:
        self.messages.append("settings")

    def open_tsd_tab(self, folder=None) -> None:
        self.messages.append(f"tsd:{folder}")


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class MetadataTabTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.raw = QSettings(
            str(self.folder / "settings.ini"), QSettings.Format.IniFormat
        )
        self.database = self.folder / "katalog.db"
        conn = connect(self.database)
        try:
            initialize(conn)
            save_workspaces(
                conn,
                "test",
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
        finally:
            close_quietly(conn)
        self.raw.setValue("paths/lineage_db", str(self.database))
        self.window = FakeWindow()

    def make_settings(self) -> AppSettings:
        return AppSettings(self.raw)

    def make_tab(self, *, with_tsd: bool = False) -> MetadataTab:
        settings = self.make_settings()
        tsd = TsdTab(self.window, settings=settings) if with_tsd else None
        tab = MetadataTab(self.window, settings=settings, tsd=tsd)
        self.addCleanup(tab.close)
        return tab


class StructureTests(MetadataTabTestCase):
    def test_sub_tabs_are_local_service_tsd(self) -> None:
        tab = self.make_tab(with_tsd=True)
        self.assertEqual(tab.tabs.count(), 3)
        self.assertEqual(
            [tab.tabs.tabText(i) for i in range(3)],
            ["Local", "Power BI Service", "Generate TSD"],
        )
        self.assertEqual(tab.active_tab, TAB_LOCAL)

    def test_legacy_report_source_is_used_once(self) -> None:
        self.raw.setValue(SETTINGS_REPORT_SOURCE_KEY, TAB_SERVICE)
        tab = self.make_tab()
        self.assertEqual(tab.active_tab, TAB_SERVICE)

    def test_active_tab_is_persisted(self) -> None:
        tab = self.make_tab(with_tsd=True)
        tab.tabs.setCurrentIndex(2)
        self.assertEqual(tab.active_tab, TAB_TSD)
        self.assertEqual(self.raw.value(SETTINGS_ACTIVE_TAB_KEY), TAB_TSD)

    def test_show_tsd_selects_sub_tab_and_sets_workbooks(self) -> None:
        (self.folder / "Report_Metadata.xlsx").write_bytes(b"x")
        (self.folder / "Semantic_Model_Metadata.xlsx").write_bytes(b"x")
        tab = self.make_tab(with_tsd=True)
        tab.show_tsd(self.folder)
        tsd = tab._tsd
        self.assertEqual(tab.active_tab, TAB_TSD)
        self.assertEqual(
            Path(tsd.report_workbook.text()), self.folder / "Report_Metadata.xlsx"
        )
        self.assertEqual(
            Path(tsd.model_workbook.text()),
            self.folder / "Semantic_Model_Metadata.xlsx",
        )

    def test_scope_has_no_validation_or_usage_checkboxes(self) -> None:
        tab = self.make_tab()
        for widget in (tab.local_tab, tab.service_tab):
            self.assertFalse(hasattr(widget, "validate_existing"))
            self.assertFalse(hasattr(widget, "with_report"))


class LocalTabTests(MetadataTabTestCase):
    def test_semantic_model_has_no_manual_endpoint(self) -> None:
        tab = self.make_tab()
        local = tab.local_tab
        self.assertFalse(hasattr(local, "source"))
        self.assertFalse(hasattr(local, "endpoint"))
        self.assertFalse(hasattr(local, "catalog"))

    def test_section_order_starts_with_scope(self) -> None:
        tab = self.make_tab()
        local = tab.local_tab
        layout = local.content.layout()
        order = [
            layout.indexOf(widget)
            for widget in (
                local.scope_box,
                local.model_box,
                local.source_box,
                local.output_box,
                local.run_button,
            )
        ]
        self.assertEqual(order, sorted(order))
        self.assertGreater(order[0], -1)

    def test_model_target_uses_selected_instance(self) -> None:
        tab = self.make_tab()
        tab.local_tab.vm.apply_instances(
            [
                SimpleNamespace(
                    label="Uji.pbix - localhost:111",
                    catalog="Model A",
                    port=111,
                    file_name="Uji",
                )
            ]
        )
        self.assertEqual(tab.local_tab.vm.model_target(), (None, "Model A", 111))

    def test_run_uses_default_validation_and_usage(self) -> None:
        window = FakeWindow(run_jobs=True)
        tab = MetadataTab(window, settings=self.make_settings())
        self.addCleanup(tab.close)
        local = tab.local_tab
        local.vm._info = SimpleNamespace(has_pbir=True, has_local_model=True)
        captured: dict = {}
        with patch(
            "app.viewmodels.metadata.run_metadata_job",
            side_effect=lambda **kwargs: captured.update(kwargs) or {"ok": True},
        ), patch.object(local.vm, "apply_result"):
            local.vm.submit()
        self.assertTrue(captured["validate_with_existing"])
        self.assertTrue(captured["include_report_usage"])

    def test_pbix_field_starts_empty(self) -> None:
        tab = self.make_tab()

        self.assertEqual(tab.local_tab.vm.pbix_text, "")
        self.assertEqual(
            tab.local_tab.kind_label.text(), "Pilih file .pbix sumber."
        )
        self.assertFalse(tab.local_tab.run_button.isEnabled())

    def test_default_out_dir_is_outputs(self) -> None:
        tab = self.make_tab()

        self.assertEqual(tab.local_tab.vm.out_dir, outputs_dir())

    def test_instance_picker_is_enabled_before_pbix_is_chosen(self) -> None:
        tab = self.make_tab()

        self.assertTrue(tab.local_tab.instance.isEnabled())
        self.assertTrue(tab.local_tab.refresh_button.isEnabled())

    def test_missing_pbix_disables_run(self) -> None:
        tab = self.make_tab()
        tab.local_tab.pbix.edit.setText(str(self.folder / "hilang.pbix"))
        tab.local_tab.vm.detect_source()
        self.assertIn("File tidak ditemukan", tab.local_tab.kind_label.text())
        self.assertFalse(tab.local_tab.run_button.isEnabled())

    def test_scope_is_saved_per_sub_tab(self) -> None:
        tab = self.make_tab()
        local = tab.local_tab
        index = local.scope.findData(SCOPE_MODEL)
        local.scope.setCurrentIndex(index)
        self.assertEqual(self.raw.value(SETTINGS_SCOPE_LOCAL_KEY), SCOPE_MODEL)
        self.assertIsNone(self.raw.value(SETTINGS_SCOPE_KEY))
        self.assertEqual(local.vm.scope, SCOPE_MODEL)


class ServiceTabTests(MetadataTabTestCase):
    API_PATCHES = (
        "core.lineage_api.PowerBILineageClient.datasets_in_group",
        "core.lineage_api.PowerBILineageClient.reports_in_group",
    )

    def make_service_tab(
        self, *, principal: bool = True, run_jobs: bool = True
    ) -> tuple[MetadataTab, FakeWindow]:
        settings = self.make_settings()
        if principal:
            settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        window = FakeWindow(run_jobs=run_jobs)
        tab = MetadataTab(window, settings=settings)
        self.addCleanup(tab.close)
        return tab, window

    def load_api(self):
        return (
            patch(self.API_PATCHES[0], return_value=DATASETS),
            patch(self.API_PATCHES[1], return_value=REPORTS),
        )

    @staticmethod
    def select_workspace(service, name: str = WORKSPACE_NAME) -> None:
        labels = service.vm.build_state().workspaces
        index = next(
            position for position, label in enumerate(labels) if label.startswith(f"{name} (")
        )
        service.workspace.setCurrentIndex(index)

    def test_workspace_picker_derives_endpoint_and_loads_lists(self) -> None:
        tab, _ = self.make_service_tab()
        service = tab.service_tab
        datasets_patch, reports_patch = self.load_api()
        with datasets_patch, reports_patch:
            self.select_workspace(service)

        self.assertEqual(service.vm.workspace_id, WORKSPACE)
        self.assertEqual(
            service.vm.endpoint,
            "powerbi://api.powerbi.com/v1.0/myorg/Contoh%20-%20SO",
        )
        self.assertTrue(service.endpoint.isReadOnly())
        self.assertEqual(service.catalog.count(), 1)
        self.assertEqual(service.report.count(), 1)

    def test_report_selection_fills_catalog_and_enables_run(self) -> None:
        tab, _ = self.make_service_tab()
        service = tab.service_tab
        datasets_patch, reports_patch = self.load_api()
        with datasets_patch, reports_patch:
            self.select_workspace(service)
            service.report.setCurrentIndex(0)

        self.assertEqual(service.vm.catalog, "Model A")
        self.assertTrue(service.run_button.isEnabled())

    def test_saved_selection_is_restored(self) -> None:
        self.raw.setValue("extraction/service_workspace_id", WORKSPACE)
        self.raw.setValue("extraction/service_report_id", REPORT)
        tab, _ = self.make_service_tab()
        service = tab.service_tab
        datasets_patch, reports_patch = self.load_api()
        with datasets_patch, reports_patch:
            service.vm.reload_workspaces()

        self.assertEqual(service.vm.workspace_id, WORKSPACE)
        self.assertEqual(service.vm.report_id, REPORT)
        self.assertEqual(service.report.currentIndex(), 0)

    def test_missing_credentials_disables_run(self) -> None:
        tab, _ = self.make_service_tab(principal=False)
        service = tab.service_tab
        service.workspace.setCurrentIndex(0)
        state = service.vm.build_state()

        self.assertFalse(service.run_button.isEnabled())
        self.assertTrue(state.credentials_missing)
        self.assertEqual(
            state.missing_credentials,
            ("TENANT_ID", "CLIENT_ID", "CLIENT_SECRET"),
        )

    def test_credentials_warning_shown_once_per_session(self) -> None:
        tab, window = self.make_service_tab(principal=False)
        service = tab.service_tab
        with patch.object(service, "_warn_credentials", return_value=True) as warn:
            service._maybe_warn_credentials()
            service._maybe_warn_credentials()

        self.assertEqual(warn.call_count, 1)
        self.assertEqual(window.messages.count("settings"), 1)

    def test_credentials_warning_is_rearmed_when_credentials_change(self) -> None:
        settings = self.make_settings()
        window = FakeWindow(run_jobs=False)
        tab = MetadataTab(window, settings=settings)
        self.addCleanup(tab.close)
        service = tab.service_tab

        with patch.object(service, "_warn_credentials", return_value=False) as warn:
            service._maybe_warn_credentials()
            self.assertEqual(warn.call_count, 1)

            settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
            service._maybe_warn_credentials()
            self.assertEqual(warn.call_count, 1)

            settings.set_principal(ServicePrincipal.from_values("", "", ""))
            service._maybe_warn_credentials()
            self.assertEqual(warn.call_count, 2)

    def test_model_only_disables_report_inputs(self) -> None:
        tab, _ = self.make_service_tab()
        service = tab.service_tab
        service.scope.setCurrentIndex(service.scope.findData(SCOPE_MODEL))

        self.assertFalse(service.report.isEnabled())
        self.assertFalse(service.report_note.isHidden())
        self.assertTrue(service.workspace.isEnabled())
        self.assertEqual(self.raw.value(SETTINGS_SCOPE_SERVICE_KEY), SCOPE_MODEL)

    def test_semantic_model_has_workspace_picker(self) -> None:
        tab, _ = self.make_service_tab()
        service = tab.service_tab
        for name in ("source", "instance", "refresh_button", "service_url"):
            self.assertFalse(hasattr(service, name))
        for name in ("workspace", "endpoint", "catalog"):
            self.assertTrue(hasattr(service, name))
        self.assertTrue(service.endpoint.isReadOnly())
        self.assertIn("XMLA", service.endpoint.toolTip())
        self.assertIn("dataset", service.catalog.toolTip())
        self.assertTrue(hasattr(service, "settings_button"))

    def test_empty_catalog_shows_settings_shortcut(self) -> None:
        settings = self.make_settings()
        settings.set_lineage_db(self.folder / "kosong.db")
        tab = MetadataTab(self.window, settings=settings)
        self.addCleanup(tab.close)
        service = tab.service_tab

        self.assertFalse(service.settings_button.isHidden())
        service.settings_button.click()
        self.assertIn("settings", self.window.messages)

    def test_section_order_matches_local(self) -> None:
        tab = self.make_tab()
        service = tab.service_tab
        layout = service.content.layout()
        order = [
            layout.indexOf(widget)
            for widget in (
                service.scope_box,
                service.model_box,
                service.source_box,
                service.output_box,
                service.run_button,
            )
        ]
        self.assertEqual(order, sorted(order))
        self.assertGreater(order[0], -1)

    def test_model_requires_catalog_from_workspace(self) -> None:
        tab, _ = self.make_service_tab()
        service = tab.service_tab
        self.assertFalse(service.vm.model_ready())
        datasets_patch, reports_patch = self.load_api()
        with datasets_patch, reports_patch:
            self.select_workspace(service)
            self.assertFalse(service.vm.model_ready())
            service.catalog.setCurrentIndex(0)

        self.assertTrue(service.vm.model_ready())
        self.assertEqual(
            service.vm.endpoint,
            "powerbi://api.powerbi.com/v1.0/myorg/Contoh%20-%20SO",
        )
        self.assertEqual(service.vm.catalog, "Model A")

    def test_run_uses_default_validation_and_usage(self) -> None:
        tab, _ = self.make_service_tab()
        service = tab.service_tab
        datasets_patch, reports_patch = self.load_api()
        with datasets_patch, reports_patch:
            self.select_workspace(service)
            service.report.setCurrentIndex(0)
        captured: dict = {}
        with patch(
            "app.viewmodels.metadata.run_metadata_job",
            side_effect=lambda **kwargs: captured.update(kwargs) or {"ok": True},
        ), patch.object(service.vm, "apply_result"):
            service.vm.submit()
        self.assertTrue(captured["validate_with_existing"])
        self.assertTrue(captured["include_report_usage"])

    def test_default_scope_is_both(self) -> None:
        tab = self.make_tab()
        self.assertEqual(tab.service_tab.vm.scope, SCOPE_BOTH)


class TsdTabTests(MetadataTabTestCase):
    def make_tsd(self, *, settings: AppSettings | None = None) -> TsdTab:
        tab = TsdTab(self.window, settings=settings or self.make_settings())
        self.addCleanup(tab.close)
        return tab

    @staticmethod
    def index_of(combo, name: str) -> int:
        return next(
            index
            for index in range(combo.count())
            if combo.itemText(index).startswith(f"{name} (")
        )

    def test_document_sections_are_json_only(self) -> None:
        tsd = self.make_tsd()

        for name in (
            "workspace",
            "folder",
            "subtitle",
            "prepared_for",
            "navigation",
            "author_name",
            "author_role",
            "author_date",
            "authorizer_name",
            "authorizer_role",
            "authorizer_date",
            "overview",
            "insight",
        ):
            self.assertFalse(hasattr(tsd, name), name)
        self.assertTrue(hasattr(tsd, "report_name"))

    def test_collect_manual_preserves_sidecar_sections(self) -> None:
        tsd = self.make_tsd()
        tsd.vm._manual_data = {
            "meta": {"draft": False, "expand_all": False},
            "document": {
                "subtitle": "Subjudul",
                "prepared_for": "Tim BI",
                "author": {"name": "Ani", "role": "Analyst", "date": "2026-01-02"},
                "authorizer": {"name": "Budi", "role": "Lead", "date": "2026-01-03"},
            },
            "report": {
                "name": "Uji",
                "workspace": "Contoh - SO",
                "folder": "Folder",
                "navigation_menu": "Menu",
                "overview": "Ringkasan",
                "insight": ["Satu", "Dua"],
            },
        }
        tsd.draft.setChecked(True)
        tsd.report_name.setText("Report Baru")

        manual = tsd._collect_manual()

        self.assertTrue(manual["meta"]["draft"])
        self.assertEqual(manual["report"]["name"], "Report Baru")
        self.assertEqual(manual["report"]["overview"], "Ringkasan")
        self.assertEqual(manual["report"]["insight"], ["Satu", "Dua"])
        self.assertEqual(manual["report"]["workspace"], "Contoh - SO")
        self.assertEqual(manual["document"]["subtitle"], "Subjudul")
        self.assertEqual(manual["document"]["author"]["name"], "Ani")
        self.assertEqual(manual["document"]["authorizer"]["role"], "Lead")

        tsd.report_name.setText("")
        manual = tsd._collect_manual()
        self.assertEqual(manual["report"]["name"], "Uji")

    def test_screenshot_section_uses_workspace_picker(self) -> None:
        tsd = self.make_tsd()

        for name in ("workspace_id", "service_report_id"):
            self.assertFalse(hasattr(tsd, name))
        for name in ("shot_workspace", "shot_report", "shot_mobile"):
            self.assertTrue(hasattr(tsd, name))
        self.assertTrue(tsd.shot_mobile.isChecked())
        self.assertEqual(tsd.shot_workspace.count(), 2)
        self.assertEqual(tsd.shot_report.count(), 0)
        self.assertFalse(tsd.shot_workspace.isEnabled())
        self.assertFalse(tsd.shot_report.isEnabled())
        self.assertFalse(hasattr(tsd, "shot_note"))
        self.assertIn("service principal", tsd.screenshots.toolTip())

        tsd.screenshots.setChecked(True)
        self.assertTrue(tsd.shot_workspace.isEnabled())
        self.assertFalse(tsd.shot_report.isEnabled())

    def test_selecting_workspace_requests_reports(self) -> None:
        self.raw.setValue("auth/tenant_id", "t")
        self.raw.setValue("auth/client_id", "c")
        self.raw.setValue("auth/client_secret", "s")
        tsd = self.make_tsd()
        tsd.screenshots.setChecked(True)

        tsd.shot_workspace.setCurrentIndex(self.index_of(tsd.shot_workspace, WORKSPACE_NAME))

        self.assertEqual(tsd.vm.form.workspace_id, WORKSPACE)
        self.assertEqual(self.raw.value("tsd/workspace_id"), WORKSPACE)
        self.assertIn("Membaca report workspace", self.window.jobs)
        self.assertTrue(tsd.shot_report.isEnabled())

    def test_empty_catalog_shows_settings_shortcut(self) -> None:
        settings = self.make_settings()
        settings.set_lineage_db(self.folder / "kosong.db")
        tsd = self.make_tsd(settings=settings)

        self.assertFalse(tsd.shot_workspace_hint.isHidden())
        self.assertIn("Belum ada workspace", tsd.shot_workspace_hint.text())
        self.assertFalse(tsd.settings_button.isHidden())
        tsd.settings_button.click()
        self.assertIn("settings", self.window.messages)


class SettingsTabTests(MetadataTabTestCase):
    def test_catalog_sync_section_is_wired(self) -> None:
        from app.settings_tab import SettingsTab

        tab = SettingsTab(self.window, settings=self.make_settings())
        self.addCleanup(tab.close)

        self.assertEqual(tab.catalog_mode.count(), 3)
        self.assertIn("katalog", tab.catalog_button.text().lower())
        self.assertIn("lineage", tab.scan_button.text().lower())
        self.assertIn("workspace siap dipilih", tab.sync_status.text())

        tab.catalog_mode.setCurrentIndex(2)
        self.assertEqual(self.raw.value(SETTINGS_CATALOG_MODE_KEY), "member")
        tab.full_scan.setChecked(True)
        self.assertTrue(tab.vm.build_state().full_scan)
        self.assertIn("personal", tab.include_personal.text().lower())
        tab.include_personal.setChecked(True)
        self.assertTrue(tab.vm.build_state().include_personal)
        self.assertTrue(
            self.raw.value("catalog/include_personal", False, type=bool)
        )

    def test_two_sub_tabs_hold_their_sections(self) -> None:
        from app.settings_tab import SettingsTab

        tab = SettingsTab(self.window, settings=self.make_settings())
        self.addCleanup(tab.close)

        self.assertEqual(
            [tab.tabs.tabText(i) for i in range(tab.tabs.count())],
            ["Kredensial", "Katalog & Database"],
        )
        credentials, catalog = tab.tabs.widget(0), tab.tabs.widget(1)
        for name in ("tenant", "client", "secret", "status", "save_button",
                     "test_button", "rls_username", "rls_roles"):
            self.assertTrue(credentials.isAncestorOf(getattr(tab, name)), name)
        for name in (
            "db_path",
            "catalog_mode",
            "full_scan",
            "include_personal",
            "catalog_button",
            "scan_button",
            "sync_status",
        ):
            self.assertTrue(catalog.isAncestorOf(getattr(tab, name)), name)
        self.assertFalse(credentials.isAncestorOf(tab.catalog_mode))

    def test_sub_tab_choice_is_remembered(self) -> None:
        from app.settings_tab import SettingsTab

        settings = self.make_settings()
        tab = SettingsTab(self.window, settings=settings)
        self.addCleanup(tab.close)
        self.assertEqual(tab.active_sub_tab, "credentials")

        tab.tabs.setCurrentIndex(1)
        self.assertEqual(tab.active_sub_tab, "catalog")
        self.assertEqual(self.raw.value(SETTINGS_SUB_TAB_KEY), "catalog")

        again = SettingsTab(self.window, settings=settings)
        self.addCleanup(again.close)
        self.assertEqual(again.active_sub_tab, "catalog")


class MainWindowTests(MetadataTabTestCase):
    def test_top_level_tabs_and_tsd_shortcut(self) -> None:
        from app.main_window import MainWindow

        with patch("app.main_window.MetadataTab.refresh_instances"):
            window = MainWindow(settings=self.make_settings())
        self.addCleanup(window.close)
        self.assertEqual(
            [window.tabs.tabText(i) for i in range(window.tabs.count())],
            [
            "Metadata & TSD",
            "Analisa Semantic Model",
            "Lineage",
            "Pengaturan",
        ],
        )
        self.assertEqual(window.extraction_tab.tabs.count(), 3)

        window.open_tsd_tab(self.folder)
        self.assertIs(window.tabs.currentWidget(), window.extraction_tab)
        self.assertEqual(window.extraction_tab.active_tab, TAB_TSD)


class BusyAndInstanceTests(MetadataTabTestCase):
    def test_busy_disables_both_run_buttons(self) -> None:
        tab = self.make_tab(with_tsd=True)
        tab.set_busy(True)
        self.assertFalse(tab.local_tab.run_button.isEnabled())
        self.assertFalse(tab.service_tab.run_button.isEnabled())
        self.assertFalse(tab._tsd.run_button.isEnabled())
        tab.set_busy(False)
        self.assertFalse(tab.local_tab.run_button.isEnabled())  # pbix tidak ada

    def test_instances_only_reach_local_tab(self) -> None:
        tab = self.make_tab()
        instances = [
            SimpleNamespace(
                label="Uji.pbix - localhost:111",
                catalog="Model A",
                port=111,
                file_name="Uji",
            ),
            SimpleNamespace(
                label="Lain.pbix - localhost:222",
                catalog="Model B",
                port=222,
                file_name="Lain",
            ),
        ]
        tab.local_tab.vm.apply_instances(instances)
        self.assertEqual(tab.local_tab.instance.count(), 3)  # + placeholder
        self.assertEqual(tab.local_tab.instance.currentIndex(), 0)
        self.assertFalse(hasattr(tab.service_tab, "instance"))

    def test_refresh_instances_goes_through_one_job(self) -> None:
        tab = self.make_tab()
        tab.refresh_instances()
        self.assertEqual(self.window.jobs, ["Membaca instance Power BI Desktop"])



class AnalysisTabTests(MetadataTabTestCase):
    class FakeRunner:
        def submit(self, title, job, on_success=None):
            return False

    def make_window(self):
        window = SimpleNamespace(
            messages=[],
            runner=self.FakeRunner(),
            log=lambda message: window.messages.append(str(message)),
            open_settings_tab=lambda: window.messages.append("settings"),
        )
        return window

    def make_tab(self):
        from app.analysis_tab import AnalysisTab

        tab = AnalysisTab(self.make_window(), settings=self.make_settings())
        self.addCleanup(tab.close)
        return tab

    def test_tree_columns_match_design(self) -> None:
        from app.analysis_tab import HEADERS

        tab = self.make_tab()

        self.assertEqual(tab.tree.columnCount(), len(HEADERS))
        self.assertEqual(
            [tab.tree.headerItem().text(i) for i in range(len(HEADERS))],
            list(HEADERS),
        )
        self.assertIn("Name", HEADERS)
        self.assertIn("Status", HEADERS)
        self.assertIn("Display folder", HEADERS)

    def test_personal_checkbox_is_wired(self) -> None:
        from app.settings import SETTINGS_ANALYSIS_PERSONAL_KEY

        tab = self.make_tab()
        self.assertFalse(tab.include_personal.isChecked())
        tab.include_personal.setChecked(True)

        self.assertTrue(
            self.raw.value(SETTINGS_ANALYSIS_PERSONAL_KEY, type=bool)
        )

    def test_object_filter_combo_is_wired(self) -> None:
        from app.settings import SETTINGS_ANALYSIS_OBJECT_FILTER_KEY

        tab = self.make_tab()
        self.assertEqual(tab.object_filter.count(), 3)
        self.assertEqual(tab.object_filter.itemData(0), "all")

        tab.object_filter.setCurrentIndex(2)

        self.assertEqual(
            self.raw.value(SETTINGS_ANALYSIS_OBJECT_FILTER_KEY), "measures"
        )

    def test_unused_filter_persists(self) -> None:
        from app.settings import SETTINGS_ANALYSIS_UNUSED_ONLY_KEY

        tab = self.make_tab()
        tab.unused_only.setChecked(True)

        self.assertTrue(self.raw.value(SETTINGS_ANALYSIS_UNUSED_ONLY_KEY, type=bool))

    def test_result_renders_groups_and_enables_export(self) -> None:
        from tests.test_viewmodels_analysis import make_result

        tab = self.make_tab()
        tab.vm.apply_result(make_result())

        self.assertEqual(tab.tree.topLevelItemCount(), 3)
        self.assertTrue(tab.export_button.isEnabled())
        items = {
            tab.tree.topLevelItem(i).text(0): tab.tree.topLevelItem(i)
            for i in range(tab.tree.topLevelItemCount())
        }
        customer = items["Customer"]
        self.assertIn("Qty", items)
        labels = [customer.child(i).text(0) for i in range(customer.childCount())]
        self.assertTrue(any(label.startswith("Used in visuals") for label in labels))

    def test_header_is_clickable(self) -> None:
        tab = self.make_tab()

        # Regression: QTreeView.setSortingEnabled(False) mematikan lagi
        # sectionsClickable jika dipanggil setelah setSectionsClickable(True).
        self.assertTrue(tab.tree.header().sectionsClickable())
        self.assertFalse(tab.tree.isSortingEnabled())

    def test_busy_keeps_result_table_usable(self) -> None:
        from tests.test_viewmodels_analysis import make_result

        tab = self.make_tab()
        tab.vm.apply_result(make_result())

        tab.set_busy(True)

        self.assertTrue(tab.tree.isEnabled())
        self.assertTrue(tab.search.isEnabled())
        self.assertTrue(tab.object_filter.isEnabled())
        self.assertFalse(tab.analyze_button.isEnabled())

    def test_header_click_sorts_tree(self) -> None:
        from tests.test_viewmodels_analysis import make_result

        tab = self.make_tab()
        tab.vm.apply_result(make_result())
        self.assertFalse(tab.tree.header().isSortIndicatorShown())

        tab.tree.header().sectionClicked.emit(0)  # Name

        self.assertEqual(tab.vm.build_state().sort_column, "name")
        self.assertEqual(tab.tree.header().sortIndicatorSection(), 0)
        self.assertEqual(
            [tab.tree.topLevelItem(i).text(0) for i in range(3)],
            ["Customer", "Qty", "Total"],
        )

    def test_analyze_button_requires_selection(self) -> None:
        tab = self.make_tab()

        self.assertFalse(tab.analyze_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
