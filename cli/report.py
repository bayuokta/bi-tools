"""CLI ekstraksi report: python extract_report_metadata.py [opsi]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.auth import EntraTokens, ServicePrincipal, fabric_provider
from core.errors import ExtractionError
from core.fabric_api import ServiceReportRef, parse_report_url
from core.jobs import run_report_job, run_service_report_job
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
        help="File .pbix sumber report (default: berkas .pbix bawaan di folder tooling).",
    )
    parser.add_argument("--report-url", help="URL report Power BI Service (workspace/reports).")
    parser.add_argument("--workspace-id", help="Workspace ID (GUID) untuk sumber Power BI Service.")
    parser.add_argument("--report-id", help="Report ID (GUID) untuk sumber Power BI Service.")
    parser.add_argument("--model-workbook", help="Workbook Semantic_Model_Metadata.xlsx untuk validasi field.")
    parser.add_argument("--no-model", action="store_true", help="Lewati validasi model; cukup file .pbix.")
    parser.add_argument("--out", help=f"Path workbook output (default: {OUT_FILE.name}).")
    parser.add_argument("--extract-to", help="Simpan hasil ekstraksi Report/definition ke folder ini (default: temporary).")
    return parser.parse_args(argv)


def _service_ref(args: argparse.Namespace) -> ServiceReportRef | None:
    if args.report_url:
        if args.workspace_id or args.report_id:
            raise ExtractionError(
                "Gunakan --report-url saja, atau pasangan --workspace-id dan --report-id."
            )
        return parse_report_url(args.report_url)
    if args.workspace_id or args.report_id:
        if not (args.workspace_id and args.report_id):
            raise ExtractionError("--workspace-id dan --report-id harus diisi berpasangan.")
        return ServiceReportRef.from_ids(args.workspace_id, args.report_id)
    return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_file = Path(args.out).resolve() if args.out else None
    try:
        service = _service_ref(args)
        if service is not None:
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
            run_service_report_job(
                service,
                token_provider,
                model_workbook=Path(args.model_workbook).resolve() if args.model_workbook else None,
                no_model=args.no_model,
                out_file=out_file,
                report_kind="Power BI Service",
                validation_dir=out_file.parent if out_file else None,
                log=print,
            )
        else:
            run_report_job(
                pbix=Path(args.report) if args.report else None,
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
