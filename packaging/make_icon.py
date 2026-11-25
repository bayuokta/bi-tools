"""Buat ``packaging/bi-tools.ico`` (ikon aplikasi & installer).

Ikon dirender dengan PySide6 (QPainter) dalam beberapa ukuran lalu dikemas
sebagai ICO berisi PNG, jadi tidak butuh Pillow. Jalankan ulang hanya bila
desainnya berubah; hasilnya ikut di-commit:

    python packaging/make_icon.py

Desain: kotak grafit gelap dengan garis grafik kuning (mark BI Tools).
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
    QPainter,
    QPainterPath,
    QPen,
)

SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 8
OUT_PATH = Path(__file__).resolve().with_name("bi-tools.ico")

BACKGROUND = QColor("#0E1116")
ACCENT = QColor("#F2C811")
# Mark mengikuti SVG 512x512: konten 24 unit digambar di (56,56) skala 16.667.
MARGIN = 56.0
UNIT = 16.6667
STROKE = 1.9 * UNIT


def _point(x: float, y: float) -> QPointF:
    return QPointF(MARGIN + x * UNIT, MARGIN + y * UNIT)


def render(size: int) -> QImage:
    """Render satu ukuran ikon (persegi, latar transparan di luar sudut)."""
    canvas = size * SUPERSAMPLE
    image = QImage(canvas, canvas, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    radius = canvas * (112.0 / 512.0)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, canvas, canvas), radius, radius)
    painter.fillPath(path, BACKGROUND)

    painter.scale(canvas / 512.0, canvas / 512.0)
    pen = QPen(ACCENT)
    pen.setWidthF(STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    painter.drawLine(_point(4, 19), _point(4, 5))
    painter.drawLine(_point(4, 19), _point(20, 19))

    line = QPainterPath(_point(8, 15))
    line.lineTo(_point(12, 10))
    line.lineTo(_point(15, 13))
    line.lineTo(_point(20, 6))
    painter.drawPath(line)
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
