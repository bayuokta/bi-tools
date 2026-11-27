"""Guard: every UI icon comes from the vendored Lucide sprite."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
MANIFEST = WEB / "vendor" / "lucide" / "icons.json"
DOC = WEB / "ICONS.md"
SYMBOL = re.compile(r'<symbol id="(i-[a-z0-9-]+)" viewBox="0 0 24 24">(.*?)</symbol>', re.S)
REFERENCE = re.compile(r"#(i-[a-z0-9-]+)")
HELPER_CALL = re.compile(r'icon\("([a-z0-9-]+)"')
UI_SVG = re.compile(r'<svg class="[^"]*od-icon[^"]*"[^>]*>(.*?)</svg>', re.S)
INVENTORY_ROW = re.compile(r"^\| `([a-z0-9-]+)` \| \d+ \|", re.M)


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def sprite_block(markup: str) -> str:
    start = markup.index("<!-- lucide:sprite:begin -->")
    end = markup.index("<!-- lucide:sprite:end -->") + len("<!-- lucide:sprite:end -->")
    return markup[start:end]


def symbols(markup: str) -> dict:
    return {match.group(1): re.sub(r"\s+", " ", match.group(2)).strip()
            for match in SYMBOL.finditer(sprite_block(markup))}


def web_scripts() -> list:
    return [WEB / "app.js", *sorted((WEB / "js").rglob("*.js"))]


class LucideSpriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = manifest()
        self.markup = (WEB / "index.html").read_text(encoding="utf-8")
        self.symbols = symbols(self.markup)

    def test_manifest_is_pinned(self) -> None:
        self.assertEqual("ISC", self.data["license"])
        self.assertRegex(self.data["version"], r"^\d+\.\d+\.\d+$")
        self.assertTrue((WEB / "vendor" / "lucide" / "LICENSE").is_file())

    def test_sprite_matches_manifest(self) -> None:
        expected = {"i-" + name: markup for name, markup in self.data["icons"].items()}
        self.assertEqual(expected, self.symbols)

    def test_all_references_resolve(self) -> None:
        used = set(REFERENCE.findall(self.markup))
        for path in web_scripts():
            text = path.read_text(encoding="utf-8")
            used.update(REFERENCE.findall(text))
            used.update("i-" + name for name in HELPER_CALL.findall(text))
        self.assertEqual(set(), used - set(self.symbols), "ikon tanpa <symbol>")
        self.assertEqual(set(), set(self.symbols) - used, "ikon yang tidak dipakai")

    def test_ui_icons_have_no_inline_paths(self) -> None:
        for match in UI_SVG.finditer(self.markup):
            body = match.group(1)
            self.assertIn("<use href=\"#i-", body)
            self.assertNotIn("<path", body)
            self.assertNotIn("<rect", body)

    def test_no_external_icon_source(self) -> None:
        for path in web_scripts():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("unpkg.com", text, str(path))
            self.assertNotIn("<script", text, str(path))
        self.assertNotRegex(self.markup, r"<script[^>]+src=\"https?://")

    def test_documentation_lists_every_icon(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        start = text.index("<!-- icon-inventory:begin -->")
        end = text.index("<!-- icon-inventory:end -->")
        documented = set(INVENTORY_ROW.findall(text[start:end]))
        self.assertEqual(set(self.data["icons"]), documented)


if __name__ == "__main__":
    unittest.main()
