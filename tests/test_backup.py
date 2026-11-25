"""Uji backup definisi model/report tanpa TOM, XMLA, atau jaringan."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.auth import ServicePrincipal
from core.backup import (
    BackupItem,
    BackupOptions,
    history,
    run_backup,
    safe_name,
    write_report_parts,
    write_zip,
)
from core.errors import ExtractionError
from core.fabric_api import DefinitionPart, ReportDefinition
from core.requests import BackupRequest

WORKSPACE = "11111111-2222-3333-4444-555555555555"
MODEL = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
REPORT = "22222222-3333-4444-5555-666666666666"
PRINCIPAL = ServicePrincipal.from_values("tenant", "client", "secret")


def item(kind: str, item_id: str, name: str, **kwargs: object) -> BackupItem:
    return BackupItem(kind=kind, item_id=item_id, name=name, **kwargs)


class SafeNameTests(unittest.TestCase):
    def test_strips_invalid_characters(self) -> None:
        self.assertEqual(safe_name('a/b:c*?"<>|'), "a_b_c_")
        self.assertEqual(safe_name("  Laporan  "), "Laporan")
        self.assertEqual(safe_name(""), "item")


class ZipTests(unittest.TestCase):
    def test_write_zip_keeps_relative_paths(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / "definition" / "pages").mkdir(parents=True)
        (root / "definition" / "pages" / "pages.json").write_text("{}", encoding="utf-8")
        (root / "model.bim").write_text("{}", encoding="utf-8")
        target = root / "out.zip"
        size = write_zip(root, target)
        self.assertGreater(size, 0)
        with zipfile.ZipFile(target) as archive:
            self.assertEqual(
                sorted(archive.namelist()),
                ["definition/pages/pages.json", "model.bim"],
            )

    def test_empty_folder_is_rejected(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        with self.assertRaises(ExtractionError):
            write_zip(root / "missing", root / "out.zip")


class ReportPartTests(unittest.TestCase):
    def test_writes_parts_and_rejects_traversal(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        definition = ReportDefinition(
            report_format="PBIR",
            parts=(
                DefinitionPart("definition/pages/pages.json", b"{}"),
                DefinitionPart("StaticResources/RegisteredResources/a.png", b"png"),
            ),
        )
        self.assertEqual(write_report_parts(definition, root), 2)
        self.assertTrue((root / "definition" / "pages" / "pages.json").is_file())

        unsafe = ReportDefinition(
            report_format="PBIR",
            parts=(DefinitionPart("../evil.json", b"{}"),),
        )
        with self.assertRaises(ExtractionError):
            write_report_parts(unsafe, root)


class RequestTests(unittest.TestCase):
    def test_requires_items_and_absolute_folder(self) -> None:
        with self.assertRaises(ExtractionError):
            BackupRequest.from_payload({"workspace_id": WORKSPACE, "items": []})
        with self.assertRaises(ExtractionError):
            BackupRequest.from_payload(
                {
                    "workspace_id": WORKSPACE,
                    "items": [{"kind": "model", "id": MODEL, "name": "Sales"}],
                    "folder": "relatif",
                }
            )

    def test_rejects_bad_kind_and_guid(self) -> None:
        with self.assertRaises(ExtractionError):
            item("dataset", MODEL, "Sales")
        with self.assertRaises(ExtractionError):
            BackupRequest.from_payload(
                {
                    "workspace_id": WORKSPACE,
                    "items": [{"kind": "model", "id": "bukan-guid", "name": "Sales"}],
                    "folder": "C:/backup",
                }
            ).to_options()

    def test_options_are_built(self) -> None:
        request = BackupRequest.from_payload(
            {
                "workspace_id": WORKSPACE,
                "workspace_name": "Data",
                "items": [
                    {"kind": "model", "id": MODEL, "name": "Sales"},
                    {"kind": "report", "id": REPORT, "name": "Overview"},
                ],
                "folder": "C:/backup",
            }
        )
        options = request.to_options()
        self.assertEqual(options.workspace_name, "Data")
        self.assertEqual(len(options.items), 2)
        self.assertEqual(options.items[0].kind, "model")


class RunBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.folder = self.root / "backups"

    def test_model_and_report_are_zipped_then_manifest_written(self) -> None:
        class FakeWorker:
            def export(self, target: str) -> dict:
                root = Path(target)
                (root / "definition").mkdir(parents=True, exist_ok=True)
                (root / "definition" / "model.tmdl").write_text("model", encoding="utf-8")
                (root / "model.bim").write_text("{}", encoding="utf-8")
                return {"files": 2, "bytes": 10}

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def get_report_definition(self, service: object) -> ReportDefinition:
                return ReportDefinition(
                    report_format="PBIR",
                    parts=(
                        DefinitionPart("definition/pages/pages.json", b"{}"),
                        DefinitionPart("definition/report.json", b"{}"),
                    ),
                )

            def close(self) -> None:
                pass

        options = BackupOptions(
            workspace_id=WORKSPACE,
            workspace_name="Data Platform",
            items=(
                item("model", MODEL, "Sales"),
                item("report", REPORT, "Overview"),
            ),
            folder=self.folder,
            prefix="Backup",
        )
        with patch("core.backup.get_tom_worker", return_value=FakeWorker()), patch(
            "core.backup.FabricReportClient", FakeClient
        ):
            result = run_backup(options, PRINCIPAL)

        self.assertEqual(result.ok_count, 2)
        names = sorted(row["file"] for row in result.payload()["items"])
        self.assertEqual(
            names,
            ["report_Overview_22222222.zip", "semantic_model_Sales_aaaaaaaa.zip"],
        )
        for row in result.payload()["items"]:
            self.assertTrue((result.run_dir / row["file"]).is_file())
        manifest = json.loads(result.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["workspace"]["name"], "Data Platform")
        self.assertEqual(manifest["totals"]["ok"], 2)
        with zipfile.ZipFile(result.run_dir / "semantic_model_Sales_aaaaaaaa.zip") as z:
            self.assertIn("definition/model.tmdl", z.namelist())
            self.assertIn("model.bim", z.namelist())

    def test_model_uses_fabric_definition_and_keeps_model_bim(self) -> None:
        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def get_semantic_model_definition(self, workspace_id, model_id):
                return ReportDefinition(
                    report_format="TMDL",
                    parts=(
                        DefinitionPart("definition/model.tmdl", b"model Model"),
                        DefinitionPart("definition.pbism", b"{}"),
                        DefinitionPart(".platform", b"{}"),
                    ),
                )

            def close(self) -> None:
                pass

        class FakeWorker:
            def export(self, target: str) -> dict:
                root = Path(target)
                (root / "definition").mkdir(parents=True, exist_ok=True)
                (root / "definition" / "model.tmdl").write_text("tom", encoding="utf-8")
                (root / "model.bim").write_text("{}", encoding="utf-8")
                return {"files": 2, "bytes": 2}

        options = BackupOptions(
            workspace_id=WORKSPACE,
            workspace_name="Data",
            items=(item("model", MODEL, "Sales"),),
            folder=self.folder,
        )
        with patch("core.backup.get_tom_worker", return_value=FakeWorker()), patch(
            "core.backup.FabricReportClient", FakeClient
        ):
            result = run_backup(options, PRINCIPAL)
        entry = result.payload()["items"][0]
        self.assertEqual(entry["source"], "fabric")
        with zipfile.ZipFile(result.run_dir / entry["file"]) as archive:
            names = archive.namelist()
        self.assertIn("definition/model.tmdl", names)
        self.assertIn("definition.pbism", names)
        self.assertIn(".platform", names)
        self.assertIn("model.bim", names)
        self.assertNotIn("_tom/definition/model.tmdl", names)

    def test_model_falls_back_to_tom(self) -> None:
        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def get_semantic_model_definition(self, workspace_id, model_id):
                raise ExtractionError("Fabric semantic model definition tidak tersedia")

            def close(self) -> None:
                pass

        class FakeWorker:
            def export(self, target: str) -> dict:
                root = Path(target)
                (root / "definition").mkdir(parents=True, exist_ok=True)
                (root / "definition" / "model.tmdl").write_text("tom", encoding="utf-8")
                (root / "model.bim").write_text("{}", encoding="utf-8")
                return {"files": 2, "bytes": 2}

        options = BackupOptions(
            workspace_id=WORKSPACE,
            workspace_name="Data",
            items=(item("model", MODEL, "Sales"),),
            folder=self.folder,
        )
        with patch("core.backup.get_tom_worker", return_value=FakeWorker()), patch(
            "core.backup.FabricReportClient", FakeClient
        ):
            result = run_backup(options, PRINCIPAL)
        entry = result.payload()["items"][0]
        self.assertEqual(entry["source"], "tom")
        with zipfile.ZipFile(result.run_dir / entry["file"]) as archive:
            self.assertTrue(any(name.startswith("definition/") for name in archive.namelist()))
            self.assertIn("definition.pbism", archive.namelist())

    def test_failed_item_does_not_stop_others(self) -> None:
        class FakeWorker:
            def export(self, target: str) -> dict:
                raise ExtractionError("XMLA read tidak tersedia")

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def get_report_definition(self, service: object) -> ReportDefinition:
                return ReportDefinition(
                    report_format="PBIR",
                    parts=(DefinitionPart("definition/report.json", b"{}"),),
                )

            def close(self) -> None:
                pass

        options = BackupOptions(
            workspace_id=WORKSPACE,
            workspace_name="Data",
            items=(
                item("model", MODEL, "Sales"),
                item("report", REPORT, "Overview"),
            ),
            folder=self.folder,
        )
        with patch("core.backup.get_tom_worker", return_value=FakeWorker()), patch(
            "core.backup.FabricReportClient", FakeClient
        ):
            result = run_backup(options, PRINCIPAL)

        statuses = {row["kind"]: row["status"] for row in result.payload()["items"]}
        self.assertEqual(statuses, {"model": "failed", "report": "ok"})
        self.assertIn("XMLA", result.payload()["items"][0]["message"])

    def test_cancel_marks_remaining_items_skipped(self) -> None:
        event = threading.Event()
        event.set()

        class FakeWorker:
            def export(self, target: str) -> dict:
                raise AssertionError("tidak boleh dipanggil saat dibatalkan")

        options = BackupOptions(
            workspace_id=WORKSPACE,
            workspace_name="Data",
            items=(item("model", MODEL, "Sales"),),
            folder=self.folder,
        )
        with patch("core.backup.get_tom_worker", return_value=FakeWorker()):
            result = run_backup(options, PRINCIPAL, cancel=event)
        self.assertEqual(result.items[0].status, "skipped")

    def test_history_reads_manifest(self) -> None:
        options = BackupOptions(
            workspace_id=WORKSPACE,
            workspace_name="Data",
            items=(item("report", REPORT, "Overview"),),
            folder=self.folder,
        )

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def get_report_definition(self, service: object) -> ReportDefinition:
                return ReportDefinition(
                    report_format="PBIR",
                    parts=(DefinitionPart("definition/report.json", b"{}"),),
                )

            def close(self) -> None:
                pass

        with patch("core.backup.FabricReportClient", FakeClient):
            run_backup(options, PRINCIPAL)
        rows = history(self.folder)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["workspace"], "Data")
        self.assertEqual(rows[0]["items"], 1)


if __name__ == "__main__":
    unittest.main()
