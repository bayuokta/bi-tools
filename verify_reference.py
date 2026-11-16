"""Verifikasi angka acuan report & model terhadap hasil ekstraksi terbaru.

Jalankan setelah Power BI Desktop terbuka agar model ikut diperiksa:

    python verify_reference.py

Tanpa Desktop, report tetap diperiksa (validasi memakai workbook model yang
sudah ada bila tersedia). Exit code: 0 semua cocok, 1 ada perbedaan,
2 tidak bisa dijalankan (file/instance ambigu).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from core.errors import ExtractionError
from core.jobs import run_report_job
from core.model import DEFAULT_OUT as DEFAULT_MODEL_OUT
from core.model import run_model
from core.pbix import DEFAULT_PBIX, display_path, detect_pbix_source
from core.report import DEFAULT_MODEL_WORKBOOK, OUT_FILE
from core.xmla_client import DesktopInstance, list_instances

REFERENCE_REPORT = {
    "pages": 10,
    "visuals": 137,
    "fields": 207,
    "slicers": 76,
    "sync_slicers": 74,
    "filters": 32,
    "interactions": 11,
    "measures": 51,
    "columns": 94,
}

REFERENCE_MODEL = {
    "tables": 11,
    "columns": 94,
    "measures": 51,
    "lineage_warnings": 0,
    "unresolved_refs": 0,
}

REPORT_SHEETS = 13
MODEL_SHEETS = 24


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ekstrak ulang report/model ke folder sementara, lalu bandingkan hasilnya "
            "dengan angka acuan report/model. Tidak menimpa workbook di folder tooling."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--pbix",
        help="File .pbix sumber (default: berkas .pbix bawaan di folder tooling).",
    )
    parser.add_argument("--port", type=int, help="Port instance Power BI Desktop (lihat --list-instances).")
    parser.add_argument("--catalog", help="Nama catalog/dataset untuk XMLA (opsional bila hanya satu instance).")
    parser.add_argument("--model-workbook", help="Workbook model pengganti untuk validasi report.")
    parser.add_argument("--no-model", action="store_true", help="Lewati ekstraksi model; bandingkan report saja.")
    parser.add_argument("--out-dir", help="Simpan hasil ekstraksi ke folder ini (default: temporary, dihapus).")
    return parser.parse_args(argv)


def sheet_count(path: Path) -> int:
    with pd.ExcelFile(path) as workbook:
        return len(workbook.sheet_names)


def print_comparison(title: str, rows: list[tuple[str, Any, Any]]) -> bool:
    """Cetak tabel acuan vs hasil. Return True bila semua baris cocok."""
    width = max(len(name) for name, _, _ in rows)
    print(title)
    print(f"  {'Metrik'.ljust(width)}  {'Acuan':>7}  {'Hasil':>7}  Status")
    ok = True
    for name, expected, actual in rows:
        status = "OK" if expected == actual else "BEDA"
        ok = ok and status == "OK"
        print(f"  {name.ljust(width)}  {expected:>7}  {actual:>7}  {status}")
    print()
    return ok


def print_instances(instances: list[DesktopInstance]) -> None:
    for index, item in enumerate(instances, start=1):
        print(f"  {index}. {item.label}")
        print(f"     --port {item.port}  --catalog {item.catalog}")


def resolve_instance(args: argparse.Namespace) -> tuple[int | None, str | None, int]:
    """Tentukan target XMLA. Return (port, catalog, exit_code); exit_code != 0 berarti berhenti."""
    if args.port is not None or args.catalog:
        return args.port, args.catalog, 0

    try:
        instances = list_instances()
    except ExtractionError as exc:
        print(f"ERROR: gagal membaca instance Power BI Desktop: {exc}", file=sys.stderr)
        return None, None, 2
    if len(instances) == 1:
        item = instances[0]
        print(f"Instance : {item.label}")
        print()
        return item.port, item.catalog, 0
    if not instances:
        print("Instance : tidak ada Power BI Desktop yang terbuka; model tidak akan diekstrak.")
        print()
        return None, None, 0

    print("Ada lebih dari satu instance Power BI Desktop. Pilih satu secara eksplisit:")
    print_instances(instances)
    print("\nUlangi dengan --port/--catalog yang sesuai.")
    return None, None, 2


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pbix = Path(args.pbix).expanduser().resolve() if args.pbix else DEFAULT_PBIX.resolve()
    try:
        source = detect_pbix_source(pbix)
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not source.has_local_model:
        print(f"ERROR: angka acuan hanya untuk model lokal; {display_path(pbix)} terdeteksi sebagai {source.label}.", file=sys.stderr)
        return 2

    print(f"Sumber   : {display_path(pbix)}")
    print(f"Jenis    : {source.label}")
    print()

    port: int | None = None
    catalog: str | None = None
    if not args.no_model:
        port, catalog, code = resolve_instance(args)
        if code:
            return code

    workdir = Path(tempfile.mkdtemp(prefix="verify-reference-")) if not args.out_dir else Path(args.out_dir).expanduser().resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    report_out = workdir / OUT_FILE.name
    model_out = workdir / DEFAULT_MODEL_OUT.name
    print(f"Output   : {workdir}")
    print()

    model_summary: dict[str, Any] | None = None
    if not args.no_model and (port is not None or catalog):
        print("=== Ekstraksi semantic model (XMLA) ===")
        try:
            model_summary = run_model(
                endpoint=None,
                catalog=catalog,
                port=port,
                report=pbix,
                no_report=False,
                out_file=model_out,
                log=print,
            )
        except ExtractionError as exc:
            print(f"WARNING: ekstraksi model gagal: {exc}")
            print("WARNING: report akan divalidasi dengan workbook model yang ada (bila tersedia).")
        print()
    elif args.no_model:
        print("Model    : dilewati (--no-model)")
        print()
    else:
        print("Model    : dilewati (tidak ada instance Desktop)")
        print()

    validation_workbook: Path | None = None
    if model_summary is not None:
        validation_workbook = model_out
    elif args.model_workbook:
        validation_workbook = Path(args.model_workbook).expanduser().resolve()
    elif DEFAULT_MODEL_WORKBOOK.exists():
        validation_workbook = DEFAULT_MODEL_WORKBOOK
    if validation_workbook is not None and not validation_workbook.exists():
        print(f"WARNING: workbook validasi tidak ditemukan: {validation_workbook}")
        validation_workbook = None

    print("=== Ekstraksi report ===")
    try:
        report_summary = run_report_job(
            pbix=pbix,
            model_workbook=validation_workbook,
            no_model=validation_workbook is None,
            out_file=report_out,
            report_kind=source.label,
            log=print,
        )
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print()

    rows = [(name, expected, report_summary.get(name, -1)) for name, expected in REFERENCE_REPORT.items()]
    ok = print_comparison("=== Angka acuan report ===", rows)

    skipped = int(report_summary.get("validation_skipped", 0))
    issues = int(report_summary.get("validation_issues", -1))
    print("=== Validasi field ===")
    if skipped:
        print(f"  Masalah validasi  acuan=0  hasil={issues}  SKIP ({skipped} field tidak divalidasi)")
        print("  Jalankan dengan instance Desktop (atau --model-workbook) agar validasi ikut diperiksa.")
        ok = False
    else:
        print(f"  Masalah validasi  acuan=0  hasil={issues}  {'OK' if issues == 0 else 'BEDA'}")
        ok = ok and issues == 0
    print()

    if model_summary is not None:
        rows = [(name, expected, model_summary.get(name, -1)) for name, expected in REFERENCE_MODEL.items()]
        ok = print_comparison("=== Angka acuan model ===", rows) and ok
    else:
        print("=== Angka acuan model ===")
        if args.no_model:
            print("  Dilewati (--no-model).")
        else:
            print("  Dilewati: model tidak diekstrak pada jalankan ini.")
            print("  Buka Power BI Desktop atau pakai --port/--catalog agar model ikut diverifikasi.")
            ok = False
        print()

    sheet_rows = [("report sheets", REPORT_SHEETS, sheet_count(report_out))]
    if model_summary is not None and model_out.exists():
        sheet_rows.append(("model sheets", MODEL_SHEETS, sheet_count(model_out)))
    ok = print_comparison("=== Jumlah sheet ===", sheet_rows) and ok

    if ok:
        print("HASIL: semua angka acuan cocok.")
        return 0
    print("HASIL: ada angka yang belum cocok atau belum diverifikasi (lihat status BEDA/SKIP).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
