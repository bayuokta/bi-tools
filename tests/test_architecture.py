"""Penjaga batas arsitektur: satu tempat untuk HTTP, satu tempat untuk token."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("core", "cli", "app")


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


class PresentationBoundaryTests(unittest.TestCase):
    def test_core_has_no_qt(self) -> None:
        hits = matching_in(
            files_under("core"), r"^\s*(import PySide6|from PySide6\b)"
        )
        self.assertEqual(hits, [], "core harus bebas Qt agar bisa dipakai CLI")

    def test_worker_instantiated_only_in_job_runner(self) -> None:
        self.assertEqual(
            matching_in(files_under("app"), r"^\s*worker = ExtractionWorker\("),
            ["app/job_runner.py"],
        )

    def test_qthread_subclass_only_in_worker(self) -> None:
        self.assertEqual(
            matching_in(files_under("app"), r"^\s*class \w+\(QThread\)"),
            ["app/worker.py"],
        )

    def test_cli_does_not_import_app(self) -> None:
        hits = matching_in(files_under("cli"), r"^\s*(import app\b|from app\b)")
        self.assertEqual(hits, [], "CLI harus berdiri di atas core, bukan GUI")

    def test_viewmodels_have_no_widgets(self) -> None:
        viewmodels = [
            path
            for path in source_files()
            if "viewmodels" in path.relative_to(ROOT).parts
        ]
        self.assertTrue(viewmodels, "folder app/viewmodels belum ada")
        hits = matching_in(
            viewmodels,
            r"^\s*(import PySide6\.QtWidgets|from PySide6\.QtWidgets\b)",
        )
        self.assertEqual(hits, [], "view model tidak boleh menyentuh widget")

    def test_metadata_views_do_not_call_use_cases(self) -> None:
        targets = [
            ROOT / "app" / "local_tab.py",
            ROOT / "app" / "service_tab.py",
            ROOT / "app" / "extraction_base.py",
        ]
        hits = matching_in(targets, r"^\s*from core\.(jobs|report|model)\b")
        self.assertEqual(hits, [], "view metadata hanya boleh lewat view model")

    def test_tsd_view_does_not_call_use_cases(self) -> None:
        target = [ROOT / "app" / "tsd_tab.py"]
        hits = matching_in(
            target,
            r"\b(run_tsd|build_context|render_tsd|write_tsd|write_manual"
            r"|load_screenshot_set|capture_report|cache_dir)\s*\(",
        )
        self.assertEqual(hits, [], "view TSD hanya boleh lewat TsdViewModel")

    def test_lineage_view_does_not_touch_storage(self) -> None:
        target = [ROOT / "app" / "lineage_tab.py"]
        hits = matching_in(
            target,
            r"^\s*(import sqlite3|from core\.lineage_(store|service|export|scan)\b)",
        )
        self.assertEqual(hits, [], "view lineage hanya boleh lewat LineageViewModel")

    def test_settings_view_has_no_core_imports(self) -> None:
        target = [ROOT / "app" / "settings_tab.py"]
        hits = matching_in(target, r"^\s*(import core\b|from core\b)")
        self.assertEqual(hits, [], "view pengaturan hanya boleh lewat SettingsViewModel")


if __name__ == "__main__":
    unittest.main()
