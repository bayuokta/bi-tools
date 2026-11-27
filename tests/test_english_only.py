"""Penjaga antarmuka English-only (tanpa opsi Bahasa Indonesia)."""

from __future__ import annotations

import ast
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


# Kata Indonesia yang khas; sengaja tanpa kata yang juga Bahasa Inggris
# (folder, manual, data, mode, status, default, display, model, visual, page).
INDONESIAN_WORDS = re.compile(
    r"\b("
    "tidak|belum|dipakai|digunakan|kolom|tabel|relasi|halaman|dari|untuk|"
    "dengan|pada|adalah|atau|yang|bisa|harus|gagal|jumlah|ukuran|tanpa|"
    "sudah|juga|hanya|lebih|dalam|dilewati|dipindai|unduh|pilih|jalankan|"
    "memakai|milik|sebagai|antara|setiap|semua|buka|buat|simpan|hapus|"
    "nama|katalog|siap|pratinjau|termuat|antarmuka|berjalan|ditemukan|"
    "dibaca|ditulis|kredensial|sinkronisasi|berkas|wajib|kontrol|saja|"
    "perlu|coba|menunggu|memuat|membaca|mengunduh|mengirim|menulis|"
    "memproses|menyiapkan|mengambil|selesai|memeriksa|mencari|menghapus|"
    "membuat|menyimpan|menjalankan|hasil|diperbarui|diproses|dikirim|"
    "diterima|berhasil|sebelumnya|kembali|ulang|masih|sedang|akan|dapat|"
    "kedalaman|langkah|ditampilkan|disembunyikan|ditutup|dibuka|dipilih|"
    "terbuka|tertutup|pengguna|aplikasi|versi|waktu|tanggal|nilai|proses|"
    "bagian|daftar|jenis|sumber|tujuan|aturan|pesan|kesalahan|peringatan|"
    "bantuan|pilihan|bawaan|otomatis|lanjut|berhenti|mulai|akhir|awal|baru|"
    "lama|besar|kecil|tinggi|rendah|panjang|pendek|cepat|lambat|mudah|"
    "sulit|benar|salah|kosong|penuh|mungkin|pasti|masing|beberapa|banyak|"
    "sedikit|seluruh|lagi|pula"
    r")\b",
    re.IGNORECASE,
)
ALLOWED_TEXT = (
    # Kunci data kanonik lama untuk langkah Power Query; label UI-nya "M step".
    re.compile(r"^langkah [Mm]$"),
    # Catatan yang masuk ke dokumen TSD (dokumen tetap berbahasa Indonesia).
    re.compile(r"^Report belum memiliki mobile layout"),
    # Halaman embed internal untuk Playwright (bukan teks UI aplikasi).
    re.compile(r"^<!DOCTYPE html>"),
)
SCAN_SKIP = {"model.py", "report.py"}
HTML_ATTR = re.compile(r'(?:title|placeholder|aria-label|alt)="([^"]+)"')


def indonesian_strings():
    hits = []
    roots = [ROOT / "core", ROOT / "server", ROOT / "cli", ROOT / "sync"]
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if path.name in SCAN_SKIP or "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docs = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if (
                    isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and body
                    and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    docs.add(id(body[0].value))
            skip_nodes = set()
            for node in ast.walk(tree):
                test = getattr(node, "test", None)
                if (
                    isinstance(node, ast.If)
                    and isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name)
                    and test.left.id == "__name__"
                    and any(
                        isinstance(item, ast.Constant) and item.value == "__main__"
                        for item in test.comparators
                    )
                ):
                    for child in node.body:
                        for inner in ast.walk(child):
                            skip_nodes.add(id(inner))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docs
                    and id(node) not in skip_nodes
                    and INDONESIAN_WORDS.search(node.value)
                    and not any(p.match(node.value.strip()) for p in ALLOWED_TEXT)
                ):
                    hits.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value[:120]}")
    return hits


class EnglishOnlySourceTests(unittest.TestCase):
    def test_no_indonesian_ui_log_or_cli_strings(self) -> None:
        self.assertEqual([], indonesian_strings())

    def test_no_indonesian_web_text(self) -> None:
        hits = []
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        text = re.sub(r"<script.*?</script>", "", html, flags=re.S)
        text = re.sub(r"<style.*?</style>", "", text, flags=re.S)
        for match in re.finditer(r">([^<>]+)<", text):
            value = " ".join(match.group(1).split())
            if INDONESIAN_WORDS.search(value):
                hits.append(value[:120])
        for match in HTML_ATTR.finditer(html):
            if INDONESIAN_WORDS.search(match.group(1)):
                hits.append(match.group(1)[:120])
        self.assertEqual([], hits)


def _js_literals(source: str):
    """Ambil literal string per baris; komentar // di luar kutip dibuang."""
    literals = []
    pattern = re.compile(
        r'"((?:[^"\\]|\\.)*)"'
        r"|'((?:[^'\\]|\\.)*)'"
        r"|`((?:[^`\\]|\\.)*)`"
    )
    for line in source.splitlines():
        quote, index, cut = None, 0, len(line)
        while index < len(line) - 1:
            char = line[index]
            if quote is not None:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
            else:
                if char in "\"'`":
                    quote = char
                elif line.startswith("//", index):
                    cut = index
                    break
            index += 1
        code = line[:cut].strip()
        if not code or code.startswith(("*", "/*")):
            continue
        for match in pattern.finditer(code):
            literals.append(match.group(1) or match.group(2) or match.group(3) or "")
    return literals


class EnglishOnlyWebTests(unittest.TestCase):
    def test_no_indonesian_js_literals(self) -> None:
        hits = []
        for path in sorted((ROOT / "web").rglob("*.js")):
            if "vendor" in path.parts or path.name == "highlight.js":
                continue
            for value in _js_literals(path.read_text(encoding="utf-8")):
                if INDONESIAN_WORDS.search(value):
                    hits.append(f"{path.relative_to(ROOT)}: {value[:120]}")
        self.assertEqual([], hits)


if __name__ == "__main__":
    unittest.main()
