"""Unduh Chromium Playwright dari dalam aplikasi terpaket.

Chromium (±150 MB) tidak dibundel. Aplikasi terpaket tidak punya interpreter
``python`` untuk ``python -m playwright``, jadi driver bawaan Playwright
(``node.exe`` + ``cli.js``) dipanggil langsung lewat subprocess. Modul ini juga
mengenali kegagalan ``launch()`` yang berarti browser belum diunduh.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

from ..errors import ExtractionError

Log = Callable[[str], None]
BROWSER = "chromium"


def _silent(_message: str) -> None:
    pass


def default_browsers_path() -> Path:
    """Folder browser Playwright normal (di luar folder aplikasi)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "").strip()
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def prepare_environment() -> Path | None:
    """Samakan folder browser installer dan driver saat aplikasi dipaket.

    Playwright (``playwright/_impl/transport.py``) memaksa
    ``PLAYWRIGHT_BROWSERS_PATH=0`` untuk proses driver ketika ``sys.frozen``:
    browser dicari di dalam ``playwright/driver/package/.local-browsers``.
    Unduhan memakai lokasi normal, jadi tanpa ini install dan launch menunjuk
    folder berbeda dan launch selalu gagal. Nilai kustom non-``0`` dibiarkan.
    """
    if not getattr(sys, "frozen", False):
        return None
    current = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if current and current != "0":
        return Path(current).expanduser()
    path = default_browsers_path()
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
    return path


def driver_command(*args: str) -> list[str]:
    """Perintah driver Playwright; dipisah agar mudah diuji."""
    prepare_environment()
    from playwright._impl._driver import compute_driver_executable

    node, cli = compute_driver_executable()
    return [str(node), str(cli), *args]


def missing_browser(exc: BaseException) -> bool:
    """True bila kegagalan ``launch()`` karena browser belum diunduh."""
    text = str(exc).lower()
    return (
        "executable doesn't exist" in text
        or "executable was not found" in text
        or "playwright install" in text
    )


def install_chromium(log: Log = _silent) -> None:
    """Unduh Chromium memakai driver Playwright; progres diteruskan ke ``log``."""
    try:
        command = driver_command("install", "--no-progress", BROWSER)
    except Exception as exc:  # noqa: BLE001 - paket Playwright tidak lengkap
        raise ExtractionError(
            "Playwright is not available in this package; reinstall the application."
        ) from exc

    log("Downloading Chromium (about 150 MB) ...")
    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    )
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise ExtractionError(
            f"Could not run the Chromium downloader: {exc}. "
            "Run 'bi-tools-cli install-browser' from Command Prompt."
        ) from exc

    if process.stdout is not None:
        for line in process.stdout:
            line = line.strip()
            if line:
                log(line)
    code = process.wait()
    if code != 0:
        raise ExtractionError(
            f"Chromium download failed (exit {code}). Check the connection/proxy, then "
            "run 'bi-tools-cli install-browser'."
        )
    log("Chromium is ready.")


__all__ = [
    "BROWSER",
    "default_browsers_path",
    "driver_command",
    "install_chromium",
    "missing_browser",
    "prepare_environment",
]
