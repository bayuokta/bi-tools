"""Format teks status yang dipakai beberapa tab.

Sebelumnya ``file_status`` dan teks status service principal ditulis ulang di
beberapa widget dengan aturan berbeda. Semua format tampilan kecil ada di sini
supaya tab tinggal menulis hasilnya ke label.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.auth import ServicePrincipal

OK_COLOR = "#2e7d32"
WARN_COLOR = "#a05000"
ERROR_COLOR = "#b00020"


def file_status(path: Path) -> str:
    """Nama file + waktu modifikasi untuk label status output."""
    path = Path(path)
    if not path.exists():
        return f"{path.name}  (belum dibuat)"
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return path.name
    return f"{path.name}  ({stamp})"


def credential_status(principal: ServicePrincipal) -> tuple[str, str]:
    """Teks dan warna status service principal untuk label baca-saja."""
    if principal.is_complete:
        return "Service principal lengkap dan siap dipakai.", OK_COLOR
    return (
        "Service principal belum lengkap: "
        + ", ".join(principal.missing)
        + " (isi di tab Pengaturan).",
        WARN_COLOR,
    )


def duration_text(seconds: float) -> str:
    """Durasi dalam detik untuk ringkasan log."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "-"
    return f"{value:.1f} detik"
