"""Uji presenter/endpoint Generate TSD (tanpa Playwright/network)."""

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
from server.presenters import tsd as presenter  # noqa: E402
from server.settings_store import SettingsStore  # noqa: E402
from tests.helpers import use_user  # noqa: E402

WORKSPACE = "11111111-2222-3333-4444-555555555555"
REPORT = "66666666-7777-8888-9999-000000000000"


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TsdPresenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out_dir = self.root / "out"
        self.out_dir.mkdir()
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        use_user(self.store)
        self.store.set("tsd/out_dir", str(self.out_dir))
        self.report = self.out_dir / "Report_Metadata.xlsx"
        self.report.write_bytes(b"xlsx")
        self.model = self.out_dir / "Semantic_Model_Metadata.xlsx"
        self.model.write_bytes(b"xlsx")
        self.template = self.root / "template.html"
        self.template.write_text("<html></html>", encoding="utf-8")

    def form(self, **changes: object) -> dict[str, object]:
        data: dict[str, object] = {
            "report_workbook": str(self.report),
            "model_workbook": str(self.model),
            "template_path": str(self.template),
            "out_dir": str(self.out_dir),
            "report_name": "Report Uji",
            "draft": True,
            "screenshots": False,
        }
        data.update(changes)
        return data

    def test_paths_auto_name_and_sidecar(self) -> None:
        data = presenter.normalize(self.store, self.form(report_id=REPORT[:8]))
        paths = presenter.paths_for(data)
        self.assertEqual(paths["out_file"].name, "TSD_Report Uji_66666666.html")
        self.assertEqual(paths["manual_file"].name, "TSD_Report Uji_66666666.json")
        self.assertEqual(
            paths["assets_dir"].name, "Report_Uji_66666666"
        )

    def test_normalize_scopes_and_rls(self) -> None:
        data = presenter.normalize(
            self.store,
            {
                "screenshots": True,
                "shot_scope": "salah",
                "shot_scale": "2",
                "rls_username": "u",
                "rls_roles": "HO, Region",
                "workspace_id": WORKSPACE,
                "report_id": REPORT,
            },
        )
        self.assertEqual(data["shot_scope"], "both")
        self.assertEqual(data["shot_scale"], 2.0)
        self.assertEqual(data["rls_roles"], "HO,Region")
        self.assertTrue(data["screenshots"])

    def test_build_request_requires_report(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            presenter.build_request(
                self.store,
                presenter.normalize(self.store, {"report_workbook": ""}),
            )
        self.assertIn("Report_Metadata", str(ctx.exception))
        with self.assertRaises(ExtractionError):
            presenter.build_request(
                self.store,
                presenter.normalize(
                    self.store,
                    self.form(report_workbook=str(self.root / "tidak-ada.xlsx")),
                ),
            )

    def test_build_request_local_render(self) -> None:
        request, capture, paths = presenter.build_request(
            self.store, presenter.normalize(self.store, self.form())
        )
        self.assertIsNone(capture)
        self.assertEqual(request.report_workbook, self.report)
        self.assertEqual(request.model_workbook, self.model)
        self.assertTrue(request.draft)
        self.assertEqual(paths["out_file"].suffix, ".html")

    def test_build_request_screenshots_need_workspace_report(self) -> None:
        with self.assertRaises(ExtractionError) as ctx:
            presenter.build_request(
                self.store,
                presenter.normalize(self.store, self.form(screenshots=True)),
            )
        self.assertIn("workspace dan report", str(ctx.exception))

    def test_build_request_screenshots_builds_capture(self) -> None:
        request, capture, _paths = presenter.build_request(
            self.store,
            presenter.normalize(
                self.store,
                self.form(
                    screenshots=True,
                    workspace_id=WORKSPACE,
                    report_id=REPORT,
                    shot_scope="pages",
                    shot_scale=2,
                    shot_mobile=False,
                    include_decorative=True,
                ),
            ),
        )
        self.assertIsNotNone(capture)
        self.assertEqual(capture.workspace_id, WORKSPACE)
        self.assertEqual(capture.report_id, REPORT)
        self.assertEqual(capture.scope, "pages")
        self.assertEqual(capture.scale, 2.0)
        self.assertFalse(capture.mobile)
        self.assertEqual(capture.exclude_visual_types, ())

    def test_run_job_summary_and_preferences(self) -> None:
        fake = {
            "output": self.out_dir / "TSD.html",
            "manual": self.out_dir / "TSD.json",
            "pages": 10,
            "visuals": 101,
            "todos": 2,
            "size": 1234,
            "screenshot_pages": 0,
            "screenshot_visuals": 0,
            "screenshot_mobile": 0,
            "screenshot_missing": 0,
            "screenshot_root": None,
        }
        with patch.object(presenter, "run_tsd", return_value=fake) as run:
            summary = presenter.run_job(
                self.store, self.form(), lambda _line: None, None
            )
        self.assertEqual(summary["pages"], 10)
        self.assertEqual(summary["output"], str(fake["output"]))
        self.assertIn("state", summary)
        self.assertTrue(run.called)
        self.assertEqual(
            self.store.get_str("tsd/report_workbook"), str(self.report)
        )

    def test_capture_job_summary(self) -> None:
        result = SimpleNamespace(
            root=self.out_dir / "assets",
            page_count=3,
            visual_count=20,
            mobile_count=1,
            missing=("a",),
            warnings=("w",),
            captured_at="2026-11-18T12:00:00",
        )
        with patch.object(presenter, "capture_report", return_value=result):
            summary = presenter.capture_job(
                self.store,
                self.form(
                    screenshots=True,
                    workspace_id=WORKSPACE,
                    report_id=REPORT,
                ),
                lambda _line: None,
                None,
            )
        self.assertEqual(summary["pages"], 3)
        self.assertEqual(summary["visuals"], 20)
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(summary["warnings"], ["w"])

    def test_clear_cache(self) -> None:
        data = presenter.normalize(
            self.store, self.form(report_id=REPORT, screenshots=True,
                                  workspace_id=WORKSPACE)
        )
        assets = presenter.paths_for(data)["assets_dir"]
        assets.mkdir(parents=True)
        (assets / "manifest.json").write_text("{}", encoding="utf-8")

        result = presenter.clear_cache(self.store, self.form(report_id=REPORT))
        self.assertTrue(result["removed"])
        self.assertFalse(assets.exists())
        again = presenter.clear_cache(self.store, self.form(report_id=REPORT))
        self.assertFalse(again["removed"])

    def test_manual_roundtrip(self) -> None:
        state = presenter.manual_state(self.store, self.form())
        self.assertFalse(state["exists"])
        path = state["path"]
        saved = presenter.save_manual_file(
            self.store, path, {"meta": {"draft": False}}
        )
        self.assertTrue(saved["exists"])
        loaded = presenter.manual_state(self.store, {"manual_path": path})
        self.assertEqual(loaded["data"]["meta"]["draft"], False)
        with self.assertRaises(ExtractionError):
            presenter.save_manual_file(self.store, str(self.root / "x.txt"), {})

    def test_preview_only_html_inside_output(self) -> None:
        target = self.out_dir / "TSD.html"
        target.write_text("<html>ok</html>", encoding="utf-8")
        self.assertEqual(
            presenter.preview_path(self.store, str(target)), target.resolve()
        )
        outside = self.root / "luar.html"
        outside.write_text("x", encoding="utf-8")
        with self.assertRaises(ExtractionError):
            presenter.preview_path(self.store, str(outside))
        with self.assertRaises(ExtractionError):
            presenter.preview_path(self.store, str(self.root / "x.txt"))


class TsdEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out_dir = self.root / "out"
        self.out_dir.mkdir()
        self.store = SettingsStore(
            self.root / "settings.json", registry_reader=lambda: {}
        )
        self.store.set("tsd/out_dir", str(self.out_dir))
        self.report = self.out_dir / "Report_Metadata.xlsx"
        self.report.write_bytes(b"xlsx")
        self.template = self.root / "template.html"
        self.template.write_text("<html></html>", encoding="utf-8")
        web = self.root / "web"
        web.mkdir()
        (web / "index.html").write_text("ok", encoding="utf-8")
        self.app = create_app(settings_store=self.store, web_root=web)
        self.client = TestClient(self.app)

    def payload(self, **changes: object) -> dict[str, object]:
        data: dict[str, object] = {
            "report_workbook": str(self.report),
            "template_path": str(self.template),
            "out_dir": str(self.out_dir),
            "report_name": "Report Uji",
            "screenshots": False,
        }
        data.update(changes)
        return data

    def test_state_defaults(self) -> None:
        response = self.client.get("/api/tsd/state")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("form", body)
        self.assertEqual(body["paths"]["out_dir"], str(self.out_dir))
        self.assertTrue(body["checklist"]["template"])

    def test_inspect_with_payload(self) -> None:
        response = self.client.post("/api/tsd/state", json=self.payload())
        body = response.json()
        self.assertTrue(body["status"]["report"]["exists"])
        self.assertEqual(body["paths"]["out_name"], "TSD_Report Uji.html")

    def test_run_rejects_missing_report(self) -> None:
        response = self.client.post(
            "/api/tsd/run",
            json={"out_dir": str(self.out_dir), "report_workbook": ""},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Report_Metadata", response.json()["detail"])

    def test_run_starts_job(self) -> None:
        def fake_job(store, payload, log, cancel):
            log("render")
            return {"ok": True}

        with patch.object(presenter, "run_job", fake_job):
            response = self.client.post("/api/tsd/run", json=self.payload())
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

    def test_capture_requires_selection(self) -> None:
        response = self.client.post(
            "/api/tsd/capture", json=self.payload(screenshots=True)
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("workspace dan report", response.json()["detail"])

    def test_manual_endpoints(self) -> None:
        state = self.client.get("/api/tsd/manual").json()
        path = state["path"]
        saved = self.client.put(
            "/api/tsd/manual", json={"path": path, "data": {"meta": {"draft": True}}}
        )
        self.assertEqual(saved.status_code, 200)
        loaded = self.client.get("/api/tsd/manual", params={"path": path}).json()
        self.assertEqual(loaded["data"]["meta"]["draft"], True)

    def test_preview_endpoint_and_csp(self) -> None:
        target = self.out_dir / "TSD.html"
        target.write_text("<html><body>ok</body></html>", encoding="utf-8")
        response = self.client.get("/api/tsd/preview", params={"path": str(target)})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("default-src 'none'", response.headers["content-security-policy"])
        self.assertIn("no-store", response.headers["cache-control"])

    def test_cache_clear_endpoint(self) -> None:
        response = self.client.post(
            "/api/tsd/cache/clear", json=self.payload(report_id=REPORT)
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["removed"])


if __name__ == "__main__":
    unittest.main()
