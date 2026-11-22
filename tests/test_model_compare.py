"""Uji engine compare semantic model (tanpa XMLA/network)."""

from __future__ import annotations

import unittest

from core.model_compare import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_SKIP,
    ACTION_UPDATE,
    STATUS_DIFFERENT,
    STATUS_SAME,
    STATUS_SOURCE_ONLY,
    STATUS_TARGET_ONLY,
    compare_snapshots,
    normalize_options,
)


def snapshot() -> dict:
    return {
        "tables": [{"table": "Sales", "is_hidden": False, "storage_mode": "Import"}],
        "columns": [
            {
                "table": "Sales",
                "column": "Amount",
                "data_type": "Double",
                "format_string": "0.00",
                "summarize_by": "Sum",
                "is_hidden": False,
                "display_folder": "",
                "expression": "",
            },
            {
                "table": "Sales",
                "column": "Year",
                "data_type": "Int64",
                "format_string": "0",
                "summarize_by": "None",
                "is_hidden": False,
                "display_folder": "",
                "expression": "",
            },
        ],
        "measures": [
            {
                "table": "Sales",
                "measure": "Total",
                "expression": "SUM(Sales[Amount])",
                "format_string": "#,0",
                "is_hidden": False,
                "display_folder": "",
                "description": "",
            }
        ],
        "relationships": [
            {
                "from_table": "Sales",
                "from_column": "Year",
                "to_table": "Calendar",
                "to_column": "Year",
                "cross_filtering": "oneDirection",
                "security_filtering": "none",
                "is_active": True,
                "from_cardinality": "many",
                "to_cardinality": "one",
                "join_on_date_behavior": "",
            }
        ],
        "expressions": [
            {"name": "Path", "kind": "Expression", "data_type": "", "expression": '"C:/data"'}
        ],
        "partitions": [
            {
                "table": "Sales",
                "partition": "Sales",
                "mode": "Import",
                "source_type": "m",
                "source": "let Source = ... in Source",
            }
        ],
        "roles": [
            {
                "id": 1,
                "name": "Region",
                "model_permission": "read",
                "members": [{"name": "a@example.com"}],
                "permissions": [{"table": "Sales", "expression": "Sales[Region] = \"A\"", "has_ols": False}],
            }
        ],
    }


class CompareSnapshotTests(unittest.TestCase):
    def test_statuses_and_actions(self) -> None:
        source = snapshot()
        target = snapshot()
        target["columns"].append(
            {
                "table": "Sales",
                "column": "OnlyTarget",
                "data_type": "String",
                "format_string": "",
                "summarize_by": "None",
                "is_hidden": False,
                "display_folder": "",
                "expression": "",
            }
        )
        target["measures"] = []
        source["tables"].append({"table": "OnlySource", "is_hidden": False})

        result = compare_snapshots(source, target)
        by_name = {item["name"]: item for item in result["items"]}

        self.assertEqual(by_name["Total"]["status"], STATUS_SOURCE_ONLY)
        self.assertEqual(by_name["Total"]["action"], ACTION_CREATE)
        self.assertEqual(by_name["OnlyTarget"]["status"], STATUS_TARGET_ONLY)
        self.assertEqual(by_name["OnlyTarget"]["action"], ACTION_DELETE)
        self.assertEqual(by_name["OnlySource"]["status"], STATUS_SOURCE_ONLY)
        self.assertEqual(by_name["Amount"]["status"], STATUS_SAME)
        self.assertEqual(by_name["Amount"]["action"], ACTION_SKIP)
        self.assertEqual(result["stats"]["same"], 7)
        self.assertEqual(result["stats"]["source_only"], 2)
        self.assertEqual(result["stats"]["target_only"], 1)

    def test_different_definition_and_format_option(self) -> None:
        source = snapshot()
        target = snapshot()
        target["measures"][0]["expression"] = "SUM(Sales[Amount]) + 1"
        target["measures"][0]["format_string"] = "0"

        without_format = compare_snapshots(source, target, {"format_string": False})
        measure = next(item for item in without_format["items"] if item["name"] == "Total")
        self.assertEqual(measure["status"], STATUS_DIFFERENT)
        self.assertEqual(measure["action"], ACTION_UPDATE)
        self.assertIn("Expression", {p["name"] for p in measure["properties"] if p["source"] != p["target"]})
        self.assertNotIn("Format string", {p["name"] for p in measure["properties"]})

        with_format = compare_snapshots(source, target, {"format_string": True})
        measure = next(item for item in with_format["items"] if item["name"] == "Total")
        self.assertIn("Format string", {p["name"] for p in measure["properties"] if p["source"] != p["target"]})

    def test_options_skip_types(self) -> None:
        source = snapshot()
        target = snapshot()
        target["relationships"][0]["cross_filtering"] = "bothDirections"
        result = compare_snapshots(
            source,
            target,
            {"measures": False, "relationships": False, "expressions": False, "roles": False},
        )
        types = {item["type"] for item in result["items"]}
        self.assertEqual(types, {"Table"})
        self.assertEqual(result["stats"]["different"], 0)

    def test_roles_members_and_rls(self) -> None:
        source = snapshot()
        target = snapshot()
        target["roles"][0]["members"] = [{"name": "b@example.com"}]
        target["roles"][0]["permissions"][0]["expression"] = "Sales[Region] = \"B\""
        result = compare_snapshots(source, target)
        role = next(item for item in result["items"] if item["type"] == "Role")
        self.assertEqual(role["status"], STATUS_DIFFERENT)
        changed = {p["name"] for p in role["properties"] if p["source"] != p["target"]}
        self.assertIn("Members", changed)
        self.assertIn("RLS Sales", changed)

    def test_line_diff_marks_changed_lines(self) -> None:
        source = snapshot()
        target = snapshot()
        target["measures"][0]["expression"] = "SUM(Sales[Amount])\n+ 1"
        result = compare_snapshots(source, target)
        measure = next(item for item in result["items"] if item["name"] == "Total")
        self.assertTrue(any(line["changed"] for line in measure["diff"]["target"]))
        self.assertTrue(measure["diff"]["source"])

    def test_options_defaults(self) -> None:
        options = normalize_options(None)
        self.assertTrue(options["measures"])
        self.assertTrue(options["roles"])
        self.assertFalse(options["format_string"])


if __name__ == "__main__":
    unittest.main()
