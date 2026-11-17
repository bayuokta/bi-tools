"""View model tab Pengaturan.

Satu tempat membaca/menulis kredensial service principal, RLS default, dan path
database. View hanya menampilkan nilai dan meneruskan input.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

from core.auth import (
    FABRIC_SCOPE,
    POWERBI_SCOPE,
    EntraTokens,
    ServicePrincipal,
)
from core.catalog_sync import run_workspace_sync
from core.errors import ExtractionError
from core.lineage_scan import run_lineage_scan
from core.lineage_service import database_summary, workspace_status
from core.lineage_store import DEFAULT_DB

from ..formatting import ERROR_COLOR, OK_COLOR, credential_status, duration_text
from ..settings import SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY, SETTINGS_CATALOG_MODE_KEY
from ..settings_store import AppSettings
from .metadata import JobSubmitter

CATALOG_MODES = ("auto", "admin", "member")


@dataclass(frozen=True)
class SettingsState:
    """Nilai formulir dan status yang dirender tab Pengaturan."""

    idle: bool
    tenant_id: str
    client_id: str
    client_secret: str
    rls_username: str
    rls_roles: str
    database: str
    status_text: str
    status_color: str
    catalog_mode: str = "auto"
    full_scan: bool = False
    include_personal: bool = False
    sync_status: str = ""
    sync_status_color: str = ""


class SettingsViewModel(QObject):
    """Pemilik formulir kredensial/path dan aksi simpan/tes koneksi."""

    state_changed = Signal(object)
    log = Signal(str)

    def __init__(self, settings: AppSettings, runner: JobSubmitter) -> None:
        super().__init__()
        self._settings = settings
        self._runner = runner
        self._busy = False
        self._saving = False
        self._feedback: tuple[str, str] | None = None
        self._tenant_id = ""
        self._client_id = ""
        self._client_secret = ""
        self._rls_username = ""
        self._rls_roles = ""
        self._database = str(DEFAULT_DB)
        self._catalog_mode = "auto"
        self._full_scan = False
        self._include_personal = False
        self._sync_status = ""
        self._sync_color = ""
        self._reload(emit=False)
        self._settings.changed.connect(self._on_settings_changed)

    # -- siklus ------------------------------------------------------------
    def start(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self.state_changed.emit(self.build_state())

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if busy == self._busy:
            return
        self._busy = busy
        self.refresh()

    # -- formulir ----------------------------------------------------------
    def apply(self, **changes: Any) -> None:
        """Perbarui field dari widget; hapus pesan tes/kesalahan lama."""
        updated = False
        for name, value in changes.items():
            field = f"_{name}"
            if not hasattr(self, field):
                raise AttributeError(f"SettingsViewModel tidak punya field {name!r}")
            value = str(value or "").strip() if name != "client_secret" else str(value)
            if getattr(self, field) == value:
                continue
            setattr(self, field, value)
            updated = True
        if updated:
            self._feedback = None
            self.refresh()

    def principal(self) -> ServicePrincipal:
        return ServicePrincipal.from_values(
            self._tenant_id, self._client_id, self._client_secret
        )

    def build_state(self) -> SettingsState:
        if self._feedback is not None:
            text, color = self._feedback
        else:
            text, color = credential_status(self.principal())
        return SettingsState(
            idle=not self._busy,
            tenant_id=self._tenant_id,
            client_id=self._client_id,
            client_secret=self._client_secret,
            rls_username=self._rls_username,
            rls_roles=self._rls_roles,
            database=self._database,
            status_text=text,
            status_color=color,
            catalog_mode=self._catalog_mode,
            full_scan=self._full_scan,
            include_personal=self._include_personal,
            sync_status=self._sync_status,
            sync_status_color=self._sync_color,
        )

    # -- muat --------------------------------------------------------------
    def _reload(self, *, emit: bool = True) -> None:
        principal = self._settings.principal()
        self._tenant_id = principal.tenant_id
        self._client_id = principal.client_id
        self._client_secret = principal.client_secret
        username, roles = self._settings.rls()
        self._rls_username = username
        self._rls_roles = ",".join(roles)
        self._database = self._settings.lineage_db() or str(DEFAULT_DB)
        self._catalog_mode = self._saved_catalog_mode()
        self._include_personal = bool(
            self._settings.value(
                SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY, False, type=bool
            )
        )
        self._refresh_sync_status()
        self._feedback = None
        if emit:
            self.refresh()

    def _saved_catalog_mode(self) -> str:
        saved = str(
            self._settings.value(SETTINGS_CATALOG_MODE_KEY, "auto", type=str) or "auto"
        )
        return saved if saved in CATALOG_MODES else "auto"

    def _database_path(self) -> str:
        """Path database yang sudah disimpan (dipakai sync dan status katalog)."""
        return self._settings.lineage_db() or str(DEFAULT_DB)

    def _refresh_sync_status(self) -> None:
        """Gabungkan status katalog workspace dan hasil scan lineage."""
        path = self._database_path()
        try:
            summary = workspace_status(path)
        except ExtractionError as exc:
            self._sync_status = f"Database tidak bisa dibaca: {exc}"
            self._sync_color = ERROR_COLOR
            return
        database = database_summary(path)
        if database.exists and not database.readable:
            self._sync_status = f"Database tidak bisa dibaca: {database.error}"
            self._sync_color = ERROR_COLOR
            return
        total = int(summary.get("total") or 0)
        active = int(summary.get("active") or 0)
        selectable = int(summary.get("selectable", active) or 0)
        last_sync = self._format_time(str(summary.get("last_sync") or ""))
        last_mode = str(summary.get("last_mode") or "")
        last_scan = self._format_time(database.last_scan)
        if total:
            text = f"{selectable} workspace siap dipilih dari {total} tersimpan"
            if last_sync:
                suffix = f" ({last_mode})" if last_mode else ""
                text += f" · sync katalog {last_sync}{suffix}"
            color = OK_COLOR if selectable else ERROR_COLOR
        else:
            text = "Belum ada katalog workspace tersimpan"
            color = ""
        if last_scan:
            text += f" · scan lineage {last_scan}"
        else:
            text += " · scan lineage belum pernah dijalankan"
        self._sync_status = text
        self._sync_color = color

    @staticmethod
    def _format_time(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return text.replace("T", " ")[:16]

    def _on_settings_changed(self, group: str) -> None:
        if self._saving:
            return
        if group in {"auth", "paths"}:
            self._reload()

    # -- aksi --------------------------------------------------------------
    def save(self) -> bool:
        principal = self.principal()
        if not principal.is_complete:
            self._feedback = (
                "Lengkapi kolom berikut: " + ", ".join(principal.missing),
                ERROR_COLOR,
            )
            self.refresh()
            return False

        username = self._rls_username
        roles = self._rls_roles
        database = self._database or str(DEFAULT_DB)
        self._saving = True
        try:
            self._settings.set_principal(principal)
            self._settings.set_rls(username, roles)
            self._settings.set_lineage_db(database)
        finally:
            self._saving = False
        self._feedback = None
        self.log.emit("Kredensial dan path disimpan; dipakai semua tab.")
        self._reload(emit=False)
        self.refresh()
        return True

    # -- sinkronisasi data -------------------------------------------------
    def set_catalog_mode(self, mode: str) -> None:
        value = str(mode or "").strip()
        if value not in CATALOG_MODES:
            raise ExtractionError(f"Mode sinkronisasi tidak dikenal: {mode}")
        if value == self._catalog_mode:
            return
        self._catalog_mode = value
        self._settings.set_value(SETTINGS_CATALOG_MODE_KEY, value)
        self.refresh()

    def set_full_scan(self, value: bool) -> None:
        value = bool(value)
        if value == self._full_scan:
            return
        self._full_scan = value
        self.refresh()

    def set_include_personal(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self._include_personal:
            return
        self._include_personal = enabled
        self._settings.set_value(SETTINGS_CATALOG_INCLUDE_PERSONAL_KEY, enabled)
        self.refresh()

    def sync_catalog(self) -> bool:
        principal = self.principal()
        if not principal.is_complete:
            self._sync_status = (
                "Lengkapi Tenant ID, Client ID, dan Client Secret sebelum "
                "sinkronisasi."
            )
            self._sync_color = ERROR_COLOR
            self.refresh()
            return False

        database = self._database_path()
        mode = self._catalog_mode

        def job(log):
            return run_workspace_sync(database, principal, mode=mode, log=log)

        self._sync_status = "Sinkronisasi katalog berjalan..."
        self._sync_color = ""
        self.refresh()
        accepted = self._runner.submit(
            "Sinkronisasi katalog workspace", job, self.apply_sync_result
        )
        if accepted is False:
            self._sync_status = (
                "Pekerjaan lain masih berjalan; coba lagi setelah selesai."
            )
            self._sync_color = ERROR_COLOR
            self.refresh()
            return False
        return True

    def apply_sync_result(self, result: Any) -> None:
        self._refresh_sync_status()
        if result is not None:
            count = int(getattr(result, "workspace_count", 0) or 0)
            mode = str(getattr(result, "mode", self._catalog_mode))
            duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)
            self._sync_status = (
                f"Sinkronisasi katalog selesai: {count} workspace ({mode}, "
                f"{duration_text(duration)}). {self._sync_status}"
            )
            self._sync_color = OK_COLOR
            self.log.emit(
                f"Katalog workspace: {count} workspace, mode {mode}."
            )
        self.refresh()

    def run_scan(self) -> bool:
        """Jalankan scan lineage ke database yang sudah disimpan."""
        principal = self.principal()
        try:
            principal.validate()
        except ExtractionError as exc:
            self._sync_status = f"Kredensial belum lengkap: {exc}"
            self._sync_color = ERROR_COLOR
            self.refresh()
            return False

        database = self._database_path()
        mode = self._catalog_mode
        full = self._full_scan
        include_personal = self._include_personal

        def job(log):
            return run_lineage_scan(
                database,
                principal,
                mode=mode,
                full=full,
                include_personal=include_personal,
                log=log,
            )

        self._sync_status = "Scan lineage berjalan..."
        self._sync_color = ""
        self.refresh()
        accepted = self._runner.submit(
            "Scan lineage Power BI", job, self.apply_scan_result
        )
        if accepted is False:
            self._sync_status = (
                "Pekerjaan lain masih berjalan; coba lagi setelah selesai."
            )
            self._sync_color = ERROR_COLOR
            self.refresh()
            return False
        return True

    def apply_scan_result(self, result: Any) -> None:
        self._refresh_sync_status()
        if result is not None:
            workspaces = int(getattr(result, "workspace_count", 0) or 0)
            nodes = int(getattr(result, "node_count", 0) or 0)
            edges = int(getattr(result, "edge_count", 0) or 0)
            mode = str(getattr(result, "mode", self._catalog_mode))
            duration = float(getattr(result, "duration_seconds", 0.0) or 0.0)
            scope = (
                "termasuk personal"
                if bool(getattr(result, "include_personal", False))
                else "tanpa personal"
            )
            self._sync_status = (
                f"Scan lineage selesai: {workspaces} workspace ({scope}), "
                f"{nodes} node, {edges} edge "
                f"(mode {mode}, {duration_text(duration)}). {self._sync_status}"
            )
            self._sync_color = OK_COLOR
            self.log.emit(
                f"Lineage: {workspaces} workspace ({scope}), {nodes} node, "
                f"{edges} edge (mode {mode}, {duration_text(duration)})."
            )
            unresolved = int(getattr(result, "unresolved_sources", 0) or 0)
            if unresolved:
                self.log.emit(
                    f"CATATAN: {unresolved} sumber feed belum punya metadata."
                )
        self.refresh()

    def test_connection(self) -> bool:
        principal = self.principal()
        if not principal.is_complete:
            self._feedback = None
            self.refresh()
            return False

        def job(log):
            log("Mengambil token Fabric dan Power BI...")
            tokens = EntraTokens(principal)
            tokens.get(FABRIC_SCOPE)
            log("Token Fabric OK.")
            tokens.get(POWERBI_SCOPE)
            log("Token Power BI OK (dipakai REST, embed, dan XMLA).")
            return "ok"

        self._feedback = None
        accepted = self._runner.submit(
            "Tes koneksi Power BI", job, self.apply_test_result
        )
        return accepted is not False

    def apply_test_result(self, _result: Any) -> None:
        self._feedback = (
            "Tes koneksi berhasil: token Fabric dan Power BI diterima.",
            OK_COLOR,
        )
        self.refresh()
