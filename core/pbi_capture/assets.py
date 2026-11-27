"""Pemetaan manifest capture -> file screenshot, plus helper data URI.

Manifest berasal dari embedded JS client (powerbi-client) karena REST API Power
BI tidak punya endpoint daftar visual. Struktur manifest sama dengan tool
``pbi-download-image``:

{
  "workspaceId", "reportId", "generatedAt", "source": "embedded-client",
  "pages": [
    {"name", "displayName", "isActive", "ordinal",
     "visuals": [{"name", "type", "title", "layout", "output"}]}
  ]
}

Kunci join ke workbook report memakai nama internal page/visual (``name``),
yang sama dengan ``01_Pages.page_id`` dan ``08_Visual_Summary.visual_id``.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

PAGE_DIR = "pages"
VISUAL_DIR = "visuals"
MOBILE_DIR = "mobile"

SCOPES = ("both", "pages", "visuals")

SCOPE_LABELS = {
    "both": "Page + visual",
    "pages": "Pages only",
    "visuals": "Visuals only",
}

# Objek dekoratif pada report: tetap terlihat di screenshot halaman, tetapi
# tidak perlu menjadi baris "visual" TSD atau file PNG tersendiri. Slicer tetap
# tampil. Daftar ini dipakai capture (exclude) dan TSD (filter baris visual).
DECORATIVE_VISUAL_TYPES = frozenset(
    {
        "shape",
        "image",
        "textbox",
        "actionButton",
        "basicShape",
        "pageNavigator",
        "bookmarkNavigator",
    }
)


# ---------------------------------------------------------------------- util
def slug(text: str, max_len: int = 80) -> str:
    """Ubah string jadi aman untuk nama file (tetap boleh unicode/huruf ID)."""
    text = (text or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_{2,}", "_", text).strip("._ ")
    return text[:max_len] or "untitled"


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def new_manifest(workspace_id: str, report_id: str) -> dict:
    return {
        "workspaceId": workspace_id,
        "reportId": report_id,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "embedded-client",
        "pages": [],
    }


def save_json(path: Path, data: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def data_uri(path: Path) -> str:
    """Baca PNG dan kembalikan data URI supaya HTML tetap satu file mandiri."""
    data = Path(path).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def scope_covers(cached: str, requested: str) -> bool:
    """True bila cache dengan cakupan ``cached`` cukup untuk ``requested``."""
    if cached == "both":
        return True
    return cached == requested


def visual_file_base(visual: Mapping) -> str:
    """Nama dasar file visual: judul bila ada, selain itu type + nama."""
    title = visual.get("title")
    if title:
        return slug(str(title))
    vtype = visual.get("type") or "visual"
    return slug(f"{vtype}_{visual.get('name') or 'unknown'}")


# ------------------------------------------------------------------- item
@dataclass
class ExportItem:
    """Satu unit output = satu file gambar (page ATAU visual)."""

    kind: str  # "page" | "visual" | "mobile"
    page_name: str
    page_display_name: str
    page_ordinal: int
    output_path: Path
    visual_name: str = ""
    visual_title: str = ""
    visual_type: str = ""


def build_items(
    manifest: Mapping,
    output_root: Path,
    scope: str = "both",
    exclude_visual_types: Iterable[str] | None = None,
) -> tuple[list[ExportItem], list[dict]]:
    """Susun daftar file output dari manifest.

    Mengembalikan ``(items, skipped)``; ``skipped`` berisi visual yang
    dikecualikan lewat ``exclude_visual_types``.
    """
    if scope not in SCOPES:
        raise ValueError(f"Unknown screenshot scope: {scope}")

    exclude = set(exclude_visual_types or ())
    root = Path(output_root)
    items: list[ExportItem] = []
    skipped: list[dict] = []

    for page in manifest.get("pages") or []:
        ordinal = int(page.get("ordinal") or 0)
        page_name = str(page.get("name") or "")
        page_label = str(page.get("displayName") or page_name)
        dir_name = f"{ordinal:02d}_{slug(page_label)}"

        if scope in ("pages", "both"):
            items.append(
                ExportItem(
                    kind="page",
                    page_name=page_name,
                    page_display_name=page_label,
                    page_ordinal=ordinal,
                    output_path=root / PAGE_DIR / f"{dir_name}.png",
                )
            )
            if page.get("mobileOutput") is not None or page.get("mobileLayout"):
                items.append(
                    ExportItem(
                        kind="mobile",
                        page_name=page_name,
                        page_display_name=page_label,
                        page_ordinal=ordinal,
                        output_path=root / MOBILE_DIR / f"{dir_name}.png",
                    )
                )

        if scope in ("visuals", "both"):
            used: dict[str, str] = {}
            for visual in page.get("visuals") or []:
                v_name = str(visual.get("name") or "unknown_visual")
                v_type = visual.get("type") or ""
                if v_type in exclude:
                    skipped.append(
                        {
                            "page": page_label,
                            "visualName": v_name,
                            "type": v_type,
                            "reason": "excludeVisualTypes",
                        }
                    )
                    continue
                base = visual_file_base(visual)
                fname = base
                if fname.lower() in used:
                    fname = f"{base}_{slug(v_name)}"
                used[fname.lower()] = v_name
                items.append(
                    ExportItem(
                        kind="visual",
                        page_name=page_name,
                        page_display_name=page_label,
                        page_ordinal=ordinal,
                        visual_name=v_name,
                        visual_title=str(visual.get("title") or ""),
                        visual_type=v_type,
                        output_path=root / VISUAL_DIR / dir_name / f"{fname}.png",
                    )
                )

    return items, skipped


# ------------------------------------------------------------- screenshot set
@dataclass
class ScreenshotSet:
    """Hasil capture (atau cache) yang siap dipakai TSD."""

    root: Path
    pages: dict[str, Path] = field(default_factory=dict)
    visuals: dict[tuple[str, str], Path] = field(default_factory=dict)
    mobile: dict[str, Path] = field(default_factory=dict)
    page_titles: dict[str, str] = field(default_factory=dict)
    visual_titles: dict[tuple[str, str], str] = field(default_factory=dict)
    captured_at: str = ""
    workspace_id: str = ""
    report_id: str = ""
    scope: str = "both"
    mobile_enabled: bool = False
    rls_username: str = ""
    rls_roles: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    # -- pencarian ---------------------------------------------------------
    def _page_key(self, page_id: str, page_title: str = "") -> str:
        if page_id and page_id in self.pages:
            return page_id
        wanted = norm_text(page_title)
        if wanted:
            for name, display in self.page_titles.items():
                if norm_text(display) == wanted:
                    return name
        return ""

    def page(self, page_id: str, page_title: str = "") -> Path | None:
        key = self._page_key(page_id, page_title)
        return self.pages.get(key) if key else None

    def mobile_page(self, page_id: str, page_title: str = "") -> Path | None:
        key = self._page_key(page_id, page_title)
        return self.mobile.get(key) if key else None

    def visual(
        self,
        page_id: str,
        visual_id: str,
        visual_title: str = "",
        page_title: str = "",
    ) -> Path | None:
        page_key = self._page_key(page_id, page_title)
        if page_key and visual_id and (page_key, visual_id) in self.visuals:
            return self.visuals[(page_key, visual_id)]
        if page_key and visual_title:
            wanted = norm_text(visual_title)
            for (key, visual), title in self.visual_titles.items():
                if key != page_key:
                    continue
                if norm_text(title) == wanted:
                    return self.visuals.get((key, visual))
        if not page_key and visual_id:
            for (key, visual), path in self.visuals.items():
                if visual == visual_id:
                    return path
        return None

    # -- status ------------------------------------------------------------
    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def visual_count(self) -> int:
        return len(self.visuals)

    @property
    def mobile_count(self) -> int:
        return len(self.mobile)

    def matches(
        self,
        workspace_id: str,
        report_id: str,
        scope: str,
        *,
        require_mobile: bool = False,
    ) -> bool:
        if workspace_id and self.workspace_id:
            if workspace_id.lower() != self.workspace_id.lower():
                return False
        if report_id and self.report_id:
            if report_id.lower() != self.report_id.lower():
                return False
        if require_mobile and not self.mobile_enabled:
            return False
        return scope_covers(self.scope, scope)

    def summary(self) -> str:
        parts = [f"{self.page_count} page", f"{self.visual_count} visual"]
        if self.mobile:
            parts.append(f"{self.mobile_count} mobile")
        if self.captured_at:
            parts.append(str(self.captured_at).replace("T", " ")[:16])
        if self.rls_roles:
            parts.append("role " + ", ".join(self.rls_roles))
        return " · ".join(parts)
