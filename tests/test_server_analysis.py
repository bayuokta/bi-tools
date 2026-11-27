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

from core.errors import ExtractionError  # noqa: E402
from server.app import create_app  # noqa: E402
from server.presenters import analysis as presenter  # noqa: E402
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
            depth=1,
        ),
        SimpleNamespace(
            kind="measure",
            object="'Fact Sales'[Other Measure]",
            detail="measure 'Fact Sales'[Other Measure] (kedalaman 2)",
            blocking=False,
            depth=2,
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
        self.store.set_shared_db_local(str(self.root / "shared" / "bi_tools.db"))
        use_user(self.store)
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
                "Used in visuals",
                "Used in artifacts",
                "Indirect references",
                "Used in page level filters",
                "Used in relationships",
                "Used in row/object level security",
                "Used as key column",
                "Used in column sorting",
                "Used in field parameters",
            ],
        )
        by_label = {group["label"]: group for group in groups}
        artifacts = by_label["Used in artifacts"]
        self.assertEqual(artifacts["count"], 1)
        self.assertEqual(
            [column["index"] for column in artifacts["columns"]],
            [1, 2, 3, 4, 5, 6, 7, 8, 10],
        )
        self.assertEqual(artifacts["columns"][0]["label"], "Type")
        self.assertEqual(artifacts["rows"][0]["name"], "'Fact Sales'[Total Sales]")
        self.assertEqual(artifacts["rows"][0]["cells"]["1"], "Measure")
        self.assertEqual(artifacts["rows"][0]["cells"]["4"], "Double")
        indirect = by_label["Indirect references"]
        self.assertEqual(indirect["count"], 1)
        self.assertEqual(
            indirect["rows"][0]["name"], "'Fact Sales'[Other Measure]"
        )
        self.assertEqual(
            indirect["rows"][0]["cells"]["1"], "Measure \u00b7 depth 2"
        )
        self.assertEqual(data["columns"][0]["uses"], 7)
        self.assertEqual(data["columns"][0]["direct_refs"], 5)
        self.assertEqual(data["columns"][0]["transitive_refs"], 1)
        self.assertEqual(artifacts["rows"][0]["cells"]["6"], "Dipakai")
        visuals = by_label["Used in visuals"]
        self.assertEqual(
            [(column["index"], column["label"]) for column in visuals["columns"]],
            [(1, "Type"), (2, "Page"), (3, "Report"), (10, "Used as")],
        )
        self.assertEqual(visuals["rows"][0]["cells"]["2"], "Halaman 1")
        self.assertEqual(visuals["rows"][0]["cells"]["10"], "Values")
        page_filters = by_label["Used in page level filters"]
        self.assertEqual(page_filters["rows"][0]["cells"]["1"], "Categorical")
        self.assertEqual(page_filters["rows"][0]["cells"]["2"], "Halaman 1")
        relationships = by_label["Used in relationships"]
        self.assertEqual(relationships["rows"][0]["cells"]["2"], "Fact Sales")
        security = by_label["Used in row/object level security"]
        self.assertEqual(security["rows"][0]["cells"]["1"], "RLS")
        self.assertEqual(security["rows"][0]["cells"]["2"], "Dim Customer")
        key_column = by_label["Used as key column"]
        self.assertEqual(key_column["rows"][0]["cells"]["2"], "Dim Customer")
        self.assertEqual(key_column["rows"][0]["cells"]["5"], "1,0 KB")
        sorting = by_label["Used in column sorting"]
        self.assertEqual(sorting["rows"][0]["cells"]["2"], "Dim Customer")
        self.assertEqual(sorting["rows"][0]["cells"]["4"], "Text")
        parameters = by_label["Used in field parameters"]
        self.assertEqual(parameters["rows"][0]["name"], "Parameter Posisi")
        self.assertEqual(parameters["rows"][0]["cells"]["1"], "Field parameter")
        self.assertEqual(data["measures"][0]["children"], [])
        self.assertEqual(data["measures"][0]["expression"], "SUM(Fact[Amount])")
        self.assertEqual(data["reports"][0]["report_name"], "Report Uji")
        self.assertEqual(data["reports"][0]["page_count"], 3)
        self.assertEqual(data["reports"][0]["pages"][0]["page_name"], "Halaman 1")
        self.assertEqual(data["reports"][0]["pages"][0]["field_count"], 5)
        self.assertEqual(data["reports"][0]["broken_visuals"], 0)
        self.assertEqual(data["reports"][0]["health_score"], 100)
        self.assertEqual(data["health"]["counts"]["critical"], 0)
        self.assertIn(
            "missing_theme",
            [item["rule"] for item in data["health"]["items"]],
        )
        self.assertTrue(data["best_practice"]["available"])
        self.assertEqual(data["best_practice"]["rule_count"], 71)
        self.assertGreaterEqual(data["best_practice"]["evaluated"], 1)
        self.assertIn("score", data["best_practice"])
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
                category="measures",
            )
        self.assertEqual(data["nodes"], [])
        kwargs = build.call_args.kwargs
        self.assertEqual(kwargs["kind"], "measure")
        self.assertEqual(kwargs["table"], "KPI")
        self.assertEqual(kwargs["name"], "Total")
        self.assertEqual(kwargs["direction"], "downstream")
        self.assertEqual(kwargs["depth"], 3)
        self.assertEqual(kwargs["category"], "measures")

    def test_lineage_table_payload_uses_table_builder(self) -> None:
        presenter._session(DATASET)
        with patch.object(
            presenter, "snapshot_from_connection", return_value=fake_result()
        ), patch.object(
            presenter, "build_table_lineage", return_value={"nodes": [], "edges": []}
        ) as build:
            data = presenter.lineage_payload(
                self.store,
                DATASET,
                "table",
                "Sales",
                "Sales",
                direction="both",
                depth=4,
                outline_mode="full",
            )
        self.assertEqual(data["nodes"], [])
        kwargs = build.call_args.kwargs
        self.assertEqual(kwargs["table"], "Sales")
        self.assertEqual(kwargs["direction"], "both")
        self.assertEqual(kwargs["depth"], 4)
        self.assertEqual(kwargs["outline_mode"], "full")

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

    def test_preview_payload_queries_model_read_only(self) -> None:
        presenter._session(DATASET)
        client = SimpleNamespace(
            query_sql=lambda sql, timeout=None: [{"Customer Name": "Budi"}],
            close=lambda: None,
        )
        with patch.object(
            presenter, "snapshot_from_connection", return_value=fake_result()
        ), patch.object(presenter, "open_client", return_value=client) as opened, patch.object(
            presenter, "EntraTokens", return_value=object()
        ):
            data = presenter.preview_payload(
                self.store,
                DATASET,
                "column",
                "Dim Customer",
                "Customer Name",
                limit=10,
            )
        query = opened.call_args.kwargs["endpoint"]
        self.assertIn("Workspace%20Uji", query)
        self.assertEqual(opened.call_args.kwargs["catalog"], "Model Uji")
        self.assertEqual(data["columns"], ["Customer Name"])
        self.assertEqual(data["rows"], [["Budi"]])
        self.assertEqual(data["limit"], 10)
        self.assertIn("TOPN(10,", data["query"])

    def test_preview_payload_rejects_unknown_item(self) -> None:
        presenter._session(DATASET)
        with patch.object(
            presenter, "snapshot_from_connection", return_value=fake_result()
        ), patch.object(presenter, "open_client") as opened:
            with self.assertRaises(ExtractionError):
                presenter.preview_payload(
                    self.store, DATASET, "column", "T", "TidakAda"
                )
        opened.assert_not_called()

    def test_export_lineage_writes_files(self) -> None:
        presenter._session(DATASET)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                presenter, "snapshot_from_connection", return_value=fake_result()
            ), patch.object(presenter, "outputs_dir", return_value=Path(tmp)):
                data = presenter.export_lineage(
                    self.store,
                    {
                        "dataset_id": DATASET,
                        "kind": "column",
                        "table": "Dim Customer",
                        "name": "Customer Name",
                    },
                )
            self.assertEqual(len(data["paths"]), 3)
            for path in data["paths"]:
                self.assertTrue(Path(path).exists())
            with patch.object(
                presenter, "snapshot_from_connection", return_value=fake_result()
            ), patch.object(presenter, "outputs_dir", return_value=Path(tmp)):
                only_json = presenter.export_lineage(
                    self.store,
                    {
                        "dataset_id": DATASET,
                        "kind": "column",
                        "table": "Dim Customer",
                        "name": "Customer Name",
                        "format": "json",
                    },
                )
            self.assertEqual(len(only_json["paths"]), 1)
            self.assertTrue(only_json["paths"][0].endswith(".json"))

    def test_details_payload_for_column(self) -> None:
        presenter._session(DATASET)
        with patch.object(
            presenter, "snapshot_from_connection", return_value=fake_result()
        ):
            data = presenter.details_payload(
                self.store, DATASET, "column", "Dim Customer", "Customer Name"
            )
        details = data["details"]
        self.assertEqual(details["type"], "Column")
        self.assertTrue(details["is_used_relationships"])
        self.assertTrue(details["is_used_key"])
        self.assertEqual(
            details["relationship_dependencies"][0]["table2"], "Dim Customer"
        )
        self.assertIsNone(details["is_used_excel"])
        self.assertIn("is_used_excel", details["unsupported"])

    def test_raw_metadata_payload_finds_column(self) -> None:
        presenter._session(DATASET)
        rows = {
            "TMSCHEMA_TABLES": [{"ID": 1, "Name": "Dim Customer"}],
            "TMSCHEMA_COLUMNS": [
                {
                    "ID": 10,
                    "TableID": 1,
                    "ExplicitName": "Customer Name",
                    "InferredName": "Customer Name",
                    "Expression": "None",
                }
            ],
            "TMSCHEMA_MEASURES": [
                {"ID": 20, "TableID": 2, "Name": "Total Sales"}
            ],
        }
        client = SimpleNamespace(
            query=lambda dmv: rows[dmv],
            close=lambda: None,
        )
        with patch.object(
            presenter, "snapshot_from_connection", return_value=fake_result()
        ), patch.object(presenter, "open_client", return_value=client), patch.object(
            presenter, "EntraTokens", return_value=object()
        ):
            data = presenter.raw_metadata_payload(
                self.store, DATASET, "column", "Dim Customer", "Customer Name"
            )
        self.assertTrue(data["found"])
        self.assertEqual(data["dmv"], "TMSCHEMA_COLUMNS")
        self.assertEqual(data["row"]["ID"], 10)

    def test_raw_metadata_missing_row_is_error(self) -> None:
        presenter._session(DATASET)
        client = SimpleNamespace(
            query=lambda dmv: [], close=lambda: None
        )
        with patch.object(
            presenter, "snapshot_from_connection", return_value=fake_result()
        ), patch.object(presenter, "open_client", return_value=client), patch.object(
            presenter, "EntraTokens", return_value=object()
        ):
            with self.assertRaises(ExtractionError):
                presenter.raw_metadata_payload(
                    self.store, DATASET, "column", "Dim Customer", "Customer Name"
                )

    def test_export_lineage_image_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(presenter, "outputs_dir", return_value=Path(tmp)):
                data = presenter.export_lineage_image(
                    self.store,
                    {
                        "table": "Sales",
                        "name": "Amount",
                        "format": "svg",
                        "content": '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                    },
                )
            self.assertTrue(data["path"].endswith("_lineage.svg"))
            self.assertTrue(Path(data["path"]).exists())
            with patch.object(presenter, "outputs_dir", return_value=Path(tmp)):
                with self.assertRaises(ExtractionError):
                    presenter.export_lineage_image(
                        self.store,
                        {
                            "table": "Sales",
                            "name": "Amount",
                            "format": "png",
                            "content": "not-a-png",
                        },
                    )

    def test_export_dependencies_writes_csv(self) -> None:
        presenter._session(DATASET)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                presenter, "snapshot_from_connection", return_value=fake_result()
            ), patch.object(presenter, "outputs_dir", return_value=Path(tmp)):
                data = presenter.export_dependencies(
                    self.store,
                    {
                        "dataset_id": DATASET,
                        "kind": "column",
                        "table": "Dim Customer",
                        "name": "Customer Name",
                    },
                )
            self.assertGreater(data["rows"], 0)
            self.assertTrue(Path(data["path"]).exists())


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
        self.store.set_shared_db_local(str(self.root / "shared" / "bi_tools.db"))
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
                    "category": "reports",
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
        self.assertEqual(mock.call_args.kwargs["category"], "reports")

    def test_lineage_image_endpoint_delegates(self) -> None:
        payload = {
            "format": "svg",
            "content": "<svg></svg>",
            "table": "KPI",
            "name": "Total",
        }
        with patch.object(
            presenter, "export_lineage_image", return_value={"path": "x.svg"}
        ) as mock:
            response = self.client.post(
                "/api/analysis/lineage/image", json=payload
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "x.svg")
        self.assertEqual(mock.call_args.args[1], payload)

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

    def test_details_endpoint_delegates(self) -> None:
        with patch.object(
            presenter, "details_payload", return_value={"details": {"name": "X"}}
        ) as mock:
            response = self.client.get(
                "/api/analysis/details",
                params={
                    "dataset_id": DATASET,
                    "kind": "measure",
                    "table": "KPI",
                    "name": "Total",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["details"]["name"], "X")
        self.assertEqual(mock.call_args.args[1:], (DATASET, "measure", "KPI", "Total"))

    def test_raw_metadata_endpoint_starts_job(self) -> None:
        def fake_metadata(store, dataset_id, kind, table, name):
            return {"found": True, "row": {"ID": 1}}

        with patch.object(presenter, "raw_metadata_payload", fake_metadata):
            response = self.client.post(
                "/api/analysis/raw-metadata",
                json={
                    "dataset_id": DATASET,
                    "kind": "column",
                    "table": "Sales",
                    "name": "Amount",
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
        result = self.client.get(f"/api/jobs/{job_id}").json()["result"]
        self.assertTrue(result["found"])
        self.assertEqual(result["row"]["ID"], 1)

    def test_run_requires_ids(self) -> None:
        response = self.client.post("/api/analysis/run", json={})
        self.assertEqual(response.status_code, 400)

    def test_run_starts_job(self) -> None:
        def fake_job(store, payload, log, cancel):
            log("analisa")
            return {"ok": True}

        use_user(self.store)
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

    def test_preview_endpoint_requires_item(self) -> None:
        response = self.client.post(
            "/api/analysis/preview", json={"dataset_id": DATASET, "kind": "column"}
        )
        self.assertEqual(response.status_code, 400)

    def test_preview_endpoint_starts_job(self) -> None:
        def fake_preview(store, dataset_id, kind, table, name, limit=100):
            return {"columns": ["A"], "rows": [[1]], "limit": limit}

        with patch.object(presenter, "preview_payload", fake_preview):
            response = self.client.post(
                "/api/analysis/preview",
                json={
                    "dataset_id": DATASET,
                    "kind": "column",
                    "table": "Sales",
                    "name": "Amount",
                    "limit": 10,
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
        result = self.client.get(f"/api/jobs/{job_id}").json()["result"]
        self.assertEqual(result["limit"], 10)
        self.assertEqual(result["rows"], [[1]])

    def test_lineage_export_endpoint_delegates(self) -> None:
        with patch.object(
            presenter, "export_lineage", return_value={"paths": ["a.csv"]}
        ) as mock:
            response = self.client.post(
                "/api/analysis/lineage/export",
                json={
                    "dataset_id": DATASET,
                    "kind": "column",
                    "table": "Sales",
                    "name": "Amount",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["paths"], ["a.csv"])
        self.assertEqual(mock.call_args.args[1]["table"], "Sales")

    def test_dependencies_export_endpoint_delegates(self) -> None:
        with patch.object(
            presenter, "export_dependencies", return_value={"path": "d.csv"}
        ) as mock:
            response = self.client.post(
                "/api/analysis/dependencies/export",
                json={
                    "dataset_id": DATASET,
                    "kind": "measure",
                    "table": "KPI",
                    "name": "Total",
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["path"], "d.csv")
        self.assertEqual(mock.call_args.args[1]["kind"], "measure")

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
