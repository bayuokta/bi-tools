"""Lokasi aset web dan berkas runtime server."""

from __future__ import annotations

import os
from pathlib import Path

from core.paths import APP_DIR, data_dir

WEB_DIR_NAME = "web"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PORT_ATTEMPTS = 10
STATE_FILE_NAME = "server.json"
SETTINGS_FILE_NAME = "settings.json"
SETTINGS_ENV = "BI_TOOLS_SETTINGS"


def web_dir() -> Path:
    """Folder aset statis; di paket onedir berada di samping executable."""
    return APP_DIR / WEB_DIR_NAME


def state_file() -> Path:
    """Berkas penanda server yang sedang berjalan (port + token)."""
    return data_dir() / STATE_FILE_NAME


def settings_file() -> Path:
    override = os.environ.get(SETTINGS_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return data_dir() / SETTINGS_FILE_NAME
