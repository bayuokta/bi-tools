"""Uji evaluasi rule PBI Inspector per report."""

from __future__ import annotations

import json
import unittest

from core.fabric_api import DefinitionPart, ReportDefinition
from core.report_practice import (
    build_report_practice,
    load_practice_rules,
    report_practice_text,
)


def part(path: str, payload: dict) -> DefinitionPart:
    return DefinitionPart(path, json.dumps(payload).encode("utf-8"))


def definition(*, visuals: list[dict] | None = None, page_height: float = 720) -> ReportDefinition:
    visual_list = visuals if visuals is not None else [
        {
            "name": "v1",
            "visual": {
                "visualType": "tableEx",
                "query": {
                    "queryState": {
                        "Values": {
                            "projections": [
                                {
                                    "field": {
                                        "Column": {
                                            "Expression": {
                                                "SourceRef": {"Entity": "Sales"}
                                            },
                                            "Property": "Region",
                                        }
                                    }
                                }
                            ]
                        }
                    }
                },
            },
        }
    ]
    parts = [
        part(
            "definition/report.json",
            {
                "publicCustomVisuals": [],
                "themeCollection": {"baseTheme": {"name": "CY24SU10"}},
                "filterConfig": {"filters": []},
            },
        ),
        part(
            "definition/pages/pages.json",
            {"pageOrder": ["p1"]},
        ),
        part(
            "definition/pages/p1/page.json",
            {
                "name": "p1",
                "displayName": "Overview",
                "height": page_height,
                "width": 1280,
                "filterConfig": {"filters": []},
            },
        ),
    ]
    for index, visual in enumerate(visual_list):
        parts.append(
            part(
                f"definition/pages/p1/visuals/{visual.get('name', f'v{index}')}/visual.json",
                visual,
            )
        )
    return ReportDefinition(report_format="PBIR", parts=tuple(parts))


class ReportPracticeTests(unittest.TestCase):
    def test_catalog_has_ten_active_rules(self) -> None:
        rules = load_practice_rules()
        self.assertEqual(len(rules), 10)
        ids = {rule.id for rule in rules}
        self.assertNotIn("ENSURE_ALTTEXT", ids)
        self.assertNotIn("template", ids)

    def test_all_rules_pass(self) -> None:
        practice = build_report_practice(definition())
        self.assertTrue(practice["available"])
        self.assertEqual(practice["score"], 100)
        self.assertEqual(practice["label"], "Ok")
        self.assertEqual(practice["passed"], 10)
        self.assertEqual(practice["failed"], 0)
        self.assertEqual(len(practice["rules"]), 10)
        self.assertTrue(all(rule["evaluated"] for rule in practice["rules"]))
        self.assertEqual(report_practice_text(practice), "100 (Ok)")

    def test_warning_failure_lowers_score(self) -> None:
        practice = build_report_practice(definition(page_height=1000))
        self.assertEqual(practice["score"], 90)
        self.assertEqual(practice["label"], "Warning")
        failed = [rule for rule in practice["rules"] if not rule["passed"]]
        self.assertEqual(
            [rule["id"] for rule in failed],
            ["ENSURE_PAGES_DO_NOT_SCROLL_VERTICALLY"],
        )
        self.assertIn("Overview", failed[0]["objects"][0])

    def test_theme_failure_is_critical(self) -> None:
        visual = {
            "name": "v1",
            "visual": {
                "visualType": "pivotTable",
                "query": {"queryState": {}},
                "objects": {
                    "values": [
                        {
                            "properties": {
                                "fontColor": {
                                    "solid": {"color": {"Literal": {"Value": "#FFFFFF"}}}
                                }
                            }
                        }
                    ]
                },
            },
        }
        practice = build_report_practice(definition(visuals=[visual]))
        self.assertEqual(practice["label"], "Critical")
        self.assertEqual(practice["score"], 90)
        failed = [rule for rule in practice["rules"] if not rule["passed"]]
        self.assertEqual([rule["id"] for rule in failed], ["ENSURE_THEME_COLOURS"])

    def test_advanced_filters_and_objects(self) -> None:
        projections = [
            {
                "field": {
                    "Column": {
                        "Expression": {"SourceRef": {"Entity": "Sales"}},
                        "Property": f"C{index}",
                    }
                }
            }
            for index in range(7)
        ]
        filters = [
            {"name": f"f{index}", "type": "Advanced"}
            for index in range(5)
        ]
        visual = {
            "name": "v1",
            "visual": {
                "visualType": "pivotTable",
                "query": {"queryState": {"Values": {"projections": projections}}},
            },
            "filterConfig": {"filters": filters},
        }
        practice = build_report_practice(definition(visuals=[visual]))
        failed = {rule["id"] for rule in practice["rules"] if not rule["passed"]}
        self.assertIn("REDUCE_OBJECTS_WITHIN_VISUALS", failed)
        self.assertIn("REDUCE_ADVANCED_FILTERS", failed)
        self.assertEqual(practice["label"], "Warning")
        self.assertEqual(practice["score"], 80)

    def test_report_practice_text_blank_when_unavailable(self) -> None:
        self.assertEqual(report_practice_text({}), "-")
        self.assertEqual(
            report_practice_text({"available": True, "score": 0, "label": ""}),
            "-",
        )


if __name__ == "__main__":
    unittest.main()
