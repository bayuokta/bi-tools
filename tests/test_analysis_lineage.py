"""Uji builder lineage kolom/measure (tanpa XMLA, REST, atau SQLite)."""

from __future__ import annotations

import unittest

from core.analysis_lineage import MAX_USAGE_PER_PAGE, build_lineage, build_table_lineage
from core.column_stats import ColumnStat, MeasureStat, ModelStats, TableStat
from core.m_lineage import build_lineage as build_m_lineage
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
    order: int = 0,
) -> dict:
    return {
        "report_id": report,
        "report_name": report,
        "page_id": page,
        "page_name": page,
        "page_order": order,
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
        self.assertEqual(visual["group_id"], page["id"])
        self.assertEqual(visual["container_id"], "artifact:" + report["id"])
        self.assertEqual(page["role"], "group-head")
        self.assertLess(page["y"], visual["y"])

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
        self.assertEqual(
            sorted(step["step"] for step in steps),
            list(range(1, len(steps) + 1)),
        )
        source = next(
            artifact for artifact in data["artifacts"]
            if artifact["id"] == datasource["container_id"]
        )
        self.assertEqual(source["kind"], "datasource")
        mquery_group = next(
            group for group in data["groups"] if group["kind"] == "mquery"
        )
        self.assertEqual(mquery_group["label"], "Sales")
        self.assertEqual(nodes["mquery:Sales"]["role"], "group-head")
        self.assertEqual(nodes["mquery:Sales"]["group_id"], mquery_group["id"])
        seed = nodes["col:Sales:Total Amount"]
        self.assertEqual(seed["group_id"], mquery_group["id"])
        self.assertNotIn("step", seed)
        self.assertTrue(
            all(
                node["group_id"] == mquery_group["id"]
                for node in data["nodes"]
                if node["kind"] in {"mquery", "mstep"}
            )
        )

    def test_outline_collapses_m_steps_but_keeps_mquery_and_datasource(self) -> None:
        expression = """
let
    Source = Sql.Database("server", "db"),
    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data],
    #"Removed Other Columns" = Table.SelectColumns(dbo_Sales, {"Amount"}),
    #"Renamed Columns" = Table.RenameColumns(#"Removed Other Columns", {{"Amount", "Total Amount"}})
in
    #"Renamed Columns"
"""
        data = build_lineage(
            make_result(
                columns=[column_analysis("Sales", "Total Amount")],
                m_queries=[
                    {
                        "name": "Sales",
                        "kind": "Tabel",
                        "source": "Import",
                        "expression": expression,
                    }
                ],
            ),
            kind="column",
            table="Sales",
            name="Total Amount",
        )
        upstream: list[dict] = []

        def walk(items: list[dict]) -> None:
            for item in items:
                upstream.append(item)
                walk(item.get("children") or [])

        walk(data["outline"]["upstream"])
        kinds = {item["kind"] for item in upstream}
        self.assertNotIn("mstep", kinds)
        self.assertIn("mquery", kinds)
        self.assertIn("datasource", kinds)
        self.assertTrue(any(item["label"] == "dbo.Sales" for item in upstream))

    def test_mquery_without_steps_becomes_model_card(self) -> None:
        result = make_result(
            columns=[column_analysis("Sales", "Amount")],
            m_queries=[
                {"name": "Sales", "kind": "Tabel", "source": "Import"}
            ],
        )
        data = build_lineage(result, kind="column", table="Sales", name="Amount")
        nodes = {node["id"]: node for node in data["nodes"]}
        self.assertFalse(
            any(group["kind"] == "mquery" for group in data["groups"])
        )
        self.assertEqual(nodes["mquery:Sales"]["role"], "card")
        self.assertEqual(nodes["mquery:Sales"]["group_id"], "model")

    def test_grouped_layout_artifacts_and_groups(self) -> None:
        base = measure_analysis("M", "Base")
        calc = measure_analysis(
            "M",
            "Calc",
            refs=[
                ModelReference(
                    kind="measure",
                    object="'M'[Base]",
                    detail="dipakai measure",
                    blocking=False,
                    source_table="M",
                    source_measure="Base",
                )
            ],
            records=[
                usage(report="R1", page="P1", visual="V1"),
                usage(report="R1", page="P2", visual="V2"),
                usage(report="R2", page="P3", visual="V3"),
            ],
        )
        data = build_lineage(
            make_result(measures=[base, calc]),
            kind="measure",
            table="M",
            name="Calc",
        )

        artifacts = {artifact["id"]: artifact for artifact in data["artifacts"]}
        groups = {group["id"]: group for group in data["groups"]}
        self.assertIn("artifact:model", artifacts)
        reports = [
            artifact for artifact in data["artifacts"]
            if artifact["kind"] == "report"
        ]
        self.assertEqual(len(reports), 2)

        model = artifacts["artifact:model"]
        model_groups = [
            group for group in data["groups"]
            if group["container"] == model["id"]
        ]
        self.assertEqual([group["kind"] for group in model_groups], ["model"])
        for report in reports:
            page_groups = [
                group for group in data["groups"]
                if group["container"] == report["id"]
            ]
            self.assertTrue(page_groups)
            self.assertTrue(
                all(group["kind"] == "page" for group in page_groups)
            )

        def inside(inner: dict, outer: dict) -> bool:
            return (
                inner["x"] >= outer["x"]
                and inner["y"] >= outer["y"]
                and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
                and inner["y"] + inner["h"] <= outer["y"] + outer["h"]
            )

        for group in data["groups"]:
            self.assertTrue(inside(group, artifacts[group["container"]]))
        for node in data["nodes"]:
            self.assertIn("container_id", node)
            if node["role"] != "card":
                continue
            self.assertTrue(inside(node, groups[node["group_id"]]))

        cards = [node for node in data["nodes"] if node["role"] == "card"]
        for index, first in enumerate(cards):
            for second in cards[index + 1:]:
                overlap = (
                    first["x"] < second["x"] + second["w"]
                    and second["x"] < first["x"] + first["w"]
                    and first["y"] < second["y"] + second["h"]
                    and second["y"] < first["y"] + first["h"]
                )
                self.assertFalse(overlap, f"{first['id']} vs {second['id']}")

    def test_canvas_edges_collapse_report_and_page(self) -> None:
        calc = measure_analysis(
            "M",
            "Calc",
            records=[
                usage(report="R1", page="P1", visual="V1", detail="Values"),
                usage(report="R1", page="P2", visual="V2", detail="Rows"),
            ],
        )
        data = build_lineage(
            make_result(measures=[calc]), kind="measure", table="M", name="Calc"
        )
        canvas = {
            (edge["from"], edge["to"], edge["kind"])
            for edge in data["canvas_edges"]
        }
        visuals = {
            node["id"]: node["label"]
            for node in data["nodes"]
            if node["kind"] == "visual"
        }
        self.assertEqual(len(canvas), 2)
        for source, target, kind in canvas:
            self.assertEqual(source, "measure:M:Calc")
            self.assertIn(target, visuals)
            self.assertEqual(kind, "visual")
        for edge in data["canvas_edges"]:
            self.assertNotIn(edge["to"], {
                node["id"] for node in data["nodes"]
                if node["kind"] in {"report", "page"}
            })
        semantic = {
            (edge["from"], edge["to"]) for edge in data["edges"]
        }
        self.assertIn(("measure:M:Calc", next(
            node["id"] for node in data["nodes"] if node["kind"] == "report"
        )), semantic)

    def test_pages_single_column_and_reports_side_by_side(self) -> None:
        records = [
            usage(page=f"P{index}", visual=f"V{index}")
            for index in range(1, 7)
        ]
        calc = measure_analysis("M", "Calc", records=records)
        data = build_lineage(
            make_result(measures=[calc]), kind="measure", table="M", name="Calc"
        )
        page_groups = [
            group for group in data["groups"] if group["kind"] == "page"
        ]
        self.assertEqual(len(page_groups), 6)
        self.assertEqual(len({group["x"] for group in page_groups}), 1)
        report = next(
            artifact for artifact in data["artifacts"]
            if artifact["kind"] == "report"
        )
        for group in page_groups:
            self.assertGreaterEqual(group["y"], report["y"])
            self.assertLessEqual(
                group["y"] + group["h"], report["y"] + report["h"]
            )
        ordered = sorted(page_groups, key=lambda group: group["y"])
        self.assertEqual(
            [group["label"] for group in ordered],
            [f"P{index}" for index in range(1, 7)],
        )

        # Dua report berdampingan, bukan ditumpuk.
        first = measure_analysis(
            "M",
            "First",
            refs=[
                ModelReference(
                    kind="measure",
                    object="'M'[Second]",
                    detail="",
                    blocking=False,
                    source_table="M",
                    source_measure="Second",
                )
            ],
            records=[usage(report="R1", page="A1")],
        )
        second = measure_analysis(
            "M", "Second", records=[usage(report="R2", page="B1")]
        )
        data = build_lineage(
            make_result(measures=[first, second]),
            kind="measure",
            table="M",
            name="First",
        )
        reports = sorted(
            (
                artifact for artifact in data["artifacts"]
                if artifact["kind"] == "report"
            ),
            key=lambda artifact: artifact["x"],
        )
        self.assertEqual(len(reports), 2)
        self.assertEqual({artifact["y"] for artifact in reports}, {reports[0]["y"]})
        self.assertLess(reports[0]["x"] + reports[0]["w"], reports[1]["x"])

    def test_page_order_uses_report_order(self) -> None:
        records = [
            usage(page="Z", visual="VZ", order=3),
            usage(page="A", visual="VA", order=1),
            usage(page="M", visual="VM", order=2),
        ]
        data = build_lineage(
            make_result(
                measures=[measure_analysis("M", "Ordered", records=records)]
            ),
            kind="measure",
            table="M",
            name="Ordered",
        )
        page_groups = sorted(
            (
                group for group in data["groups"]
                if group["kind"] == "page"
            ),
            key=lambda group: group["y"],
        )
        self.assertEqual(
            [group["label"] for group in page_groups], ["A", "M", "Z"]
        )

    def test_canvas_edges_are_collapsed_when_dense(self) -> None:
        def edges_for(measures, max_nodes=250):
            data = build_lineage(
                make_result(measures=measures),
                kind="measure",
                table="M",
                name=measures[0].measure.measure,
                max_nodes=max_nodes,
            )
            notice = next(
                (
                    item for item in data["notices"]
                    if item.get("code") == "edges_collapsed"
                ),
                {},
            )
            return data, str(notice.get("level") or "usage")

        # 3 measure x 7 halaman x 8 visual = 168 edge langsung -> level page.
        medium = []
        for index in range(3):
            refs = []
            if index < 2:
                refs = [
                    ModelReference(
                        kind="measure",
                        object=f"'M'[M{index + 1}]",
                        detail="",
                        blocking=False,
                        source_table="M",
                        source_measure=f"M{index + 1}",
                    )
                ]
            records = [
                usage(page=f"P{page}", visual=f"{index}-{page}-{visual}")
                for page in range(7)
                for visual in range(8)
            ]
            medium.append(
                measure_analysis("M", f"M{index}", refs=refs, records=records)
            )
        data, level = edges_for(medium)
        self.assertEqual(level, "page")
        targets = {edge["to"] for edge in data["canvas_edges"]}
        page_ids = {
            node["id"] for node in data["nodes"] if node["kind"] == "page"
        }
        self.assertTrue(targets.issubset(
            page_ids
            | {
                node["id"] for node in data["nodes"]
                if node["kind"] not in {"visual", "filter", "sort", "usage", "more"}
            }
        ))

        # 25 measure x 10 halaman = 250 edge halaman -> level report.
        dense = []
        for index in range(25):
            records = [
                usage(page=f"Q{page}", visual=f"{index}-{page}")
                for page in range(10)
            ]
            dense.append(
                measure_analysis("M", f"N{index}", records=records)
            )
        dense[0] = measure_analysis(
            "M",
            "N0",
            refs=[
                ModelReference(
                    kind="measure",
                    object=f"'M'[N{index}]",
                    detail="",
                    blocking=False,
                    source_table="M",
                    source_measure=f"N{index}",
                )
                for index in range(1, 25)
            ],
            records=[
                usage(page=f"Q{page}", visual=f"0-{page}")
                for page in range(10)
            ],
        )
        data, level = edges_for(dense, max_nodes=400)
        self.assertEqual(level, "report")
        report_ids = {
            node["id"] for node in data["nodes"] if node["kind"] == "report"
        }
        targets = {edge["to"] for edge in data["canvas_edges"]}
        self.assertTrue(report_ids & targets)
        self.assertFalse(
            any(target.startswith(("usage:", "page:")) for target in targets)
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

    def test_table_lineage_builds_columns_measures_and_reports(self) -> None:
        amount = column_analysis(
            "Sales",
            "Amount",
            refs=[
                ModelReference(
                    kind="measure",
                    object="'KPI'[Total]",
                    detail="measure 'KPI'[Total]",
                    blocking=False,
                )
            ],
        )
        qty = column_analysis("Sales", "Qty")
        measure = measure_analysis("KPI", "Total", records=[usage()])
        result = make_result(columns=[amount, qty], measures=[measure])
        data = build_table_lineage(result, table="Sales")
        kinds = {node["kind"] for node in data["nodes"]}
        self.assertEqual(data["seed"]["kind"], "table")
        self.assertIn("column", kinds)
        self.assertIn("measure", kinds)
        self.assertIn("report", kinds)
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertIn(("table:Sales", "col:Sales:Amount"), edges)
        self.assertIn(("col:Sales:Amount", "measure:KPI:Total"), edges)
        self.assertIn(("table:Sales", "col:Sales:Qty"), edges)
        self.assertIn(
            "artifact:model",
            {artifact["id"] for artifact in data["artifacts"]},
        )
        self.assertIn("model", {group["id"] for group in data["groups"]})
        seed = next(node for node in data["nodes"] if node["kind"] == "table")
        self.assertEqual(seed["group_id"], "model")
        self.assertEqual(seed["container_id"], "artifact:model")

    def test_table_lineage_accepts_mquery_only_table(self) -> None:
        result = make_result(
            columns=[],
            m_queries=[{"name": "Sales", "kind": "Tabel", "source": "Import"}],
        )
        data = build_table_lineage(result, table="Sales")
        self.assertEqual(
            {node["kind"] for node in data["nodes"]}, {"table", "mquery"}
        )
        self.assertEqual(data["m_lineage"]["status"], "unavailable")
        with self.assertRaises(ValueError):
            build_table_lineage(result, table="TidakAda")
        with self.assertRaises(ValueError):
            build_table_lineage(result, table="Sales", outline_mode="ngawur")

    def test_outline_full_expands_repeated_nodes(self) -> None:
        column = column_analysis(
            "Sales",
            "Amount",
            refs=[
                ModelReference(
                    kind="measure", object="'KPI'[First]", detail="", blocking=False
                ),
                ModelReference(
                    kind="measure", object="'KPI'[Second]", detail="", blocking=False
                ),
            ],
        )
        first = measure_analysis("KPI", "First", records=[usage(report="R1")])
        second = measure_analysis("KPI", "Second", records=[usage(report="R1")])
        result = make_result(columns=[column], measures=[first, second])
        compact = build_lineage(
            result, kind="column", table="Sales", name="Amount"
        )
        full = build_lineage(
            result,
            kind="column",
            table="Sales",
            name="Amount",
            outline_mode="full",
        )

        def reports(outline):
            found = []
            stack = list(outline["downstream"])
            while stack:
                item = stack.pop()
                if item["kind"] == "report":
                    found.append(item)
                stack.extend(item.get("children") or [])
            return found

        compact_reports = reports(compact["outline"])
        full_reports = reports(full["outline"])
        self.assertTrue(any(item["children"] for item in compact_reports))
        self.assertTrue(
            any(item.get("repeat") and not item["children"] for item in compact_reports)
        )
        self.assertEqual(len(full_reports), 2)
        self.assertTrue(all(item["children"] for item in full_reports))

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

    def test_outline_items_carry_visual_usage_details(self) -> None:
        records = [
            usage(
                report="R1",
                page="P1",
                visual="V1",
                title="Trend KK",
                usage_kind="field",
                detail="Values",
            ),
            usage(
                report="R1",
                page="P1",
                visual="V2",
                title="Trend filter",
                usage_kind="filter-visual",
                detail="Advanced",
            ),
        ]
        data = build_lineage(
            make_result(measures=[measure_analysis("M", "Calc", records=records)]),
            kind="measure",
            table="M",
            name="Calc",
        )
        items: list[dict] = []

        def walk(nodes: list[dict]) -> None:
            for node in nodes or []:
                items.append(node)
                walk(node.get("children") or [])

        walk(data["outline"]["downstream"])
        visual = next(
            node for node in items
            if node["kind"] == "visual" and node["usage_kind"] == "field"
        )
        filter_item = next(
            node for node in items
            if node["kind"] == "filter" and node["usage_kind"] == "filter-visual"
        )
        self.assertEqual(visual["detail"], "Values")
        self.assertEqual(visual["visual_type"], "tableEx")
        self.assertEqual(filter_item["detail"], "Advanced")
        self.assertEqual(filter_item["visual_title"], "Trend filter")

    def test_tree_layout_centers_parent_between_children(self) -> None:
        def consumer(name: str) -> ModelReference:
            return ModelReference(
                kind="measure",
                object=f"'M'[{name}]",
                detail="",
                blocking=False,
            )

        calc = measure_analysis(
            "M",
            "Calc",
            refs=[consumer("Left"), consumer("Right")],
        )
        left = measure_analysis("M", "Left")
        right = measure_analysis("M", "Right")
        data = build_lineage(
            make_result(measures=[calc, left, right]),
            kind="measure",
            table="M",
            name="Calc",
        )
        nodes = {node["id"]: node for node in data["nodes"]}
        seed = nodes["measure:M:Calc"]
        children = [nodes["measure:M:Left"], nodes["measure:M:Right"]]
        self.assertEqual(seed["column"], 0)
        self.assertEqual(children[0]["column"], 1)
        self.assertEqual(children[1]["column"], 1)
        self.assertNotEqual(children[0]["y"], children[1]["y"])
        center = sum(node["y"] for node in children) / len(children)
        self.assertLessEqual(abs(seed["y"] - center), 2)

    def test_measure_upstream_columns_get_m_chains(self) -> None:
        expression = """
let
    Source = Sql.Database("server", "db"),
    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data],
    #"Renamed Columns" = Table.RenameColumns(
        dbo_Sales, {{"Amount", "Total Amount"}, {"Qty", "Quantity"}}
    )
in
    #"Renamed Columns"
"""
        calc = measure_analysis("M", "Calc")
        refs = [
            ModelReference(
                kind="measure",
                object="'M'[Calc]",
                detail="",
                blocking=False,
            )
        ]
        amount = column_analysis("Sales", "Total Amount", refs=refs)
        quantity = column_analysis("Sales", "Quantity", refs=refs)
        data = build_lineage(
            make_result(
                columns=[amount, quantity],
                measures=[calc],
                m_queries=[
                    {
                        "name": "Sales",
                        "kind": "Tabel",
                        "source": "Import",
                        "expression": expression,
                    }
                ],
            ),
            kind="measure",
            table="M",
            name="Calc",
        )
        nodes = {node["id"]: node for node in data["nodes"]}
        m_groups = [group for group in data["groups"] if group["kind"] == "mquery"]
        self.assertEqual(len(m_groups), 1)
        group = m_groups[0]
        self.assertEqual(group["label"], "Sales")
        outputs = [nodes["col:Sales:Total Amount"], nodes["col:Sales:Quantity"]]
        for output in outputs:
            self.assertEqual(output["group_id"], group["id"])
            self.assertIn(output["id"], group["members"])
        self.assertNotEqual(outputs[0]["y"], outputs[1]["y"])
        for node in data["nodes"]:
            if node["kind"] == "mstep":
                self.assertGreaterEqual(int(node.get("step") or 0), 1)
        self.assertEqual(
            nodes["measure:M:Calc"]["group_id"],
            "model",
        )
        self.assertNotIn("measure:M:Calc", group["members"])

    def test_m_columns_truncated_notice(self) -> None:
        expression = """
let
    Source = Sql.Database("server", "db"),
    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data],
    #"Renamed Columns" = Table.RenameColumns(
        dbo_Sales,
        {{"A", "Col A"}, {"B", "Col B"}, {"C", "Col C"}, {"D", "Col D"}}
    )
in
    #"Renamed Columns"
"""
        calc = measure_analysis("M", "Calc")
        refs = [
            ModelReference(
                kind="measure",
                object="'M'[Calc]",
                detail="",
                blocking=False,
            )
        ]
        columns = [
            column_analysis("Sales", name, refs=refs)
            for name in ("Col A", "Col B", "Col C", "Col D")
        ]
        data = build_lineage(
            make_result(
                columns=columns,
                measures=[calc],
                m_queries=[
                    {
                        "name": "Sales",
                        "kind": "Tabel",
                        "source": "Import",
                        "expression": expression,
                    }
                ],
            ),
            kind="measure",
            table="M",
            name="Calc",
        )
        notice = next(
            (
                item for item in data["notices"]
                if item.get("code") == "m_columns_truncated"
            ),
            None,
        )
        self.assertIsNotNone(notice)
        self.assertEqual(notice["count"], 1)

    def test_tree_edges_connect_report_pages_and_visuals(self) -> None:
        records = [
            usage(report="R1", page="P1", visual="V1"),
            usage(report="R1", page="P1", visual="V2"),
            usage(report="R1", page="P2", visual="V3"),
        ]
        data = build_lineage(
            make_result(measures=[measure_analysis("M", "Calc", records=records)]),
            kind="measure",
            table="M",
            name="Calc",
        )
        report = next(node for node in data["nodes"] if node["kind"] == "report")
        pages = [
            group for group in data["groups"] if group["kind"] == "page"
        ]
        self.assertEqual(len(pages), 2)
        tree = {(edge["from"], edge["to"]) for edge in data["tree_edges"]}
        for page in pages:
            self.assertIn((report["id"], page["head_id"]), tree)
            visuals = [
                node["id"] for node in data["nodes"]
                if node["group_id"] == page["id"] and node["role"] == "card"
            ]
            self.assertTrue(visuals)
            for visual_id in visuals:
                self.assertIn((page["head_id"], visual_id), tree)
        self.assertTrue(all(edge["kind"] == "tree" for edge in data["tree_edges"]))

    def test_tree_edges_connect_mquery_head_to_steps(self) -> None:
        expression = """
let
    Source = Sql.Database("server", "db"),
    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data],
    #"Renamed Columns" = Table.RenameColumns(dbo_Sales, {{"Amount", "Total"}})
in
    #"Renamed Columns"
"""
        result = make_result(
            columns=[column_analysis("Sales", "Total")],
            m_queries=[
                {
                    "name": "Sales",
                    "kind": "Tabel",
                    "source": "Import",
                    "expression": expression,
                }
            ],
        )
        data = build_lineage(result, kind="column", table="Sales", name="Total")
        group = next(
            group for group in data["groups"] if group["kind"] == "mquery"
        )
        steps = [
            node["id"] for node in data["nodes"]
            if node["kind"] == "mstep" and node["group_id"] == group["id"]
        ]
        self.assertTrue(steps)
        tree = {(edge["from"], edge["to"]) for edge in data["tree_edges"]}
        targets = {
            to for (frm, to) in tree if frm == group["head_id"]
        }
        self.assertTrue(targets)
        self.assertTrue(targets.issubset(set(steps)))

    def test_transitive_reference_does_not_create_direct_edge(self) -> None:
        def measure_ref(name: str, *, depth: int) -> ModelReference:
            return ModelReference(
                kind="measure",
                object=f"'_Measures'[{name}]",
                detail=f"measure '{name}' (kedalaman {depth})",
                blocking=False,
                depth=depth,
            )

        engine = column_analysis(
            "OCRKK",
            "Engine No",
            refs=[
                measure_ref("# Unit", depth=1),
                measure_ref("# KK", depth=2),
            ],
        )
        status = column_analysis(
            "OCRKK",
            "Status Kartu Keluarga",
            refs=[measure_ref("# KK", depth=1)],
        )
        unit = measure_analysis(
            "_Measures",
            "# Unit",
            refs=[
                ModelReference(
                    kind="measure",
                    object="'_Measures'[# KK]",
                    detail="measure '# KK' (kedalaman 1)",
                    blocking=False,
                    depth=1,
                )
            ],
        )
        target = measure_analysis("_Measures", "# KK")
        data = build_lineage(
            make_result(columns=[engine, status], measures=[unit, target]),
            kind="measure",
            table="_Measures",
            name="# KK",
        )
        edges = {(edge["from"], edge["to"]) for edge in data["edges"]}
        self.assertIn(("col:OCRKK:Engine No", "measure:_Measures:# Unit"), edges)
        self.assertIn(
            ("measure:_Measures:# Unit", "measure:_Measures:# KK"), edges
        )
        self.assertIn(
            ("col:OCRKK:Status Kartu Keluarga", "measure:_Measures:# KK"),
            edges,
        )
        self.assertNotIn(
            ("col:OCRKK:Engine No", "measure:_Measures:# KK"), edges
        )

    def test_highlight_edges_keep_direct_visuals_when_dense(self) -> None:
        records = [
            usage(page=f"P{page}", visual=f"{page}-{visual}")
            for page in range(25)
            for visual in range(10)
        ]
        calc = measure_analysis("M", "Calc", records=records)
        data = build_lineage(
            make_result(measures=[calc]), kind="measure", table="M", name="Calc"
        )
        level = next(
            (
                item.get("level")
                for item in data["notices"]
                if item.get("code") == "edges_collapsed"
            ),
            "",
        )
        self.assertEqual(level, "page")
        visual_ids = {
            node["id"] for node in data["nodes"] if node["kind"] == "visual"
        }
        page_ids = {
            node["id"] for node in data["nodes"] if node["kind"] == "page"
        }
        canvas_targets = {edge["to"] for edge in data["canvas_edges"]}
        self.assertTrue(canvas_targets.issubset(page_ids))
        highlight_targets = {
            edge["to"] for edge in data["highlight_edges"]
            if edge["kind"] == "visual"
        }
        self.assertTrue(highlight_targets.issubset(visual_ids))
        self.assertGreater(len(data["highlight_edges"]), len(data["canvas_edges"]))


class SourcePathTests(unittest.TestCase):
    """Path sumber per konektor: BigQuery, Snowflake, PostgreSQL, OData, SQL."""

    def test_bigquery_reads_project_dataset_table(self) -> None:
        text = (
            "let\n"
            "    Source = GoogleBigQuery.Database(null),\n"
            '    proj = Source{[Name="my-project"]}[Data],\n'
            '    ds = proj{[Name="sales_ds", Kind="Schema"]}[Data],\n'
            '    tbl = ds{[Name="orders", Kind="Table"]}[Data],\n'
            '    #"Renamed Columns" = Table.RenameColumns(tbl, {{"amount", "Total"}})\n'
            "in\n"
            '    #"Renamed Columns"'
        )
        parsed = build_m_lineage(text)

        self.assertEqual(parsed.origin, "bigquery")
        self.assertEqual(parsed.source_path, ["my-project", "sales_ds", "orders"])
        self.assertEqual(
            parsed.source_object, "my-project.sales_ds.orders"
        )
        self.assertIn("Total", parsed.columns)

    def test_snowflake_reads_database_schema_table(self) -> None:
        text = (
            "let\n"
            '    Source = Snowflake.Databases("acct", "WH"),\n'
            '    db = Source{[Name="ANALYTICS"]}[Data],\n'
            '    sch = db{[Name="PUBLIC", Kind="Schema"]}[Data],\n'
            '    tbl = sch{[Name="ORDERS", Kind="Table"]}[Data]\n'
            "in\n"
            "    tbl"
        )
        parsed = build_m_lineage(text)

        self.assertEqual(parsed.origin, "snowflake")
        self.assertEqual(parsed.source_path, ["ANALYTICS", "PUBLIC", "ORDERS"])

    def test_postgresql_keeps_origin_on_name_navigation(self) -> None:
        text = (
            "let\n"
            '    Source = PostgreSQL.Database("host", "db"),\n'
            '    public = Source{[Name="public"]}[Data],\n'
            '    orders = public{[Name="orders"]}[Data]\n'
            "in\n"
            "    orders"
        )
        parsed = build_m_lineage(text)

        self.assertEqual(parsed.origin, "postgresql")
        self.assertEqual(parsed.source_object, "public.orders")

    def test_sql_server_schema_item_unchanged(self) -> None:
        text = (
            "let\n"
            '    Source = Sql.Database("server", "db"),\n'
            '    dbo_Sales = Source{[Schema="dbo", Item="Sales"]}[Data]\n'
            "in\n"
            "    dbo_Sales"
        )
        parsed = build_m_lineage(text)

        self.assertEqual(parsed.origin, "sql")
        self.assertEqual(parsed.source_path, ["dbo", "Sales"])

    def test_odata_and_dataflow_keep_single_level(self) -> None:
        odata = build_m_lineage(
            "let\n"
            '    Source = OData.Feed("https://x/odata"),\n'
            '    Customers = Source{[Name="Customers"]}[Data]\n'
            "in\n"
            "    Customers"
        )
        dataflow = build_m_lineage(
            "let\n"
            "    Source = PowerPlatform.Dataflows(null),\n"
            '    ent = Source{[entity="Sales"]}[Data]\n'
            "in\n"
            "    ent"
        )

        self.assertEqual(odata.origin, "odata")
        self.assertEqual(odata.source_object, "Customers")
        self.assertEqual(dataflow.origin, "dataflow")
        self.assertEqual(dataflow.source_object, "Sales")

    def test_unknown_connector_does_not_invent_name(self) -> None:
        parsed = build_m_lineage(
            "let\n"
            '    Source = Contoso.Connector("x"),\n'
            '    T = Source{[Name="Thing"]}[Data]\n'
            "in\n"
            "    T"
        )

        self.assertEqual(parsed.origin, "table")
        self.assertEqual(parsed.source_object, "Thing")

    def test_datasource_node_uses_full_path(self) -> None:
        text = (
            "let\n"
            "    Source = GoogleBigQuery.Database(null),\n"
            '    proj = Source{[Name="my-project"]}[Data],\n'
            '    ds = proj{[Name="sales_ds", Kind="Schema"]}[Data],\n'
            '    tbl = ds{[Name="orders", Kind="Table"]}[Data]\n'
            "in\n"
            "    tbl"
        )
        data = build_lineage(
            make_result(
                columns=[column_analysis("orders", "amount")],
                m_queries=[
                    {
                        "name": "orders",
                        "kind": "Tabel",
                        "source": "Import",
                        "expression": text,
                    }
                ],
            ),
            kind="column",
            table="orders",
            name="amount",
        )
        node = next(
            node for node in data["nodes"] if node["kind"] == "datasource"
        )

        self.assertEqual(node["label"], "my-project.sales_ds.orders")
        self.assertEqual(node["context"], "bigquery")


if __name__ == "__main__":
    unittest.main()
