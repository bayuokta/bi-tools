"""Uji builder lineage kolom/measure (tanpa XMLA, REST, atau SQLite)."""

from __future__ import annotations

import unittest

from core.analysis_lineage import MAX_USAGE_PER_PAGE, build_lineage
from core.column_stats import ColumnStat, MeasureStat, ModelStats, TableStat
from core.usage_service import (
    STATUS_UNUSED,
    STATUS_USED,
    AnalysisResult,
    ColumnAnalysis,
    MeasureAnalysis,
    ModelReference,
)


def column_stat(
    table: str,
    name: str,
    *,
    calculated: bool = False,
    expression: str = "",
) -> ColumnStat:
    return ColumnStat(
        table=table,
        column=name,
        column_id=1,
        column_type="Calculated" if calculated else "Data",
        data_type="string",
        format_string="",
        display_folder="",
        is_hidden=False,
        is_calculated=calculated,
        sort_by_column="",
        expression=expression,
        size_data_bytes=100,
        size_hierarchy_bytes=0,
        rows=10,
    )


def column_analysis(
    table: str,
    name: str,
    *,
    refs: list[ModelReference] | None = None,
    records: list[dict] | None = None,
    calculated: bool = False,
) -> ColumnAnalysis:
    return ColumnAnalysis(
        column=column_stat(
            table, name, calculated=calculated, expression="SUM(x)" if calculated else ""
        ),
        status=STATUS_USED if (refs or records) else STATUS_UNUSED,
        reason="",
        model_refs=list(refs or []),
        report_records=list(records or []),
    )


def measure_analysis(
    table: str,
    name: str,
    *,
    refs: list[ModelReference] | None = None,
    records: list[dict] | None = None,
) -> MeasureAnalysis:
    return MeasureAnalysis(
        measure=MeasureStat(table=table, measure=name, expression="1"),
        status=STATUS_USED if (refs or records) else STATUS_UNUSED,
        reason="",
        model_refs=list(refs or []),
        report_records=list(records or []),
    )


def usage(
    *,
    report: str = "R1",
    page: str = "P1",
    visual: str = "V1",
    usage_kind: str = "field",
    title: str = "",
    detail: str = "",
    hidden: bool = False,
) -> dict:
    return {
        "report_id": report,
        "report_name": report,
        "page_id": page,
        "page_name": page,
        "visual_id": visual,
        "visual_title": title or visual,
        "visual_type": "tableEx",
        "usage_kind": usage_kind,
        "detail": detail or "Values",
        "is_hidden": hidden,
    }


def make_result(
    *,
    columns: list[ColumnAnalysis] | None = None,
    measures: list[MeasureAnalysis] | None = None,
    reports: list[dict] | None = None,
    m_queries: list[dict] | None = None,
    reports_included: bool = True,
) -> AnalysisResult:
    columns = list(columns or [])
    measures = list(measures or [])
    tables = [
        TableStat(
            table=name,
            column_count=1,
            rows=10,
            size_data_bytes=100,
            size_hierarchy_bytes=0,
        )
        for name in sorted({item.column.table for item in columns})
    ]
    stats = ModelStats(
        model_name="Model",
        compatibility_level=1600,
        last_update="2026-11-20",
        columns=[item.column for item in columns],
        tables=tables,
        segment_bytes=0,
        artifact_bytes=0,
        measures=[item.measure for item in measures],
    )
    return AnalysisResult(
        dataset_id="ds",
        dataset_name="Model",
        workspace_id="ws",
        workspace_name="Workspace",
        analyzed_at="2026-11-20T00:00:00",
        stats=stats,
        columns=columns,
        measures=measures,
        reports=list(reports or []),
        report_total=len(reports or []),
        report_scanned=len(reports or []),
        report_skipped=0,
        report_failed=0,
        method="test",
        coverage="uji",
        coverage_complete=True,
        m_queries=list(m_queries or []),
        reports_included=reports_included,
    )


class LineageBuilderTests(unittest.TestCase):
    def test_invalid_input(self) -> None:
        result = make_result(columns=[column_analysis("T", "C")])
        with self.assertRaises(ValueError):
            build_lineage(result, kind="table", table="T", name="C")
        with self.assertRaises(ValueError):
            build_lineage(result, kind="column", table="T", name="C", direction="x")
        with self.assertRaises(ValueError):
            build_lineage(result, kind="column", table="T", name="Nope")

    def test_measure_upstream_and_report_chain(self) -> None:
        base = measure_analysis(
            "M",
            "Base",
            refs=[
                ModelReference(
                    kind="measure",
                    object="'M'[Calc]",
                    detail="dipakai measure",
                    blocking=False,
                    source_table="M",
                    source_measure="Calc",
                )
            ],
        )
        calc = measure_analysis(
            "M",
            "Calc",
            records=[usage(title="Sales by Month")],
        )
        result = make_result(measures=[base, calc])
        data = build_lineage(result, kind="measure", table="M", name="Calc")

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertIn("measure:M:Base", nodes)
        self.assertIn("measure:M:Calc", nodes)
        self.assertEqual(nodes["measure:M:Calc"]["side"], "root")
        self.assertEqual(nodes["measure:M:Base"]["column"], -1)
        self.assertEqual(nodes["measure:M:Base"]["side"], "upstream")

        report = next(node for node in data["nodes"] if node["kind"] == "report")
        page = next(node for node in data["nodes"] if node["kind"] == "page")
        visual = next(node for node in data["nodes"] if node["kind"] == "visual")
        self.assertEqual(report["label"], "R1")
        self.assertEqual(page["label"], "P1")
        self.assertEqual(visual["label"], "Sales by Month")
        self.assertLess(nodes["measure:M:Base"]["x"], nodes["measure:M:Calc"]["x"])
        self.assertLess(nodes["measure:M:Calc"]["x"], report["x"])
        self.assertLess(report["x"], page["x"])
        self.assertLess(page["x"], visual["x"])

        edges = {(edge["from"], edge["to"], edge["kind"]) for edge in data["edges"]}
        self.assertIn(("measure:M:Base", "measure:M:Calc", "depend"), edges)
        self.assertIn(("measure:M:Calc", report["id"], "usage"), edges)
        self.assertIn((report["id"], page["id"], "page"), edges)
        self.assertIn((page["id"], visual["id"], "visual"), edges)

    def test_column_used_by_measure_shows_reports(self) -> None:
        records = [usage(report="R1", page="P1", visual="V1")]
        total = measure_analysis(
            "KPI",
            "Total",
            refs=[
                ModelReference(
                    kind="measure",
                    object="'KPI'[Total]",
                    detail="measure",
                    blocking=False,
                )
            ],
            records=records,
        )
        amount = column_analysis(
            "Sales",
            "Amount",
            refs=[
                ModelReference(
                    kind="measure",
                    object="'KPI'[Total]",
                    detail="measure",
                    blocking=False,
                )
            ],
        )
        result = make_result(columns=[amount], measures=[total])
        data = build_lineage(result, kind="column", table="Sales", name="Amount")

        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertIn("measure:KPI:Total", nodes)
        self.assertEqual(nodes["measure:KPI:Total"]["column"], 1)
        report = next(node for node in data["nodes"] if node["kind"] == "report")
        self.assertEqual(report["column"], 2)
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertIn(("col:Sales:Amount", "measure:KPI:Total"), edges)
        self.assertIn(("measure:KPI:Total", report["id"]), edges)

    def test_calculated_column_dependency_is_upstream(self) -> None:
        source = column_analysis(
            "T",
            "Source",
            refs=[
                ModelReference(
                    kind="calculated column",
                    object="'T'[Derived]",
                    detail="calculated column",
                )
            ],
        )
        derived = column_analysis("T", "Derived", calculated=True)
        result = make_result(columns=[source, derived])
        data = build_lineage(result, kind="column", table="T", name="Derived")
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertEqual(nodes["col:T:Source"]["column"], -1)
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertIn(("col:T:Source", "col:T:Derived"), edges)

    def test_mquery_node_and_no_dependency_notice(self) -> None:
        amount = column_analysis("Sales", "Amount")
        result = make_result(
            columns=[amount],
            m_queries=[{"name": "Sales", "kind": "Tabel", "source": "Import"}],
        )
        data = build_lineage(result, kind="column", table="Sales", name="Amount")
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertIn("mquery:Sales", nodes)
        self.assertEqual(nodes["mquery:Sales"]["column"], -1)
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertIn(("mquery:Sales", "col:Sales:Amount"), edges)
        self.assertNotIn("no_dependencies", [item["code"] for item in data["notices"]])

    def test_model_reference_kinds_become_nodes(self) -> None:
        refs = [
            ModelReference(kind="relationship", object="'D'[Id]", detail="relasi"),
            ModelReference(kind="sort by", object="'T'[Code]", detail="urutan"),
            ModelReference(kind="hierarchy", object="'T'[Geo]", detail="level"),
            ModelReference(kind="RLS", object="role 'Reader'", detail="filter"),
            ModelReference(kind="field parameter", object="'Param'", detail=""),
        ]
        column = column_analysis("T", "C", refs=refs)
        result = make_result(columns=[column])
        data = build_lineage(result, kind="column", table="T", name="C")
        kinds = {node["kind"] for node in data["nodes"]}
        for expected in (
            "relationship",
            "sort",
            "hierarchy",
            "security",
            "field-parameter",
        ):
            self.assertIn(expected, kinds)
        for node in data["nodes"]:
            if node.get("side") == "downstream":
                self.assertGreaterEqual(node["column"], 1)
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertEqual(len([edge for edge in edges if edge[0] == "col:T:C"]), 5)

    def test_usage_cap_and_filter_nodes(self) -> None:
        records = [
            usage(report="R1", page="P1", visual=f"V{index}", title=f"Visual {index}")
            for index in range(MAX_USAGE_PER_PAGE + 4)
        ]
        records.append(
            usage(
                report="R1",
                page="P1",
                visual="F1",
                usage_kind="filter-page",
                title="",
                detail="Categorical",
            )
        )
        measure = measure_analysis("M", "Total", records=records)
        result = make_result(measures=[measure])
        data = build_lineage(result, kind="measure", table="M", name="Total")
        visuals = [node for node in data["nodes"] if node["kind"] == "visual"]
        filters = [node for node in data["nodes"] if node["kind"] == "filter"]
        more = [node for node in data["nodes"] if node["kind"] == "more"]
        self.assertEqual(len(visuals), MAX_USAGE_PER_PAGE)
        self.assertEqual(len(filters), 1)
        self.assertEqual(len(more), 1)
        self.assertTrue(more[0]["label"].startswith("+"))
        self.assertEqual(more[0]["count"], 4)

    def test_model_only_notice_and_no_reports(self) -> None:
        measure = measure_analysis("M", "Total", records=[usage()])
        result = make_result(measures=[measure], reports_included=False)
        data = build_lineage(result, kind="measure", table="M", name="Total")
        self.assertIn("reports_excluded", [item["code"] for item in data["notices"]])
        self.assertNotIn("report", {node["kind"] for node in data["nodes"]})

    def test_direction_upstream_has_no_reports(self) -> None:
        measure = measure_analysis("M", "Total", records=[usage()])
        result = make_result(measures=[measure])
        data = build_lineage(
            result, kind="measure", table="M", name="Total", direction="upstream"
        )
        self.assertEqual(
            {node["kind"] for node in data["nodes"]}, {"measure"}
        )
        self.assertEqual(data["edges"], [])

    def test_depth_limits_pages_and_visuals(self) -> None:
        measure = measure_analysis("M", "Total", records=[usage()])
        result = make_result(measures=[measure])
        data = build_lineage(
            result, kind="measure", table="M", name="Total", depth=1
        )
        kinds = {node["kind"] for node in data["nodes"]}
        self.assertEqual(kinds, {"measure", "report"})

    def test_max_nodes_reports_truncation(self) -> None:
        columns = [
            column_analysis(
                "T",
                f"C{index}",
                refs=[
                    ModelReference(
                        kind="measure",
                        object="'M'[Total]",
                        detail="measure",
                    )
                ],
            )
            for index in range(40)
        ]
        measure = measure_analysis("M", "Total")
        result = make_result(columns=columns, measures=[measure])
        data = build_lineage(
            result, kind="measure", table="M", name="Total", max_nodes=25
        )
        self.assertLessEqual(len(data["nodes"]), 25)
        self.assertGreater(data["truncated"], 0)
        self.assertIn("truncated", [item["code"] for item in data["notices"]])

    def test_cycles_are_safe(self) -> None:
        first = measure_analysis(
            "M",
            "A",
            refs=[ModelReference(kind="measure", object="'M'[B]", detail="")],
        )
        second = measure_analysis(
            "M",
            "B",
            refs=[ModelReference(kind="measure", object="'M'[A]", detail="")],
        )
        result = make_result(measures=[first, second])
        data = build_lineage(result, kind="measure", table="M", name="A")
        ids = [node["id"] for node in data["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertIn(("measure:M:B", "measure:M:A"), edges)

    def test_m_steps_and_datasource(self) -> None:
        expression = """
let
    Source = Sql.Database("server", "db"),
    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data],
    #"Removed Other Columns" = Table.SelectColumns(dbo_Sales, {"Amount", "Qty"}),
    #"Renamed Columns" = Table.RenameColumns(#"Removed Other Columns", {{"Amount", "Total Amount"}})
in
    #"Renamed Columns"
"""
        amount = column_analysis("Sales", "Total Amount")
        result = make_result(
            columns=[amount],
            m_queries=[
                {
                    "name": "Sales",
                    "kind": "Tabel",
                    "source": "Import",
                    "expression": expression,
                }
            ],
        )
        data = build_lineage(
            result, kind="column", table="Sales", name="Total Amount"
        )
        nodes = {node["id"]: node for node in data["nodes"]}
        steps = [node for node in data["nodes"] if node["kind"] == "mstep"]
        self.assertGreaterEqual(len(steps), 2)
        self.assertIn("mquery:Sales", nodes)
        datasource = next(
            node for node in data["nodes"] if node["kind"] == "datasource"
        )
        self.assertEqual(datasource["label"], "dbo.Sales")
        self.assertEqual(datasource["context"], "sql")
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertNotIn(("mquery:Sales", "col:Sales:Total Amount"), edges)
        self.assertIn((datasource["id"], "mquery:Sales"), edges)
        ordered_steps = sorted(steps, key=lambda node: node["column"])
        self.assertTrue(
            any(edge[0] == "mquery:Sales" for edge in edges)
        )
        self.assertIn(
            (ordered_steps[-1]["id"], "col:Sales:Total Amount"),
            edges,
        )
        self.assertTrue(
            any("Removed Other Columns" in step["label"] for step in steps)
        )

    def test_outline_has_upstream_and_report_tree(self) -> None:
        base = measure_analysis(
            "M",
            "Base",
            refs=[ModelReference(kind="measure", object="'M'[Calc]", detail="")],
        )
        calc = measure_analysis(
            "M",
            "Calc",
            records=[usage(title="Sales by Month")],
        )
        result = make_result(measures=[base, calc])
        data = build_lineage(result, kind="measure", table="M", name="Calc")
        outline = data["outline"]
        self.assertEqual(outline["upstream"][0]["id"], "measure:M:Base")
        report = outline["downstream"][0]
        self.assertEqual(report["kind"], "report")
        self.assertEqual(report["children"][0]["kind"], "page")
        self.assertEqual(report["children"][0]["children"][0]["kind"], "visual")

    def test_category_filters_nodes(self) -> None:
        column = column_analysis(
            "T",
            "C",
            refs=[
                ModelReference(kind="relationship", object="'D'[Id]", detail=""),
                ModelReference(kind="sort by", object="'T'[Code]", detail=""),
                ModelReference(
                    kind="measure", object="'M'[Total]", detail="", blocking=False
                ),
            ],
            records=[usage()],
        )
        measure = measure_analysis("M", "Total")
        result = make_result(columns=[column], measures=[measure])

        related = build_lineage(
            result, kind="column", table="T", name="C", category="relationships"
        )
        self.assertEqual(
            {node["kind"] for node in related["nodes"]},
            {"column", "relationship"},
        )
        report_only = build_lineage(
            result, kind="column", table="T", name="C", category="reports"
        )
        self.assertEqual(
            {node["kind"] for node in report_only["nodes"]},
            {"column", "report", "page", "visual"},
        )
        self.assertTrue(report_only["edges"])
        with self.assertRaises(ValueError):
            build_lineage(
                result, kind="column", table="T", name="C", category="ngawur"
            )

    def test_m_split_column_steps(self) -> None:
        expression = """
let
    Source = Sql.Database("server", "db"),
    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data],
    #"Split Column" = Table.SplitColumn(dbo_Sales, "Dealer",
        Splitter.SplitTextByDelimiter("-"), {"Code", "Name"}),
    #"Renamed Columns" = Table.RenameColumns(#"Split Column", {"Name", "Dealer Name"})
in
    #"Renamed Columns"
"""
        column = column_analysis("Sales", "Dealer Name")
        result = make_result(
            columns=[column],
            m_queries=[
                {
                    "name": "Sales",
                    "kind": "Tabel",
                    "source": "Import",
                    "expression": expression,
                }
            ],
        )
        data = build_lineage(
            result, kind="column", table="Sales", name="Dealer Name"
        )
        labels = [
            node["label"] for node in data["nodes"] if node["kind"] == "mstep"
        ]
        self.assertIn("Split Column", labels)
        self.assertIn("Renamed Columns", labels)
        meta = data["m_lineage"]
        self.assertEqual(meta["status"], "complete")
        self.assertEqual(meta["warnings"], [])

    def test_m_transform_columns_is_partial(self) -> None:
        expression = """
let
    Source = Sql.Database("server", "db"),
    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data],
    #"Transformed Columns" = Table.TransformColumns(
        dbo_Sales, {{"Amount", each _ * 2, type number}})
in
    #"Transformed Columns"
"""
        column = column_analysis("Sales", "Amount")
        result = make_result(
            columns=[column],
            m_queries=[
                {
                    "name": "Sales",
                    "kind": "Tabel",
                    "source": "Import",
                    "expression": expression,
                }
            ],
        )
        data = build_lineage(result, kind="column", table="Sales", name="Amount")
        meta = data["m_lineage"]
        self.assertEqual(meta["status"], "partial")
        self.assertTrue(
            any(item["status"] == "transform_columns" for item in meta["warnings"])
        )
        self.assertIn("TransformColumns", meta["reason"])
        labels = [
            node["label"] for node in data["nodes"] if node["kind"] == "mstep"
        ]
        self.assertIn("Transformed Columns", labels)

    def test_m_single_pair_rename(self) -> None:
        expression = """
let
    Source = Sql.Database("server", "db"),
    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data],
    #"Renamed" = Table.RenameColumns(dbo_Sales, {"Old", "New"})
in
    #"Renamed"
"""
        column = column_analysis("Sales", "New")
        result = make_result(
            columns=[column],
            m_queries=[
                {
                    "name": "Sales",
                    "kind": "Tabel",
                    "source": "Import",
                    "expression": expression,
                }
            ],
        )
        data = build_lineage(result, kind="column", table="Sales", name="New")
        self.assertEqual(data["m_lineage"]["status"], "complete")
        self.assertTrue(
            any(
                node["kind"] == "mstep" and node["label"] == "Renamed"
                for node in data["nodes"]
            )
        )

    def test_layout_is_deterministic_and_spaced(self) -> None:
        measure = measure_analysis(
            "M",
            "Total",
            records=[usage(visual="V1"), usage(visual="V2")],
        )
        result = make_result(measures=[measure])
        first = build_lineage(result, kind="measure", table="M", name="Total")
        second = build_lineage(result, kind="measure", table="M", name="Total")
        self.assertEqual(first["nodes"], second["nodes"])
        self.assertEqual(first["edges"], second["edges"])

        by_column: dict[int, list[dict]] = {}
        for node in first["nodes"]:
            by_column.setdefault(node["column"], []).append(node)
        for items in by_column.values():
            ordered = sorted(items, key=lambda node: node["y"])
            for previous, current in zip(ordered, ordered[1:]):
                self.assertGreaterEqual(current["y"], previous["y"] + previous["h"])
        self.assertGreater(first["width"], 0)
        self.assertGreater(first["height"], 0)


if __name__ == "__main__":
    unittest.main()
