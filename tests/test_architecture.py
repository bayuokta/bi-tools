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
        self.assertIn('data-tooltip="Endpoint XMLA diturunkan', text)
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


if __name__ == "__main__":
    unittest.main()
