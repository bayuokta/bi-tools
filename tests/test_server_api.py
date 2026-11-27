"""Uji endpoint preferensi, katalog, berkas, dan sistem."""

from __future__ import annotations

import tempfile
import time
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated"
)

from fastapi.testclient import TestClient  # noqa: E402

from core.report import MODEL_WORKBOOK_NAME, OUT_FILE
from server import settings as keys
from server.app import create_app
from server.settings_store import SettingsStore


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("<h1>uji</h1>", encoding="utf-8")
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.store.set_shared_db_local(str(self.root / "shared" / "bi_tools.db"))
        self.app = create_app(
            settings_store=self.store,
            web_root=self.web,
            shutdown=lambda: None,
        )
        self.client = TestClient(self.app)

    def test_save_rls_accepts_list(self) -> None:
        response = self.client.put(
            "/api/settings/rls", json={"username": "u", "roles": ["HO", "Region"]}
        )
        self.assertEqual(response.json()["rls"]["roles"], "HO,Region")

    def test_static_assets_disable_browser_cache(self) -> None:
        index = self.client.get("/index.html")
        self.assertEqual(index.status_code, 200)
        self.assertEqual(index.headers.get("cache-control"), "no-store")
        (self.web / "styles.css").write_text("body{}", encoding="utf-8")
        asset = self.client.get("/styles.css")
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.headers.get("cache-control"), "no-store")

    def test_api_responses_keep_their_headers(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertNotEqual(health.headers.get("cache-control"), "no-store")

    def test_save_paths_rejects_relative(self) -> None:
        response = self.client.put(
            "/api/settings/paths", json={"lineage_db": "data/bi_tools.db"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("absolut", response.json()["detail"])

    def test_save_paths_accepts_absolute_and_empty(self) -> None:
        target = self.root / "lain.db"
        response = self.client.put(
            "/api/settings/paths", json={"lineage_db": str(target)}
        )
        self.assertEqual(response.json()["paths"]["lineage_db"], str(target))

        response = self.client.put("/api/settings/paths", json={"lineage_db": ""})
        self.assertTrue(response.json()["paths"]["lineage_db"].endswith("bi_tools.db"))

    def test_ui_validation_and_save(self) -> None:
        bad = self.client.put("/api/settings/ui", json={"theme": "neon"})
        self.assertEqual(bad.status_code, 400)
        good = self.client.put(
            "/api/settings/ui", json={"theme": "light", "motion": False}
        )
        self.assertEqual(good.json()["ui"]["theme"], "light")
        self.assertFalse(good.json()["ui"]["motion"])

        self.assertEqual(self.client.get("/api/settings").json()["ui"]["language"], "en")
        bad_language = self.client.put("/api/settings/ui", json={"language": "fr"})
        self.assertEqual(bad_language.status_code, 400)
        language = self.client.put("/api/settings/ui", json={"language": "id"})
        self.assertEqual(language.json()["ui"]["language"], "id")

    def test_extraction_scope_and_out_dir(self) -> None:
        bad = self.client.put(
            "/api/settings/extraction", json={"scope_local": "sebagian"}
        )
        self.assertEqual(bad.status_code, 400)

        response = self.client.put(
            "/api/settings/extraction",
            json={"scope_local": "model", "scope_service": "report", "out_dir": str(self.root)},
        )
        body = response.json()["extraction"]
        self.assertEqual(body["scope_local"], "model")
        self.assertEqual(body["scope_service"], "report")
        self.assertEqual(body["out_dir"], str(self.root))

    def test_scope_falls_back_to_legacy_key(self) -> None:
        self.store.set(keys.SETTINGS_SCOPE_KEY, "report")
        body = self.client.get("/api/settings").json()["extraction"]
        self.assertEqual(body["scope_local"], "report")
        self.assertEqual(body["scope_service"], "report")

    def test_catalog_status_without_database(self) -> None:
        self.store.set_lineage_db(self.root / "tidak-ada.db")
        body = self.client.get("/api/catalog/status").json()
        self.assertEqual(body["tone"], "idle")
        self.assertIn("Belum ada katalog", body["text"])

    def test_files_browse_root_and_folder(self) -> None:
        roots = self.client.get("/api/files/browse").json()
        self.assertGreaterEqual(roots["count"], 1)
        self.assertEqual(roots["path"], "")

        folder = self.root / "folder"
        folder.mkdir()
        (folder / "contoh.pbix").write_bytes(b"x")
        (folder / "catatan.txt").write_text("x", encoding="utf-8")

        listing = self.client.get(
            "/api/files/browse", params={"path": str(folder), "kind": "file", "ext": ".pbix"}
        ).json()
        names = [entry["name"] for entry in listing["entries"]]
        self.assertIn("contoh.pbix", names)
        self.assertNotIn("catatan.txt", names)

    def test_files_browse_rejects_missing_folder(self) -> None:
        response = self.client.get(
            "/api/files/browse", params={"path": str(self.root / "tidak-ada")}
        )
        self.assertEqual(response.status_code, 400)

    def test_files_open_missing_file(self) -> None:
        response = self.client.post(
            "/api/files/open", json={"path": str(self.root / "tidak-ada.xlsx")}
        )
        self.assertEqual(response.status_code, 404)

    def test_files_open_rejects_executable(self) -> None:
        target = self.root / "contoh.exe"
        target.write_bytes(b"MZ")
        response = self.client.post("/api/files/open", json={"path": str(target)})
        self.assertEqual(response.status_code, 400)
        self.assertIn("dieksekusi", response.json()["detail"])

    def test_outputs_use_saved_folder(self) -> None:
        target = self.root / "hasil"
        target.mkdir()
        (target / OUT_FILE.name).write_text("x", encoding="utf-8")
        (target / MODEL_WORKBOOK_NAME).write_text("y", encoding="utf-8")
        self.client.put("/api/settings/extraction", json={"out_dir": str(target)})

        body = self.client.get("/api/files/outputs").json()
        self.assertEqual(Path(body["folder"]), target)
        self.assertTrue(body["report"]["exists"])
        self.assertTrue(body["model"]["exists"])
        self.assertGreater(body["report"]["size"], 0)

    def test_system_state(self) -> None:
        body = self.client.get("/api/system/state").json()
        from core.version import __version__

        self.assertEqual(body["version"], __version__)
        self.assertTrue(body["shutdown_available"])
        self.assertEqual(Path(body["settings"]["path"]), self.store.path)



if __name__ == "__main__":
    unittest.main()
