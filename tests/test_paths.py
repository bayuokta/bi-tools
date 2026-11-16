"""Uji lokasi aplikasi dan folder outputs/data (skrip maupun executable)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import paths


class AppDirTests(unittest.TestCase):
    def test_script_mode_uses_repo_root(self) -> None:
        with patch.object(sys, "frozen", False, create=True):
            self.assertEqual(
                paths.app_dir(), Path(paths.__file__).resolve().parents[1]
            )

    def test_frozen_mode_uses_executable_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "BI Tools.exe"
            with patch.object(sys, "frozen", True, create=True), patch.object(
                sys, "executable", str(exe)
            ):
                # app_dir() me-resolve path (nama pendek Windows 8.3 bisa berbeda).
                self.assertEqual(paths.app_dir(), exe.parent.resolve())


class OutputsDirTests(unittest.TestCase):
    def setUp(self) -> None:
        paths.outputs_dir.cache_clear()
        paths.data_dir.cache_clear()
        self.addCleanup(paths.outputs_dir.cache_clear)
        self.addCleanup(paths.data_dir.cache_clear)
        self.addCleanup(patch.stopall)

    def test_env_override_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "keluaran"
            with patch.dict(os.environ, {"BI_TOOLS_OUTPUTS": str(target)}):
                self.assertEqual(paths.outputs_dir(), target)
            self.assertFalse(target.exists())

    def test_data_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "basisdata"
            with patch.dict(os.environ, {"BI_TOOLS_DATA": str(target)}):
                self.assertEqual(paths.data_dir(), target)

    def test_falls_back_to_localappdata_when_app_dir_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            app.mkdir()
            local = Path(tmp) / "local"
            local.mkdir()
            patch.object(paths, "APP_DIR", app).start()
            patch.object(
                paths, "_writable", lambda base: base != app
            ).start()
            patch.dict(os.environ, {"LOCALAPPDATA": str(local)}, clear=False).start()

            self.assertEqual(
                paths.outputs_dir(), local / paths.FALLBACK_DIR_NAME / "outputs"
            )
            self.assertEqual(
                paths.data_dir(), local / paths.FALLBACK_DIR_NAME / "data"
            )

    def test_writable_app_dir_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "app"
            app.mkdir()
            patch.object(paths, "APP_DIR", app).start()

            self.assertEqual(paths.outputs_dir(), app / "outputs")
            self.assertFalse((app / "outputs").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
