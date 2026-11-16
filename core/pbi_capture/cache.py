"""Simpan dan muat cache screenshot di ``TSD_assets\\<nama report>``.

Cache membuat generate TSD berikutnya tidak perlu membuka browser lagi.
Isi folder: ``pages\\*.png``, ``visuals\\<halaman>\\*.png``, ``manifest.json``
(daftar page/visual + path hasil), dan ``capture.json`` (waktu ambil,
workspace/report, role RLS, daftar file hilang).

Cache tidak pernah menyimpan token atau client secret.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from .assets import (
    ScreenshotSet,
    build_items,
    save_json,
    slug,
)

MANIFEST_NAME = "manifest.json"
CAPTURE_NAME = "capture.json"

# Naikkan bila algoritma pairing/penamaan berubah: cache lama tidak dipakai lagi
# supaya gambar yang salah tidak ikut terbawa.
CAPTURE_VERSION = 5


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def write_capture(
    root: Path,
    manifest: Mapping,
    page_pngs: Mapping[str, bytes],
    visual_pngs: Mapping[tuple[str, str], bytes],
    mobile_pngs: Mapping[str, bytes] | None = None,
    *,
    scope: str = "both",
    workspace_id: str = "",
    report_id: str = "",
    rls_username: str = "",
    rls_roles: Iterable[str] = (),
    excludes: Iterable[str] | None = None,
    mobile_enabled: bool = False,
    warnings: Iterable[str] = (),
) -> ScreenshotSet:
    """Tulis PNG + manifest ke cache lalu kembalikan ``ScreenshotSet``."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    data = json.loads(json.dumps(manifest))  # salinan dalam, tanpa efek samping
    data.setdefault("generatedAt", datetime.now(timezone.utc).isoformat())
    data.setdefault("workspaceId", workspace_id)
    data.setdefault("reportId", report_id)
    data.setdefault("captureVersion", CAPTURE_VERSION)

    items, skipped = build_items(
        data, root, scope=scope, exclude_visual_types=excludes
    )
    page_by_name = {str(p.get("name") or ""): p for p in data.get("pages") or []}
    saved = {"page": 0, "visual": 0, "mobile": 0}
    missing: list[str] = []

    for item in items:
        if item.kind == "page":
            png = page_pngs.get(item.page_name)
            label = item.page_display_name
        elif item.kind == "mobile":
            png = (mobile_pngs or {}).get(item.page_name)
            label = f"{item.page_display_name} (mobile)"
        else:
            png = visual_pngs.get((item.page_name, item.visual_name))
            label = f"{item.page_display_name} / {item.visual_title or item.visual_name}"
        if not png:
            missing.append(f"{item.kind}: {label}")
            continue
        item.output_path.parent.mkdir(parents=True, exist_ok=True)
        item.output_path.write_bytes(png)
        saved[item.kind] += 1
        page = page_by_name.get(item.page_name)
        if page is None:
            continue
        if item.kind == "page":
            page["output"] = _rel(root, item.output_path)
        elif item.kind == "mobile":
            page["mobileOutput"] = _rel(root, item.output_path)
        else:
            for visual in page.get("visuals") or []:
                if str(visual.get("name") or "") == item.visual_name:
                    visual["output"] = _rel(root, item.output_path)

    save_json(root / MANIFEST_NAME, data)
    revealed = [
        {
            "page": str(page.get("displayName") or page.get("name") or ""),
            "bookmark": str(page.get("revealedBookmark") or ""),
        }
        for page in data.get("pages") or []
        if page.get("revealedBookmark")
    ]
    save_json(
        root / CAPTURE_NAME,
        {
            "captureVersion": CAPTURE_VERSION,
            "generatedAt": data["generatedAt"],
            "workspaceId": workspace_id,
            "reportId": report_id,
            "scope": scope,
            "rlsUsername": rls_username,
            "rlsRoles": list(rls_roles),
            "pageCount": saved["page"],
            "visualCount": saved["visual"],
            "mobileCount": saved["mobile"],
            "mobileEnabled": bool(mobile_enabled),
            "excludedVisuals": skipped,
            "revealed": revealed,
            "missing": missing,
            "warnings": [str(item) for item in warnings],
        },
    )
    cached = load_screenshot_set(root)
    if cached is None:  # tidak mungkin kecuali penulisan gagal; jaga-jaga
        return ScreenshotSet(
            root=root,
            workspace_id=workspace_id,
            report_id=report_id,
            scope=scope,
            mobile_enabled=mobile_enabled,
            captured_at=str(data["generatedAt"]),
            rls_username=rls_username,
            rls_roles=tuple(rls_roles),
            warnings=tuple(str(item) for item in warnings),
            missing=tuple(missing),
        )
    return cached


def load_screenshot_set(root: Path) -> ScreenshotSet | None:
    """Muat cache screenshot; ``None`` bila folder belum berisi capture."""
    root = Path(root)
    manifest_path = root / MANIFEST_NAME
    capture_path = root / CAPTURE_NAME
    if not manifest_path.exists() or not capture_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        meta = json.loads(capture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict) or not isinstance(meta, dict):
        return None
    if int(manifest.get("captureVersion") or 0) != CAPTURE_VERSION:
        return None

    manifest_pages = manifest.get("pages") or []
    if not isinstance(manifest_pages, list):
        return None

    # Manifest lama (tool pbi-download-image) belum menyimpan path hasil;
    # bangun ulang dari aturan penamaan yang sama.
    needs_fallback = any(
        "output" not in page
        or (page.get("mobileLayout") and "mobileOutput" not in page)
        or any("output" not in visual for visual in page.get("visuals") or [])
        for page in manifest_pages
    )
    fallback: dict[tuple[str, str, str], Path] = {}
    if needs_fallback:
        items, _skipped = build_items(manifest, root, scope="both")
        fallback = {
            (item.kind, item.page_name, item.visual_name): item.output_path
            for item in items
        }

    pages: dict[str, Path] = {}
    visuals: dict[tuple[str, str], Path] = {}
    mobile: dict[str, Path] = {}
    page_titles: dict[str, str] = {}
    visual_titles: dict[tuple[str, str], str] = {}

    for page in manifest_pages:
        if not isinstance(page, dict):
            continue
        name = str(page.get("name") or "")
        if not name:
            continue
        label = str(page.get("displayName") or name)
        page_titles[name] = label

        relative = page.get("output")
        path = root / str(relative) if relative else fallback.get(("page", name, ""))
        if path is not None and Path(path).exists():
            pages[name] = Path(path)

        relative = page.get("mobileOutput")
        path = (
            root / str(relative)
            if relative
            else fallback.get(("mobile", name, ""))
        )
        if path is not None and Path(path).exists():
            mobile[name] = Path(path)

        for visual in page.get("visuals") or []:
            if not isinstance(visual, dict):
                continue
            visual_name = str(visual.get("name") or "")
            if not visual_name:
                continue
            title = str(visual.get("title") or "")
            visual_titles[(name, visual_name)] = title
            relative = visual.get("output")
            path = (
                root / str(relative)
                if relative
                else fallback.get(("visual", name, visual_name))
            )
            if path is not None and Path(path).exists():
                visuals[(name, visual_name)] = Path(path)

    if not pages and not visuals and not mobile:
        return None

    roles = meta.get("rlsRoles") or ()
    warnings = meta.get("warnings") or ()
    missing = meta.get("missing") or ()
    return ScreenshotSet(
        root=root,
        pages=pages,
        visuals=visuals,
        mobile=mobile,
        page_titles=page_titles,
        visual_titles=visual_titles,
        captured_at=str(meta.get("generatedAt") or ""),
        workspace_id=str(meta.get("workspaceId") or ""),
        report_id=str(meta.get("reportId") or ""),
        scope=str(meta.get("scope") or "both"),
        rls_username=str(meta.get("rlsUsername") or ""),
        rls_roles=tuple(str(role) for role in roles),
        warnings=tuple(str(item) for item in warnings),
        missing=tuple(str(item) for item in missing),
        mobile_enabled=bool(meta.get("mobileEnabled")),
    )


def cache_dir(base: Path, report_name: str, report_id: str = "") -> Path:
    """Folder cache: ``<base>\\TSD_assets\\<nama report>_<id8>``.

    Delapan karakter pertama report ID mencegah dua report yang namanya sama
    (atau nama kosong) saling menimpa cache.
    """
    name = slug(report_name or "Report")
    suffix = (report_id or "").strip()[:8]
    if suffix:
        name = f"{name}_{suffix}"
    return Path(base) / "TSD_assets" / name
