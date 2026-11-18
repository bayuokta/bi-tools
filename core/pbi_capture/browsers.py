"""Unduh Chromium Playwright dari dalam aplikasi terpaket.

Chromium (±150 MB) tidak dibundel. Aplikasi terpaket tidak punya interpreter
``python`` untuk ``python -m playwright``, jadi driver bawaan Playwright
(``node.exe`` + ``cli.js``) dipanggil langsung lewat subprocess. Modul ini juga
mengenali kegagalan ``launch()`` yang berarti browser belum diunduh.
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable

from ..errors import ExtractionError

Log = Callable[[str], None]
BROWSER = "chromium"


def _silent(_message: str) -> None:
    pass


def driver_command(*args: str) -> list[str]:
    """Perintah driver Playwright; dipisah agar mudah diuji."""
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
            "Playwright tidak tersedia di paket ini; pasang ulang aplikasi."
        ) from exc

    log("Mengunduh Chromium (sekitar 150 MB) ...")
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
            f"Tidak bisa menjalankan pengunduh Chromium: {exc}. "
            "Jalankan 'bi-tools-cli install-browser' dari Command Prompt."
        ) from exc

    if process.stdout is not None:
        for line in process.stdout:
            line = line.strip()
            if line:
                log(line)
    code = process.wait()
    if code != 0:
        raise ExtractionError(
            f"Unduh Chromium gagal (exit {code}). Periksa koneksi/proxy lalu "
            "jalankan 'bi-tools-cli install-browser'."
        )
    log("Chromium siap dipakai.")


__all__ = [
    "BROWSER",
    "driver_command",
    "install_chromium",
    "missing_browser",
]
