"""View model sub-tab ekstraksi Local dan Power BI Service.

Semua keputusan yang sebelumnya tersebar di widget sekarang ada di sini:
cakupan mana yang dipilih, kapan tombol Jalankan aktif, catatan XMLA, status
output, pemilihan instance Power BI Desktop, dan penyusunan request untuk
:func:`core.jobs.run_metadata_job`.

Modul ini tidak boleh mengimpor ``QtWidgets``; view hanya membaca
:class:`MetadataState` dan memanggil method publik di sini.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Callable, Protocol

from PySide6.QtCore import QObject, Signal

from core.auth import EntraTokens, fabric_provider
from core.errors import ExtractionError
from core.fabric_api import ServiceReportRef, parse_report_url
from core.jobs import run_metadata_job
from core.lineage_service import WorkspaceOption
from core.lineage_store import DEFAULT_DB
from core.pbix import DEFAULT_PBIX, ROOT, PbixSourceInfo, detect_pbix_source
from core.report import MODEL_WORKBOOK_NAME, OUT_FILE
from core.requests import (
    SCOPE_BOTH,
    SCOPE_MODEL,
    SCOPE_REPORT,
    LocalMetadataRequest,
    ServiceMetadataRequest,
    validate_scope,
)
from core.xmla_client import list_instances, workspace_endpoint

from ..formatting import file_status
from ..settings import (
    SETTINGS_INSTANCE_KEY,
    SETTINGS_SCOPE_KEY,
    SETTINGS_SERVICE_REPORT_KEY,
    SETTINGS_SERVICE_URL_KEY,
    SETTINGS_SERVICE_WORKSPACE_KEY,
)
from ..settings_store import AppSettings
from .service_picker import (
    BUSY_MESSAGE,
    MISSING_CREDENTIALS,
    report_label,
    workspace_contents_job,
    workspace_label,
    workspace_picklist,
)


class JobSubmitter(Protocol):
    """Objek yang bisa menjalankan pekerjaan latar (``JobRunner`` atau adaptor)."""

    def submit(
        self,
        title: str,
        job: Callable[[Callable[[str], None]], Any],
        on_success: Callable[[Any], None] | None = None,
    ) -> Any:
        ...


def same_path(text: str, expected: Path) -> bool:
    return bool(text) and Path(text).expanduser().resolve() == expected.resolve()


# --------------------------------------------------------------------- state
@dataclass(frozen=True)
class MetadataState:
    """Keadaan satu sub-tab yang dirender view."""

    scope: str
    idle: bool
    can_run: bool
    model_inputs_active: bool
    source_active: bool
    report_status: str
    model_status: str
    report_exists: bool
    model_exists: bool
    folder_exists: bool
    out_folder: Path


@dataclass(frozen=True)
class LocalMetadataState(MetadataState):
    kind_text: str = ""
    dataset_text: str = ""
    instances: tuple[Any, ...] = ()
    instance_index: int = 0
    instance_placeholder: bool = False


@dataclass(frozen=True)
class ServiceMetadataState(MetadataState):
    workspace_id: str = ""
    report_id: str = ""
    credentials_missing: bool = False
    missing_credentials: tuple[str, ...] = ()
    report_note: str = ""
    report_note_visible: bool = False
    workspaces: tuple[str, ...] = ()
    workspace_index: int = -1
    datasets: tuple[str, ...] = ()
    dataset_index: int = -1
    reports: tuple[str, ...] = ()
    report_index: int = -1
    endpoint_text: str = ""
    loading_text: str = ""
    message: str = ""
    workspace_hint: str = ""
    workspace_active: bool = False
    settings_shortcut_visible: bool = False


# ---------------------------------------------------------------- base model
class MetadataViewModel(QObject):
    """Perilaku bersama: cakupan, folder output, status sibuk, dan submit."""

    state_changed = Signal(object)
    log = Signal(str)

    job_title = "Ekstraksi metadata"

    def __init__(
        self,
        settings: AppSettings,
        runner: JobSubmitter,
        *,
        scope_key: str,
        default_scope: str = SCOPE_BOTH,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._runner = runner
        self._scope_key = scope_key
        self._scope = self._initial_scope(default_scope)
        self._busy = False
        self._out_dir = ROOT
        self._out_dir_auto = False
        self._settings.changed.connect(self._on_settings_changed)

    # -- siklus ------------------------------------------------------------
    def start(self) -> None:
        """Kirim state awal setelah view selesai membangun widget."""
        self.refresh()

    def refresh(self) -> None:
        self.state_changed.emit(self.build_state())

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if busy == self._busy:
            return
        self._busy = busy
        self.refresh()

    # -- input -------------------------------------------------------------
    def _initial_scope(self, default_scope: str) -> str:
        saved = self._settings.value(self._scope_key, "", type=str)
        if not saved:
            saved = self._settings.value(SETTINGS_SCOPE_KEY, default_scope, type=str)
        try:
            return validate_scope(saved or default_scope)
        except ExtractionError:
            return default_scope

    def set_scope(self, scope: str) -> None:
        value = validate_scope(scope)
        if value == self._scope:
            return
        self._scope = value
        self._settings.set_value(self._scope_key, value)
        self.refresh()

    def set_out_dir(self, value: Path | str, *, automatic: bool = False) -> None:
        text = str(value or "").strip()
        path = Path(text).expanduser().resolve() if text else ROOT
        changed = path != self._out_dir
        self._out_dir = path
        if not automatic:
            self._out_dir_auto = False
        if changed:
            self.refresh()

    # -- turunan -----------------------------------------------------------
    @property
    def scope(self) -> str:
        return self._scope

    @property
    def out_dir(self) -> Path:
        return self._out_dir

    @property
    def wants_report(self) -> bool:
        return self._scope != SCOPE_MODEL

    @property
    def wants_model(self) -> bool:
        return self._scope != SCOPE_REPORT

    @property
    def report_out(self) -> Path:
        return self._out_dir / OUT_FILE.name

    @property
    def model_out(self) -> Path:
        return self._out_dir / MODEL_WORKBOOK_NAME

    # -- hook --------------------------------------------------------------
    def model_available(self) -> bool:
        """Apakah model bisa diekstrak dari sumber ini."""
        return True

    def source_ready(self) -> bool:
        return True

    def source_active(self, idle: bool) -> bool:
        """Apakah widget sumber boleh diubah saat idle."""
        return idle

    def prepare(
        self,
    ) -> tuple[LocalMetadataRequest | ServiceMetadataRequest, dict[str, Any]] | None:
        """Susun request dan argumen runtime; ``None`` bila input belum siap."""
        raise NotImplementedError

    # -- state -------------------------------------------------------------
    def build_state(self) -> MetadataState:
        idle = not self._busy
        return MetadataState(
            scope=self._scope,
            idle=idle,
            can_run=idle and self.source_ready(),
            model_inputs_active=idle and self.wants_model and self.model_available(),
            source_active=self.source_active(idle),
            report_status=file_status(self.report_out),
            model_status=file_status(self.model_out),
            report_exists=self.report_out.exists(),
            model_exists=self.model_out.exists(),
            folder_exists=self._out_dir.exists(),
            out_folder=self._out_dir,
        )

    # -- eksekusi ----------------------------------------------------------
    def submit(self) -> bool:
        if self._busy:
            self.log.emit("Pekerjaan lain masih berjalan; tunggu sampai selesai.")
            return False
        try:
            prepared = self.prepare()
        except ExtractionError as exc:
            self.log.emit(f"ERROR: {exc}")
            return False
        if prepared is None:
            return False
        request, runtime = prepared
        kwargs = dict(request.to_job_kwargs())
        kwargs.update(runtime)

        def job(log):
            return run_metadata_job(**kwargs, log=log)

        accepted = self._runner.submit(self.job_title, job, self.apply_result)
        if accepted is False:
            self.log.emit("Pekerjaan lain masih berjalan; tunggu sampai selesai.")
            return False
        return True

    def apply_result(self, result: Any) -> None:
        self.refresh()
        self.log.emit(f"Jenis report     : {result.source.label}")
        if result.model_error:
            if result.report is not None:
                self.log.emit(
                    "CATATAN: file model tidak dibuat; "
                    "report diekstrak tanpa validasi model."
                )
            else:
                self.log.emit("CATATAN: file model tidak dibuat.")
        if result.report_out is not None:
            self.log.emit(
                "Tips: sub-tab 'Generate TSD' dapat membuat dokumen TSD "
                "dari workbook ini."
            )

    # -- kredensial --------------------------------------------------------
    def _tokens(self) -> EntraTokens | None:
        principal = self._settings.principal()
        if not principal.is_complete:
            self.log.emit(
                "ERROR: kredensial service principal belum lengkap: "
                + ", ".join(principal.missing)
            )
            return None
        return EntraTokens(principal)

    def _on_settings_changed(self, group: str) -> None:
        if group == "auth":
            self.refresh()


def _base_fields(state: MetadataState) -> dict[str, Any]:
    """Field ``MetadataState`` saja, untuk membangun subclass state."""
    return {field.name: getattr(state, field.name) for field in fields(MetadataState)}


# ----------------------------------------------------------------- local view
class LocalMetadataViewModel(MetadataViewModel):
    """Sumber ``.pbix`` lokal: instance Desktop dan deteksi jenis file."""

    job_title = "Ekstraksi metadata (file lokal)"

    def __init__(
        self,
        settings: AppSettings,
        runner: JobSubmitter,
        *,
        scope_key: str,
        default_scope: str = SCOPE_BOTH,
        pbix: Path | str | None = None,
    ) -> None:
        self._pbix_text = str(pbix or DEFAULT_PBIX)
        self._info: PbixSourceInfo | None = None
        self._kind_text = ""
        self._dataset_text = ""
        self._instances: tuple[Any, ...] = ()
        self._instance_index = 0
        self._instance_placeholder = False
        super().__init__(
            settings, runner, scope_key=scope_key, default_scope=default_scope
        )
        self._out_dir_auto = True
        self._detect(emit=False)

    # -- sumber ------------------------------------------------------------
    @property
    def pbix_text(self) -> str:
        return self._pbix_text

    @property
    def source_info(self) -> PbixSourceInfo | None:
        return self._info

    def set_pbix(self, text: str) -> None:
        """Simpan path tanpa membaca arsip; view memicu ``detect_source``."""
        self._pbix_text = str(text or "").strip()

    def detect_source(self) -> None:
        self._detect(emit=True)

    def _detect(self, *, emit: bool) -> None:
        info: PbixSourceInfo | None = None
        kind = ""
        detail = ""
        text = self._pbix_text
        if not text:
            kind = "Pilih file .pbix sumber."
        else:
            path = Path(text).expanduser()
            if not path.exists():
                kind = f"File tidak ditemukan: {path}"
            else:
                path = path.resolve()
                try:
                    info = detect_pbix_source(path)
                except Exception as exc:  # noqa: BLE001 - ditampilkan di label
                    kind = f"Tidak bisa dibaca: {exc}"
                else:
                    kind = info.label
                    if not info.has_pbir:
                        kind += " - Report/definition tidak ditemukan (format legacy?)"
                    detail = self._detail_text(info)
                    if self._out_dir_auto:
                        self._out_dir = path.parent

        self._info = info
        self._kind_text = kind
        self._dataset_text = detail
        if emit:
            self.refresh()

    @staticmethod
    def _detail_text(info: PbixSourceInfo) -> str:
        if info.has_local_model:
            return (
                "Metadata model tersimpan di dalam .pbix. "
                "Ekstraksi model memakai XMLA, jadi Power BI Desktop harus terbuka."
            )
        if info.is_live_connection:
            dataset = f" Dataset: {info.dataset_id}." if info.dataset_id else ""
            return (
                f"Thin report ke dataset remote.{dataset} "
                "Metadata model tidak tersedia di file; hanya report yang diekstrak."
            )
        return (
            "Jenis sumber tidak dikenali. Report tetap bisa dicoba bila PBIR tersedia."
        )

    # -- instance ----------------------------------------------------------
    @property
    def selected_instance(self) -> Any | None:
        if self._instance_placeholder:
            if self._instance_index <= 0:
                return None
            index = self._instance_index - 1
        else:
            index = self._instance_index
        if 0 <= index < len(self._instances):
            return self._instances[index]
        return None

    def refresh_instances(self) -> None:
        if self._busy:
            return
        self._runner.submit(
            "Membaca instance Power BI Desktop",
            lambda log: list_instances(),
            self.apply_instances,
        )

    def apply_instances(self, instances: list[Any]) -> None:
        items = tuple(instances)
        remembered = self._settings.value(SETTINGS_INSTANCE_KEY, "", type=str)
        index = next(
            (i for i, item in enumerate(items) if item.catalog == remembered), None
        )
        if index is None:
            stem = Path(self._pbix_text).stem if self._pbix_text else ""
            matches = [
                i
                for i, item in enumerate(items)
                if stem and getattr(item, "file_name", "") == stem
            ]
            if len(matches) == 1:
                index = matches[0]

        placeholder = bool(items and index is None and len(items) > 1)
        self._instances = items
        self._instance_placeholder = placeholder
        if placeholder:
            self._instance_index = 0
        elif items:
            self._instance_index = index or 0
        else:
            self._instance_index = 0
        self._remember_instance()

        if not items:
            self.log.emit(
                "Tidak ada instance Power BI Desktop yang terbuka. "
                "Buka file .pbix/.pbip lalu muat ulang."
            )
        elif len(items) > 1:
            self.log.emit(
                "Ada lebih dari satu instance Power BI Desktop. "
                "Pilih instance yang sesuai sebelum menjalankan."
            )
        self.refresh()

    def select_instance(self, combo_index: int) -> None:
        index = int(combo_index)
        if index == self._instance_index:
            return
        self._instance_index = index
        self._remember_instance()
        self.refresh()

    def _remember_instance(self) -> None:
        instance = self.selected_instance
        if instance is None:
            return
        self._settings.set_value(SETTINGS_INSTANCE_KEY, instance.catalog)

    def model_ready(self) -> bool:
        """Model bisa diekstrak: Desktop tidak terbuka boleh (report saja)."""
        if not self._instances:
            return True
        return self.selected_instance is not None

    def model_target(self) -> tuple[str | None, str | None, int | None] | None:
        """``(endpoint, catalog, port)``; ``None`` bila instance belum dipilih."""
        if not self._instances:
            return None, None, None
        instance = self.selected_instance
        if instance is None:
            return None
        return None, instance.catalog, instance.port

    # -- hook --------------------------------------------------------------
    @property
    def will_extract_model(self) -> bool:
        return self.wants_model and self.model_available()

    def model_available(self) -> bool:
        return self._info is not None and self._info.has_local_model

    def source_ready(self) -> bool:
        info = self._info
        has_pbir = info is not None and info.has_pbir
        if self._scope != SCOPE_MODEL and not has_pbir:
            return False
        if self._scope == SCOPE_MODEL:
            if info is None or not info.has_local_model:
                return False
            return self.model_ready()
        if self.will_extract_model:
            return self.model_ready()
        return True

    def source_active(self, idle: bool) -> bool:
        # Path .pbix tetap bisa diubah walau pekerjaan lain berjalan.
        return True

    def build_state(self) -> LocalMetadataState:
        base = super().build_state()
        return LocalMetadataState(
            **_base_fields(base),
            kind_text=self._kind_text,
            dataset_text=self._dataset_text,
            instances=self._instances,
            instance_index=self._instance_index,
            instance_placeholder=self._instance_placeholder,
        )

    # -- eksekusi ----------------------------------------------------------
    def prepare(self):
        info = self._info
        if info is None:
            self.log.emit("ERROR: pilih file .pbix yang valid lebih dulu.")
            return None
        if self.wants_report and not info.has_pbir:
            self.log.emit("ERROR: Report/definition tidak ditemukan di .pbix ini.")
            return None
        if self._scope == SCOPE_MODEL and not info.has_local_model:
            self.log.emit("ERROR: .pbix ini tidak menyimpan model lokal.")
            return None

        target = self.model_target() if self.will_extract_model else (None, None, None)
        if target is None:
            self.log.emit("ERROR: pilih instance Power BI Desktop yang sesuai.")
            return None
        _endpoint, catalog, port = target
        if self.will_extract_model and not info.has_pbir:
            self.log.emit(
                "Catatan: pemakaian report dilewati "
                "(Report/definition tidak ditemukan)."
            )

        pbix = (
            None
            if same_path(self._pbix_text, DEFAULT_PBIX)
            else Path(self._pbix_text).expanduser()
        )
        request = LocalMetadataRequest(
            out_dir=self.out_dir,
            scope=self._scope,
            pbix=pbix,
            port=port,
            catalog=catalog,
            include_usage=info.has_pbir,
        )
        return request, {}


# --------------------------------------------------------------- service view
class ServiceMetadataViewModel(MetadataViewModel):
    """Sumber Power BI Service: Fabric API untuk report, XMLA untuk model."""

    job_title = "Ekstraksi metadata (Power BI Service)"

    def __init__(
        self,
        settings: AppSettings,
        runner: JobSubmitter,
        *,
        scope_key: str,
        default_scope: str = SCOPE_BOTH,
    ) -> None:
        self._workspace_id = ""
        self._report_id = ""
        self._endpoint = ""
        self._catalog = ""
        self._workspace_options: tuple[WorkspaceOption, ...] = ()
        self._duplicate_names: set[str] = set()
        self._workspace_index = -1
        self._dataset_items: tuple[dict[str, Any], ...] = ()
        self._report_items: tuple[dict[str, Any], ...] = ()
        self._dataset_index = -1
        self._report_index = -1
        self._loading = ""
        self._message = ""
        self._workspace_hint = ""
        super().__init__(
            settings, runner, scope_key=scope_key, default_scope=default_scope
        )
        self._workspace_id = str(
            self._settings.value(SETTINGS_SERVICE_WORKSPACE_KEY, "", type=str) or ""
        )
        self._report_id = str(
            self._settings.value(SETTINGS_SERVICE_REPORT_KEY, "", type=str) or ""
        )
        self._restore_legacy_url()

    # -- siklus ------------------------------------------------------------
    def start(self) -> None:
        """Baca katalog workspace; isi dataset/report dimuat saat tab ditampilkan."""
        self._load_workspace_options()
        self._restore_workspace_selection()
        self.refresh()

    # -- input -------------------------------------------------------------
    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def report_id(self) -> str:
        return self._report_id

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def catalog(self) -> str:
        return self._catalog

    def set_scope(self, scope: str) -> None:
        before = self._scope
        super().set_scope(scope)
        if self._scope != before:
            self.ensure_contents()

    def select_workspace(self, index: int) -> None:
        """Pilih workspace dari combo; endpoint XMLA diturunkan dari namanya."""
        index = int(index)
        if index < 0 or index >= len(self._workspace_options):
            return
        if index == self._workspace_index:
            return
        previous = self._snapshot()
        self._apply_workspace(index)
        self.refresh()
        if not self._load_contents():
            self._restore(previous)
            self.refresh()

    def select_catalog(self, index: int) -> None:
        index = int(index)
        if index < 0 or index >= len(self._dataset_items):
            return
        if index == self._dataset_index:
            return
        self._dataset_index = index
        self._catalog = str(self._dataset_items[index].get("name") or "")
        self._message = ""
        self.refresh()

    def select_report(self, index: int) -> None:
        index = int(index)
        if index < 0 or index >= len(self._report_items):
            return
        if index == self._report_index:
            return
        self._apply_report(index)
        self.refresh()

    # -- daftar workspace --------------------------------------------------
    def reload_workspaces(self) -> None:
        """Baca ulang tabel katalog workspace dari SQLite lalu muat isinya."""
        self._load_workspace_options()
        self._restore_workspace_selection()
        self.refresh()
        self.ensure_contents()

    def reload_contents(self) -> None:
        """Ambil ulang dataset/report workspace dari REST API."""
        if not self._workspace_id:
            self._message = "Pilih workspace lebih dulu."
            self.refresh()
            return
        self._reset_contents(keep_report_id=True)
        self._load_contents()
        self.refresh()

    def ensure_contents(self) -> None:
        """Muat dataset/report bila daftar untuk cakupan aktif masih kosong."""
        if self._loading or self._busy or self._workspace_index < 0:
            return
        needs_datasets = self.wants_model and not self._dataset_items
        needs_reports = self.wants_report and not self._report_items
        if not (needs_datasets or needs_reports):
            return
        self._load_contents()
        self.refresh()

    def _on_settings_changed(self, group: str) -> None:
        if group == "paths":
            self.reload_workspaces()
            return
        super()._on_settings_changed(group)

    def apply_workspace_contents(self, result: Any) -> None:
        """Callback job pembacaan dataset/report (dijalankan JobRunner)."""
        self._loading = ""
        if not isinstance(result, dict):
            self.refresh()
            return
        if str(result.get("workspace_id") or "") != self._workspace_id:
            # Pemilihan berubah sebelum hasil datang; buang hasil lama.
            self.refresh()
            return
        self._dataset_items = tuple(
            item for item in result.get("datasets") or () if isinstance(item, dict)
        )
        self._report_items = tuple(
            item for item in result.get("reports") or () if isinstance(item, dict)
        )
        self._dataset_index = -1
        self._report_index = -1
        self._catalog = ""
        if self._report_id:
            index = self._find_report_index(self._report_id)
            if index >= 0:
                self._apply_report(index, persist=False)
            else:
                self._message = "Report terakhir tidak ditemukan di workspace ini."
        self.refresh()

    # -- internal ----------------------------------------------------------
    def _load_workspace_options(self) -> None:
        database = self._settings.lineage_db() or str(DEFAULT_DB)
        options, duplicates, hint = workspace_picklist(database)
        self._workspace_options = options
        self._duplicate_names = duplicates
        self._workspace_hint = hint

    def _restore_legacy_url(self) -> None:
        """Kunci lama ``extraction/service_url`` dipakai sekali bila kunci baru kosong.

        Field URL sudah dihapus dari UI; nilai lama tetap dibaca agar pengguna
        yang pernah memakai versi sebelumnya tidak kehilangan pilihan terakhir.
        """
        if self._workspace_id and self._report_id:
            return
        text = str(
            self._settings.value(SETTINGS_SERVICE_URL_KEY, "", type=str) or ""
        )
        try:
            ref = parse_report_url(text)
        except ExtractionError:
            return
        self._workspace_id = self._workspace_id or ref.workspace_id
        self._report_id = self._report_id or ref.report_id

    def _restore_workspace_selection(self) -> None:
        index = self._find_workspace_index(self._workspace_id)
        if index < 0:
            self._workspace_index = -1
            self._endpoint = ""
            if self._workspace_id and self._workspace_options:
                self._workspace_hint = (
                    "Workspace terakhir tidak ada di katalog. Jalankan "
                    "Sinkronisasi workspace di tab Pengaturan."
                )
            return
        self._workspace_index = index
        self._endpoint = self._endpoint_for(self._workspace_options[index])

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

    def _endpoint_for(self, option: WorkspaceOption) -> str:
        return workspace_endpoint(
            "myorg",
            option.name,
            option.workspace_id,
            disambiguate=option.name in self._duplicate_names,
        )

    def _apply_workspace(self, index: int) -> None:
        option = self._workspace_options[index]
        self._workspace_index = index
        self._workspace_id = option.workspace_id
        self._endpoint = self._endpoint_for(option)
        self._reset_contents()
        self._workspace_hint = ""
        self._message = ""
        self._settings.set_value(SETTINGS_SERVICE_WORKSPACE_KEY, self._workspace_id)
        self._settings.set_value(SETTINGS_SERVICE_REPORT_KEY, "")

    def _apply_report(self, index: int, *, persist: bool = True) -> None:
        item = self._report_items[index]
        self._report_index = index
        self._report_id = str(item.get("id") or "")
        self._dataset_index = -1
        self._catalog = ""
        notes: list[str] = []
        dataset_id = str(item.get("datasetId") or "")
        if dataset_id:
            match = next(
                (
                    position
                    for position, dataset in enumerate(self._dataset_items)
                    if str(dataset.get("id") or "") == dataset_id
                ),
                -1,
            )
            if match >= 0:
                self._dataset_index = match
                self._catalog = str(self._dataset_items[match].get("name") or "")
                notes.append(f"Catalog diisi dari dataset report: {self._catalog}.")
            elif self.wants_model:
                notes.append(
                    "Dataset report tidak ada di workspace ini (kemungkinan "
                    "dataset bersama di workspace lain). Pilih workspace dataset "
                    "tersebut atau catalog manual."
                )
        if str(item.get("reportType") or "") == "PaginatedReport":
            notes.append(
                "Report paginated (RDL) tidak didukung; pilih report Power BI."
            )
        self._message = " ".join(notes)
        if persist:
            self._settings.set_value(SETTINGS_SERVICE_REPORT_KEY, self._report_id)

    def _reset_contents(self, *, keep_report_id: bool = False) -> None:
        self._dataset_items = ()
        self._report_items = ()
        self._dataset_index = -1
        self._report_index = -1
        self._catalog = ""
        if not keep_report_id:
            self._report_id = ""

    def _load_contents(self) -> bool:
        """Submit job pembacaan dataset/report; ``False`` bila job ditolak."""
        workspace_id = self._workspace_id
        if not workspace_id:
            return True
        wants_model, wants_report = self.wants_model, self.wants_report
        if not (wants_model or wants_report):
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

        self._loading = "Memuat dataset dan report workspace..."

        job = workspace_contents_job(
            principal, workspace_id, datasets=wants_model, reports=wants_report
        )
        accepted = self._runner.submit(
            "Membaca dataset & report workspace", job, self.apply_workspace_contents
        )
        if accepted is False:
            self._loading = ""
            self._message = "Pekerjaan lain masih berjalan; coba lagi setelah selesai."
            return False
        self.refresh()
        return True

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self._workspace_index,
            self._workspace_id,
            self._endpoint,
            self._dataset_items,
            self._dataset_index,
            self._catalog,
            self._report_items,
            self._report_index,
            self._report_id,
            self._workspace_hint,
        )

    def _restore(self, snapshot: tuple[Any, ...]) -> None:
        (
            self._workspace_index,
            self._workspace_id,
            self._endpoint,
            self._dataset_items,
            self._dataset_index,
            self._catalog,
            self._report_items,
            self._report_index,
            self._report_id,
            self._workspace_hint,
        ) = snapshot
        self._loading = ""
        self._settings.set_value(SETTINGS_SERVICE_WORKSPACE_KEY, self._workspace_id)
        self._settings.set_value(SETTINGS_SERVICE_REPORT_KEY, self._report_id)

    # -- turunan -----------------------------------------------------------
    def service_ref(self) -> ServiceReportRef | None:
        try:
            return ServiceReportRef.from_ids(self._workspace_id, self._report_id)
        except ExtractionError:
            return None

    def service_ready(self) -> bool:
        return (
            self.service_ref() is not None
            and self._settings.principal().is_complete
        )

    def model_ready(self) -> bool:
        return bool(self._endpoint and self._catalog)

    def _selected_report_type(self) -> str:
        if 0 <= self._report_index < len(self._report_items):
            return str(self._report_items[self._report_index].get("reportType") or "")
        return ""

    def source_ready(self) -> bool:
        if self._scope != SCOPE_MODEL and not self.service_ready():
            return False
        if self._scope != SCOPE_REPORT and not self.model_ready():
            return False
        return True

    def source_active(self, idle: bool) -> bool:
        return idle and self.wants_report

    def build_state(self) -> ServiceMetadataState:
        base = super().build_state()
        principal = self._settings.principal()
        note_visible = self.wants_model and not self.wants_report
        options = self._workspace_options
        return ServiceMetadataState(
            **_base_fields(base),
            workspace_id=self._workspace_id,
            report_id=self._report_id,
            credentials_missing=not principal.is_complete,
            missing_credentials=tuple(principal.missing),
            report_note=(
                "Cakupan semantic model saja: pilihan sumber report diabaikan. "
                "Model diekstrak lewat endpoint XMLA di grup Semantic model."
                if note_visible
                else ""
            ),
            report_note_visible=note_visible,
            workspaces=tuple(workspace_label(item) for item in options),
            workspace_index=(
                self._workspace_index if 0 <= self._workspace_index < len(options) else -1
            ),
            datasets=tuple(
                str(item.get("name") or item.get("id") or "")
                for item in self._dataset_items
            ),
            dataset_index=self._dataset_index,
            reports=tuple(report_label(item) for item in self._report_items),
            report_index=self._report_index,
            endpoint_text=self._endpoint,
            loading_text=self._loading,
            message=self._message,
            workspace_hint=self._workspace_hint,
            workspace_active=base.idle,
            settings_shortcut_visible=not options,
        )

    # -- eksekusi ----------------------------------------------------------
    def prepare(self):
        tokens: EntraTokens | None = None
        token_provider = None
        if self.wants_report:
            tokens = self._tokens()
            if tokens is None:
                return None
            if self.service_ref() is None:
                self.log.emit(
                    "ERROR: pilih workspace dan report dari daftar."
                )
                return None
            if self._selected_report_type() == "PaginatedReport":
                self.log.emit(
                    "ERROR: report paginated (RDL) tidak didukung; pilih report "
                    "Power BI biasa."
                )
                return None
            token_provider = fabric_provider(tokens)

        if self.wants_model:
            if not self._endpoint:
                self.log.emit(
                    "ERROR: pilih workspace lebih dulu; endpoint XMLA diturunkan "
                    "dari nama workspace."
                )
                return None
            if not self._catalog:
                self.log.emit(
                    "ERROR: pilih catalog (dataset) semantic model di workspace ini."
                )
                return None
            if tokens is None and self._is_powerbi_endpoint():
                tokens = self._tokens()
                if tokens is None:
                    return None

        request = ServiceMetadataRequest(
            out_dir=self.out_dir,
            workspace_id=self._workspace_id,
            report_id=self._report_id,
            endpoint=self._endpoint,
            catalog=self._catalog,
            scope=self._scope,
            include_usage=self.wants_model and self.wants_report,
        )
        return request, {"tokens": tokens, "token_provider": token_provider}

    def _is_powerbi_endpoint(self) -> bool:
        endpoint = self._endpoint.lower()
        return endpoint.startswith(("powerbi://", "asazure://"))
