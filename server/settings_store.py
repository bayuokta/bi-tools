"""Preferensi aplikasi dalam JSON, dengan migrasi sekali dari QSettings.

QSettings 0.3.x menyimpan semua nilai sebagai string di registry
``HKCU\\Software\\<org>\\<app>`` (termasuk boolean ``"true"``/``"false"``).
Migrasi di sini membaca pohon registry itu tanpa PySide6, menyalin kunci lama
``lineage/*`` ke ``auth/*``/``paths/*``, lalu menulis satu berkas JSON.

Berkas JSON dipilih karena server web tidak boleh bergantung pada Qt, sedangkan
isi preferensi harus tetap sama dengan versi GUI sebelumnya.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from core.auth import ServicePrincipal
from core.paths import data_dir
from core.pbi_capture.credentials import split_roles

from . import settings as keys

SETTINGS_FILE_NAME = "settings.json"
SETTINGS_ENV = "BI_TOOLS_SETTINGS"
MIGRATION_FLAG = "settings/json_migrated_v1"
FILE_VERSION = 1

BOOL_KEYS = frozenset(
    {
        "settings/org_migrated_v2",
        keys.SETTINGS_MIGRATED_KEY,
        MIGRATION_FLAG,
        keys.SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY,
        keys.SETTINGS_TSD_DRAFT_KEY,
        keys.SETTINGS_TSD_EXPAND_KEY,
        keys.SETTINGS_TSD_SHOTS_KEY,
        keys.SETTINGS_TSD_SHOT_MOBILE_KEY,
        keys.SETTINGS_TSD_DECORATIVE_KEY,
        keys.SETTINGS_TSD_AUTO_INSTALL_KEY,
        keys.SETTINGS_ANALYSIS_OTHER_WS_KEY,
        keys.SETTINGS_ANALYSIS_PERSONAL_KEY,
        keys.SETTINGS_ANALYSIS_SORT_DESC_KEY,
        keys.SETTINGS_ANALYSIS_UNUSED_ONLY_KEY,
        keys.SETTINGS_UI_MOTION_KEY,
        keys.SETTINGS_UI_CONSOLE_KEY,
    }
)
INT_KEYS = frozenset({keys.SETTINGS_TSD_SHOT_SCALE_KEY})

RegistryReader = Callable[[], Mapping[str, Any]]


class SettingsError(RuntimeError):
    """Preferensi tidak bisa dibaca atau ditulis."""


def default_path() -> Path:
    """Lokasi berkas preferensi; bisa dioverride lewat ``BI_TOOLS_SETTINGS``."""
    override = os.environ.get(SETTINGS_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return data_dir() / SETTINGS_FILE_NAME


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def normalize(key: str, value: Any) -> Any:
    """Samakan tipe nilai: boolean/int dikenal, sisanya dipertahankan."""
    if key in BOOL_KEYS:
        return _as_bool(value)
    if key in INT_KEYS:
        return _as_int(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _open_registry_key(root: Any, path: str) -> Any | None:
    import winreg

    try:
        return winreg.OpenKey(root, path)
    except OSError:
        return None


def _read_tree(root: Any, path: str) -> dict[str, str]:
    import winreg

    values: dict[str, str] = {}
    key = _open_registry_key(root, path)
    if key is None:
        return values
    stack: list[tuple[str, Any]] = [("", key)]
    while stack:
        prefix, current = stack.pop()
        with current:
            index = 0
            while True:
                try:
                    name, value, _kind = winreg.EnumValue(current, index)
                except OSError:
                    break
                if value is not None:
                    key_name = f"{prefix}/{name}" if prefix else name
                    values[key_name] = value
                index += 1
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(current, index)
                except OSError:
                    break
                child = _open_registry_key(current, sub)
                if child is not None:
                    stack.append((f"{prefix}/{sub}" if prefix else sub, child))
                index += 1
    return values


def read_registry_values() -> dict[str, str]:
    """Baca QSettings lama; organisasi baru diprioritaskan atas organisasi lama."""
    try:
        import winreg
    except ImportError:  # pragma: no cover - Windows selalu punya winreg
        return {}
    for org, app in (
        (keys.SETTINGS_ORG, keys.SETTINGS_APP),
        (keys.LEGACY_SETTINGS_ORG, keys.LEGACY_SETTINGS_APP),
    ):
        values = _read_tree(winreg.HKEY_CURRENT_USER, rf"Software\{org}\{app}")
        if values:
            return values
    return {}


class SettingsStore:
    """Akses bertipe ke berkas preferensi JSON (thread-safe, tulis atomik)."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        registry_reader: RegistryReader | None = None,
        persist: bool = True,
    ) -> None:
        self.path = Path(path).expanduser() if path else default_path()
        self._lock = threading.RLock()
        self._values: dict[str, Any] = {}
        self._persist = persist
        self._registry_reader = (
            registry_reader if registry_reader is not None else read_registry_values
        )
        self._load()
        self._migrate()

    # -- berkas ------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SettingsError(
                f"Preferensi tidak bisa dibaca: {self.path} ({exc})"
            ) from exc
        values = data.get("values") if isinstance(data, dict) else None
        if not isinstance(values, dict):
            return
        self._values = {
            str(key): normalize(str(key), value)
            for key, value in values.items()
            if value is not None
        }

    def save(self) -> None:
        if not self._persist:
            return
        payload = {
            "version": FILE_VERSION,
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "values": self._values,
        }
        temp = ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(
                dir=str(self.path.parent), prefix=".settings-", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp, self.path)
        except OSError as exc:
            if temp:
                try:
                    os.unlink(temp)
                except OSError:
                    pass
            raise SettingsError(
                f"Preferensi tidak bisa disimpan: {self.path} ({exc})"
            ) from exc

    # -- migrasi -----------------------------------------------------------
    def _migrate(self) -> None:
        """Salin QSettings sekali; nilai JSON yang sudah ada selalu menang."""
        if _as_bool(self._values.get(MIGRATION_FLAG)):
            return
        try:
            raw = dict(self._registry_reader() or {})
        except (OSError, RuntimeError):
            raw = {}
        migrated = {
            str(key): normalize(str(key), value)
            for key, value in raw.items()
            if value is not None
        }
        for legacy, current in (
            (keys.LINEAGE_TENANT_KEY, keys.AUTH_TENANT_KEY),
            (keys.LINEAGE_CLIENT_KEY, keys.AUTH_CLIENT_KEY),
            (keys.LINEAGE_SECRET_KEY, keys.AUTH_SECRET_KEY),
            (keys.LINEAGE_DB_KEY, keys.PATHS_LINEAGE_DB_KEY),
        ):
            old_value = migrated.get(legacy)
            if old_value not in (None, "") and migrated.get(current) in (None, ""):
                migrated[current] = old_value
        merged = dict(migrated)
        merged.update(self._values)
        merged[MIGRATION_FLAG] = True
        self._values = merged
        self.save()

    # -- dasar -------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def get_bool(self, key: str, default: bool = False) -> bool:
        return _as_bool(self.get(key, default), default)

    def get_int(self, key: str, default: int = 0) -> int:
        return _as_int(self.get(key, default), default)

    def get_str(self, key: str, default: str = "") -> str:
        value = self.get(key, default)
        if value is None:
            return default
        return str(value)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._values[key] = normalize(key, value)
            self.save()

    def update(self, values: Mapping[str, Any]) -> None:
        with self._lock:
            for key, value in values.items():
                self._values[str(key)] = normalize(str(key), value)
            self.save()

    def remove(self, key: str) -> None:
        with self._lock:
            if self._values.pop(key, None) is not None:
                self.save()

    def all(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def reset_session(self) -> None:
        """Kosongkan pilihan sesi; preferensi tidak disentuh."""
        with self._lock:
            changed = False
            for key in keys.SESSION_SELECTION_KEYS:
                if self._values.pop(key, None) is not None:
                    changed = True
            if changed:
                self.save()

    # -- kredensial --------------------------------------------------------
    def principal(self) -> ServicePrincipal:
        return ServicePrincipal.from_values(
            self.get_str(keys.AUTH_TENANT_KEY),
            self.get_str(keys.AUTH_CLIENT_KEY),
            self.get_str(keys.AUTH_SECRET_KEY),
        )

    def set_principal(self, principal: ServicePrincipal) -> None:
        self.update(
            {
                keys.AUTH_TENANT_KEY: principal.tenant_id,
                keys.AUTH_CLIENT_KEY: principal.client_id,
                keys.AUTH_SECRET_KEY: principal.client_secret,
            }
        )

    def rls(self) -> tuple[str, tuple[str, ...]]:
        return (
            self.get_str(keys.AUTH_RLS_USER_KEY),
            split_roles(self.get_str(keys.AUTH_RLS_ROLES_KEY)),
        )

    def set_rls(self, username: str, roles: str | tuple[str, ...] | list[str]) -> None:
        text = roles if isinstance(roles, str) else ",".join(roles)
        self.update(
            {
                keys.AUTH_RLS_USER_KEY: (username or "").strip(),
                keys.AUTH_RLS_ROLES_KEY: text.strip(),
            }
        )

    # -- path --------------------------------------------------------------
    def lineage_db(self) -> str:
        return self.get_str(keys.PATHS_LINEAGE_DB_KEY)

    def set_lineage_db(self, value: Path | str) -> None:
        self.set(keys.PATHS_LINEAGE_DB_KEY, str(value))

    def describe(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "exists": self.path.exists(),
            "migrated": _as_bool(self.get(MIGRATION_FLAG)),
        }
