"""Uji ekspor hasil compare: CSV UTF-8 BOM dan manifest script."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.compare_export import (
    default_compare_stem,
    script_manifest,
    write_compare_csv,
    write_compare_script,
)


def result() -> dict:
    return {
        "generated_at": "2026-11-22 12:00:00",
        "source": {"label": "Workspace / Source"},
        "target": {"label": "Workspace / Target"},
        "options": {"tmsl": False},
        "items": [
            {
                "id": "measure:sales|total",
                "type": "Measure",
                "name": "Total",
                "source_name": "Total",
                "target_name": "Total",
                "parent": "Sales",
                "status": "different",
                "action": "Update",
                "source_definition": "measure Total = SUM(Sales[Amount])",
                "target_definition": "measure Total = SUM(Sales[Value])",
            },
            {
                "id": "table:sales",
                "type": "Table",
                "name": "Sales",
                "source_name": "Sales",
                "target_name": "",
                "parent": "",
                "status": "source_only",
                "action": "Create",
                "source_definition": "table 'Sales'",
                "target_definition": "",
            },
            {
                "id": "measure:sales|old",
                "type": "Measure",
                "name": "Old",
                "source_name": "",
                "target_name": "Old",
                "parent": "Sales",
                "status": "target_only",
                "action": "Delete",
                "source_definition": "",
                "target_definition": "measure Old = 1",
            },
        ],
    }


class CompareExportTests(unittest.TestCase):
    def test_csv_has_bom_and_all_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_compare_csv(result(), Path(tmp) / "compare.csv")
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            text = raw.decode("utf-8-sig")
            self.assertIn("Type,Name,Parent,Status,Action", text)
            self.assertIn("Measure,Total,Sales,different,Update", text)
            self.assertIn("Table,Sales,,source_only,Create", text)
            self.assertIn("Measure,Old,Sales,target_only,Delete", text)

    def test_script_only_create_update_and_manual_table(self) -> None:
        manifest = script_manifest(result())
        self.assertEqual(len(manifest["actions"]), 1)
        self.assertEqual(manifest["actions"][0]["type"], "Measure")
        self.assertIn("measure Total", manifest["actions"][0]["definition"])
        self.assertEqual(manifest["actions"][0]["format"], "tmdl")
        self.assertEqual(len(manifest["manual"]), 1)
        self.assertEqual(manifest["manual"][0]["type"], "Table")

    def test_script_file_is_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_compare_script(result(), Path(tmp) / "script.json")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(payload["note"])
            self.assertEqual(len(payload["actions"]), 1)
            self.assertTrue(path.read_bytes().startswith(b"{"))

    def test_default_stem_is_safe(self) -> None:
        stem = default_compare_stem("Workspace / A", "Workspace: B")
        self.assertTrue(stem.startswith("Compare_"))
        self.assertNotIn("/", stem)
        self.assertNotIn(":", stem)


if __name__ == "__main__":
    unittest.main()
