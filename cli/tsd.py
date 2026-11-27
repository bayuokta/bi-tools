"""CLI generate TSD: python extract_tsd.py [opsi]."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from core.auth import (
    DeferredTokenProvider,
    EntraTokens,
    ServicePrincipal,
    powerbi_provider,
)
from core.errors import ExtractionError
from core.pbi_capture import CaptureCredentials, CaptureOptions
from core.pbi_capture.credentials import split_roles
from core.pbix import ROOT
from core.report import OUT_FILE
from core.requests import CaptureRequest, TsdRequest
from core.tsd import MODEL_WORKBOOK_NAME, run_tsd


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the TSD document (Confluence-style HTML) from Report_Metadata.xlsx "
            "and Semantic_Model_Metadata.xlsx."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--report",
        help=f"Report workbook (default: {OUT_FILE.name} in the tooling folder).",
    )
    parser.add_argument(
        "--model",
        help=(
            "Workbook model (default: "
            f"{MODEL_WORKBOOK_NAME} in the tooling folder when present)."
        ),
    )
    parser.add_argument(
        "--manual",
        help="Manual override JSON file (default: <output name>.json in the same folder).",
    )
    parser.add_argument("--out", help="Output HTML file (default: TSD_<report name>.html).")
    parser.add_argument("--name", help="Report name for the title and output file name.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--draft",
        action="store_true",
        help="Show TODO and instruction text for empty fields (default).",
    )
    mode.add_argument(
        "--final",
        action="store_true",
        help="Hide TODO and instruction text (final document).",
    )
    parser.add_argument(
        "--expand-all",
        action="store_true",
        help="Open all expand panels (default: collapsed).",
    )
    parser.add_argument(
        "--template",
        help="Jinja2 template path (default: templates\\tsd.template.html).",
    )
    service = parser.add_argument_group(
        "Power BI Service screenshots",
        "Capture page/visual images for section 2.2.7.1 Web layout.",
    )
    service.add_argument(
        "--screenshots",
        action="store_true",
        help="Capture page & visual screenshots from the Power BI Service.",
    )
    service.add_argument(
        "--workspace-id",
        help="Report workspace ID (or the PBI_WORKSPACE_ID environment variable).",
    )
    service.add_argument(
        "--report-id",
        help="Power BI Service report ID (or the PBI_REPORT_ID environment variable).",
    )
    service.add_argument(
        "--rls-username",
        help="RLS identity username (default RLS_USERNAME in .env).",
    )
    service.add_argument(
        "--rls-roles",
        help="Comma-separated RLS roles, e.g. HO,Region (default RLS_ROLES).",
    )
    service.add_argument(
        "--screenshot-scope",
        choices=["both", "pages", "visuals"],
        default="both",
        help="Capture scope (default: both).",
    )
    service.add_argument(
        "--screenshot-scale",
        type=float,
        default=1.0,
        help="Screenshot resolution scale 0.5-4 (default: 1).",
    )
    service.add_argument(
        "--screenshot-dir",
        help=(
            "Screenshot cache folder (default: "
            "TSD_assets\\<report name> in the output folder)."
        ),
    )
    service.add_argument(
        "--refresh-screenshots",
        action="store_true",
        help="Force a new capture even when the cache exists.",
    )
    service.add_argument(
        "--no-reveal-bookmarks",
        action="store_true",
        help=(
            "Do not try bookmarks to reveal hidden visuals."
        ),
    )
    service.add_argument(
        "--no-mobile-screenshots",
        action="store_true",
        help=(
            "Do not capture mobile layout screenshots (2.2.7.2). Default: enabled "
            "when a page has a mobile layout."
        ),
    )
    service.add_argument(
        "--no-auto-install-browser",
        action="store_true",
        help=(
            "Do not download Chromium automatically when missing. Default: capture "
            "downloads it via the Playwright driver on the first attempt."
        ),
    )
    service.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window during capture (debug).",
    )
    parser.add_argument(
        "--include-decorative-visuals",
        action="store_true",
        help=(
            "Include shape/image/textbox/button as visual rows in the TSD "
            "and their screenshots (default: hidden, slicers still shown)."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    default_model = ROOT / MODEL_WORKBOOK_NAME
    model = Path(args.model).resolve() if args.model else default_model
    if not args.model and not default_model.exists():
        model = None
    try:
        capture = _capture_options(args)
        request = TsdRequest(
            report_workbook=Path(args.report).resolve() if args.report else OUT_FILE,
            model_workbook=model,
            out_file=Path(args.out).resolve() if args.out else None,
            manual_path=Path(args.manual).resolve() if args.manual else None,
            report_name=args.name or "",
            report_id=args.report_id or "",
            draft=not args.final,
            expand_all=args.expand_all,
            template_path=Path(args.template).resolve() if args.template else None,
            include_decorative=args.include_decorative_visuals,
        )
        run_tsd(**request.to_run_kwargs(), capture=capture, log=print)
    except ExtractionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


def _capture_options(args: argparse.Namespace) -> CaptureOptions | None:
    """Susun opsi capture dari argumen CLI + environment/.env."""
    if not args.screenshots:
        return None
    workspace_id = (args.workspace_id or os.getenv("PBI_WORKSPACE_ID", "")).strip()
    report_id = (args.report_id or os.getenv("PBI_REPORT_ID", "")).strip()
    if not workspace_id or not report_id:
        raise ExtractionError(
            "--screenshots requires --workspace-id and --report-id "
            " (or the PBI_WORKSPACE_ID / PBI_REPORT_ID environment variables)."
        )
    base = CaptureCredentials.from_env()
    tokens = DeferredTokenProvider(
        lambda: powerbi_provider(EntraTokens(ServicePrincipal.from_env()))
    )
    request = CaptureRequest(
        workspace_id=workspace_id,
        report_id=report_id,
        rls_username=args.rls_username or base.rls_username,
        rls_roles=split_roles(args.rls_roles) if args.rls_roles else base.rls_roles,
        scope=args.screenshot_scope,
        scale=args.screenshot_scale,
        headless=not args.headed,
        output_root=Path(args.screenshot_dir).resolve()
        if args.screenshot_dir
        else None,
        refresh=args.refresh_screenshots,
        reveal_bookmarks=not args.no_reveal_bookmarks,
        mobile=not args.no_mobile_screenshots,
        include_decorative=args.include_decorative_visuals,
        auto_install_browser=not args.no_auto_install_browser,
        hints_workbook=Path(args.report).resolve() if args.report else OUT_FILE,
    )
    return request.to_options(tokens)
