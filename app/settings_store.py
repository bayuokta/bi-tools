"""Satu pemilik QSettings untuk seluruh GUI.

Tab tidak lagi membuat ``QSettings`` sendiri. Semua perubahan lewat
:class:`AppSettings` agar status kredensial di tab lain ikut diperbarui
(``changed`` per grup kunci) dan kunci lama ``lineage/*`` termigrasi sekali.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QSettings, Signal

from core.auth import ServicePrincipal
from core.pbi_capture.credentials import split_roles

from .settings import (
    AUTH_CLIENT_KEY,
    AUTH_SECRET_KEY,
    AUTH_TENANT_KEY,
    LINEAGE_CLIENT_KEY,
    LINEAGE_DB_KEY,
    LINEAGE_SECRET_KEY,
    LINEAGE_TENANT_KEY,
    PATHS_LINEAGE_DB_KEY,
    SESSION_SELECTION_KEYS,
    SETTINGS_APP,
    SETTINGS_MIGRATED_KEY,
    SETTINGS_ORG,
)


class AppSettings(QObject):
    """Akses bertipe ke QSettings + notifikasi perubahan per grup."""

    changed = Signal(str)

    def __init__(
        self,
        settings: QSettings | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings or QSettings(SETTINGS_ORG, SETTINGS_APP)
        self._migrate()

    # -- dasar -------------------------------------------------------------
    def value(self, key: str, default: Any = None, type: Any = None) -> Any:
        if type is not None:
            return self._settings.value(key, default, type=type)
        return self._settings.value(key, default)

    def set_value(self, key: str, value: Any) -> None:
        self._settings.setValue(key, value)
        self.changed.emit(key.split("/", 1)[0])

    def reset_session(self) -> None:
        """Kosongkan pilihan sesi (workspace/report/dataset/instance) saat aplikasi dibuka.

        Preferensi (kredensial, RLS, path database, cakupan, filter, sort, tab
        aktif, opsi render TSD) tidak disentuh.
        """
        for key in SESSION_SELECTION_KEYS:
            self._settings.remove(key)
        self.sync()

    def sync(self) -> None:
        self._settings.sync()

    @property
    def raw(self) -> QSettings:
        """Akses langsung untuk kasus khusus (mis. setValue massal di tab)."""
        return self._settings

    # -- kredensial --------------------------------------------------------
    def principal(self) -> ServicePrincipal:
        return ServicePrincipal.from_values(
            str(self.value(AUTH_TENANT_KEY, "", type=str) or ""),
            str(self.value(AUTH_CLIENT_KEY, "", type=str) or ""),
            str(self.value(AUTH_SECRET_KEY, "", type=str) or ""),
        )

    def set_principal(self, principal: ServicePrincipal) -> None:
        self._settings.setValue(AUTH_TENANT_KEY, principal.tenant_id)
        self._settings.setValue(AUTH_CLIENT_KEY, principal.client_id)
        self._settings.setValue(AUTH_SECRET_KEY, principal.client_secret)
        self.changed.emit("auth")

    def rls(self) -> tuple[str, tuple[str, ...]]:
        return (
            str(self.value("auth/rls_username", "", type=str) or ""),
            split_roles(str(self.value("auth/rls_roles", "", type=str) or "")),
        )

    def set_rls(self, username: str, roles: str | tuple[str, ...]) -> None:
        text = ",".join(roles) if not isinstance(roles, str) else roles
        self._settings.setValue("auth/rls_username", (username or "").strip())
        self._settings.setValue("auth/rls_roles", text.strip())
        self.changed.emit("auth")

    # -- path --------------------------------------------------------------
    def lineage_db(self) -> str:
        return str(self.value(PATHS_LINEAGE_DB_KEY, "", type=str) or "")

    def set_lineage_db(self, value: Path | str) -> None:
        self._settings.setValue(PATHS_LINEAGE_DB_KEY, str(value))
        self.changed.emit("paths")

    # -- migrasi -----------------------------------------------------------
    def _migrate(self) -> None:
        """Salin kunci lama ``lineage/*`` ke ``auth/*``/``paths/*`` sekali.

        Kunci lama sengaja tidak dihapus pada rilis ini agar pengguna bisa
        rollback; pembersihan dilakukan setelah satu rilis stabil.
        """
        if bool(self._settings.value(SETTINGS_MIGRATED_KEY, False, type=bool)):
            return
        pairs = (
            (LINEAGE_TENANT_KEY, AUTH_TENANT_KEY),
            (LINEAGE_CLIENT_KEY, AUTH_CLIENT_KEY),
            (LINEAGE_SECRET_KEY, AUTH_SECRET_KEY),
            (LINEAGE_DB_KEY, PATHS_LINEAGE_DB_KEY),
        )
        for legacy, current in pairs:
            old = self._settings.value(legacy, None)
            new = self._settings.value(current, None)
            if old not in (None, "") and new in (None, ""):
                self._settings.setValue(current, old)
        self._settings.setValue(SETTINGS_MIGRATED_KEY, True)
        self._settings.sync()
