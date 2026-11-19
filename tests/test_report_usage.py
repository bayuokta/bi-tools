"""Uji scanner pemakaian field: PBIR dan PBIR-Legacy (tanpa jaringan)."""

from __future__ import annotations

import json
import unittest

from core.fabric_api import PBIR, PBIR_LEGACY, DefinitionPart, ReportDefinition
from core.report_usage import (
    USAGE_CALCULATION,
    USAGE_FIELD,
    USAGE_FILTER_PAGE,
    USAGE_FILTER_REPORT,
    USAGE_FILTER_VISUAL,
    USAGE_FORMAT,
    USAGE_QUERY_FILTER,
    USAGE_SORT,
    scan_definition,
)


def definition(report_format: str, parts: dict[str, object]) -> ReportDefinition:
    return ReportDefinition(
        report_format=report_format,
        parts=tuple(
            DefinitionPart(path=path, payload=json.dumps(payload).encode("utf-8"))
            for path, payload in parts.items()
        ),
    )


def column(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def measure(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def aggregation(entity: str, prop: str, function: int = 0) -> dict:
    return {
        "Aggregation": {
            "Expression": {"Column": column(entity, prop)["Column"]},
            "Function": function,
        }
    }


def pbir_parts() -> dict[str, object]:
    return {
        "definition/report.json": {
            "filterConfig": {
                "filters": [
                    {
                        "field": column("Sales", "Region"),
                        "filter": {
                            "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                            "Where": [],
                        },
                        "type": "Advanced",
                    }
                ]
            }
        },
        "definition/pages/pages.json": {"pageOrder": ["p1"], "activePageName": "p1"},
        "definition/pages/p1/page.json": {
            "displayName": "Overview",
            "filterConfig": {
                "filters": [{"field": column("Sales", "Segment"), "type": "Categorical"}]
            },
        },
        "definition/pages/p1/visuals/v1/visual.json": {
            "name": "v1",
            "visual": {
                "visualType": "tableEx",
                "query": {
                    "queryState": {
                        "Values": {
                            "projections": [
                                {"field": column("Sales", "Customer"), "queryRef": "Sales.Customer"},
                                {"field": measure("Sales", "Total Sales"), "queryRef": "Sales.Total Sales"},
                                {
                                    "field": aggregation("Sales", "Qty"),
                                    "queryRef": "Sum(Sales.Qty)",
                                },
                            ]
                        }
                    },
                    "sortDefinition": {
                        "sort": [
                            {
                                "field": column("Sales", "Customer"),
                                "direction": "Ascending",
                            }
                        ]
                    },
                },
                "visualContainerObjects": {
                    "title": [
                        {"properties": {"text": {"expr": {"Literal": {"Value": "'Customer list'"}}}}}
                    ]
                },
                "objects": {
                    "labels": [
                        {
                            "properties": {
                                "color": {
                                    "solid": {
                                        "color": {
                                            "expr": measure("Sales", "Highlight")
                                        }
                                    }
                                }
                            }
                        }
                    ]
                },
            },
            "filterConfig": {
                "filters": [{"field": column("Sales", "Year"), "type": "Advanced"}]
            },
        },
        "definition/pages/p1/visuals/g1/visual.json": {
            "name": "g1",
            "visualGroup": {"displayName": "Filter Pane"},
            "isHidden": True,
        },
        "definition/pages/p1/visuals/v2/visual.json": {
            "name": "v2",
            "parentGroupName": "g1",
            "visual": {
                "visualType": "slicer",
                "query": {
                    "queryState": {
                        "Values": {
                            "projections": [
                                {"field": column("Sales", "Country"), "queryRef": "Sales.Country"}
                            ]
                        }
                    }
                },
            },
        },
        "definition/pages/p1/visuals/v3/visual.json": {
            "name": "v3",
            "visual": {
                "visualType": "tableEx",
                "query": {
                    "queryState": {
                        "Values": {
                            "projections": [
                                {
                                    "field": {
                                        "NativeVisualCalculation": {
                                            "Name": "Running Qty",
                                            "Expression": "SUMX ( Sales, Sales[Qty] )",
                                        }
                                    },
                                    "queryRef": "Running Qty",
                                }
                            ]
                        }
                    }
                },
            },
        },
    }


def legacy_parts() -> dict[str, object]:
    def legacy_title() -> dict:
        return {
            "title": [
                {"properties": {"text": {"expr": {"Literal": {"Value": "'Customer list'"}}}}}
            ]
        }

    config = {
        "name": "v1",
        "singleVisual": {
            "visualType": "tableEx",
            "projections": {
                "Values": [
                    {"queryRef": "Sales.Customer"},
                    {"queryRef": "Sales.Total Sales"},
                    {"queryRef": "Sum(Sales.Qty)"},
                ]
            },
            "prototypeQuery": {
                "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                "Select": [
                    {"Column": column("Sales", "Customer")["Column"], "Name": "Sales.Customer"},
                    {
                        "Measure": measure("Sales", "Total Sales")["Measure"],
                        "Name": "Sales.Total Sales",
                    },
                    {
                        "Aggregation": aggregation("Sales", "Qty")["Aggregation"],
                        "Name": "Sum(Sales.Qty)",
                    },
                ],
                "Where": [
                    {
                        "Condition": {
                            "Comparison": {
                                "ComparisonKind": 0,
                                "Left": {
                                    "Column": {
                                        "Expression": {
                                            "SourceRef": {"Source": "s"}
                                        },
                                        "Property": "Channel",
                                    }
                                },
                                "Right": {"Literal": {"Value": "'Online'"}},
                            }
                        }
                    }
                ],
                "Version": 2,
            },
            "sortDefinition": {
                "sort": [{"field": column("Sales", "Customer"), "direction": "Ascending"}]
            },
            "vcObjects": legacy_title(),
            "objects": {
                "labels": [
                    {
                        "properties": {
                            "color": {
                                "solid": {
                                    "color": {"expr": measure("Sales", "Highlight")}
                                }
                            }
                        }
                    }
                ]
            },
        },
    }
    group_config = {"name": "g1", "singleVisualGroup": {"displayName": "Filter Pane"}}
    report = {
        "config": json.dumps({"version": "5.43"}),
        "sections": [
            {
                "name": "s1",
                "displayName": "Overview",
                "displayOption": 2,
                "filters": json.dumps(
                    [{"expression": column("Sales", "Segment"), "type": "Categorical"}]
                ),
                "visualContainers": [
                    {
                        "config": json.dumps(config),
                        "filters": json.dumps(
                            [{"expression": column("Sales", "Year"), "type": "Advanced"}]
                        ),
                    },
                    {"config": json.dumps(group_config)},
                ],
            }
        ],
        "filters": json.dumps(
            [{"expression": column("Sales", "Region"), "type": "Advanced"}]
        ),
    }
    return {"report.json": report}


class PbirScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.usage = scan_definition(
            definition(PBIR, pbir_parts()), table_names=["Sales"]
        )

    def test_counts(self) -> None:
        self.assertEqual(self.usage.report_format, PBIR)
        self.assertEqual(self.usage.pages, 1)
        self.assertEqual(self.usage.visuals, 3)

    def test_pages_and_theme(self) -> None:
        parts = pbir_parts()
        parts["definition/report.json"]["themeCollection"] = {
            "baseTheme": {"name": "Corporate"}
        }
        parts["definition/pages/pages.json"]["pageOrder"] = ["p1", "p2"]
        parts["definition/pages/p2/page.json"] = {
            "displayName": "Arsip",
            "visibility": "HiddenInViewMode",
        }
        usage = scan_definition(definition(PBIR, parts), table_names=["Sales"])

        self.assertEqual(usage.theme, "Corporate")
        self.assertEqual(usage.pages, 2)
        pages = {row["page_name"]: row for row in usage.page_rows}
        self.assertFalse(pages["Overview"]["is_hidden"])
        self.assertTrue(pages["Arsip"]["is_hidden"])
        self.assertEqual(pages["Overview"]["visual_count"], 3)

    def test_visual_fields(self) -> None:
        fields = [
            (row.field_kind, row.table, row.field, row.aggregation)
            for row in self.usage.records
            if row.usage_kind == USAGE_FIELD and row.visual_id == "v1"
        ]
        self.assertIn(("Column", "Sales", "Customer", ""), fields)
        self.assertIn(("Measure", "Sales", "Total Sales", ""), fields)
        self.assertIn(("Aggregation", "Sales", "Qty", "Sum"), fields)

    def test_filters_report_page_visual(self) -> None:
        kinds = {row.usage_kind for row in self.usage.records}
        self.assertIn(USAGE_FILTER_REPORT, kinds)
        self.assertIn(USAGE_FILTER_PAGE, kinds)
        self.assertIn(USAGE_FILTER_VISUAL, kinds)
        visual = [
            row for row in self.usage.records if row.usage_kind == USAGE_FILTER_VISUAL
        ][0]
        self.assertEqual((visual.table, visual.field), ("Sales", "Year"))

    def test_sort_and_formatting(self) -> None:
        sorts = [row for row in self.usage.records if row.usage_kind == USAGE_SORT]
        self.assertEqual([(row.field, row.detail) for row in sorts], [("Customer", "Ascending")])
        formats = [row for row in self.usage.records if row.usage_kind == USAGE_FORMAT]
        self.assertEqual([(row.field_kind, row.field) for row in formats], [("Measure", "Highlight")])

    def test_hidden_group_inheritance(self) -> None:
        slicer = [
            row
            for row in self.usage.records
            if row.usage_kind == USAGE_FIELD and row.visual_id == "v2"
        ]
        self.assertEqual(len(slicer), 1)
        self.assertTrue(slicer[0].is_hidden)

    def test_visual_calculation_references_model_column(self) -> None:
        calculations = [
            row for row in self.usage.records if row.usage_kind == USAGE_CALCULATION
        ]
        self.assertEqual(
            [(row.table, row.field, row.detail) for row in calculations],
            [("Sales", "Qty", "Running Qty")],
        )

    def test_title_falls_back_to_type(self) -> None:
        slicer = [
            row
            for row in self.usage.records
            if row.usage_kind == USAGE_FIELD and row.visual_id == "v2"
        ][0]
        self.assertTrue(slicer.visual_title.startswith("(tanpa judul) slicer"))


class LegacyScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.usage = scan_definition(
            definition(PBIR_LEGACY, legacy_parts()), table_names=["Sales"]
        )

    def test_counts(self) -> None:
        self.assertEqual(self.usage.report_format, PBIR_LEGACY)
        self.assertEqual(self.usage.pages, 1)
        self.assertEqual(self.usage.visuals, 1)

    def test_resolves_select_to_model_fields(self) -> None:
        fields = [
            (row.field_kind, row.table, row.field, row.aggregation)
            for row in self.usage.records
            if row.usage_kind == USAGE_FIELD
        ]
        self.assertIn(("Column", "Sales", "Customer", ""), fields)
        self.assertIn(("Measure", "Sales", "Total Sales", ""), fields)
        self.assertIn(("Aggregation", "Sales", "Qty", "Sum"), fields)

    def test_groups_are_not_counted_as_visuals(self) -> None:
        self.assertFalse(
            any(row.visual_id == "g1" for row in self.usage.records)
        )

    def test_report_and_container_filters(self) -> None:
        report_filter = [
            row for row in self.usage.records if row.usage_kind == USAGE_FILTER_REPORT
        ]
        visual_filter = [
            row for row in self.usage.records if row.usage_kind == USAGE_FILTER_VISUAL
        ]
        page_filter = [
            row for row in self.usage.records if row.usage_kind == USAGE_FILTER_PAGE
        ]
        self.assertEqual([row.field for row in report_filter], ["Region"])
        self.assertEqual([row.field for row in page_filter], ["Segment"])
        self.assertEqual([row.field for row in visual_filter], ["Year"])

    def test_sort_and_formatting(self) -> None:
        sorts = [row for row in self.usage.records if row.usage_kind == USAGE_SORT]
        self.assertEqual([(row.field, row.detail) for row in sorts], [("Customer", "Ascending")])
        formats = [row for row in self.usage.records if row.usage_kind == USAGE_FORMAT]
        self.assertEqual([(row.field_kind, row.field) for row in formats], [("Measure", "Highlight")])

    def test_query_where_resolves_alias(self) -> None:
        query_filters = [
            row for row in self.usage.records if row.usage_kind == USAGE_QUERY_FILTER
        ]
        self.assertEqual(
            [(row.table, row.field, row.detail) for row in query_filters],
            [("Sales", "Channel", "query Where")],
        )


class ParityTests(unittest.TestCase):
    def test_core_usage_matches_between_formats(self) -> None:
        core_kinds = {
            USAGE_FIELD,
            USAGE_FILTER_REPORT,
            USAGE_FILTER_PAGE,
            USAGE_FILTER_VISUAL,
            USAGE_SORT,
            USAGE_FORMAT,
        }

        def rows(definition_part: ReportDefinition) -> set[tuple]:
            usage = scan_definition(definition_part, table_names=["Sales"])
            return {
                (
                    row.usage_kind,
                    row.field_kind,
                    row.table,
                    row.field,
                    row.aggregation,
                )
                for row in usage.records
                if row.usage_kind in core_kinds
            }

        pbir_rows = rows(definition(PBIR, pbir_parts()))
        legacy_rows = rows(definition(PBIR_LEGACY, legacy_parts()))
        # Objek yang sengaja berbeda: PBIR punya group/slicer & visual
        # calculation, legacy tidak. Sisa pemakaian inti harus identik.
        expected = {
            (USAGE_FIELD, "Column", "Sales", "Customer", ""),
            (USAGE_FIELD, "Measure", "Sales", "Total Sales", ""),
            (USAGE_FIELD, "Aggregation", "Sales", "Qty", "Sum"),
            (USAGE_FILTER_REPORT, "Column", "Sales", "Region", ""),
            (USAGE_FILTER_PAGE, "Column", "Sales", "Segment", ""),
            (USAGE_FILTER_VISUAL, "Column", "Sales", "Year", ""),
            (USAGE_SORT, "Column", "Sales", "Customer", ""),
            (USAGE_FORMAT, "Measure", "Sales", "Highlight", ""),
        }
        self.assertTrue(expected.issubset(pbir_rows))
        self.assertTrue(expected.issubset(legacy_rows))


class LegacyEdgeCaseTests(unittest.TestCase):
    def test_visual_calculation_select_is_not_unresolved(self) -> None:
        config = {
            "name": "v1",
            "singleVisual": {
                "visualType": "tableEx",
                "projections": {
                    "Values": [
                        {"queryRef": "Sales.Customer"},
                        {"queryRef": "select"},
                    ]
                },
                "prototypeQuery": {
                    "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                    "Select": [
                        {
                            "Column": column("Sales", "Customer")["Column"],
                            "Name": "Sales.Customer",
                        },
                        {
                            "NativeVisualCalculation": {
                                "Name": "Running Qty",
                                "Expression": "SUMX ( Sales, Sales[Qty] )",
                            },
                            "Name": "select",
                        },
                    ],
                },
            },
        }
        report = {
            "sections": [
                {
                    "name": "s1",
                    "displayName": "Page 1",
                    "visualContainers": [{"config": json.dumps(config)}],
                }
            ]
        }

        usage = scan_definition(
            definition(PBIR_LEGACY, {"report.json": report}),
            table_names=["Sales"],
        )

        self.assertEqual(usage.unresolved, [])
        calculations = [
            (row.table, row.field) for row in usage.records
            if row.usage_kind == USAGE_CALCULATION
        ]
        self.assertEqual(calculations, [("Sales", "Qty")])

    def test_query_ref_with_parentheses_is_not_treated_as_function(self) -> None:
        config = {
            "name": "v1",
            "singleVisual": {
                "visualType": "tableEx",
                "projections": {
                    "Values": [{"queryRef": "Sales.Total Unit (STNK Date)"}]
                },
                "prototypeQuery": {
                    "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                    "Select": [],
                },
            },
        }
        report = {
            "sections": [
                {
                    "name": "s1",
                    "displayName": "Page 1",
                    "visualContainers": [{"config": json.dumps(config)}],
                }
            ]
        }

        usage = scan_definition(
            definition(PBIR_LEGACY, {"report.json": report}),
            table_names=["Sales"],
        )

        self.assertEqual(usage.unresolved, [])
        fields = [
            (row.table, row.field, row.field_kind) for row in usage.records
            if row.usage_kind == USAGE_FIELD
        ]
        self.assertEqual(
            fields, [("Sales", "Total Unit (STNK Date)", "Field")]
        )


class UnsupportedFormatTests(unittest.TestCase):
    def test_unknown_format_reports_reason(self) -> None:
        usage = scan_definition(ReportDefinition(report_format="unknown", parts=()))

        self.assertEqual(usage.records, [])
        self.assertTrue(any("tidak dikenal" in line for line in usage.unresolved))


if __name__ == "__main__":
    unittest.main()
