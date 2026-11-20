"""CLI ekstraksi report: python extract_report_metadata.py [opsi]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.auth import EntraTokens, ServicePrincipal, fabric_provider
from core.errors import ExtractionError
from core.fabric_api import ServiceReportRef, parse_report_url
from core.jobs import run_metadata_job, run_report_job, run_service_report_job
from core.paths import outputs_dir
from core.report import OUT_FILE


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ekstraksi metadata report PBIR dari file .pbix atau dari Power BI Service "
            "ke Report_Metadata.xlsx. Validasi field terhadap model bersifat opsional."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--report",
        help="File .pbix sumber report (wajib untuk sumber lokal).",
    )
    parser.add_argument("--report-url", help="URL report Power BI Service (workspace/reports).")
    parser.add_argument("--workspace-id", help="Workspace ID (GUID) untuk sumber Power BI Service.")
    parser.add_argument("--report-id", action="append", default=[], help="Report ID (GUID); ulangi untuk batch report.")
    parser.add_argument("--model-workbook", help="Workbook Semantic_Model_Metadata.xlsx untuk validasi field.")
    parser.add_argument("--no-model", action="store_true", help="Lewati validasi model; cukup file .pbix.")
    parser.add_argument("--out", help=f"Path workbook output (default: {OUT_FILE.name}).")
    parser.add_argument("--extract-to", help="Simpan hasil ekstraksi Report/definition ke folder ini (default: temporary).")
    return parser.parse_args(argv)


def _service_refs(args: argparse.Namespace) -> list[ServiceReportRef]:
    ids = [str(item).strip() for item in (args.report_id or []) if str(item).strip()]
    if args.report_url:
        if args.workspace_id or ids:
            raise ExtractionError(
                "Gunakan --report-url saja, atau pasangan --workspace-id dan --report-id."
            )
        return [parse_report_url(args.report_url)]
    if args.workspace_id or ids:
        if not (args.workspace_id and ids):
            raise ExtractionError("--workspace-id dan --report-id harus diisi berpasangan.")
        return [ServiceReportRef.from_ids(args.workspace_id, item) for item in ids]
    return []


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_file = Path(args.out).resolve() if args.out else None
    try:
        refs = _service_refs(args)
        if refs:
            if args.report:
                raise ExtractionError(
                    "--report (file .pbix) tidak bisa digabung dengan opsi Power BI Service."
                )
            if args.extract_to:
                raise ExtractionError(
                    "--extract-to hanya untuk sumber .pbix; report service memakai folder temporary."
                )
            settings = ServicePrincipal.from_env()
            token_provider = fabric_provider(EntraTokens(settings))
            if len(refs) > 1:
                out_dir = Path(args.out).resolve() if args.out else outputs_dir()
                if out_dir.suffix.lower() == ".xlsx":
                    out_dir = out_dir.parent
                if args.model_workbook:
                    print(
                        "NOTE: --model-workbook diabaikan pada batch; validasi "
                        "memakai workbook model di folder output.",
                        file=sys.stderr,
                    )
                run_metadata_job(
                    service_mode=True,
                    service_reports=refs,
                    extract_report=True,
                    extract_model=False,
                    include_report_usage=False,
                    out_dir=out_dir,
                    token_provider=token_provider,
                    log=print,
                )
            else:
                run_service_report_job(
                    refs[0],
                    token_provider,
                    model_workbook=Path(args.model_workbook).resolve() if args.model_workbook else None,
                    no_model=args.no_model,
                    out_file=out_file,
                    report_kind="Power BI Service",
                    validation_dir=out_file.parent if out_file else None,
                    log=print,
                )
        else:
            if not args.report:
                raise ExtractionError(
                    "File .pbix wajib ditentukan dengan --report, atau pakai opsi "
                    "Power BI Service (--report-url / --workspace-id + --report-id)."
                )
            run_report_job(
                pbix=Path(args.report),
                model_workbook=Path(args.model_workbook).resolve() if args.model_workbook else None,
                no_model=args.no_model,
                out_file=out_file,
                extract_to=args.extract_to,
                validation_dir=out_file.parent if out_file else None,
                log=print,
            )
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0
