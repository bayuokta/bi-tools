"""Hint posisi absolut visual dari workbook report untuk pairing capture.

``08_Visual_Summary`` menyimpan posisi visual relatif terhadap group induknya
(kolom ``position_x``/``position_y``). Embed API dan elemen DOM memakai
koordinat absolut halaman, sehingga visual di dalam group tidak bisa dipasangkan
hanya dari layout API. Kolom ``position_x_abs``/``position_y_abs`` diisi oleh
:mod:`core.report` (posisi visual + seluruh group induk) dan dipakai di sini.

Workbook lama tanpa kolom tersebut menghasilkan hint kosong; capture lalu
memakai pencocokan label/ukuran seperti sebelumnya.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

HINTS_SHEET = "08_Visual_Summary"
HINT_COLUMNS = (
    "page_id",
    "visual_id",
    "position_x_abs",
    "position_y_abs",
    "width",
    "height",
)

# {page_id: {visual_id: (x_abs, y_abs, width, height)}} dalam satuan halaman.
LayoutHints = dict[str, dict[str, tuple[float, float, float, float]]]


def _number(value: Any) -> float | None:
    """Angka dari sel workbook; ``None`` bila kosong/NaN (bukan 0)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def load_layout_hints(workbook: Path | str | None) -> LayoutHints:
    """Baca hint posisi absolut dari workbook report (tanpa melempar error)."""
    if not workbook:
        return {}
    path = Path(workbook)
    if not path.exists():
        return {}
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover - pandas sudah wajib untuk ekstraksi
        return {}
    try:
        frame = pd.read_excel(path, sheet_name=HINTS_SHEET)
    except Exception:  # noqa: BLE001 - workbook rusak/tanpa sheet: tanpa hint
        return {}
    if any(name not in frame.columns for name in HINT_COLUMNS):
        return {}

    hints: LayoutHints = {}
    for row in frame.to_dict("records"):
        page_id = str(row.get("page_id") or "").strip()
        visual_id = str(row.get("visual_id") or "").strip()
        if not page_id or not visual_id:
            continue
        position_x = _number(row.get("position_x_abs"))
        position_y = _number(row.get("position_y_abs"))
        width = _number(row.get("width"))
        height = _number(row.get("height"))
        if position_x is None or position_y is None:
            continue
        if width is None or height is None or width <= 0 or height <= 0:
            continue
        hints.setdefault(page_id, {})[visual_id] = (
            position_x,
            position_y,
            width,
            height,
        )
    return hints
