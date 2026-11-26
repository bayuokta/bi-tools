"""Uji restore ZIP backup: validasi, daftar file, dan pemanggilan Fabric."""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.auth import ServicePrincipal
from core.errors import ExtractionError
from core.requests import RestoreRequest
from core.restore import (
    RestoreOptions,
    inspect_archive,
    list_restore_files,
    run_restore,
)

WORKSPACE = "11111111-2222-3333-4444-555555555555"
TARGET = "99999999-8888-7777-6666-555555555555"
PRINCIPAL = ServicePrincipal.from_values("tenant", "client", "secret")


def write_zip(path: Path, files: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    return path


def model_files(name: str = "Sales", *, platform: bool = True) -> dict[str, bytes]:
    files = {
        "definition/model.tmdl": b"model Model\n",
        "definition/tables/Sales.tmdl": b"table Sales\n",
        "definition.pbism": json.dumps({"version": "4.0", "settings": {}}).encode(),
        "model.bim": json.dumps({"name": name, "model": {"tables": []}}).encode(),
    }
    if platform:
        files[".platform"] = json.dumps(
            {"metadata": {"type": "SemanticModel", "displayName": name}}
        ).encode()
    return files


def report_files(name: str = "Overview") -> dict[str, bytes]:
    return {
        "definition.pbir": b"{}",
        "report.json": b"{}",
        ".platform": json.dumps(
            {"metadata": {"type": "Report", "displayName": name}}
        ).encode(),
        "StaticResources/SharedResources/BaseThemes/CY24SU10.json": b"{}",
    }


class TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.folder = self.root / "backups"


class InspectTests(TempCase):
    def test_model_archive_is_detected(self) -> None:
        path = write_zip(self.root / "semantic_model_Sales_aaaaaaaa.zip", model_files())
        info = inspect_archive(path)
        self.assertEqual(info.kind, "model")
        self.assertEqual(info.name, "Sales")
        self.assertTrue(info.has_model_bim)
        self.assertEqual(len(info.parts), 5)

    def test_report_archive_is_detected(self) -> None:
        path = write_zip(self.root / "report_Overview_bbbbbbbb.zip", report_files())
        info = inspect_archive(path)
        self.assertEqual(info.kind, "report")
        self.assertEqual(info.name, "Overview")

    def test_name_falls_back_to_file_name(self) -> None:
        path = write_zip(
            self.root / "semantic_model_My Model_aaaaaaaa.zip",
            model_files(platform=False),
        )
        self.assertEqual(inspect_archive(path).name, "My Model")

    def test_unsafe_path_is_rejected(self) -> None:
        path = write_zip(
            self.root / "bad.zip",
            {**model_files(), "../evil.txt": b"x"},
        )
        with self.assertRaises(ExtractionError):
            inspect_archive(path)

    def test_missing_model_part_is_rejected_in_strict_mode(self) -> None:
        path = write_zip(
            self.root / "broken.zip",
            {"definition.pbism": b"{}", ".platform": b"{}"},
        )
        with self.assertRaises(ExtractionError):
            inspect_archive(path)
        info = inspect_archive(path, strict=False)
        self.assertEqual(info.kind, "model")

    def test_invalid_model_bim_json_is_rejected(self) -> None:
        files = model_files()
        files["model.bim"] = b"{not-json"
        path = write_zip(self.root / "bad-model.zip", files)
        with self.assertRaises(ExtractionError):
            inspect_archive(path)


class ListFilesTests(TempCase):
    def test_lists_zip_from_manifest(self) -> None:
        run = self.folder / "Backup_Data_20261125_1200"
        write_zip(run / "report_Overview_bbbbbbbb.zip", report_files())
        (run / "manifest.json").write_text(
            json.dumps(
                {
                    "workspace": {"name": "Data"},
                    "finished_at": "2026-11-25T12:00:00",
                    "items": [
                        {
                            "kind": "report",
                            "name": "Overview",
                            "file": "report_Overview_bbbbbbbb.zip",
                            "status": "ok",
                            "size": 100,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        rows = list_restore_files(self.folder)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "report")
        self.assertEqual(rows[0]["workspace"], "Data")
        self.assertTrue(Path(rows[0]["path"]).is_file())


class RequestTests(TempCase):
    def test_requires_absolute_file_and_target_when_overwrite(self) -> None:
        with self.assertRaises(ExtractionError):
            RestoreRequest(file=Path("relatif.zip"), workspace_id=WORKSPACE)
        with self.assertRaises(ExtractionError):
            RestoreRequest(
                file=self.root / "a.zip",
                workspace_id=WORKSPACE,
                overwrite=True,
            )
        with self.assertRaises(ExtractionError):
            RestoreRequest(
                file=self.root / "a.zip",
                workspace_id=WORKSPACE,
                target_id=TARGET,
            )

    def test_payload_builds_options(self) -> None:
        write_zip(self.root / "a.zip", model_files())
        request = RestoreRequest.from_payload(
            {
                "file": str(self.root / "a.zip"),
                "workspace_id": WORKSPACE,
                "overwrite": True,
                "target_id": TARGET,
                "target_name": "Sales",
                "validate": False,
            }
        )
        self.assertTrue(request.overwrite)
        self.assertFalse(request.validate)
        self.assertEqual(request.to_options().target_name, "Sales")


class RunRestoreTests(TempCase):
    def test_create_model_strips_platform_and_renames(self) -> None:
        path = write_zip(self.root / "semantic_model_Sales_aaaaaaaa.zip", model_files())
        calls: dict[str, object] = {}

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def create_semantic_model(self, workspace_id, name, parts):
                calls["workspace"] = workspace_id
                calls["name"] = name
                calls["parts"] = [part.path for part in parts]
                return {"id": "new-model"}

            def close(self) -> None:
                pass

        options = RestoreOptions(
            file=path,
            workspace_id=WORKSPACE,
            workspace_name="Data Platform",
        )
        with patch("core.restore.FabricReportClient", FakeClient):
            result = run_restore(options, PRINCIPAL)
        self.assertEqual(result.action, "created")
        self.assertEqual(result.item_id, "new-model")
        self.assertIn("restored", calls["name"])
        self.assertNotIn(".platform", calls["parts"])
        self.assertNotIn("model.bim", calls["parts"])
        self.assertIn("definition/model.tmdl", calls["parts"])

    def test_tmsl_only_archive_selects_bim_and_pbism(self) -> None:
        path = write_zip(
            self.root / "semantic_model_Bim_aaaaaaaa.zip",
            {
                "model.bim": json.dumps({"name": "Bim", "model": {}}).encode(),
                "definition.pbism": b"{}",
                ".platform": json.dumps(
                    {"metadata": {"type": "SemanticModel", "displayName": "Bim"}}
                ).encode(),
            },
        )
        info = inspect_archive(path)
        self.assertEqual(info.kind, "model")
        calls: dict[str, object] = {}

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def create_semantic_model(self, workspace_id, name, parts):
                calls["parts"] = [part.path for part in parts]
                return {"id": "bim-id"}

            def close(self) -> None:
                pass

        options = RestoreOptions(
            file=path,
            workspace_id=WORKSPACE,
            workspace_name="Data",
        )
        with patch("core.restore.FabricReportClient", FakeClient):
            run_restore(options, PRINCIPAL)
        self.assertEqual(
            sorted(calls["parts"]), ["definition.pbism", "model.bim"]
        )

    def test_overwrite_uses_target_and_keeps_platform(self) -> None:
        path = write_zip(self.root / "report_Overview_bbbbbbbb.zip", report_files())
        calls: dict[str, object] = {}

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def update_report_definition(self, workspace_id, report_id, parts):
                calls["workspace"] = workspace_id
                calls["target"] = report_id
                calls["parts"] = [part.path for part in parts]
                return {}

            def close(self) -> None:
                pass

        options = RestoreOptions(
            file=path,
            workspace_id=WORKSPACE,
            workspace_name="Data",
            overwrite=True,
            target_id=TARGET,
            target_name="Overview PROD",
        )
        with patch("core.restore.FabricReportClient", FakeClient):
            result = run_restore(options, PRINCIPAL)
        self.assertEqual(result.action, "updated")
        self.assertEqual(result.display_name, "Overview PROD")
        self.assertEqual(calls["target"], TARGET)
        self.assertIn(".platform", calls["parts"])

    def test_api_failure_is_reported(self) -> None:
        path = write_zip(self.root / "semantic_model_Sales_aaaaaaaa.zip", model_files())

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def create_semantic_model(self, *args: object, **kwargs: object):
                raise ExtractionError("HTTP 400 skema TMDL ditolak")

            def close(self) -> None:
                pass

        options = RestoreOptions(
            file=path,
            workspace_id=WORKSPACE,
            workspace_name="Data",
        )
        with patch("core.restore.FabricReportClient", FakeClient):
            with self.assertRaises(ExtractionError) as ctx:
                run_restore(options, PRINCIPAL)
        self.assertIn("HTTP 400", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
