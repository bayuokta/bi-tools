"""Penjaga batas arsitektur: satu tempat untuk HTTP, satu tempat untuk token."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("core", "cli", "server")


def source_files() -> list[Path]:
    files: list[Path] = []
    for folder in SOURCES:
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def matching(pattern: str) -> list[str]:
    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    hits: list[str] = []
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        if regex.search(text):
            hits.append(path.relative_to(ROOT).as_posix())
    return sorted(hits)


def files_under(folder: str) -> list[Path]:
    return [path for path in source_files() if path.relative_to(ROOT).parts[0] == folder]


def matching_in(files: list[Path], pattern: str) -> list[str]:
    regex = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
    return sorted(
        path.relative_to(ROOT).as_posix()
        for path in files
        if regex.search(path.read_text(encoding="utf-8"))
    )


class LayerGuardTests(unittest.TestCase):
    def test_requests_only_in_transport(self) -> None:
        expected = {"core/api/transport.py"}
        self.assertEqual(set(matching(r"^\s*(import requests|from requests\b)")), expected)

    def test_msal_client_only_in_auth(self) -> None:
        self.assertEqual(
            set(matching(r"ConfidentialClientApplication")), {"core/auth.py"}
        )

    def test_browser_login_is_gone(self) -> None:
        self.assertEqual(matching(r"azure\.identity|InteractiveBrowserCredential"), [])

    def test_no_token_in_connection_string(self) -> None:
        self.assertEqual(matching(r"password\s*="), [])

    def test_auth_module_stays_pure_python(self) -> None:
        text = (ROOT / "core" / "auth.py").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"(?m)^\s*(import clr|import pythonnet|from pythonnet)")

    def test_new_core_modules_have_no_terminal_calls(self) -> None:
        modules = [
            ROOT / "core" / "auth.py",
            ROOT / "core" / "api" / "transport.py",
            ROOT / "core" / "api" / "__init__.py",
        ]
        pattern = re.compile(r"(?m)^\s*(print\(|input\()")
        for path in modules:
            self.assertIsNone(
                pattern.search(path.read_text(encoding="utf-8")),
                f"core tidak boleh mencetak ke terminal: {path}",
            )


class BoundaryTests(unittest.TestCase):
    def test_qt_is_gone(self) -> None:
        hits = matching(r"^\s*(import PySide6|from PySide6\b)")
        self.assertEqual(hits, [], "PySide6 sudah dihapus dari 0.4.0")

    def test_app_package_is_gone(self) -> None:
        self.assertFalse((ROOT / "app").exists(), "app/ sudah dihapus setelah paritas web")

    def test_core_has_no_web_framework(self) -> None:
        hits = matching_in(
            files_under("core"),
            r"^\s*(import fastapi|import uvicorn|from fastapi\b|from uvicorn\b)",
        )
        self.assertEqual(hits, [], "core harus bebas framework web agar bisa dipakai CLI")

    def test_server_has_no_qt(self) -> None:
        hits = matching_in(
            files_under("server"), r"^\s*(import PySide6|from PySide6\b)"
        )
        self.assertEqual(hits, [], "server web tidak boleh bergantung pada PySide6")

    def test_server_does_not_import_gui(self) -> None:
        hits = matching_in(files_under("server"), r"^\s*(import app\b|from app\b)")
        self.assertEqual(hits, [], "server harus berdiri di atas core, bukan GUI")

    def test_cli_does_not_import_server(self) -> None:
        hits = matching_in(files_under("cli"), r"^\s*(import server\b|from server\b)")
        self.assertEqual(hits, [], "CLI tidak boleh menyeret server web")

    def test_server_does_not_use_requests(self) -> None:
        hits = matching_in(
            files_under("server"), r"^\s*(import requests|from requests\b)"
        )
        self.assertEqual(hits, [], "HTTP REST tetap lewat core.api.transport")

    def test_no_hardcoded_pbix_default(self) -> None:
        hits = matching(r"DEFAULT_PBIX|DRAGON_PBIX_SOURCE|stale_copy_warning")
        self.assertEqual(
            hits, [], "path .pbix wajib eksplisit; jangan ada default/env di kode"
        )


class WebLayerTests(unittest.TestCase):
    def test_web_folder_has_no_python(self) -> None:
        files = [path for path in (ROOT / "web").rglob("*.py")]
        self.assertEqual(files, [], "web/ hanya aset statis, bukan kode server")

    def test_web_entry_loads_api_client(self) -> None:
        text = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="api.js"', text)
        self.assertIn('src="app.js"', text)
        api = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
        self.assertIn("window.BIToolsApi", api)

    def test_web_helpers_are_defined_once(self) -> None:
        # Duplikat deklarasi pernah menutupi helper (parentDir) tanpa error
        # sintaks; setiap helper inti harus tepat satu deklarasi.
        text = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        for name in (
            "parentDir",
            "browseRow",
            "openFilePicker",
            "openFolderPicker",
            "buildMetadataPayload",
            "runExtraction",
            "enhanceSelect",
            "initComboEvents",
            "setSelectOptions",
            "refreshCombo",
            "loadModelContents",
            "loadReportContents",
            "tsdPayload",
            "renderTsdState",
            "runTsd",
            "openTsdDocument",
            "saveJsonDialog",
            "analysisLoad",
            "analysisRender",
            "analysisRun",
            "analysisExport",
            "lineageLoadState",
            "lineageSearch",
            "lineageOpen",
            "lineageRenderGraph",
            "lineageExport",
            "startJob",
        ):
            self.assertEqual(
                text.count(f"function {name}("),
                1,
                f"helper {name} harus dideklarasikan tepat satu kali",
            )

    def test_web_combo_options_do_not_shrink(self) -> None:
        # Daftar 800+ opsi pernah dipaksa flexbox menyusut sampai teks
        # terpotong; opsi harus flex:none dan placeholder tidak ikut daftar.
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("flex:0 0 auto", css)
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('item.value !== ""', js)

    def test_web_endpoint_help_is_a_tooltip_icon(self) -> None:
        text = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="info-tip"', text)
        self.assertIn('data-tooltip="The XMLA endpoint is derived', text)
        self.assertIn('id="xmlaEndpointHelp"', text)

    def test_web_tsd_design_has_screenshot_panel(self) -> None:
        text = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="captureScreenshots"',
            'id="clearShotCache"',
            'id="shotCachePath"',
            'id="tsdOutFolder"',
            'id="tsdPreview"',
            'id="reportWorkbook"',
            'id="contextJson"',
            'class="shot-cache"',
        ):
            self.assertIn(marker, text, f"desain TSD kehilangan {marker}")

    def test_web_analysis_table_and_report_structure(self) -> None:
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".row-inline .select{ flex:1 1 auto; min-width:0; }", css)
        self.assertIn('relSvg.addEventListener("pointerdown"', js)
        self.assertIn("state.relPanX", js)
        self.assertIn("function applyAnalysisCellTitles(", js)
        self.assertIn("requestAnimationFrame(applyAnalysisCellTitles)", js)
        self.assertIn(".detail-head .btn{ flex:0 0 auto; }", css)
        self.assertIn(".graph-wrap{ padding:8px 12px 12px; background:var(--console-bg); overflow:hidden; }", css)
        self.assertIn("function analysisLoadReportDetail(", js)
        self.assertIn("/api/analysis/report-detail", js)
        self.assertIn('label: t("Practice score")', js)
        self.assertIn('label: t("Broken visuals")', js)
        self.assertIn('{ label: "Views", num: true }', js)
        self.assertIn("hidden: Boolean(page.is_hidden)", js)
        self.assertIn("hidden: Boolean(visual.is_hidden)", js)
        self.assertIn('page: \'<svg class="row-ico"', js)
        self.assertIn("options.hidden && ANALYSIS_ICONS.hidden", js)
        self.assertIn(
            "#analyzeTable td.cell-name{ padding-left:calc(9px + var(--depth, 0) * 16px); }",
            css,
        )
        self.assertIn("analysisIsOpen(tableId, false)", js)

    def test_web_lineage_is_live_and_zoomable(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="lineageZoomIn"', html)
        self.assertIn('id="lineageZoomOut"', html)
        self.assertIn('id="lineageZoomReset"', html)
        self.assertIn("function applyLineageZoom(", js)
        self.assertIn("function setLineageZoom(", js)
        self.assertIn("function lineageChain(", js)
        self.assertIn("lineageChainId", js)
        self.assertIn('" is-chain"', js)
        self.assertIn('lineageSvg.addEventListener("pointerdown"', js)
        self.assertIn('state.lineageJustDragged', js)
        self.assertNotIn("var lineageNodes = {", js)
        self.assertNotIn("var lineageEdges = [", js)
        self.assertNotIn("function renderLineage(", js)
        self.assertIn('isApp ? "Apps" : "Local report"', js)

    def test_web_sidebar_and_partisi_placeholder(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="appSidebar"', html)
        self.assertIn('id="sidebarToggle"', html)
        self.assertIn('data-view="partisi"', html)
        self.assertIn('"pbi-sidebar"', js)
        self.assertIn("function applySidebar(", js)
        self.assertIn('id="reloadModelAnalisa"', html)
        self.assertIn("analysisLoadDatasets()", js)
        self.assertNotIn("openSettingsFromAnalysis", html)
        self.assertNotIn("reloadWsAnalisa", html)
        self.assertNotIn("partitionTables", js)
        self.assertNotIn("renderPartitions", js)
        self.assertNotIn("partitionDialog", html)
        self.assertIn("partitionEmptyState", html)
        self.assertIn('item.kind !== "measure"', js)

    def test_web_analysis_has_six_tabs_and_no_mock_model_data(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for tab in ("all", "tables", "relationships", "report", "dax", "m"):
            self.assertIn(f'data-analysis-tab="{tab}"', html)
        js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        presenter = (ROOT / "server" / "presenters" / "analysis.py").read_text(
            encoding="utf-8"
        )
        for marker in (
            "var modelTables",
            "var relationshipRows",
            "var reportModel",
            "var mQueries",
            "Fact Sales[Order Date Key]",
        ):
            self.assertNotIn(marker, js, f"data contoh mockup tidak boleh ada: {marker}")
        for name in (
            "analysisFlatRows",
            "analysisChildGroups",
            "analysisTreeView",
            "analysisRenderGraph",
            "analysisRelationshipRows",
            "analysisDaxRows",
            "analysisMRows",
        ):
            self.assertEqual(
                js.count(f"function {name}("),
                1,
                f"helper {name} harus dideklarasikan tepat satu kali",
            )
        self.assertIn('if (tab === "all") view = analysisFlatRows();', js)
        for label in (
            "Used in artifacts",
            "Used in visuals",
            "Used as key column",
            "Used in relationships",
            "Used in row/object level security",
            "Used in page level filters",
            "Used in column sorting",
            "Used in field parameters",
        ):
            self.assertIn(f'"{label}"', presenter, f"grup {label} hilang dari presenter")
        self.assertIn('label: "Auto create"', js)
        self.assertIn('label: t("# used"), key: "used", num: true', js)
        self.assertNotIn('{ label: "Security filter"', js)
        self.assertNotIn('kind: "subhead"', js)
        self.assertIn('"columns": [', presenter)
        self.assertNotIn("function processPartitions(", js)
        self.assertNotIn('$("#processSelectedPartitions").addEventListener', js)


if __name__ == "__main__":
    unittest.main()
