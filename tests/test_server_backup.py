"""Uji presenter/endpoint Backup tanpa Power BI, TOM, atau jaringan."""

from __future__ import annotations

import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated"
)

from fastapi.testclient import TestClient  # noqa: E402

from core.auth import ServicePrincipal  # noqa: E402
from core.lineage_store import connect, initialize, save_workspaces  # noqa: E402
from server.app import create_app  # noqa: E402
from server.presenters import backup as presenter  # noqa: E402
from server.settings_store import SettingsStore  # noqa: E402

WORKSPACE = "11111111-2222-3333-4444-555555555555"
MODEL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
REPORT = "22222222-3333-4444-5555-666666666666"


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.db = self.root / "lineage.db"
        conn = connect(self.db)
        try:
            initialize(conn)
            save_workspaces(
                conn,
                "sync-1",
                [
                    {"id": WORKSPACE, "name": "Data Platform", "state": "Active"},
                    {
                        "id": "33333333-4444-5555-6666-777777777777",
                        "name": "Finance",
                        "state": "Active",
                    },
                ],
            )
        finally:
            conn.close()
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.store.set_lineage_db(self.db)
        self.store.set_shared_db_local(str(self.root / "shared" / "bi_tools.db"))
        self.store.set_principal(ServicePrincipal("t", "c", "s"))
        self.store.set("backup/folder", str(self.root / "backups"))
        self.web = self.root / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("ok", encoding="utf-8")


class StateTests(_StoreCase):
    def test_state_lists_workspaces_and_default_folder(self) -> None:
        data = presenter.build_state(self.store)
        self.assertEqual(len(data["workspaces"]), 2)
        self.assertEqual(data["workspaces"][0]["name"], "Data Platform")
        self.assertTrue(Path(data["folder"]).is_absolute())
        self.assertEqual(data["history"], [])
        self.assertEqual(data["prefix"], "Backup")

    def test_items_are_split_and_sorted(self) -> None:
        payload = {
            "workspace_id": WORKSPACE,
            "datasets": [
                {"id": MODEL, "name": "Sales Model"},
                {"id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff", "name": "Alpha"},
            ],
            "reports": [
                {"id": REPORT, "name": "Overview", "reportType": "PowerBIReport"},
                {
                    "id": "44444444-5555-6666-7777-888888888888",
                    "name": "RDL Report",
                    "reportType": "PaginatedReport",
                },
            ],
        }
        with patch(
            "server.presenters.service_picker.workspace_contents", return_value=payload
        ):
            data = presenter.workspace_items(self.store, WORKSPACE)
        self.assertEqual([row["name"] for row in data["models"]], ["Alpha", "Sales Model"])
        self.assertEqual(
            [row["name"] for row in data["reports"]], ["Overview", "RDL Report"]
        )
        self.assertEqual(len(data["items"]), 4)
        self.assertEqual(data["items"][0]["kind"], "model")


class EndpointTests(_StoreCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = create_app(settings_store=self.store, web_root=self.web)
        self.client = TestClient(self.app)

    def test_state_endpoint(self) -> None:
        response = self.client.get("/api/backup/state")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["workspaces"]), 2)

    def test_items_endpoint_requires_valid_payload(self) -> None:
        payload = {
            "workspace_id": WORKSPACE,
            "datasets": [{"id": MODEL, "name": "Sales"}],
            "reports": [],
        }
        with patch(
            "server.presenters.service_picker.workspace_contents", return_value=payload
        ):
            response = self.client.get(f"/api/backup/workspaces/{WORKSPACE}/items")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["models"][0]["name"], "Sales")

    def test_run_rejects_empty_items(self) -> None:
        response = self.client.post(
            "/api/backup/run",
            json={"workspace_id": WORKSPACE, "items": [], "folder": "C:/backup"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("minimal satu item", response.json()["detail"])

    def test_restore_state_includes_files_and_targets(self) -> None:
        payload = {
            "workspace_id": WORKSPACE,
            "datasets": [{"id": MODEL, "name": "Sales"}],
            "reports": [{"id": REPORT, "name": "Overview"}],
        }
        with patch(
            "server.presenters.service_picker.workspace_contents", return_value=payload
        ):
            response = self.client.get(
                "/api/backup/restore/state",
                params={"folder": str(self.root / "backups"), "workspace_id": WORKSPACE},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("files", body)
        self.assertEqual(body["targets"]["models"][0]["name"], "Sales")
        self.assertEqual(body["targets"]["reports"][0]["name"], "Overview")

    def test_restore_rejects_missing_file(self) -> None:
        response = self.client.post(
            "/api/backup/restore/run",
            json={
                "file": str(self.root / "missing.zip"),
                "workspace_id": WORKSPACE,
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(".zip", response.json()["detail"])

    def test_restore_starts_job(self) -> None:
        import zipfile

        archive = self.root / "backup.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("definition.pbir", "{}")
            handle.writestr("report.json", "{}")

        def fake_restore(store, payload, log, cancel):
            log("restore uji")
            return {"kind": "report", "action": "created", "name": "Overview"}

        body = {
            "file": str(archive),
            "workspace_id": WORKSPACE,
            "workspace_name": "Data Platform",
        }
        with patch.object(presenter, "restore_job", fake_restore):
            response = self.client.post("/api/backup/restore/run", json=body)
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            self.assertTrue(
                wait_until(
                    lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"]
                    != "running"
                )
            )
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["result"]["action"], "created")
        self.assertIn("restore uji", job["log"])

    def test_run_starts_job(self) -> None:
        def fake_job(store, payload, log, cancel, progress=None):
            log("backup uji")
            return {"ok": 1, "items": [], "folder": payload["folder"]}

        body = {
            "workspace_id": WORKSPACE,
            "workspace_name": "Data Platform",
            "items": [{"kind": "report", "id": REPORT, "name": "Overview"}],
            "folder": str(self.root / "backups"),
        }
        with patch.object(presenter, "run_job", fake_job):
            response = self.client.post("/api/backup/run", json=body)
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            self.assertTrue(
                wait_until(
                    lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"]
                    != "running"
                )
            )
        job = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["result"]["ok"], 1)
        self.assertIn("backup uji", job["log"])


if __name__ == "__main__":
    unittest.main()
