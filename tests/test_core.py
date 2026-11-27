"""Uji angka acuan dan penanganan error.

Jalankan dari folder tooling:
    python -m unittest discover -s tests -t .
Uji model (butuh Power BI Desktop terbuka):
    set RUN_LIVE_TESTS=1 && python -m unittest discover -s tests -t .
Uji angka acuan measure/kolom memakai workbook model acuan; nama catalog-nya
tidak disimpan di repo (identifier pelanggan). Set nama itu bila perlu:
    set RUN_MODEL_CATALOG=<nama Catalog di 01_Model_Overview>
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import verify_reference

from core.errors import ExtractionError
from core.jobs import run_metadata_job, run_report_job
from core.metadata_common import parse_report_field, report_aggregation_label, scan_report_usage
from core.model import extract_connector
from core.pbix import (
    LIVE_CONNECTION,
    LOCAL_MODEL,
    ROOT,
    UNSUPPORTED,
    detect_pbix_source,
    resolve_pbix,
)
from core.report import (
    DEFAULT_MODEL_WORKBOOK,
    extract_report,
    extract_sync_slicers,
    find_validation_workbook,
    page_is_hidden,
    parse_field,
    resolve_validation_model,
    run_report,
)
from core.xmla_client import DesktopInstance

def _sample_pbix(env_name: str) -> Path:
    """File .pbix contoh dari env; path pengganti yang tidak ada bila kosong."""
    text = os.environ.get(env_name, "").strip()
    return Path(text).expanduser() if text else ROOT / "tidak-diset.pbix"


LIVE_SAMPLE = _sample_pbix("RUN_LIVE_PBIX")
DIRECT_QUERY_SAMPLE = _sample_pbix("RUN_DQ_PBIX")


def write_minimal_model_workbook(path: Path) -> Path:
    """Workbook model minimal (03_Columns + 04_Measures) untuk uji validasi offline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = pd.DataFrame([{"table": "Sales", "column": "Amount", "is_hidden": False}])
    measures = pd.DataFrame([{"table": "Sales", "measure": "Total Amount", "is_hidden": False}])
    with pd.ExcelWriter(path) as writer:
        columns.to_excel(writer, sheet_name="03_Columns", index=False)
        measures.to_excel(writer, sheet_name="04_Measures", index=False)
    return path


class ParseFieldTests(unittest.TestCase):
    def test_aggregation_function_is_mapped(self) -> None:
        info = parse_field(
            {
                "Aggregation": {
                    "Expression": {
                        "Column": {
                            "Expression": {"SourceRef": {"Entity": "Sales"}},
                            "Property": "Amount",
                        }
                    },
                    "Function": 0,
                }
            }
        )
        self.assertEqual(info["field_kind"], "Aggregation")
        self.assertEqual(info["table"], "Sales")
        self.assertEqual(info["field"], "Amount")
        self.assertEqual(info["aggregation"], "Sum")
        self.assertEqual(info["expression"], "")

    def test_visual_calculation_is_mapped(self) -> None:
        info = parse_field(
            {
                "NativeVisualCalculation": {
                    "Language": "dax",
                    "Expression": "[A] + [B]",
                    "Name": "Testing",
                }
            }
        )
        self.assertEqual(info["field_kind"], "VisualCalculation")
        self.assertEqual(info["table"], "")
        self.assertEqual(info["field"], "Testing")
        self.assertEqual(info["expression"], "[A] + [B]")
        self.assertEqual(info["aggregation"], "")


REFERENCE_REPORT = {
    "pages": 10,
    "fields": 207,
    "slicers": 76,
    "sync_slicers": 74,
    "filters": 32,
    "visuals": 137,
    "interactions": 11,
    "measures": 51,
    "columns": 94,
    "validation_issues": 0,
}

REPORT_SHEET_ORDER = [
    "00_README",
    "01_Pages",
    "02_Bookmarks",
    "03_Interactions",
    "04_Visual_Fields",
    "05_Slicers",
    "06_Sync_Slicers",
    "07_Filters",
    "08_Visual_Summary",
    "09_Usage_Measures",
    "10_Usage_Columns",
    "11_Validation",
    "12_Model_Inventory",
]

# Nama catalog workbook acuan sengaja tidak disimpan di repo (identifier
# pelanggan). Isi RUN_MODEL_CATALOG agar uji angka acuan measure/kolom berjalan;
# tanpa variabel itu uji tersebut dilewati, bukan gagal.
EXPECTED_MODEL_CATALOG = os.getenv("RUN_MODEL_CATALOG", "").strip()

# Path .pbix acuan juga tidak disimpan di repo. Isi RUN_PBIX dengan path file
# .pbix model lokal untuk menjalankan uji angka acuan report/model.
PBIX_TEXT = os.environ.get("RUN_PBIX", "").strip()
RUN_PBIX = Path(PBIX_TEXT).expanduser() if PBIX_TEXT else None
PBIX_READY = RUN_PBIX is not None and RUN_PBIX.exists()


def model_catalog(path: Path) -> str:
    """Nama catalog di 01_Model_Overview (kosong bila workbook tidak cocok)."""
    try:
        frame = pd.read_excel(path, sheet_name="01_Model_Overview")
    except Exception:  # noqa: BLE001 - workbook lama/rusak: tanpa nama
        return ""
    if "property" not in frame.columns or "value" not in frame.columns:
        return ""
    rows = {str(p): str(v) for p, v in zip(frame["property"], frame["value"])}
    return rows.get("Catalog", "")


def make_pbix(
    path: Path,
    *,
    datamodel: bool = False,
    live: bool = False,
    remote_artifact: bool = False,
    pbir: bool = True,
) -> Path:
    """Buat .pbix sintetis untuk menguji deteksi jenis sumber."""
    with zipfile.ZipFile(path, "w") as archive:
        if pbir:
            archive.writestr("Report/definition/report.json", "{}")
            archive.writestr("Report/definition/pages/pages.json", '{"pageOrder": []}')
        if datamodel:
            archive.writestr("DataModel", b"stub")
        if live:
            archive.writestr(
                "Connections",
                json.dumps(
                    {
                        "Version": 6,
                        "Connections": [
                            {
                                "ConnectionType": "pbiServiceLive",
                                "PbiModelDatabaseName": "88888888-8888-4888-8888-888888888888",
                            }
                        ],
                        "RemoteArtifacts": [
                            {"DatasetId": "88888888-8888-4888-8888-888888888888", "ReportId": "report-1"}
                        ],
                    }
                ),
            )
        elif remote_artifact:
            archive.writestr(
                "Connections",
                json.dumps(
                    {
                        "Version": 3,
                        "RemoteArtifacts": [{"DatasetId": "dataset-1", "ReportId": "report-1"}],
                    }
                ),
            )
    return path


class ReportReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not PBIX_READY:
            raise unittest.SkipTest(
                "set RUN_PBIX=<file .pbix model lokal> untuk uji angka acuan report/model"
            )
        cls.model_matches = False
        model_workbook = None
        if DEFAULT_MODEL_WORKBOOK.exists():
            catalog = model_catalog(DEFAULT_MODEL_WORKBOOK)
            cls.model_matches = bool(EXPECTED_MODEL_CATALOG) and (
                EXPECTED_MODEL_CATALOG.lower() in catalog.lower()
            )
            if cls.model_matches:
                model_workbook = DEFAULT_MODEL_WORKBOOK
        cls._tmp = tempfile.TemporaryDirectory()
        cls.out_file = Path(cls._tmp.name) / "Report_Metadata.xlsx"
        cls.summary = run_report_job(
            pbix=RUN_PBIX,
            model_workbook=model_workbook,
            out_file=cls.out_file,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_report_counts_match_reference(self) -> None:
        self.assertEqual(self.summary["pages"], REFERENCE_REPORT["pages"])
        self.assertEqual(self.summary["visuals"], REFERENCE_REPORT["visuals"])
        self.assertEqual(self.summary["fields"], REFERENCE_REPORT["fields"])
        self.assertEqual(self.summary["slicers"], REFERENCE_REPORT["slicers"])
        self.assertEqual(self.summary["sync_slicers"], REFERENCE_REPORT["sync_slicers"])
        self.assertEqual(self.summary["filters"], REFERENCE_REPORT["filters"])
        self.assertEqual(self.summary["interactions"], REFERENCE_REPORT["interactions"])

    def test_model_counts_match_reference(self) -> None:
        if not self.model_matches:
            self.skipTest(
                "Semantic_Model_Metadata.xlsx bukan model acuan "
                "(set RUN_MODEL_CATALOG); angka acuan measure/kolom dilewati."
            )
        self.assertEqual(self.summary["measures"], REFERENCE_REPORT["measures"])
        self.assertEqual(self.summary["columns"], REFERENCE_REPORT["columns"])
        self.assertEqual(
            self.summary["validation_issues"], REFERENCE_REPORT["validation_issues"]
        )

    def test_workbook_sheets(self) -> None:
        with pd.ExcelFile(self.out_file) as workbook:
            sheets = workbook.sheet_names
        self.assertEqual(sheets, REPORT_SHEET_ORDER)

    def test_sync_slicer_sheet_contents(self) -> None:
        df = pd.read_excel(self.out_file, sheet_name="06_Sync_Slicers")
        self.assertEqual(len(df), 74)
        self.assertEqual(df["sync_group"].nunique(), 15)
        # baris harus berurutan per grup: semua anggota satu grup berdampingan
        first_seen: list[str] = []
        for group in df["sync_group"]:
            if not first_seen or first_seen[-1] != group:
                if group in first_seen:
                    self.fail(f"grup sync {group!r} tidak berurutan berdampingan")
                first_seen.append(group)
        self.assertEqual(len(first_seen), 15)
        # anggota grup terbesar sync di 8 halaman berbeda
        largest = df["sync_group"].value_counts().idxmax()
        self.assertEqual(int(df["sync_group"].value_counts().max()), 8)
        self.assertEqual(df[df["sync_group"] == largest]["page_name"].nunique(), 8)


class SyncSlicerTests(unittest.TestCase):
    """Uji extract_sync_slicers dengan folder PBIR sintetis (tanpa file besar)."""

    @staticmethod
    def _write_visual(
        root: Path, page_id: str, visual_id: str, visual: dict
    ) -> None:
        vdir = root / "pages" / page_id / "visuals" / visual_id
        vdir.mkdir(parents=True, exist_ok=True)
        payload = {"name": visual_id, "visual": visual}
        (vdir / "visual.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def _build_report(
        self, root: Path, *, with_sync: bool = True, with_slicer: bool = True
    ) -> Path:
        pages_dir = root / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        (pages_dir / "pages.json").write_text(
            json.dumps({"pageOrder": ["page1", "page2"]}), encoding="utf-8"
        )
        for page_id, display in (("page1", "Halaman 1"), ("page2", "Halaman 2")):
            pdir = pages_dir / page_id
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "page.json").write_text(
                json.dumps({"name": page_id, "displayName": display}),
                encoding="utf-8",
            )
            (pdir / "visuals").mkdir(parents=True, exist_ok=True)

        def slicer(sync: dict | None) -> dict:
            item = {
                "visualType": "slicer",
                "query": {
                    "queryState": {
                        "Values": {
                            "projections": [
                                {
                                    "field": {
                                        "Column": {
                                            "Expression": {
                                                "SourceRef": {"Entity": "Tabel"}
                                            },
                                            "Property": "Kolom",
                                        }
                                    }
                                }
                            ]
                        }
                    }
                },
                "visualContainerObjects": {
                    "title": [
                        {"properties": {"text": {"Literal": {"Value": "'Slicer X'"}}}}
                    ]
                },
            }
            if sync is not None:
                item["syncGroup"] = sync
            return item

        if with_slicer:
            group = {"groupName": "GrupA", "fieldChanges": True, "filterChanges": True}
            self._write_visual(
                root, "page1", "v1", slicer(group if with_sync else None)
            )
            if with_sync:
                self._write_visual(root, "page2", "v2", slicer(group))
        # visual non-slicer tidak boleh ikut terbaca
        self._write_visual(
            root,
            "page1",
            "v3",
            {"visualType": "barChart", "syncGroup": {"groupName": "Abaikan"}},
        )
        return root

    def test_sync_rows_group_pages_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._build_report(Path(tmp))
            rows = extract_sync_slicers(root)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["sync_group"] for r in rows], ["GrupA", "GrupA"])
        self.assertEqual([r["page_name"] for r in rows], ["Halaman 1", "Halaman 2"])
        self.assertEqual(rows[0]["slicer_name"], "Slicer X")
        self.assertEqual(rows[0]["table"], "Tabel")
        self.assertEqual(rows[0]["column"], "Kolom")
        self.assertEqual(rows[0]["field_kind"], "Column")
        self.assertTrue(rows[0]["field_changes"])
        self.assertTrue(rows[0]["filter_changes"])
        self.assertEqual(rows[0]["group_size"], 2)
        self.assertEqual(rows[0]["group_pages"], "Halaman 2")
        self.assertEqual(rows[1]["group_pages"], "Halaman 1")
        self.assertEqual(rows[0]["note"], "")

    def test_slicer_without_sync_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._build_report(Path(tmp), with_sync=False)
            rows = extract_sync_slicers(root)
        self.assertEqual(len(rows), 1)
        self.assertIn("TIDAK ADA SYNC SLICER", rows[0]["note"])
        self.assertEqual(rows[0]["sync_group"], "")

    def test_report_without_slicers_gives_note_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._build_report(Path(tmp), with_slicer=False)
            rows = extract_sync_slicers(root)
        self.assertEqual(len(rows), 1)
        self.assertIn("TIDAK ADA SYNC SLICER", rows[0]["note"])


class ReportPageHiddenTests(unittest.TestCase):
    """Kolom is_hidden di 01_Pages diambil dari page.json PBIR."""

    @staticmethod
    def _build_report(root: Path) -> Path:
        (root / "pages").mkdir(parents=True, exist_ok=True)
        (root / "report.json").write_text("{}", encoding="utf-8")
        (root / "pages" / "pages.json").write_text(
            json.dumps({"pageOrder": ["p1", "p2", "p3"], "activePageName": "p1"}),
            encoding="utf-8",
        )
        pages = {
            "p1": {"name": "p1", "displayName": "Visible"},
            "p2": {
                "name": "p2",
                "displayName": "Hidden",
                "visibility": "HiddenInViewMode",
            },
            "p3": {"name": "p3", "displayName": "Tooltip", "type": "Tooltip"},
        }
        for page_id, payload in pages.items():
            page_dir = root / "pages" / page_id
            (page_dir / "visuals").mkdir(parents=True, exist_ok=True)
            (page_dir / "page.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
        return root

    def test_page_hidden_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page_rows, *_ = extract_report(self._build_report(Path(tmp)))
        flags = {row["page_name"]: row["is_hidden"] for row in page_rows}
        self.assertEqual(flags, {"Visible": False, "Hidden": True, "Tooltip": True})
        self.assertTrue(all(isinstance(value, bool) for value in flags.values()))

    def test_page_is_hidden_falls_back_to_is_hidden_key(self) -> None:
        self.assertTrue(page_is_hidden({"isHidden": True}))
        self.assertFalse(page_is_hidden({"isHidden": False}))
        self.assertFalse(page_is_hidden({}))


class ReportVisualHiddenTests(unittest.TestCase):
    """Kolom is_hidden di 08_Visual_Summary diambil dari visual.json PBIR."""

    @staticmethod
    def _write_visual(
        root: Path, page_id: str, visual_id: str, payload: dict
    ) -> None:
        vdir = root / "pages" / page_id / "visuals" / visual_id
        vdir.mkdir(parents=True, exist_ok=True)
        data = {"name": visual_id, **payload}
        (vdir / "visual.json").write_text(json.dumps(data), encoding="utf-8")

    def _build_report(self, root: Path) -> Path:
        (root / "pages").mkdir(parents=True, exist_ok=True)
        (root / "report.json").write_text("{}", encoding="utf-8")
        (root / "pages" / "pages.json").write_text(
            json.dumps({"pageOrder": ["p1"], "activePageName": "p1"}),
            encoding="utf-8",
        )
        page_dir = root / "pages" / "p1"
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "page.json").write_text(
            json.dumps({"name": "p1", "displayName": "Page"}), encoding="utf-8"
        )

        self._write_visual(root, "p1", "v1", {"visual": {"visualType": "card"}})
        self._write_visual(
            root, "p1", "v2", {"visual": {"visualType": "card"}, "isHidden": True}
        )
        self._write_visual(
            root,
            "p1",
            "g1",
            {
                "visualGroup": {"displayName": "Grup", "groupMode": "ScaleMode"},
                "isHidden": True,
                "position": {"x": 10, "y": 20, "width": 400, "height": 300},
            },
        )
        self._write_visual(
            root,
            "p1",
            "v3",
            {
                "visual": {"visualType": "card"},
                "parentGroupName": "g1",
                "position": {"x": 1, "y": 2, "width": 100, "height": 50},
            },
        )
        # group bersarang di dalam group yang hidden
        self._write_visual(
            root,
            "p1",
            "g2",
            {
                "visualGroup": {"displayName": "Anak", "groupMode": "ScaleMode"},
                "parentGroupName": "g1",
                "position": {"x": 5, "y": 7, "width": 200, "height": 150},
            },
        )
        self._write_visual(
            root,
            "p1",
            "v4",
            {
                "visual": {"visualType": "card"},
                "parentGroupName": "g2",
                "position": {"x": 1, "y": 2, "width": 80, "height": 40},
            },
        )
        # group biasa tidak ikut menyembunyikan isinya
        self._write_visual(
            root,
            "p1",
            "g3",
            {"visualGroup": {"displayName": "Biasa", "groupMode": "ScaleMode"}},
        )
        self._write_visual(
            root,
            "p1",
            "v5",
            {"visual": {"visualType": "card"}, "parentGroupName": "g3"},
        )
        return root

    def test_visual_hidden_flags_and_group_inheritance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = extract_report(self._build_report(Path(tmp)))
        visual_rows = result[4]
        flags = {row["visual_id"]: row["is_hidden"] for row in visual_rows}
        self.assertEqual(
            flags, {"v1": False, "v2": True, "v3": True, "v4": True, "v5": False}
        )
        self.assertTrue(all(isinstance(value, bool) for value in flags.values()))

    def test_absolute_position_includes_parent_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = extract_report(self._build_report(Path(tmp)))
        rows = {row["visual_id"]: row for row in result[4]}

        # v3: group g1 (10,20) + visual (1,2)
        self.assertEqual(
            (rows["v3"]["position_x_abs"], rows["v3"]["position_y_abs"]),
            (11.0, 22.0),
        )
        # v4: g1 (10,20) + g2 (5,7) + visual (1,2)
        self.assertEqual(
            (rows["v4"]["position_x_abs"], rows["v4"]["position_y_abs"]),
            (16.0, 29.0),
        )
        # posisi relatif tetap tersimpan apa adanya
        self.assertEqual(
            (rows["v4"]["position_x"], rows["v4"]["position_y"]), (1.0, 2.0)
        )


class ReportUsageTests(unittest.TestCase):
    """Agregasi level visual dihitung sebagai pemakaian kolom model."""

    @staticmethod
    def _write_report(root: Path, projections: list[dict]) -> Path:
        pages_dir = root / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        (pages_dir / "pages.json").write_text(
            json.dumps({"pageOrder": ["page1"]}), encoding="utf-8"
        )
        pdir = pages_dir / "page1"
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "page.json").write_text(
            json.dumps({"name": "page1", "displayName": "Halaman 1"}), encoding="utf-8"
        )
        vdir = pdir / "visuals" / "v1"
        vdir.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": "v1",
            "visual": {"query": {"queryState": {"Values": {"projections": projections}}}},
        }
        (vdir / "visual.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return root

    @staticmethod
    def _aggregation(table: str, column: str, function: int, query_ref: str) -> dict:
        return {
            "field": {
                "Aggregation": {
                    "Expression": {
                        "Column": {
                            "Expression": {"SourceRef": {"Entity": table}},
                            "Property": column,
                        }
                    },
                    "Function": function,
                }
            },
            "queryRef": query_ref,
            "nativeQueryRef": f"{column}",
        }

    def test_aggregation_counts_as_column_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_report(
                Path(tmp),
                [
                    self._aggregation("TabelA", "Engine No", 3, "Min(TabelA.Engine No)"),
                    self._aggregation("TabelA", "Engine No", 2, "Count(TabelA.Engine No)"),
                    {
                        "field": {
                            "Column": {
                                "Expression": {"SourceRef": {"Entity": "Sales"}},
                                "Property": "Amount",
                            }
                        },
                        "queryRef": "Sales.Amount",
                    },
                ],
            )
            measures, columns = scan_report_usage(root)

        self.assertEqual(measures, {})
        self.assertEqual(set(columns), {("TabelA", "Engine No"), ("Sales", "Amount")})
        aggregated = columns[("TabelA", "Engine No")]
        self.assertEqual(len(aggregated["visuals"]), 1)
        self.assertEqual(len(aggregated["pages"]), 1)
        self.assertEqual(aggregated["aggregations"], {"Min", "Distinct count"})
        self.assertNotIn("aggregations", columns[("Sales", "Amount")])

    def test_aggregated_query_ref_is_not_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_report(
                Path(tmp),
                [
                    {
                        "field": {"Aggregation": {}},
                        "queryRef": "Min(TabelA.Engine No)",
                    }
                ],
            )
            _measures, columns = scan_report_usage(root)
        self.assertEqual(columns, {})

    def test_stale_query_ref_falls_back_to_table_and_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._write_report(
                Path(tmp),
                [{"field": {"Column": {}}, "queryRef": "Sales.Amount"}],
            )
            _measures, columns = scan_report_usage(root)
        self.assertEqual(set(columns), {("Sales", "Amount")})

    def test_parse_report_field_reads_aggregation_column(self) -> None:
        field = self._aggregation("TabelA", "Engine No", 1, "Average(TabelA.Engine No)")["field"]
        self.assertEqual(parse_report_field(field), ("Aggregation", "TabelA", "Engine No"))
        self.assertEqual(report_aggregation_label(field), "Average")


class ErrorHandlingTests(unittest.TestCase):
    def test_missing_pbix_raises_extraction_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ExtractionError):
            resolve_pbix(Path(tmp) / "tidak_ada.pbix", Path(tmp))

    def test_folder_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ExtractionError):
            resolve_pbix(Path(tmp), Path(tmp))

    def test_non_pbix_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text_file = Path(tmp) / "report.txt"
            text_file.write_text("x", encoding="utf-8")
            with self.assertRaises(ExtractionError):
                resolve_pbix(text_file, Path(tmp))

    def test_missing_path_argument_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ExtractionError):
            resolve_pbix(None, Path(tmp))

    def test_model_usage_requires_report_or_no_report(self) -> None:
        from core.model import resolve_report_pbix

        with self.assertRaises(ExtractionError):
            resolve_report_pbix(None, False)
        self.assertIsNone(resolve_report_pbix(None, True))


class CliPbixArgumentTests(unittest.TestCase):
    """CLI menolak jalan tanpa path .pbix eksplisit."""

    def test_report_cli_requires_pbix(self) -> None:
        from cli.report import main as report_main

        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            self.assertEqual(report_main(["--no-model"]), 2)
        self.assertIn("--report", buffer.getvalue())

    def test_model_cli_requires_report_or_no_report(self) -> None:
        from cli.model import main as model_main

        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            self.assertEqual(model_main([]), 2)
        self.assertIn("--no-report", buffer.getvalue())


class PbixDetectionTests(unittest.TestCase):
    """Deteksi jenis sumber dari isi .pbix (tanpa Power BI Desktop)."""

    def test_local_model_with_remote_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_pbix(Path(tmp) / "local.pbix", datamodel=True, remote_artifact=True)
            info = detect_pbix_source(path)
        self.assertEqual(info.kind, LOCAL_MODEL)
        self.assertTrue(info.has_datamodel)
        self.assertTrue(info.has_pbir)
        self.assertEqual(info.dataset_id, "dataset-1")

    def test_live_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_pbix(Path(tmp) / "live.pbix", live=True)
            info = detect_pbix_source(path)
        self.assertEqual(info.kind, LIVE_CONNECTION)
        self.assertFalse(info.has_datamodel)
        self.assertEqual(info.connection_type, "pbiServiceLive")
        self.assertEqual(info.dataset_id, "88888888-8888-4888-8888-888888888888")

    def test_thin_report_from_remote_artifact_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_pbix(Path(tmp) / "thin.pbix", remote_artifact=True)
            info = detect_pbix_source(path)
        self.assertEqual(info.kind, LIVE_CONNECTION)

    def test_unknown_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = make_pbix(Path(tmp) / "unknown.pbix", pbir=False)
            info = detect_pbix_source(path)
        self.assertEqual(info.kind, UNSUPPORTED)
        self.assertFalse(info.has_pbir)

    def test_invalid_zip_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rusak.pbix"
            path.write_bytes(b"bukan zip")
            with self.assertRaises(ExtractionError):
                detect_pbix_source(path)


class SampleSourceTests(unittest.TestCase):
    """Verifikasi deteksi pada file contoh nyata (opsional, dari env)."""

    @unittest.skipUnless(
        LIVE_SAMPLE.exists(), "set RUN_LIVE_PBIX=<file .pbix live connection>"
    )
    def test_live_sample(self) -> None:
        info = detect_pbix_source(LIVE_SAMPLE)
        self.assertEqual(info.kind, LIVE_CONNECTION)
        self.assertTrue(info.has_pbir)

    @unittest.skipUnless(
        DIRECT_QUERY_SAMPLE.exists(),
        "set RUN_DQ_PBIX=<file .pbix DirectQuery/model lokal>",
    )
    def test_direct_query_sample(self) -> None:
        info = detect_pbix_source(DIRECT_QUERY_SAMPLE)
        self.assertEqual(info.kind, LOCAL_MODEL)
        self.assertTrue(info.has_datamodel)
        self.assertTrue(info.has_pbir)


@unittest.skipUnless(
    LIVE_SAMPLE.exists(), "set RUN_LIVE_PBIX=<file .pbix live connection>"
)
class LiveConnectionJobTests(unittest.TestCase):
    """Live connection: report dibuat, model tidak dicoba."""

    def test_report_only_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            # workbook model lama di folder output harus dipakai untuk validasi
            write_minimal_model_workbook(out_dir / DEFAULT_MODEL_WORKBOOK.name)
            logs: list[str] = []
            result = run_metadata_job(
                pbix=LIVE_SAMPLE, out_dir=out_dir, extract_model=True, log=logs.append
            )
            self.assertEqual(result.output_count, 1)
            self.assertIsNone(result.model_out)
            self.assertIsNone(result.model)
            self.assertIsNotNone(result.report_out)
            self.assertTrue(result.report_out.exists())
            self.assertEqual(result.report["pages"], 23)
            self.assertTrue(
                any(
                    "Sumber model" in line and DEFAULT_MODEL_WORKBOOK.name in line
                    for line in logs
                ),
                "report seharusnya divalidasi dengan workbook di folder output",
            )

    def test_model_only_needs_local_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExtractionError):
                run_metadata_job(
                    pbix=LIVE_SAMPLE,
                    out_dir=Path(tmp),
                    extract_report=False,
                    extract_model=True,
                )
            self.assertFalse((Path(tmp) / "Report_Metadata.xlsx").exists())

    def test_no_scope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ExtractionError):
                run_metadata_job(
                    pbix=LIVE_SAMPLE,
                    out_dir=Path(tmp),
                    extract_report=False,
                    extract_model=False,
                )
            self.assertEqual(list(Path(tmp).iterdir()), [])


class ExtractionScopeTests(unittest.TestCase):
    """Cakupan report/model dan workbook validasi (tanpa Desktop)."""

    def test_output_folder_wins_over_tooling_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tooling = root / "tooling"
            fallback = write_minimal_model_workbook(
                tooling / DEFAULT_MODEL_WORKBOOK.name
            )
            out_dir = root / "output"
            local = write_minimal_model_workbook(out_dir / DEFAULT_MODEL_WORKBOOK.name)
            with patch("core.report.OUT_DIR", root / "outputs"), patch(
                "core.report.APP_DIR", tooling
            ):
                self.assertEqual(find_validation_workbook(out_dir), local)
                self.assertEqual(find_validation_workbook(root / "kosong"), fallback)

    def test_validation_uses_workbook_in_output_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "output"
            workbook = write_minimal_model_workbook(out_dir / DEFAULT_MODEL_WORKBOOK.name)
            with patch("core.report.DEFAULT_MODEL_WORKBOOK", Path(tmp) / "tidak-ada.xlsx"):
                tables, inventory, source = resolve_validation_model(
                    no_model=False, workbook=None, search_dir=out_dir
                )
            self.assertIn("Sales", tables)
            self.assertEqual(len(inventory), 2)
            self.assertIn(workbook.name, source)

    def test_disabled_validation_ignores_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            write_minimal_model_workbook(out_dir / DEFAULT_MODEL_WORKBOOK.name)
            tables, inventory, source = resolve_validation_model(
                no_model=True, workbook=None, search_dir=out_dir
            )
            self.assertEqual(tables, {})
            self.assertEqual(inventory, [])
            self.assertIn("validation", source.lower())


class DesktopInstanceSelectionTests(unittest.TestCase):
    """Aturan pemilihan instance Power BI Desktop, dengan data tiruan (tanpa Desktop)."""

    TWO_INSTANCES = [(111, Path("a")), (222, Path("b"))]

    def test_label_prefers_file_name(self) -> None:
        from core.xmla_client import DesktopInstance

        item = DesktopInstance(
            port=51249,
            catalog="guid",
            model_name="Model",
            modified="12/11/2026 03:32:50",
            file_name="Report Uji",
        )
        self.assertTrue(item.label.startswith("Report Uji"))

    def test_label_falls_back_to_model_name(self) -> None:
        from core.xmla_client import DesktopInstance

        item = DesktopInstance(port=51249, catalog="guid", model_name="Model", modified="")
        self.assertTrue(item.label.startswith("Model"))

    def test_desktop_file_name_strips_suffix(self) -> None:
        from core import xmla_client

        fake = subprocess.CompletedProcess(
            args="powershell",
            returncode=0,
            stdout="Report Uji - Power BI Desktop\r\n",
            stderr="",
        )
        with patch.object(xmla_client.subprocess, "run", return_value=fake):
            self.assertEqual(
                xmla_client.desktop_file_name(51249),
                "Report Uji",
            )

    def test_desktop_file_name_empty_when_not_windows(self) -> None:
        from core import xmla_client

        with patch.object(xmla_client.sys, "platform", "linux"):
            self.assertEqual(xmla_client.desktop_file_name(51249), "")

    def test_workspace_roots_cover_classic_and_store(self) -> None:
        from core import xmla_client

        roots = [str(item).lower() for item in xmla_client.workspace_roots()]
        self.assertTrue(any(item.endswith("analysisservicesworkspaces") for item in roots))
        self.assertTrue(any("power bi desktop store app" in item for item in roots))

    def test_detect_ports_reads_all_workspace_roots(self) -> None:
        from core import xmla_client

        with tempfile.TemporaryDirectory() as tmp:
            classic = Path(tmp) / "classic"
            store = Path(tmp) / "store"
            for root, port in ((classic, 11111), (store, 22222)):
                data = root / "AnalysisServicesWorkspace_x" / "Data"
                data.mkdir(parents=True)
                (data / "msmdsrv.port.txt").write_text(str(port), encoding="utf-16-le")
            with patch.object(xmla_client, "workspace_roots", return_value=[classic, store]):
                ports = sorted(port for port, _ in xmla_client.detect_ports())
        self.assertEqual(ports, [11111, 22222])


    def test_multiple_instances_without_choice_is_error(self) -> None:
        from core import xmla_client

        with patch.object(xmla_client, "detect_ports", return_value=self.TWO_INSTANCES), patch.object(
            xmla_client, "_connect", side_effect=AssertionError("tidak boleh konek")
        ), self.assertRaises(xmla_client.XmlaError) as ctx:
            xmla_client.open_client()
        message = str(ctx.exception)
        self.assertIn("localhost:111", message)
        self.assertIn("localhost:222", message)

    def test_explicit_port_never_falls_back(self) -> None:
        from core import xmla_client

        attempts: list[str] = []

        def failing_connect(connection_string, dll_path=None):
            attempts.append(connection_string)
            raise RuntimeError("gagal")

        with patch.object(xmla_client, "detect_ports", return_value=self.TWO_INSTANCES), patch.object(
            xmla_client, "_connect", side_effect=failing_connect
        ), self.assertRaises(xmla_client.XmlaError):
            xmla_client.open_client(port=111)
        self.assertEqual(attempts, ["Data Source=localhost:111"])

    def test_no_instances_lists_nothing(self) -> None:
        from core import xmla_client

        with patch.object(xmla_client, "detect_ports", return_value=[]):
            self.assertEqual(xmla_client.list_instances(), [])


@unittest.skipUnless(os.environ.get("RUN_LIVE_TESTS") == "1", "butuh Power BI Desktop terbuka")
class ModelLiveTests(unittest.TestCase):
    def test_model_counts(self) -> None:
        from core.model import run_model

        with tempfile.TemporaryDirectory() as tmp:
            summary = run_model(out_file=Path(tmp) / "Semantic_Model_Metadata.xlsx")
        self.assertEqual(summary["tables"], 11)
        self.assertEqual(summary["columns"], 94)
        self.assertEqual(summary["measures"], 51)
        self.assertEqual(summary["lineage_warnings"], 0)
        self.assertEqual(summary["unresolved_refs"], 0)


class VerifyReferenceScriptTests(unittest.TestCase):
    """Skrip verifikasi: parsing argumen dan status perbandingan."""

    def test_parse_args_reads_pbix(self) -> None:
        args = verify_reference.parse_args(["--pbix", "contoh.pbix"])
        self.assertEqual(args.pbix, "contoh.pbix")
        self.assertFalse(args.no_model)
        self.assertIsNone(args.port)
        self.assertIsNone(args.catalog)

    def test_pbix_is_required(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                verify_reference.parse_args([])

    def test_print_comparison(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.assertTrue(verify_reference.print_comparison("ok", [("pages", 9, 9)]))
            self.assertFalse(verify_reference.print_comparison("beda", [("pages", 9, 8)]))
        output = buffer.getvalue()
        self.assertIn("OK", output)
        self.assertIn("BEDA", output)

    @unittest.skipUnless(
        LIVE_SAMPLE.exists(), "set RUN_LIVE_PBIX=<file .pbix live connection>"
    )
    def test_live_source_is_rejected(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(verify_reference.main(["--pbix", str(LIVE_SAMPLE)]), 2)

    @unittest.skipUnless(
        PBIX_READY, "set RUN_PBIX=<file .pbix model lokal>"
    )
    def test_multiple_instances_require_explicit_choice(self) -> None:
        instances = [
            DesktopInstance(port=60000, catalog="a", model_name="A", modified=""),
            DesktopInstance(port=60001, catalog="b", model_name="B", modified=""),
        ]
        with patch.object(verify_reference, "list_instances", return_value=instances):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    verify_reference.main(["--pbix", str(RUN_PBIX)]), 2
                )


class ReportOutputDirTests(unittest.TestCase):
    """Folder output dibuat saat menulis, bukan saat import.

    Penting untuk paket: ``outputs\\`` tidak ikut dibundel, jadi proses pertama
    harus membuatnya sendiri (dulu gagal dengan "non-existent directory").
    """

    def test_creates_missing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            definition = Path(tmp) / "definition"
            ReportUsageTests._write_report(definition, [])
            (definition / "report.json").write_text(
                json.dumps({"name": "uji"}), encoding="utf-8"
            )
            out_file = Path(tmp) / "outputs" / "Report_Metadata.xlsx"

            run_report(
                report_def=definition,
                report_source="uji",
                tables={},
                inventory=[],
                model_source="",
                out_file=out_file,
            )

            self.assertTrue(out_file.exists())


class ConnectorRecognitionTests(unittest.TestCase):
    """Connector sumber baru dikenali `extract_connector` untuk 15_Data_Sources."""

    def test_source_connectors_are_recognized(self) -> None:
        cases = {
            "let S = PowerBI.Dataflows(null) in S": "PowerBI.Dataflows",
            "let S = Odbc.Query(\"dsn=X\", \"select 1\") in S": "Odbc.Query",
            "let S = GoogleBigQueryAad.Database(p) in S": "GoogleBigQueryAad.Database",
            "let S = SapBusinessWarehouse.Cubes(\"h\") in S": "SapBusinessWarehouse.Cubes",
            "let S = GoogleSheets.Contents(\"u\") in S": "GoogleSheets.Contents",
            "let S = Parquet.Document(File.Contents(\"a\")) in S": "Parquet.Document",
            "let S = UsageMetricsDataConnector.GetMetricsData(null) in S": (
                "UsageMetricsDataConnector.GetMetricsData"
            ),
        }
        for expression, name in cases.items():
            with self.subTest(connector=name):
                self.assertEqual(extract_connector(expression)[0], name)


if __name__ == "__main__":
    unittest.main()
