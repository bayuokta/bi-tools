"""Uji Best Practice Analyzer model (tanpa XMLA/REST/SQLite)."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.best_practice import (
    _EVALUATORS,
    UNSUPPORTED_REASONS,
    build_best_practice,
    load_rules,
    model_verdict,
)
from core.paths import RULES_DIR

RULE_FILE = RULES_DIR / "BPARules.json"


def column(
    name: str,
    table: str = "Sales",
    *,
    data_type: str = "string",
    status: str = "Used",
    size: int = 1024,
    cardinality: int = 0,
    hidden: bool = False,
    calculated: bool = False,
    expression: str = "",
    format_string: str = "",
    description: str = "desc",
    summarize_by: str = "none",
    source_column: str = "Source",
    data_category: str = "",
    is_key: bool = False,
    sort_by: str = "",
    column_type: str = "data",
):
    stat = SimpleNamespace(
        column=name,
        table=table,
        data_type=data_type,
        column_type=column_type,
        size_total_bytes=size,
        size_data_bytes=size // 2,
        size_hierarchy_bytes=0,
        size_dictionary_bytes=size // 2,
        cardinality=cardinality,
        is_hidden=hidden,
        is_calculated=calculated,
        expression=expression,
        format_string=format_string,
        description=description,
        summarize_by=summarize_by,
        source_column=source_column,
        data_category=data_category,
        is_key=is_key,
        sort_by_column=sort_by,
        rows=100,
        error_message="",
        has_error=False,
    )
    return SimpleNamespace(column=stat, status=status, reason="", report_records=[], model_refs=[])


def measure(
    name: str,
    table: str = "Sales",
    *,
    expression: str = "1",
    status: str = "Used",
    format_string: str = "#,0",
    hidden: bool = False,
    description: str = "desc",
    data_type: str = "double",
):
    stat = SimpleNamespace(
        measure=name,
        table=table,
        data_type=data_type,
        expression=expression,
        format_string=format_string,
        is_hidden=hidden,
        description=description,
        display_folder="",
        error_message="",
        has_error=False,
    )
    return SimpleNamespace(measure=stat, status=status, reason="", report_records=[], model_refs=[])


def table(
    name: str,
    *,
    rows: int = 1000,
    partitions: int = 1,
    mode: str = "Import",
    hidden: bool = False,
    data_category: str = "",
    description: str = "desc",
    calculated: bool = False,
    calc_group: bool = False,
    column_count: int = 1,
):
    return SimpleNamespace(
        table=name,
        rows=rows,
        partition_count=partitions,
        storage_mode=mode,
        is_hidden=hidden,
        data_category=data_category,
        description=description,
        is_calculated_table=calculated,
        is_calculation_group=calc_group,
        size_total_bytes=1024,
        column_count=column_count,
        measure_count=1,
    )


def relationship(
    name: str,
    from_table: str,
    from_column: str,
    to_table: str,
    to_column: str,
    *,
    from_type: str = "many",
    to_type: str = "one",
    cross: str = "oneDirection",
    active: bool = True,
):
    return {
        "name": name,
        "from_table": from_table,
        "from_column": from_column,
        "to_table": to_table,
        "to_column": to_column,
        "from_cardinality": from_type,
        "to_cardinality": to_type,
        "cross_filtering": cross,
        "is_active": active,
        "is_auto": False,
    }


def result(
    *,
    columns=(),
    measures=(),
    tables=(),
    relationships=(),
    m_queries=(),
    reports_included: bool = True,
    coverage_complete: bool = True,
):
    return SimpleNamespace(
        dataset_id="ds",
        dataset_name="Model Uji",
        columns=list(columns),
        measures=list(measures),
        relationships=list(relationships),
        m_queries=list(m_queries),
        stats=SimpleNamespace(tables=list(tables)),
        reports=[],
        report_pages={},
        unresolved=[],
        reports_included=reports_included,
        coverage_complete=coverage_complete,
        report_total=0,
        report_scanned=0,
        report_skipped=0,
        report_failed=0,
    )


class CatalogTests(unittest.TestCase):
    def test_catalog_is_complete(self) -> None:
        rules = load_rules()
        self.assertEqual(len(rules), 71)
        ids = {rule.id for rule in rules}
        self.assertEqual(set(_EVALUATORS) - ids, set())
        self.assertEqual(set(UNSUPPORTED_REASONS) - ids, set())
        missing = [
            rule.id
            for rule in rules
            if rule.id not in _EVALUATORS and rule.id not in UNSUPPORTED_REASONS
        ]
        self.assertEqual(missing, [])
        self.assertEqual(len(_EVALUATORS), 54)
        self.assertEqual(len(UNSUPPORTED_REASONS), 17)

    def test_missing_catalog_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.best_practice.RULES_DIR", Path(tmp)):
                data = build_best_practice(result())
        self.assertFalse(data["available"])
        self.assertIn("could not be read", data["error"])

    def test_verdict_boundaries(self) -> None:
        self.assertEqual(model_verdict(0)[0], "Power BI Pro")
        self.assertEqual(model_verdict(49)[0], "Power BI Pro")
        self.assertEqual(model_verdict(50)[0], "Good")
        self.assertEqual(model_verdict(200)[0], "Good")
        self.assertEqual(model_verdict(201)[0], "Ok")
        self.assertEqual(model_verdict(600)[0], "Poor")
        self.assertEqual(model_verdict(601)[0], "Awful")
        self.assertEqual(model_verdict(800)[0], "Power BI Criminal")


class EvaluationTests(unittest.TestCase):
    def sample(self, *, coverage_complete: bool = True) -> SimpleNamespace:
        return result(
            columns=[
                column(
                    "Amount",
                    data_type="double",
                    cardinality=250_000,
                    description="",
                    summarize_by="sum",
                    format_string="",
                ),
                column(
                    "Order Date",
                    data_type="datetime",
                    format_string="",
                    description="",
                ),
                column(
                    "Month Name",
                    data_type="string",
                    sort_by="",
                    description="",
                ),
                column(
                    "Hidden Unused",
                    status="Unused",
                    hidden=True,
                    description="",
                ),
                column(
                    "Calc",
                    calculated=True,
                    expression="RELATED('Dim'[Name])",
                    description="",
                ),
                column("Broken Calc", calculated=True, expression="", description=""),
                column("Key", data_type="string", is_key=False, description=""),
                column("Customer Name", table="Dim", description="Customer"),
            ],
            measures=[
                measure("Total", expression="SUM(Sales[Amount])", format_string="#,0"),
                measure("Duplicate", expression="SUM(Sales[Amount])", format_string="#,0"),
                measure("Wrapper", expression="[Total]", format_string="#,0"),
                measure("Bad", expression="IFERROR([Total] / 2, 0)", format_string="#,0"),
                measure(
                    "YTD",
                    expression="TOTALYTD([Total], 'Date'[Date])",
                    format_string="#,0",
                ),
                measure("No Format", expression="1", format_string="", hidden=True),
            ],
            tables=[
                table("Sales", rows=30_000_000, partitions=1),
                table("Dim"),
                table("Date", data_category="Time"),
                table("LocalDateTable_abc", calculated=True),
            ],
            relationships=[
                relationship(
                    "Rel High",
                    "Sales",
                    "Amount",
                    "Dim",
                    "Customer Name",
                    cross="bothDirections",
                ),
                relationship(
                    "Rel Inactive",
                    "Sales",
                    "Key",
                    "Dim",
                    "Key",
                    active=False,
                ),
            ],
            m_queries=[
                {
                    "name": "Sales",
                    "kind": "Table",
                    "expression": 'let Source = ... in Table.AddColumn(Source, "x", each 1)',
                }
            ],
            coverage_complete=coverage_complete,
        )

    def test_payload_shape_and_supported_counts(self) -> None:
        data = build_best_practice(self.sample())
        self.assertTrue(data["available"])
        self.assertEqual(data["rule_count"], 71)
        self.assertEqual(data["evaluated"], 54)
        self.assertEqual(data["not_evaluated"], 17)
        self.assertGreater(data["score"], 0)
        self.assertIn(data["verdict"], {
            "Power BI Pro", "Good", "Ok", "Poor", "Awful", "Power BI Criminal"
        })
        self.assertEqual(
            sum(row["score"] for row in data["rules"]), data["score"]
        )
        statuses = {row["status"] for row in data["rules"]}
        self.assertTrue(statuses <= {"violation", "pass", "not_evaluated", "needs_coverage"})

    def test_expected_rules_fire(self) -> None:
        data = build_best_practice(self.sample())
        fired = {
            row["id"]
            for row in data["rules"]
            if row["status"] == "violation"
        }
        for rule_id in (
            "AVOID_FLOATING_POINT_DATA_TYPES",
            "REDUCE_USAGE_OF_CALCULATED_COLUMNS_THAT_USE_THE_RELATED_FUNCTION",
            "LARGE_TABLES_SHOULD_BE_PARTITIONED",
            "MINIMIZE_POWER_QUERY_TRANSFORMATIONS",
            "AVOID_DUPLICATE_MEASURES",
            "AVOID_USING_THE_IFERROR_FUNCTION",
            "MEASURES_SHOULD_NOT_BE_DIRECT_REFERENCES_OF_OTHER_MEASURES",
            "EXPRESSION_RELIANT_OBJECTS_MUST_HAVE_AN_EXPRESSION",
            "OBJECTS_WITH_NO_DESCRIPTION",
            "REMOVE_AUTO-DATE_TABLE",
        ):
            self.assertIn(rule_id, fired, rule_id)

    def test_score_uses_log_scale(self) -> None:
        data = build_best_practice(self.sample())
        row = next(
            item
            for item in data["rules"]
            if item["id"] == "AVOID_FLOATING_POINT_DATA_TYPES"
        )
        expected = round(row["severity"] * row["count"] * data["log_scale"])
        self.assertEqual(row["score"], expected)
        self.assertEqual(data["model_objects"], data["model_objects"])

    def test_report_usage_rules_need_coverage(self) -> None:
        data = build_best_practice(self.sample(coverage_complete=False))
        rows = {row["id"]: row for row in data["rules"]}
        self.assertEqual(rows["UNNECESSARY_COLUMNS"]["status"], "needs_coverage")
        self.assertEqual(rows["UNNECESSARY_MEASURES"]["status"], "needs_coverage")

    def test_model_only_still_evaluates_model_rules(self) -> None:
        data = build_best_practice(
            result(
                columns=[column("Amount", data_type="double")],
                coverage_complete=False,
                reports_included=False,
            )
        )
        rows = {row["id"]: row for row in data["rules"]}
        self.assertEqual(
            rows["AVOID_FLOATING_POINT_DATA_TYPES"]["status"], "violation"
        )

    def test_items_carry_targets_and_rule_metadata(self) -> None:
        data = build_best_practice(self.sample())
        item = next(
            item
            for item in data["items"]
            if item["rule_id"] == "AVOID_FLOATING_POINT_DATA_TYPES"
        )
        self.assertEqual(item["target"]["kind"], "column")
        self.assertEqual(item["target"]["table"], "Sales")
        self.assertEqual(item["target"]["name"], "Amount")
        self.assertIn("rule_score", item)
        self.assertIn("category", item)
        self.assertIn("severity", item)

    def test_total_score_matches_log_formula(self) -> None:
        data = build_best_practice(self.sample())
        expected = sum(
            round(row["severity"] * row["count"] * math.log10(data["model_objects"]))
            for row in data["rules"]
            if row["status"] in {"violation", "pass"}
        )
        self.assertEqual(data["score"], expected)


class TemplateParityTests(unittest.TestCase):
    def rules(self) -> dict[str, object]:
        return {rule.id: rule for rule in load_rules()}

    def test_model_objects_excludes_m_queries(self) -> None:
        base = result(
            columns=[column("Amount")],
            measures=[measure("Total")],
            tables=[table("Sales")],
        )
        with_m = result(
            columns=[column("Amount")],
            measures=[measure("Total")],
            tables=[table("Sales")],
            m_queries=[
                {"name": "Sales", "kind": "Table", "expression": "let 1 in 1"}
            ],
        )
        self.assertEqual(
            build_best_practice(base)["model_objects"],
            build_best_practice(with_m)["model_objects"],
        )

    def test_object_labels_follow_measure_killer(self) -> None:
        data = build_best_practice(
            result(
                columns=[column("Customer", description="")],
                measures=[measure("Total", description="")],
                tables=[
                    table("Sales", description=""),
                    table("Calc", calculated=True, description=""),
                ],
            )
        )
        objects = {item["object"] for item in data["items"]}
        self.assertIn("'Sales'[Customer]", objects)
        self.assertIn("'Sales'[Total]", objects)
        self.assertIn("Sales (Table)", objects)
        self.assertIn("Calc (Calculated Table)", objects)

    def test_relationship_label_uses_ascii_cardinality(self) -> None:
        rule = self.rules()["CHECK_IF_BI-DIRECTIONAL_AND_MANY-TO-MANY_RELATIONSHIPS_ARE_VALID"]
        data = build_best_practice(
            result(
                columns=[column("Key", data_type="string")],
                relationships=[
                    relationship("Rel", "A", "Key", "B", "Key", cross="bothDirections")
                ],
            )
        )
        items = [
            item for item in data["items"] if item["rule_id"] == rule.id
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["object"], "'A'[Key] N <-> 1 'B'[Key]")

    def test_relationship_integer_one_row_per_relationship(self) -> None:
        rule = self.rules()["RELATIONSHIP_COLUMNS_SHOULD_BE_OF_INTEGER_DATA_TYPE"]
        data = build_best_practice(
            result(
                columns=[
                    column("From Key", table="Fact", data_type="string"),
                    column("To Key", table="Dim", data_type="string"),
                ],
                relationships=[
                    relationship("Rel", "Fact", "From Key", "Dim", "To Key")
                ],
            )
        )
        items = [item for item in data["items"] if item["rule_id"] == rule.id]
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0]["object"],
            "'Fact'[From Key] N <- 1 'Dim'[To Key] (Text, Text)",
        )

    def test_relationship_integer_passes_for_integer_columns(self) -> None:
        rule = self.rules()["RELATIONSHIP_COLUMNS_SHOULD_BE_OF_INTEGER_DATA_TYPE"]
        data = build_best_practice(
            result(
                columns=[
                    column("From Key", table="Fact", data_type="int64"),
                    column("To Key", table="Dim", data_type="int64"),
                ],
                relationships=[
                    relationship("Rel", "Fact", "From Key", "Dim", "To Key")
                ],
            )
        )
        rows = {row["id"]: row for row in data["rules"]}
        self.assertEqual(rows[rule.id]["status"], "pass")

    def test_tables_without_relationship_skips_measure_and_field_parameter(self) -> None:
        rule = self.rules()["ENSURE_TABLES_HAVE_RELATIONSHIPS"]
        columns = [
            column("Field", table="Parameter Posisi", column_type="Field parameter")
        ]
        data = build_best_practice(
            result(
                columns=columns,
                tables=[
                    table("Pages"),
                    table("_Measures", column_count=0),
                    table("Hidden", hidden=True),
                    table("Parameter Posisi", calculated=True),
                ],
                relationships=[],
            )
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(objects, {"Pages (Table)"})

    def test_calculated_tables_skip_field_parameter(self) -> None:
        rule = self.rules()["REDUCE_USAGE_OF_CALCULATED_TABLES"]
        data = build_best_practice(
            result(
                columns=[
                    column(
                        "Field",
                        table="Parameter Posisi",
                        column_type="Field parameter",
                    )
                ],
                tables=[
                    table("Parameter", calculated=True),
                    table("Parameter Posisi", calculated=True),
                ],
            )
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(objects, {"Parameter (Calculated Table)"})

    def test_measure_format_flags_variant_measures(self) -> None:
        rule = self.rules()["PROVIDE_FORMAT_STRING_FOR_MEASURES"]
        data = build_best_practice(
            result(
                measures=[
                    measure(
                        "Dynamic", table="Pages", data_type="variant", format_string=""
                    ),
                    measure(
                        "Hidden", table="Pages", data_type="variant",
                        format_string="", hidden=True,
                    ),
                ]
            )
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(objects, {"'Pages'[Dynamic]"})

    def test_first_letter_checks_hidden_columns(self) -> None:
        rule = self.rules()["FIRST_LETTER_OF_OBJECTS_MUST_BE_CAPITALIZED"]
        data = build_best_practice(
            result(columns=[column("lowercase", hidden=True)])
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(objects, {"'Sales'[lowercase]"})

    def test_date_format_checks_every_datetime_column(self) -> None:
        rule = self.rules()["DATECOLUMN_FORMATSTRING"]
        data = build_best_practice(
            result(
                columns=[
                    column("Start of Month", data_type="datetime", format_string="General Date"),
                    column("Proper Date", data_type="datetime", format_string="dd-MM-yyyy"),
                ]
            )
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(
            objects,
            {
                "'Sales'[Start of Month] "
                "(Format: 'General Date' - Expected: 'dd-MM-yyyy')"
            },
        )

    def test_primary_keys_include_date_table_but_not_auto_date(self) -> None:
        rule = self.rules()["MARK_PRIMARY_KEYS"]
        data = build_best_practice(
            result(
                columns=[
                    column("Key", table="Sales", data_type="string"),
                    column("Dates Key", table="Dates", data_type="int64", is_key=False),
                    column(
                        "Date", table="LocalDateTable_abc", data_type="int64",
                        is_key=False,
                    ),
                ],
                tables=[
                    table("Sales"),
                    table("Dates", data_category="Time"),
                    table("LocalDateTable_abc"),
                ],
                relationships=[
                    relationship("Dates Rel", "Sales", "Key", "Dates", "Dates Key"),
                    relationship(
                        "Auto Rel", "Sales", "Key", "LocalDateTable_abc", "Date"
                    ),
                ],
            )
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(objects, {"'Dates'[Dates Key]"})


    def test_numeric_summarize_includes_data_type(self) -> None:
        rule = self.rules()["NUMERIC_COLUMN_SUMMARIZE_BY"]
        data = build_best_practice(
            result(
                columns=[column("Amount", data_type="int64", summarize_by="sum")]
            )
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(objects, {"'Sales'[Amount] (Integer)"})

    def test_percentage_format_includes_expected_format(self) -> None:
        rule = self.rules()["PERCENTAGE_FORMATTING"]
        data = build_best_practice(
            result(
                measures=[
                    measure("Growth", format_string="0.00%;-0.00%;0.00%")
                ]
            )
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(len(objects), 1)
        self.assertTrue(
            objects.pop().endswith(
                "(Format: '0.00%;-0.00%;0.00%' - Expected: "
                "'#,0.0%;-#,0.0%;#,0.0%' or '#,0.0\\ %;-#,0.0\\ %;#,0.0\\ %')"
            )
        )

    def test_power_query_transformation_uses_table_suffix(self) -> None:
        rule = self.rules()["MINIMIZE_POWER_QUERY_TRANSFORMATIONS"]
        data = build_best_practice(
            result(
                tables=[table("Sales")],
                m_queries=[
                    {
                        "name": "Sales",
                        "kind": "Table",
                        "expression": "Table.AddColumn(Source, \"x\", each 1)",
                    }
                ],
            )
        )
        objects = {
            item["object"]
            for item in data["items"]
            if item["rule_id"] == rule.id
        }
        self.assertEqual(objects, {"Sales (Table)"})

    def test_calculation_group_uses_table_suffix(self) -> None:
        data = build_best_practice(
            result(tables=[table("Time Intelligence", calc_group=True, description="")])
        )
        objects = {item["object"] for item in data["items"]}
        self.assertIn("Time Intelligence (Table)", objects)
        self.assertNotIn("Time Intelligence (Calculation Group)", objects)

    def test_date_rule_name_matches_template(self) -> None:
        data = build_best_practice(result())
        rows = {row["id"]: row for row in data["rules"]}
        self.assertEqual(
            rows["DATECOLUMN_FORMATSTRING"]["name"],
            '[Formatting] Provide format string for "Date" columns.',
        )


if __name__ == "__main__":
    unittest.main()
