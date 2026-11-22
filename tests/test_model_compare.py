"""Uji engine compare berbasis definisi TOM/TMDL (tanpa XMLA/network)."""

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


def obj(object_type: str, key: str, name: str, definition: str, parent: str = "") -> dict:
    return {
        "type": object_type,
        "key": key,
        "name": name,
        "parent": parent,
        "definition": definition,
    }


def snapshot(objects: list[dict]) -> dict:
    return {"catalog": "Model", "model": {"name": "Model"}, "objects": objects}


class CompareSnapshotTests(unittest.TestCase):
    def test_statuses_and_actions(self) -> None:
        source = snapshot(
            [
                obj("Table", "Sales", "Sales", "table 'Sales'\n\tcolumn Amount\n\t\tdataType: double"),
                obj("Measure", "Sales|Total", "Total", "measure Total = SUM(Sales[Amount])", "Sales"),
                obj("Table", "OnlySource", "OnlySource", "table 'OnlySource'"),
            ]
        )
        target = snapshot(
            [
                obj("Table", "Sales", "Sales", "table 'Sales'\n\tcolumn Amount\n\t\tdataType: double"),
                obj("Measure", "Sales|Amount", "Amount", "measure Amount = SUM(Sales[Amount])", "Sales"),
                obj("Table", "OnlyTarget", "OnlyTarget", "table 'OnlyTarget'"),
            ]
        )
        result = compare_snapshots(source, target)
        by_name = {item["name"]: item for item in result["items"]}

        self.assertEqual(by_name["Sales"]["status"], STATUS_SAME)
        self.assertEqual(by_name["Sales"]["action"], ACTION_SKIP)
        self.assertEqual(by_name["Total"]["status"], STATUS_SOURCE_ONLY)
        self.assertEqual(by_name["Total"]["action"], ACTION_CREATE)
        self.assertEqual(by_name["Amount"]["status"], STATUS_TARGET_ONLY)
        self.assertEqual(by_name["Amount"]["action"], ACTION_DELETE)
        self.assertEqual(by_name["OnlySource"]["status"], STATUS_SOURCE_ONLY)
        self.assertEqual(by_name["OnlyTarget"]["status"], STATUS_TARGET_ONLY)
        self.assertEqual(result["stats"]["same"], 1)
        self.assertEqual(result["stats"]["source_only"], 2)
        self.assertEqual(result["stats"]["target_only"], 2)

    def test_different_definition_is_exact_text(self) -> None:
        source = snapshot([obj("Measure", "Sales|Total", "Total", "measure Total = SUM(Sales[Amount])", "Sales")])
        target = snapshot([obj("Measure", "Sales|Total", "Total", "measure Total = SUM(Sales[Value])", "Sales")])
        measure = compare_snapshots(source, target)["items"][0]

        self.assertEqual(measure["status"], STATUS_DIFFERENT)
        self.assertEqual(measure["action"], ACTION_UPDATE)
        self.assertIn("Sales[Amount]", measure["source_definition"])
        self.assertIn("Sales[Value]", measure["target_definition"])
        rows = measure["diff"]["rows"]
        replace_rows = [row for row in rows if row["kind"] == "replace"]
        self.assertTrue(replace_rows)
        self.assertTrue(any(
            segment["changed"]
            for row in replace_rows
            for segment in row["target"]["segments"]
        ))

    def test_role_member_definition_is_compared_when_present(self) -> None:
        source = snapshot([obj("Role", "HO", "HO", "role HO\n\tmodelPermission: read\n\tmember a")])
        target = snapshot([obj("Role", "HO", "HO", "role HO\n\tmodelPermission: read\n\tmember b")])
        role = compare_snapshots(source, target)["items"][0]

        self.assertEqual(role["status"], STATUS_DIFFERENT)
        self.assertIn("member a", role["source_definition"])
        self.assertIn("member b", role["target_definition"])

    def test_options_defaults_follow_alm(self) -> None:
        options = normalize_options(None)
        self.assertTrue(options["measures"])
        self.assertTrue(options["relationships"])
        self.assertTrue(options["expressions"])
        self.assertFalse(options["roles"])
        self.assertFalse(options["partitions"])
        self.assertFalse(options["annotations"])
        self.assertFalse(options["lineage_tag"])
        self.assertFalse(options["tmsl"])
        self.assertTrue(options["measure_dependencies"])

    def test_options_can_enable_roles(self) -> None:
        options = normalize_options({"roles": True, "partitions": True})
        self.assertTrue(options["roles"])
        self.assertTrue(options["partitions"])

    def test_snapshot_warnings_are_merged(self) -> None:
        source = snapshot([obj("Table", "Sales", "Sales", "table 'Sales'")])
        source["warnings"] = [{"measure": "Total", "message": "missing"}]
        target = snapshot([])
        result = compare_snapshots(source, target)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(result["warnings"][0]["measure"], "Total")

    def test_aligned_rows_include_spacers_and_stats(self) -> None:
        source = snapshot([obj("Measure", "M|X", "X", "a\nb\nc", "M")])
        target = snapshot([obj("Measure", "M|X", "X", "a\nc\nd", "M")])
        diff = compare_snapshots(source, target)["items"][0]["diff"]

        self.assertEqual(
            [row["kind"] for row in diff["rows"]],
            ["equal", "delete", "equal", "insert"],
        )
        self.assertIsNone(diff["rows"][1]["target"])
        self.assertIsNone(diff["rows"][3]["source"])
        self.assertEqual(diff["stats"]["removed"], 1)
        self.assertEqual(diff["stats"]["added"], 1)
        self.assertEqual(diff["stats"]["blocks"], 2)

    def test_line_diff_marks_changed_lines(self) -> None:
        source = snapshot([obj("Measure", "Sales|Total", "Total", "measure Total =\n\tSUM(Sales[Amount])", "Sales")])
        target = snapshot([obj("Measure", "Sales|Total", "Total", "measure Total =\n\tSUM(Sales[Amount]) + 1", "Sales")])
        measure = compare_snapshots(source, target)["items"][0]

        self.assertTrue(measure["diff"]["rows"])
        self.assertGreaterEqual(measure["diff"]["stats"]["changed"], 1)
        self.assertTrue(any(
            row["kind"] in {"replace", "insert"}
            for row in measure["diff"]["rows"]
        ))


if __name__ == "__main__":
    unittest.main()
