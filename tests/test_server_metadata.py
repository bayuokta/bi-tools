"""Uji presenter dan endpoint ekstraksi metadata web."""

from __future__ import annotations

import tempfile
import time
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated"
)

from fastapi.testclient import TestClient  # noqa: E402

from core.auth import ServicePrincipal  # noqa: E402
from core.errors import ExtractionError  # noqa: E402
from core.lineage_service import WorkspaceOption  # noqa: E402
from core.pbix import LOCAL_MODEL, PbixSourceInfo  # noqa: E402
from server.app import create_app  # noqa: E402
from server.presenters import metadata as presenter  # noqa: E402
from server.settings_store import SettingsStore  # noqa: E402

WORKSPACE = "11111111-2222-3333-4444-555555555555"
REPORT = "66666666-7777-8888-9999-000000000000"
DATASET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def fake_info(path: Path) -> PbixSourceInfo:
    return PbixSourceInfo(
        path=path,
        kind=LOCAL_MODEL,
        has_datamodel=True,
        has_pbir=True,
    )


class MetadataPresenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.pbix = self.root / "contoh.pbix"
        self.pbix.write_bytes(b"bukan zip")
        self.store.set_principal(ServicePrincipal("t", "c", "s"))
        self.store.set_lineage_db(self.root / "katalog.db")

    def test_instances_empty(self) -> None:
        with patch.object(presenter, "list_instances", return_value=[]):
            payload = presenter.instances_payload()
        self.assertEqual(payload["instances"], [])
        self.assertIn("Tidak ada instance", payload["hint"])

    def test_instances_serialized(self) -> None:
        item = SimpleNamespace(
            port=1234,
            catalog="Model",
            file_name="Sales.pbix",
            model_name="Model",
            modified="2026-11-18",
            label="Sales.pbix - localhost:1234",
        )
        with patch.object(presenter, "list_instances", return_value=[item]):
            payload = presenter.instances_payload()
        self.assertEqual(payload["instances"][0]["port"], 1234)
        self.assertIn("Satu instance", payload["hint"])

    def test_pbix_missing_and_empty(self) -> None:
        self.assertEqual(presenter.pbix_payload("")["label"], "Belum ada file .pbix dipilih.")
        missing = presenter.pbix_payload(str(self.root / "tidak-ada.pbix"))
        self.assertFalse(missing["exists"])
        self.assertIn("tidak ditemukan", missing["label"])

    def test_pbix_reads_source_info(self) -> None:
        with patch.object(presenter, "detect_pbix_source", side_effect=fake_info):
            payload = presenter.pbix_payload(str(self.pbix))
        self.assertTrue(payload["exists"])
        self.assertTrue(payload["has_pbir"])
        self.assertTrue(payload["has_local_model"])
        self.assertIn("Desktop harus terbuka", payload["detail"])

    def test_workspaces_without_catalog(self) -> None:
        payload = presenter.workspaces_payload(self.store)
        self.assertEqual(payload["workspaces"], [])
        self.assertIn("Sinkronisasi", payload["hint"])

    def test_contents_requires_known_workspace(self) -> None:
        with patch.object(presenter, "workspace_detail", return_value=None):
            with self.assertRaises(ExtractionError) as ctx:
                presenter.contents_payload(self.store, WORKSPACE)
        self.assertIn("katalog SQLite", str(ctx.exception))

    def test_contents_lists_items_and_endpoint(self) -> None:
        option = WorkspaceOption(WORKSPACE, "Contoh - SO")
        contents = {
            "datasets": [{"id": DATASET, "name": "Model SO"}],
            "reports": [
                {
                    "id": REPORT,
                    "name": "Report SO",
                    "reportType": "PowerBIReport",
                    "datasetId": DATASET,
                },
                {
                    "id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                    "name": "Report RDL",
                    "reportType": "PaginatedReport",
                },
            ],
        }
        with patch.object(presenter, "workspace_detail", return_value=option), patch.object(
            presenter, "workspace_contents", return_value=contents
        ):
            payload = presenter.contents_payload(self.store, WORKSPACE)

        self.assertEqual(payload["workspace"]["name"], "Contoh - SO")
        self.assertIn("Contoh%20-%20SO", payload["workspace"]["endpoint"])
        self.assertEqual(payload["datasets"][0]["name"], "Model SO")
        self.assertEqual(payload["reports"][0]["label"], "Report SO (66666666)")
        self.assertTrue(payload["reports"][1]["is_paginated"])
        self.assertIn("[Paginated]", payload["reports"][1]["label"])

    def test_contents_can_limit_kinds(self) -> None:
        option = WorkspaceOption(WORKSPACE, "Contoh")
        with patch.object(presenter, "workspace_detail", return_value=option), patch.object(
            presenter, "workspace_contents", return_value={}
        ) as loader:
            presenter.contents_payload(self.store, WORKSPACE, datasets=True, reports=False)
        loader.assert_called_once_with(
            self.store.principal(), WORKSPACE, datasets=True, reports=False
        )

    def test_build_request_local(self) -> None:
        with patch.object(presenter, "detect_pbix_source", side_effect=fake_info):
            request = presenter.build_request(
                self.store,
                {
                    "source": "local",
                    "scope": "both",
                    "pbix": str(self.pbix),
                    "port": 1234,
                    "catalog": "Model",
                },
            )
        self.assertEqual(request.scope, "both")
        self.assertTrue(request.extract_report)
        self.assertTrue(request.extract_model)
        self.assertEqual(request.port, 1234)
        self.assertEqual(request.catalog, "Model")
        self.assertTrue(request.include_usage)

    def test_build_request_local_model_needs_instance(self) -> None:
        with patch.object(presenter, "detect_pbix_source", side_effect=fake_info):
            with self.assertRaises(ExtractionError) as ctx:
                presenter.build_request(
                    self.store,
                    {"source": "local", "scope": "model", "pbix": str(self.pbix)},
                )
        self.assertIn("instance Power BI Desktop", str(ctx.exception))

    def test_build_request_local_report_requires_pbir(self) -> None:
        info = PbixSourceInfo(
            path=self.pbix, kind=LOCAL_MODEL, has_datamodel=True, has_pbir=False
        )
        with patch.object(presenter, "detect_pbix_source", return_value=info):
            with self.assertRaises(ExtractionError) as ctx:
                presenter.build_request(
                    self.store,
                    {"source": "local", "scope": "report", "pbix": str(self.pbix)},
                )
        self.assertIn("Report/definition", str(ctx.exception))

    def test_build_request_service_endpoint_derived(self) -> None:
        request = presenter.build_request(
            self.store,
            {
                "source": "service",
                "scope": "both",
                "workspace_id": WORKSPACE,
                "workspace_name": "Contoh - SO",
                "report_id": REPORT,
                "catalog": "Model SO",
                "dataset_name": "Model SO",
            },
        )
        self.assertIn("Contoh%20-%20SO", request.endpoint)
        self.assertTrue(request.extract_report)
        self.assertTrue(request.include_usage)

    def test_build_request_service_rejects_paginated(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            presenter.build_request(
                self.store,
                {
                    "source": "service",
                    "scope": "report",
                    "workspace_id": WORKSPACE,
                    "workspace_name": "Contoh",
                    "report_id": REPORT,
                    "report_type": "PaginatedReport",
                },
            )
        self.assertIn("paginated", str(ctx.exception))

    def test_build_request_service_requires_credentials(self) -> None:
        store = SettingsStore(
            self.root / "kosong.json", registry_reader=lambda: {}
        )
        with self.assertRaises(ExtractionError) as ctx:
            presenter.build_request(
                store,
                {
                    "source": "service",
                    "scope": "report",
                    "workspace_id": WORKSPACE,
                    "workspace_name": "Contoh",
                    "report_id": REPORT,
                },
            )
        self.assertIn("Kredensial", str(ctx.exception))

    def test_build_request_service_separate_report_workspace(self) -> None:
        report_workspace = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        request = presenter.build_request(
            self.store,
            {
                "source": "service",
                "scope": "both",
                "model_workspace_id": WORKSPACE,
                "model_workspace_name": "Workspace Model",
                "report_workspace_id": report_workspace,
                "report_workspace_name": "Workspace Report",
                "report_id": REPORT,
                "catalog": "Model DS",
            },
        )
        self.assertEqual(request.workspace_id, report_workspace)
        self.assertIn("Workspace%20Model", request.endpoint)
        self.assertEqual(request.catalog, "Model DS")

    def test_build_request_service_report_only_without_model_workspace(self) -> None:
        request = presenter.build_request(
            self.store,
            {
                "source": "service",
                "scope": "report",
                "report_workspace_id": WORKSPACE,
                "report_workspace_name": "Contoh",
                "report_id": REPORT,
            },
        )
        self.assertTrue(request.extract_report)
        self.assertFalse(request.extract_model)
        self.assertEqual(request.endpoint, "")

    def test_build_request_service_model_requires_catalog(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            presenter.build_request(
                self.store,
                {
                    "source": "service",
                    "scope": "model",
                    "model_workspace_id": WORKSPACE,
                    "model_workspace_name": "Contoh",
                },
            )
        self.assertIn("catalog", str(ctx.exception))

    def test_run_job_local_passes_kwargs(self) -> None:
        result = SimpleNamespace(
            source=SimpleNamespace(label="Model lokal", kind="local_model"),
            report={"pages": 2},
            model={"tables": 3},
            model_error="",
            report_out=self.root / "Report.xlsx",
            model_out=self.root / "Model.xlsx",
            outputs=(self.root / "Report.xlsx", self.root / "Model.xlsx"),
        )
        with patch.object(presenter, "detect_pbix_source", side_effect=fake_info), patch.object(
            presenter, "run_metadata_job", return_value=result
        ) as run:
            summary = presenter.run_job(
                self.store,
                {
                    "source": "local",
                    "scope": "both",
                    "pbix": str(self.pbix),
                    "port": 1234,
                    "catalog": "Model",
                },
                lambda _line: None,
                None,
            )
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["port"], 1234)
        self.assertTrue(kwargs["extract_model"])
        self.assertTrue(kwargs["validate_with_existing"])
        self.assertEqual(summary["model"]["tables"], 3)
        self.assertEqual(len(summary["outputs"]), 2)

    def test_run_job_service_passes_tokens(self) -> None:
        request = presenter.build_request(
            self.store,
            {
                "source": "service",
                "scope": "report",
                "workspace_id": WORKSPACE,
                "workspace_name": "Contoh",
                "report_id": REPORT,
            },
        )
        result = SimpleNamespace(
            source=SimpleNamespace(label="Power BI Service", kind="service_report"),
            report={"pages": 1},
            model=None,
            model_error="",
            report_out=self.root / "Report.xlsx",
            model_out=None,
            outputs=(self.root / "Report.xlsx",),
        )
        with patch.object(presenter, "build_request", return_value=request), patch.object(
            presenter, "EntraTokens"
        ) as tokens, patch.object(presenter, "fabric_provider") as provider, patch.object(
            presenter, "run_metadata_job", return_value=result
        ) as run:
            summary = presenter.run_job(self.store, {}, lambda _line: None, None)

        tokens.assert_called_once()
        provider.assert_called_once()
        self.assertIn("token_provider", run.call_args.kwargs)
        self.assertEqual(summary["kind"], "service_report")


class MetadataEndpointTests(unittest.TestCase):
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

    def test_run_rejects_missing_pbix(self) -> None:
        response = self.client.post(
            "/api/metadata/run", json={"source": "local", "scope": "report"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(".pbix", response.json()["detail"])

    def test_run_starts_job(self) -> None:
        def fake_job(store, payload, log, cancel):
            log("mulai")
            return {"ok": True}

        with patch.object(presenter, "build_request", return_value=object()), patch.object(
            presenter, "run_job", fake_job
        ):
            response = self.client.post(
                "/api/metadata/run", json={"source": "local", "scope": "report"}
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["job_id"]
            self.assertTrue(
                wait_until(
                    lambda: self.client.get(f"/api/jobs/{job_id}").json()["status"]
                    != "running"
                )
            )
        body = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(body["result"], {"ok": True})

    def test_pbix_endpoint(self) -> None:
        response = self.client.get("/api/metadata/pbix")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["exists"])

    def test_workspaces_endpoint(self) -> None:
        response = self.client.get("/api/metadata/workspaces")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspaces"], [])

    def test_instances_endpoint(self) -> None:
        with patch.object(presenter, "list_instances", return_value=[]):
            response = self.client.get("/api/metadata/instances")
        self.assertEqual(response.status_code, 200)
        self.assertIn("instances", response.json())


if __name__ == "__main__":
    unittest.main()
