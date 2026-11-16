"""Capture screenshot page & visual dari Power BI Service (embed + RLS).

Paket ini adalah port dari tool ``pbi-download-image``: embed token membawa
identitas RLS, report dibuka di Chromium headless lewat ``powerbi-client``,
lalu setiap page dan visual di-screenshot.

Pemakaian utama ada di :mod:`core.tsd` (section 2.2.7.1 Web layout). Ekspor
berat (runner/cache) dimuat malas agar ``import core.tsd`` tetap ringan.
"""

from __future__ import annotations

from .assets import ScreenshotSet, data_uri, slug
from .credentials import CaptureCredentials

__all__ = [
    "CaptureCredentials",
    "CaptureOptions",
    "ScreenshotSet",
    "cache_dir",
    "capture_report",
    "data_uri",
    "load_or_capture",
    "load_screenshot_set",
    "slug",
]


def __getattr__(name: str):
    if name in {"CaptureOptions", "capture_report", "load_or_capture"}:
        from . import runner

        return getattr(runner, name)
    if name in {"cache_dir", "load_screenshot_set"}:
        from . import cache

        return getattr(cache, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
