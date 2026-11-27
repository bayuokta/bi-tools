"""Orkestrasi capture screenshot: embed token -> browser -> cache.

Semua langkah berat (HTTP, browser) ada di modul lain paket ini. Modul ini
hanya merangkai opsi, memanggil capturer, lalu menyimpan hasil ke cache supaya
generate TSD berikutnya tidak perlu membuka browser lagi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from ..errors import ExtractionError
from ..pbix import ROOT
from .assets import SCOPES, ScreenshotSet, new_manifest, slug
from .cache import load_screenshot_set, write_capture
from .capture import MOBILE_DEFAULT_HEIGHT, MOBILE_DEFAULT_WIDTH, ReportCapturer
from .credentials import CaptureCredentials
from .embed import EmbedTokenProvider
from .hints import load_layout_hints

Log = Callable[[str], None]

GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _silent(_message: str) -> None:
    pass


def is_guid(value: str) -> bool:
    return bool(GUID_RE.match((value or "").strip()))


@dataclass
class CaptureOptions:
    """Opsi capture screenshot dari Power BI Service."""

    workspace_id: str
    report_id: str
    credentials: CaptureCredentials = field(default_factory=CaptureCredentials)
    token_provider: Any | None = None
    scope: str = "both"
    scale: float = 1.0
    headless: bool = True
    render_timeout_seconds: float = 20.0
    settle_ms: int = 800
    request_timeout_seconds: int = 30
    max_retries: int = 6
    viewport_width: int = 1600
    viewport_height: int = 1000
    output_root: Path | None = None
    refresh: bool = False
    extra_dataset_ids: tuple[str, ...] = ()
    exclude_visual_types: tuple[str, ...] = ()
    reveal_bookmarks: bool = True
    mobile: bool = True
    hints_workbook: Path | None = None
    auto_install_browser: bool = True

    def __post_init__(self) -> None:
        self.workspace_id = str(self.workspace_id or "").strip()
        self.report_id = str(self.report_id or "").strip()
        if not is_guid(self.workspace_id):
            raise ExtractionError(
                "Workspace ID must be a GUID (36 characters, e.g. "
                "11111111-1111-4111-8111-111111111111)."
            )
        if not is_guid(self.report_id):
            raise ExtractionError(
                "Report ID must be a GUID (36 characters, e.g. "
                "22222222-2222-4222-8222-222222222222)."
            )
        self.scope = str(self.scope or "both").lower()
        if self.scope not in SCOPES:
            raise ExtractionError(
                "Screenshot scope must be one of: " + ", ".join(SCOPES) + "."
            )
        try:
            self.scale = float(self.scale)
        except (TypeError, ValueError) as exc:
            raise ExtractionError("Screenshot scale must be a number (e.g. 1 or 2).") from exc
        if not 0.5 <= self.scale <= 4:
            raise ExtractionError("Screenshot scale must be between 0.5 and 4.")
        self.extra_dataset_ids = tuple(self.extra_dataset_ids or ())
        self.exclude_visual_types = tuple(self.exclude_visual_types or ())
        self.reveal_bookmarks = bool(self.reveal_bookmarks)
        self.mobile = bool(self.mobile)
        self.auto_install_browser = bool(self.auto_install_browser)
        if self.hints_workbook is not None:
            self.hints_workbook = Path(self.hints_workbook)


def default_root(options: CaptureOptions) -> Path:
    """Folder cache bawaan bila pemanggil tidak menentukan ``output_root``."""
    return ROOT / "TSD_assets" / slug(options.report_id or "capture")


def _wants_pages(scope: str) -> bool:
    return scope in ("pages", "both")


def _wants_visuals(scope: str) -> bool:
    return scope in ("visuals", "both")


def capture_report(options: CaptureOptions, log: Log = _silent) -> ScreenshotSet:
    """Buka report di browser, screenshot page/visual, simpan ke cache."""
    root = Path(options.output_root) if options.output_root else default_root(options)
    log(f"Workspace / report : {options.workspace_id} / {options.report_id}")
    log(f"Cache screenshot   : {root}")

    provider = EmbedTokenProvider(
        options.token_provider,
        options.credentials,
        request_timeout=options.request_timeout_seconds,
        max_retries=options.max_retries,
        log=log,
    )
    log("Creating embed token (RLS)...")
    embed_token = provider.get_embed_token(
        options.workspace_id, options.report_id, options.extra_dataset_ids
    )

    capturer = ReportCapturer(
        report_id=options.report_id,
        workspace_id=options.workspace_id,
        embed_token=embed_token,
        headless=options.headless,
        viewport_width=options.viewport_width,
        viewport_height=options.viewport_height,
        scale_factor=options.scale,
        render_timeout_ms=int(options.render_timeout_seconds * 1000),
        settle_ms=options.settle_ms,
        debug_dir=str(root / "_debug"),
        log=log,
        auto_install=options.auto_install_browser,
    )

    want_pages = _wants_pages(options.scope)
    want_visuals = _wants_visuals(options.scope)
    hints = load_layout_hints(options.hints_workbook)
    if hints:
        log(
            f"Layout hint       : {sum(len(v) for v in hints.values())} visuals "
            "from the report workbook"
        )
    manifest = new_manifest(options.workspace_id, options.report_id)
    page_pngs: dict[str, bytes] = {}
    visual_pngs: dict[tuple[str, str], bytes] = {}
    mobile_pngs: dict[str, bytes] = {}
    warnings: list[str] = []

    with capturer:
        pages = capturer.list_pages()
        if not pages:
            raise ExtractionError(
                "The report has no capturable pages "
                " (hidden pages are not returned by the embed API)."
            )
        log(f"Found {len(pages)} pages; starting capture.")
        for ordinal, page in enumerate(pages, start=1):
            name = str(page.get("name") or "")
            label = str(page.get("displayName") or name)
            log(f"Capture page {ordinal:02d} '{label}' ...")
            result = capturer.capture_page(
                name,
                want_page_png=want_pages,
                want_visual_pngs=want_visuals,
                exclude_types=options.exclude_visual_types,
                reveal_bookmarks=options.reveal_bookmarks,
                hints=hints.get(name) or None,
            )
            manifest["pages"].append(
                {
                    "name": name,
                    "displayName": label,
                    "isActive": page.get("isActive"),
                    "ordinal": ordinal,
                    "mobileLayout": bool(page.get("hasMobileLayout")),
                    "visuals": result.get("visuals") or [],
                    "revealedBookmark": result.get("revealed_bookmark") or "",
                }
            )
            if result.get("page_png"):
                page_pngs[name] = result["page_png"]
            for visual_name, png in (result.get("visual_pngs") or {}).items():
                visual_pngs[(name, visual_name)] = png
            if result.get("debug"):
                warnings.append(f"{label}: {result['debug']}")

    mobile_enabled = bool(options.mobile and want_pages)
    mobile_layout_names: set[str] = set()
    if mobile_enabled:
        mobile_capturer = ReportCapturer(
            report_id=options.report_id,
            workspace_id=options.workspace_id,
            embed_token=embed_token,
            headless=options.headless,
            viewport_width=MOBILE_DEFAULT_WIDTH,
            viewport_height=MOBILE_DEFAULT_HEIGHT,
            scale_factor=options.scale,
            render_timeout_ms=int(options.render_timeout_seconds * 1000),
            settle_ms=options.settle_ms,
            debug_dir=str(root / "_debug"),
            layout_type=2,
            auto_install=options.auto_install_browser,
            log=log,
        )
        try:
            with mobile_capturer:
                # hasLayout hanya akurat di embed mobile, bukan embed desktop.
                mobile_pages_all = mobile_capturer.list_pages()
                mobile_pages = [
                    page
                    for page in mobile_pages_all
                    if page.get("hasMobileLayout")
                ]
                mobile_layout_names = {
                    str(page.get("name") or "") for page in mobile_pages
                }
                if not mobile_pages:
                    log(
                        "No pages have a mobile layout; "
                        "mobile screenshots are skipped."
                    )
                else:
                    log(
                        f"Capture mobile layout {len(mobile_pages)} pages "
                        f"out of {len(mobile_pages_all)} pages."
                    )
                    for ordinal, page in enumerate(mobile_pages, start=1):
                        name = str(page.get("name") or "")
                        label = str(page.get("displayName") or name)
                        log(
                            f"Capture mobile {ordinal:02d}/{len(mobile_pages)} "
                            f"'{label}' ..."
                        )
                        try:
                            mobile_pngs[name] = (
                                mobile_capturer.capture_mobile_page(
                                    name, page.get("mobileSize")
                                )
                            )
                        except Exception as exc:  # noqa: BLE001 - lanjut page lain
                            warnings.append(f"mobile {label}: {exc}")
        except Exception as exc:  # noqa: BLE001 - jangan batalkan capture desktop
            warnings.append(f"mobile layout: {exc}")
            log(f"WARNING: mobile layout capture failed: {exc}")

    for entry in manifest["pages"]:
        entry["mobileLayout"] = str(entry.get("name") or "") in mobile_layout_names

    cached = write_capture(
        root,
        manifest,
        page_pngs,
        visual_pngs,
        mobile_pngs,
        scope=options.scope,
        workspace_id=options.workspace_id,
        report_id=options.report_id,
        rls_username=options.credentials.rls_username,
        rls_roles=options.credentials.rls_roles,
        excludes=options.exclude_visual_types,
        mobile_enabled=mobile_enabled,
        warnings=warnings,
    )
    log(
        f"Screenshot tersimpan: {cached.page_count} page, "
        f"{cached.visual_count} visual, {cached.mobile_count} mobile."
    )
    if cached.missing:
        log(
            f"{len(cached.missing)} files were not mapped to DOM elements "
            " (see capture.json)."
        )
    for warning in warnings:
        log(f"WARNING: {warning}")
    return cached


def load_or_capture(
    options: CaptureOptions,
    log: Log = _silent,
) -> ScreenshotSet:
    """Pakai cache bila cocok (workspace/report/cakupan), selain itu capture."""
    root = Path(options.output_root) if options.output_root else default_root(options)
    if not options.refresh:
        cached = load_screenshot_set(root)
        if cached is not None and cached.matches(
            options.workspace_id,
            options.report_id,
            options.scope,
            require_mobile=options.mobile,
        ):
            log(f"Screenshot cache used: {root} ({cached.summary()}).")
            return cached
        log("The screenshot cache is missing or does not match; running a new capture.")
    else:
        log("Screenshot refresh requested; running a new capture.")
    return capture_report(replace(options, output_root=root), log=log)
