"""CLI analisa semantic model: ukuran kolom + pemakaian di semua report.

Contoh:

    python analyze_semantic_model.py --workspace-id <ws> --dataset-id <ds>
    python analyze_semantic_model.py --workspace-id <ws> --dataset-id <ds> --list-reports
    python analyze_semantic_model.py --workspace-id <ws> --dataset-id <ds> --refresh --max-reports 20
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from core.auth import ServicePrincipal
from core.errors import ExtractionError
from core.lineage_store import DEFAULT_DB
from core.best_practice import build_best_practice
from core.model_health import build_health
from core.pbix import ROOT
from core.requests import AnalysisRequest
from core.usage_service import (
    analyze_dataset,
    discover_reports,
    format_bytes,
    output_file_name,
    resolve_names,
    write_workbook,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a Power BI Service semantic model: column sizes (DMV), "
            "usage across all reports using the dataset, and a safe-to-remove verdict."
        ),
        allow_abbrev=False,
    )
    parser.add_argument("--workspace-id", required=True, help="Workspace ID (GUID).")
    parser.add_argument("--dataset-id", required=True, help="Semantic model ID (GUID).")
    parser.add_argument("--workspace-name", help="Workspace name (default: SQLite catalog).")
    parser.add_argument("--dataset-name", help="Semantic model name (default: SQLite catalog).")
    parser.add_argument("--out", help="Output workbook path (default: Analysis_<name>_<id8>.xlsx).")
    parser.add_argument("--db", help=f"Database SQLite (default: {DEFAULT_DB}).")
    parser.add_argument(
        "--workspace-only",
        action="store_true",
        help="Only reports in the dataset workspace; do not use the cross-workspace admin API.",
    )
    parser.add_argument(
        "--include-personal",
        action="store_true",
        help=(
            "Include reports in My Workspace (personal). Skipped by default because "
            "the service principal has no access there."
        ),
    )
    parser.add_argument("--refresh", action="store_true", help="Force download of all report definitions.")
    parser.add_argument(
        "--model-only",
        action="store_true",
        help=(
            "Analyze model metadata only (columns, sizes, measures, relationships, M). "
            "Reports are not downloaded; unreferenced columns become 'Needs review'."
        ),
    )
    parser.add_argument("--max-reports", type=int, help="Maximum number of new reports scanned per run.")
    parser.add_argument(
        "--scan-workers",
        type=int,
        default=2,
        help=(
            "Number of report definitions downloaded concurrently (1-4, default 2). "
            "Falls back to 1 when Fabric returns 429."
        ),
    )
    parser.add_argument("--list-reports", action="store_true", help="Only list reports using the dataset.")
    return parser.parse_args(argv)


def _names(args: argparse.Namespace) -> tuple[str, str]:
    workspace_name = str(args.workspace_name or "").strip()
    dataset_name = str(args.dataset_name or "").strip()
    if workspace_name and dataset_name:
        return workspace_name, dataset_name
    database = Path(args.db) if args.db else DEFAULT_DB
    from_catalog_ws, from_catalog_ds = resolve_names(
        database, args.workspace_id, args.dataset_id
    )
    return workspace_name or from_catalog_ws, dataset_name or from_catalog_ds


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        request = AnalysisRequest(
            workspace_id=args.workspace_id,
            dataset_id=args.dataset_id,
            output=args.out,
            database=args.db,
            include_other_workspaces=not args.workspace_only,
            include_personal=args.include_personal,
            include_reports=not args.model_only,
            refresh=args.refresh,
            max_reports=args.max_reports,
            scan_workers=args.scan_workers,
        )
        principal = ServicePrincipal.from_env()
        workspace_name, dataset_name = _names(args)
        request = replace(
            request, workspace_name=workspace_name, dataset_name=dataset_name
        )

        if args.list_reports:
            entries, method, notes = discover_reports(
                principal,
                dataset_id=request.dataset_id,
                workspace_id=request.workspace_id,
                include_other_workspaces=request.include_other_workspaces,
                database=request.database or DEFAULT_DB,
                log=print,
            )
            print(f"List source    : {method}")
            print(f"Report count   : {len(entries)}")
            for index, entry in enumerate(entries, start=1):
                status = "" if entry.supported else "  [not analyzed]"
                print(
                    f"  {index:3d}. {entry.label}  {entry.report_format or '?'}"
                    f"{status}"
                )
            for note in notes:
                print(f"NOTE: {note}")
            return 0

        result = analyze_dataset(
            **request.to_run_kwargs(),
            principal=principal,
            log=print,
            progress=lambda index, total, name: print(
                f"  scanning {index}/{total}: {name}"
            ),
        )
        target = request.output or (ROOT / output_file_name(dataset_name, request.dataset_id))
        path = write_workbook(result, target)

        print()
        print(f"Model size        : {format_bytes(result.dataset_bytes)}")
        print(f"Columns           : {len(result.columns)}")
        print(f"Unused            : {len(result.unused)} ({format_bytes(result.unused_bytes)})")
        for status, count in sorted(result.status_counts.items()):
            print(f"  {status:<24}: {count}")
        print(f"Report coverage   : {result.coverage} ({result.method})")
        health = build_health(result)
        print(
            "Health            : "
            f"{health['counts']['critical']} critical · "
            f"{health['counts']['warning']} warning · "
            f"{health['counts']['info']} info"
        )
        best_practice = build_best_practice(result)
        print(
            "Best practice     : "
            f"score {best_practice.get('score', 0)} · "
            f"{best_practice.get('verdict', '-')} · "
            f"{best_practice.get('evaluated', 0)}/"
            f"{best_practice.get('rule_count', 0)} rules evaluated"
        )
        print(f"Workbook          : {path}")
        return 0
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
