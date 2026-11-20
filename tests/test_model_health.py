"""Uji pemeriksaan kesehatan model/report (tanpa XMLA, REST, atau SQLite)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.model_health import (
    DICTIONARY_MIN_BYTES,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    broken_visual_counts,
    build_health,
)
from core.usage_service import STATUS_UNUSED

REPORT_ID = "b" * 32


def column(
    name: str,
    table: str = "T",
    status: str = "Dipakai",
    *,
    size: int = 0,
    dictionary: int = 0,
    error: str = "",
    calculated: bool = False,
):
    stat = SimpleNamespace(
        column=name,
        table=table,
        size_total_bytes=size,
        size_dictionary_bytes=dictionary,
        is_calculated=calculated,
        has_error=bool(error),
        error_message=error,
    )
    return SimpleNamespace(column=stat, status=status)


def measure(
    name: str,
    table: str = "T",
    status: str = "Dipakai",
    *,
    error: str = "",
):
    stat = SimpleNamespace(
        measure=name,
        table=table,
        has_error=bool(error),
        error_message=error,
    )
    return SimpleNamespace(measure=stat, status=status)


def table(
    name: str,
    *,
    size: int = 0,
    mode: str = "Import",
    rows: int = 0,
):
    return SimpleNamespace(
        table=name,
        size_total_bytes=size,
        storage_mode=mode,
        rows=rows,
        column_count=0,
        measure_count=0,
        partition_count=0,
    )


def report(
    status: str = "ok",
    *,
    theme: str = "Base",
    report_id: str = REPORT_ID,
    name: str = "Report Uji",
):
    return {
        "report_id": report_id,
        "report_name": name,
        "status": status,
        "theme": theme,
        "page_count": 1,
        "visual_count": 2,
        "field_count": 4,
        "unresolved_count": 0,
    }


def result(
    *,
    columns=(),
    measures=(),
    tables=(),
    relationships=(),
    reports=(),
    pages=None,
    unresolved=(),
    reports_included: bool = True,
):
    return SimpleNamespace(
        stats=SimpleNamespace(tables=list(tables)),
        columns=list(columns),
        measures=list(measures),
        relationships=list(relationships),
        reports=list(reports),
        report_pages=dict(pages or {}),
        unresolved=list(unresolved),
        reports_included=reports_included,
        dataset_bytes=0,
        unused=[],
        unused_measures=[],
    )


def rules_of(items) -> list[str]:
    return [item["rule"] for item in items]


class ModelHealthTests(unittest.TestCase):
    def test_unused_status_constant_matches_analysis(self) -> None:
        self.assertEqual(STATUS_UNUSED, "Tidak dipakai")

    def test_errors_are_critical(self) -> None:
        data = result(
            columns=[column("Broken", size=100, error="DAX error")],
            measures=[measure("Bad measure", error="boom")],
        )
        health = build_health(data)
        self.assertEqual(health["counts"][SEVERITY_CRITICAL], 2)
        items = {item["rule"]: item for item in health["items"]}
        self.assertEqual(items["column_error"]["size_bytes"], 100)
        self.assertIn("DAX error", items["column_error"]["detail"])
        self.assertEqual(items["measure_error"]["target"]["kind"], "measure")

    def test_unused_and_isolated_table(self) -> None:
        data = result(
            columns=[
                column("A", "Old", STATUS_UNUSED, size=500),
                column("B", "Old", STATUS_UNUSED, size=500),
                column("C", "Used", status="Dipakai", size=500),
            ],
            tables=[
                table("Old", size=1000),
                table("Used", size=500),
            ],
            relationships=[
                {
                    "name": "Rel",
                    "from_table": "Used",
                    "from_column": "C",
                    "to_table": "Dim",
                    "to_column": "Key",
                    "cross_filtering": "oneDirection",
                    "is_active": True,
                    "is_auto": False,
                    "from_cardinality": "many",
                    "to_cardinality": "one",
                }
            ],
        )
        health = build_health(data)
        items = health["items"]
        self.assertIn("unused_table", rules_of(items))
        self.assertIn("isolated_table", rules_of(items))
        unused = next(item for item in items if item["rule"] == "unused_table")
        self.assertEqual(unused["metrics"]["columns"], 2)
        self.assertEqual(unused["size_bytes"], 1000)
        isolated = next(item for item in items if item["rule"] == "isolated_table")
        self.assertEqual(isolated["object"], "Old")

    def test_helper_and_calculation_group_tables_are_excluded(self) -> None:
        data = result(
            columns=[
                column("x", "_Measures", STATUS_UNUSED),
                column("y", "Calc Group", STATUS_UNUSED),
            ],
            tables=[
                table("_Measures"),
                table("Calc Group", mode="calculationGroup"),
            ],
        )
        health = build_health(data)
        self.assertNotIn("unused_table", rules_of(health["items"]))
        self.assertNotIn("isolated_table", rules_of(health["items"]))

    def test_relationship_rules(self) -> None:
        data = result(
            columns=[column("A", "Fact")],
            reports=[report()],
            relationships=[
                {
                    "name": "Both",
                    "from_table": "Fact",
                    "from_column": "A",
                    "to_table": "Dim",
                    "to_column": "Key",
                    "cross_filtering": "bothDirections",
                    "is_active": True,
                    "is_auto": False,
                    "from_cardinality": "many",
                    "to_cardinality": "one",
                },
                {
                    "name": "M2M",
                    "from_table": "Fact",
                    "from_column": "A",
                    "to_table": "Dim",
                    "to_column": "Key",
                    "cross_filtering": "oneDirection",
                    "is_active": False,
                    "is_auto": True,
                    "from_cardinality": "many",
                    "to_cardinality": "many",
                },
            ],
        )
        health = build_health(data)
        rules = rules_of(health["items"])
        for rule in (
            "bidirectional_relationship",
            "many_to_many_relationship",
            "inactive_relationship",
            "auto_relationship",
        ):
            self.assertIn(rule, rules)
        ids = [item["id"] for item in health["items"]]
        self.assertEqual(len(ids), len(set(ids)), "id health harus unik")

    def test_large_dictionary_threshold(self) -> None:
        data = result(
            columns=[
                column(
                    "Big",
                    size=10_000_000,
                    dictionary=DICTIONARY_MIN_BYTES,
                ),
                column("Small", size=10_000_000, dictionary=100_000),
                column("Share", size=2_000_000, dictionary=1_500_000),
            ]
        )
        health = build_health(data)
        found = [
            item["object"]
            for item in health["items"]
            if item["rule"] == "large_dictionary"
        ]
        self.assertEqual(found, ["T[Share]"])

    def test_unused_calculated_column_is_info(self) -> None:
        data = result(
            columns=[
                column("Calc", "T", STATUS_UNUSED, size=64, calculated=True),
                column("Plain", "T", STATUS_UNUSED, size=64),
            ]
        )
        health = build_health(data)
        found = [
            item
            for item in health["items"]
            if item["rule"] == "unused_calculated_column"
        ]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], SEVERITY_INFO)


class ReportHealthTests(unittest.TestCase):
    def test_broken_visual_counts_and_practice_score(self) -> None:
        pages = {
            REPORT_ID: [
                {"page_id": "p1", "page_name": "A", "visual_count": 2},
                {"page_id": "p2", "page_name": "B", "visual_count": 0},
            ]
        }
        unresolved = [
            {
                "report_id": REPORT_ID,
                "page_id": "p1",
                "page_name": "A",
                "visual_id": "v1",
                "visual_title": "Chart",
                "query_ref": "T[Missing]",
                "reason": "tidak bisa dipetakan",
            },
            {
                "report_id": REPORT_ID,
                "page_id": "p1",
                "page_name": "A",
                "visual_id": "v1",
                "visual_title": "Chart",
                "query_ref": "T[Other]",
                "reason": "tidak bisa dipetakan",
            },
        ]
        data = result(
            reports=[report()],
            pages=pages,
            unresolved=unresolved,
        )
        health = build_health(data)
        self.assertEqual(broken_visual_counts(data), {REPORT_ID: 1})
        item = next(
            item for item in health["items"] if item["rule"] == "broken_visual"
        )
        self.assertEqual(item["metrics"]["unresolved"], 2)
        self.assertIn("T[Missing]", item["detail"])
        self.assertIn("page_without_visuals", rules_of(health["items"]))
        practice = health["practice"][REPORT_ID]
        self.assertEqual(practice["score"], 100 - 5 - 3 - 2)
        checks = {check["rule"]: check for check in practice["checks"]}
        self.assertEqual(checks["broken_visual"]["count"], 1)
        self.assertEqual(checks["page_without_visuals"]["count"], 1)
        self.assertEqual(checks["unresolved_field"]["count"], 2)

    def test_hidden_page_with_visuals_is_info(self) -> None:
        pages = {
            REPORT_ID: [
                {
                    "page_id": "p1",
                    "page_name": "Tooltip",
                    "visual_count": 3,
                    "is_hidden": True,
                }
            ]
        }
        health = build_health(result(reports=[report()], pages=pages))
        item = next(
            item
            for item in health["items"]
            if item["rule"] == "hidden_page_with_visuals"
        )
        self.assertEqual(item["severity"], SEVERITY_INFO)
        self.assertEqual(item["metrics"]["visuals"], 3)

    def test_practice_skips_reports_without_definition(self) -> None:
        pages = {REPORT_ID: [{"page_id": "p1", "visual_count": 0}]}
        health = build_health(
            result(reports=[report(status="failed")], pages=pages)
        )
        self.assertNotIn(REPORT_ID, health["practice"])

    def test_model_only_result_has_no_report_items(self) -> None:
        health = build_health(result(reports_included=False))
        self.assertEqual(health["items"], [])
        self.assertFalse(health["reports_included"])

    def test_missing_theme_is_info_without_penalty(self) -> None:
        health = build_health(result(reports=[report(theme="")]))
        rules = rules_of(health["items"])
        self.assertIn("missing_theme", rules)
        self.assertEqual(health["practice"][REPORT_ID]["score"], 100)

    def test_payload_carries_rank_and_counts(self) -> None:
        data = result(
            columns=[column("X", error="bad")],
            reports=[report()],
            pages={REPORT_ID: [{"page_id": "p1", "visual_count": 0}]},
        )
        health = build_health(data)
        self.assertEqual(health["rules_version"], 1)
        self.assertEqual(
            sum(health["counts"].values()), len(health["items"])
        )
        self.assertEqual(health["counts"][SEVERITY_CRITICAL], 1)
        self.assertGreaterEqual(health["counts"][SEVERITY_WARNING], 1)
        for item in health["items"]:
            self.assertIn(item["severity_rank"], (0, 1, 2))
            self.assertTrue(item["id"])


if __name__ == "__main__":
    unittest.main()
