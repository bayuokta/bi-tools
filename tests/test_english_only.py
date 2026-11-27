"""Penjaga antarmuka English-only (tanpa opsi Bahasa Indonesia)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EnglishOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.settings = (ROOT / "server" / "settings.py").read_text(
            encoding="utf-8"
        )
        self.presenter = (
            ROOT / "server" / "presenters" / "settings.py"
        ).read_text(encoding="utf-8")

    def test_locale_dictionary_and_switcher_are_gone(self) -> None:
        self.assertFalse((ROOT / "web" / "locales.js").exists())
        self.assertNotIn("locales.js", self.html)
        self.assertNotIn("data-language", self.html)
        self.assertNotIn("data-i18n", self.html)
        self.assertNotIn("BIToolsI18n", self.app)

    def test_language_setting_is_gone(self) -> None:
        self.assertNotIn("ui/language", self.settings)
        self.assertNotIn("LANGUAGES", self.presenter)
        self.assertNotIn('"language"', self.presenter)

    def test_no_translation_helpers_or_switch(self) -> None:
        self.assertFalse((ROOT / "web" / "js" / "core" / "i18n.js").exists())
        scripts = [ROOT / "web" / "app.js"]
        scripts.extend((ROOT / "web" / "js").rglob("*.js"))
        pattern = re.compile(r"(?<![\w$.])(?:t|tr)\(")
        for path in scripts:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(pattern.search(text), path.relative_to(ROOT).as_posix())
            self.assertNotIn("data-language", text)
            self.assertNotIn("applyLanguage", text)

    def test_verdict_statuses_are_english(self) -> None:
        usage = (ROOT / "core" / "usage_service.py").read_text(encoding="utf-8")
        for value in ("Unused", "Used", "Must keep", "Needs review"):
            self.assertIn(f'"{value}"', usage)
        self.assertNotIn('STATUS_UNUSED = "Tidak dipakai"', usage)
        self.assertNotIn('STATUS_BLOCKER = "Wajib dipertahankan"', usage)


if __name__ == "__main__":
    unittest.main()
