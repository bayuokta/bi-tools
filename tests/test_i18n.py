"""Uji lapisan bahasa web: kamus, markup dasar, dan preferensi ui/language."""

from __future__ import annotations

import html
import json
import re
import tempfile
import unittest
from pathlib import Path

from core.errors import ExtractionError
from server import settings as keys
from server.presenters import settings as presenter
from server.settings_store import SettingsStore

ROOT = Path(__file__).resolve().parent.parent

INDONESIAN_LEFTOVERS = (
    "Ekstraksi metadata",
    "Pengaturan",
    "Belum dibuat",
    "Muat ulang",
    "Pilih workspace",
    "Jalankan ekstraksi",
    "Tidak dipakai",
    "Katalog lokal",
    "Ambil screenshot",
)

# Frasa UI Indonesia yang tidak boleh ditulis langsung di app.js. Nilai kanonik
# seperti "Tidak dipakai" dikecualikan karena sengaja dipakai sebagai data.
SCRIPT_INDONESIAN_LEFTOVERS = (
    "Tidak ada halaman",
    "Tidak ada relasi",
    "Ubah kata kunci",
    "Relasi tidak ditemukan",
    "Grafik relasi",
    "Klik tabel atau garis",
    "Server dihentikan",
    "Jalankan BI Tools lagi",
    "Pilih workspace",
    "Muat ulang",
    "Ambil screenshot",
    "Belum dibuat",
)


def read_dictionary() -> dict[str, str]:
    text = (ROOT / "web" / "locales.js").read_text(encoding="utf-8")
    start = text.index("var id = ") + len("var id = ")
    end = text.index(";\n\n  // Pesan dari server", start)
    return json.loads(text[start:end])


def script_text() -> str:
    """Semua JS sumber UI (app.js + modul), tanpa kamus locales.js."""
    files = [ROOT / "web" / "app.js"]
    files.extend(sorted((ROOT / "web" / "js").rglob("*.js")))
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


class DictionaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dictionary = read_dictionary()

    def test_dictionary_is_large_and_complete(self) -> None:
        self.assertGreaterEqual(len(self.dictionary), 450)
        for english, indonesian in self.dictionary.items():
            self.assertTrue(english.strip(), "kunci kosong")
            self.assertTrue(indonesian.strip(), f"nilai kosong untuk {english!r}")

    def test_key_terms_are_translated(self) -> None:
        expected = {
            "Metadata extraction": "Ekstraksi metadata",
            "Settings": "Pengaturan",
            "Language": "Bahasa",
            "Unused": "Tidak dipakai",
            "Depth": "Kedalaman",
            "Columns": "Kolom",
            "Reload": "Muat ulang",
            "Export XLSX": "Ekspor XLSX",
        }
        for english, indonesian in expected.items():
            self.assertEqual(
                str(self.dictionary.get(english, "")).lower(),
                indonesian.lower(),
                english,
            )

    def test_every_markup_key_exists_in_dictionary(self) -> None:
        markup = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        keys = set(re.findall(r'data-i18n="([^"]+)"', markup))
        keys |= set(
            re.findall(
                r'data-i18n-(?:placeholder|title|aria-label|tooltip)="([^"]+)"',
                markup,
            )
        )
        missing = sorted(
            html.unescape(key) for key in keys if html.unescape(key) not in self.dictionary
        )
        self.assertEqual(missing, [], "kunci data-i18n tanpa terjemahan")

    def test_every_script_literal_exists_in_dictionary(self) -> None:
        script = script_text()
        keys = set(re.findall(r'\bt\(\s*"((?:[^"\\]|\\.)*)"\s*\)', script))
        keys |= set(re.findall(r"\bt\(\s*`((?:[^`\\]|\\.)*)`\s*\)", script))
        missing = sorted(key for key in keys if key not in self.dictionary)
        self.assertEqual(missing, [], "kunci t() tanpa terjemahan")

    def test_no_indonesian_ui_phrases_in_script(self) -> None:
        script = script_text()
        for phrase in SCRIPT_INDONESIAN_LEFTOVERS:
            self.assertNotIn(
                phrase,
                script,
                f"teks UI Indonesia di app.js: {phrase!r}; pakai t()",
            )

    def test_health_rule_help_exists_in_dictionary(self) -> None:
        script = script_text()
        start = script.index("var HEALTH_RULE_HELP = [")
        end = script.index("\n  ];", start)
        block = script[start:end]
        keys = set(
            re.findall(
                r'^\s+(?:description|source|action|threshold): '
                r'"((?:[^"\\]|\\.)*)",?$',
                block,
                re.M,
            )
        )
        missing = sorted(key for key in keys if key not in self.dictionary)
        self.assertEqual(missing, [], "teks bantuan aturan tanpa terjemahan")


class MarkupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.markup = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.script = script_text()

    def test_english_is_the_base_language(self) -> None:
        self.assertIn('<html lang="en"', self.markup)
        self.assertNotIn('<html lang="id"', self.markup)
        self.assertIn('data-language="en"', self.markup)
        self.assertIn('data-language="id"', self.markup)
        self.assertGreaterEqual(self.markup.count("data-i18n="), 200)

    def test_no_indonesian_labels_left_in_markup(self) -> None:
        visible = re.sub(r"<[^>]+>", " ", self.markup)
        for text in INDONESIAN_LEFTOVERS:
            self.assertNotIn(text, visible, f"sisa teks Indonesia: {text}")

    def test_locales_load_before_app(self) -> None:
        self.assertIn('<script src="locales.js"></script>', self.markup)
        self.assertLess(
            self.markup.index('src="locales.js"'),
            self.markup.index('src="app.js"'),
        )
        script = (ROOT / "web" / "locales.js").read_text(encoding="utf-8")
        self.assertIn("window.BIToolsI18n", script)
        self.assertIn("translateServer", script)

    def test_language_switch_helpers_exist(self) -> None:
        for name in ("t", "tr", "applyLanguage", "rerenderLanguage", "applyComboLanguage"):
            self.assertEqual(
                self.script.count(f"function {name}("),
                1,
                f"helper {name} harus dideklarasikan satu kali",
            )
        self.assertIn('store.set("pbi-lang", next)', self.script)
        self.assertIn('window.BIToolsApi.put("/api/settings/ui", { language: next })', self.script)


class LanguagePreferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = SettingsStore(
            Path(self._tmp.name) / "settings.json", registry_reader=lambda: {}
        )

    def test_default_is_english(self) -> None:
        state = presenter.build_state(self.store)
        self.assertEqual(state["ui"]["language"], "en")

    def test_save_and_reload_indonesian(self) -> None:
        state = presenter.save_ui(self.store, language="id")
        self.assertEqual(state["ui"]["language"], "id")
        self.assertEqual(
            self.store.get_str(keys.SETTINGS_UI_LANGUAGE_KEY),
            "id",
        )
        self.assertEqual(presenter.build_state(self.store)["ui"]["language"], "id")

    def test_unknown_language_is_rejected(self) -> None:
        with self.assertRaises(ExtractionError):
            presenter.save_ui(self.store, language="fr")
        self.assertEqual(
            presenter.build_state(self.store)["ui"]["language"],
            "en",
        )


if __name__ == "__main__":
    unittest.main()
