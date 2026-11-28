"""Uji ekspor tab DAX expressions mengikuti template Measure Killer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from core.dax_export import (
    DAX_RESULT_COLUMNS,
    build_dax_rows,
    write_dax_export,
)


def result() -> SimpleNamespace:
    function = SimpleNamespace(
        name="PercentageGrowth",
        expression="(x: SCALAR) => x",
        description="",
        lineage_tag="fn-guid",
    )
    measure_stat = SimpleNamespace(
        table="_Measures",
        measure="Max Pages",
        expression="MAX('Pages'[Pages])",
        display_folder="",
        description="",
        lineage_tag="measure-guid",
        has_error=False,
    )
    calculated = SimpleNamespace(
        table="Dates",
        column="Day",
        column_type="calculated",
        is_calculated=True,
        expression="DAY(Dates[Dates])",
        display_folder="",
        description="",
        lineage_tag="column-guid",
        has_error=False,
    )
    data = SimpleNamespace(
        table="Dates",
        column="Dates",
        column_type="data",
        is_calculated=False,
        expression="",
        display_folder="",
        description="",
        lineage_tag="data-guid",
        has_error=False,
    )
    parameter_column = SimpleNamespace(
        table="Parameter Posisi",
        column="Parameter",
        column_type="Field parameter",
        is_calculated=False,
        expression="",
        display_folder="",
        description="",
        lineage_tag="param-column-guid",
        has_error=False,
    )
    tables = [
        SimpleNamespace(
            table="Parameter",
            is_calculated_table=True,
            is_calculation_group=False,
            expression="GENERATESERIES(3, 6, 3)",
            lineage_tag="table-guid",
            description="",
        ),
        SimpleNamespace(
            table="Parameter Posisi",
            is_calculated_table=True,
            is_calculation_group=False,
            expression='{ ("A", NAMEOF(...), 0) }',
            lineage_tag="field-param-guid",
            description="",
        ),
        SimpleNamespace(
            table="Time Intelligence",
            is_calculated_table=False,
            is_calculation_group=True,
            expression="",
            lineage_tag="group-guid",
            description="",
        ),
    ]
    return SimpleNamespace(
        dataset_name="Model Uji",
        functions=[SimpleNamespace(function=function, status="Used", use_count=1)],
        measures=[
            SimpleNamespace(
                measure=measure_stat,
                status="Used",
                use_count=2,
            )
        ],
        columns=[
            SimpleNamespace(column=calculated, status="Used", use_count=1),
            SimpleNamespace(column=data, status="Used", use_count=1),
            SimpleNamespace(column=parameter_column, status="Unused", use_count=0),
        ],
        stats=SimpleNamespace(tables=tables),
    )


class DaxExportTests(unittest.TestCase):
    def test_build_rows_contains_all_expression_objects(self) -> None:
        rows = build_dax_rows(result())
        self.assertEqual(len(rows), 5)
        by_name = {row["Name"]: row for row in rows}
        self.assertEqual(
            [row["Type"] for row in rows],
            [
                "User-defined function",
                "Measure",
                "Calculated Column",
                "Calculated Table",
                "Field param. table",
            ],
        )
        function = by_name["PercentageGrowth"]
        self.assertEqual(function["Table"], "")
        self.assertEqual(function["Has_error"], "N/A")
        self.assertEqual(function["Best_practices_violations"], 0)
        self.assertEqual(function["Source"], "Model Uji")
        self.assertEqual(function["Source_type"], "Semantic model")
        self.assertEqual(function["Lineage_tag"], "fn-guid")
        self.assertEqual(function["Expression"], "(x: SCALAR) => x")

        measure = by_name["Max Pages"]
        self.assertEqual(measure["Table"], "_Measures")
        self.assertFalse(measure["Has_error"])
        self.assertEqual(measure["Lineage_tag"], "measure-guid")

        column = by_name["Day"]
        self.assertEqual(column["Type"], "Calculated Column")
        self.assertEqual(column["Table"], "Dates")

        table = by_name["Parameter"]
        self.assertEqual(table["Type"], "Calculated Table")
        self.assertEqual(table["Expression"], "GENERATESERIES(3, 6, 3)")
        self.assertEqual(table["Has_error"], "N/A")

        field_param = by_name["Parameter Posisi"]
        self.assertEqual(field_param["Type"], "Field param. table")
        self.assertEqual(field_param["Lineage_tag"], "field-param-guid")

        self.assertNotIn("Dates", [row["Name"] for row in rows])
        self.assertNotIn("Time Intelligence", by_name)

    def test_best_practice_violations_count_division(self) -> None:
        def measure(name: str, expression: str) -> SimpleNamespace:
            return SimpleNamespace(
                measure=SimpleNamespace(
                    table="Sales",
                    measure=name,
                    expression=expression,
                    display_folder="",
                    description="",
                    lineage_tag="",
                    has_error=False,
                ),
                status="Used",
            )

        data = SimpleNamespace(
            dataset_name="Model Uji",
            functions=[],
            measures=[
                measure("Bad", "SUM(Sales[A]) / SUM(Sales[B])"),
                measure("Good", "DIVIDE(SUM(Sales[A]), SUM(Sales[B]))"),
            ],
            columns=[],
            stats=SimpleNamespace(tables=[]),
        )
        rows = {row["Name"]: row for row in build_dax_rows(data)}
        self.assertEqual(rows["Bad"]["Best_practices_violations"], 1)
        self.assertEqual(rows["Good"]["Best_practices_violations"], 0)

    def test_write_dax_export_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "DAX.xlsx"
            write_dax_export(result(), target)
            frame = pd.read_excel(target, "DAX expressions", keep_default_na=False)
        self.assertEqual(list(frame.columns), DAX_RESULT_COLUMNS)
        self.assertEqual(len(frame), 5)


if __name__ == "__main__":
    unittest.main()
