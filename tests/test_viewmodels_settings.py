"""Uji view model Pengaturan: muat, simpan, tes koneksi, status."""

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
    from core.auth import FABRIC_SCOPE, POWERBI_SCOPE, ServicePrincipal
    from core.catalog_sync import WorkspaceSyncResult
    from core.errors import ExtractionError
    from core.lineage_store import (
        close_quietly,
        connect,
        initialize,
        save_workspace_sync_run,
        save_workspaces,
    )

    from app.settings import SETTINGS_CATALOG_MODE_KEY
    from app.settings_store import AppSettings
    from app.viewmodels.settings import SettingsViewModel


class FakeRunner:
    def __init__(self, *, accept: bool = True) -> None:
        self.calls: list[tuple] = []
        self.accept = accept

    def submit(self, title, job, on_success=None) -> bool:
        self.calls.append((title, job, on_success))
        return self.accept


class FakeTokens:
    def __init__(self, principal) -> None:
        self.principal = principal
        self.scopes: list[str] = []

    def get(self, scope):
        self.scopes.append(scope)
        return SimpleNamespace(value="token")


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class SettingsViewModelTests(unittest.TestCase):
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

    def make(self) -> SettingsViewModel:
        return SettingsViewModel(self.settings, self.runner)

    def seed(self) -> None:
        self.settings.set_principal(
            ServicePrincipal.from_values("tenant", "client", "secret")
        )
        self.settings.set_rls("default@user", "HO,Region")
        self.settings.set_lineage_db(self.folder / "lineage.db")

    # -- muat --------------------------------------------------------------
    def test_initial_state_reads_settings(self) -> None:
        self.seed()
        state = self.make().build_state()

        self.assertEqual(
            (state.tenant_id, state.client_id, state.client_secret),
            ("tenant", "client", "secret"),
        )
        self.assertEqual((state.rls_username, state.rls_roles), ("default@user", "HO,Region"))
        self.assertTrue(state.database.endswith("lineage.db"))
        self.assertIn("lengkap", state.status_text)

    def test_empty_settings_report_missing_fields(self) -> None:
        state = self.make().build_state()

        self.assertIn("belum lengkap", state.status_text)
        self.assertIn("TENANT_ID", state.status_text)

    def test_external_settings_change_reloads_fields(self) -> None:
        vm = self.make()
        self.settings.set_principal(
            ServicePrincipal.from_values("t2", "c2", "s2")
        )

        state = vm.build_state()

        self.assertEqual(state.tenant_id, "t2")
        self.assertEqual(state.client_id, "c2")

    # -- simpan ------------------------------------------------------------
    def test_save_incomplete_returns_false_and_keeps_settings(self) -> None:
        vm = self.make()
        vm.apply(tenant_id="tenant", client_id="client")
        logs: list[str] = []
        vm.log.connect(logs.append)

        self.assertFalse(vm.save())

        state = vm.build_state()
        self.assertIn("Lengkapi kolom berikut", state.status_text)
        self.assertIn("CLIENT_SECRET", state.status_text)
        self.assertFalse(self.settings.principal().is_complete)
        self.assertEqual(logs, [])

    def test_save_persists_principal_rls_and_path(self) -> None:
        vm = self.make()
        vm.apply(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            rls_username="run@user",
            rls_roles="HO, Region",
            database=str(self.folder / "baru.db"),
        )
        logs: list[str] = []
        vm.log.connect(logs.append)

        self.assertTrue(vm.save())

        self.assertEqual(
            self.settings.principal(),
            ServicePrincipal.from_values("tenant", "client", "secret"),
        )
        self.assertEqual(self.settings.rls(), ("run@user", ("HO", "Region")))
        self.assertTrue(self.settings.lineage_db().endswith("baru.db"))
        self.assertTrue(any("disimpan" in line for line in logs))
        self.assertIn("lengkap", vm.build_state().status_text)

    def test_save_uses_edited_values_despite_reload(self) -> None:
        self.seed()
        vm = self.make()
        vm.apply(rls_username="baru@user", rls_roles="Region", database=str(self.folder / "x.db"))

        vm.save()

        self.assertEqual(self.settings.rls(), ("baru@user", ("Region",)))
        self.assertTrue(self.settings.lineage_db().endswith("x.db"))

    # -- tes koneksi -------------------------------------------------------
    def test_test_connection_requires_complete_principal(self) -> None:
        vm = self.make()

        self.assertFalse(vm.test_connection())
        self.assertEqual(self.runner.calls, [])

    def test_test_connection_submits_job_and_shows_success(self) -> None:
        self.seed()
        vm = self.make()
        logs: list[str] = []
        instances: list[FakeTokens] = []

        def factory(principal):
            tokens = FakeTokens(principal)
            instances.append(tokens)
            return tokens

        with patch("app.viewmodels.settings.EntraTokens", factory):
            self.assertTrue(vm.test_connection())
            title, job, on_success = self.runner.calls[0]
            self.assertEqual(title, "Tes koneksi Power BI")
            self.assertEqual(job(logs.append), "ok")
            on_success("ok")

        self.assertEqual(logs[0], "Mengambil token Fabric dan Power BI...")
        self.assertIn("Token Fabric OK.", logs)
        self.assertEqual(instances[0].scopes, [FABRIC_SCOPE, POWERBI_SCOPE])
        self.assertIn("Tes koneksi berhasil", vm.build_state().status_text)

    # -- katalog workspace -------------------------------------------------
    def test_catalog_sync_requires_complete_principal(self) -> None:
        vm = self.make()

        self.assertFalse(vm.sync_catalog())
        self.assertEqual(self.runner.calls, [])
        self.assertIn("Lengkapi", vm.build_state().sync_status)

    def test_catalog_sync_submits_job_and_updates_status(self) -> None:
        self.seed()
        vm = self.make()
        result = WorkspaceSyncResult(
            database=Path(self.settings.lineage_db()),
            sync_id="ws-1",
            mode="admin",
            workspace_count=3,
            active_count=3,
            added=3,
            updated=0,
            started_at="2026-01-01T00:00:00.0000000Z",
            finished_at="2026-01-01T00:00:02.0000000Z",
            duration_seconds=2.0,
        )

        with patch(
            "app.viewmodels.settings.run_workspace_sync", return_value=result
        ) as sync:
            self.assertTrue(vm.sync_catalog())
            title, job, on_success = self.runner.calls[0]
            self.assertEqual(title, "Sinkronisasi katalog workspace")
            self.assertEqual(job(lambda _message: None), result)
            on_success(result)

        self.assertEqual(sync.call_args.kwargs["mode"], "auto")
        state = vm.build_state()
        self.assertIn("Sinkronisasi katalog selesai", state.sync_status)
        self.assertIn("3 workspace", state.sync_status)
        self.assertIn("admin", state.sync_status)

    def test_catalog_sync_rejected_when_busy(self) -> None:
        self.seed()
        vm = self.make()
        self.runner.accept = False

        self.assertFalse(vm.sync_catalog())
        self.assertIn("masih berjalan", vm.build_state().sync_status)

    def test_catalog_mode_is_persisted_and_validated(self) -> None:
        vm = self.make()
        vm.set_catalog_mode("member")

        self.assertEqual(self.settings.value(SETTINGS_CATALOG_MODE_KEY), "member")
        self.assertEqual(vm.build_state().catalog_mode, "member")
        with self.assertRaises(ExtractionError):
            vm.set_catalog_mode("aneh")

    def test_catalog_status_reads_saved_database(self) -> None:
        database = self.folder / "katalog.db"
        conn = connect(database)
        try:
            initialize(conn)
            save_workspaces(
                conn,
                "s",
                [
                    {"id": "ws-1", "name": "Alpha", "state": "Active", "type": "Workspace"},
                    {"id": "ws-2", "name": "Beta", "state": "Deleted", "type": "Workspace"},
                ],
            )
            save_workspace_sync_run(
                conn,
                "s",
                started_at="2026-11-14T14:36:18.0000000Z",
                finished_at="2026-11-14T14:36:20.0000000Z",
                mode="admin",
                workspace_count=2,
                active_count=1,
                status="Succeeded",
            )
        finally:
            close_quietly(conn)
        self.settings.set_lineage_db(database)

        state = self.make().build_state()

        self.assertIn("1 workspace siap dipilih dari 2", state.sync_status)
        self.assertIn("admin", state.sync_status)
        self.assertIn("2026-11-14 14:36", state.sync_status)

    def test_catalog_status_hints_empty_database(self) -> None:
        self.seed()
        state = self.make().build_state()

        self.assertIn("Belum ada katalog workspace", state.sync_status)

    # -- sinkronisasi lineage ---------------------------------------------
    def test_scan_requires_complete_principal(self) -> None:
        vm = self.make()

        self.assertFalse(vm.run_scan())
        self.assertEqual(self.runner.calls, [])
        self.assertIn("Kredensial", vm.build_state().sync_status)

    def test_scan_submits_mode_full_and_saved_database(self) -> None:
        self.seed()
        vm = self.make()
        result = SimpleNamespace(
            workspace_count=2,
            node_count=6,
            edge_count=9,
            mode="member",
            duration_seconds=1.25,
            unresolved_sources=2,
        )
        vm.set_catalog_mode("member")
        vm.set_full_scan(True)
        self.assertTrue(vm.build_state().full_scan)
        captured: dict = {}
        with patch(
            "app.viewmodels.settings.run_lineage_scan",
            side_effect=lambda database, principal, **kwargs: captured.update(
                database=database, **kwargs
            )
            or result,
        ):
            self.assertTrue(vm.run_scan())
            title, job, on_success = self.runner.calls[0]
            self.assertEqual(title, "Scan lineage Power BI")
            self.assertIs(job(lambda _message: None), result)
            logs: list[str] = []
            vm.log.connect(logs.append)
            on_success(result)

        self.assertEqual(captured["mode"], "member")
        self.assertTrue(captured["full"])
        self.assertEqual(
            Path(captured["database"]).expanduser(),
            Path(self.settings.lineage_db()).expanduser(),
        )
        state = vm.build_state()
        self.assertIn("Scan lineage selesai", state.sync_status)
        self.assertIn("2 workspace", state.sync_status)
        self.assertIn("6 node", state.sync_status)
        self.assertTrue(any("1.2 detik" in line for line in logs))
        self.assertTrue(any("2 sumber feed" in line for line in logs))

    def test_scan_rejected_when_busy(self) -> None:
        self.seed()
        vm = self.make()
        self.runner.accept = False

        self.assertFalse(vm.run_scan())
        self.assertIn("masih berjalan", vm.build_state().sync_status)

    # -- state -------------------------------------------------------------
    def test_apply_clears_feedback(self) -> None:
        vm = self.make()
        vm.apply(tenant_id="tenant", client_id="client")
        vm.save()
        self.assertIn("Lengkapi", vm.build_state().status_text)

        vm.apply(client_secret="secret")

        self.assertNotIn("Lengkapi", vm.build_state().status_text)

    def test_secret_is_not_stripped(self) -> None:
        vm = self.make()
        vm.apply(client_secret="  rahasia  ")
        self.assertEqual(vm.build_state().client_secret, "  rahasia  ")

    def test_busy_disables_actions(self) -> None:
        vm = self.make()
        self.assertTrue(vm.build_state().idle)
        vm.set_busy(True)
        self.assertFalse(vm.build_state().idle)


if __name__ == "__main__":
    unittest.main()
