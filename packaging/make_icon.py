"""Buat ``packaging/bi-tools.ico`` (ikon aplikasi & installer).

Ikon dirender dengan PySide6 (QPainter) dalam beberapa ukuran lalu dikemas
sebagai ICO berisi PNG, jadi tidak butuh Pillow. Jalankan ulang hanya bila
desainnya berubah; hasilnya ikut di-commit:

    python packaging/make_icon.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
)

SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 8
OUT_PATH = Path(__file__).resolve().with_name("bi-tools.ico")

BACKGROUND_TOP = QColor("#12395E")
BACKGROUND_BOTTOM = QColor("#0B2440")
BAR_COLORS = (QColor("#8FD6EC"), QColor("#57B8DC"), QColor("#F4FAFF"))
BAR_HEIGHTS = (0.26, 0.44, 0.62)
BAR_WIDTH = 0.15
BAR_GAP = 0.075
BAR_BOTTOM = 0.78
BASELINE = QColor("#57B8DC")


def render(size: int) -> QImage:
    """Render satu ukuran ikon (persegi, latar transparan di luar sudut)."""
    canvas = size * SUPERSAMPLE
    image = QImage(canvas, canvas, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    radius = canvas * 0.22
    body = QRectF(0, 0, canvas, canvas)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(canvas, canvas))
    gradient.setColorAt(0.0, BACKGROUND_TOP)
    gradient.setColorAt(1.0, BACKGROUND_BOTTOM)

    path = QPainterPath()
    path.addRoundedRect(body, radius, radius)
    painter.fillPath(path, gradient)

    # Garis dasar tipis sebagai "sumbu" grafik.
    base_y = canvas * BAR_BOTTOM
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(BASELINE)
    base_height = max(2.0, canvas * 0.022)
    painter.drawRoundedRect(
        QRectF(canvas * 0.20, base_y, canvas * 0.60, base_height),
        base_height / 2,
        base_height / 2,
    )

    bar_width = canvas * BAR_WIDTH
    gap = canvas * BAR_GAP
    total = len(BAR_HEIGHTS) * bar_width + (len(BAR_HEIGHTS) - 1) * gap
    start_x = (canvas - total) / 2

    for index, (ratio, color) in enumerate(zip(BAR_HEIGHTS, BAR_COLORS)):
        height = canvas * ratio
        x = start_x + index * (bar_width + gap)
        bar = QRectF(x, base_y - height, bar_width, height)
        painter.setBrush(color)
        painter.drawRoundedRect(bar, bar_width * 0.30, bar_width * 0.30)

    painter.end()

    return image.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _png_bytes(image: QImage) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def write_ico(path: Path, images: dict[int, QImage]) -> None:
    """Tulis ICO berisi PNG untuk setiap ukuran."""
    payloads = [(size, _png_bytes(images[size])) for size in sorted(images)]

    header = struct.pack("<HHH", 0, 1, len(payloads))
    offset = len(header) + 16 * len(payloads)
    entries = bytearray()
    blob = bytearray()
    for size, payload in payloads:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(payload),
            offset,
        )
        blob += payload
        offset += len(payload)

    path.write_bytes(header + bytes(entries) + bytes(blob))


_APP = None


def main() -> int:
    global _APP
    _APP = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    images = {size: render(size) for size in SIZES}
    write_ico(OUT_PATH, images)

    preview = Path(os.environ.get("TEMP", ".")) / "bi-tools-icon-preview.png"
    images[256].save(str(preview), "PNG")
    print(f"Ikon ditulis: {OUT_PATH} ({OUT_PATH.stat().st_size} byte)")
    print(f"Pratinjau 256px: {preview}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
