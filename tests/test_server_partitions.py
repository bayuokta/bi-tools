"""Uji presenter/endpoint Partisi tanpa XMLA atau jaringan."""

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

from core.errors import ExtractionError  # noqa: E402
from server.app import create_app  # noqa: E402
from server.presenters import partitions as presenter  # noqa: E402
from server.settings_store import SettingsStore  # noqa: E402
from tests.helpers import use_user  # noqa: E402

WORKSPACE = "11111111-2222-3333-4444-555555555555"
DATASET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class PartitionPresenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.store.set_shared_db_local(str(self.root / "shared" / "bi_tools.db"))
        self.store.set_lineage_db(self.root / "katalog.db")

    def test_state_has_refresh_types_and_confirmation(self) -> None:
        state = presenter.build_state(self.store)
        self.assertEqual(state["workspaces"], [])
        self.assertIn("Sinkronisasi", state["hint"])
        self.assertIn("full", state["refresh_types"])
        self.assertEqual(state["confirmation"], "PROCESS")

    def test_build_inventory_request_resolves_names(self) -> None:
        with patch.object(presenter, "resolve_names", return_value=("Workspace Uji", "Model Uji")):
            request = presenter.build_inventory_request(
                self.store, {"workspace_id": WORKSPACE, "dataset_id": DATASET}
            )
        self.assertEqual(request.workspace_name, "Workspace Uji")
        self.assertEqual(request.dataset_name, "Model Uji")

    def test_build_refresh_request_requires_confirmation_and_targets(self) -> None:
        with patch.object(presenter, "resolve_names", return_value=("W", "M")):
            with self.assertRaises(ExtractionError):
                presenter.build_refresh_request(
                    self.store,
                    {
                        "workspace_id": WORKSPACE,
                        "dataset_id": DATASET,
                        "targets": [{"table": "Fact", "partition": "P"}],
                        "confirmation": "yes",
                    },
                )
            request = presenter.build_refresh_request(
                self.store,
                {
                    "workspace_id": WORKSPACE,
                    "dataset_id": DATASET,
                    "targets": [{"table": "Fact", "partition": "P"}],
                    "refresh_type": "dataOnly",
                    "confirmation": "process",
                },
            )
        self.assertEqual(request.targets, (("Fact", "P"),))
        self.assertEqual(request.refresh_type, "dataOnly")
        self.assertEqual(request.confirmation, "PROCESS")

    def test_run_inventory_job_delegates(self) -> None:
        with patch.object(presenter, "resolve_names", return_value=("W", "M")), patch.object(
            presenter, "read_partition_inventory", return_value={"partitions": []}
        ) as read:
            payload = presenter.run_inventory_job(
                self.store,
                {"workspace_id": WORKSPACE, "dataset_id": DATASET},
                lambda _line: None,
                None,
            )
        self.assertEqual(payload, {"partitions": []})
        self.assertEqual(read.call_args.kwargs["workspace_name"], "W")

    def test_run_refresh_job_delegates(self) -> None:
        use_user(self.store)
        with patch.object(presenter, "resolve_names", return_value=("W", "M")), patch.object(
            presenter, "process_partitions", return_value={"refresh": {"type": "full"}}
        ) as process:
            payload = presenter.run_refresh_job(
                self.store,
                {
                    "workspace_id": WORKSPACE,
                    "dataset_id": DATASET,
                    "targets": [{"table": "Fact", "partition": "P"}],
                    "confirmation": "PROCESS",
                },
                lambda _line: None,
                None,
            )
        self.assertEqual(payload["refresh"]["type"], "full")
        self.assertEqual(process.call_args.kwargs["targets"], (("Fact", "P"),))


class PartitionEndpointTests(unittest.TestCase):
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
        self.store.set_shared_db_local(str(self.root / "shared" / "bi_tools.db"))
        self.store.set_lineage_db(self.root / "katalog.db")
        self.app = create_app(settings_store=self.store, web_root=web)
        self.client = TestClient(self.app)

    def test_state_endpoint(self) -> None:
        response = self.client.get("/api/partitions/state")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["confirmation"], "PROCESS")

    def test_datasets_endpoint_delegates(self) -> None:
        with patch.object(
            presenter,
            "datasets_payload",
            return_value={"workspace": {"name": "W"}, "datasets": [{"id": "d"}]},
        ):
            response = self.client.get(f"/api/partitions/workspaces/{WORKSPACE}/datasets")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["datasets"][0]["id"], "d")

    def test_inventory_requires_ids(self) -> None:
        response = self.client.post("/api/partitions/inventory", json={})
        self.assertEqual(response.status_code, 400)

    def test_refresh_requires_confirmation(self) -> None:
        with patch.object(presenter, "resolve_names", return_value=("W", "M")):
            response = self.client.post(
                "/api/partitions/refresh",
                json={
                    "workspace_id": WORKSPACE,
                    "dataset_id": DATASET,
                    "targets": [{"table": "Fact", "partition": "P"}],
                    "confirmation": "nope",
                },
            )
        self.assertEqual(response.status_code, 400)

    def test_inventory_starts_job(self) -> None:
        def fake_job(_store, _payload, _log, _cancel):
            return {"partitions": []}

        with patch.object(presenter, "build_inventory_request", return_value=object()), patch.object(
            presenter, "run_inventory_job", fake_job
        ):
            response = self.client.post(
                "/api/partitions/inventory",
                json={"workspace_id": WORKSPACE, "dataset_id": DATASET},
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            self.assertTrue(
                wait_until(
                    lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"]
                    != "running"
                )
            )
        self.assertEqual(
            self.client.get(f"/api/jobs/{job_id}").json()["result"],
            {"partitions": []},
        )

    def test_refresh_starts_job(self) -> None:
        def fake_job(_store, _payload, _log, _cancel):
            return {"refresh": {"type": "full"}}

        with patch.object(presenter, "build_refresh_request", return_value=object()), patch.object(
            presenter, "run_refresh_job", fake_job
        ):
            response = self.client.post(
                "/api/partitions/refresh",
                json={
                    "workspace_id": WORKSPACE,
                    "dataset_id": DATASET,
                    "targets": [{"table": "Fact", "partition": "P"}],
                    "confirmation": "PROCESS",
                },
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            self.assertTrue(
                wait_until(
                    lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"]
                    != "running"
                )
            )
        self.assertEqual(
            self.client.get(f"/api/jobs/{job_id}").json()["result"]["refresh"]["type"],
            "full",
        )


if __name__ == "__main__":
    unittest.main()
