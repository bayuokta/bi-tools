"""Uji batch extraction report Power BI Service (tanpa jaringan/XMLA)."""

from __future__ import annotations

import contextlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.errors import ExtractionError
from core.fabric_api import ServiceReportRef
from core.jobs import run_metadata_job

WORKSPACE = "11111111-2222-3333-4444-555555555555"
REPORT_A = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
REPORT_B = "22222222-3333-4444-5555-666666666666"
REPORT_C = "33333333-4444-5555-6666-777777777777"


def ref(report_id: str, workspace: str = WORKSPACE) -> ServiceReportRef:
    return ServiceReportRef.from_ids(workspace, report_id)


class BatchExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = Path(self._tmp.name)
        self.work = self.out / "work"
        self.work.mkdir()

    def run_batch(self, refs, runner, names=None):
        client = patch("core.jobs.FabricReportClient")
        with client as client_cls, patch(
            "core.jobs.report_workspace",
            return_value=contextlib.nullcontext(self.work),
        ), patch(
            "core.jobs.materialize_definition", return_value=self.work
        ), patch(
            "core.jobs._run_report_from_definition", side_effect=runner
        ):
            client_cls.return_value.get_report_definition.return_value = (
                SimpleNamespace(report_format="PBIR")
            )
            return run_metadata_job(
                service_mode=True,
                service_reports=refs,
                extract_report=True,
                extract_model=False,
                include_report_usage=False,
                out_dir=self.out,
                token_provider=object(),
                service_report_names=names,
                log=lambda _message: None,
            )

    def test_batch_writes_one_folder_per_report_and_summary(self) -> None:
        refs = [ref(REPORT_A), ref(REPORT_B)]
        calls: list[Path] = []

        def runner(*_args, **kwargs):
            calls.append(kwargs["out_file"])
            return {"pages": 1, "visuals": 2, "fields": 3, "validation_issues": 0}

        result = self.run_batch(
            refs,
            runner,
            names={REPORT_A: "Report A", REPORT_B: "Report B"},
        )

        self.assertEqual(len(result.batch), 2)
        self.assertTrue(all(row["Status"] == "ok" for row in result.batch))
        self.assertEqual(
            [path.parent.name for path in calls],
            [
                f"Report A_{REPORT_A[:8]}",
                f"Report B_{REPORT_B[:8]}",
            ],
        )
        self.assertTrue(result.summary_out)
        self.assertTrue(Path(result.summary_out).exists())
        self.assertEqual(result.source.kind, "service_report")
        self.assertIn("batch 2 report", result.source.label)

    def test_batch_isolates_failure_and_continues(self) -> None:
        refs = [ref(REPORT_A), ref(REPORT_B), ref(REPORT_C)]
        calls: list[str] = []

        def runner(*_args, **kwargs):
            calls.append(kwargs["out_file"].parent.name)
            if len(calls) == 1:
                raise ExtractionError("definisi rusak")
            return {"pages": 1, "visuals": 1, "fields": 1, "validation_issues": 0}

        result = self.run_batch(refs, runner)
        statuses = [row["Status"] for row in result.batch]

        self.assertEqual(statuses, ["failed", "ok", "ok"])
        self.assertIn("definisi rusak", result.batch[0]["Message"])
        self.assertEqual(len(calls), 3)
        self.assertTrue(Path(result.summary_out).exists())

    def test_batch_requires_single_workspace(self) -> None:
        refs = [ref(REPORT_A), ref(REPORT_B, "99999999-8888-7777-6666-555555555555")]
        with self.assertRaises(ExtractionError):
            self.run_batch(refs, lambda *_args, **_kwargs: {})

    def test_single_report_keeps_single_result(self) -> None:
        with patch("core.jobs._run_service_metadata_job") as single:
            single.return_value = SimpleNamespace(batch=())
            result = run_metadata_job(
                service_mode=True,
                service_reports=[ref(REPORT_A)],
                extract_report=True,
                extract_model=False,
                out_dir=self.out,
                token_provider=object(),
                log=lambda _message: None,
            )
        single.assert_called_once()
        self.assertEqual(result.batch, ())


if __name__ == "__main__":
    unittest.main()
