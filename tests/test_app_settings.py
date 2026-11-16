"""Uji AppSettings: migrasi kunci lama, kredensial, RLS, dan sinyal."""

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

from core.auth import ServicePrincipal

if QT_AVAILABLE:
    from app.settings import (
        AUTH_TENANT_KEY,
        LINEAGE_CLIENT_KEY,
        LINEAGE_DB_KEY,
        LINEAGE_SECRET_KEY,
        LINEAGE_TENANT_KEY,
        SETTINGS_ANALYSIS_DATASET_KEY,
        SETTINGS_ANALYSIS_SORT_COLUMN_KEY,
        SETTINGS_INSTANCE_KEY,
        SETTINGS_MIGRATED_KEY,
        SETTINGS_SCOPE_LOCAL_KEY,
        SETTINGS_SERVICE_WORKSPACE_KEY,
        SETTINGS_TSD_REPORT_ID_KEY,
        SETTINGS_TSD_WORKSPACE_KEY,
    )
    from app.settings_store import AppSettings


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class AppSettingsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.raw = QSettings(
            str(Path(self._tmp.name) / "settings.ini"),
            QSettings.Format.IniFormat,
        )

    def settings(self) -> AppSettings:
        return AppSettings(self.raw)


class MigrationTests(AppSettingsTestCase):
    def test_legacy_credentials_are_copied(self) -> None:
        self.raw.setValue(LINEAGE_TENANT_KEY, "legacy-tenant")
        self.raw.setValue(LINEAGE_CLIENT_KEY, "legacy-client")
        self.raw.setValue(LINEAGE_SECRET_KEY, "legacy-secret")
        self.raw.setValue(LINEAGE_DB_KEY, "legacy.db")

        settings = self.settings()

        self.assertEqual(
            (
                settings.principal().tenant_id,
                settings.principal().client_id,
                settings.principal().client_secret,
            ),
            ("legacy-tenant", "legacy-client", "legacy-secret"),
        )
        self.assertEqual(settings.lineage_db(), "legacy.db")
        self.assertTrue(self.raw.value(SETTINGS_MIGRATED_KEY, False, type=bool))

    def test_existing_auth_values_are_not_overwritten(self) -> None:
        self.raw.setValue(AUTH_TENANT_KEY, "new-tenant")
        self.raw.setValue(LINEAGE_TENANT_KEY, "legacy-tenant")

        settings = self.settings()

        self.assertEqual(settings.principal().tenant_id, "new-tenant")

    def test_migration_runs_once(self) -> None:
        self.raw.setValue(LINEAGE_TENANT_KEY, "first")
        self.settings()
        self.raw.setValue(AUTH_TENANT_KEY, "changed")
        self.raw.setValue(LINEAGE_TENANT_KEY, "second")

        settings = self.settings()

        self.assertEqual(settings.principal().tenant_id, "changed")

    def test_no_legacy_keys_is_harmless(self) -> None:
        settings = self.settings()
        self.assertFalse(settings.principal().is_complete)
        self.assertEqual(settings.lineage_db(), "")


class CredentialTests(AppSettingsTestCase):
    def test_principal_roundtrip_emits_auth(self) -> None:
        settings = self.settings()
        groups: list[str] = []
        settings.changed.connect(groups.append)

        settings.set_principal(ServicePrincipal.from_values("t", "c", "s"))

        self.assertEqual(
            (settings.principal().tenant_id, settings.principal().client_id),
            ("t", "c"),
        )
        self.assertEqual(groups, ["auth"])

    def test_rls_roundtrip(self) -> None:
        settings = self.settings()
        settings.set_rls("user@domain.com", "HO,Region")

        username, roles = settings.rls()

        self.assertEqual(username, "user@domain.com")
        self.assertEqual(roles, ("HO", "Region"))

    def test_rls_accepts_tuple(self) -> None:
        settings = self.settings()
        settings.set_rls("u", ("HO", "Region"))
        self.assertEqual(settings.rls(), ("u", ("HO", "Region")))


class PathTests(AppSettingsTestCase):
    def test_lineage_db_roundtrip_emits_paths(self) -> None:
        settings = self.settings()
        groups: list[str] = []
        settings.changed.connect(groups.append)

        settings.set_lineage_db(Path("data") / "bi_tools.db")

        self.assertTrue(settings.lineage_db().endswith("bi_tools.db"))
        self.assertEqual(groups, ["paths"])


class SessionResetTests(AppSettingsTestCase):
    """Pilihan sesi dikosongkan, preferensi (kredensial/cakupan/sort) tetap."""

    def test_reset_session_clears_selection_but_keeps_preferences(self) -> None:
        self.raw.setValue(SETTINGS_SERVICE_WORKSPACE_KEY, "ws-service")
        self.raw.setValue(SETTINGS_TSD_WORKSPACE_KEY, "ws-tsd")
        self.raw.setValue(SETTINGS_TSD_REPORT_ID_KEY, "report-tsd")
        self.raw.setValue(SETTINGS_ANALYSIS_DATASET_KEY, "dataset")
        self.raw.setValue(SETTINGS_INSTANCE_KEY, "51249")
        self.raw.setValue(AUTH_TENANT_KEY, "tenant")
        self.raw.setValue(SETTINGS_SCOPE_LOCAL_KEY, "model")
        self.raw.setValue(SETTINGS_ANALYSIS_SORT_COLUMN_KEY, "size")

        settings = self.settings()
        settings.reset_session()

        for key in (
            SETTINGS_SERVICE_WORKSPACE_KEY,
            SETTINGS_TSD_WORKSPACE_KEY,
            SETTINGS_TSD_REPORT_ID_KEY,
            SETTINGS_ANALYSIS_DATASET_KEY,
            SETTINGS_INSTANCE_KEY,
        ):
            self.assertIsNone(self.raw.value(key), key)
        self.assertEqual(self.raw.value(AUTH_TENANT_KEY), "tenant")
        self.assertEqual(self.raw.value(SETTINGS_SCOPE_LOCAL_KEY), "model")
        self.assertEqual(self.raw.value(SETTINGS_ANALYSIS_SORT_COLUMN_KEY), "size")


class StartupTests(AppSettingsTestCase):
    def test_run_resets_session_before_showing_window(self) -> None:
        with patch("app.main_window.QApplication") as app_cls, patch(
            "app.main_window.AppSettings"
        ) as settings_cls, patch("app.main_window.MainWindow") as window_cls:
            app_cls.instance.return_value = app_cls.return_value
            app_cls.return_value.exec.return_value = 0

            from app.main_window import run

            self.assertEqual(run(), 0)

        settings_cls.return_value.reset_session.assert_called_once()
        window_cls.assert_called_once_with(settings=settings_cls.return_value)


if __name__ == "__main__":
    unittest.main()
