"""Uji view model metadata Local/Service tanpa widget dan tanpa network."""

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

from core.requests import SCOPE_BOTH, SCOPE_MODEL, SCOPE_REPORT

if QT_AVAILABLE:
    from core.auth import ServicePrincipal
    from core.errors import ExtractionError
    from core.lineage_store import (
        close_quietly,
        connect,
        initialize,
        save_workspaces,
    )

    from app.settings import (
        SETTINGS_INSTANCE_KEY,
        SETTINGS_SCOPE_KEY,
        SETTINGS_SCOPE_SERVICE_KEY,
        SETTINGS_SERVICE_REPORT_KEY,
        SETTINGS_SERVICE_URL_KEY,
        SETTINGS_SERVICE_WORKSPACE_KEY,
    )
    from app.settings_store import AppSettings
    from app.viewmodels.metadata import (
        LocalMetadataViewModel,
        ServiceMetadataViewModel,
    )

WORKSPACE = "44444444-4444-4444-8444-444444444444"
WORKSPACE_NAME = "Contoh - SO"
OTHER_WORKSPACE = "8a5b1c2d-1111-4222-8333-944455556666"
REPORT = "55555555-5555-4555-8555-555555555555"
URL = f"https://app.powerbi.com/groups/{WORKSPACE}/reports/{REPORT}"
ENDPOINT = (
    "powerbi://api.powerbi.com/v1.0/myorg/Contoh%20-%20SO"
)
DATASETS = [{"id": "ds-1", "name": "Uji Model"}]
REPORTS = [
    {
        "id": REPORT,
        "name": "Report Uji",
        "datasetId": "ds-1",
        "reportType": "PowerBIReport",
    }
]


def seed_workspaces(database: Path, rows: list[dict]) -> None:
    conn = connect(database)
    try:
        initialize(conn)
        save_workspaces(conn, "test", rows)
    finally:
        close_quietly(conn)


def contents(workspace_id: str, *, datasets=None, reports=None) -> dict:
    return {
        "workspace_id": workspace_id,
        "datasets": DATASETS if datasets is None else datasets,
        "reports": REPORTS if reports is None else reports,
    }


class FakeRunner:
    def __init__(self, *, accept: bool = True) -> None:
        self.calls: list[tuple] = []
        self.accept = accept

    def submit(self, title, job, on_success=None) -> bool:
        self.calls.append((title, job, on_success))
        return self.accept


def source_info(*, pbir: bool = True, local_model: bool = True):
    return SimpleNamespace(
        label="Lokal",
        has_pbir=pbir,
        has_local_model=local_model,
        is_live_connection=not local_model,
        dataset_id="dataset" if not local_model else "",
    )


def instance(label: str, catalog: str, port: int, stem: str):
    return SimpleNamespace(label=label, catalog=catalog, port=port, file_name=stem)


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class ViewModelCase(unittest.TestCase):
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
        self.database = self.folder / "katalog.db"
        seed_workspaces(
            self.database,
            [
                {"id": WORKSPACE, "name": WORKSPACE_NAME, "state": "Active", "type": "Workspace"},
                {"id": OTHER_WORKSPACE, "name": "Lain", "state": "Active", "type": "Workspace"},
            ],
        )
        self.settings.set_lineage_db(self.database)
        self.runner = FakeRunner()

    def local(self, **kwargs) -> LocalMetadataViewModel:
        return LocalMetadataViewModel(
            self.settings, self.runner, scope_key="extraction/scope_local", **kwargs
        )

    def service(self) -> ServiceMetadataViewModel:
        vm = ServiceMetadataViewModel(
            self.settings, self.runner, scope_key=SETTINGS_SCOPE_SERVICE_KEY
        )
        vm.start()
        return vm

    def workspace_index(
        self, vm: ServiceMetadataViewModel, name: str = WORKSPACE_NAME
    ) -> int:
        """Indeks combo workspace berdasarkan nama (opsi diurutkan per nama)."""
        labels = vm.build_state().workspaces
        return next(
            index for index, label in enumerate(labels) if label.startswith(f"{name} (")
        )

    def ready_service(self) -> ServiceMetadataViewModel:
        """VM dengan workspace, dataset, dan report terpilih (siap dijalankan)."""
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.service()
        vm.select_workspace(self.workspace_index(vm))
        vm.apply_workspace_contents(contents(WORKSPACE))
        vm.select_report(0)
        return vm


class LocalViewModelTests(ViewModelCase):
    def test_automatic_out_dir_follows_pbix(self) -> None:
        pbix = self.folder / "Uji.pbix"
        pbix.write_bytes(b"x")
        with patch(
            "app.viewmodels.metadata.detect_pbix_source",
            return_value=source_info(),
        ):
            vm = self.local(pbix=pbix)

        state = vm.build_state()
        self.assertEqual(vm.out_dir, self.folder)
        self.assertIn("Lokal", state.kind_text)
        self.assertTrue(state.can_run)

    def test_missing_file_disables_run(self) -> None:
        vm = self.local(pbix=self.folder / "hilang.pbix")

        state = vm.build_state()

        self.assertFalse(state.can_run)
        self.assertIn("File tidak ditemukan", state.kind_text)

    def test_report_only_scope_does_not_need_instance(self) -> None:
        pbix = self.folder / "Uji.pbix"
        pbix.write_bytes(b"x")
        with patch(
            "app.viewmodels.metadata.detect_pbix_source",
            return_value=source_info(),
        ):
            vm = self.local(pbix=pbix)
        vm.set_scope(SCOPE_REPORT)

        self.assertTrue(vm.build_state().can_run)
        self.assertEqual(vm.model_target(), (None, None, None))

    def test_two_instances_require_explicit_selection(self) -> None:
        pbix = self.folder / "Uji.pbix"
        pbix.write_bytes(b"x")
        with patch(
            "app.viewmodels.metadata.detect_pbix_source",
            return_value=source_info(),
        ):
            vm = self.local(pbix=pbix)

        vm.apply_instances(
            [
                instance("A.pbix - 1", "Model A", 111, "A"),
                instance("B.pbix - 2", "Model B", 222, "B"),
            ]
        )

        state = vm.build_state()
        self.assertTrue(state.instance_placeholder)
        self.assertIsNone(vm.model_target())
        self.assertFalse(state.can_run)

        vm.select_instance(2)  # melewati baris placeholder
        self.assertEqual(vm.selected_instance.catalog, "Model B")
        self.assertEqual(vm.build_state().instance_index, 2)
        self.assertTrue(vm.build_state().can_run)

    def test_remembered_instance_wins_over_file_name(self) -> None:
        self.settings.set_value(SETTINGS_INSTANCE_KEY, "Model B")
        vm = self.local(pbix=self.folder / "Uji.pbix")

        vm.apply_instances(
            [
                instance("A.pbix - 1", "Model A", 111, "Uji"),
                instance("B.pbix - 2", "Model B", 222, "Lain"),
            ]
        )

        self.assertEqual(vm.selected_instance.catalog, "Model B")
        self.assertEqual(vm.build_state().instance_index, 1)

    def test_prepare_builds_local_request_with_instance(self) -> None:
        pbix = self.folder / "Uji.pbix"
        pbix.write_bytes(b"x")
        with patch(
            "app.viewmodels.metadata.detect_pbix_source",
            return_value=source_info(),
        ):
            vm = self.local(pbix=pbix)
        vm.apply_instances([instance("Uji - 111", "Model A", 111, "Uji")])

        request, runtime = vm.prepare()

        self.assertEqual(runtime, {})
        self.assertEqual(request.scope, SCOPE_BOTH)
        self.assertEqual((request.catalog, request.port), ("Model A", 111))
        self.assertTrue(request.include_usage)
        self.assertEqual(
            (request.extract_report, request.extract_model), (True, True)
        )

    def test_model_scope_without_local_model_is_rejected(self) -> None:
        pbix = self.folder / "Thin.pbix"
        pbix.write_bytes(b"x")
        with patch(
            "app.viewmodels.metadata.detect_pbix_source",
            return_value=source_info(pbir=False, local_model=False),
        ):
            vm = self.local(pbix=pbix)
        vm.set_scope(SCOPE_MODEL)
        logs: list[str] = []
        vm.log.connect(logs.append)

        self.assertIsNone(vm.prepare())
        self.assertTrue(any("model lokal" in line for line in logs))

    def test_open_desktop_allows_run_but_skips_model(self) -> None:
        pbix = self.folder / "Uji.pbix"
        pbix.write_bytes(b"x")
        with patch(
            "app.viewmodels.metadata.detect_pbix_source",
            return_value=source_info(),
        ):
            vm = self.local(pbix=pbix)
        vm.apply_instances([])

        request, _runtime = vm.prepare()

        self.assertIsNone(request.port)
        self.assertIsNone(request.catalog)

    def test_submit_maps_request_to_job_kwargs(self) -> None:
        pbix = self.folder / "Uji.pbix"
        pbix.write_bytes(b"x")
        with patch(
            "app.viewmodels.metadata.detect_pbix_source",
            return_value=source_info(),
        ):
            vm = self.local(pbix=pbix)
        vm.apply_instances([instance("Uji - 111", "Model A", 111, "Uji")])
        captured: dict = {}
        with patch(
            "app.viewmodels.metadata.run_metadata_job",
            side_effect=lambda **kwargs: captured.update(kwargs) or {"ok": True},
        ):
            self.assertTrue(vm.submit())
            _title, job, _on_success = self.runner.calls[0]
            job(lambda _message: None)

        self.assertEqual(captured["port"], 111)
        self.assertEqual(captured["catalog"], "Model A")
        self.assertTrue(captured["extract_model"])
        self.assertTrue(captured["validate_with_existing"])


class ServiceViewModelTests(ViewModelCase):
    def test_saved_selection_is_restored_without_loading(self) -> None:
        self.settings.set_value(SETTINGS_SERVICE_WORKSPACE_KEY, WORKSPACE)
        self.settings.set_value(SETTINGS_SERVICE_REPORT_KEY, REPORT)
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))

        vm = self.service()

        state = vm.build_state()
        self.assertEqual(state.workspace_index, self.workspace_index(vm))
        self.assertEqual(vm.endpoint, ENDPOINT)
        self.assertEqual(vm.report_id, REPORT)
        self.assertEqual(state.reports, ())
        self.assertEqual(self.runner.calls, [])

        vm.select_workspace(self.workspace_index(vm, "Lain"))
        self.assertEqual(vm.report_id, "")

    def test_saved_report_is_restored_when_contents_arrive(self) -> None:
        self.settings.set_value(SETTINGS_SERVICE_WORKSPACE_KEY, WORKSPACE)
        self.settings.set_value(SETTINGS_SERVICE_REPORT_KEY, REPORT)
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.service()

        vm.ensure_contents()
        self.assertEqual(len(self.runner.calls), 1)
        vm.apply_workspace_contents(contents(WORKSPACE))

        self.assertEqual(vm.catalog, "Uji Model")
        self.assertEqual(vm.build_state().report_index, 0)

    def test_legacy_url_is_used_when_new_keys_are_empty(self) -> None:
        self.settings.set_value(SETTINGS_SERVICE_URL_KEY, URL)

        vm = self.service()

        self.assertEqual(vm.workspace_id, WORKSPACE)
        self.assertEqual(vm.report_id, REPORT)
        self.assertEqual(
            vm.build_state().workspace_index, self.workspace_index(vm)
        )

    def test_legacy_url_with_unknown_workspace_shows_hint(self) -> None:
        unknown = "00000000-0000-4000-8000-000000000000"
        self.settings.set_value(
            SETTINGS_SERVICE_URL_KEY,
            f"https://app.powerbi.com/groups/{unknown}/reports/{REPORT}",
        )

        vm = self.service()

        self.assertEqual(vm.workspace_id, unknown)
        self.assertIn("tidak ada di katalog", vm.build_state().workspace_hint)

    def test_select_workspace_derives_endpoint_and_persists(self) -> None:
        vm = self.service()
        vm.select_workspace(self.workspace_index(vm))

        self.assertEqual(vm.endpoint, ENDPOINT)
        self.assertEqual(
            self.settings.value(SETTINGS_SERVICE_WORKSPACE_KEY), WORKSPACE
        )
        self.assertEqual(vm.build_state().workspace_index, self.workspace_index(vm))

    def test_rejected_load_reverts_workspace_choice(self) -> None:
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        self.runner.accept = False
        vm = self.service()
        vm.select_workspace(self.workspace_index(vm, "Lain"))

        state = vm.build_state()
        self.assertEqual(
            (state.workspace_index, vm.workspace_id, vm.endpoint), (-1, "", "")
        )
        self.assertTrue(state.message)

    def test_select_report_sets_catalog_and_persists(self) -> None:
        vm = self.service()
        vm.select_workspace(self.workspace_index(vm))
        vm.apply_workspace_contents(contents(WORKSPACE))
        vm.select_report(0)

        state = vm.build_state()
        self.assertEqual((vm.report_id, vm.catalog), (REPORT, "Uji Model"))
        self.assertEqual(state.dataset_index, 0)
        self.assertEqual(
            self.settings.value(SETTINGS_SERVICE_REPORT_KEY), REPORT
        )
        self.assertIn("Catalog", state.message)

    def test_report_with_external_dataset_shows_hint(self) -> None:
        vm = self.service()
        vm.select_workspace(self.workspace_index(vm))
        vm.apply_workspace_contents(
            {
                "workspace_id": WORKSPACE,
                "datasets": [],
                "reports": [
                    {
                        "id": REPORT,
                        "name": "Report Uji",
                        "datasetId": "dataset-lain",
                        "reportType": "PowerBIReport",
                    }
                ],
            }
        )
        vm.select_report(0)

        self.assertEqual(vm.catalog, "")
        self.assertIn("workspace lain", vm.build_state().message)

    def test_workspace_only_is_not_runnable_without_catalog(self) -> None:
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.service()
        vm.select_workspace(self.workspace_index(vm))

        self.assertFalse(vm.build_state().can_run)
        vm.apply_workspace_contents(contents(WORKSPACE))
        self.assertFalse(vm.build_state().can_run)

        vm.select_report(0)
        self.assertTrue(vm.build_state().can_run)

    def test_scope_change_loads_missing_contents(self) -> None:
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.service()
        vm.set_scope(SCOPE_REPORT)
        vm.select_workspace(self.workspace_index(vm))
        vm.apply_workspace_contents(
            {"workspace_id": WORKSPACE, "datasets": [], "reports": REPORTS}
        )
        self.assertEqual(len(self.runner.calls), 1)

        vm.set_scope(SCOPE_MODEL)
        self.assertEqual(len(self.runner.calls), 2)

    def test_prepare_returns_request_and_token_provider(self) -> None:
        vm = self.ready_service()

        request, runtime = vm.prepare()

        self.assertEqual((request.workspace_id, request.report_id), (WORKSPACE, REPORT))
        self.assertEqual(request.endpoint, ENDPOINT)
        self.assertEqual(request.catalog, "Uji Model")
        self.assertTrue(request.include_usage)
        self.assertIsNotNone(runtime["tokens"])
        self.assertTrue(hasattr(runtime["token_provider"], "get_token"))

    def test_prepare_model_only_skips_report_token(self) -> None:
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.service()
        vm.set_scope(SCOPE_MODEL)
        vm.select_workspace(self.workspace_index(vm))
        vm.apply_workspace_contents(contents(WORKSPACE))

        self.assertIsNone(vm.prepare())
        vm.select_catalog(0)
        request, runtime = vm.prepare()

        self.assertIsNone(request.service_ref)
        self.assertIsNone(runtime["token_provider"])
        self.assertIsNotNone(runtime["tokens"])
        self.assertEqual(request.catalog, "Uji Model")

    def test_paginated_report_is_rejected(self) -> None:
        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        vm = self.service()
        vm.set_scope(SCOPE_REPORT)
        vm.select_workspace(self.workspace_index(vm))
        vm.apply_workspace_contents(
            {
                "workspace_id": WORKSPACE,
                "datasets": [],
                "reports": [
                    {
                        "id": REPORT,
                        "name": "Paginated",
                        "reportType": "PaginatedReport",
                    }
                ],
            }
        )
        logs: list[str] = []
        vm.log.connect(logs.append)
        vm.select_report(0)

        self.assertIsNone(vm.prepare())
        self.assertTrue(any("paginated" in line.lower() for line in logs))
        self.assertIn("[Paginated]", vm.build_state().reports[0])

    def test_missing_credentials_does_not_start_job(self) -> None:
        vm = self.service()
        vm.select_workspace(self.workspace_index(vm))

        state = vm.build_state()
        self.assertIn("Kredensial", state.message)
        self.assertEqual(self.runner.calls, [])

        logs: list[str] = []
        vm.log.connect(logs.append)
        self.assertFalse(vm.submit())
        self.assertEqual(self.runner.calls, [])
        self.assertTrue(any("kredensial" in line for line in logs))

    def test_empty_database_shows_settings_shortcut(self) -> None:
        vm = self.service()
        self.settings.set_lineage_db(self.folder / "kosong.db")

        state = vm.build_state()
        self.assertEqual(state.workspaces, ())
        self.assertTrue(state.workspace_hint)
        self.assertTrue(state.settings_shortcut_visible)

    def test_credentials_state_follows_service_principal(self) -> None:
        vm = self.service()
        state = vm.build_state()
        self.assertTrue(state.credentials_missing)
        self.assertIn("CLIENT_SECRET", state.missing_credentials)

        self.settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))
        state = vm.build_state()
        self.assertFalse(state.credentials_missing)
        self.assertEqual(state.missing_credentials, ())

    def test_model_only_disables_report_inputs(self) -> None:
        vm = self.service()
        vm.set_scope(SCOPE_MODEL)
        state = vm.build_state()

        self.assertTrue(state.report_note_visible)
        self.assertFalse(state.source_active)
        self.assertTrue(state.workspace_active)


class SharedViewModelTests(ViewModelCase):
    def test_scope_is_saved_under_its_own_key(self) -> None:
        vm = self.service()
        vm.set_scope(SCOPE_MODEL)

        self.assertEqual(self.settings.value(SETTINGS_SCOPE_SERVICE_KEY), SCOPE_MODEL)
        self.assertIsNone(self.settings.value(SETTINGS_SCOPE_KEY))

    def test_busy_state_disables_run(self) -> None:
        vm = self.ready_service()
        self.assertTrue(vm.build_state().can_run)

        vm.set_busy(True)
        state = vm.build_state()

        self.assertFalse(state.idle)
        self.assertFalse(state.can_run)
        self.assertFalse(state.model_inputs_active)

    def test_busy_submit_is_rejected(self) -> None:
        vm = self.service()
        vm.set_busy(True)

        self.assertFalse(vm.submit())
        self.assertEqual(self.runner.calls, [])

    def test_legacy_scope_key_is_used_once(self) -> None:
        self.settings.set_value(SETTINGS_SCOPE_KEY, SCOPE_REPORT)
        vm = self.service()

        self.assertEqual(vm.scope, SCOPE_REPORT)

    def test_invalid_saved_scope_falls_back(self) -> None:
        self.settings.set_value(SETTINGS_SCOPE_SERVICE_KEY, "aneh")
        vm = self.service()

        self.assertEqual(vm.scope, SCOPE_BOTH)

    def test_invalid_scope_input_raises(self) -> None:
        vm = self.service()
        with self.assertRaises(ExtractionError):
            vm.set_scope("aneh")


if __name__ == "__main__":
    unittest.main()
