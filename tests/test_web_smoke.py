"""Smoke test browser nyata untuk antarmuka web (Playwright).

Uji unit lain memakai ``TestClient`` yang tidak menjalankan JavaScript, jadi
kesalahan boot ``app.js`` (sintaks, elemen hilang, handler null) tidak tertangkap.
Uji ini menjalankan server uvicorn sungguhan di port acak, membuka halaman
dengan Chromium, lalu memeriksa semua view dan aset.

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
    "compare": "Compare model",
    "lineage": "Lineage",
    "backup": "Backup and Restore",
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
        page.wait_for_selector("#view-analisa", state="visible")
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

    def test_interface_is_english_only(self) -> None:
        page = self.open_page()
        self.show_view(page, "pengaturan")
        self.assertEqual(page.get_attribute("html", "lang"), "en")
        self.assertEqual(page.locator(".theme-card[data-language]").count(), 0)
        self.assertEqual(page.inner_text("#titlePengaturan").strip(), "Settings")

    def test_analysis_view_without_credentials_shows_empty_state(self) -> None:
        page = self.open_page()
        self.show_view(page, "analisa")
        self.assertTrue(page.is_visible("#analyzeEmpty"))
        self.assertFalse(page.is_visible("#analyzeTableWrap"))
        text = page.inner_text("#analyzeEmptyText").lower()
        self.assertTrue(text)

    def test_analysis_dax_tab_renders_template_columns(self) -> None:
        """Tab DAX expressions memakai 11 kolom template dengan state palsu."""

        page = self.open_page()
        self.show_view(page, "analisa")
        result = {
            "dataset": {"id": "ds", "name": "Model Uji"},
            "totals": {"columns": 1, "measures": 1, "hierarchies": 0, "functions": 1},
            "measures": [
                {
                    "name": "Max Pages",
                    "table": "Pages",
                    "status": "Used",
                    "uses": 2,
                    "has_error": False,
                    "lineage_tag": "measure-guid",
                    "display_folder": "",
                    "description": "",
                    "expression": "MAX('Pages'[Pages])",
                }
            ],
            "columns": [
                {
                    "name": "Day",
                    "table": "Dates",
                    "status": "Used",
                    "uses": 1,
                    "has_error": False,
                    "is_calculated": True,
                    "expression": "DAY(Dates[Dates])",
                    "lineage_tag": "column-guid",
                    "display_folder": "",
                    "description": "",
                }
            ],
            "functions": [
                {
                    "name": "PercentageGrowth",
                    "status": "Used",
                    "uses": 1,
                    "lineage_tag": "function-guid",
                    "description": "",
                    "expression": "(x: SCALAR) => x",
                }
            ],
            "tables": [
                {
                    "name": "Parameter",
                    "is_calculated_table": True,
                    "is_calculation_group": False,
                    "is_field_parameter": False,
                    "expression": "GENERATESERIES(3, 6, 3)",
                    "lineage_tag": "table-guid",
                    "description": "",
                },
                {
                    "name": "Parameter Posisi",
                    "is_calculated_table": True,
                    "is_calculation_group": False,
                    "is_field_parameter": True,
                    "expression": "{\"A\"}",
                    "lineage_tag": "field-guid",
                    "description": "",
                },
                {
                    "name": "Time Intelligence",
                    "is_calculated_table": False,
                    "is_calculation_group": True,
                    "is_field_parameter": False,
                    "expression": "",
                    "lineage_tag": "group-guid",
                    "description": "",
                },
            ],
            "relationships": [],
            "roles": [],
            "reports": [],
            "m_queries": [],
            "coverage": {"complete": True},
            "reports_included": False,
        }
        page.evaluate(
            """async (result) => {
                const { state } = await import('/js/core/state.js');
                const view = await import('/js/views/analysis.js');
                state.analysis = result;
                state.analysisTab = 'dax';
                state.analysisOpen = {};
                state.analysisForceOpen = null;
                state.analysisSort = 'default';
                view.analysisRender();
            }""",
            result,
        )

        self.assertEqual(page.locator("#analyzeHead th").count(), 11)
        headers = [text.lower() for text in page.locator("#analyzeHead th").all_inner_texts()]
        self.assertEqual(headers[0], "name")
        self.assertIn("best practices violations", headers[4])
        self.assertEqual(headers[10], "expression")
        self.assertEqual(page.locator("#analyzeBody tr").count(), 5)
        self.assertIn("Export DAX expressions", page.inner_text("#exportXlsx"))
        body = page.inner_text("#analyzeBody")
        self.assertIn("PercentageGrowth", body)
        self.assertIn("Parameter Posisi", body)
        self.assertIn("GENERATESERIES(3, 6, 3)", body)
        self.assertNotIn("Time Intelligence", body)

    def test_analysis_m_tab_renders_template_columns(self) -> None:
        """Tab M queries memakai 5 kolom template, termasuk baris duplikat."""

        page = self.open_page()
        self.show_view(page, "analisa")
        result = {
            "dataset": {"id": "ds", "name": "Model Uji"},
            "totals": {"columns": 0, "measures": 0, "hierarchies": 0, "functions": 0},
            "measures": [],
            "columns": [],
            "functions": [],
            "tables": [],
            "m_queries": [
                {
                    "name": "Sales",
                    "kind": "Table",
                    "source": "Import",
                    "expression": "let Source = 1 in Source",
                    "warning": "",
                    "detail": "Sales",
                    "entry_key": "table:Sales:p:Sales",
                },
                {
                    "name": "Sales",
                    "kind": "Table",
                    "source": "Import",
                    "expression": "let Source = 1 in Source",
                    "warning": "",
                    "detail": "refresh policy",
                    "entry_key": "table:Sales:z:policy",
                },
                {
                    "name": "Stock Level",
                    "kind": "Table",
                    "source": "Import",
                    "expression": "let Source = 2 in Source",
                    "warning": "evaluationError",
                    "detail": "Stock Level",
                    "entry_key": "table:Stock Level:p:Stock Level",
                },
                {
                    "name": "Pages Testing",
                    "kind": "M Query",
                    "source": "Model",
                    "expression": "let Source = 3 in Source",
                    "warning": "",
                    "detail": "",
                    "entry_key": "query:Pages Testing",
                },
                {
                    "name": "RangeStart",
                    "kind": "M Parameter",
                    "source": "Params",
                    "expression": "#datetime(2026, 1, 1, 0, 0, 0)",
                    "warning": "",
                    "detail": "DateTime",
                    "entry_key": "parameter:RangeStart",
                },
            ],
            "relationships": [],
            "roles": [],
            "reports": [],
            "coverage": {"complete": True},
            "reports_included": False,
        }
        page.evaluate(
            """async (result) => {
                const { state } = await import('/js/core/state.js');
                const view = await import('/js/views/analysis.js');
                state.analysis = result;
                state.analysisTab = 'm';
                state.analysisOpen = {'m:table:Sales:p:Sales': true};
                state.analysisForceOpen = null;
                state.analysisSort = 'default';
                view.analysisRender();
            }""",
            result,
        )

        self.assertEqual(page.locator("#analyzeHead th").count(), 5)
        headers = [text.lower() for text in page.locator("#analyzeHead th").all_inner_texts()]
        self.assertEqual(headers, ["name", "type", "source", "warnings", "expression"])
        self.assertEqual(page.locator("#analyzeBody tr:not(.code-row)").count(), 5)
        self.assertEqual(page.locator("#analyzeBody tr.code-row").count(), 1)
        self.assertIn("Export M expressions", page.inner_text("#exportXlsx"))
        body = page.inner_text("#analyzeBody")
        self.assertIn("Sales", body)
        self.assertIn("M Query", body)
        self.assertIn("M Parameter", body)
        self.assertIn("Model Uji", body)
        self.assertIn("evaluationError", body)

    def test_analysis_best_practice_tab_renders_flat_template(self) -> None:
        """Tab Best practice memakai 4 kolom template dengan baris datar."""

        page = self.open_page()
        self.show_view(page, "analisa")
        result = {
            "dataset": {"id": "ds", "name": "Model Uji"},
            "totals": {"columns": 0, "measures": 0, "hierarchies": 0, "functions": 0},
            "measures": [],
            "columns": [],
            "functions": [],
            "tables": [],
            "m_queries": [],
            "relationships": [],
            "roles": [],
            "reports": [],
            "coverage": {"complete": True},
            "reports_included": True,
            "best_practice": {
                "available": True,
                "score": 42,
                "verdict": "Poor",
                "verdict_key": "poor",
                "rule_count": 71,
                "evaluated": 54,
                "not_evaluated": 17,
                "counts": {"violations": 2, "rules": 1},
                "rules": [],
                "items": [
                    {
                        "rule_id": "OBJECTS_WITH_NO_DESCRIPTION",
                        "rule_name": "[Maintenance] Visible objects with no description",
                        "category": "Maintenance",
                        "severity": 1,
                        "rule_score": 42,
                        "object": "'Sales'[Customer]",
                        "kind": "column",
                        "table": "Sales",
                        "name": "Customer",
                        "detail": "no description",
                        "target": {"kind": "column", "table": "Sales", "name": "Customer"},
                    },
                    {
                        "rule_id": "OBJECTS_WITH_NO_DESCRIPTION",
                        "rule_name": "[Maintenance] Visible objects with no description",
                        "category": "Maintenance",
                        "severity": 1,
                        "rule_score": 42,
                        "object": "Sales (Table)",
                        "kind": "table",
                        "table": "Sales",
                        "name": "Sales",
                        "detail": "no description",
                        "target": {"kind": "table", "table": "Sales"},
                    },
                ],
            },
        }
        page.evaluate(
            """async (result) => {
                const { state } = await import('/js/core/state.js');
                const view = await import('/js/views/analysis.js');
                state.analysis = result;
                state.analysisTab = 'bestpractice';
                state.analysisOpen = {};
                state.analysisForceOpen = null;
                state.analysisSort = 'default';
                view.analysisRender();
            }""",
            result,
        )

        self.assertEqual(page.locator("#analyzeHead th").count(), 4)
        headers = [text.lower() for text in page.locator("#analyzeHead th").all_inner_texts()]
        self.assertEqual(headers, ["rule", "violation score", "severity", "object"])
        self.assertEqual(page.locator("#analyzeBody tr").count(), 2)
        self.assertIn("Export best practice", page.inner_text("#exportXlsx"))
        body = page.inner_text("#analyzeBody")
        self.assertIn("Visible objects with no description", body)
        self.assertIn("'Sales'[Customer]", body)
        self.assertIn("Sales (Table)", body)

    def test_analysis_unloaded_tab_renders_tree_and_menu(self) -> None:
        """Tab Unloaded M queries: 5 kolom, grup pemakaian, dan menu root."""

        page = self.open_page()
        self.show_view(page, "analisa")
        result = {
            "dataset": {"id": "ds", "name": "Model Uji"},
            "totals": {"columns": 0, "measures": 0, "hierarchies": 0, "functions": 0},
            "measures": [],
            "columns": [],
            "functions": [],
            "tables": [],
            "m_queries": [],
            "unloaded_queries": [
                {
                    "name": "Pages Testing",
                    "type": "M Query",
                    "source": "Model Uji",
                    "status": "Unused",
                    "uses": 0,
                    "expression": "let Source = 1 in Source",
                    "usages": [],
                },
                {
                    "name": "RangeStart",
                    "type": "M Parameter",
                    "source": "Model Uji",
                    "status": "Used",
                    "uses": 1,
                    "expression": "#datetime(2026, 1, 1, 0, 0, 0)",
                    "usages": [
                        {
                            "name": "Sales",
                            "type": "Table",
                            "source": "Model Uji",
                            "status": "Used 50.0% (1/2)",
                            "uses": 1,
                        }
                    ],
                },
            ],
            "relationships": [],
            "roles": [],
            "reports": [],
            "coverage": {"complete": True},
            "reports_included": False,
        }
        page.evaluate(
            """async (result) => {
                const { state } = await import('/js/core/state.js');
                const view = await import('/js/views/analysis.js');
                state.analysis = result;
                state.analysisTab = 'unloaded';
                state.analysisOpen = {'unloaded:RangeStart': true};
                state.analysisForceOpen = null;
                state.analysisSort = 'default';
                view.analysisRender();
            }""",
            result,
        )

        self.assertEqual(page.locator("#analyzeHead th").count(), 5)
        headers = [text.lower() for text in page.locator("#analyzeHead th").all_inner_texts()]
        self.assertEqual(
            headers, ["name", "type", "source", "status", "# of uses"]
        )
        self.assertEqual(page.locator("#analyzeBody tr").count(), 4)
        body = page.inner_text("#analyzeBody")
        self.assertIn("Pages Testing", body)
        self.assertIn("Used in Power Query", body)
        self.assertIn("Sales", body)
        self.assertIn("Used 50.0% (1/2)", body)
        self.assertIn("Export unloaded power query", page.inner_text("#exportXlsx"))
        self.assertEqual(page.inner_text("#tabCountUnloaded"), "2")

        page.evaluate(
            """async () => {
                const view = await import('/js/views/analysis.js');
                view.analysisOpenMenu(
                  { kind: 'unloaded', table: '', name: 'RangeStart' },
                  { x: 20, y: 20 }
                );
            }"""
        )
        menu = page.inner_text("#analysisMenu")
        self.assertIn("Unloaded table details", menu)
        self.assertIn("View M expression", menu)
        self.assertIn("Model details", menu)
        self.assertNotIn("Model options", menu)

    def test_analysis_health_tab_enables_export(self) -> None:
        """Tab Health memakai 6 kolom UI dan tombol Export health."""

        page = self.open_page()
        self.show_view(page, "analisa")
        result = {
            "dataset": {"id": "ds", "name": "Model Uji"},
            "totals": {"columns": 0, "measures": 0, "hierarchies": 0, "functions": 0},
            "measures": [],
            "columns": [],
            "functions": [],
            "tables": [],
            "m_queries": [],
            "unloaded_queries": [],
            "relationships": [],
            "roles": [],
            "reports": [],
            "coverage": {"complete": True},
            "reports_included": True,
            "health": {
                "counts": {"critical": 0, "warning": 0, "info": 1},
                "items": [
                    {
                        "id": "unused_table:old",
                        "rule": "unused_table",
                        "severity": "info",
                        "severity_rank": 2,
                        "area": "model",
                        "object": "Old",
                        "kind": "table",
                        "table": "Old",
                        "name": "Old",
                        "detail": "",
                        "size_bytes": 1024,
                        "metrics": {"columns": 1, "measures": 0},
                        "target": {"kind": "table", "table": "Old"},
                    }
                ],
            },
        }
        page.evaluate(
            """async (result) => {
                const { state } = await import('/js/core/state.js');
                const view = await import('/js/views/analysis.js');
                state.analysis = result;
                state.analysisTab = 'health';
                state.analysisOpen = {};
                state.analysisForceOpen = null;
                state.analysisSort = 'default';
                view.analysisRender();
            }""",
            result,
        )

        self.assertEqual(page.locator("#analyzeHead th").count(), 6)
        self.assertIn("Export health", page.inner_text("#exportXlsx"))
        self.assertIn("1 findings", page.inner_text("#analyzeSummary"))

    def test_analysis_roles_tab_enables_export(self) -> None:
        """Tab Roles memakai pohon 11 kolom dan tombol Export roles."""

        page = self.open_page()
        self.show_view(page, "analisa")
        result = {
            "dataset": {"id": "ds", "name": "Model Uji"},
            "totals": {"columns": 0, "measures": 0, "hierarchies": 0, "functions": 0},
            "measures": [],
            "columns": [],
            "functions": [],
            "tables": [],
            "m_queries": [],
            "unloaded_queries": [],
            "relationships": [],
            "reports": [],
            "coverage": {"complete": True},
            "reports_included": True,
            "roles": [
                {
                    "id": 1,
                    "name": "Dealer",
                    "model_permission": "read",
                    "description": "",
                    "modified": "",
                    "members": [
                        {
                            "name": "Dealer A",
                            "member_id": "m1",
                            "member_type": "User",
                            "provider": "AzureAD",
                            "modified": "",
                        }
                    ],
                    "permissions": [
                        {
                            "table": "RLS Dealer",
                            "expression": "[Email] = USERPRINCIPALNAME()",
                            "has_ols": False,
                        }
                    ],
                }
            ],
        }
        page.evaluate(
            """async (result) => {
                const { state } = await import('/js/core/state.js');
                const view = await import('/js/views/analysis.js');
                state.analysis = result;
                state.analysisTab = 'roles';
                state.analysisOpen = {'role:1': true};
                state.analysisForceOpen = null;
                state.analysisSort = 'default';
                view.analysisRender();
            }""",
            result,
        )

        self.assertEqual(page.locator("#analyzeHead th").count(), 11)
        self.assertEqual(page.locator("#analyzeBody tr").count(), 3)
        self.assertIn("Export roles", page.inner_text("#exportXlsx"))
        body = page.inner_text("#analyzeBody")
        self.assertIn("Dealer", body)
        self.assertIn("Dealer A", body)
        self.assertIn("RLS Dealer", body)

    def test_relationship_canvas_has_dotted_background(self) -> None:
        page = self.open_page()
        self.show_view(page, "analisa")
        page.evaluate(
            """async () => {
              const s = await import('/js/core/state.js');
              s.state.analysis = {
                tables: [
                  {name: 'Fact', column_count: 3, measure_count: 1},
                  {name: 'Dim', column_count: 2, measure_count: 0}
                ],
                relationships: [{
                  from_table: 'Fact', to_table: 'Dim', is_active: true,
                  type: 'Many to one', cross: 'Single', cardinality: '*:1',
                  auto: 'No', status: 'Used'
                }],
                measures: [], columns: [], m_queries: [], roles: [],
                totals: {}, coverage_complete: true, coverage: '',
                reports_included: true
              };
              s.state.analysisTab = 'relationships';
              const analysis = await import('/js/views/analysis.js');
              analysis.analysisRender();
            }"""
        )
        page.wait_for_selector("#relGraphSvg [data-rel-table]")
        background = page.eval_on_selector(
            "#relGraph .rel-graph-canvas",
            "el => getComputedStyle(el).backgroundImage",
        )
        self.assertIn("radial-gradient", background)
        self.assertEqual(page.locator("#relGraphSvg [data-rel-table]").count(), 2)

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
