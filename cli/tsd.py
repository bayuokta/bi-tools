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
            "Generate dokumen TSD (HTML gaya Confluence) dari Report_Metadata.xlsx "
            "dan Semantic_Model_Metadata.xlsx."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--report",
        help=f"Workbook report (default: {OUT_FILE.name} di folder tooling).",
    )
    parser.add_argument(
        "--model",
        help=(
            "Workbook model (default: "
            f"{MODEL_WORKBOOK_NAME} di folder tooling bila ada)."
        ),
    )
    parser.add_argument(
        "--manual",
        help="File JSON override manual (default: <nama output>.json di folder yang sama).",
    )
    parser.add_argument("--out", help="File HTML output (default: TSD_<nama report>.html).")
    parser.add_argument("--name", help="Nama report untuk judul dan nama file output.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--draft",
        action="store_true",
        help="Tampilkan TODO dan teks instruksi untuk field kosong (default).",
    )
    mode.add_argument(
        "--final",
        action="store_true",
        help="Sembunyikan TODO dan teks instruksi (dokumen final).",
    )
    parser.add_argument(
        "--expand-all",
        action="store_true",
        help="Buka semua panel expand (default: tertutup).",
    )
    parser.add_argument(
        "--template",
        help="Path template Jinja2 (default: templates\\tsd.template.html).",
    )
    service = parser.add_argument_group(
        "Screenshot Power BI Service",
        "Capture gambar page/visual untuk section 2.2.7.1 Web layout.",
    )
    service.add_argument(
        "--screenshots",
        action="store_true",
        help="Ambil screenshot page & visual dari Power BI Service.",
    )
    service.add_argument(
        "--workspace-id",
        help="ID workspace report (atau environment PBI_WORKSPACE_ID).",
    )
    service.add_argument(
        "--report-id",
        help="ID report Power BI Service (atau environment PBI_REPORT_ID).",
    )
    service.add_argument(
        "--rls-username",
        help="Username identitas RLS (default RLS_USERNAME di .env).",
    )
    service.add_argument(
        "--rls-roles",
        help="Daftar role RLS dipisah koma, mis. HO,Region (default RLS_ROLES).",
    )
    service.add_argument(
        "--screenshot-scope",
        choices=["both", "pages", "visuals"],
        default="both",
        help="Cakupan capture (default: both).",
    )
    service.add_argument(
        "--screenshot-scale",
        type=float,
        default=1.0,
        help="Skala resolusi screenshot 0.5-4 (default: 1).",
    )
    service.add_argument(
        "--screenshot-dir",
        help=(
            "Folder cache screenshot (default: "
            "TSD_assets\\<nama report> di folder output)."
        ),
    )
    service.add_argument(
        "--refresh-screenshots",
        action="store_true",
        help="Paksa capture baru walau cache masih ada.",
    )
    service.add_argument(
        "--no-reveal-bookmarks",
        action="store_true",
        help=(
            "Jangan coba bookmark untuk memunculkan visual tersembunyi."
        ),
    )
    service.add_argument(
        "--no-mobile-screenshots",
        action="store_true",
        help=(
            "Jangan ambil screenshot mobile layout (2.2.7.2). Default: aktif "
            "bila halaman punya mobile layout."
        ),
    )
    service.add_argument(
        "--headed",
        action="store_true",
        help="Tampilkan jendela browser saat capture (debug).",
    )
    parser.add_argument(
        "--include-decorative-visuals",
        action="store_true",
        help=(
            "Sertakan shape/image/textbox/tombol sebagai baris visual di TSD "
            "dan screenshot-nya (default: disembunyikan, slicer tetap tampil)."
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
            "--screenshots membutuhkan --workspace-id dan --report-id "
            "(atau environment PBI_WORKSPACE_ID / PBI_REPORT_ID)."
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
        hints_workbook=Path(args.report).resolve() if args.report else OUT_FILE,
    )
    return request.to_options(tokens)
