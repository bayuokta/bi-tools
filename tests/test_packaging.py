"""Uji sumber versi, dispatcher CLI tunggal, dan berkas packaging."""

from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import __main__ as cli_main
from core import version

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"


class VersionTests(unittest.TestCase):
    def test_version_is_release_number(self) -> None:
        self.assertRegex(version.__version__, r"^\d+\.\d+\.\d+$")
        self.assertTrue(version.is_release_version())

    def test_require_release_version_returns_version(self) -> None:
        self.assertEqual(version.require_release_version(), version.__version__)

    def test_version_tuple_has_four_numbers(self) -> None:
        parts = version.version_tuple()
        self.assertEqual(len(parts), 4)
        self.assertTrue(all(isinstance(part, int) for part in parts))
        self.assertEqual(
            list(parts[:3]), [int(p) for p in version.__version__.split(".")]
        )

    def test_prerelease_is_not_release_version(self) -> None:
        self.assertFalse(version.is_release_version("0.2.0-rc1"))
        self.assertFalse(version.is_release_version("0.2"))
        self.assertTrue(version.is_release_version("10.20.30"))

    def test_app_name_present(self) -> None:
        self.assertEqual(version.APP_NAME, "BI Tools")


class CliDispatcherTests(unittest.TestCase):
    def test_help_lists_every_command(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(cli_main.main(["--help"]), 0)
        output = buffer.getvalue()
        for name in ("report", "model", "tsd", "lineage", "analyze", "install-browser"):
            self.assertIn(name, output)

    def test_without_arguments_prints_usage(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(cli_main.main([]), 2)
        self.assertIn("bi-tools-cli", buffer.getvalue())

    def test_version_flag(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertEqual(cli_main.main(["--version"]), 0)
        self.assertIn(version.__version__, buffer.getvalue())

    def test_unknown_command(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            self.assertEqual(cli_main.main(["tidak-ada"]), 2)
        self.assertIn("tidak dikenal", buffer.getvalue())

    def test_commands_point_to_modules_with_main(self) -> None:
        import importlib

        for name, (module_name, _description) in cli_main.COMMANDS.items():
            if not module_name:
                self.assertEqual(name, "install-browser")
                continue
            module = importlib.import_module(module_name)
            self.assertTrue(callable(getattr(module, "main", None)), name)

    def test_forwards_remaining_arguments(self) -> None:
        with patch("cli.report.main", return_value=7) as patched:
            self.assertEqual(cli_main.main(["report", "--report", "x.pbix"]), 7)
        patched.assert_called_once_with(["--report", "x.pbix"])

    def test_install_browser_is_lazy(self) -> None:
        with patch.object(cli_main, "install_browser", return_value=3) as patched:
            self.assertEqual(cli_main.main(["install-browser", "chromium"]), 3)
        patched.assert_called_once_with(["chromium"])

    def test_install_browser_prepares_frozen_browser_path(self) -> None:
        seen: dict[str, list[str]] = {}

        def fake_main() -> None:
            seen["argv"] = list(sys.argv)

        with patch.object(cli_main, "prepare_environment") as prepare, patch(
            "playwright.__main__.main", side_effect=fake_main
        ):
            self.assertEqual(cli_main.install_browser([]), 0)
        prepare.assert_called_once()
        self.assertEqual(seen["argv"][1:], ["install", "chromium"])

    def test_install_browser_reports_missing_playwright(self) -> None:
        buffer = io.StringIO()
        with patch.dict(sys.modules, {"playwright": None, "playwright.__main__": None}):
            with contextlib.redirect_stderr(buffer):
                code = cli_main.install_browser()
        self.assertEqual(code, 1)
        self.assertIn("Playwright", buffer.getvalue())


class PackagingAssetsTests(unittest.TestCase):
    def test_spec_builds_two_executables(self) -> None:
        text = (PACKAGING / "bi_tools.spec").read_text(encoding="utf-8")
        compile(text, "bi_tools.spec", "exec")
        self.assertIn('name=APP_NAME', text)
        self.assertIn('name="bi-tools-cli"', text)
        self.assertIn("console=False", text)
        self.assertIn("console=True", text)
        self.assertIn("collect_all(\"playwright\")", text)
        for asset in ("templates", "libs"):
            self.assertIn(asset, text)
        self.assertIn("COLLECT(", text)

    def test_adomd_dll_follows_app_dir(self) -> None:
        # Saat frozen modul berada di _internal\; DLL harus dicari di folder exe.
        import inspect

        from core import xmla_client

        source = inspect.getsource(xmla_client)
        self.assertIn("ROOT = APP_DIR", source)
        self.assertNotIn("parents[1]", source)
        self.assertEqual(xmla_client.DEFAULT_DLL.parent.name, "libs")

    def test_spec_collects_dynamic_cli_modules(self) -> None:
        # CLI diimpor lewat __import__ sehingga PyInstaller butuh hiddenimports.
        text = (PACKAGING / "bi_tools.spec").read_text(encoding="utf-8")
        for module_name, _description in cli_main.COMMANDS.values():
            if module_name:
                self.assertIn(f'"{module_name}"', text)

    def test_installer_script_is_per_user_and_keeps_data(self) -> None:
        text = (PACKAGING / "bi-tools.iss").read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn(r"DefaultDirName={autopf}", text)
        self.assertIn("install-browser", text)
        # Bagian aktif, bukan penyebutan di komentar.
        self.assertNotRegex(text, r"(?m)^\[UninstallDelete\]")
        self.assertIn('Excludes: "outputs\\*,data\\*,TSD_assets\\*"', text)
        self.assertIn("BuildDir \"..\\dist\\BI Tools\"", text)

    def test_build_script_uses_spec_and_installer(self) -> None:
        text = (PACKAGING / "build.ps1").read_text(encoding="utf-8")
        self.assertIn("packaging\\bi_tools.spec", text)
        self.assertIn("bi-tools.iss", text)
        self.assertIn("/DMyAppVersion=", text)

    def test_icon_is_valid_ico(self) -> None:
        data = (PACKAGING / "bi-tools.ico").read_bytes()
        self.assertGreater(len(data), 1024)
        reserved, kind, count = (
            int.from_bytes(data[0:2], "little"),
            int.from_bytes(data[2:4], "little"),
            int.from_bytes(data[4:6], "little"),
        )
        self.assertEqual((reserved, kind), (0, 1))
        self.assertGreaterEqual(count, 4)

    def test_release_workflow_publishes_artifacts_on_tag(self) -> None:
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('tags: ["v*"]', text)
        self.assertIn("contents: write", text)
        self.assertIn("actions/upload-artifact", text)
        self.assertIn("gh release create", text)
        self.assertIn("SHA256SUMS.txt", text)

    def test_workflows_use_node24_actions(self) -> None:
        # Action lama (Node 20) memunculkan anotasi deprecation di setiap run.
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        for text in (ci, release):
            self.assertIn("actions/checkout@v7", text)
            self.assertIn("actions/setup-python@v7", text)
            self.assertNotIn("actions/checkout@v4", text)
            self.assertNotIn("actions/setup-python@v5", text)
        self.assertIn("actions/upload-artifact@v6", release)
        self.assertNotIn("actions/upload-artifact@v4", release)

    def test_release_notes_are_built_from_changelog(self) -> None:
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("Susun catatan rilis", text)
        self.assertIn("dist\\RELEASE_NOTES.md", text)
        self.assertIn("CHANGELOG.md", text)
        self.assertIn("--notes $notes", text)
        self.assertIn("--generate-notes", text)

    def test_ci_workflow_runs_tests_and_lint(self) -> None:
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("unittest discover", text)
        self.assertIn("flake8", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
