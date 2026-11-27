"""Uji endpoint compare (tanpa XMLA/network)."""

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

from server.app import create_app  # noqa: E402
from server.presenters import compare as presenter  # noqa: E402
from server.settings_store import SettingsStore  # noqa: E402

WORKSPACE_A = "11111111-2222-3333-4444-555555555555"
WORKSPACE_B = "66666666-7777-8888-9999-000000000000"
DATASET_A = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
DATASET_B = "ffffffff-1111-2222-3333-444444444444"


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def payload() -> dict:
    return {
        "source": {"type": "dataset", "workspace_id": WORKSPACE_A, "dataset_id": DATASET_A},
        "target": {"type": "dataset", "workspace_id": WORKSPACE_B, "dataset_id": DATASET_B},
        "options": {"measures": True, "roles": True},
    }


class CompareEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        web = self.root / "web"
        web.mkdir()
        (web / "index.html").write_text("ok", encoding="utf-8")
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.store.set_lineage_db(self.root / "katalog.db")
        self.app = create_app(settings_store=self.store, web_root=web)
        self.client = TestClient(self.app)

    def test_state(self) -> None:
        with patch.object(
            presenter,
            "build_state",
            return_value={"workspaces": [], "instances": [], "hint": ""},
        ):
            response = self.client.get("/api/compare/state")
        self.assertEqual(response.status_code, 200)
        self.assertIn("workspaces", response.json())

    def test_run_rejects_invalid_payload(self) -> None:
        response = self.client.post(
            "/api/compare/run",
            json={"source": {"type": "dataset"}, "target": {"type": "desktop"}},
        )
        self.assertEqual(response.status_code, 400)

    def test_run_rejects_same_model(self) -> None:
        same = {
            "source": {"type": "dataset", "workspace_id": WORKSPACE_A, "dataset_id": DATASET_A},
            "target": {"type": "dataset", "workspace_id": WORKSPACE_A, "dataset_id": DATASET_A},
        }
        response = self.client.post("/api/compare/run", json=same)
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot", response.json()["detail"])

    def test_run_submits_job(self) -> None:
        fake = {
            "items": [],
            "stats": {"total": 0, "same": 0, "different": 0, "source_only": 0, "target_only": 0},
            "source": {"label": "A"},
            "target": {"label": "B"},
        }
        with patch.object(presenter, "run_job", return_value=fake):
            response = self.client.post("/api/compare/run", json=payload())
        self.assertEqual(response.status_code, 202)
        job_id = response.json()["job_id"]
        self.assertTrue(
            wait_until(
                lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"] != "running"
            )
        )
        self.assertEqual(
            self.client.get(f"/api/jobs/{job_id}").json()["status"], "done"
        )

    def test_export_requires_last_result(self) -> None:
        with patch.object(
            presenter, "export_csv", side_effect=presenter.ExtractionError("Belum ada")
        ):
            response = self.client.post("/api/compare/export")
        self.assertEqual(response.status_code, 400)

    def test_export_delegates(self) -> None:
        with patch.object(
            presenter, "export_csv", return_value={"path": "x.csv", "size": 10}
        ) as mock:
            response = self.client.post("/api/compare/export")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "x.csv")
        mock.assert_called_once()

    def test_script_delegates(self) -> None:
        with patch.object(
            presenter, "generate_script", return_value={"path": "x.json", "size": 10}
        ):
            response = self.client.post("/api/compare/script")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "x.json")


if __name__ == "__main__":
    unittest.main()
