"""Format teks status yang dipakai server web.

Berbeda dengan ``app/formatting.py`` yang mengembalikan warna Qt, di sini
status dikembalikan sebagai *tone* (``ok``/``warn``/``error``/``idle``) supaya
CSS yang menentukan tampilannya.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path



def file_status(path: Path) -> dict[str, object]:
    """Ringkasan satu berkas hasil generate untuk kartu output."""
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "name": path.name,
            "exists": False,
            "size": 0,
            "modified": "",
            "text": f"{path.name}  (not created yet)",
        }
    try:
        stat = path.stat()
    except OSError:
        return {
            "path": str(path),
            "name": path.name,
            "exists": True,
            "size": 0,
            "modified": "",
            "text": path.name,
        }
    stamp = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    return {
        "path": str(path),
        "name": path.name,
        "exists": True,
        "size": stat.st_size,
        "modified": stamp,
        "text": f"{path.name}  ({stamp})",
    }


def duration_text(seconds: float) -> str:
    """Durasi dalam detik untuk ringkasan log."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "-"
    return f"{value:.1f} seconds"


def format_time(value: str) -> str:
    """Timestamp ISO dari database dipersingkat untuk label."""
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("T", " ")[:16]
