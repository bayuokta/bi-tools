"""Uji client Fabric API dan jalur report Power BI Service (tanpa network)."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from core.auth import EntraTokens, FABRIC_SCOPE, MsalTokenProvider, ServicePrincipal
from core.errors import ExtractionError
from core.fabric_api import (
    DefinitionPart,
    FabricReportClient,
    ServiceReportRef,
    materialize_definition,
    parse_definition_response,
    parse_report_url,
)
from core.jobs import run_metadata_job, run_service_report_job
from core.model import _resolve_report_usage

WORKSPACE = "99999999-9999-4999-8999-999999999999"
REPORT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


class DummyTokens:
    def __init__(self) -> None:
        self.calls = 0

    def get_token(self) -> str:
        self.calls += 1
        return "token-fabric"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("respons tanpa JSON")
        return self._payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        timeout: int = 0,
        **kwargs: object,
    ):
        self.calls.append((method, url, dict(headers or {})))
        if not self._responses:
            raise AssertionError("tidak ada respons tiruan tersisa")
        return self._responses.pop(0)

    def close(self) -> None:
        pass


class FakeFabricClient:
    def __init__(self, definition) -> None:
        self.definition = definition
        self.closed = False
        self.requests: list[ServiceReportRef] = []

    def get_report_definition(self, service: ServiceReportRef):
        self.requests.append(service)
        return self.definition

    def close(self) -> None:
        self.closed = True


def _part(path: str, content: str | bytes) -> dict:
    data = content.encode("utf-8") if isinstance(content, str) else content
    return {
        "path": path,
        "payload": base64.b64encode(data).decode("ascii"),
        "payloadType": "InlineBase64",
    }


def _pbir_parts() -> list[dict]:
    return [
        _part("definition/report.json", "{}"),
        _part(
            "definition/pages/pages.json",
            json.dumps({"pageOrder": ["p1"], "activePageName": "p1"}),
        ),
        _part(
            "definition/pages/p1/page.json",
            json.dumps({"name": "p1", "displayName": "Halaman 1"}),
        ),
        _part(
            "definition/pages/p1/visuals/v1/visual.json",
            json.dumps({"name": "v1", "visual": {"visualType": "textbox"}}),
        ),
        _part(
            "definition.pbir",
            json.dumps(
                {
                    "datasetReference": {
                        "byConnection": {"connectionString": "semanticmodelid=model-123"}
                    }
                }
            ),
        ),
    ]


def _definition():
    return parse_definition_response({"definition": {"parts": _pbir_parts()}})


def write_minimal_model_workbook(path: Path) -> Path:
    """Workbook model minimal (03_Columns + 04_Measures) untuk validasi offline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = pd.DataFrame([{"table": "Sales", "column": "Amount", "is_hidden": False}])
    measures = pd.DataFrame([{"table": "Sales", "measure": "Total Amount", "is_hidden": False}])
    with pd.ExcelWriter(path) as writer:
        columns.to_excel(writer, sheet_name="03_Columns", index=False)
        measures.to_excel(writer, sheet_name="04_Measures", index=False)
    return path


def write_report_definition(root: Path, pages: dict | None = None) -> Path:
    """Folder report definition minimal untuk uji usage."""
    report_def = root / "definition"
    (report_def / "pages").mkdir(parents=True, exist_ok=True)
    (report_def / "pages" / "pages.json").write_text(
        json.dumps(pages or {}), encoding="utf-8"
    )
    (report_def / "report.json").write_text("{}", encoding="utf-8")
    return report_def


class ReportUrlTests(unittest.TestCase):
    def test_powerbi_app_url(self) -> None:
        ref = parse_report_url(
            f"https://app.powerbi.com/groups/{WORKSPACE}/reports/{REPORT}/abc?ctid=1"
        )
        self.assertEqual(ref.workspace_id, WORKSPACE)
        self.assertEqual(ref.report_id, REPORT)

    def test_fabric_url(self) -> None:
        ref = parse_report_url(
            f"https://app.fabric.microsoft.com/groups/{WORKSPACE}/reports/{REPORT}"
        )
        self.assertEqual(ref.workspace_id, WORKSPACE)

    def test_manual_ids(self) -> None:
        ref = parse_report_url(f"{WORKSPACE} {REPORT}")
        self.assertEqual(ref.report_id, REPORT)
        ref = ServiceReportRef.from_ids(WORKSPACE, REPORT)
        self.assertEqual(ref.workspace_id, WORKSPACE)

    def test_my_workspace_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            parse_report_url(f"https://app.powerbi.com/groups/me/reports/{REPORT}")
        self.assertIn("My workspace", str(ctx.exception))

    def test_invalid_url_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            parse_report_url("https://app.powerbi.com/groups/abc/reports/def")


class DefinitionParsingTests(unittest.TestCase):
    def test_pbir_parts_and_model_reference(self) -> None:
        definition = _definition()
        self.assertEqual(definition.report_format, "PBIR")
        self.assertEqual(definition.model_reference, "model-123")
        self.assertFalse(any(part.path.startswith("StaticResources") for part in definition.parts))

    def test_non_base64_payload_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            parse_definition_response(
                {
                    "definition": {
                        "parts": [
                            {
                                "path": "definition/pages/pages.json",
                                "payload": "bukan base64!",
                                "payloadType": "InlineBase64",
                            }
                        ]
                    }
                }
            )
        self.assertIn("base64", str(ctx.exception).lower())

    def test_missing_parts_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            parse_definition_response({"definition": {"parts": []}})

    def test_materialize_pbir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_def = materialize_definition(_definition(), Path(tmp))
            self.assertEqual(report_def, Path(tmp) / "definition")
            self.assertTrue((report_def / "pages" / "pages.json").exists())
            visual = report_def / "pages" / "p1" / "visuals" / "v1" / "visual.json"
            self.assertTrue(visual.exists())

    def test_legacy_definition_is_rejected(self) -> None:
        legacy = parse_definition_response(
            {
                "definition": {
                    "parts": [
                        _part("report.json", "{}"),
                        _part("definition.pbir", "{}"),
                    ]
                }
            }
        )
        self.assertEqual(legacy.report_format, "PBIR-Legacy")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExtractionError) as ctx:
                materialize_definition(legacy, Path(tmp))
        self.assertIn("PBIR-Legacy", str(ctx.exception))

    def test_unsafe_path_is_rejected(self) -> None:
        definition = parse_definition_response(
            {
                "definition": {
                    "parts": [
                        _part("definition/../keluar.json", "{}"),
                        _part("definition/pages/pages.json", "{}"),
                    ]
                }
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExtractionError) as ctx:
                materialize_definition(definition, Path(tmp))
        self.assertIn("Unsafe", str(ctx.exception))


class FabricClientTests(unittest.TestCase):
    def _client(self, responses: list[FakeResponse], sleeps: list[float]) -> FabricReportClient:
        self.session = FakeSession(responses)
        return FabricReportClient(
            DummyTokens(),
            session=self.session,
            sleep=sleeps.append,
        )

    def test_direct_200(self) -> None:
        sleeps: list[float] = []
        client = self._client(
            [FakeResponse(200, {"definition": {"parts": _pbir_parts()}})], sleeps
        )
        definition = client.get_report_definition(ServiceReportRef.from_ids(WORKSPACE, REPORT))
        self.assertEqual(definition.report_format, "PBIR")
        self.assertEqual(sleeps, [])
        method, url, headers = self.session.calls[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith(f"/reports/{REPORT}/getDefinition"))
        self.assertEqual(headers["Authorization"], "Bearer token-fabric")

    def test_long_running_operation(self) -> None:
        sleeps: list[float] = []
        operation = "https://api.fabric.microsoft.com/v1/operations/op-1"
        client = self._client(
            [
                FakeResponse(202, None, {"Location": operation, "Retry-After": "1"}),
                FakeResponse(200, {"status": "Running"}),
                FakeResponse(200, {"status": "Succeeded"}),
                FakeResponse(200, {"definition": {"parts": _pbir_parts()}}),
            ],
            sleeps,
        )
        definition = client.get_report_definition(ServiceReportRef.from_ids(WORKSPACE, REPORT))
        self.assertEqual(definition.report_format, "PBIR")
        self.assertEqual(sleeps[0], 1)
        self.assertEqual(sleeps[1], 5)
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(self.session.calls[-1][1], operation + "/result")

    def test_update_definition_accepts_empty_operation_result(self) -> None:
        sleeps: list[float] = []
        operation = "https://api.fabric.microsoft.com/v1/operations/op-update"
        client = self._client(
            [
                FakeResponse(202, None, {"Location": operation, "Retry-After": "1"}),
                FakeResponse(200, {"status": "Running"}),
                FakeResponse(200, {"status": "Succeeded"}),
            ],
            sleeps,
        )
        result = client.update_report_definition(
            WORKSPACE, REPORT, [DefinitionPart("definition.pbir", b"{}")]
        )
        self.assertIsInstance(result, dict)
        urls = [url for _method, url, _headers in self.session.calls]
        self.assertNotIn(operation + "/result", urls)
        self.assertEqual(urls[-1], operation)

    def test_rejects_non_token_provider(self) -> None:
        with self.assertRaises(ExtractionError):
            FabricReportClient(object(), session=FakeSession([]))

    def test_semantic_model_tmsl(self) -> None:
        tmsl = {"name": "Model", "compatibilityLevel": 1702, "model": {}}
        payload = base64.b64encode(json.dumps(tmsl).encode("utf-8")).decode("ascii")
        sleeps: list[float] = []
        client = self._client(
            [
                FakeResponse(
                    200,
                    {
                        "definition": {
                            "parts": [
                                {
                                    "path": "model.bim",
                                    "payload": payload,
                                    "payloadType": "InlineBase64",
                                }
                            ]
                        }
                    },
                )
            ],
            sleeps,
        )
        data = client.get_semantic_model_tmsl(WORKSPACE, REPORT)
        self.assertEqual(data["compatibilityLevel"], 1702)
        method, url, _headers = self.session.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn(f"/semanticModels/{REPORT}/getDefinition", url)
        self.assertTrue(url.endswith("?format=TMSL"))

    def test_poll_wait_caps_initial_wait(self) -> None:
        sleeps: list[float] = []
        operation = "https://api.fabric.microsoft.com/v1/operations/op-fast"
        self.session = FakeSession(
            [
                FakeResponse(202, None, {"Location": operation, "Retry-After": "20"}),
                FakeResponse(200, {"definition": {"parts": _pbir_parts()}}),
            ]
        )
        client = FabricReportClient(
            DummyTokens(), session=self.session, sleep=sleeps.append, poll_wait=1.0
        )
        definition = client.get_report_definition(
            ServiceReportRef.from_ids(WORKSPACE, REPORT)
        )

        self.assertEqual(definition.report_format, "PBIR")
        self.assertEqual(sleeps, [1.0])

    def test_429_is_retried(self) -> None:
        sleeps: list[float] = []
        client = self._client(
            [
                FakeResponse(429, {"message": "terlalu banyak"}, {"Retry-After": "2"}),
                FakeResponse(200, {"definition": {"parts": _pbir_parts()}}),
            ],
            sleeps,
        )
        definition = client.get_report_definition(ServiceReportRef.from_ids(WORKSPACE, REPORT))
        self.assertEqual(definition.report_format, "PBIR")
        self.assertEqual(sleeps, [2])

    def test_403_reports_service_message(self) -> None:
        client = self._client(
            [FakeResponse(403, {"message": "Forbidden by tenant policy"})], []
        )
        with self.assertRaises(ExtractionError) as ctx:
            client.get_report_definition(ServiceReportRef.from_ids(WORKSPACE, REPORT))
        self.assertIn("403", str(ctx.exception))
        self.assertIn("Forbidden by tenant policy", str(ctx.exception))


class TokenProviderTests(unittest.TestCase):
    class FakeMsal:
        def __init__(self, result: dict) -> None:
            self.result = result
            self.calls = 0
            self.last_scopes: list[str] = []

        def acquire_token_for_client(self, scopes):
            self.calls += 1
            self.last_scopes = list(scopes)
            return self.result

    def test_service_principal_token_is_cached_per_scope(self) -> None:
        app = self.FakeMsal({"access_token": "token-sp", "expires_in": 3600})
        tokens = EntraTokens(
            ServicePrincipal.from_values("tenant", "client", "secret"),
            msal_app=app,
        )
        provider = MsalTokenProvider(tokens, FABRIC_SCOPE)
        self.assertEqual(provider.get_token(), "token-sp")
        self.assertEqual(provider.get_token(), "token-sp")
        self.assertEqual(app.calls, 1)
        self.assertEqual(app.last_scopes, [FABRIC_SCOPE])
        # Scope lain memakai credential yang sama tetapi token berbeda.
        tokens.get("scope-lain")
        self.assertEqual(app.calls, 2)
        self.assertEqual(tokens.get(FABRIC_SCOPE).value, "token-sp")

    def test_deferred_provider_does_not_build_until_needed(self) -> None:
        from core.auth import DeferredTokenProvider

        calls: list[int] = []

        class Provider:
            def get_token(self) -> str:
                return "deferred-token"

        provider = DeferredTokenProvider(lambda: calls.append(1) or Provider())
        self.assertEqual(calls, [])
        self.assertEqual(provider.get_token(), "deferred-token")
        self.assertEqual(provider.get_token(), "deferred-token")
        self.assertEqual(calls, [1])

    def test_service_principal_error_is_reported(self) -> None:
        app = self.FakeMsal({"error": "invalid_client", "error_description": "AADSTS7000215"})
        tokens = EntraTokens(
            ServicePrincipal.from_values("tenant", "client", "secret"),
            msal_app=app,
        )
        with self.assertRaises(ExtractionError) as ctx:
            tokens.get()
        self.assertIn("AADSTS7000215", str(ctx.exception))


class ServiceMetadataJobTests(unittest.TestCase):
    REF = ServiceReportRef.from_ids(WORKSPACE, REPORT)
    ENDPOINT = "powerbi://api.powerbi.com/v1.0/myorg/Test"

    def test_missing_token_provider_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            run_metadata_job(
                service_report=self.REF,
                extract_report=True,
                extract_model=False,
            )
        self.assertIn("Fabric token", str(ctx.exception))

    def test_nothing_selected_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            run_metadata_job(
                service_mode=True,
                extract_report=False,
                extract_model=False,
            )
        self.assertIn("both report and model scopes are disabled", str(ctx.exception))

    def test_model_without_endpoint_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            run_metadata_job(
                service_mode=True,
                extract_model=True,
                extract_report=False,
            )
        self.assertIn("No files were created", str(ctx.exception))

    def test_model_via_desktop_instance(self) -> None:
        captured: dict = {}

        def fake_run_model(**kwargs):
            captured.update(kwargs)
            write_minimal_model_workbook(Path(kwargs["out_file"]))
            return {"tables": 1}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.jobs.run_model", side_effect=fake_run_model):
                result = run_metadata_job(
                    service_mode=True,
                    port=51249,
                    catalog="instance-guid",
                    out_dir=Path(tmp),
                    extract_report=False,
                    extract_model=True,
                )
            self.assertEqual(result.output_count, 1)
            self.assertTrue(Path(tmp, "Semantic_Model_Metadata.xlsx").exists())
        self.assertEqual(captured["port"], 51249)
        self.assertIsNone(captured["endpoint"])

    def test_report_and_model_with_usage(self) -> None:
        definition = _definition()
        captured: dict = {}

        def fake_run_model(**kwargs):
            captured.update(kwargs)
            write_minimal_model_workbook(Path(kwargs["out_file"]))
            return {"tables": 1}

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "core.jobs.fetch_service_report_definition", return_value=definition
            ) as fetch, patch("core.jobs.run_model", side_effect=fake_run_model):
                result = run_metadata_job(
                    service_mode=True,
                    service_report=self.REF,
                    token_provider=DummyTokens(),
                    endpoint=self.ENDPOINT,
                    catalog="Model",
                    out_dir=Path(tmp),
                    include_report_usage=True,
                    extract_report=True,
                    extract_model=True,
                )
            self.assertEqual(result.output_count, 2)
            self.assertTrue(Path(tmp, "Report_Metadata.xlsx").exists())
            self.assertTrue(Path(tmp, "Semantic_Model_Metadata.xlsx").exists())
            self.assertEqual(result.report["pages"], 1)
            self.assertEqual(result.source.report_format, "PBIR")
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(captured["no_report"])
        self.assertIsNotNone(captured["report_definition"])
        self.assertEqual(
            captured["report_label"], f"report Power BI Service {REPORT}"
        )

    def test_model_only_without_report_or_token(self) -> None:
        captured: dict = {}

        def fake_run_model(**kwargs):
            captured.update(kwargs)
            write_minimal_model_workbook(Path(kwargs["out_file"]))
            return {"tables": 1}

        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.jobs.fetch_service_report_definition") as fetch, patch(
                "core.jobs.run_model", side_effect=fake_run_model
            ):
                result = run_metadata_job(
                    service_mode=True,
                    endpoint=self.ENDPOINT,
                    out_dir=Path(tmp),
                    extract_report=False,
                    extract_model=True,
                )
            self.assertEqual(result.output_count, 1)
            self.assertIsNone(result.report_out)
            self.assertFalse(Path(tmp, "Report_Metadata.xlsx").exists())
            self.assertTrue(Path(tmp, "Semantic_Model_Metadata.xlsx").exists())
            self.assertEqual(result.source.label, "Power BI Service (XMLA endpoint)")
        fetch.assert_not_called()
        self.assertTrue(captured["no_report"])
        self.assertIsNone(captured["report_definition"])


class ReportUsageSourceTests(unittest.TestCase):
    def test_definition_is_used_and_labelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report_def = write_report_definition(Path(tmp))
            measures, columns, source, available = _resolve_report_usage(
                report_def, Path("tidak-dipakai.pbix"), False, "report Power BI Service"
            )
        self.assertTrue(available)
        self.assertEqual(measures, {})
        self.assertEqual(columns, {})
        self.assertEqual(source, "report Power BI Service")

    def test_no_report_wins(self) -> None:
        measures, columns, source, available = _resolve_report_usage(
            None, None, True
        )
        self.assertFalse(available)
        self.assertIn("--no-report", source)

    def test_incomplete_definition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExtractionError) as ctx:
                _resolve_report_usage(Path(tmp), None, False)
        self.assertIn("Incomplete", str(ctx.exception))


class ServiceReportJobTests(unittest.TestCase):
    def test_writes_report_workbook_without_login(self) -> None:
        definition = _definition()
        client = FakeFabricClient(definition)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "Report_Metadata.xlsx"
            summary = run_service_report_job(
                ServiceReportRef.from_ids(WORKSPACE, REPORT),
                DummyTokens(),
                client=client,
                out_file=out,
                no_model=True,
            )
            self.assertEqual(summary["pages"], 1)
            self.assertEqual(summary["visuals"], 1)
            self.assertTrue(out.exists())
            with pd.ExcelFile(out) as workbook:
                self.assertEqual(len(workbook.sheet_names), 13)
        self.assertEqual(len(client.requests), 1)
        self.assertFalse(client.closed)
