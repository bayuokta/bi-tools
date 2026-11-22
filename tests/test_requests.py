"""Uji request GUI/CLI: pemetaan cakupan, validasi, dan parity dengan use case."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

from core.errors import ExtractionError
from core.jobs import run_metadata_job
from core.pbi_capture.runner import CaptureOptions
from core.requests import (
    SCOPE_BOTH,
    SCOPE_MODEL,
    SCOPE_REPORT,
    AnalysisRequest,
    CaptureRequest,
    CompareRequest,
    CompareSide,
    LocalMetadataRequest,
    ServiceMetadataRequest,
    TsdRequest,
    split_scope,
    validate_scope,
)
from core.tsd import run_tsd

WORKSPACE = "44444444-4444-4444-8444-444444444444"
REPORT = "55555555-5555-4555-8555-555555555555"


class ScopeTests(unittest.TestCase):
    def test_split_scope_maps_each_option(self) -> None:
        self.assertEqual(split_scope(SCOPE_BOTH), (True, True))
        self.assertEqual(split_scope(SCOPE_REPORT), (True, False))
        self.assertEqual(split_scope(SCOPE_MODEL), (False, True))

    def test_unknown_scope_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            validate_scope("everything")

    def test_empty_scope_defaults_to_both(self) -> None:
        self.assertEqual(validate_scope(""), SCOPE_BOTH)


class LocalRequestTests(unittest.TestCase):
    def test_paths_are_expanded_and_scope_flags_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = LocalMetadataRequest(
                out_dir=Path(tmp),
                scope=SCOPE_REPORT,
                pbix=Path(tmp) / "report.pbix",
                port=51234,
            )
            kwargs = request.to_job_kwargs()

        self.assertTrue(request.extract_report)
        self.assertFalse(request.extract_model)
        self.assertEqual(kwargs["port"], 51234)
        self.assertEqual(kwargs["extract_report"], True)
        self.assertEqual(kwargs["extract_model"], False)

    def test_negative_port_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            LocalMetadataRequest(out_dir=Path("."), port=0)

    def test_job_kwargs_match_use_case_signature(self) -> None:
        request = LocalMetadataRequest(out_dir=Path("."))
        self.assertLessEqual(
            set(request.to_job_kwargs()), set(inspect.signature(run_metadata_job).parameters)
        )


class ServiceRequestTests(unittest.TestCase):
    def test_report_scope_requires_valid_guids(self) -> None:
        with self.assertRaises(ExtractionError):
            ServiceMetadataRequest(
                out_dir=Path("."),
                workspace_id="not-a-guid",
                report_id=REPORT,
                scope=SCOPE_REPORT,
            )

    def test_model_only_ignores_report_fields(self) -> None:
        request = ServiceMetadataRequest(
            out_dir=Path("."),
            endpoint="powerbi://api.powerbi.com/v1.0/myorg/Uji",
            scope=SCOPE_MODEL,
        )
        self.assertFalse(request.extract_report)
        self.assertTrue(request.extract_model)
        self.assertIsNone(request.service_ref)

    def test_model_scope_requires_endpoint(self) -> None:
        with self.assertRaises(ExtractionError):
            ServiceMetadataRequest(
                out_dir=Path("."),
                workspace_id=WORKSPACE,
                report_id=REPORT,
                scope=SCOPE_BOTH,
            )

    def test_both_scope_builds_service_ref(self) -> None:
        request = ServiceMetadataRequest(
            out_dir=Path("."),
            workspace_id=WORKSPACE,
            report_id=REPORT,
            endpoint="powerbi://api.powerbi.com/v1.0/myorg/Uji",
            catalog="Uji",
        )
        kwargs = request.to_job_kwargs()
        self.assertTrue(kwargs["service_mode"])
        self.assertEqual(kwargs["service_report"].report_id, REPORT)
        self.assertEqual(kwargs["catalog"], "Uji")
        self.assertLessEqual(
            set(kwargs), set(inspect.signature(run_metadata_job).parameters)
        )

    def test_report_only_does_not_require_endpoint(self) -> None:
        request = ServiceMetadataRequest(
            out_dir=Path("."),
            workspace_id=WORKSPACE,
            report_id=REPORT,
            scope=SCOPE_REPORT,
        )
        self.assertFalse(request.extract_model)
        self.assertEqual(request.to_job_kwargs()["endpoint"], None)


class TsdRequestTests(unittest.TestCase):
    def test_non_xlsx_report_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            TsdRequest(report_workbook=Path("Report_Metadata.txt"))

    def test_generated_at_blank_becomes_none(self) -> None:
        request = TsdRequest(report_workbook=Path("Report_Metadata.xlsx"), generated_at=" ")
        self.assertIsNone(request.generated_at)

    def test_run_kwargs_match_use_case_signature(self) -> None:
        request = TsdRequest(report_workbook=Path("Report_Metadata.xlsx"))
        self.assertLessEqual(
            set(request.to_run_kwargs()), set(inspect.signature(run_tsd).parameters)
        )
        self.assertNotIn("capture", request.to_run_kwargs())

    def test_report_id_is_stripped_and_passed(self) -> None:
        request = TsdRequest(
            report_workbook=Path("Report_Metadata.xlsx"),
            report_id=" 66666666-6666-4666-8666-666666666666 ",
        )
        self.assertEqual(
            request.to_run_kwargs()["report_id"],
            "66666666-6666-4666-8666-666666666666",
        )


class CaptureRequestTests(unittest.TestCase):
    def test_options_carry_credentials_and_flags(self) -> None:
        workbook = Path("Report_Metadata.xlsx")
        request = CaptureRequest(
            workspace_id=WORKSPACE,
            report_id=REPORT,
            rls_username="AI_PowerBI_Prd",
            rls_roles=("HO", "Region"),
            scope="visuals",
            scale=2.0,
            headless=False,
            refresh=True,
            reveal_bookmarks=False,
            mobile=False,
            auto_install_browser=False,
            hints_workbook=workbook,
        )
        options = request.to_options()

        self.assertIsInstance(options, CaptureOptions)
        self.assertEqual(options.credentials.rls_username, "AI_PowerBI_Prd")
        self.assertEqual(options.credentials.rls_roles, ("HO", "Region"))
        self.assertEqual((options.scope, options.scale), ("visuals", 2.0))
        self.assertFalse(options.headless)
        self.assertTrue(options.refresh)
        self.assertFalse(options.reveal_bookmarks)
        self.assertFalse(options.mobile)
        self.assertFalse(options.auto_install_browser)
        self.assertEqual(options.hints_workbook, workbook)
        # Objek dekoratif dilewati secara default agar capture = filter TSD.
        self.assertIn("shape", options.exclude_visual_types)
        self.assertIn("textbox", options.exclude_visual_types)

    def test_decorative_visuals_can_be_included(self) -> None:
        request = CaptureRequest(
            workspace_id=WORKSPACE,
            report_id=REPORT,
            include_decorative=True,
        )
        options = request.to_options()
        self.assertEqual(options.exclude_visual_types, ())

    def test_invalid_scope_and_guid_are_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            CaptureRequest(workspace_id=WORKSPACE, report_id=REPORT, scope="all").to_options()
        with self.assertRaises(ExtractionError):
            CaptureRequest(workspace_id="x", report_id=REPORT).to_options()



DATASET = "77777777-7777-4777-8777-777777777777"


class AnalysisRequestTests(unittest.TestCase):
    def test_defaults_and_kwargs(self) -> None:
        request = AnalysisRequest(workspace_id=WORKSPACE, dataset_id=DATASET)
        payload = request.to_run_kwargs()

        self.assertTrue(request.include_other_workspaces)
        self.assertFalse(request.include_personal)
        self.assertFalse(request.refresh)
        self.assertIsNone(payload["max_reports"])
        self.assertEqual(payload["scan_workers"], 2)
        self.assertNotIn("database", payload)
        self.assertEqual(payload["dataset_id"], DATASET)

    def test_output_suffix_and_database(self) -> None:
        folder = Path(tempfile.mkdtemp())
        request = AnalysisRequest(
            workspace_id=WORKSPACE,
            dataset_id=DATASET,
            output=folder / "hasil",
            database=folder / "data" / "bi_tools.db",
            include_other_workspaces=False,
            refresh=True,
            max_reports=5,
        )

        self.assertEqual(request.output.name, "hasil.xlsx")
        payload = request.to_run_kwargs()
        self.assertEqual(payload["database"], folder / "data" / "bi_tools.db")
        self.assertFalse(payload["include_other_workspaces"])
        self.assertFalse(payload["include_personal"])
        self.assertTrue(payload["refresh"])
        self.assertEqual(payload["max_reports"], 5)

    def test_invalid_guid_and_limit_are_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            AnalysisRequest(workspace_id="x", dataset_id=DATASET)
        with self.assertRaises(ExtractionError):
            AnalysisRequest(workspace_id=WORKSPACE, dataset_id="bukan-guid")
        with self.assertRaises(ExtractionError):
            AnalysisRequest(workspace_id=WORKSPACE, dataset_id=DATASET, max_reports=0)
        for workers in (0, 5, "x"):
            with self.assertRaises(ExtractionError):
                AnalysisRequest(
                    workspace_id=WORKSPACE,
                    dataset_id=DATASET,
                    scan_workers=workers,
                )
        self.assertEqual(
            AnalysisRequest(
                workspace_id=WORKSPACE, dataset_id=DATASET, scan_workers=1
            ).to_run_kwargs()["scan_workers"],
            1,
        )

    def test_batch_report_ids_are_validated_and_mapped(self) -> None:
        refs = [
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "11111111-2222-3333-4444-555555555555",
        ]
        request = AnalysisRequest(
            workspace_id=WORKSPACE,
            dataset_id=DATASET,
            scan_workers=2,
        )
        self.assertEqual(request.to_run_kwargs()["scan_workers"], 2)

        from core.requests import ServiceMetadataRequest, MAX_BATCH_REPORTS

        batch = ServiceMetadataRequest(
            out_dir=Path(tempfile.mkdtemp()),
            workspace_id=WORKSPACE,
            report_ids=(refs[0], refs[1], refs[0]),
            scope="report",
        )
        self.assertEqual(batch.report_ids, tuple(refs))
        self.assertTrue(batch.batch)
        kwargs = batch.to_job_kwargs()
        self.assertEqual(len(kwargs["service_reports"]), 2)
        self.assertNotIn("service_report", kwargs)

        with self.assertRaises(ExtractionError):
            from uuid import uuid4

            ServiceMetadataRequest(
                out_dir=Path(tempfile.mkdtemp()),
                workspace_id=WORKSPACE,
                report_ids=tuple(
                    str(uuid4()) for _ in range(MAX_BATCH_REPORTS + 1)
                ),
            )
        with self.assertRaises(ExtractionError):
            ServiceMetadataRequest(
                out_dir=Path(tempfile.mkdtemp()),
                workspace_id=WORKSPACE,
                report_ids=("bukan-guid",),
            )
        with self.assertRaises(ExtractionError):
            ServiceMetadataRequest(
                out_dir=Path(tempfile.mkdtemp()),
                workspace_id=WORKSPACE,
                report_ids=(refs[0], refs[1]),
                scope="model",
                endpoint="powerbi://api.powerbi.com/v1.0/myorg/Contoh",
            )

    def test_kwargs_match_use_case(self) -> None:
        import core.usage_service as service

        params = set(inspect.signature(service.analyze_dataset).parameters)
        payload = AnalysisRequest(
            workspace_id=WORKSPACE,
            dataset_id=DATASET,
            workspace_name="Contoh - SO",
            dataset_name="Uji",
        ).to_run_kwargs()

        self.assertTrue(set(payload).issubset(params))
        self.assertIn("principal", params)


class CompareRequestTests(unittest.TestCase):
    def test_dataset_side_requires_valid_guids(self) -> None:
        with self.assertRaises(ExtractionError):
            CompareSide.from_payload({"type": "dataset", "workspace_id": "x"})

    def test_desktop_side_requires_port_and_catalog(self) -> None:
        with self.assertRaises(ExtractionError):
            CompareSide.from_payload({"type": "desktop", "port": 0, "catalog": "M"})
        with self.assertRaises(ExtractionError):
            CompareSide.from_payload({"type": "desktop", "port": 1234, "catalog": ""})

    def test_source_and_target_must_differ(self) -> None:
        side = {
            "type": "dataset",
            "workspace_id": WORKSPACE,
            "dataset_id": DATASET,
        }
        with self.assertRaises(ExtractionError):
            CompareRequest.from_payload({"source": side, "target": dict(side)})

    def test_payload_round_trip(self) -> None:
        payload = {
            "source": {
                "type": "dataset",
                "workspace_id": WORKSPACE,
                "dataset_id": DATASET,
            },
            "target": {"type": "desktop", "port": 1234, "catalog": "Model"},
            "options": {"measures": True, "roles": True},
        }
        request = CompareRequest.from_payload(payload)
        body = request.to_run_kwargs()
        self.assertEqual(body["source"]["workspace_id"], WORKSPACE)
        self.assertEqual(body["target"]["port"], 1234)
        self.assertEqual(body["options"]["roles"], True)


if __name__ == "__main__":
    unittest.main()
