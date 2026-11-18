"""View model sub-tab Generate TSD.

Memegang formulir ``tsd/*`` (lewat :class:`TsdForm`), path turunan, status
cache/output, penyusunan :class:`TsdRequest` dan :class:`CaptureRequest`, serta
orkestrasi job render/capture. View hanya mengisi widget, memanggil setter, dan
merender :class:`TsdState`.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QObject, Signal

from core.auth import DeferredTokenProvider, EntraTokens, powerbi_provider
from core.errors import ExtractionError
from core.lineage_service import WorkspaceOption
from core.lineage_store import DEFAULT_DB
from core.pbi_capture import (
    CaptureOptions,
    cache_dir,
    capture_report,
    load_screenshot_set,
)
from core.pbi_capture.credentials import split_roles
from core.pbix import ROOT
from core.requests import CaptureRequest, TsdRequest
from core.tsd import (
    TEMPLATE_PATH,
    format_date,
    load_manual,
    output_file_name,
    run_tsd,
    write_manual,
)

from ..formatting import file_status
from ..forms import TsdForm, section
from ..settings_store import AppSettings
from .metadata import JobSubmitter
from .service_picker import (
    BUSY_MESSAGE,
    MISSING_CREDENTIALS,
    is_paginated,
    report_label,
    workspace_contents_job,
    workspace_label,
    workspace_picklist,
)


@dataclass(frozen=True)
class TsdState:
    """Keadaan sub-tab TSD yang dirender view."""

    idle: bool
    can_run: bool
    can_capture: bool
    can_clear_cache: bool
    output_exists: bool
    folder_ready: bool
    report_status: str
    model_status: str
    template_status: str
    manual_status: str
    output_status: str
    cache_status: str
    out_name: str
    rls_username: str
    rls_roles: str
    workspaces: tuple[str, ...] = ()
    workspace_index: int = -1
    reports: tuple[str, ...] = ()
    report_index: int = -1
    workspace_hint: str = ""
    settings_shortcut_visible: bool = False
    loading_text: str = ""
    message: str = ""
    picker_active: bool = False
    reports_active: bool = False


class TsdViewModel(QObject):
    """Satu sumber kebenaran untuk formulir dan aksi Generate TSD."""

    state_changed = Signal(object)
    log = Signal(str)

    def __init__(self, settings: AppSettings, runner: JobSubmitter) -> None:
        super().__init__()
        self._settings = settings
        self._runner = runner
        self._form = TsdForm.load(settings)
        self._report_name = ""
        self._out_name = output_file_name("Report")
        self._out_name_auto = True
        self._generated_at = format_date()
        self._headless = True
        self._manual_data: dict[str, Any] = {}
        self._busy = False
        self._workspace_options: tuple[WorkspaceOption, ...] = ()
        self._report_items: tuple[dict[str, Any], ...] = ()
        self._loading = ""
        self._message = ""
        self._workspace_hint = ""
        self._settings.changed.connect(self._on_settings_changed)

    # -- siklus ------------------------------------------------------------
    def start(self) -> None:
        """Baca katalog workspace (SQLite); report dimuat saat sub-tab dibuka."""
        self._load_workspace_options()
        if self._out_name_auto:
            self._out_name = self._auto_out_name()
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
    @property
    def form(self) -> TsdForm:
        return self._form

    @property
    def report_name(self) -> str:
        return self._report_name

    @property
    def out_name(self) -> str:
        return self._out_name

    @property
    def generated_at(self) -> str:
        return self._generated_at

    @property
    def manual_data(self) -> dict[str, Any]:
        return self._manual_data

    def apply(self, **changes: Any) -> None:
        """Perbarui field ``TsdForm`` dari widget; abaikan nilai yang sama."""
        updated = False
        for name, value in changes.items():
            if not hasattr(self._form, name):
                raise AttributeError(f"TsdForm tidak punya field {name!r}")
            if isinstance(value, str):
                value = value.strip()
            if getattr(self._form, name) == value:
                continue
            setattr(self._form, name, value)
            updated = True
        if updated:
            if "report_id" in changes:
                self._refresh_auto_out_name()
            self.refresh()

    def set_report_name(self, text: str) -> None:
        name = (text or "").strip()
        if name == self._report_name:
            return
        self._report_name = name
        if self._out_name_auto:
            self._out_name = self._auto_out_name()
        self.refresh()

    def _auto_out_name(self) -> str:
        """Nama file bawaan; report Service memakai akhiran 8 karakter ID."""
        return output_file_name(
            self._report_name or "Report", self._form.report_id
        )

    def _refresh_auto_out_name(self) -> None:
        if self._out_name_auto:
            self._out_name = self._auto_out_name()

    def set_out_name(self, text: str, *, automatic: bool = False) -> None:
        name = (text or "").strip()
        changed = name != self._out_name
        self._out_name = name
        if not automatic:
            self._out_name_auto = False
        if changed:
            self.refresh()

    def set_generated_at(self, text: str) -> None:
        self._generated_at = (text or "").strip()

    def set_headless(self, headless: bool) -> None:
        self._headless = bool(headless)

    def set_rls(self, username: str, roles: str) -> None:
        self.apply(rls_username=username, rls_roles=roles)

    def save_settings(self) -> None:
        self._form.save(self._settings)

    # -- picker Power BI Service -------------------------------------------
    @property
    def workspaces(self) -> tuple[str, ...]:
        return tuple(workspace_label(option) for option in self._workspace_options)

    @property
    def reports(self) -> tuple[str, ...]:
        return tuple(report_label(item) for item in self._report_items)

    @property
    def workspace_index(self) -> int:
        return self._find_workspace_index(self._form.workspace_id)

    @property
    def report_index(self) -> int:
        return self._find_report_index(self._form.report_id)

    def reload_workspaces(self) -> None:
        """Baca ulang katalog SQLite lalu muat report workspace terpilih."""
        self._load_workspace_options()
        self.refresh()
        self.ensure_reports()

    def ensure_reports(self) -> None:
        """Muat daftar report bila workspace sudah dipilih dan daftarnya kosong."""
        if self._loading or self._busy or self._report_items:
            return
        if not self._form.workspace_id:
            return
        self._load_reports()

    def reload_reports(self) -> None:
        """Ambil ulang daftar report workspace terpilih dari REST API."""
        if not self._form.workspace_id:
            self._message = "Pilih workspace lebih dulu."
            self.refresh()
            return
        self._report_items = ()
        self._message = ""
        self._load_reports()
        self.refresh()

    def select_workspace(self, index: int) -> None:
        index = int(index)
        if index < 0 or index >= len(self._workspace_options):
            return
        option = self._workspace_options[index]
        if option.workspace_id == self._form.workspace_id:
            return
        self._report_items = ()
        self._loading = ""
        self._message = ""
        self._workspace_hint = ""
        self.apply(workspace_id=option.workspace_id, report_id="")
        self._refresh_auto_out_name()
        self._persist_selection()
        self._load_reports()
        self.refresh()

    def select_report(self, index: int) -> None:
        index = int(index)
        if index < 0 or index >= len(self._report_items):
            return
        item = self._report_items[index]
        report_id = str(item.get("id") or "")
        if report_id == self._form.report_id:
            return
        self._message = ""
        self.apply(report_id=report_id)
        self._refresh_auto_out_name()
        self._persist_selection()
        if is_paginated(item):
            self._message = (
                "Report paginated (RDL) tidak didukung untuk screenshot; "
                "pilih report Power BI."
            )
        elif not self._report_name:
            self.set_report_name(str(item.get("name") or ""))
        self.refresh()

    def apply_reports(self, result: Any) -> None:
        """Callback job pembacaan report workspace (dijalankan JobRunner)."""
        self._loading = ""
        if not isinstance(result, dict):
            self.refresh()
            return
        if str(result.get("workspace_id") or "") != self._form.workspace_id:
            # Pemilihan workspace berubah sebelum hasil datang; buang hasil lama.
            self.refresh()
            return
        self._report_items = tuple(
            item for item in result.get("reports") or () if isinstance(item, dict)
        )
        if self._form.report_id and self.report_index < 0:
            self._message = "Report terakhir tidak ditemukan di workspace ini."
        self.refresh()

    def _persist_selection(self) -> None:
        self._form.save_selection(self._settings)

    def _load_workspace_options(self) -> None:
        database = self._settings.lineage_db() or str(DEFAULT_DB)
        options, _duplicates, hint = workspace_picklist(database)
        self._workspace_options = options
        self._workspace_hint = hint

    def _find_workspace_index(self, workspace_id: str) -> int:
        if not workspace_id:
            return -1
        return next(
            (
                index
                for index, option in enumerate(self._workspace_options)
                if option.workspace_id == workspace_id
            ),
            -1,
        )

    def _find_report_index(self, report_id: str) -> int:
        if not report_id:
            return -1
        return next(
            (
                index
                for index, item in enumerate(self._report_items)
                if str(item.get("id") or "") == report_id
            ),
            -1,
        )

    def _load_reports(self) -> bool:
        """Submit job pembacaan report; ``False`` bila job ditolak."""
        workspace_id = self._form.workspace_id
        if not workspace_id:
            return True
        principal = self._settings.principal()
        if not principal.is_complete:
            self._message = MISSING_CREDENTIALS
            self._loading = ""
            return True
        if self._busy:
            self._message = BUSY_MESSAGE
            self._loading = ""
            return True

        self._loading = "Memuat daftar report workspace..."
        job = workspace_contents_job(
            principal, workspace_id, datasets=False, reports=True
        )
        accepted = self._runner.submit(
            "Membaca report workspace", job, self.apply_reports
        )
        if accepted is False:
            self._loading = ""
            self._message = "Pekerjaan lain masih berjalan; coba lagi setelah selesai."
            return False
        self.refresh()
        return True

    # -- path --------------------------------------------------------------
    @property
    def output_path(self) -> Path:
        text = self._form.out_dir.strip()
        folder = Path(text).expanduser() if text else ROOT
        name = self._out_name.strip()
        if not name or self._out_name_auto:
            name = self._auto_out_name()
        return folder / name

    @property
    def manual_path(self) -> Path:
        text = self._form.manual_path.strip()
        if text:
            return Path(text).expanduser()
        return self.output_path.with_suffix(".json")

    @property
    def assets_dir(self) -> Path:
        return cache_dir(
            self.output_path.parent,
            self._report_name or "Report",
            self._form.report_id.strip(),
        )

    # -- state -------------------------------------------------------------
    def build_state(self) -> TsdState:
        idle = not self._busy
        report_text = self._form.report_workbook
        report_exists = bool(report_text) and Path(report_text).expanduser().exists()
        model_text = self._form.model_workbook
        output = self.output_path
        shots_ready = (
            not self._form.screenshots
            or (
                bool(self._form.workspace_id.strip())
                and bool(self._form.report_id.strip())
            )
        )
        return TsdState(
            idle=idle,
            can_run=(
                idle
                and bool(report_text)
                and report_exists
                and bool(self._form.out_dir.strip())
                and shots_ready
            ),
            can_capture=idle and self._form.screenshots,
            can_clear_cache=idle and self.assets_dir.exists(),
            output_exists=output.exists(),
            folder_ready=bool(self._form.out_dir.strip()),
            report_status=self._report_status(report_text),
            model_status=self._model_status(model_text),
            template_status=self._template_status(),
            manual_status=file_status(self.manual_path),
            output_status=file_status(output),
            cache_status=self._cache_status(),
            out_name=self._out_name,
            rls_username=self._form.rls_username,
            rls_roles=self._form.rls_roles,
            workspaces=self.workspaces,
            workspace_index=self.workspace_index,
            reports=self.reports,
            report_index=self.report_index,
            workspace_hint=self._workspace_hint,
            settings_shortcut_visible=not self._workspace_options,
            loading_text=self._loading,
            message=self._message,
            picker_active=bool(self._form.screenshots),
            reports_active=(
                bool(self._form.screenshots) and bool(self._form.workspace_id)
            ),
        )

    @staticmethod
    def _report_status(text: str) -> str:
        if not text:
            return "Belum dipilih"
        return file_status(Path(text).expanduser())

    @staticmethod
    def _model_status(text: str) -> str:
        if not text:
            return "Tidak dipakai"
        return file_status(Path(text).expanduser())

    @staticmethod
    def _template_status() -> str:
        if TEMPLATE_PATH.exists():
            return (
                f"templates\\{TEMPLATE_PATH.name}  "
                "(ada, versi template dari repo template-tsd)"
            )
        return (
            "templates\\tsd.template.html belum ada; "
            "salin dari repo template-tsd."
        )

    def _cache_status(self) -> str:
        if not self._form.screenshots:
            return "Tidak dipakai"
        folder = self.assets_dir
        cached = load_screenshot_set(folder)
        if cached is None:
            return f"Belum ada cache; akan diambil saat generate.\n{folder}"
        return f"{cached.summary()}\n{folder}"

    # -- kredensial --------------------------------------------------------
    def _rls(self) -> tuple[str, tuple[str, ...]]:
        """RLS efektif: override per-run, atau default tab Pengaturan."""
        username = self._form.rls_username.strip()
        roles = self._form.rls_roles.strip()
        if not username and not roles:
            default_user, default_roles = self._settings.rls()
            return default_user, tuple(default_roles)
        return username, split_roles(roles)

    def _token_provider(self) -> DeferredTokenProvider:
        """Provider lazy: cache screenshot bisa dipakai tanpa kredensial."""
        return DeferredTokenProvider(
            lambda: powerbi_provider(EntraTokens(self._settings.principal()))
        )

    def _on_settings_changed(self, group: str) -> None:
        if group == "paths":
            self.reload_workspaces()
            return
        if group != "auth":
            return
        if self._form.rls_username.strip() or self._form.rls_roles.strip():
            return  # override per-run tidak boleh ditimpa default
        username, roles = self._settings.rls()
        self._form.rls_username = username
        self._form.rls_roles = ",".join(roles)
        self.refresh()

    # -- request -----------------------------------------------------------
    def build_capture_request(self, refresh: bool = False) -> CaptureRequest:
        username, roles = self._rls()
        workbook = self._form.report_workbook.strip()
        return CaptureRequest(
            workspace_id=self._form.workspace_id,
            report_id=self._form.report_id,
            rls_username=username,
            rls_roles=roles,
            scope=self._form.shot_scope or "both",
            scale=float(self._form.shot_scale or 1.0),
            mobile=bool(self._form.shot_mobile),
            headless=self._headless,
            output_root=self.assets_dir,
            refresh=refresh,
            include_decorative=bool(self._form.include_decorative),
            auto_install_browser=bool(self._form.auto_install_browser),
            hints_workbook=Path(workbook).expanduser() if workbook else None,
        )

    def capture_options(self, refresh: bool = False) -> CaptureOptions:
        return self.build_capture_request(refresh).to_options(self._token_provider())

    def build_request(
        self, manual: Mapping[str, Any] | None = None
    ) -> tuple[TsdRequest, CaptureOptions | None]:
        """Susun request render; melempar ``ExtractionError`` bila belum siap."""
        report_text = self._form.report_workbook
        if not report_text:
            raise ExtractionError("pilih workbook Report_Metadata.xlsx.")
        report_path = Path(report_text).expanduser()
        if not report_path.exists():
            raise ExtractionError(f"workbook report tidak ditemukan: {report_path}")

        model_path: Path | None = None
        model_text = self._form.model_workbook
        if model_text:
            candidate = Path(model_text).expanduser()
            if candidate.exists():
                model_path = candidate
            else:
                self.log.emit(
                    f"Catatan: workbook model tidak ditemukan ({candidate}); "
                    "bagian model TSD dikosongkan."
                )

        merged = dict(manual or {})
        if self._report_name:
            report_section = section(merged, "report")
            report_section["name"] = self._report_name
            merged["report"] = report_section

        capture = None
        if self._form.screenshots:
            capture = self.capture_options()

        request = TsdRequest(
            report_workbook=report_path,
            model_workbook=model_path,
            out_file=self.output_path,
            manual_path=self.manual_path,
            manual=merged,
            report_name=self._report_name,
            report_id=self._form.report_id,
            draft=self._form.draft,
            expand_all=self._form.expand_all,
            generated_at=self._generated_at or None,
            include_decorative=self._form.include_decorative,
        )
        return request, capture

    # -- aksi --------------------------------------------------------------
    def run(self, manual: Mapping[str, Any] | None = None) -> bool:
        try:
            request, capture = self.build_request(manual)
        except ExtractionError as exc:
            self.log.emit(f"ERROR: {exc}")
            return False
        self.save_settings()

        def job(log):
            return run_tsd(**request.to_run_kwargs(), capture=capture, log=log)

        accepted = self._runner.submit("Generate TSD", job, self.apply_result)
        return accepted is not False

    def capture_now(self) -> bool:
        if not self._form.screenshots:
            self.log.emit("ERROR: centang 'Ambil screenshot' dulu.")
            return False
        try:
            options = self.capture_options(refresh=True)
        except ExtractionError as exc:
            self.log.emit(f"ERROR: {exc}")
            return False
        self.save_settings()

        def job(log):
            return capture_report(options, log=log)

        accepted = self._runner.submit(
            "Ambil screenshot report", job, self.apply_capture
        )
        return accepted is not False

    def clear_cache(self) -> bool:
        folder = self.assets_dir
        if not folder.exists():
            self.log.emit(f"Cache screenshot belum ada: {folder}")
            return False
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            self.log.emit(f"ERROR: cache tidak bisa dihapus: {exc}")
            return False
        self.log.emit(f"Cache screenshot dihapus: {folder}")
        self.refresh()
        return True

    # -- manual ------------------------------------------------------------
    def load_manual(self, quiet: bool = False) -> dict[str, Any] | None:
        """Muat sidecar; ``None`` bila file ada tapi tidak bisa dibaca."""
        path = self.manual_path
        if not path.exists():
            self._manual_data = {}
            if not quiet:
                self.log.emit(f"Konteks manual belum ada: {path}")
            self.refresh()
            return {}
        try:
            data = load_manual(path)
        except ExtractionError as exc:
            self.log.emit(f"ERROR: {exc}")
            return None
        self._manual_data = data
        if not quiet:
            self.log.emit(f"Konteks manual dimuat: {path}")
        self.refresh()
        return data

    def save_manual(self, data: Mapping[str, Any]) -> Path | None:
        path = self.manual_path
        merged = dict(data)
        try:
            write_manual(path, merged)
        except OSError as exc:
            self.log.emit(f"ERROR: konteks manual tidak bisa disimpan: {exc}")
            return None
        self._manual_data = merged
        self.log.emit(f"Konteks manual disimpan: {path}")
        self.refresh()
        return path

    # -- hasil -------------------------------------------------------------
    def apply_result(self, result: Mapping[str, Any]) -> None:
        self._manual_data = load_manual(self.manual_path) or self._manual_data
        self.refresh()
        self.log.emit(f"TSD             : {result['output']}")
        self.log.emit(
            f"Halaman/visual  : {result['pages']} / {result['visuals']}"
        )
        self.log.emit(f"TODO            : {result['todos']}")
        if result.get("screenshot_root"):
            self.log.emit(
                f"Screenshot      : {result['screenshot_pages']} page / "
                f"{result['screenshot_visuals']} visual "
                f"({result['screenshot_missing']} tanpa gambar)"
            )

    def apply_capture(self, result: Any) -> None:
        self.log.emit(f"Cache screenshot : {result.root}")
        self.log.emit(
            f"Tersimpan        : {result.page_count} page / "
            f"{result.visual_count} visual"
        )
        if result.missing:
            self.log.emit(
                f"Tanpa gambar     : {len(result.missing)} file "
                "(lihat capture.json)"
            )
        for warning in result.warnings:
            self.log.emit(f"WARNING: {warning}")
        self.refresh()
