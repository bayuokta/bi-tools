"""Endpoint berkas lokal: penjelajah folder, buka berkas, status output.

Browser tidak bisa memberi path asli dari ``<input type=file>``, sehingga
pemilihan folder/berkas dilakukan di sisi server (komputer yang sama). Semua
endpoint hanya membaca dan membuka berkas; tidak ada unggahan.
"""

from __future__ import annotations

import os
import string
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.paths import outputs_dir
from core.report import MODEL_WORKBOOK_NAME, OUT_FILE

from .. import settings as keys
from ..presenters.formatting import file_status
from . import settings_of

router = APIRouter(prefix="/api/files", tags=["files"])

MAX_ENTRIES = 2000
# Hanya berkas hasil kerja yang boleh dibuka; mencegah "Buka" dipakai untuk
# menjalankan program dari path sembarang.
BLOCKED_SUFFIXES = {
    ".exe",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".msi",
    ".ps1",
    ".vbs",
    ".vbe",
    ".js",
    ".jse",
    ".lnk",
    ".pif",
}


def _entry(path: Path) -> dict[str, Any]:
    is_dir = path.is_dir()
    size = 0
    modified = ""
    if not is_dir:
        try:
            stat = path.stat()
        except OSError:
            stat = None
        if stat is not None:
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d %H:%M"
            )
    return {
        "name": path.name or str(path),
        "path": str(path),
        "is_dir": is_dir,
        "size": size,
        "modified": modified,
    }


def _roots() -> list[dict[str, Any]]:
    if os.name == "nt":
        entries: list[dict[str, Any]] = []
        for letter in string.ascii_uppercase:
            root = Path(f"{letter}:\\")
            try:
                if root.exists():
                    entries.append(_entry(root))
            except OSError:
                continue
        return entries
    return [_entry(Path("/"))]


def _home() -> Path:
    return Path.home()


@router.get("/browse")
def browse(
    path: str = "",
    kind: Literal["dir", "file"] = "dir",
    ext: str = "",
) -> dict[str, Any]:
    """Isi satu folder; ``path`` kosong mengembalikan daftar drive."""
    if not path:
        roots = _roots()
        return {
            "path": "",
            "parent": None,
            "home": str(_home()),
            "entries": roots,
            "count": len(roots),
            "truncated": False,
        }
    target = Path(path).expanduser()
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Folder tidak ditemukan: {path}")
    extensions = {
        item.strip().lower()
        for item in str(ext).replace(";", ",").split(",")
        if item.strip()
    }
    entries: list[dict[str, Any]] = []
    truncated = False
    try:
        children = sorted(
            target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())
        )
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"Folder tidak bisa dibaca: {exc}"
        ) from exc
    for child in children:
        try:
            is_dir = child.is_dir()
        except OSError:
            continue
        if not is_dir:
            if kind == "dir":
                continue
            if extensions and child.suffix.lower() not in extensions:
                continue
        entries.append(_entry(child))
        if len(entries) >= MAX_ENTRIES:
            truncated = True
            break
    parent = target.parent
    return {
        "path": str(target),
        "parent": str(parent) if parent != target else None,
        "home": str(_home()),
        "entries": entries,
        "count": len(entries),
        "truncated": truncated,
    }


class OpenIn(BaseModel):
    path: str
    mode: Literal["open", "reveal"] = "open"


def _startfile(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # noqa: S606 - berkas lokal milik pengguna
        return
    command = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([command, str(path)])  # noqa: S603,S607


@router.post("/open")
def open_path(payload: OpenIn) -> dict[str, Any]:
    """Buka berkas/folder di aplikasi default, atau sorot di Explorer."""
    text = str(payload.path or "").strip().strip('"')
    if not text or "\x00" in text:
        raise HTTPException(status_code=400, detail="Path tidak valid.")
    target = Path(text).expanduser()
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Berkas tidak ditemukan: {text}")
    if target.is_file() and target.suffix.lower() in BLOCKED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail="Berkas yang dapat dieksekusi tidak dibuka dari halaman web.",
        )
    if payload.mode == "reveal":
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(target)])  # noqa: S603,S607
        else:
            _startfile(target.parent if target.is_file() else target)
    else:
        _startfile(target)
    return {"status": "ok", "path": str(target), "mode": payload.mode}


@router.get("/outputs")
def outputs(request: Request, folder: str = "") -> dict[str, Any]:
    """Status workbook metadata di folder output."""
    store = settings_of(request)
    text = str(folder or "").strip().strip('"')
    if not text and store is not None:
        text = store.get_str(keys.SETTINGS_OUT_DIR_KEY)
    target = Path(text).expanduser() if text else outputs_dir()
    report = file_status(target / OUT_FILE.name)
    model = file_status(target / MODEL_WORKBOOK_NAME)
    return {
        "folder": str(target),
        "exists": target.exists(),
        "report": report,
        "model": model,
    }
