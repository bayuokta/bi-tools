"""Presenter tab Pengaturan untuk web (tanpa Qt).

Modul ini menangani status kredensial, path database, mode sinkronisasi, dan
dua pekerjaan panjang (sinkronisasi katalog workspace dan scan lineage).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.auth import FABRIC_SCOPE, POWERBI_SCOPE, EntraTokens, ServicePrincipal
from core.catalog_sync import run_workspace_sync
from core.errors import ExtractionError
from core.lineage_scan import run_lineage_scan
from core.lineage_service import database_summary, workspace_status
from core.lineage_store import DEFAULT_DB
from core.requests import SCOPES

from .. import settings as keys
from ..settings_store import SettingsStore
from .formatting import credential_status, duration_text, format_time

CATALOG_MODES = ("auto", "admin", "member")
THEMES = ("dark", "light")
LANGUAGES = ("en", "id")


def effective_database(store: SettingsStore) -> str:
    """Path database yang sudah disimpan, atau default aplikasi."""
    return store.lineage_db() or str(DEFAULT_DB)


def saved_catalog_mode(store: SettingsStore) -> str:
    value = store.get_str(keys.SETTINGS_CATALOG_MODE_KEY, "auto")
    return value if value in CATALOG_MODES else "auto"


def _saved_scope(store: SettingsStore, key: str) -> str:
    value = store.get_str(key, "")
    if value not in SCOPES:
        value = store.get_str(keys.SETTINGS_SCOPE_KEY, "both")
    return value if value in SCOPES else "both"


def build_state(store: SettingsStore) -> dict[str, Any]:
    """Nilai formulir Pengaturan, tanpa secret."""
    principal = store.principal()
    status_text, tone = credential_status(principal)
    username, roles = store.rls()
    active_tab = store.get_str(keys.SETTINGS_ACTIVE_TAB_KEY, "local")
    if active_tab not in keys.ACTIVE_TABS:
        active_tab = "local"
    theme = store.get_str(keys.SETTINGS_UI_THEME_KEY, "dark")
    language = store.get_str(keys.SETTINGS_UI_LANGUAGE_KEY, "en")
    return {
        "auth": {
            "tenant_id": principal.tenant_id,
            "client_id": principal.client_id,
            "has_secret": bool(principal.client_secret),
            "complete": principal.is_complete,
            "missing": principal.missing,
            "status": status_text,
            "tone": tone,
        },
        "rls": {"username": username, "roles": ",".join(roles)},
        "paths": {
            "lineage_db": effective_database(store),
            "default_db": str(DEFAULT_DB),
        },
        "catalog": {
            "mode": saved_catalog_mode(store),
            "include_personal": store.get_bool(
                keys.SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY
            ),
        },
        "extraction": {
            "scope_local": _saved_scope(store, keys.SETTINGS_SCOPE_LOCAL_KEY),
            "scope_service": _saved_scope(store, keys.SETTINGS_SCOPE_SERVICE_KEY),
            "active_tab": active_tab,
            "out_dir": store.get_str(keys.SETTINGS_OUT_DIR_KEY),
        },
        "ui": {
            "theme": theme if theme in THEMES else "dark",
            "language": language if language in LANGUAGES else "en",
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
            text=f"Database tidak bisa dibaca: {exc}", tone="error", error=str(exc)
        )
        return payload
    database = database_summary(path)
    payload["exists"] = database.exists
    payload["readable"] = database.readable
    if database.exists and not database.readable:
        payload.update(
            text=f"Database tidak bisa dibaca: {database.error}",
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
        text = f"{selectable} workspace siap dipilih dari {total} tersimpan"
        if last_sync:
            suffix = f" ({last_mode})" if last_mode else ""
            text += f" · sync katalog {last_sync}{suffix}"
        tone = "ok" if selectable else "error"
    else:
        text = "Belum ada katalog workspace tersimpan"
        tone = "idle"
    text += (
        f" · scan lineage {last_scan}"
        if last_scan
        else " · scan lineage belum pernah dijalankan"
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
def save_credentials(
    store: SettingsStore,
    tenant_id: str,
    client_id: str,
    client_secret: str | None,
) -> dict[str, Any]:
    """Simpan kredensial; secret kosong berarti pakai yang tersimpan."""
    current = store.principal()
    secret = current.client_secret if client_secret is None else client_secret.strip()
    principal = ServicePrincipal.from_values(tenant_id, client_id, secret)
    if not principal.is_complete:
        raise ExtractionError(
            "Lengkapi kolom berikut: " + ", ".join(principal.missing) + "."
        )
    store.set_principal(principal)
    return build_state(store)


def save_rls(store: SettingsStore, username: str, roles: Any) -> dict[str, Any]:
    store.set_rls(username, roles if roles is not None else "")
    return build_state(store)


def save_paths(store: SettingsStore, lineage_db: str) -> dict[str, Any]:
    text = str(lineage_db or "").strip().strip('"')
    if text:
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise ExtractionError("Path database harus absolut.")
        store.set_lineage_db(path)
    else:
        store.set(keys.PATHS_LINEAGE_DB_KEY, "")
    return build_state(store)


def save_catalog(
    store: SettingsStore, mode: str, include_personal: bool
) -> dict[str, Any]:
    value = str(mode or "").strip()
    if value not in CATALOG_MODES:
        raise ExtractionError(f"Mode sinkronisasi tidak dikenal: {mode}")
    store.update(
        {
            keys.SETTINGS_CATALOG_MODE_KEY: value,
            keys.SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY: bool(include_personal),
        }
    )
    return build_state(store)


def save_ui(
    store: SettingsStore,
    theme: str | None = None,
    motion: bool | None = None,
    show_console: bool | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if theme is not None:
        value = str(theme).strip()
        if value not in THEMES:
            raise ExtractionError(f"Tema tidak dikenal: {theme}")
        changes[keys.SETTINGS_UI_THEME_KEY] = value
    if language is not None:
        value = str(language).strip().lower()
        if value not in LANGUAGES:
            raise ExtractionError(f"Bahasa tidak dikenal: {language}")
        changes[keys.SETTINGS_UI_LANGUAGE_KEY] = value
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
            raise ExtractionError(f"Cakupan {name} tidak dikenal: {value}")
        changes[key] = text
    if active_tab is not None:
        text = str(active_tab).strip()
        if text not in keys.ACTIVE_TABS:
            raise ExtractionError(f"Sub-tab tidak dikenal: {active_tab}")
        changes[keys.SETTINGS_ACTIVE_TAB_KEY] = text
    if out_dir is not None:
        text = str(out_dir).strip().strip('"')
        if text:
            path = Path(text).expanduser()
            if not path.is_absolute():
                raise ExtractionError("Folder output harus absolut.")
            text = str(path)
        changes[keys.SETTINGS_OUT_DIR_KEY] = text
    if changes:
        store.update(changes)
    return build_state(store)


# -- pekerjaan -----------------------------------------------------------
def test_token_job(store: SettingsStore, log: Any, cancel: Any) -> dict[str, Any]:
    """Ambil token Fabric dan Power BI untuk kredensial tersimpan."""
    principal = store.principal()
    principal.validate()
    result: dict[str, Any] = {}
    log("Mengambil token Fabric dan Power BI...")
    tokens = EntraTokens(principal)
    for name, scope, label in (
        ("fabric", FABRIC_SCOPE, "Fabric"),
        ("powerbi", POWERBI_SCOPE, "Power BI"),
    ):
        if cancel.is_set():
            log("Tes koneksi dibatalkan.")
            break
        try:
            token = tokens.get(scope)
        except ExtractionError as exc:
            result[name] = {"ok": False, "error": str(exc)}
            log(f"Token {label} gagal: {exc}")
        else:
            result[name] = {"ok": True, "expires_on": token.expires_on}
            log(f"Token {label} OK.")
    return {"tokens": result}


def sync_catalog_job(store: SettingsStore, log: Any, cancel: Any) -> dict[str, Any]:
    """Sinkronisasi daftar workspace ke database yang sudah disimpan."""
    principal = store.principal()
    principal.validate()
    database = effective_database(store)
    mode = saved_catalog_mode(store)
    result = run_workspace_sync(database, principal, mode=mode, log=log)
    log(
        f"Katalog workspace: {result.workspace_count} workspace "
        f"({result.mode}, {duration_text(result.duration_seconds)})."
    )
    return {
        "database": str(result.database),
        "sync_id": result.sync_id,
        "mode": result.mode,
        "workspace_count": result.workspace_count,
        "active_count": result.active_count,
        "added": result.added,
        "updated": result.updated,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_seconds": result.duration_seconds,
    }


def scan_lineage_job(
    store: SettingsStore, full: bool, log: Any, cancel: Any
) -> dict[str, Any]:
    """Scan lineage Power BI memakai database dan mode tersimpan."""
    principal = store.principal()
    principal.validate()
    database = effective_database(store)
    mode = saved_catalog_mode(store)
    include_personal = store.get_bool(keys.SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY)
    result = run_lineage_scan(
        database,
        principal,
        mode=mode,
        full=bool(full),
        include_personal=include_personal,
        log=log,
    )
    scope = "termasuk personal" if result.include_personal else "tanpa personal"
    log(
        f"Lineage: {result.workspace_count} workspace ({scope}), "
        f"{result.node_count} node, {result.edge_count} edge "
        f"(mode {result.mode}, {duration_text(result.duration_seconds)})."
    )
    if result.unresolved_sources:
        log(f"CATATAN: {result.unresolved_sources} sumber feed belum punya metadata.")
    return {
        "database": str(result.database),
        "scan_id": result.scan_id,
        "mode": result.mode,
        "workspace_count": result.workspace_count,
        "node_count": result.node_count,
        "edge_count": result.edge_count,
        "unresolved_sources": result.unresolved_sources,
        "include_personal": result.include_personal,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "duration_seconds": result.duration_seconds,
    }
