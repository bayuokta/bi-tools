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

from core.auth import ServicePrincipal
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
        self.app = create_app(
            settings_store=self.store,
            web_root=self.web,
            shutdown=lambda: None,
        )
        self.client = TestClient(self.app)

    def test_settings_hide_secret(self) -> None:
        self.store.set_principal(
            ServicePrincipal("tenant", "client", "sangat-rahasia")
        )
        response = self.client.get("/api/settings")
        body = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["auth"]["tenant_id"], "tenant")
        self.assertTrue(body["auth"]["has_secret"])
        self.assertNotIn("sangat-rahasia", response.text)
        self.assertNotIn("client_secret", body["auth"])

    def test_save_credentials_requires_complete_values(self) -> None:
        response = self.client.put(
            "/api/settings/credentials",
            json={"tenant_id": "t", "client_id": "", "client_secret": "s"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("CLIENT_ID", response.json()["detail"])
        self.assertEqual(self.store.principal().client_secret, "")

    def test_save_credentials_keeps_secret_when_omitted(self) -> None:
        self.client.put(
            "/api/settings/credentials",
            json={"tenant_id": "t", "client_id": "c", "client_secret": "s1"},
        )
        response = self.client.put(
            "/api/settings/credentials",
            json={"tenant_id": "t2", "client_id": "c2"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.store.principal().tenant_id, "t2")
        self.assertEqual(self.store.principal().client_secret, "s1")

    def test_save_rls_accepts_list(self) -> None:
        response = self.client.put(
            "/api/settings/rls", json={"username": "u", "roles": ["HO", "Region"]}
        )
        self.assertEqual(response.json()["rls"]["roles"], "HO,Region")

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

    def test_catalog_mode_validation(self) -> None:
        bad = self.client.put(
            "/api/settings/catalog", json={"mode": "ngawur", "include_personal": False}
        )
        self.assertEqual(bad.status_code, 400)

        good = self.client.put(
            "/api/settings/catalog", json={"mode": "admin", "include_personal": True}
        )
        self.assertEqual(good.status_code, 200)
        self.assertEqual(good.json()["catalog"]["mode"], "admin")
        self.assertTrue(good.json()["catalog"]["include_personal"])

    def test_ui_validation_and_save(self) -> None:
        bad = self.client.put("/api/settings/ui", json={"theme": "neon"})
        self.assertEqual(bad.status_code, 400)
        good = self.client.put(
            "/api/settings/ui", json={"theme": "light", "motion": False}
        )
        self.assertEqual(good.json()["ui"]["theme"], "light")
        self.assertFalse(good.json()["ui"]["motion"])

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

    def test_catalog_sync_job_runs(self) -> None:
        from unittest.mock import patch

        from server.presenters import settings as presenter

        def fake_sync(store, log, cancel):
            log("mulai sinkronisasi uji")
            return {"workspace_count": 3, "mode": "admin"}

        with patch.object(presenter, "sync_catalog_job", fake_sync):
            response = self.client.post("/api/catalog/sync")
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            self.assertTrue(
                wait_until(
                    lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"]
                    != "running"
                )
            )

        body = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["result"]["workspace_count"], 3)
        self.assertIn("mulai sinkronisasi uji", body["log"])

    def test_second_job_is_rejected_while_running(self) -> None:
        import threading
        from unittest.mock import patch

        from server.presenters import settings as presenter

        release = threading.Event()
        started = threading.Event()

        def fake_sync(store, log, cancel):
            started.set()
            release.wait(5)
            return {"workspace_count": 1}

        with patch.object(presenter, "sync_catalog_job", fake_sync):
            first = self.client.post("/api/catalog/sync")
            self.assertTrue(started.wait(5))
            second = self.client.post("/api/catalog/scan", json={"full": False})
            self.assertEqual(second.status_code, 409)
            self.assertIn("masih berjalan", second.json()["detail"])

        self.assertEqual(first.status_code, 202)
        release.set()
        job_id = first.json()["job_id"]
        self.assertTrue(
            wait_until(
                lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"]
                != "running"
            )
        )

    def test_test_token_job_returns_tokens(self) -> None:
        from unittest.mock import patch

        from server.presenters import settings as presenter

        def fake_tokens(store, log, cancel):
            log("token uji")
            return {"tokens": {"fabric": {"ok": True}, "powerbi": {"ok": True}}}

        with patch.object(presenter, "test_token_job", fake_tokens):
            response = self.client.post("/api/settings/test-token")
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            self.assertTrue(
                wait_until(
                    lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"]
                    != "running"
                )
            )

        body = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertTrue(body["result"]["tokens"]["fabric"]["ok"])


if __name__ == "__main__":
    unittest.main()
