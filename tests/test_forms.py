"""Uji TsdForm: default, fallback RLS, dan roundtrip QSettings."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - tergantung environment
    QT_AVAILABLE = False

if QT_AVAILABLE:
    from app.forms import TsdForm
    from app.settings_store import AppSettings


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class TsdFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        raw = QSettings(
            str(Path(self._tmp.name) / "settings.ini"),
            QSettings.Format.IniFormat,
        )
        self.settings = AppSettings(raw)

    def test_defaults_when_settings_empty(self) -> None:
        form = TsdForm.load(self.settings)
        self.assertTrue(form.report_workbook.endswith("Report_Metadata.xlsx"))
        self.assertTrue(form.draft)
        self.assertFalse(form.expand_all)
        self.assertFalse(form.screenshots)
        self.assertEqual((form.shot_scope, form.shot_scale), ("both", 1.0))
        self.assertTrue(form.shot_mobile)
        self.assertTrue(form.auto_install_browser)

    def test_empty_rls_falls_back_to_settings_default(self) -> None:
        self.settings.set_rls("default@user", "HO,Region")
        form = TsdForm.load(self.settings)
        self.assertEqual((form.rls_username, form.rls_roles), ("default@user", "HO,Region"))

    def test_roundtrip_does_not_touch_default_rls(self) -> None:
        self.settings.set_rls("default@user", "HO")
        form = TsdForm.load(self.settings)
        form.rls_username = "run@user"
        form.rls_roles = "Region"
        form.shot_scope = "visuals"
        form.shot_scale = 2.0
        form.shot_mobile = False
        form.auto_install_browser = False
        form.draft = False
        form.save(self.settings)

        again = TsdForm.load(self.settings)

        self.assertEqual(
            (again.rls_username, again.rls_roles), ("run@user", "Region")
        )
        self.assertEqual((again.shot_scope, again.shot_scale), ("visuals", 2.0))
        self.assertFalse(again.shot_mobile)
        self.assertFalse(again.auto_install_browser)
        self.assertFalse(again.draft)
        self.assertEqual(self.settings.rls(), ("default@user", ("HO",)))


if __name__ == "__main__":
    unittest.main()
