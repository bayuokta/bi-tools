"""Smoke test browser nyata untuk antarmuka web (Playwright).

Uji unit lain memakai ``TestClient`` yang tidak menjalankan JavaScript, jadi
kesalahan boot ``app.js`` (sintaks, elemen hilang, handler null) tidak tertangkap.
Uji ini menjalankan server uvicorn sungguhan di port acak, membuka halaman
dengan Chromium, lalu memeriksa semua view, pergantian bahasa, dan aset.

Dijalankan hanya bila diminta karena membutuhkan Chromium::

    python -m pip install playwright
    python -m playwright install chromium
    python -m unittest tests.test_web_smoke          # PowerShell: $env:RUN_WEB_SMOKE="1"
    RUN_WEB_SMOKE=1 python -m unittest tests.test_web_smoke

Tanpa ``RUN_WEB_SMOKE=1`` seluruh kelas di-skip sehingga CI utama tetap ringan.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

RUN_SMOKE = os.environ.get("RUN_WEB_SMOKE") == "1"

VIEWS = {
    "ekstraksi": "Extraction & TSD",
    "analisa": "Semantic model analysis",
    "compare": "Compare semantic model",
    "lineage": "Lineage",
    "partisi": "Semantic model partitions",
    "pengaturan": "Settings",
}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_health(port: int, timeout: float = 30.0) -> bool:
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:  # noqa: BLE001 - server belum siap
            time.sleep(0.05)
    return False


class WebSmokeTests(unittest.TestCase):
    """Satu server, satu browser; setiap uji memakai context baru."""

    @classmethod
    def setUpClass(cls) -> None:
        if not RUN_SMOKE:
            raise unittest.SkipTest(
                "Smoke browser dilewati; set RUN_WEB_SMOKE=1 untuk menjalankan."
            )
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - lingkungan tanpa Playwright
            raise unittest.SkipTest(f"Playwright tidak terpasang: {exc}") from exc

        import uvicorn

        from server.app import create_app
        from server.security import allowed_for, new_token
        from server.settings_store import SettingsStore

        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        cls._env_backup = {
            key: os.environ.get(key)
            for key in ("BI_TOOLS_OUTPUTS", "BI_TOOLS_DATA")
        }
        os.environ["BI_TOOLS_OUTPUTS"] = str(root / "outputs")
        os.environ["BI_TOOLS_DATA"] = str(root / "data")
        from core import paths

        paths.outputs_dir.cache_clear()
        paths.data_dir.cache_clear()

        store = SettingsStore(root / "settings.json", registry_reader=lambda: {})
        store.reset_session()
        store.set_lineage_db(root / "data" / "missing.db")

        cls.port = free_port()
        cls.token = new_token()
        hosts, origins = allowed_for(cls.port)
        app = create_app(
            settings_store=store,
            token=cls.token,
            allowed_hosts=hosts,
            allowed_origins=origins,
        )

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=cls.port,
            log_level="warning",
            log_config=None,
            access_log=False,
        )
        cls._server = uvicorn.Server(config)
        cls._thread = threading.Thread(target=cls._server.run, daemon=True)
        cls._thread.start()
        if not wait_health(cls.port):
            cls._shutdown_server()
            raise RuntimeError("Server uji tidak siap di port " + str(cls.port))

        cls._playwright = sync_playwright().start()
        try:
            cls._browser = cls._playwright.chromium.launch()
        except Exception as exc:  # pragma: no cover - Chromium belum diunduh
            cls._playwright.stop()
            cls._shutdown_server()
            raise unittest.SkipTest(
                f"Chromium Playwright tidak bisa dijalankan: {exc}"
            ) from exc

    @classmethod
    def tearDownClass(cls) -> None:
        browser = getattr(cls, "_browser", None)
        if browser is not None:
            browser.close()
        playwright = getattr(cls, "_playwright", None)
        if playwright is not None:
            playwright.stop()
        cls._shutdown_server()
        from core import paths

        paths.outputs_dir.cache_clear()
        paths.data_dir.cache_clear()
        for key, value in getattr(cls, "_env_backup", {}).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        tmp = getattr(cls, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    @classmethod
    def _shutdown_server(cls) -> None:
        server = getattr(cls, "_server", None)
        thread = getattr(cls, "_thread", None)
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)

    # -- helper -----------------------------------------------------------
    def open_page(self, width: int = 1366, height: int = 768):
        context = self._browser.new_context(
            viewport={"width": width, "height": height}
        )
        self.addCleanup(context.close)
        page = context.new_page()
        # Deteksi instance Desktop memakai ADOMD/.NET. Smoke test tidak boleh
        # bergantung pada Power BI Desktop yang terbuka, jadi endpoint ini
        # dijawab palsu (kosong) sebelum halaman dimuat.
        page.route(
            "**/api/metadata/instances**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "instances": [],
                        "hint": "Smoke test: instance list is stubbed.",
                    }
                ),
            ),
        )
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on(
            "console",
            lambda msg: errors.append(f"console: {msg.text}")
            if msg.type == "error"
            else None,
        )
        page.goto(
            f"http://127.0.0.1:{self.port}/?t={self.token}",
            wait_until="load",
        )
        page.wait_for_selector("#view-ekstraksi", state="visible")
        self.addCleanup(lambda: self.assertEqual(errors, [], "error di browser"))
        return page

    def show_view(self, page, view: str) -> None:
        page.click(f'.nav-item[data-view="{view}"]')
        page.wait_for_selector(f"#view-{view}:not([hidden])", state="visible")

    # -- uji --------------------------------------------------------------
    def test_boot_and_all_views_render(self) -> None:
        page = self.open_page()
        for view, title in VIEWS.items():
            self.show_view(page, view)
            heading = page.inner_text(f"#view-{view} .view-title").strip()
            self.assertEqual(heading, title, view)

    def test_partition_inventory_groups_render(self) -> None:
        """Modul Partisi dirender dengan state palsu tanpa XMLA.

        Menangkap kesalahan runtime seperti ``partitionRows is not defined``
        yang tidak terlihat oleh tes statis maupun view kosong.
        """

        page = self.open_page()
        self.show_view(page, "partisi")
        rows = [
            {
                "table": "Dates",
                "partition": "Dates",
                "rows": 365,
                "range": "",
                "range_start": "",
                "range_end": "",
                "range_source": "",
                "mode": "Import",
                "source_type": "M",
                "state": "Ready",
                "last_processed": "2026-11-20T10:00:00",
                "modified": "2026-11-20T10:00:00",
            }
        ]
        for index in range(1, 6):
            rows.append(
                {
                    "table": "Sales",
                    "partition": f"2025-{index:02d}",
                    "rows": 1000 * index,
                    "range": f"2025-{index:02d}",
                    "range_start": f"2025-{index:02d}-01",
                    "range_end": f"2025-{index:02d}-28",
                    "range_source": "RangeStart",
                    "mode": "Import",
                    "source_type": "PolicyRangePartitionSource",
                    "state": "Ready",
                    "last_processed": "2026-11-20T10:00:00",
                    "modified": "2026-11-20T10:00:00",
                }
            )

        page.evaluate(
            """async (rows) => {
                const { state } = await import('/js/core/state.js');
                const view = await import('/js/views/partitions-lineage.js');
                state.partitions = { partitions: rows, loaded_at: '2026-11-22T00:00:00' };
                state.partitionLoaded = true;
                state.partitionSelected = {};
                state.partitionOpen = {};
                view.partitionRender();
            }""",
            rows,
        )

        self.assertTrue(page.is_visible("#partitionTableWrap"))
        self.assertEqual(page.locator("#partitionBody tr.partition-group").count(), 1)
        self.assertEqual(page.locator("#partitionBody tr.partition-child").count(), 0)
        self.assertEqual(
            page.locator("#partitionBody tr.partition-item:not(.partition-child)").count(),
            1,
        )
        self.assertIn("Sales", page.inner_text("#partitionBody tr.partition-group"))
        self.assertIn("5 partitions", page.inner_text("#partitionBody tr.partition-group"))

        page.click("#partitionBody tr.partition-group td:nth-child(4)")
        self.assertEqual(page.locator("#partitionBody tr.partition-child").count(), 5)

        page.check("#partitionBody .partition-group-check")
        self.assertIn("5", page.inner_text("#partitionSelectionSummary"))
        self.assertIn("selected", page.inner_text("#partitionSelectionSummary"))

        page.click("#partitionCollapseAll")
        self.assertEqual(page.locator("#partitionBody tr.partition-child").count(), 0)
        page.click("#partitionExpandAll")
        self.assertEqual(page.locator("#partitionBody tr.partition-child").count(), 5)

    def test_extraction_and_tsd_steps_render(self) -> None:
        page = self.open_page()
        self.show_view(page, "ekstraksi")
        self.assertTrue(page.is_visible("#metaSteps"))
        # Langkah 2 terkunci tanpa workbook report, tetapi bisa terbuka bila
        # Report_Metadata.xlsx sudah ada di folder kerja. Keduanya sah.
        unlocked = not page.eval_on_selector("#view-tsd", "el => el.hidden")
        if unlocked:
            self.assertTrue(page.is_visible("#view-tsd"))
            self.assertFalse(page.is_visible("#tsdLock"))
        else:
            self.assertTrue(page.is_visible("#tsdLock"))
            self.assertFalse(page.is_visible("#view-tsd"))

    def test_language_switch_persists_after_reload(self) -> None:
        page = self.open_page()
        self.show_view(page, "pengaturan")
        page.click("#tab-tampilan")
        page.wait_for_selector("#set-tampilan:not([hidden])", state="visible")
        page.click('.theme-card[data-language="id"]')
        page.wait_for_function("document.documentElement.lang === 'id'")
        self.assertEqual(page.inner_text("#titlePengaturan").strip(), "Pengaturan")
        self.assertEqual(
            page.inner_text("#titleEkstraksi").strip(), "Ekstraksi & TSD"
        )

        page.reload(wait_until="load")
        page.wait_for_selector("#view-ekstraksi", state="visible")
        page.wait_for_function("document.documentElement.lang === 'id'")
        self.assertEqual(
            page.inner_text("#titleEkstraksi").strip(), "Ekstraksi & TSD"
        )

        self.show_view(page, "pengaturan")
        page.click("#tab-tampilan")
        page.wait_for_selector("#set-tampilan:not([hidden])", state="visible")
        page.click('.theme-card[data-language="en"]')
        page.wait_for_function("document.documentElement.lang === 'en'")
        self.assertEqual(page.inner_text("#titlePengaturan").strip(), "Settings")

    def test_analysis_view_without_credentials_shows_empty_state(self) -> None:
        page = self.open_page()
        self.show_view(page, "analisa")
        self.assertTrue(page.is_visible("#analyzeEmpty"))
        self.assertFalse(page.is_visible("#analyzeTableWrap"))
        text = page.inner_text("#analyzeEmptyText").lower()
        self.assertTrue(text)

    def test_no_failed_assets_and_no_body_overflow(self) -> None:
        failed: list[str] = []
        page = self.open_page()
        page.on(
            "response",
            lambda response: failed.append(
                f"{response.status} {response.url}"
            )
            if response.status >= 400
            and response.request.resource_type
            in {"document", "script", "stylesheet", "image", "font"}
            else None,
        )
        for view in VIEWS:
            self.show_view(page, view)
        self.assertEqual(failed, [], "aset web gagal dimuat")

        for width in (1366, 1600):
            page.set_viewport_size({"width": width, "height": 900})
            self.show_view(page, "analisa")
            overflow = page.evaluate(
                "() => document.body.scrollWidth - document.body.clientWidth"
            )
            self.assertLessEqual(overflow, 1, f"overflow horizontal di {width}px")


if __name__ == "__main__":
    unittest.main()
