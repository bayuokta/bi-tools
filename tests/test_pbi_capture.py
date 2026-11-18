"""Uji capture screenshot Power BI Service tanpa network/Playwright.

Semua bagian berat (embed token, browser) diganti tiruan; yang diuji adalah
pemetaan manifest, penamaan file, cache, dan validasi opsi.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from core.errors import ExtractionError
from core.pbi_capture.assets import (
    ScreenshotSet,
    build_items,
    data_uri,
    slug,
)
from core.pbi_capture.cache import (
    CAPTURE_VERSION,
    cache_dir,
    load_screenshot_set,
    write_capture,
)
from core.pbi_capture.capture import (
    ReportCapturer,
    mobile_viewport,
    pair_visuals_to_rects,
)
from core.pbi_capture.credentials import CaptureCredentials, split_roles
from core.pbi_capture.hints import load_layout_hints
from core.pbi_capture.runner import CaptureOptions, capture_report, load_or_capture

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-bytes"
WORKSPACE = "11111111-1111-4111-8111-111111111111"
REPORT = "22222222-2222-4222-8222-222222222222"


def manifest() -> dict:
    return {
        "workspaceId": WORKSPACE,
        "reportId": REPORT,
        "generatedAt": "2026-11-14T00:00:00+00:00",
        "source": "embedded-client",
        "pages": [
            {
                "name": "p1",
                "displayName": "Overview",
                "isActive": True,
                "ordinal": 1,
                "visuals": [
                    {"name": "v1", "type": "barChart", "title": "Sales by Region"},
                    {"name": "v2", "type": "card", "title": "KPI"},
                ],
            },
            {
                "name": "p2",
                "displayName": "Detail",
                "isActive": False,
                "ordinal": 2,
                "visuals": [
                    {"name": "v3", "type": "tableEx", "title": "Table"},
                ],
            },
        ],
    }


class AssetTests(unittest.TestCase):
    def test_slug_is_file_safe(self) -> None:
        self.assertEqual(slug("Data Acquisition / Insight: 2W"), "Data_Acquisition_Insight_2W")
        self.assertEqual(slug("   "), "untitled")

    def test_build_items_names_pages_and_visuals(self) -> None:
        items, skipped = build_items(manifest(), Path("out"))
        self.assertEqual(skipped, [])
        pages = [item for item in items if item.kind == "page"]
        visuals = [item for item in items if item.kind == "visual"]
        self.assertEqual(
            [item.output_path.as_posix() for item in pages],
            ["out/pages/01_Overview.png", "out/pages/02_Detail.png"],
        )
        self.assertEqual(
            [item.output_path.as_posix() for item in visuals],
            [
                "out/visuals/01_Overview/Sales_by_Region.png",
                "out/visuals/01_Overview/KPI.png",
                "out/visuals/02_Detail/Table.png",
            ],
        )

    def test_build_items_scope_and_exclude(self) -> None:
        pages_only, empty = build_items(manifest(), Path("out"), scope="pages")
        self.assertEqual(empty, [])
        self.assertTrue(all(item.kind == "page" for item in pages_only))

        visuals, skipped = build_items(
            manifest(), Path("out"), scope="visuals", exclude_visual_types=["card"]
        )
        self.assertEqual(len(visuals), 2)
        self.assertEqual([item["visualName"] for item in skipped], ["v2"])

    def test_build_items_adds_mobile_only_for_pages_with_layout(self) -> None:
        data = manifest()
        data["pages"][0]["mobileLayout"] = True
        items, _skipped = build_items(data, Path("out"), scope="pages")
        mobile = [item for item in items if item.kind == "mobile"]
        self.assertEqual(
            [item.output_path.as_posix() for item in mobile],
            ["out/mobile/01_Overview.png"],
        )

    def test_build_items_deduplicates_titles(self) -> None:
        data = manifest()
        data["pages"][0]["visuals"].append(
            {"name": "v9", "type": "card", "title": "KPI"}
        )
        items, _skipped = build_items(data, Path("out"))
        names = [item.output_path.name for item in items if item.kind == "visual"]
        self.assertIn("KPI.png", names)
        self.assertIn("KPI_v9.png", names)

    def test_data_uri_is_base64_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.png"
            path.write_bytes(PNG)
            self.assertTrue(data_uri(path).startswith("data:image/png;base64,"))


class CacheTests(unittest.TestCase):
    def test_cache_dir_appends_report_id(self) -> None:
        base = Path("out")
        self.assertEqual(
            cache_dir(base, "Uji", REPORT).as_posix(),
            "out/TSD_assets/Uji_22222222",
        )
        self.assertEqual(
            cache_dir(base, "Uji").as_posix(), "out/TSD_assets/Uji"
        )
        self.assertEqual(
            cache_dir(base, "Report Uji", REPORT).name,
            "Report_Uji_22222222",
        )

    def _write(self, root: Path, scope: str = "both") -> ScreenshotSet:
        return write_capture(
            root,
            manifest(),
            {"p1": PNG, "p2": PNG},
            {("p1", "v1"): PNG, ("p1", "v2"): PNG},
            scope=scope,
            workspace_id=WORKSPACE,
            report_id=REPORT,
            rls_username="AI_PowerBI_Prd",
            rls_roles=("HO",),
        )

    def test_roundtrip_and_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            created = self._write(root)
            self.assertEqual(created.page_count, 2)
            self.assertEqual(created.visual_count, 2)
            self.assertTrue((root / "manifest.json").exists())
            self.assertTrue((root / "capture.json").exists())
            meta = json.loads((root / "capture.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["captureVersion"], CAPTURE_VERSION)

            loaded = load_screenshot_set(root)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.page("p1"), root / "pages" / "01_Overview.png")
            self.assertEqual(
                loaded.visual("p1", "v2"), root / "visuals" / "01_Overview" / "KPI.png"
            )
            self.assertEqual(loaded.rls_roles, ("HO",))

    def test_mobile_roundtrip_and_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            data = manifest()
            data["pages"][0]["mobileLayout"] = True
            created = write_capture(
                root,
                data,
                {"p1": PNG, "p2": PNG},
                {},
                {"p1": PNG},
                scope="pages",
                workspace_id=WORKSPACE,
                report_id=REPORT,
                mobile_enabled=True,
            )
            self.assertEqual(created.mobile_count, 1)
            self.assertEqual(
                created.mobile_page("p1"), root / "mobile" / "01_Overview.png"
            )
            self.assertTrue(created.mobile_enabled)
            self.assertTrue(created.matches(WORKSPACE, REPORT, "pages", require_mobile=True))
            self.assertFalse(
                self._write(Path(tmp) / "other", scope="pages").matches(
                    WORKSPACE, REPORT, "pages", require_mobile=True
                )
            )

    def test_old_capture_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            self._write(root)
            data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            data.pop("captureVersion", None)
            (root / "manifest.json").write_text(
                json.dumps(data), encoding="utf-8"
            )
            self.assertIsNone(load_screenshot_set(root))

    def test_lookup_falls_back_to_titles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            created = self._write(root)
            # ID berbeda (versi report lain) -> cocok lewat judul.
            self.assertEqual(
                created.page("unknown", "Overview"),
                root / "pages" / "01_Overview.png",
            )
            self.assertEqual(
                created.visual("unknown", "unknown", "KPI", "Overview"),
                root / "visuals" / "01_Overview" / "KPI.png",
            )
            self.assertIsNone(created.visual("p1", "unknown", "Tidak Ada"))

    def test_missing_files_are_not_in_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            write_capture(
                root,
                manifest(),
                {"p1": PNG},
                {},
                scope="both",
                workspace_id=WORKSPACE,
                report_id=REPORT,
            )
            loaded = load_screenshot_set(root)
            assert loaded is not None
            self.assertEqual(loaded.page_count, 1)
            self.assertEqual(loaded.visual_count, 0)
            self.assertIn("p2", loaded.page_titles)

    def test_legacy_manifest_without_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            created = self._write(root)
            import json

            legacy = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            for page in legacy["pages"]:
                page.pop("output", None)
                for visual in page["visuals"]:
                    visual.pop("output", None)
            (root / "manifest.json").write_text(
                json.dumps(legacy), encoding="utf-8"
            )
            loaded = load_screenshot_set(root)
            assert loaded is not None
            self.assertEqual(loaded.page_count, created.page_count)
            self.assertEqual(loaded.visual_count, created.visual_count)

    def test_matches_requires_same_report_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = self._write(Path(tmp) / "shots", scope="pages")
            self.assertTrue(created.matches(WORKSPACE, REPORT, "pages"))
            self.assertFalse(created.matches(WORKSPACE, REPORT, "both"))
            self.assertFalse(created.matches(WORKSPACE, "00000000-0000-0000-0000-000000000000", "pages"))


class OptionTests(unittest.TestCase):
    def test_invalid_guid_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            CaptureOptions(workspace_id="bukan-guid", report_id=REPORT)
        with self.assertRaises(ExtractionError):
            CaptureOptions(workspace_id=WORKSPACE, report_id="123")

    def test_invalid_scope_and_scale_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            CaptureOptions(workspace_id=WORKSPACE, report_id=REPORT, scope="semua")
        with self.assertRaises(ExtractionError):
            CaptureOptions(workspace_id=WORKSPACE, report_id=REPORT, scale=9)

    def test_roles_are_split(self) -> None:
        self.assertEqual(split_roles("HO, Region;X"), ("HO", "Region", "X"))
        self.assertEqual(split_roles(["HO", " ", "Region"]), ("HO", "Region"))
        self.assertEqual(split_roles(None), ())

    def test_reveal_bookmarks_default_is_on(self) -> None:
        options = CaptureOptions(workspace_id=WORKSPACE, report_id=REPORT)
        self.assertTrue(options.reveal_bookmarks)

    def test_mobile_default_is_on(self) -> None:
        options = CaptureOptions(workspace_id=WORKSPACE, report_id=REPORT)
        self.assertTrue(options.mobile)
        off = CaptureOptions(
            workspace_id=WORKSPACE, report_id=REPORT, mobile=False
        )
        self.assertFalse(off.mobile)

    def test_mobile_viewport_uses_page_size_or_default(self) -> None:
        self.assertEqual(mobile_viewport({"width": 390, "height": 844}), (390, 844))
        self.assertEqual(mobile_viewport(None), (375, 667))
        self.assertEqual(mobile_viewport({"width": 0, "height": "x"}), (375, 667))
        self.assertEqual(mobile_viewport({"width": 5000, "height": 9999}), (1200, 4000))


class PairingTests(unittest.TestCase):
    def test_hidden_visual_does_not_borrow_far_decorative_rect(self) -> None:
        visuals = [
            {
                "name": "v",
                "title": "Main Dealer",
                "layout": {"x": 24, "y": 222, "width": 226, "height": 70},
            }
        ]
        rects = [{"i": 0, "x": 16, "y": 0, "w": 228, "h": 72, "label": "Logo"}]
        self.assertIsNone(pair_visuals_to_rects(visuals, rects)["v"])

    def test_near_rect_is_matched(self) -> None:
        visuals = [
            {
                "name": "v",
                "title": "",
                "layout": {"x": 100, "y": 100, "width": 200, "height": 80},
            }
        ]
        rects = [{"i": 0, "x": 104, "y": 98, "w": 202, "h": 82, "label": ""}]
        self.assertIsNotNone(pair_visuals_to_rects(visuals, rects)["v"])

    def test_label_match_wins_even_when_position_differs(self) -> None:
        visuals = [
            {
                "name": "v",
                "title": "KPI",
                "layout": {"x": 0, "y": 500, "width": 200, "height": 80},
            }
        ]
        rects = [{"i": 0, "x": 0, "y": 0, "w": 200, "h": 80, "label": "KPI"}]
        mapping = pair_visuals_to_rects(visuals, rects)
        self.assertEqual(mapping["v"]["i"], 0)

    def test_exact_label_beats_substring(self) -> None:
        visuals = [
            {
                "name": "dealer",
                "title": "Dealer",
                "layout": {"x": 25, "y": 298, "width": 227, "height": 70},
            },
            {
                "name": "main",
                "title": "Main Dealer",
                "layout": {"x": 25, "y": 222, "width": 227, "height": 70},
            },
        ]
        rects = [
            {"i": 0, "x": 1037, "y": 222, "w": 227, "h": 70, "label": "Main Dealer"},
            {"i": 1, "x": 1037, "y": 298, "w": 227, "h": 70, "label": "Dealer"},
        ]
        mapping = pair_visuals_to_rects(visuals, rects)
        self.assertEqual(mapping["dealer"]["i"], 1)
        self.assertEqual(mapping["main"]["i"], 0)

    def test_far_leftover_is_not_assigned_by_reading_order(self) -> None:
        visuals = [
            {
                "name": "a",
                "title": "",
                "layout": {"x": 0, "y": 0, "width": 100, "height": 50},
            },
            {
                "name": "b",
                "title": "",
                "layout": {"x": 500, "y": 500, "width": 100, "height": 50},
            },
        ]
        rects = [
            {"i": 0, "x": 0, "y": 0, "w": 100, "h": 50, "label": ""},
            {"i": 1, "x": 900, "y": 600, "w": 100, "h": 50, "label": ""},
        ]
        mapping = pair_visuals_to_rects(visuals, rects)
        self.assertEqual(mapping["a"]["i"], 0)
        self.assertIsNone(mapping["b"])

    def test_grouped_visual_matches_by_unique_size(self) -> None:
        # Di dalam group, layout memakai koordinat relatif sehingga posisi
        # prediksi (0,0) jauh dari elemen sebenarnya di (229,73).
        visuals = [
            {
                "name": "card",
                "title": "Card",
                "layout": {"x": 0, "y": 0, "width": 1097, "height": 89},
            },
            {
                "name": "chart",
                "title": "Trend",
                "layout": {"x": 190, "y": 148, "width": 1084, "height": 218},
            },
        ]
        rects = [
            {"i": 0, "x": 229, "y": 73, "w": 1371, "h": 111, "label": ""},
            {"i": 1, "x": 238, "y": 186, "w": 1354, "h": 272, "label": "Trend"},
        ]

        mapping = pair_visuals_to_rects(visuals, rects, scale=1.253)

        self.assertEqual(mapping["card"]["i"], 0)
        self.assertEqual(mapping["chart"]["i"], 1)

    def test_unique_size_is_ignored_when_another_visual_shares_it(self) -> None:
        visuals = [
            {
                "name": "a",
                "title": "",
                "layout": {"x": 0, "y": 0, "width": 16, "height": 25},
            },
            {
                "name": "b",
                "title": "",
                "layout": {"x": 50, "y": 0, "width": 16, "height": 25},
            },
        ]
        rects = [{"i": 0, "x": 900, "y": 600, "w": 20, "h": 32, "label": ""}]

        mapping = pair_visuals_to_rects(visuals, rects, scale=1.253)

        self.assertIsNone(mapping["a"])
        self.assertIsNone(mapping["b"])


class ProbeRevealTests(unittest.TestCase):
    class _Frame:
        def evaluate(self, _script):
            return {
                "selector": ".visualContainer",
                "rects": [
                    {"i": 0, "x": 0, "y": 0, "w": 100, "h": 100, "label": "Dealer"}
                ],
            }

    def _capturer(self, active_pages: list[str], capture_counts: list[int]):
        capturer = ReportCapturer.__new__(ReportCapturer)
        capturer._log = lambda _message: None
        bookmarks = [
            {"name": f"bm{i}", "displayName": f"Bookmark {i}"}
            for i in range(len(active_pages))
        ]
        capturer.get_bookmarks = lambda: bookmarks
        capturer.save_bookmark_state = lambda: True
        restored: list[int] = []
        capturer.restore_bookmark_state = lambda timeout_ms=None: (
            restored.append(1) or True
        )
        pages = iter(active_pages)
        counts = iter(capture_counts)
        capturer.apply_bookmark = lambda name, timeout_ms=None: True
        capturer.active_page_name = lambda: next(pages, "")
        capturer._report_frame = lambda: self._Frame()
        capturer._capture_mapping = (
            lambda frame, selector, mapping, target: next(counts, 0)
        )
        capturer.restored = restored
        return capturer

    def test_skips_bookmark_that_navigates_and_uses_revealing_one(self) -> None:
        capturer = self._capturer(["page-a", "page-b"], [2])
        result = {"visual_pngs": {}}
        missing = [
            {
                "name": "v",
                "title": "Dealer",
                "layout": {"x": 0, "y": 0, "width": 100, "height": 100},
            }
        ]
        captured = capturer._probe_reveal("page-b", missing, 1.0, result)
        self.assertTrue(captured)
        self.assertEqual(result["revealed_bookmark"], "bm1")
        self.assertGreaterEqual(len(capturer.restored), 2)

    def test_returns_false_when_no_bookmark_reveals(self) -> None:
        capturer = self._capturer(["page-a", "page-a"], [0])
        result = {"visual_pngs": {}, "revealed_bookmark": ""}
        missing = [
            {
                "name": "v",
                "title": "Dealer",
                "layout": {"x": 0, "y": 0, "width": 100, "height": 100},
            }
        ]
        captured = capturer._probe_reveal("page-a", missing, 1.0, result)
        self.assertFalse(captured)
        self.assertEqual(result["revealed_bookmark"], "")


class FakeCapturer:
    instances: list["FakeCapturer"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.hints_by_page: dict[str, dict | None] = {}
        FakeCapturer.instances.append(self)

    def __enter__(self) -> "FakeCapturer":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def list_pages(self) -> list[dict]:
        return [
            {
                "name": "p1",
                "displayName": "Overview",
                "isActive": True,
                "hasMobileLayout": True,
                "mobileSize": {"width": 375, "height": 667},
            },
            {
                "name": "p2",
                "displayName": "Detail",
                "isActive": False,
                "hasMobileLayout": False,
                "mobileSize": None,
            },
        ]

    def capture_page(
        self,
        page_name: str,
        *,
        want_page_png: bool = True,
        want_visual_pngs: bool = True,
        exclude_types: tuple[str, ...] = (),
        reveal_bookmarks: bool = True,
        hints: dict | None = None,
    ) -> dict:
        self.last_hints = hints
        self.hints_by_page[page_name] = hints
        visual = {"name": f"{page_name}_v", "type": "card", "title": "KPI"}
        return {
            "page_png": PNG if want_page_png else None,
            "visuals": [visual],
            "visual_pngs": {visual["name"]: PNG} if want_visual_pngs else {},
            "debug": None,
            "revealed_bookmark": "Show Filter" if reveal_bookmarks else "",
        }

    def capture_mobile_page(self, page_name: str, mobile_size: dict | None = None) -> bytes:
        return PNG


class FakeProvider:
    def __init__(self, token_provider, credentials=None, **_kwargs) -> None:
        self.token_provider = token_provider
        self.credentials = credentials or CaptureCredentials()

    def get_embed_token(self, workspace_id, report_id, extra_dataset_ids=None) -> str:
        return "fake-token"


class CliCaptureTests(unittest.TestCase):
    def test_screenshots_need_workspace_and_report(self) -> None:
        import os

        from cli.tsd import _capture_options, parse_args

        env = {key: "" for key in ("PBI_WORKSPACE_ID", "PBI_REPORT_ID")}
        with patch.dict(os.environ, env):
            args = parse_args(["--screenshots"])
            with self.assertRaises(ExtractionError):
                _capture_options(args)

    def test_options_from_args(self) -> None:
        import os

        from cli.tsd import _capture_options, parse_args

        args = parse_args(
            [
                "--screenshots",
                "--workspace-id",
                WORKSPACE,
                "--report-id",
                REPORT,
                "--rls-roles",
                "HO,Region",
                "--screenshot-scope",
                "pages",
                "--screenshot-scale",
                "2",
                "--refresh-screenshots",
            ]
        )
        env = {
            "TENANT_ID": "tenant",
            "CLIENT_ID": "client",
            "CLIENT_SECRET": "secret",
        }
        with patch.dict(os.environ, env):
            options = _capture_options(args)
        assert options is not None
        self.assertEqual(options.workspace_id, WORKSPACE)
        self.assertEqual(options.report_id, REPORT)
        self.assertEqual(options.credentials.rls_roles, ("HO", "Region"))
        self.assertIsNotNone(options.token_provider)
        self.assertEqual(options.scope, "pages")
        self.assertEqual(options.scale, 2.0)
        self.assertTrue(options.refresh)

    def test_no_capture_without_flag(self) -> None:
        from cli.tsd import _capture_options, parse_args

        self.assertIsNone(_capture_options(parse_args([])))

    def test_no_reveal_bookmarks_flag(self) -> None:
        import os

        from cli.tsd import _capture_options, parse_args

        args = parse_args(
            [
                "--screenshots",
                "--workspace-id",
                WORKSPACE,
                "--report-id",
                REPORT,
                "--no-reveal-bookmarks",
            ]
        )
        env = {
            "TENANT_ID": "tenant",
            "CLIENT_ID": "client",
            "CLIENT_SECRET": "secret",
        }
        with patch.dict(os.environ, env):
            options = _capture_options(args)
        assert options is not None
        self.assertFalse(options.reveal_bookmarks)


    def test_no_mobile_screenshots_flag(self) -> None:
        import os

        from cli.tsd import _capture_options, parse_args

        args = parse_args(
            [
                "--screenshots",
                "--workspace-id",
                WORKSPACE,
                "--report-id",
                REPORT,
                "--no-mobile-screenshots",
            ]
        )
        env = {
            "TENANT_ID": "tenant",
            "CLIENT_ID": "client",
            "CLIENT_SECRET": "secret",
        }
        with patch.dict(os.environ, env):
            options = _capture_options(args)
        assert options is not None
        self.assertFalse(options.mobile)


class LayoutHintTests(unittest.TestCase):
    """Hint posisi absolut menyelesaikan visual di dalam group."""

    def test_hints_pair_grouped_visuals_by_absolute_position(self) -> None:
        visuals = [
            {
                "name": "a",
                "title": "Series",
                "layout": {"x": 0, "y": 0, "width": 300, "height": 100},
            },
            {
                "name": "b",
                "title": "Market Name",
                "layout": {"x": 320, "y": 0, "width": 300, "height": 100},
            },
        ]
        rects = [
            {"i": 0, "x": 80, "y": 160, "w": 300, "h": 100, "label": ""},
            {"i": 1, "x": 400, "y": 160, "w": 300, "h": 100, "label": ""},
        ]
        hints = {
            "a": (10.0, 150.0, 300.0, 100.0),
            "b": (330.0, 150.0, 300.0, 100.0),
        }

        mapping = pair_visuals_to_rects(visuals, rects, hints=hints)

        self.assertIs(mapping["a"], rects[0])
        self.assertIs(mapping["b"], rects[1])

    def test_without_hints_group_visuals_stay_unpaired(self) -> None:
        visuals = [
            {
                "name": "a",
                "title": "Series",
                "layout": {"x": 0, "y": 0, "width": 300, "height": 100},
            },
            {
                "name": "b",
                "title": "Market Name",
                "layout": {"x": 320, "y": 0, "width": 300, "height": 100},
            },
        ]
        rects = [
            {"i": 0, "x": 80, "y": 160, "w": 300, "h": 100, "label": ""},
            {"i": 1, "x": 400, "y": 160, "w": 300, "h": 100, "label": ""},
        ]

        mapping = pair_visuals_to_rects(visuals, rects)

        self.assertIsNone(mapping["a"])
        self.assertIsNone(mapping["b"])

    def test_single_hint_does_not_guess_offset(self) -> None:
        visuals = [
            {
                "name": "a",
                "title": "Matrix",
                "layout": {"x": 0, "y": 0, "width": 300, "height": 100},
            },
            {
                "name": "b",
                "title": "Matrix",
                "layout": {"x": 320, "y": 0, "width": 300, "height": 100},
            },
        ]
        rects = [
            {"i": 0, "x": 400, "y": 300, "w": 300, "h": 100, "label": ""},
            {"i": 1, "x": 720, "y": 300, "w": 300, "h": 100, "label": ""},
        ]

        mapping = pair_visuals_to_rects(
            visuals, rects, hints={"a": (0.0, 0.0, 300.0, 100.0)}
        )

        self.assertIsNone(mapping["a"])
        self.assertIsNone(mapping["b"])

    def test_loader_reads_absolute_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Report_Metadata.xlsx"
            pd.DataFrame(
                [
                    {
                        "page_id": "p1",
                        "visual_id": "v1",
                        "position_x": 0,
                        "position_y": 0,
                        "position_x_abs": 10.5,
                        "position_y_abs": 150.25,
                        "width": 300,
                        "height": 100,
                    },
                    {
                        "page_id": "p1",
                        "visual_id": "v2",
                        "position_x": 0,
                        "position_y": 0,
                        "position_x_abs": 320,
                        "position_y_abs": 150,
                        "width": 280,
                        "height": 90,
                    },
                    {
                        "page_id": "p2",
                        "visual_id": "v3",
                        "position_x_abs": "",
                        "position_y_abs": "",
                        "width": 100,
                        "height": 50,
                    },
                ]
            ).to_excel(path, sheet_name="08_Visual_Summary", index=False)

            hints = load_layout_hints(path)

        self.assertEqual(hints["p1"]["v1"], (10.5, 150.25, 300.0, 100.0))
        self.assertEqual(hints["p1"]["v2"], (320.0, 150.0, 280.0, 90.0))
        self.assertNotIn("p2", hints)

    def test_loader_ignores_workbook_without_absolute_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lama.xlsx"
            pd.DataFrame(
                [{"page_id": "p1", "visual_id": "v1", "width": 300, "height": 100}]
            ).to_excel(path, sheet_name="08_Visual_Summary", index=False)

            self.assertEqual(load_layout_hints(path), {})
        self.assertEqual(load_layout_hints(None), {})
        self.assertEqual(load_layout_hints(Path("tidak-ada.xlsx")), {})


class CaptureReportTests(unittest.TestCase):
    def _options(self, root: Path, scope: str = "both") -> CaptureOptions:
        return CaptureOptions(
            workspace_id=WORKSPACE,
            report_id=REPORT,
            credentials=CaptureCredentials(rls_roles=("HO",)),
            scope=scope,
            output_root=root,
        )

    def test_capture_writes_files_and_returns_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            with patch(
                "core.pbi_capture.runner.EmbedTokenProvider", FakeProvider
            ), patch("core.pbi_capture.runner.ReportCapturer", FakeCapturer):
                result = capture_report(self._options(root))
            self.assertEqual(result.page_count, 2)
            self.assertEqual(result.visual_count, 2)
            self.assertEqual(result.mobile_count, 1)
            self.assertTrue((root / "pages" / "01_Overview.png").exists())
            self.assertTrue(
                (root / "visuals" / "01_Overview" / "KPI.png").exists()
            )
            self.assertTrue((root / "mobile" / "01_Overview.png").exists())
            self.assertFalse((root / "mobile" / "02_Detail.png").exists())
            self.assertTrue(result.mobile_enabled)
            self.assertEqual(result.scope, "both")

    def test_auto_install_flag_is_forwarded_to_capturer(self) -> None:
        FakeCapturer.instances.clear()
        with tempfile.TemporaryDirectory() as tmp:
            options = self._options(Path(tmp) / "shots")
            options.auto_install_browser = False
            with patch(
                "core.pbi_capture.runner.EmbedTokenProvider", FakeProvider
            ), patch("core.pbi_capture.runner.ReportCapturer", FakeCapturer):
                capture_report(options)
        self.assertTrue(FakeCapturer.instances)
        for instance in FakeCapturer.instances:
            self.assertFalse(instance.kwargs["auto_install"])

    def test_mobile_capture_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            options = CaptureOptions(
                workspace_id=WORKSPACE,
                report_id=REPORT,
                credentials=CaptureCredentials(rls_roles=("HO",)),
                output_root=root,
                mobile=False,
            )
            with patch(
                "core.pbi_capture.runner.EmbedTokenProvider", FakeProvider
            ), patch("core.pbi_capture.runner.ReportCapturer", FakeCapturer):
                result = capture_report(options)
            self.assertEqual(result.mobile_count, 0)
            self.assertFalse(result.mobile_enabled)
            self.assertFalse((root / "mobile").exists())

    def test_pages_only_scope_skips_visuals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            with patch(
                "core.pbi_capture.runner.EmbedTokenProvider", FakeProvider
            ), patch("core.pbi_capture.runner.ReportCapturer", FakeCapturer):
                result = capture_report(self._options(root, scope="pages"))
            self.assertEqual(result.page_count, 2)
            self.assertEqual(result.visual_count, 0)
            self.assertEqual(result.scope, "pages")

    def test_hints_workbook_is_passed_per_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            workbook = Path(tmp) / "Report_Metadata.xlsx"
            pd.DataFrame(
                [
                    {
                        "page_id": "p1",
                        "visual_id": "v1",
                        "position_x_abs": 12,
                        "position_y_abs": 34,
                        "width": 300,
                        "height": 100,
                    }
                ]
            ).to_excel(workbook, sheet_name="08_Visual_Summary", index=False)
            options = CaptureOptions(
                workspace_id=WORKSPACE,
                report_id=REPORT,
                credentials=CaptureCredentials(rls_roles=("HO",)),
                output_root=root,
                hints_workbook=workbook,
            )
            FakeCapturer.instances.clear()
            with patch(
                "core.pbi_capture.runner.EmbedTokenProvider", FakeProvider
            ), patch("core.pbi_capture.runner.ReportCapturer", FakeCapturer):
                capture_report(options)

        hints_by_page = FakeCapturer.instances[0].hints_by_page
        self.assertEqual(hints_by_page["p1"], {"v1": (12.0, 34.0, 300.0, 100.0)})
        self.assertIsNone(hints_by_page["p2"])

    def test_cached_capture_is_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            with patch(
                "core.pbi_capture.runner.EmbedTokenProvider", FakeProvider
            ), patch("core.pbi_capture.runner.ReportCapturer", FakeCapturer):
                first = capture_report(self._options(root))
                with patch(
                    "core.pbi_capture.runner.capture_report"
                ) as capture_mock:
                    second = load_or_capture(self._options(root))
            capture_mock.assert_not_called()
            self.assertEqual(second.captured_at, first.captured_at)
            self.assertEqual(second.page_count, first.page_count)

    def test_cache_without_mobile_is_recaptured_when_mobile_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shots"
            off = CaptureOptions(
                workspace_id=WORKSPACE,
                report_id=REPORT,
                credentials=CaptureCredentials(rls_roles=("HO",)),
                output_root=root,
                mobile=False,
            )
            with patch(
                "core.pbi_capture.runner.EmbedTokenProvider", FakeProvider
            ), patch("core.pbi_capture.runner.ReportCapturer", FakeCapturer):
                capture_report(off)
                with patch(
                    "core.pbi_capture.runner.capture_report"
                ) as capture_mock:
                    load_or_capture(self._options(root))
            capture_mock.assert_called_once()


class MissingBrowserTests(unittest.TestCase):
    """Chromium tidak dibundel: pesan harus menunjuk perintah paket."""

    class _BrokenFactory:
        def __call__(self):
            class _Broken:
                def start(self):
                    raise RuntimeError("Executable doesn't exist at chrome.exe")

            return _Broken()

    def test_open_explains_how_to_install_chromium(self) -> None:
        from core.pbi_capture import capture as capture_module

        capturer = ReportCapturer(
            report_id=REPORT,
            workspace_id=WORKSPACE,
            embed_token="token",
        )
        with patch.object(capture_module, "sync_playwright", self._BrokenFactory()):
            with self.assertRaises(ExtractionError) as ctx:
                capturer.open()

        message = str(ctx.exception)
        self.assertIn("install-browser", message)
        self.assertIn("playwright install chromium", message)

    def _capturer_for_launch(self, auto_install: bool, error: str):
        capturer = ReportCapturer.__new__(ReportCapturer)
        capturer.auto_install = auto_install
        capturer.headless = True
        lines: list[str] = []
        attempts: list[int] = []
        capturer._log = lines.append

        class Chromium:
            def launch(self, headless: bool = True):
                attempts.append(1)
                if len(attempts) == 1:
                    raise RuntimeError(error)
                return "browser"

        capturer._pw = SimpleNamespace(chromium=Chromium())
        return capturer, lines, attempts

    def test_auto_install_downloads_and_retries_once(self) -> None:
        capturer, lines, attempts = self._capturer_for_launch(
            True, "Executable doesn't exist at chrome.exe"
        )
        with patch("core.pbi_capture.capture.install_chromium") as install:
            self.assertEqual(capturer._launch_browser(), "browser")
        install.assert_called_once()
        self.assertEqual(len(attempts), 2)
        self.assertTrue(any("mengunduh otomatis" in line.lower() for line in lines))

    def test_auto_install_can_be_disabled(self) -> None:
        capturer, _lines, attempts = self._capturer_for_launch(
            False, "Executable doesn't exist at chrome.exe"
        )
        with patch("core.pbi_capture.capture.install_chromium") as install:
            with self.assertRaises(RuntimeError):
                capturer._launch_browser()
        install.assert_not_called()
        self.assertEqual(len(attempts), 1)

    def test_other_launch_errors_do_not_install(self) -> None:
        capturer, _lines, _attempts = self._capturer_for_launch(
            True, "Target page, context or browser has been closed"
        )
        with patch("core.pbi_capture.capture.install_chromium") as install:
            with self.assertRaises(RuntimeError):
                capturer._launch_browser()
        install.assert_not_called()

    def test_missing_browser_detection(self) -> None:
        from core.pbi_capture.browsers import missing_browser

        self.assertTrue(
            missing_browser(RuntimeError("Executable doesn't exist at chrome.exe"))
        )
        self.assertTrue(missing_browser(RuntimeError("run playwright install")))
        self.assertFalse(missing_browser(RuntimeError("Target page crashed")))

    def test_auto_install_defaults_to_true(self) -> None:
        options = CaptureOptions(workspace_id=WORKSPACE, report_id=REPORT)
        self.assertTrue(options.auto_install_browser)
        disabled = CaptureOptions(
            workspace_id=WORKSPACE,
            report_id=REPORT,
            auto_install_browser=False,
        )
        self.assertFalse(disabled.auto_install_browser)


if __name__ == "__main__":
    unittest.main()
