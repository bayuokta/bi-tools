"""Uji presenter/endpoint Analisa Semantic Model (tanpa XMLA/network)."""

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
from server.app import create_app  # noqa: E402
from server.presenters import analysis as presenter  # noqa: E402
from server.settings_store import SettingsStore  # noqa: E402

WORKSPACE = "11111111-2222-3333-4444-555555555555"
DATASET = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def fake_result() -> SimpleNamespace:
    column_stat = SimpleNamespace(
        column="Customer Name",
        column_type="Data",
        table="Dim Customer",
        data_type="Text",
        size_total_bytes=1024,
        size_data_bytes=512,
        size_hierarchy_bytes=256,
        size_dictionary_bytes=256,
        rows=1000,
        format_string="",
        has_error=False,
        display_folder="Customer",
    )
    record = {
        "usage_kind": "field",
        "report_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
        "report_name": "Report Uji",
        "workspace_id": WORKSPACE,
        "page_name": "Halaman 1",
        "visual_title": "Tabel",
        "visual_type": "tableEx",
        "field_kind": "Column",
        "aggregation": "",
        "detail": "Values",
        "is_hidden": False,
    }
    page_filter = dict(record, usage_kind="filter-page", detail="Categorical", visual_title="")
    refs = [
        SimpleNamespace(
            kind="relationship",
            object="'Fact Sales'[Customer Name]",
            detail="relasi ke 'Fact Sales'[Customer Name]",
            blocking=True,
        ),
        SimpleNamespace(
            kind="measure",
            object="'Fact Sales'[Total Sales]",
            detail="measure 'Fact Sales'[Total Sales] (kedalaman 1)",
            blocking=False,
        ),
        SimpleNamespace(
            kind="RLS",
            object="role 'HO'",
            detail="filter RLS role 'HO' pada tabel 'Dim Customer'",
            blocking=True,
        ),
        SimpleNamespace(
            kind="sort by",
            object="'Dim Customer'[Customer Name]",
            detail="mengurutkan 'Dim Customer'[Customer Name]",
            blocking=True,
        ),
        SimpleNamespace(
            kind="field parameter",
            object="'Parameter Posisi'",
            detail="field parameter 'Parameter Posisi'",
            blocking=True,
        ),
    ]
    column = SimpleNamespace(
        column=column_stat,
        status="Tidak dipakai",
        reason="Tidak ada referensi.",
        report_records=[record, page_filter],
        model_refs=refs,
    )
    measure_stat = SimpleNamespace(
        measure="Total Sales",
        table="Fact Sales",
        data_type="Double",
        is_hidden=False,
        format_string="#,0",
        has_error=False,
        display_folder="Sales",
        expression="SUM(Fact[Amount])",
    )
    measure = SimpleNamespace(
        measure=measure_stat,
        status="Dipakai",
        reason="Dipakai report.",
        report_records=[],
        model_refs=[],
    )
    stats = SimpleNamespace(
        data_bytes=600,
        hierarchy_bytes=300,
        dictionary_bytes=124,
        tables=[
            SimpleNamespace(
                table="Dim Customer",
                column_count=1,
                rows=1000,
                size_total_bytes=1024,
                storage_mode="Import",
                measure_count=0,
                partition_count=1,
            )
        ],
    )
    return SimpleNamespace(
        dataset_id=DATASET,
        dataset_name="Model Uji",
        workspace_id=WORKSPACE,
        workspace_name="Workspace Uji",
        analyzed_at="2026-11-18T10:00:00",
        stats=stats,
        columns=[column],
        measures=[measure],
        reports=[
            {
                "report_id": "bbbbbbbb-cccc-dddd-eeee-ffffffffffff",
                "report_name": "Report Uji",
                "workspace_id": WORKSPACE,
                "workspace_name": "Workspace Uji",
                "report_format": "PBIR",
                "status": "ok",
                "message": "",
                "modified_at": "2026-11-17T10:00:00",
                "page_count": 3,
                "visual_count": 12,
                "field_count": 40,
                "unresolved_count": 1,
            }
        ],
        relationships=[
            {
                "name": "Rel",
                "from_table": "Fact Sales",
                "from_column": "Customer Name",
                "to_table": "Dim Customer",
                "to_column": "Customer Name",
                "cross_filtering": "oneDirection",
                "is_active": True,
                "is_auto": True,
                "dependent_count": 2,
                "from_cardinality": "many",
                "to_cardinality": "one",
            }
        ],
        m_queries=[
            {"name": "Fact Sales", "kind": "Tabel", "detail": "2 partisi"}
        ],
        report_pages={
            "bbbbbbbb-cccc-dddd-eeee-ffffffffffff": [
                {
                    "page_id": "p1",
                    "page_name": "Halaman 1",
                    "visual_count": 2,
                    "field_count": 5,
                }
            ]
        },
        report_total=1,
        report_scanned=1,
        report_skipped=0,
        report_failed=0,
        report_personal=0,
        report_app=0,
        report_inaccessible=0,
        method="admin",
        coverage="1 report dipindai",
        coverage_complete=True,
        unresolved=[],
        messages=["Catatan uji"],
        unused=[column],
        unused_measures=[],
        unused_bytes=1024,
        dataset_bytes=1024,
        status_counts={"Tidak dipakai": 1},
        measure_status_counts={"Dipakai": 1},
    )


class AnalysisPresenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(presenter.reset_sessions)
        self.root = Path(self._tmp.name)
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.store.set_principal(ServicePrincipal("t", "c", "s"))
        self.store.set_lineage_db(self.root / "katalog.db")

    def test_serialize_result(self) -> None:
        data = presenter.serialize_result(fake_result())
        self.assertEqual(data["dataset"]["name"], "Model Uji")
        self.assertEqual(data["totals"]["columns"], 1)
        self.assertEqual(data["totals"]["unused_bytes"], 1024)
        self.assertEqual(data["columns"][0]["name"], "Customer Name")
        groups = data["columns"][0]["children"]
        self.assertEqual(
            [group["label"] for group in groups],
            [
                "Used in artifacts",
                "Used in visuals",
                "Used as key column",
                "Used in relationships",
                "Used in row/object level security",
                "Used in page level filters",
                "Used in column sorting",
                "Used in field parameters",
            ],
        )
        artifacts = groups[0]
        self.assertEqual(artifacts["count"], 1)
        self.assertEqual(
            [column["index"] for column in artifacts["columns"]],
            [1, 2, 3, 4, 5, 6, 7, 8, 10],
        )
        self.assertEqual(artifacts["columns"][0]["label"], "Type")
        self.assertEqual(artifacts["rows"][0]["name"], "'Fact Sales'[Total Sales]")
        self.assertEqual(artifacts["rows"][0]["cells"]["1"], "Measure")
        self.assertEqual(artifacts["rows"][0]["cells"]["4"], "Double")
        self.assertEqual(artifacts["rows"][0]["cells"]["6"], "Dipakai")
        visuals = groups[1]
        self.assertEqual(
            [(column["index"], column["label"]) for column in visuals["columns"]],
            [(1, "Type"), (2, "Page"), (3, "Report"), (10, "Used as")],
        )
        self.assertEqual(visuals["rows"][0]["cells"]["2"], "Halaman 1")
        self.assertEqual(visuals["rows"][0]["cells"]["10"], "Values")
        self.assertEqual(groups[2]["rows"][0]["cells"]["2"], "Dim Customer")
        self.assertEqual(groups[2]["rows"][0]["cells"]["5"], "1,0 KB")
        self.assertEqual(groups[3]["rows"][0]["cells"]["2"], "Fact Sales")
        self.assertEqual(groups[4]["rows"][0]["cells"]["1"], "RLS")
        self.assertEqual(groups[4]["rows"][0]["cells"]["2"], "Dim Customer")
        self.assertEqual(groups[5]["rows"][0]["cells"]["1"], "Categorical")
        self.assertEqual(groups[5]["rows"][0]["cells"]["2"], "Halaman 1")
        self.assertEqual(groups[6]["rows"][0]["cells"]["2"], "Dim Customer")
        self.assertEqual(groups[6]["rows"][0]["cells"]["4"], "Text")
        self.assertEqual(groups[7]["rows"][0]["name"], "Parameter Posisi")
        self.assertEqual(groups[7]["rows"][0]["cells"]["1"], "Field parameter")
        self.assertEqual(data["measures"][0]["children"], [])
        self.assertEqual(data["measures"][0]["expression"], "SUM(Fact[Amount])")
        self.assertEqual(data["reports"][0]["report_name"], "Report Uji")
        self.assertEqual(data["reports"][0]["page_count"], 3)
        self.assertEqual(data["reports"][0]["pages"][0]["page_name"], "Halaman 1")
        self.assertEqual(data["reports"][0]["pages"][0]["field_count"], 5)
        self.assertEqual(data["tables"][0]["storage_mode"], "Import")
        self.assertEqual(data["tables"][0]["partition_count"], 1)
        relation = data["relationships"][0]
        self.assertEqual(relation["name"], "Rel")
        self.assertEqual(relation["label"], "'Fact Sales'[Customer Name] N \u2190 1 'Dim Customer'[Customer Name]")
        self.assertEqual(relation["type"], "Active")
        self.assertEqual(relation["cross"], "Single")
        self.assertEqual(relation["cardinality"], "N \u2190 1")
        self.assertEqual(relation["status"], "Dipakai")
        self.assertEqual(relation["auto"], "Ya")
        self.assertEqual(relation["used"], 2)
        self.assertEqual(data["m_queries"][0]["kind"], "Tabel")
        self.assertEqual(data["totals"]["pages"], 3)
        self.assertEqual(data["totals"]["tables"], 1)

    def test_preferences_validation_and_roundtrip(self) -> None:
        saved = presenter.save_preferences(
            self.store,
            {
                "object_filter": "measures",
                "unused_only": True,
                "include_reports": False,
                "include_other_workspaces": False,
                "include_personal": True,
                "sort_column": "size",
                "sort_desc": True,
            },
        )
        self.assertEqual(saved["object_filter"], "measures")
        self.assertEqual(saved["sort_column"], "size")
        self.assertTrue(saved["unused_only"])
        self.assertFalse(saved["include_reports"])
        self.assertTrue(presenter.analysis_settings(self.store)["include_personal"])
        presenter.save_preferences(self.store, {"include_reports": True})
        self.assertTrue(presenter.analysis_settings(self.store)["include_reports"])
        with self.assertRaises(ExtractionError):
            presenter.save_preferences(self.store, {"object_filter": "ngawur"})
        with self.assertRaises(ExtractionError):
            presenter.save_preferences(self.store, {"sort_column": "ngawur"})
        for key in ("format", "source", "warning", "security_filtering"):
            saved = presenter.save_preferences(self.store, {"sort_column": key})
            self.assertEqual(saved["sort_column"], key)

    def test_state_empty_catalog(self) -> None:
        state = presenter.build_state(self.store)
        self.assertEqual(state["workspaces"], [])
        self.assertIn("Sinkronisasi", state["hint"])
        self.assertEqual(state["settings"]["object_filter"], "all")

    def test_run_job_requires_selection(self) -> None:
        with self.assertRaises(ExtractionError):
            presenter.run_job(self.store, {}, lambda _line: None, None)

    def test_run_job_passes_request_and_returns_payload(self) -> None:
        result = fake_result()
        with patch.object(presenter, "resolve_names", return_value=("Workspace Uji", "Model Uji")), patch.object(
            presenter, "analyze_dataset", return_value=result
        ) as analyze:
            payload = presenter.run_job(
                self.store,
                {
                    "workspace_id": WORKSPACE,
                    "dataset_id": DATASET,
                    "include_reports": False,
                    "include_other_workspaces": False,
                    "include_personal": True,
                    "refresh": True,
                },
                lambda _line: None,
                SimpleNamespace(is_set=lambda: False),
            )
        kwargs = analyze.call_args.kwargs
        self.assertEqual(kwargs["workspace_id"], WORKSPACE)
        self.assertEqual(kwargs["dataset_id"], DATASET)
        self.assertFalse(kwargs["include_reports"])
        self.assertFalse(kwargs["include_other_workspaces"])
        self.assertTrue(kwargs["include_personal"])
        self.assertTrue(kwargs["refresh"])
        self.assertIsNotNone(kwargs["session"])
        self.assertEqual(payload["dataset"]["id"], DATASET)

    def test_export_requires_snapshot(self) -> None:
        presenter.reset_sessions()
        with self.assertRaises(ExtractionError) as ctx:
            presenter.export({"dataset_id": DATASET}, self.store)
        self.assertIn("Belum ada hasil analisa", str(ctx.exception))
        self.assertIn("tidak disimpan", str(ctx.exception))

    def test_export_writes_workbook(self) -> None:
        target = self.root / "hasil.xlsx"
        target.write_bytes(b"xlsx")
        presenter._session(DATASET)
        with patch.object(presenter, "snapshot_from_connection", return_value=fake_result()), patch.object(
            presenter, "write_workbook", return_value=target
        ) as write:
            data = presenter.export({"dataset_id": DATASET, "output": str(target)}, self.store)
        self.assertEqual(data["path"], str(target))
        write.assert_called_once()
        with self.assertRaises(ExtractionError):
            presenter.export({"dataset_id": DATASET, "output": "relatif.xlsx"}, self.store)

    def test_snapshot_payload_reads_session(self) -> None:
        presenter._session(DATASET)
        with patch.object(presenter, "snapshot_from_connection", return_value=fake_result()):
            data = presenter.snapshot_payload(self.store, DATASET)
        self.assertEqual(data["result"]["dataset"]["name"], "Model Uji")
        presenter.reset_sessions()
        self.assertIsNone(presenter.snapshot_payload(self.store, DATASET)["result"])

    def test_report_detail_requires_session(self) -> None:
        presenter.reset_sessions()
        with self.assertRaises(ExtractionError):
            presenter.report_detail_payload(self.store, DATASET, "r1")

    def test_lineage_requires_session(self) -> None:
        presenter.reset_sessions()
        with self.assertRaises(ExtractionError) as ctx:
            presenter.lineage_payload(self.store, DATASET, "column", "T", "C")
        self.assertIn("Belum ada hasil analisa", str(ctx.exception))

    def test_lineage_payload_uses_session(self) -> None:
        presenter._session(DATASET)
        with patch.object(
            presenter, "snapshot_from_connection", return_value=fake_result()
        ), patch.object(
            presenter, "build_lineage", return_value={"nodes": [], "edges": []}
        ) as build:
            data = presenter.lineage_payload(
                self.store,
                DATASET,
                "measure",
                "KPI",
                "Total",
                direction="downstream",
                depth=3,
            )
        self.assertEqual(data["nodes"], [])
        kwargs = build.call_args.kwargs
        self.assertEqual(kwargs["kind"], "measure")
        self.assertEqual(kwargs["table"], "KPI")
        self.assertEqual(kwargs["name"], "Total")
        self.assertEqual(kwargs["direction"], "downstream")
        self.assertEqual(kwargs["depth"], 3)

    def test_lineage_invalid_seed_is_extraction_error(self) -> None:
        presenter._session(DATASET)
        with patch.object(
            presenter, "snapshot_from_connection", return_value=fake_result()
        ):
            with self.assertRaises(ExtractionError) as ctx:
                presenter.lineage_payload(
                    self.store, DATASET, "column", "T", "TidakAda"
                )
        self.assertIn("tidak ditemukan", str(ctx.exception))


class AnalysisEndpointTests(unittest.TestCase):
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
        response = self.client.get("/api/analysis/state")
        self.assertEqual(response.status_code, 200)
        self.assertIn("settings", response.json())

    def test_report_detail_endpoint(self) -> None:
        with patch.object(
            presenter,
            "report_detail_payload",
            return_value={"pages": [], "report_filters": []},
        ) as mock:
            response = self.client.get(
                f"/api/analysis/report-detail?dataset_id={DATASET}&report_id=r1"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"pages": [], "report_filters": []})
        self.assertEqual(mock.call_args.args[1], DATASET)
        self.assertEqual(mock.call_args.args[2], "r1")

    def test_datasets_endpoint_delegates(self) -> None:
        with patch.object(
            presenter,
            "datasets_payload",
            return_value={"workspace": {"name": "W"}, "datasets": [{"id": "d"}]},
        ):
            response = self.client.get(f"/api/analysis/workspaces/{WORKSPACE}/datasets")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["datasets"][0]["id"], "d")

    def test_snapshot_endpoint(self) -> None:
        with patch.object(presenter, "snapshot_payload", return_value={"result": None}):
            response = self.client.get("/api/analysis/snapshot", params={"dataset_id": DATASET})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["result"])

    def test_lineage_endpoint_delegates(self) -> None:
        with patch.object(
            presenter, "lineage_payload", return_value={"nodes": [], "edges": []}
        ) as mock:
            response = self.client.get(
                "/api/analysis/lineage",
                params={
                    "dataset_id": DATASET,
                    "kind": "measure",
                    "table": "KPI",
                    "name": "Total",
                    "direction": "downstream",
                    "depth": 3,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["nodes"], [])
        args = mock.call_args.args
        self.assertEqual(args[1], DATASET)
        self.assertEqual(args[2], "measure")
        self.assertEqual(args[3], "KPI")
        self.assertEqual(args[4], "Total")
        self.assertEqual(mock.call_args.kwargs["direction"], "downstream")
        self.assertEqual(mock.call_args.kwargs["depth"], 3)

    def test_lineage_endpoint_rejects_bad_depth(self) -> None:
        response = self.client.get(
            "/api/analysis/lineage",
            params={"dataset_id": DATASET, "kind": "column", "name": "C", "depth": 99},
        )
        self.assertEqual(response.status_code, 422)

    def test_preferences_endpoint(self) -> None:
        response = self.client.post(
            "/api/analysis/preferences", json={"object_filter": "columns"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["object_filter"], "columns")

    def test_run_requires_ids(self) -> None:
        response = self.client.post("/api/analysis/run", json={})
        self.assertEqual(response.status_code, 400)

    def test_run_starts_job(self) -> None:
        def fake_job(store, payload, log, cancel):
            log("analisa")
            return {"ok": True}

        self.store.set_principal(ServicePrincipal("t", "c", "s"))
        with patch.object(presenter, "run_job", fake_job):
            response = self.client.post(
                "/api/analysis/run",
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
            self.client.get(f"/api/jobs/{job_id}").json()["result"], {"ok": True}
        )

    def test_export_endpoint(self) -> None:
        with patch.object(
            presenter, "export", return_value={"path": "C:/x.xlsx", "size": 10}
        ):
            response = self.client.post(
                "/api/analysis/export", json={"dataset_id": DATASET}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "C:/x.xlsx")


if __name__ == "__main__":
    unittest.main()
