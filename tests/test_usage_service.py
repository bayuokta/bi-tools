"""Uji orkestrasi analisa semantic model (tanpa jaringan)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.api import ApiError
from core.auth import ServicePrincipal
from core.column_stats import ColumnStat, MeasureStat, ModelStats, TableStat
from core.errors import ExtractionError
from core.fabric_api import PBIR, DefinitionPart, ReportDefinition
from core.lineage_store import (
    close_quietly,
    connect,
    initialize as initialize_lineage,
    save_workspaces,
)
from core.model import LiveModel
from core.report_usage import ReportUsage, UsageRecord
from core.usage_service import (
    STATUS_BLOCKER,
    STATUS_UNKNOWN,
    STATUS_UNUSED,
    STATUS_USED,
    FORMAT_RDL,
    AnalysisResult,
    ColumnAnalysis,
    MeasureAnalysis,
    ModelReference,
    ReportEntry,
    ScanCounters,
    build_analysis,
    coverage_text,
    discover_reports,
    format_bytes,
    load_snapshot,
    measure_references,
    measure_rows,
    model_references,
    model_snapshot,
    m_query_rows,
    normalize_report_format,
    output_file_name,
    relationship_dependency_counts,
    scan_reports,
    verdict,
    write_workbook,
)
from core.usage_store import (
    field_usage,
    initialize,
    save_columns,
    save_m_queries,
    save_measures,
    save_model_refs,
    save_report,
    save_run,
    unresolved as stored_unresolved,
)
from tests.test_report_usage import definition as make_definition
from tests.test_report_usage import legacy_parts


def column(name: str, *, size: int = 1000) -> ColumnStat:
    return ColumnStat(
        table="Sales",
        column=name,
        column_id=1,
        column_type="data",
        data_type="string",
        format_string="",
        display_folder="",
        is_hidden=False,
        is_calculated=False,
        sort_by_column="",
        expression="",
        size_data_bytes=size,
        size_hierarchy_bytes=0,
        rows=10,
    )


def stats() -> ModelStats:
    return ModelStats(
        model_name="Model",
        compatibility_level=1600,
        last_update="2026-01-01",
        columns=[column("Customer"), column("Qty", size=2000)],
        tables=[TableStat("Sales", 2, 10, 3000, 0)],
        segment_bytes=3000,
        artifact_bytes=0,
        measures=[
            MeasureStat(table="Sales", measure="Total", expression="SUM(Sales[Qty])"),
            MeasureStat(table="Sales", measure="Helper", expression="[Total] * 2"),
            MeasureStat(table="Sales", measure="Orphan", expression="1"),
        ],
    )


def definition(*, prop: str = "Customer") -> ReportDefinition:
    payload = {
        "definition/pages/pages.json": {"pageOrder": ["p1"]},
        "definition/pages/p1/page.json": {"displayName": "Overview"},
        "definition/pages/p1/visuals/v1/visual.json": {
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
                                            "Property": prop,
                                        }
                                    },
                                    "queryRef": f"Sales.{prop}",
                                }
                            ]
                        }
                    }
                },
            }
        },
    }
    return ReportDefinition(
        report_format=PBIR,
        parts=tuple(
            DefinitionPart(path=path, payload=json.dumps(body).encode("utf-8"))
            for path, body in payload.items()
        ),
    )


class FormatTests(unittest.TestCase):
    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(2048), "2,0 KB")
        self.assertEqual(format_bytes(20 * 1024 * 1024), "20,0 MB")
        self.assertEqual(format_bytes(None), "0 B")

    def test_output_file_name(self) -> None:
        name = output_file_name('Uji: Data / Acquisition', "77777777-3906-4e65")

        self.assertEqual(name, "Analisa_Semantic_Model_Uji Data Acquisition_77777777.xlsx")

    def test_output_file_name_defaults(self) -> None:
        self.assertEqual(
            output_file_name("", ""), "Analisa_Semantic_Model_Semantic Model_.xlsx"
        )

    def test_coverage_text_mentions_personal_and_inaccessible(self) -> None:
        text = coverage_text(
            ScanCounters(
                total=6, scanned=2, personal=2, app=1, inaccessible=1
            )
        )

        self.assertIn("2 personal dilewati", text)
        self.assertIn("1 App dilewati", text)
        self.assertIn("1 tidak dapat diakses", text)


class FormatNormalizationTests(unittest.TestCase):
    def test_rest_and_fabric_labels_are_equivalent(self) -> None:
        from core.fabric_api import PBIR, PBIR_LEGACY

        self.assertEqual(normalize_report_format("PBIR"), PBIR)
        self.assertEqual(normalize_report_format("pbir"), PBIR)
        self.assertEqual(normalize_report_format("PBIRLegacy"), PBIR_LEGACY)
        self.assertEqual(normalize_report_format("PBIR-Legacy"), PBIR_LEGACY)
        self.assertEqual(normalize_report_format("pbir_legacy"), PBIR_LEGACY)
        self.assertEqual(normalize_report_format("PaginatedReport"), FORMAT_RDL)
        self.assertEqual(normalize_report_format("RDL"), FORMAT_RDL)
        self.assertEqual(normalize_report_format(""), "")
        self.assertEqual(normalize_report_format(None), "")

    def test_app_report_detection_ignores_zero_width(self) -> None:
        app = ReportEntry(
            report_id="r-app",
            name="[App] Report Summary Prospect\u200b",
            workspace_id="ws",
            report_format="PBIR",
        )
        normal = ReportEntry(
            report_id="r1",
            name="Report Summary Prospect",
            workspace_id="ws",
            report_format="PBIR",
        )

        self.assertTrue(app.is_app)
        self.assertFalse(normal.is_app)

    def test_legacy_label_is_supported_rdl_is_not(self) -> None:
        legacy = ReportEntry(
            report_id="r1",
            name="Legacy",
            workspace_id="ws",
            report_format="PBIRLegacy",
        )
        rdl = ReportEntry(
            report_id="r2",
            name="Paginated",
            workspace_id="ws",
            report_format=FORMAT_RDL,
        )
        unknown = ReportEntry(
            report_id="r3", name="Unknown", workspace_id="ws", report_format=""
        )

        self.assertTrue(legacy.supported)
        self.assertFalse(rdl.supported)
        self.assertTrue(unknown.supported)


class VerdictTests(unittest.TestCase):
    def test_blocking_model_reference(self) -> None:
        refs = [ModelReference("relationship", "'T'[C]", "relasi", blocking=True)]
        status, reason = verdict(column("Customer"), refs, [], coverage_complete=True)

        self.assertEqual(status, STATUS_BLOCKER)
        self.assertIn("relationship", reason)

    def test_report_usage(self) -> None:
        records = [{"report_id": "r1"}, {"report_id": "r1"}, {"report_id": "r2"}]
        status, reason = verdict(column("Customer"), [], records, coverage_complete=True)

        self.assertEqual(status, STATUS_USED)
        self.assertIn("3 titik", reason)
        self.assertIn("2 report", reason)

    def test_measure_only_usage_is_not_blocking(self) -> None:
        refs = [ModelReference("measure", "'Sales'[Total]", "measure", blocking=False)]
        status, _reason = verdict(column("Qty"), refs, [], coverage_complete=True)

        self.assertEqual(status, STATUS_USED)

    def test_incomplete_coverage_never_says_unused(self) -> None:
        status, reason = verdict(column("Customer"), [], [], coverage_complete=False)

        self.assertEqual(status, STATUS_UNKNOWN)
        self.assertIn("cakupan", reason)

    def test_clean_column_is_unused(self) -> None:
        status, _reason = verdict(column("Customer"), [], [], coverage_complete=True)

        self.assertEqual(status, STATUS_UNUSED)


class DiscoverReportsTests(unittest.TestCase):
    def test_admin_list_is_used(self) -> None:
        principal = ServicePrincipal.from_values("t", "c", "s")
        with patch("core.usage_service.PowerBILineageClient") as client_cls:
            client = client_cls.return_value
            client.reports_for_dataset.return_value = [
                {
                    "id": "r1",
                    "name": "Report A",
                    "workspaceId": "ws-other",
                    "format": "PBIR",
                    "modifiedDateTime": "2026-01-01T00:00:00Z",
                    "reportType": "PowerBIReport",
                },
                {
                    "id": "r2",
                    "name": "Paginated",
                    "workspaceId": "ws",
                    "format": "PBIR",
                    "reportType": "PaginatedReport",
                },
            ]
            entries, method, notes = discover_reports(
                principal, dataset_id="ds", workspace_id="ws"
            )

        self.assertEqual(method, "admin")
        self.assertEqual(notes, [])
        self.assertEqual([entry.report_id for entry in entries], ["r2", "r1"])
        paginated = entries[0]
        self.assertEqual(paginated.report_format, "RDL")
        self.assertFalse(paginated.supported)
        client.close.assert_called_once()

    def test_admin_failure_falls_back_to_member_and_lineage(self) -> None:
        principal = ServicePrincipal.from_values("t", "c", "s")
        error = ApiError("GET admin/reports gagal (HTTP 403)", status_code=403)
        with patch("core.usage_service.PowerBILineageClient") as client_cls, patch(
            "core.usage_service.reports_using_dataset"
        ) as lineage:
            client = client_cls.return_value
            client.reports_for_dataset.side_effect = error
            client.reports_in_group.return_value = [
                {"id": "r1", "name": "Report A", "datasetId": "ds", "format": "PBIR"},
                {"id": "r9", "name": "Lain", "datasetId": "other", "format": "PBIR"},
            ]
            lineage.return_value = [
                {"report_id": "r2", "name": "Report B", "workspace_id": "ws-x"}
            ]
            entries, method, notes = discover_reports(
                principal, dataset_id="ds", workspace_id="ws"
            )

        self.assertEqual(method, "member")
        self.assertEqual([entry.report_id for entry in entries], ["r1", "r2"])
        self.assertEqual(entries[1].source, "lineage")
        self.assertTrue(any("lineage" in note for note in notes))

    def test_workspace_only_skips_admin_and_lineage(self) -> None:
        principal = ServicePrincipal.from_values("t", "c", "s")
        with patch("core.usage_service.PowerBILineageClient") as client_cls, patch(
            "core.usage_service.reports_using_dataset"
        ) as lineage:
            client = client_cls.return_value
            client.reports_in_group.return_value = [
                {"id": "r1", "name": "Report A", "datasetId": "ds", "format": "PBIR"}
            ]
            entries, method, _notes = discover_reports(
                principal,
                dataset_id="ds",
                workspace_id="ws",
                include_other_workspaces=False,
            )

        self.assertEqual(method, "workspace")
        self.assertEqual([entry.report_id for entry in entries], ["r1"])
        client.reports_for_dataset.assert_not_called()
        lineage.assert_not_called()

    def test_personal_workspace_is_marked_from_catalog(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        database = Path(temp.name) / "data" / "bi_tools.db"
        conn = connect(database)
        try:
            initialize_lineage(conn)
            save_workspaces(
                conn,
                "sync-1",
                [
                    {
                        "id": "pws",
                        "name": "PersonalWorkspace User",
                        "state": "Active",
                        "type": "PersonalGroup",
                    }
                ],
            )
        finally:
            close_quietly(conn)
        principal = ServicePrincipal.from_values("t", "c", "s")
        with patch("core.usage_service.PowerBILineageClient") as client_cls:
            client = client_cls.return_value
            client.reports_for_dataset.return_value = [
                {
                    "id": "r1",
                    "name": "My Report",
                    "workspaceId": "pws",
                    "format": "PBIR",
                    "modifiedDateTime": "2026-01-01T00:00:00Z",
                    "reportType": "PowerBIReport",
                }
            ]
            entries, _method, _notes = discover_reports(
                principal, dataset_id="ds", workspace_id="ws", database=database
            )

        self.assertTrue(entries[0].personal)
        self.assertEqual(entries[0].workspace_name, "PersonalWorkspace User")


class ScanReportsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.conn = connect(Path(self._tmp.name) / "data" / "bi_tools.db")
        self.addCleanup(lambda: close_quietly(self.conn))
        initialize(self.conn)
        self.entries = [
            ReportEntry(
                report_id="r1",
                name="Report A",
                workspace_id="ws",
                report_format="PBIR",
                modified_at="2026-01-01T00:00:00Z",
            )
        ]

    def scan(self, entries=None, loader=None, **kwargs):
        return scan_reports(
            self.conn,
            self.entries if entries is None else entries,
            dataset_id="ds",
            table_names=["Sales"],
            definition_loader=loader or (lambda _entry: definition()),
            **kwargs,
        )

    def test_first_scan_then_cache(self) -> None:
        first = self.scan()
        second = self.scan()

        self.assertEqual((first.scanned, first.skipped), (1, 0))
        self.assertEqual((second.scanned, second.skipped), (0, 1))

    def test_modified_report_is_rescanned(self) -> None:
        self.scan()
        changed = [
            ReportEntry(
                report_id="r1",
                name="Report A",
                workspace_id="ws",
                report_format="PBIR",
                modified_at="2026-02-02T00:00:00Z",
            )
        ]

        counters = self.scan(entries=changed)

        self.assertEqual(counters.scanned, 1)

    def test_refresh_forces_rescan(self) -> None:
        self.scan()
        counters = self.scan(refresh=True)

        self.assertEqual(counters.scanned, 1)

    def test_legacy_report_label_is_scanned(self) -> None:
        from core.fabric_api import PBIR_LEGACY

        entries = [
            ReportEntry(
                report_id="r-legacy",
                name="Legacy Report",
                workspace_id="ws",
                report_format="PBIRLegacy",
                modified_at="2026-01-01T00:00:00Z",
            )
        ]

        counters = self.scan(
            entries=entries,
            loader=lambda _entry: make_definition(PBIR_LEGACY, legacy_parts()),
        )

        self.assertEqual(counters.scanned, 1)
        self.assertEqual(counters.unsupported, 0)
        self.assertEqual(counters.failed, 0)
        rows = field_usage(self.conn, "ds")
        self.assertIn("Customer", {row["field_name"] for row in rows})

    def test_personal_workspace_is_skipped_by_default(self) -> None:
        calls: list[str] = []
        entries = [
            ReportEntry(
                report_id="r-personal",
                name="My Report",
                workspace_id="pws",
                report_format="PBIR",
                modified_at="2026-01-01T00:00:00Z",
                workspace_name="PersonalWorkspace User",
                workspace_type="PersonalGroup",
            )
        ]

        counters = self.scan(entries=entries, loader=lambda e: calls.append(e.report_id))

        self.assertEqual(counters.personal, 1)
        self.assertEqual(counters.scanned, 0)
        self.assertEqual(calls, [])
        from core.usage_store import report_cache

        self.assertEqual(report_cache(self.conn, "ds")["r-personal"]["status"], "personal")

    def test_app_report_is_skipped(self) -> None:
        calls: list[str] = []
        entries = [
            ReportEntry(
                report_id="r-app",
                name="[App] Report Summary Prospect\u200b",
                workspace_id="ws",
                report_format="PBIR",
                modified_at="2026-01-01T00:00:00Z",
            )
        ]

        counters = self.scan(entries=entries, loader=lambda e: calls.append(e.report_id))

        self.assertEqual(counters.app, 1)
        self.assertEqual(counters.scanned, 0)
        self.assertEqual(calls, [])
        from core.usage_store import report_cache

        self.assertEqual(report_cache(self.conn, "ds")["r-app"]["status"], "app")

    def test_personal_workspace_can_be_included(self) -> None:
        entries = [
            ReportEntry(
                report_id="r-personal",
                name="My Report",
                workspace_id="pws",
                report_format="PBIR",
                modified_at="2026-01-01T00:00:00Z",
                workspace_name="PersonalWorkspace User",
                workspace_type="PersonalGroup",
            )
        ]

        counters = self.scan(entries=entries, include_personal=True)

        self.assertEqual(counters.scanned, 1)
        self.assertEqual(counters.personal, 0)

    def test_inaccessible_report_is_cached_for_a_day(self) -> None:
        def failing(_entry):
            raise ApiError("404 not found", status_code=404)

        first = self.scan(loader=failing)
        self.assertEqual(first.inaccessible, 1)
        self.assertEqual(first.failed, 0)

        calls: list[str] = []
        second = self.scan(loader=lambda e: calls.append(e.report_id))
        self.assertEqual(second.inaccessible, 1)
        self.assertEqual(second.scanned, 0)
        self.assertEqual(calls, [])

        refreshed = self.scan(refresh=True)
        self.assertEqual(refreshed.scanned, 1)

    def test_other_api_error_is_failed_not_inaccessible(self) -> None:
        def failing(_entry):
            raise ApiError("500 server error", status_code=500)

        counters = self.scan(loader=failing)

        self.assertEqual(counters.failed, 1)
        self.assertEqual(counters.inaccessible, 0)

    def test_unresolved_fields_are_stored(self) -> None:
        payload = {
            "definition/pages/pages.json": {"pageOrder": ["p1"]},
            "definition/pages/p1/page.json": {"displayName": "Page 1"},
            "definition/pages/p1/visuals/v1/visual.json": {
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
                                                "Property": "Customer",
                                            }
                                        },
                                        "queryRef": "Sales.Customer",
                                    },
                                    {"field": {}, "queryRef": "tanpa-titik"},
                                ]
                            }
                        }
                    },
                }
            },
        }
        definition = ReportDefinition(
            report_format=PBIR,
            parts=tuple(
                DefinitionPart(path=path, payload=json.dumps(body).encode("utf-8"))
                for path, body in payload.items()
            ),
        )

        counters = self.scan(loader=lambda _entry: definition)

        self.assertEqual(counters.unresolved, 1)
        self.assertFalse(counters.complete)
        rows = stored_unresolved(self.conn, "ds")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["query_ref"], "tanpa-titik")
        self.assertEqual(rows[0]["visual_title"].startswith("(tanpa judul)"), True)

    def test_rdl_report_is_skipped_without_download(self) -> None:
        calls: list[str] = []
        entries = [
            ReportEntry(
                report_id="r-rdl",
                name="Paginated",
                workspace_id="ws",
                report_format=FORMAT_RDL,
            )
        ]

        counters = self.scan(
            entries=entries, loader=lambda entry: calls.append(entry.report_id)
        )

        self.assertEqual(counters.unsupported, 1)
        self.assertEqual(counters.scanned, 0)
        self.assertEqual(calls, [])

    def test_unknown_definition_format_is_failed(self) -> None:
        from core.fabric_api import ReportDefinition

        entries = [
            ReportEntry(
                report_id="r-unknown",
                name="Unknown",
                workspace_id="ws",
                report_format="",
                modified_at="2026-01-01T00:00:00Z",
            )
        ]

        counters = self.scan(
            entries=entries,
            loader=lambda _entry: ReportDefinition(
                report_format="unknown", parts=()
            ),
        )

        self.assertEqual(counters.failed, 1)
        self.assertEqual(counters.scanned, 0)

    def test_unsupported_format_is_counted(self) -> None:
        entries = [
            ReportEntry(
                report_id="r2",
                name="Paginated",
                workspace_id="ws",
                report_format="RDL",
            )
        ]
        counters = self.scan(entries=entries, loader=lambda _entry: definition())

        self.assertEqual(counters.unsupported, 1)
        self.assertEqual(counters.scanned, 0)

    def test_failure_is_recorded_and_retried(self) -> None:
        def failing(_entry):
            raise ExtractionError("report tidak bisa diunduh")

        counters = self.scan(loader=failing)

        self.assertEqual(counters.failed, 1)
        self.assertEqual(counters.scanned, 0)
        counters = self.scan()
        self.assertEqual(counters.scanned, 1)

    def test_max_reports_marks_coverage_incomplete(self) -> None:
        entries = [
            ReportEntry(
                report_id=f"r{index}",
                name=f"Report {index}",
                workspace_id="ws",
                report_format="PBIR",
                modified_at="2026-01-01T00:00:00Z",
            )
            for index in range(3)
        ]

        counters = self.scan(entries=entries, max_reports=1)

        self.assertEqual(counters.scanned, 1)
        self.assertEqual(counters.incomplete, 2)
        self.assertFalse(counters.complete)

    def test_should_stop_cancels_between_reports(self) -> None:
        entries = self.entries + [
            ReportEntry(
                report_id="r2",
                name="Report B",
                workspace_id="ws",
                report_format="PBIR",
                modified_at="2026-01-01T00:00:00Z",
            )
        ]
        counters = self.scan(entries=entries, should_stop=lambda: True)

        self.assertTrue(counters.cancelled)
        self.assertEqual(counters.scanned, 0)

    def test_report_no_longer_present_is_inactive(self) -> None:
        self.scan()
        counters = self.scan(entries=[], loader=lambda _entry: definition())

        self.assertEqual(counters.total, 0)


class BuildAnalysisTests(unittest.TestCase):
    def test_usage_rows_are_grouped_case_insensitively(self) -> None:
        usage_rows = [
            {
                "report_id": "r1",
                "report_name": "Report A",
                "report_workspace": "ws",
                "table_name": "sales",
                "field_name": "customer",
                "usage_kind": "field",
                "field_kind": "Column",
                "page_name": "Overview",
                "visual_title": "List",
                "detail": "Values",
            }
        ]
        result = build_analysis(
            stats=stats(),
            usage_rows=usage_rows,
            model_refs={},
            reports=[],
            dataset_id="ds",
            dataset_name="Uji",
            workspace_id="ws",
            workspace_name="Contoh",
            method="admin",
            report_total=1,
            report_scanned=1,
            report_skipped=0,
            report_failed=0,
            coverage_complete=True,
            coverage="1 report",
        )

        customer = next(c for c in result.columns if c.column.column == "Customer")
        qty = next(c for c in result.columns if c.column.column == "Qty")
        self.assertEqual(customer.status, STATUS_USED)
        self.assertEqual(customer.report_count, 1)
        self.assertEqual(qty.status, STATUS_UNUSED)
        self.assertEqual(result.unused_bytes, 2000)

    def test_unresolved_coverage_downgrades_unused(self) -> None:
        result = build_analysis(
            stats=stats(),
            usage_rows=[],
            model_refs={},
            reports=[],
            dataset_id="ds",
            dataset_name="Uji",
            workspace_id="ws",
            workspace_name="Contoh",
            method="admin",
            report_total=1,
            report_scanned=0,
            report_skipped=0,
            report_failed=1,
            coverage_complete=False,
            coverage="1 report gagal",
        )

        self.assertEqual(result.status_counts, {STATUS_UNKNOWN: 2})
        self.assertEqual(result.unused_bytes, 0)


def measure_usage(name: str, kind: str = "Measure") -> dict:
    return {
        "report_id": "r1",
        "report_name": "Report A",
        "report_workspace": "ws",
        "table_name": "Sales",
        "field_name": name,
        "usage_kind": "field",
        "field_kind": kind,
        "page_name": "Overview",
        "visual_title": "List",
        "visual_type": "tableEx",
        "detail": "Values",
    }


class MeasureAnalysisTests(unittest.TestCase):
    def analyse(self, usage_rows, measure_refs=None, *, complete=True):
        return build_analysis(
            stats=stats(),
            usage_rows=usage_rows,
            model_refs={},
            reports=[],
            dataset_id="ds",
            dataset_name="Uji",
            workspace_id="ws",
            workspace_name="Contoh",
            method="admin",
            report_total=1,
            report_scanned=1,
            report_skipped=0,
            report_failed=0,
            coverage_complete=complete,
            coverage="1 report",
            measure_refs=measure_refs or {},
        )

    def by_name(self, result):
        return {item.measure.measure: item for item in result.measures}

    def test_direct_measure_usage_and_unused(self) -> None:
        result = self.analyse([measure_usage("Total")])
        measures = self.by_name(result)

        self.assertEqual(measures["Total"].status, STATUS_USED)
        self.assertEqual(measures["Total"].report_count, 1)
        self.assertEqual(measures["Orphan"].status, STATUS_UNUSED)
        self.assertEqual(result.measure_status_counts[STATUS_USED], 1)

    def test_measure_used_indirectly_by_used_measure(self) -> None:
        refs = {
            ("sales", "helper"): [
                ModelReference(
                    "measure",
                    "'Sales'[Total]",
                    "dipakai measure",
                    blocking=False,
                    source_table="Sales",
                    source_measure="Total",
                )
            ]
        }
        result = self.analyse([measure_usage("Total")], refs)
        helper = self.by_name(result)["Helper"]

        self.assertEqual(helper.status, STATUS_USED)
        self.assertIn("tidak langsung", helper.reason)
        self.assertTrue(helper.indirect)

    def test_measure_referenced_only_by_unused_measure(self) -> None:
        refs = {
            ("sales", "orphan"): [
                ModelReference(
                    "measure",
                    "'Sales'[Helper]",
                    "dipakai measure",
                    blocking=False,
                    source_table="Sales",
                    source_measure="Helper",
                )
            ]
        }
        result = self.analyse([], refs)
        orphan = self.by_name(result)["Orphan"]

        self.assertEqual(orphan.status, STATUS_UNUSED)
        self.assertIn("juga tidak dipakai", orphan.reason)

    def test_calculation_item_keeps_measure(self) -> None:
        refs = {
            ("sales", "orphan"): [
                ModelReference("calculation item", "calc 'X'", "calc 'X'")
            ]
        }
        result = self.analyse([], refs)
        orphan = self.by_name(result)["Orphan"]

        self.assertEqual(orphan.status, STATUS_BLOCKER)
        self.assertIn("calculation item", orphan.reason)

    def test_incomplete_coverage_downgrades_measures(self) -> None:
        result = self.analyse([], complete=False)

        self.assertEqual(result.measure_status_counts, {STATUS_UNKNOWN: 3})

    def test_arithmetic_fallback_matches_measure_name(self) -> None:
        row = measure_usage("Total, ScopedEval(Sales.Total, [])", "Arithmetic")
        row["table_name"] = "Divide(Sales"
        result = self.analyse([row])
        total = self.by_name(result)["Total"]

        self.assertEqual(total.status, STATUS_USED)

    def test_measure_rows_for_gui(self) -> None:
        result = self.analyse([measure_usage("Total")])
        rows = {row["name"]: row for row in measure_rows(result)}

        self.assertEqual(rows["Total"]["type"], "measure")
        self.assertEqual(rows["Total"]["size"], "-")
        self.assertIs(rows["Total"]["analysis"], self.by_name(result)["Total"])


class MetadataRowsTests(unittest.TestCase):
    def test_relationship_dependency_counts_ignore_column_rows(self) -> None:
        rows = [
            {
                "OBJECT_TYPE": "ACTIVE_RELATIONSHIP",
                "OBJECT": "AutoDetected_x",
                "REFERENCED_OBJECT_TYPE": "COLUMN",
                "REFERENCED_OBJECT": "Col",
            },
            {
                "OBJECT_TYPE": "MEASURE",
                "TABLE": "Sales",
                "OBJECT": "M1",
                "REFERENCED_OBJECT_TYPE": "RELATIONSHIP",
                "REFERENCED_OBJECT": "AutoDetected_x",
            },
            {
                "OBJECT_TYPE": "MEASURE",
                "TABLE": "Sales",
                "OBJECT": "M1",
                "REFERENCED_OBJECT_TYPE": "RELATIONSHIP",
                "REFERENCED_OBJECT": "AutoDetected_x",
            },
            {
                "OBJECT_TYPE": "MEASURE",
                "TABLE": "Sales",
                "OBJECT": "M2",
                "REFERENCED_OBJECT_TYPE": "ACTIVE_RELATIONSHIP",
                "REFERENCED_OBJECT": "AutoDetected_x",
            },
        ]

        self.assertEqual(relationship_dependency_counts(rows), {"AutoDetected_x": 2})

    def test_relationship_auto_detection(self) -> None:
        from core.model import relationship_is_auto

        self.assertTrue(relationship_is_auto("AutoDetected_526c6f8a"))
        self.assertTrue(relationship_is_auto("526c6f8a-bde4-49fa-b1c4-79db0a095bfd"))
        self.assertFalse(relationship_is_auto("Relasi Dealer"))

    def test_m_query_rows_group_partitions_and_parameters(self) -> None:
        rows = m_query_rows(
            [
                {
                    "table": "Sales",
                    "source": "let Source = ... in Source",
                    "mode": "Import",
                    "state": "ready",
                },
                {
                    "table": "Sales",
                    "source": "",
                    "mode": "Import",
                    "state": "evaluationError",
                },
                {
                    "table": "Dates",
                    "source": "let Dates = ... in Dates",
                    "mode": "Import",
                    "state": "ready",
                },
                {
                    "table": "CalcTable",
                    "source": "SUMMARIZE ( Sales, Sales[Key] )",
                    "source_type": "calculated",
                    "mode": "Import",
                    "state": "ready",
                },
            ],
            [
                {
                    "name": "ServerURL",
                    "kind": "Parameter",
                    "query_group": "Param",
                    "expression": '"server"',
                    "data_type": "Text",
                },
                {
                    "name": "Helper",
                    "kind": "Expression",
                    "query_group": "",
                    "expression": "1",
                    "data_type": "",
                },
            ],
        )

        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["Sales"]["kind"], "Tabel")
        self.assertEqual(by_name["Sales"]["detail"], "2 partisi")
        self.assertIn("let Source", by_name["Sales"]["expression"])
        self.assertEqual(by_name["Sales"]["warning"], "evaluationError")
        self.assertEqual(by_name["ServerURL"]["kind"], "M parameter")
        self.assertEqual(by_name["ServerURL"]["source"], "Param")
        self.assertEqual(by_name["Helper"]["kind"], "Expression")
        self.assertNotIn("CalcTable", by_name)
        self.assertEqual(rows[0]["kind"], "Tabel")

    def test_model_snapshot_keeps_table_mode_and_relationships(self) -> None:
        value = ModelStats(
            model_name="Model",
            compatibility_level=1600,
            last_update="2026-01-01",
            columns=[],
            tables=[
                TableStat(
                    "Sales", 2, 10, 3000, 0,
                    storage_mode="DirectQuery", measure_count=4, partition_count=3,
                )
            ],
            segment_bytes=3000,
            artifact_bytes=0,
        )

        payload = json.loads(
            model_snapshot(value, "Workspace", [{"name": "Rel", "is_active": True}])
        )

        self.assertEqual(payload["tables"][0]["storage_mode"], "DirectQuery")
        self.assertEqual(payload["tables"][0]["measure_count"], 4)
        self.assertEqual(payload["tables"][0]["partition_count"], 3)
        self.assertEqual(payload["relationships"][0]["name"], "Rel")


class WriteWorkbookTests(unittest.TestCase):
    def test_workbook_contains_expected_sheets(self) -> None:
        result = AnalysisResult(
            dataset_id="ds",
            dataset_name="Uji",
            workspace_id="ws",
            workspace_name="Contoh",
            analyzed_at="2026-01-01T00:00:00+00:00",
            stats=stats(),
            columns=[
                ColumnAnalysis(
                    column=column("Customer"),
                    status=STATUS_UNUSED,
                    reason="Tidak ada referensi",
                    report_records=[
                        {
                            "report_id": "r1",
                            "report_name": "Report A",
                            "report_workspace": "ws",
                            "page_name": "Overview",
                            "visual_title": "List",
                            "visual_type": "tableEx",
                            "usage_kind": "field",
                            "field_kind": "Column",
                            "detail": "Values",
                        }
                    ],
                    model_refs=[
                        ModelReference("measure", "'Sales'[Total]", "measure", blocking=False)
                    ],
                )
            ],
            reports=[
                {
                    "report_id": "r1",
                    "name": "Report A",
                    "status": "ok",
                    "is_active": 1,
                }
            ],
            report_total=1,
            report_scanned=1,
            report_skipped=0,
            report_failed=0,
            method="admin",
            coverage="1 report",
            coverage_complete=True,
            measures=[
                MeasureAnalysis(
                    measure=MeasureStat(
                        table="Sales",
                        measure="Total",
                        expression="SUM(Sales[Qty])",
                    ),
                    status=STATUS_USED,
                    reason="Dipakai di 1 titik pada 1 report.",
                )
            ],
        )
        target = Path(tempfile.mkdtemp()) / "hasil.xlsx"

        path = write_workbook(result, target)

        import pandas as pd

        book = pd.ExcelFile(path)
        self.addCleanup(book.close)
        self.assertEqual(
            book.sheet_names,
            [
                "01_Summary",
                "02_Columns",
                "03_Report_Usage",
                "04_Model_Usage",
                "05_Reports",
                "06_Tables",
                "07_Unresolved",
                "08_Measures",
            ],
        )
        columns = pd.read_excel(book, "02_Columns")
        self.assertEqual(columns.loc[0, "Column"], "Customer")
        self.assertEqual(columns.loc[0, "Status"], STATUS_UNUSED)
        measures = pd.read_excel(book, "08_Measures")
        self.assertEqual(measures.loc[0, "Measure"], "Total")
        self.assertEqual(measures.loc[0, "Status"], STATUS_USED)


class ModelReferenceTests(unittest.TestCase):
    class FakeClient:
        endpoint = "powerbi://test"
        catalog = "Model"
        server_version = "17.0"
        catalog_info = {}

        def __init__(self, rows):
            self.rows = rows

        def query(self, dmv):
            return self.rows.get(dmv, [])

    def model(self) -> LiveModel:
        rows = {
            "TMSCHEMA_MODEL": [{"ID": 1, "Name": "Model", "CompatibilityLevel": 1600}],
            "TMSCHEMA_TABLES": [
                {"ID": 2, "Name": "Sales", "IsHidden": False},
                {"ID": 3, "Name": "Product", "IsHidden": False},
                {"ID": 4, "Name": "Parameter Posisi", "IsHidden": False},
            ],
            "TMSCHEMA_COLUMNS": [
                {"ID": 10, "TableID": 2, "ExplicitName": "Customer", "Type": 1, "ExplicitDataType": 2},
                {"ID": 11, "TableID": 2, "ExplicitName": "Qty", "Type": 1, "ExplicitDataType": 6},
                {"ID": 12, "TableID": 2, "ExplicitName": "Year", "Type": 1, "ExplicitDataType": 6},
                {"ID": 13, "TableID": 2, "ExplicitName": "Month", "Type": 1, "ExplicitDataType": 2, "SortByColumnID": 12},
                {"ID": 20, "TableID": 3, "ExplicitName": "Name", "Type": 1, "ExplicitDataType": 2},
                {"ID": 21, "TableID": 4, "ExplicitName": "Parameter", "Type": 1, "ExplicitDataType": 2},
            ],
            "TMSCHEMA_MEASURES": [
                {
                    "ID": 30,
                    "TableID": 2,
                    "Name": "Total Sales",
                    "Expression": "SUM ( Sales[Qty] )",
                },
                {
                    "ID": 31,
                    "TableID": 2,
                    "Name": "Helper",
                    "Expression": "[Total Sales] * 2",
                },
            ],
            "TMSCHEMA_PARTITIONS": [
                {
                    "ID": 40,
                    "TableID": 2,
                    "Name": "Sales",
                    "Mode": 0,
                    "QueryDefinition": (
                        'let Source = ... , Added = Table.AddColumn(Source, "Flag", '
                        "each [Qty] * 2 ) in Added"
                    ),
                },
                {
                    "ID": 41,
                    "TableID": 4,
                    "Name": "Parameter Posisi",
                    "Mode": 0,
                    "Type": 2,
                    "QueryDefinition": (
                        '{\n    ("Qty", NAMEOF(\'Sales\'[Qty]), 0),\n'
                        '    ("Tahun", NAMEOF(\'Sales\'[Year]), 1)\n}'
                    ),
                },
            ],
            "TMSCHEMA_RELATIONSHIPS": [
                {"ID": 50, "FromColumnID": 10, "ToColumnID": 20}
            ],
            "TMSCHEMA_HIERARCHIES": [
                {"ID": 70, "TableID": 2, "Name": "Calendar", "IsHidden": False}
            ],
            "TMSCHEMA_LEVELS": [
                {"ID": 60, "HierarchyID": 70, "ColumnID": 12, "Name": "Year", "Ordinal": 0}
            ],
            "TMSCHEMA_ROLES": [{"ID": 90, "Name": "Region"}],
            "TMSCHEMA_TABLE_PERMISSIONS": [
                {
                    "ID": 80,
                    "RoleID": 90,
                    "TableID": 2,
                    "FilterExpression": 'Sales[Customer] = "A"',
                }
            ],
        }
        return LiveModel(self.FakeClient(rows))

    def test_references_cover_model_objects(self) -> None:
        refs = model_references(self.model())

        def kinds(name: str, table: str = "sales") -> set[str]:
            return {
                ref.kind for ref in refs.get((table, name.casefold()), [])
            }

        self.assertIn("measure", kinds("Qty"))
        self.assertIn("langkah M", kinds("Qty"))
        self.assertIn("relationship", kinds("Customer"))
        self.assertIn("RLS", kinds("Customer"))
        self.assertIn("hierarchy", kinds("Year"))
        self.assertIn("sort by", kinds("Year"))
        self.assertIn("relationship", kinds("Name", table="product"))

    def test_field_parameter_is_detected_once(self) -> None:
        refs = model_references(self.model())
        qty = [ref for ref in refs[("sales", "qty")] if ref.kind == "field parameter"]

        self.assertEqual(len(qty), 1)
        self.assertEqual(qty[0].object, "'Parameter Posisi'")
        self.assertEqual(qty[0].detail, "field parameter 'Parameter Posisi'")
        self.assertNotIn(
            "calculated table",
            {ref.kind for ref in refs[("sales", "qty")]},
        )
        self.assertIn("field parameter", {ref.kind for ref in refs[("sales", "year")]})

    def test_measure_to_measure_reference(self) -> None:
        refs = measure_references(self.model())
        referenced = refs.get(("sales", "total sales"), [])

        self.assertTrue(referenced)
        self.assertEqual(referenced[0].kind, "measure")
        self.assertEqual(referenced[0].source_measure, "Helper")
        self.assertEqual(referenced[0].object, "'Sales'[Helper]")
        self.assertFalse(referenced[0].blocking)

    def test_measure_reference_is_not_blocking(self) -> None:
        refs = model_references(self.model())
        measure_refs = [
            ref for ref in refs[("sales", "qty")] if ref.kind == "measure"
        ]

        self.assertTrue(measure_refs)
        self.assertFalse(measure_refs[0].blocking)


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "data" / "bi_tools.db"
        conn = connect(self.db)
        try:
            initialize(conn)
            stats_value = stats()
            save_columns(conn, "ds", stats_value.columns)
            save_measures(
                conn,
                "ds",
                stats_value.measures,
                {
                    ("sales", "helper"): [
                        {
                            "kind": "measure",
                            "object": "'Sales'[Total]",
                            "detail": "dipakai measure",
                            "blocking": False,
                            "source_table": "Sales",
                            "source_measure": "Total",
                        }
                    ]
                },
            )
            save_model_refs(
                conn,
                "ds",
                [
                    {
                        "table": "sales",
                        "column": "customer",
                        "kind": "relationship",
                        "object": "'product'[name]",
                        "detail": "relasi",
                        "blocking": True,
                    }
                ],
            )
            save_m_queries(
                conn,
                "ds",
                [
                    {
                        "name": "Sales",
                        "kind": "Tabel",
                        "source": "Import",
                        "expression": "let Source = ... in Source",
                        "warning": "",
                        "detail": "2 partisi",
                    }
                ],
            )
            save_report(
                conn,
                report_id="r1",
                workspace_id="ws",
                dataset_id="ds",
                name="Report A",
                report_format="PBIR",
                modified_at="2026-01-01T00:00:00Z",
                status="ok",
                usage=ReportUsage(
                    report_format="PBIR",
                    records=[
                        UsageRecord(
                            "field", "Column", "Sales", "Customer",
                            page_id="p1", page_name="Overview",
                        )
                    ],
                ),
            )
            save_run(
                conn,
                {
                    "scan_id": "s1",
                    "dataset_id": "ds",
                    "workspace_id": "ws",
                    "dataset_name": "Uji",
                    "started_at": "2026-01-01T09:59:00+00:00",
                    "finished_at": "2026-01-01T10:00:00+00:00",
                    "status": "Succeeded",
                    "report_total": 1,
                    "report_scanned": 1,
                    "report_skipped": 0,
                    "report_failed": 0,
                    "report_unsupported": 0,
                    "coverage_complete": 1,
                    "model_json": model_snapshot(
                        stats_value,
                        "Workspace",
                        [{"name": "Rel", "is_active": True}],
                    ),
                    "column_count": 2,
                    "unused_count": 1,
                    "unused_bytes": 2000,
                    "dataset_bytes": 3000,
                    "coverage": "1 report · 1 dipindai",
                },
            )
        finally:
            close_quietly(conn)

    def test_snapshot_restores_sizes_usage_and_verdicts(self) -> None:
        result = load_snapshot(self.db, "ds")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.dataset_name, "Uji")
        self.assertEqual(result.stats.dataset_bytes, 3000)
        self.assertEqual(len(result.columns), 2)
        by_name = {column.column.column: column for column in result.columns}
        self.assertEqual(by_name["Customer"].status, STATUS_BLOCKER)
        self.assertEqual(by_name["Qty"].status, STATUS_UNUSED)
        self.assertEqual(result.report_total, 1)
        self.assertEqual(result.analyzed_at, "2026-01-01T10:00:00+00:00")
        self.assertTrue(result.coverage_complete)
        self.assertEqual(result.method, "cache")
        self.assertEqual(result.relationships[0]["name"], "Rel")
        self.assertEqual(result.report_pages["r1"][0]["page_name"], "Overview")
        self.assertEqual(result.report_pages["r1"][0]["field_count"], 1)
        self.assertEqual(result.m_queries[0]["name"], "Sales")
        self.assertEqual(result.m_queries[0]["detail"], "2 partisi")

    def test_snapshot_restores_measures(self) -> None:
        result = load_snapshot(self.db, "ds")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(len(result.measures), 3)
        helper = next(
            item for item in result.measures if item.measure.measure == "Helper"
        )
        self.assertEqual(len(helper.model_refs), 1)
        self.assertFalse(helper.model_refs[0].blocking)
        self.assertEqual(helper.model_refs[0].source_measure, "Total")

    def test_missing_snapshot_returns_none(self) -> None:
        self.assertIsNone(load_snapshot(self.db, "lain"))
        self.assertIsNone(
            load_snapshot(Path(self._tmp.name) / "tidak-ada.db", "ds")
        )


class AnalysisHelperTests(unittest.TestCase):
    def test_save_report_helper_is_reusable(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        conn = connect(Path(temp.name) / "data" / "db.sqlite")
        self.addCleanup(lambda: close_quietly(conn))
        initialize(conn)
        save_report(
            conn,
            report_id="r1",
            workspace_id="ws",
            dataset_id="ds",
            name="Report",
            report_format="PBIR",
            modified_at="",
            status="ok",
            usage=ReportUsage(
                report_format="PBIR",
                records=[UsageRecord("field", "Column", "Sales", "Qty")],
            ),
        )

        from core.usage_store import field_usage

        self.assertEqual(len(field_usage(conn, "ds")), 1)


if __name__ == "__main__":
    unittest.main()
