"""Presenter tab Pengaturan untuk web (tanpa Qt).

Modul ini menangani status kredensial, path database, mode sinkronisasi, dan
dua pekerjaan panjang (sinkronisasi katalog workspace dan scan lineage).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.errors import ExtractionError
from core.lineage_service import database_summary, workspace_status
from core.lineage_store import DEFAULT_DB
from core.requests import SCOPES

from .. import settings as keys
from ..auth_state import status as auth_status
from ..shared_db import download_snapshot as _download_snapshot
from ..shared_db import snapshot_status
from ..settings_store import SettingsStore
from .formatting import format_time

THEMES = ("dark", "light")


def effective_database(store: SettingsStore) -> str:
    """Snapshot bersama bila ada, atau database lineage lama."""
    from ..shared_db import active_database_path

    return str(active_database_path(store))


def _saved_scope(store: SettingsStore, key: str) -> str:
    value = store.get_str(key, "")
    if value not in SCOPES:
        value = store.get_str(keys.SETTINGS_SCOPE_KEY, "both")
    return value if value in SCOPES else "both"


def build_state(store: SettingsStore) -> dict[str, Any]:
    """Nilai formulir Pengaturan, tanpa secret."""
    auth = auth_status(store)
    username, roles = store.rls()
    active_tab = store.get_str(keys.SETTINGS_ACTIVE_TAB_KEY, "local")
    if active_tab not in keys.ACTIVE_TABS:
        active_tab = "local"
    theme = store.get_str(keys.SETTINGS_UI_THEME_KEY, "dark")
    return {
        "auth": auth,
        "snapshot": snapshot_status(store),
        "rls": {"username": username, "roles": ",".join(roles)},
        "paths": {
            "lineage_db": effective_database(store),
            "default_db": str(DEFAULT_DB),
        },
        "extraction": {
            "scope_local": _saved_scope(store, keys.SETTINGS_SCOPE_LOCAL_KEY),
            "scope_service": _saved_scope(store, keys.SETTINGS_SCOPE_SERVICE_KEY),
            "active_tab": active_tab,
            "out_dir": store.get_str(keys.SETTINGS_OUT_DIR_KEY),
        },
        "ui": {
            "theme": theme if theme in THEMES else "dark",
            "motion": store.get_bool(keys.SETTINGS_UI_MOTION_KEY, True),
            "show_console": store.get_bool(keys.SETTINGS_UI_CONSOLE_KEY, True),
        },
        "meta": store.describe(),
    }


def catalog_status(store: SettingsStore) -> dict[str, Any]:
    """Gabungan status katalog workspace dan scan lineage."""
    path = effective_database(store)
    payload: dict[str, Any] = {
        "database": path,
        "text": "",
        "tone": "idle",
        "exists": False,
        "readable": True,
        "total": 0,
        "active": 0,
        "selectable": 0,
        "last_sync": "",
        "last_mode": "",
        "last_scan": "",
        "error": "",
    }
    try:
        summary = workspace_status(path)
    except ExtractionError as exc:
        payload.update(
            text=f"Database could not be read: {exc}", tone="error", error=str(exc)
        )
        return payload
    database = database_summary(path)
    payload["exists"] = database.exists
    payload["readable"] = database.readable
    if database.exists and not database.readable:
        payload.update(
            text=f"Database could not be read: {database.error}",
            tone="error",
            error=database.error,
        )
        return payload

    total = int(summary.get("total") or 0)
    active = int(summary.get("active") or 0)
    selectable = int(summary.get("selectable", active) or 0)
    last_sync = format_time(str(summary.get("last_sync") or ""))
    last_mode = str(summary.get("last_mode") or "")
    last_scan = format_time(database.last_scan)
    if total:
        text = f"{selectable} workspaces selectable out of {total} saved"
        if last_sync:
            suffix = f" ({last_mode})" if last_mode else ""
            text += f" · catalog sync {last_sync}{suffix}"
        tone = "ok" if selectable else "error"
    else:
        text = "No saved workspace catalog"
        tone = "idle"
    text += (
        f" · lineage scan {last_scan}"
        if last_scan
        else " · lineage scan has not run yet"
    )
    payload.update(
        text=text,
        tone=tone,
        total=total,
        active=active,
        selectable=selectable,
        last_sync=last_sync,
        last_mode=last_mode,
        last_scan=last_scan,
    )
    return payload


# -- penyimpanan ---------------------------------------------------------
def save_rls(store: SettingsStore, username: str, roles: Any) -> dict[str, Any]:
    store.set_rls(username, roles if roles is not None else "")
    return build_state(store)


def save_paths(store: SettingsStore, lineage_db: str) -> dict[str, Any]:
    text = str(lineage_db or "").strip().strip('"')
    if text:
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise ExtractionError("Database path must be absolute.")
        store.set_lineage_db(path)
    else:
        store.set(keys.PATHS_LINEAGE_DB_KEY, "")
    return build_state(store)


def save_ui(
    store: SettingsStore,
    theme: str | None = None,
    motion: bool | None = None,
    show_console: bool | None = None,
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if theme is not None:
        value = str(theme).strip()
        if value not in THEMES:
            raise ExtractionError(f"Unknown theme: {theme}")
        changes[keys.SETTINGS_UI_THEME_KEY] = value
    if motion is not None:
        changes[keys.SETTINGS_UI_MOTION_KEY] = bool(motion)
    if show_console is not None:
        changes[keys.SETTINGS_UI_CONSOLE_KEY] = bool(show_console)
    if changes:
        store.update(changes)
    return build_state(store)


def save_extraction(
    store: SettingsStore,
    *,
    scope_local: str | None = None,
    scope_service: str | None = None,
    active_tab: str | None = None,
    out_dir: str | None = None,
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for name, value, key in (
        ("scope local", scope_local, keys.SETTINGS_SCOPE_LOCAL_KEY),
        ("scope service", scope_service, keys.SETTINGS_SCOPE_SERVICE_KEY),
    ):
        if value is None:
            continue
        text = str(value).strip()
        if text not in SCOPES:
            raise ExtractionError(f"Unknown {name} scope: {value}")
        changes[key] = text
    if active_tab is not None:
        text = str(active_tab).strip()
        if text not in keys.ACTIVE_TABS:
            raise ExtractionError(f"Unknown sub-tab: {active_tab}")
        changes[keys.SETTINGS_ACTIVE_TAB_KEY] = text
    if out_dir is not None:
        text = str(out_dir).strip().strip('"')
        if text:
            path = Path(text).expanduser()
            if not path.is_absolute():
                raise ExtractionError("Output folder must be absolute.")
            text = str(path)
        changes[keys.SETTINGS_OUT_DIR_KEY] = text
    if changes:
        store.update(changes)
    return build_state(store)


def save_shared_db(
    store: SettingsStore, source: str, auto_download: bool = True
) -> dict[str, Any]:
    text = str(source or "").strip().strip('"')
    if text:
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise ExtractionError("Snapshot location must be absolute.")
        text = str(path)
    store.update(
        {
            keys.SHARED_DB_SOURCE_KEY: text,
            keys.SHARED_DB_AUTO_KEY: bool(auto_download),
        }
    )
    return build_state(store)


def download_shared_db(store: SettingsStore) -> dict[str, Any]:
    result = _download_snapshot(store)
    return {"snapshot": snapshot_status(store), "download": result}
