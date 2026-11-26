"""Uji preferensi JSON server: migrasi QSettings, tipe, dan sesi bersih."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from server import settings as keys
from server.settings_store import MIGRATION_FLAG, SettingsStore



class SettingsStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "settings.json"

    def store(self, registry: dict[str, object] | None = None) -> SettingsStore:
        return SettingsStore(
            self.path, registry_reader=lambda: dict(registry or {})
        )

    def test_registry_values_are_migrated_with_types(self) -> None:
        store = self.store(
            {
                "auth/tenant_id": "tenant",
                "auth/client_id": "client",
                "auth/client_secret": "secret",
                "catalog/include_personal": "true",
                "tsd/screenshot_scale": "2",
                "tsd/draft": "false",
                "extraction/scope": "model",
            }
        )

        self.assertEqual(store.get_str(keys.AUTH_TENANT_KEY), "tenant")
        self.assertTrue(store.get_bool(keys.SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY))
        self.assertEqual(store.get_int(keys.SETTINGS_TSD_SHOT_SCALE_KEY), 2)
        self.assertFalse(store.get_bool(keys.SETTINGS_TSD_DRAFT_KEY))
        self.assertTrue(store.get_bool(MIGRATION_FLAG))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertTrue(payload["values"][MIGRATION_FLAG])

    def test_legacy_lineage_keys_fill_new_groups(self) -> None:
        store = self.store(
            {
                "lineage/tenant_id": "t-old",
                "lineage/client_id": "c-old",
                "lineage/client_secret": "s-old",
                "lineage/db_path": r"D:\data\bi_tools.db",
            }
        )

        self.assertEqual(store.get_str(keys.AUTH_TENANT_KEY), "t-old")
        self.assertEqual(store.lineage_db(), r"D:\data\bi_tools.db")

    def test_existing_json_wins_over_registry(self) -> None:
        first = self.store({"auth/tenant_id": "lama"})
        first.set(keys.AUTH_TENANT_KEY, "baru")
        second = self.store({"auth/tenant_id": "registry"})

        self.assertEqual(second.get_str(keys.AUTH_TENANT_KEY), "baru")

    def test_migration_runs_once(self) -> None:
        self.store({"auth/tenant_id": "pertama"})
        second = self.store({"auth/tenant_id": "kedua"})

        self.assertEqual(second.get_str(keys.AUTH_TENANT_KEY), "pertama")

    def test_reset_session_keeps_preferences(self) -> None:
        store = self.store()
        store.set(keys.SETTINGS_SERVICE_WORKSPACE_KEY, "ws")
        store.set(keys.SETTINGS_ANALYSIS_DATASET_KEY, "ds")
        store.set(keys.SETTINGS_SCOPE_LOCAL_KEY, "report")

        store.reset_session()

        self.assertEqual(store.get_str(keys.SETTINGS_SERVICE_WORKSPACE_KEY), "")
        self.assertEqual(store.get_str(keys.SETTINGS_ANALYSIS_DATASET_KEY), "")
        self.assertEqual(store.get_str(keys.SETTINGS_SCOPE_LOCAL_KEY), "report")

    def test_unknown_key_keeps_string(self) -> None:
        store = self.store()
        store.set("custom/value", "teks")
        self.assertEqual(store.get_str("custom/value"), "teks")

    def test_file_created_with_migration_flag(self) -> None:
        store = self.store()
        self.assertTrue(self.path.exists())
        store.set(keys.SETTINGS_UI_THEME_KEY, "light")
        self.assertEqual(store.get_str(keys.SETTINGS_UI_THEME_KEY), "light")
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(payload["values"][MIGRATION_FLAG])

    def test_broken_json_reports_error(self) -> None:
        from server.settings_store import SettingsError

        self.path.write_text("{bukan json", encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.store()

    def test_rls_roles_are_normalized(self) -> None:
        store = self.store()
        store.set_rls("user", ["HO", " Region ", ""])
        self.assertEqual(store.rls(), ("user", ("HO", "Region")))


if __name__ == "__main__":
    unittest.main()
