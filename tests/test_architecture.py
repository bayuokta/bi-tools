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


def web_script_text() -> str:
    """Semua JS sumber UI (app.js + modul di web/js)."""
    files = [ROOT / "web" / "app.js"]
    files.extend(sorted((ROOT / "web" / "js").rglob("*.js")))
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


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

    def test_user_login_uses_azure_identity_only_in_auth(self) -> None:
        self.assertEqual(
            set(matching(r"azure\.identity|InteractiveBrowserCredential")),
            {"core/auth.py"},
        )

    def test_no_token_in_connection_string(self) -> None:
        self.assertEqual(matching(r"password\s*="), [])

    def test_http_delete_method_is_forbidden(self) -> None:
        # Kebijakan tool: operasi hapus/bersihkan memakai POST (.../clear,
        # .../cancel). DELETE hanya boleh muncul sebagai SQL "DELETE FROM".
        patterns = (
            r"\brequest\(\s*[\"']DELETE[\"']",
            r"\bjson\(\s*[\"']DELETE[\"']",
            r"\b_call\(\s*[\"']DELETE[\"']",
            r"\b_try\(\s*[\"']DELETE[\"']",
            r"\b_paged\(\s*[\"']DELETE[\"']",
            r"@router\.delete\(",
            r"\.delete\(",
        )
        found = sorted({hit for pattern in patterns for hit in matching(pattern)})
        self.assertEqual(found, [], "metode HTTP DELETE dilarang di API apa pun")

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
        text = web_script_text()
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
            "lineageLayout",
            "lineageVisibleNodes",
            "lineageSvgDocument",
            "lineageExportImage",
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
        js = web_script_text()
        self.assertIn('item.value !== ""', js)

    def test_web_stays_static_without_framework_or_build_step(self) -> None:
        web = ROOT / "web"
        self.assertFalse((web / "package.json").exists())
        self.assertFalse((web / "node_modules").exists())
        self.assertFalse((web / "vite.config.js").exists())
        for path in web.rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"""(?:from|import)\s+["']([^"']+)["']""", text):
                target = match.group(1)
                self.assertTrue(
                    target.startswith("."),
                    f"{path.relative_to(ROOT).as_posix()} mengimpor "
                    f"dependensi eksternal: {target}",
                )
        markup = (web / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('src="http', markup)
        self.assertNotIn("cdn.", markup)
        self.assertIn('<script type="module" src="app.js"></script>', markup)

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
        js = web_script_text()
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
        self.assertIn('label: "Practice score"', js)
        self.assertIn('label: "Broken visuals"', js)
        self.assertIn('{ label: "Views", num: true }', js)
        self.assertIn("hidden: Boolean(page.is_hidden)", js)
        self.assertIn("hidden: Boolean(visual.is_hidden)", js)
        self.assertIn('page: icon("file", "row-ico"', js)
        self.assertIn("options.hidden && ANALYSIS_ICONS.hidden", js)
        self.assertIn(
            "#analyzeTable td.cell-name{ padding-left:calc(9px + var(--depth, 0) * 16px); }",
            css,
        )
        self.assertIn("analysisIsOpen(tableId, false)", js)

    def test_web_lineage_is_live_and_zoomable(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="lineageZoomIn"', html)
        self.assertIn('id="lineageZoomOut"', html)
        self.assertIn('id="lineageZoomReset"', html)
        self.assertIn("function applyLineageZoom(", js)
        self.assertIn("function setLineageZoom(", js)
        self.assertIn("is-near", js)
        self.assertIn(".edge.is-selected", css)
        self.assertNotIn("lineageChainId", js)
        self.assertNotIn("function lineageChain(", js)
        self.assertIn('lineageSvg.addEventListener("pointerdown"', js)
        self.assertIn('state.lineageJustDragged', js)
        self.assertNotIn("var lineageNodes = {", js)
        self.assertNotIn("var lineageEdges = [", js)
        self.assertNotIn("function renderLineage(", js)
        self.assertIn('isApp ? "Apps" : "Local report"', js)
        # Desain node mengikuti mockup: warna per tipe, band, ikon, halo.
        self.assertIn("NODE_HUE_BY_TYPE", js)
        self.assertIn("nodeIconMarkup(", js)
        self.assertIn("node-band-rule", js)
        self.assertIn('class="node-halo"', js)
        self.assertIn("--node-report", css)
        self.assertIn('data-hue="', js)
        # Hasil pencarian tidak lagi otomatis membuka item pertama.
        search = js.index("function lineageSearch(")
        render = js.index("function lineageRenderResults(", search)
        self.assertNotIn("lineageOpen(", js[search:render])
        # Chip tipe tidak boleh menempati kolom pertama (bug tumpukan).
        self.assertIn(".result-type{ grid-column:2", css)

    def test_web_lineage_has_image_export_and_node_type_filter(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        api = (ROOT / "server" / "api" / "lineage.py").read_text(encoding="utf-8")
        for marker in ('id="exportSvg"', 'id="exportPng"', 'id="lineageNodeType"'):
            self.assertIn(marker, html)
        self.assertIn('@router.post("/image")', api)
        self.assertIn("function lineageSvgDocument(", js)
        self.assertIn("function lineageExportImage(", js)
        self.assertIn("function lineageLayout(", js)
        self.assertIn("function lineageVisibleNodes(", js)
        self.assertIn('"/api/lineage/image"', js)
        self.assertIn("is-filtered", css)
        # Layout harus stabil saat filter aktif: posisi dihitung dari graph,
        # bukan dari daftar node yang tersaring.
        self.assertIn("var layout = lineageLayout(graph)", js)
        self.assertNotIn("lineageLayout(visibleNodes", js)

    def test_partition_tom_is_isolated_in_child_process(self) -> None:
        service = (ROOT / "core" / "partition_service.py").read_text(encoding="utf-8")
        self.assertNotIn("tom_client", service)
        presenter = (
            ROOT / "server" / "presenters" / "partitions.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("tom_client", presenter)
        plan = (ROOT / "core" / "partition_plan.py").read_text(encoding="utf-8")
        self.assertNotIn("import clr", plan)
        self.assertNotIn("from .tom_client", plan)
        self.assertNotIn("from .xmla_client", plan)
        # Cache controller ADOMD dibersihkan sebelum koneksi XMLA.
        xmla = (ROOT / "core" / "xmla_client.py").read_text(encoding="utf-8")
        self.assertIn("_clear_adomd_channel_cache(", xmla)
        self.assertIn("HttpStream+HttpChannelManager", xmla)

    def test_web_metadata_and_tsd_are_one_workflow(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertNotIn('data-view="tsd"', html)
        self.assertIn('id="metaSteps"', html)
        self.assertIn('data-meta-step="extract"', html)
        self.assertIn('data-meta-step="tsd"', html)
        self.assertIn('id="tsdLock"', html)
        self.assertIn('id="backToExtract"', html)
        self.assertIn("view view--step", html)
        self.assertIn("function setMetaStep(", js)
        self.assertIn("function applyMetaSteps(", js)
        self.assertIn("function tsdUnlocked(", js)
        self.assertNotIn('showView("tsd")', js)
        self.assertIn(".meta-steps{", css)
        self.assertIn(".step-head{", css)

    def test_web_sidebar_and_partisi_page(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
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
        self.assertIn('id="partitionDialog"', html)
        self.assertIn("partitionEmptyState", html)
        self.assertIn("function partitionLoadState(", js)
        self.assertIn("function partitionRender(", js)
        self.assertIn("/api/partitions/inventory", js)
        self.assertIn("/api/partitions/refresh", js)
        self.assertIn('confirmation: "PROCESS"', js)
        self.assertIn('item.kind === "column"', js)

    def test_partition_core_has_no_terminal_calls(self) -> None:
        for name in ("tom_client.py", "partition_service.py"):
            text = (ROOT / "core" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?m)^\s*(print\(|input\()")

    def test_web_analysis_starts_only_from_buttons(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        presenter = (ROOT / "server" / "presenters" / "analysis.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="includeReports"', html)
        self.assertIn('include_reports: $("#includeReports").checked', js)
        self.assertNotIn("analysisScheduleRun", js)
        self.assertNotIn("analysisAutoRun", js)
        self.assertIn(
            '$("#runAnalyze").addEventListener("click", analysisRun)', js
        )
        self.assertIn(
            '$("#analyzeFromEmpty").addEventListener("click", analysisRun)', js
        )
        self.assertIn("state.analysisTarget", js)
        self.assertNotIn("analysisLoadSnapshot", js)
        self.assertNotIn("/api/analysis/snapshot?dataset_id=", js)
        self.assertIn('sqlite3.connect(":memory:"', presenter)
        self.assertIn("snapshot_from_connection", presenter)
        self.assertNotIn("load_snapshot", presenter)
        self.assertIn("include_reports", presenter)

    def test_web_analysis_context_menu_phase_one(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        for marker in (
            'id="analysisMenu"',
            'id="analysisDetailsDialog"',
            'id="analysisDetailsBody"',
            'id="copyAnalysisExpression"',
        ):
            self.assertIn(marker, html)
        for marker in (
            "function analysisOpenMenu(",
            "function analysisCloseMenu(",
            "function analysisMenuEntries(",
            "function analysisDetailsMarkup(",
            "function analysisOpenDetails(",
            "function copyTextValue(",
            'addEventListener("contextmenu"',
            "data-analysis-menu",
            "data-item-kind",
            'aria-disabled="true"',
        ):
            self.assertIn(marker, js)
        for label in (
            "Expand items below",
            "Collapse items below",
            "Copy text",
            "View DAX expression",
            "View column lineage",
            "View column lineage graph",
            "Column details",
            "Measure details",
            "View dependencies",
            "Table options",
            "Model options",
            "Exports",
        ):
            self.assertIn(label, js)
        for marker in (".context-menu", ".menu-item", ".row-menu-btn", ".detail-code"):
            self.assertIn(marker, css)
        self.assertNotIn("Fact Sales[Order Date Key]", js)

    def test_web_analysis_lineage_graph_uses_backend_layout(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        presenter = (ROOT / "server" / "presenters" / "analysis.py").read_text(
            encoding="utf-8"
        )
        core = (ROOT / "core" / "analysis_lineage.py").read_text(encoding="utf-8")
        for marker in (
            'id="analysisLineageDialog"',
            'id="analysisLineageCanvasWrap"',
            'id="analysisLineageNodes"',
            'id="analysisLineageEdges"',
            'id="analysisLineageDirection"',
            'id="analysisLineageView"',
            'id="analysisLineageOutline"',
            'id="analysisLineageOutlineMode"',
            'id="analysisLineageExportSvg"',
            'id="analysisLineageExportPng"',
            'id="analysisLineageM"',
            'id="analysisLineageMList"',
            'id="analysisSubmenu"',
            'id="analysisRawDialog"',
            'id="analysisRawTable"',
            'id="analysisRawLoad"',
            'id="analysisItemDialog"',
            'id="analysisItemTabs"',
            'id="analysisRawMetaDialog"',
        ):
            self.assertIn(marker, html)
            self.assertEqual(
                html.count(marker), 1, f"{marker} harus unik (bentrok dengan halaman Lineage)"
            )
        for marker in (
            "function analysisLineageOpen(",
            "function analysisLineageRender(",
            "function analysisLineageOutlineMarkup(",
            "function analysisLineageEdgePath(",
            "function analysisLineageEdgeRoutes(",
            "function analysisLineageSvgDocument(",
            "function analysisExportLineageImage(",
            "function analysisLineageSelect(",
            "function analysisLineageRenderM(",
            "function analysisLineageViewButtons(",
            "function analysisOpenSubmenu(",
            "function analysisLineageReroot(",
            "function analysisOpenPreview(",
            "function analysisRunPreview(",
            "function analysisOpenItemDetails(",
            "function analysisOpenRawMetadata(",
            "function analysisOpenTableDetails(",
            "function analysisOpenModelDetails(",
            "function analysisExportLineage(",
            "function analysisExportDependencies(",
            "function analysisCopyMermaid(",
            "/api/analysis/lineage",
            "/api/analysis/lineage/image",
            "/api/analysis/preview",
            "/api/analysis/raw-metadata",
            "/api/analysis/details",
            "data-node-id",
            "data-menu-submenu",
            "data-outline-mode",
            "table-lineage",
            "node.x",
            "data-node-kind",
        ):
            self.assertIn(marker, js)
        self.assertIn("def preview_payload(", presenter)
        self.assertIn("def raw_metadata_payload(", presenter)
        self.assertIn("def details_payload(", presenter)
        self.assertIn("def export_lineage(", presenter)
        self.assertIn("def export_lineage_image(", presenter)
        self.assertIn("def export_dependencies(", presenter)
        self.assertIn("def lineage_payload(", presenter)
        self.assertIn("build_table_lineage", presenter)
        self.assertIn("def build_lineage(", core)
        self.assertIn("def build_table_lineage(", core)
        self.assertIn("OUTLINE_MAX_ROWS", core)
        self.assertIn("GROUP_ORDER", core)
        self.assertNotIn("sqlite3", core)

    def test_view_modules_use_app_bridge_for_ui_helpers(self) -> None:
        """Helper app.js harus diakses lewat ``app.*``, bukan identifier bebas.

        Termasuk referensi tanpa pemanggilan seperti ``.catch(reportError)``
        yang tidak tertangkap pemeriksaan ``nama(`` biasa.
        """

        app_api = (ROOT / "web" / "js" / "core" / "app_api.js").read_text(
            encoding="utf-8"
        )
        names = sorted(
            set(re.findall(r'^\s+(\w+): missing\("', app_api, re.M)) - {"api"}
        )
        self.assertTrue(names)
        for path in (ROOT / "web" / "js" / "views").rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            # Buang template/string/komentar agar teks seperti "/api/..." tidak
            # dianggap kode.
            code = re.sub(r"`(?:[^`\\]|\\.)*`", '""', text, flags=re.S)
            code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)
            code = re.sub(r"'(?:[^'\\]|\\.)*'", "''", code)
            code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
            code = re.sub(r"//[^\n]*", "", code)
            local = set(
                re.findall(r"^\s*(?:export\s+)?function\s+(\w+)\s*\(", code, re.M)
            )
            local |= set(
                re.findall(r"^\s*(?:const|let|var)\s+(\w+)\s*=", code, re.M)
            )
            imports: set[str] = set()
            for match in re.finditer(r"import\s*\{([^}]*)\}\s*from", code):
                for part in match.group(1).split(","):
                    alias = part.strip().split(" as ")[-1].strip()
                    if alias:
                        imports.add(alias)
            for name in names:
                if name in local or name in imports:
                    continue
                bare = re.search(
                    r"(?<![.\w])" + re.escape(name) + r"\b(?!\s*:)", code
                )
                if bare is None:
                    continue
                self.fail(
                    f"{path.relative_to(ROOT).as_posix()} memakai "
                    f"{name} tanpa app.* (helper ada di app.js)"
                )

    def test_main_actions_do_not_preblock_stale_jobs(self) -> None:
        """Guard job lokal di view membuat job basi tidak bisa pulih."""

        for name, marker in (
            ("analysis.js", "export function analysisRun("),
            ("metadata-tsd.js", "export function runExtraction("),
            ("metadata-tsd.js", "export function runTsd("),
            ("partitions-lineage.js", "export function partitionLoadInventory("),
            ("partitions-lineage.js", "export function partitionConfirmProcess("),
        ):
            text = (ROOT / "web" / "js" / "views" / name).read_text(
                encoding="utf-8"
            )
            start = text.index(marker)
            end = text.find("\n  }", start)
            body = text[start:end]
            self.assertNotIn(
                "if (state.jobId",
                body,
                f"{name}: {marker} masih memblokir job basi sebelum startJob",
            )
            self.assertNotIn(
                "if (state.partitionRunning",
                body,
                f"{name}: {marker} memakai flag running yang bisa basi",
            )

    def test_job_start_recovers_from_stale_local_state(self) -> None:
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function clearJobState(", app)
        self.assertIn(
            'api().get("/api/jobs/" + encodeURIComponent(pending))', app
        )
        self.assertIn("startJob(options);", app)

    def test_partition_helpers_live_in_partition_module(self) -> None:
        partition = (ROOT / "web" / "js" / "views" / "partitions-lineage.js").read_text(
            encoding="utf-8"
        )
        for name in (
            "partitionRows",
            "partitionSelectedRows",
            "partitionTime",
            "partitionRefreshLabel",
        ):
            self.assertIn(f"function {name}(", partition)
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("partitionRows", app)
        analysis = (ROOT / "web" / "js" / "views" / "analysis.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("function partitionRows(", analysis)

    def test_partition_inventory_groups_by_table(self) -> None:
        partition = (ROOT / "web" / "js" / "views" / "partitions-lineage.js").read_text(
            encoding="utf-8"
        )
        for name in (
            "partitionGroups",
            "partitionGroupSummary",
            "partitionGroupRow",
            "partitionItemRow",
            "partitionToggleTable",
            "partitionSelectTable",
            "partitionSetAllOpen",
        ):
            self.assertIn(f"function {name}(", partition)
        self.assertIn("state.partitionOpen", partition)
        state = (ROOT / "web" / "js" / "core" / "state.js").read_text(encoding="utf-8")
        self.assertIn("partitionOpen:", state)
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("partitionToggleTable", app)
        self.assertIn("partitionSelectTable", app)

    def test_web_compare_is_read_only_and_roles_tab_exists(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        for marker in (
            'data-view="compare"',
            'id="view-compare"',
            'id="runCompare"',
            'id="compareOptions"',
            'id="compareOptionsDialog"',
            'id="cmpOptRoles"',
            'id="cmpOptPartitions"',
            'id="cmpApply"',
            'id="tab-roles"',
            'id="cmpDiffSummary"',
            '<use href="#i-chevron-up">',
        ):
            self.assertIn(marker, html)
        for marker in (
            "function initCompareEvents(",
            "function runCompare(",
            "function compareGroups(",
            "function treeRow(",
            "function renderDiffLine(",
            "function bindDiffScroll(",
            "diff-token is-changed",
            "is-spacer",
            "is-block-start",
            "is-block-end",
            "/api/compare/run",
            "/api/compare/export",
            "/api/compare/script",
            "Comparison is read-only",
        ):
            self.assertIn(marker, js)
        compare_presenter = (
            ROOT / "server" / "presenters" / "compare.py"
        ).read_text(encoding="utf-8")
        css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("min-width:100%", css)
        self.assertNotIn("box-shadow:inset 1px 0 0 #e57373", css)
        self.assertIn("def run_job(", compare_presenter)
        self.assertIn("read_only", compare_presenter)
        self.assertIn("Tidak ada jalur tulis", compare_presenter)
        self.assertNotIn("import clr", compare_presenter)
        self.assertNotIn("tom_compare", compare_presenter)

    def test_web_highlighting_is_local_and_offline(self) -> None:
        vendor = ROOT / "web" / "vendor" / "prism"
        for name in (
            "prism-core.min.js",
            "prism-dax.min.js",
            "prism-json.min.js",
            "LICENSE",
        ):
            self.assertTrue((vendor / name).exists(), name)
        markup = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("vendor/prism/prism-core.min.js", markup)
        self.assertIn("vendor/prism/prism-dax.min.js", markup)
        self.assertIn("vendor/prism/prism-json.min.js", markup)
        self.assertNotIn("cdn.", markup)
        highlight = (ROOT / "web" / "js" / "core" / "highlight.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("languages.tmdl", highlight)
        self.assertIn("highlightCode", highlight)
        self.assertIn("highlightLine", highlight)

    def test_web_analysis_has_nine_tabs_and_no_mock_model_data(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for tab in ("all", "tables", "relationships", "roles", "report", "dax", "m", "health", "bestpractice"):
            self.assertIn(f'data-analysis-tab="{tab}"', html)
        js = web_script_text()
        self.assertIn("function analysisRoleRows(", js)
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
            "analysisHealthRows",
            "analysisHealthOpen",
            "analysisPracticeTitle",
            "analysisBestPracticeRows",
            "analysisRenderBestPracticeSummary",
            "analysisOpenBpRules",
        ):
            self.assertEqual(
                js.count(f"function {name}("),
                1,
                f"helper {name} harus dideklarasikan tepat satu kali",
            )
        self.assertIn('if (tab === "all") view = analysisFlatRows();', js)
        for label in (
            "Used in visuals",
            "Used in artifacts",
            "Indirect references",
            "Used in visual level filters",
            "Used in page level filters",
            "Used in report level filters",
            "Used in relationships",
            "Used in row/object level security",
            "Used in Power Query",
            "Used as default label",
            "Used in calculated tables",
            "Used in hierarchy",
            "Used as key column",
            "Used in column sorting",
            "Used in field parameters",
        ):
            self.assertIn(f'"{label}"', presenter, f"grup {label} hilang dari presenter")
        self.assertIn('label: "Auto created"', js)
        self.assertIn('label: "DAX uses", key: "used", num: true', js)
        self.assertIn('label: "# used", key: "uses", num: true', js)
        self.assertNotIn('{ label: "Security filter"', js)
        self.assertNotIn('kind: "subhead"', js)
        self.assertIn('"columns": [', presenter)
        self.assertNotIn("function processPartitions(", js)
        self.assertIn('$("#processSelectedPartitions").addEventListener', js)

    def test_web_tables_export_uses_template_groups(self) -> None:
        js = web_script_text()
        presenter = (ROOT / "server" / "presenters" / "analysis.py").read_text(
            encoding="utf-8"
        )
        table_export = (ROOT / "core" / "table_export.py").read_text(
            encoding="utf-8"
        )
        for label in (
            "Used in artifacts",
            "Used in calculated tables",
            "Used in field parameters",
            "Columns",
            "Hierarchies",
            "Measures",
            "Used in calculation items",
            "Used in row/object level security",
        ):
            self.assertIn(f'"{label}"', table_export, f"grup {label} hilang")
        self.assertIn("write_table_export", presenter)
        self.assertIn("build_table_groups", presenter)
        self.assertIn("Export tables", js)
        self.assertIn("analysisStatusCell", js)
        self.assertIn('"Has error"', js)
        self.assertEqual(js.count("function analysisChildGroups("), 1)
        self.assertIn("function analysisTableSummary(", js)

    def test_web_reports_export_uses_template_tree_and_pbi_inspector(self) -> None:
        js = web_script_text()
        presenter = (ROOT / "server" / "presenters" / "analysis.py").read_text(
            encoding="utf-8"
        )
        report_export = (ROOT / "core" / "report_export.py").read_text(
            encoding="utf-8"
        )
        report_usage = (ROOT / "core" / "report_usage.py").read_text(
            encoding="utf-8"
        )
        self.assertTrue((ROOT / "rules" / "PBIInspector-rules.json").exists())
        self.assertTrue((ROOT / "core" / "report_practice.py").exists())
        self.assertIn("REPORT_RESULT_COLUMNS", report_export)
        self.assertIn("write_report_export", presenter)
        self.assertIn("build_report_practice", report_usage)
        for name in (
            "analysisReportVisualRows",
            "analysisReportFilterRows",
            "analysisReportPageRows",
        ):
            self.assertEqual(
                js.count(f"function {name}("),
                1,
                f"helper {name} harus dideklarasikan tepat satu kali",
            )
        self.assertIn("Export reports", js)
        self.assertIn("report_type", js)
        self.assertIn("practice_label", js)
        self.assertNotIn("Hidden pages", js)

    def test_web_relationships_export_uses_template_columns(self) -> None:
        js = web_script_text()
        presenter = (ROOT / "server" / "presenters" / "analysis.py").read_text(
            encoding="utf-8"
        )
        relationship_export = (ROOT / "core" / "relationship_export.py").read_text(
            encoding="utf-8"
        )
        for column in (
            "Name",
            "ID",
            "Is_active",
            "Cross_filter",
            "Cardinality",
            "Status",
            "Auto_created",
            "DAX_uses",
            "From_column",
            "To_column",
        ):
            self.assertIn(f'"{column}"', relationship_export, column)
        self.assertIn("write_relationship_export", presenter)
        self.assertIn("relationship_row", presenter)
        self.assertIn("Export relationships", js)
        self.assertIn('label: "Is active"', js)
        self.assertIn('label: "DAX uses"', js)
        self.assertIn('label: "ID"', js)

    def test_web_dax_export_uses_template_columns(self) -> None:
        js = web_script_text()
        presenter = (ROOT / "server" / "presenters" / "analysis.py").read_text(
            encoding="utf-8"
        )
        dax_export = (ROOT / "core" / "dax_export.py").read_text(encoding="utf-8")
        for column in (
            "Name",
            "Table",
            "Type",
            "Has_error",
            "Best_practices_violations",
            "Source",
            "Source_type",
            "Lineage_tag",
            "Display_folder",
            "Description",
            "Expression",
        ):
            self.assertIn(f'"{column}"', dax_export, column)
        self.assertIn("write_dax_export", presenter)
        self.assertIn('"Export DAX expressions"', js)
        self.assertEqual(js.count("function analysisDaxObjects("), 1)
        self.assertEqual(js.count("function analysisExpressionPreview("), 1)
        self.assertIn('label: "Best practices violations"', js)
        self.assertIn('label: "Lineage tag"', js)

    def test_health_rules_dialog_and_rule_coverage(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        core = (ROOT / "core" / "model_health.py").read_text(encoding="utf-8")
        for marker in (
            'id="healthRulesInfo"',
            'id="analysisHealthRulesDialog"',
            'id="analysisHealthRulesBody"',
            'id="closeHealthRules"',
            'id="doneHealthRules"',
        ):
            self.assertIn(marker, html)
        for name in ("analysisHealthRulesMarkup", "analysisOpenHealthRules"):
            self.assertEqual(
                js.count(f"function {name}("),
                1,
                f"helper {name} harus dideklarasikan tepat satu kali",
            )
        for rule in (
            "column_error",
            "measure_error",
            "unused_table",
            "isolated_table",
            "bidirectional_relationship",
            "many_to_many_relationship",
            "inactive_relationship",
            "auto_relationship",
            "large_dictionary",
            "unused_calculated_column",
            "page_without_visuals",
            "hidden_page_with_visuals",
            "missing_theme",
            "broken_visual",
        ):
            self.assertIn(f'"{rule}"', core, f"aturan {rule} hilang dari core")
            self.assertIn(
                f'rule: "{rule}"',
                js,
                f"aturan {rule} belum punya entri bantuan di UI",
            )


    def test_best_practice_tab_and_catalog_dialog(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        js = web_script_text()
        for marker in (
            'id="bpSummary"',
            'id="bpScore"',
            'id="bpVerdict"',
            'id="bpRulesInfo"',
            'id="analysisBpRulesDialog"',
            'id="analysisBpRulesBody"',
            'id="closeBpRules"',
            'id="doneBpRules"',
        ):
            self.assertIn(marker, html)
        for name in (
            "analysisBestPracticeRows",
            "analysisRenderBestPracticeSummary",
            "analysisBpRulesMarkup",
            "analysisOpenBpRules",
        ):
            self.assertEqual(
                js.count(f"function {name}("),
                1,
                f"helper {name} harus dideklarasikan tepat satu kali",
            )
        self.assertIn(
            '$("#bpRulesInfo").addEventListener("click", analysisOpenBpRules)', js
        )


class SyncSeparationTests(unittest.TestCase):
    """Admin API dan upload snapshot hanya milik paket ``sync``."""

    def test_admin_endpoints_only_in_sync(self) -> None:
        self.assertEqual(matching(r"admin/"), [])
        sync_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "sync").rglob("*.py")
        )
        self.assertIn("admin/workspaces/getInfo", sync_text)
        self.assertIn("admin/groups", sync_text)
        self.assertIn("admin/reports", sync_text)

    def test_app_does_not_import_sync(self) -> None:
        self.assertEqual(matching(r"^\s*(from|import)\s+sync\b"), [])

    def test_sync_is_not_an_app_cli_command(self) -> None:
        cli_text = (ROOT / "cli" / "__main__.py").read_text(encoding="utf-8")
        self.assertNotIn('"sync"', cli_text)
        self.assertFalse((ROOT / "cli" / "sync.py").exists())
        for name in ("flow.py", "admin_api.py", "catalog.py", "lineage.py"):
            self.assertTrue((ROOT / "sync" / name).exists(), name)

    def test_web_has_no_service_principal_controls(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for marker in ("clientSecret", "syncCatalog", "scanLineage", "test-token"):
            self.assertNotIn(marker, html)
        js = web_script_text()
        for marker in (
            "/api/settings/credentials",
            "/api/settings/test-token",
            "/api/catalog/sync",
            "/api/catalog/scan",
        ):
            self.assertNotIn(marker, js)

    def test_catalog_api_is_read_only(self) -> None:
        text = (ROOT / "server" / "api" / "catalog.py").read_text(encoding="utf-8")
        self.assertNotIn('"/sync"', text)
        self.assertNotIn('"/scan"', text)

    def test_graph_only_in_sync_package(self) -> None:
        self.assertEqual(matching(r"graph\.microsoft\.com"), [])
        graph_text = (ROOT / "sync" / "graph.py").read_text(encoding="utf-8")
        self.assertIn("graph.microsoft.com", graph_text)
        self.assertIn("createUploadSession", graph_text)


class ServiceModeGuardTests(unittest.TestCase):
    """Web hanya memakai akun 365; tidak boleh ada sisa mode service."""

    def test_server_has_no_service_principal_mode(self) -> None:
        server_files = files_under("server")
        self.assertEqual(
            matching_in(server_files, r"auth_mode|set_principal|ServicePrincipal"), []
        )
        self.assertEqual(
            matching_in(
                server_files, r"AUTH_MODE_KEY|AUTH_CLIENT_KEY|AUTH_SECRET_KEY"
            ),
            [],
        )

    def test_web_has_no_auth_mode(self) -> None:
        self.assertNotIn("auth_mode", web_script_text())

    def test_restore_writes_only_through_fabric_client(self) -> None:
        self.assertEqual(matching(r"/updateDefinition"), ["core/fabric_api.py"])

    def test_sign_in_and_sign_out_handlers_exist(self) -> None:
        text = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('$("#signIn").addEventListener("click"', text)
        self.assertIn('$("#signOut").addEventListener("click"', text)


if __name__ == "__main__":
    unittest.main()
