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
            "Extract PBIR report metadata from a .pbix file or from the Power BI Service "
            "into Report_Metadata.xlsx. Field validation against the model is optional."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--report",
        help="Source .pbix file (required for local sources).",
    )
    parser.add_argument("--report-url", help="URL report Power BI Service (workspace/reports).")
    parser.add_argument("--workspace-id", help="Workspace ID (GUID) for the Power BI Service source.")
    parser.add_argument("--report-id", action="append", default=[], help="Report ID (GUID); repeat for batch reports.")
    parser.add_argument("--model-workbook", help="Semantic_Model_Metadata.xlsx workbook for field validation.")
    parser.add_argument("--no-model", action="store_true", help="Lewati validasi model; cukup file .pbix.")
    parser.add_argument("--out", help=f"Path workbook output (default: {OUT_FILE.name}).")
    parser.add_argument("--extract-to", help="Save the extracted Report/definition to this folder (default: temporary).")
    return parser.parse_args(argv)


def _service_refs(args: argparse.Namespace) -> list[ServiceReportRef]:
    ids = [str(item).strip() for item in (args.report_id or []) if str(item).strip()]
    if args.report_url:
        if args.workspace_id or ids:
            raise ExtractionError(
                "Use --report-url alone, or the --workspace-id and --report-id pair."
            )
        return [parse_report_url(args.report_url)]
    if args.workspace_id or ids:
        if not (args.workspace_id and ids):
            raise ExtractionError("--workspace-id and --report-id must be provided as a pair.")
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
                    "--report (a .pbix file) cannot be combined with Power BI Service options."
                )
            if args.extract_to:
                raise ExtractionError(
                    "--extract-to is only for .pbix sources; service reports use a temporary folder."
                )
            settings = ServicePrincipal.from_env()
            token_provider = fabric_provider(EntraTokens(settings))
            if len(refs) > 1:
                out_dir = Path(args.out).resolve() if args.out else outputs_dir()
                if out_dir.suffix.lower() == ".xlsx":
                    out_dir = out_dir.parent
                if args.model_workbook:
                    print(
                        "NOTE: --model-workbook is ignored for batches; validation "
                        "uses the model workbook in the output folder.",
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
                    "A .pbix file is required via --report, or use the "
                    "Power BI Service options (--report-url / --workspace-id + --report-id)."
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
