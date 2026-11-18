"""Lokasi aplikasi dan folder runtime (skrip maupun executable).

Saat dijalankan sebagai skrip (``python -m server`` atau perintah CLI) folder
aplikasi adalah root repo, sehingga perilaku lama tidak berubah. Saat dibungkus
menjadi executable, folder aplikasi adalah folder tempat ``.exe`` berada, jadi
``outputs\\`` dan ``data\\`` ikut pindah bersama aplikasi.

Folder aplikasi bisa saja tidak bisa ditulis (mis. dipasang di
``C:\\Program Files``). Dalam kasus itu :func:`outputs_dir` dan :func:`data_dir`
jatuh ke ``%LOCALAPPDATA%\\BI Tools``. Fungsi di sini tidak membuat folder;
pembuatan folder dilakukan di jalur tulis yang memang sudah memanggil
``mkdir(parents=True, exist_ok=True)``.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

FALLBACK_DIR_NAME = "BI Tools"
OUTPUTS_DIR_NAME = "outputs"
DATA_DIR_NAME = "data"

OUTPUTS_ENV = "BI_TOOLS_OUTPUTS"
DATA_ENV = "BI_TOOLS_DATA"


def app_dir() -> Path:
    """Folder aplikasi: folder executable, atau root repo saat dijalankan sebagai skrip."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_DIR = app_dir()
OUTPUTS_DIR = APP_DIR / OUTPUTS_DIR_NAME
DATA_DIR = APP_DIR / DATA_DIR_NAME


def _writable(base: Path) -> bool:
    """Apakah folder (atau induknya, bila belum ada) bisa ditulis."""
    if base.exists():
        return os.access(base, os.W_OK)
    parent = base.parent
    return parent.exists() and os.access(parent, os.W_OK)


def _resolve(name: str, env_var: str) -> Path:
    override = os.environ.get(env_var, "").strip()
    if override:
        return Path(override).expanduser()
    local = os.environ.get("LOCALAPPDATA", "").strip()
    candidates: list[Path] = [APP_DIR]
    if local:
        candidates.append(Path(local) / FALLBACK_DIR_NAME)
    for base in candidates:
        if base.exists() and _writable(base):
            return base / name
        if not base.exists() and _writable(base.parent):
            # Folder belum ada; dibuat saat tulisan pertama.
            return base / name
    return APP_DIR / name


@lru_cache(maxsize=8)
def outputs_dir() -> Path:
    """Folder hasil generate; fallback ``%LOCALAPPDATA%\\BI Tools\\outputs``."""
    return _resolve(OUTPUTS_DIR_NAME, OUTPUTS_ENV)


@lru_cache(maxsize=8)
def data_dir() -> Path:
    """Folder database lokal; fallback ``%LOCALAPPDATA%\\BI Tools\\data``."""
    return _resolve(DATA_DIR_NAME, DATA_ENV)
