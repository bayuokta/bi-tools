"""View model tab Analisa Semantic Model.

Satu tempat memilih workspace/semantic model, menjalankan analisa ukuran kolom +
pemakaian report lewat ``JobRunner``, dan mengekspor hasil. Tanpa QtWidgets:
view hanya membangun widget dan merender :class:`AnalysisState`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from core.errors import ExtractionError
from core.lineage_store import DEFAULT_DB
from core.paths import OUTPUTS_DIR
from core.requests import AnalysisRequest
from core.usage_service import (
    AnalysisResult,
    analyze_dataset,
    column_rows,
    format_bytes,
    load_snapshot,
    measure_rows,
    output_file_name,
    resolve_names,
    write_workbook,
)

from ..formatting import ERROR_COLOR, OK_COLOR, credential_status
from ..settings import (
    SETTINGS_ANALYSIS_DATASET_KEY,
    SETTINGS_ANALYSIS_OBJECT_FILTER_KEY,
    SETTINGS_ANALYSIS_OTHER_WS_KEY,
    SETTINGS_ANALYSIS_PERSONAL_KEY,
    SETTINGS_ANALYSIS_SORT_COLUMN_KEY,
    SETTINGS_ANALYSIS_SORT_DESC_KEY,
    SETTINGS_ANALYSIS_UNUSED_ONLY_KEY,
    SETTINGS_ANALYSIS_WORKSPACE_KEY,
)
from ..settings_store import AppSettings
from .metadata import JobSubmitter
from .service_picker import (
    MISSING_CREDENTIALS,
    workspace_contents_job,
    workspace_picklist,
)

OBJECT_FILTERS = ("all", "columns", "measures")
SORT_KEYS = (
    "name",
    "type",
    "table",
    "source",
    "data_type",
    "size",
    "status",
    "uses",
    "format_string",
    "has_error",
    "display_folder",
)
SORT_DESC_DEFAULT = {"size", "uses", "has_error"}
STATUS_SORT_ORDER = {
    "Tidak dipakai": 0,
    "Perlu dicek": 1,
    "Dipakai": 2,
    "Wajib dipertahankan": 3,
}


@dataclass(frozen=True)
class AnalysisState:
    """Nilai dan status yang dirender tab Analisa Semantic Model."""

    idle: bool
    credential_text: str
    credential_color: str
    workspaces: tuple[tuple[str, str], ...]
    workspace_id: str
    datasets: tuple[tuple[str, str], ...]
    dataset_id: str
    include_other_workspaces: bool
    include_personal: bool
    object_filter: str
    sort_column: str
    sort_desc: bool
    unused_only: bool
    status: str
    status_color: str
    progress: str
    summary: str
    coverage: str
    has_result: bool
    can_run: bool
    running: bool = False
    catalog_hint: str = ""


class AnalysisViewModel(QObject):
    """Pemilik pilihan workspace/dataset dan aksi analisa."""

    state_changed = Signal(object)
    log = Signal(str)
    progress_changed = Signal(int, int, str)

    def __init__(self, settings: AppSettings, runner: JobSubmitter) -> None:
        super().__init__()
        self._settings = settings
        self._runner = runner
        self._busy = False
        self._running = False
        self._stop = threading.Event()
        self._status = ""
        self._status_color = ""
        self._progress = ""
        self._workspaces: tuple[tuple[str, str], ...] = ()
        self._datasets: tuple[tuple[str, str], ...] = ()
        self._dataset_entries: dict[str, dict[str, Any]] = {}
        self._workspace_id = str(
            settings.value(SETTINGS_ANALYSIS_WORKSPACE_KEY, "") or ""
        )
        self._dataset_id = str(
            settings.value(SETTINGS_ANALYSIS_DATASET_KEY, "") or ""
        )
        self._include_other = bool(
            settings.value(SETTINGS_ANALYSIS_OTHER_WS_KEY, True, type=bool)
        )
        self._include_personal = bool(
            settings.value(SETTINGS_ANALYSIS_PERSONAL_KEY, False, type=bool)
        )
        self._object_filter = self._normalize_object_filter(
            settings.value(SETTINGS_ANALYSIS_OBJECT_FILTER_KEY, "all")
        )
        self._sort_column = self._normalize_sort_column(
            settings.value(SETTINGS_ANALYSIS_SORT_COLUMN_KEY, "default")
        )
        self._sort_desc = bool(
            settings.value(SETTINGS_ANALYSIS_SORT_DESC_KEY, False, type=bool)
        )
        self._unused_only = bool(
            settings.value(SETTINGS_ANALYSIS_UNUSED_ONLY_KEY, False, type=bool)
        )
        self._hint = ""
        self._result: AnalysisResult | None = None
        self._pending_workspace = ""
        self._settings.changed.connect(self._on_settings_changed)
        self.progress_changed.connect(self._on_progress)

    # -- siklus ------------------------------------------------------------
    def start(self) -> None:
        """Muat katalog + snapshot terakhir; dataset dimuat saat tab ditampilkan."""
        self.reload_workspaces()
        if self._dataset_id:
            self._restore_snapshot(self._dataset_id)

    def refresh(self) -> None:
        self.state_changed.emit(self.build_state())

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        self._busy = busy
        if not busy and self._running:
            self._running = False
            self._status = "Analisa berhenti tanpa hasil; lihat log."
            self._status_color = ERROR_COLOR
            self._progress = ""
        if not busy and self._pending_workspace:
            workspace_id = self._pending_workspace
            self._pending_workspace = ""
            if workspace_id == self._workspace_id and not self._datasets:
                self.load_datasets()
        self.refresh()

    def _on_settings_changed(self, group: str) -> None:
        if group == "paths":
            self.reload_workspaces()
        self.refresh()

    # -- katalog -----------------------------------------------------------
    def database(self) -> Path:
        return Path(self._settings.lineage_db() or DEFAULT_DB).expanduser()

    def reload_workspaces(self) -> None:
        options, _duplicates, hint = workspace_picklist(str(self.database()))
        self._workspaces = tuple(
            (f"{option.name} ({option.workspace_id[:8]})", option.workspace_id)
            for option in options
        )
        self._hint = hint
        if self._workspace_id and not any(
            workspace_id == self._workspace_id
            for _label, workspace_id in self._workspaces
        ):
            self._workspace_id = ""
        self.refresh()

    def set_workspace(self, workspace_id: str) -> None:
        value = str(workspace_id or "").strip()
        if value == self._workspace_id:
            if value and not self._datasets:
                self.load_datasets()
            return
        self._workspace_id = value
        self._dataset_id = ""
        self._datasets = ()
        self._dataset_entries = {}
        self._result = None
        self._settings.set_value(SETTINGS_ANALYSIS_WORKSPACE_KEY, value)
        if value:
            self.load_datasets(summary="Memuat daftar semantic model...")
        self.refresh()

    def load_datasets(self, *, summary: str = "") -> None:
        workspace_id = self._workspace_id
        if not workspace_id:
            return
        principal = self._settings.principal()
        if not principal.is_complete:
            self._datasets = ()
            self._status = MISSING_CREDENTIALS
            self._status_color = ERROR_COLOR
            self.refresh()
            return
        if summary:
            self._status = summary
            self._status_color = ""

        job = workspace_contents_job(
            principal, workspace_id, datasets=True, reports=False
        )

        def on_success(payload: Any) -> None:
            self.apply_contents(workspace_id, payload)

        self.refresh()
        if self._runner.submit("Membaca semantic model workspace", job, on_success) is False:
            # JobRunner sibuk (mis. auto-refresh instance Desktop saat aplikasi
            # dibuka). Coba lagi sekali saat pekerjaan itu selesai.
            self._pending_workspace = workspace_id
            self._status = (
                "Pekerjaan lain masih berjalan; daftar semantic model dimuat "
                "otomatis setelah selesai."
            )
            self._status_color = ""
            self.refresh()

    def apply_contents(self, workspace_id: str, payload: Any) -> None:
        if workspace_id != self._workspace_id:
            return
        rows = list((payload or {}).get("datasets") or [])
        entries: dict[str, dict[str, Any]] = {}
        items: list[tuple[str, str]] = []
        for row in rows:
            dataset_id = str(row.get("id") or "")
            if not dataset_id:
                continue
            name = str(row.get("name") or dataset_id)
            entries[dataset_id] = row
            items.append((f"{name} ({dataset_id[:8]})", dataset_id))
        items.sort(key=lambda item: item[0].casefold())
        self._dataset_entries = entries
        self._datasets = tuple(items)
        if self._dataset_id and self._dataset_id not in entries:
            self._dataset_id = ""
            self._settings.set_value(SETTINGS_ANALYSIS_DATASET_KEY, "")
        restored = False
        if self._dataset_id and self._result is None:
            restored = self._restore_snapshot(self._dataset_id)
        if not restored:
            self._status = f"{len(items)} semantic model di workspace ini."
            self._status_color = ""
        self.refresh()

    def set_dataset(self, dataset_id: str) -> None:
        value = str(dataset_id or "").strip()
        if value == self._dataset_id:
            return
        self._dataset_id = value
        self._settings.set_value(SETTINGS_ANALYSIS_DATASET_KEY, value)
        if self._result is not None and self._result.dataset_id != value:
            self._result = None
        if value and self._result is None:
            self._restore_snapshot(value)
        self.refresh()

    def _restore_snapshot(self, dataset_id: str) -> bool:
        """Tampilkan hasil analisa terakhir dari SQLite tanpa jaringan."""
        try:
            snapshot = load_snapshot(self.database(), dataset_id)
        except Exception as exc:  # noqa: BLE001 - snapshot rusak tidak memblokir UI
            self.log.emit(f"Snapshot analisa tidak bisa dibaca: {exc}")
            return False
        if snapshot is None:
            return False
        self._result = snapshot
        self._status = (
            f"Hasil tersimpan {snapshot.analyzed_at} dimuat. "
            "Klik Analisa untuk menyegarkan."
        )
        self._status_color = ""
        return True

    def set_include_other(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self._include_other:
            return
        self._include_other = enabled
        self._settings.set_value(SETTINGS_ANALYSIS_OTHER_WS_KEY, enabled)
        self.refresh()

    @staticmethod
    def _normalize_sort_column(value: Any) -> str:
        text = str(value or "").strip().lower()
        if text in SORT_KEYS:
            return text
        return "default"

    def set_sort(self, column: str) -> None:
        normalized = self._normalize_sort_column(column)
        if normalized == "default":
            return
        if normalized == self._sort_column:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_column = normalized
            self._sort_desc = normalized in SORT_DESC_DEFAULT
        self._settings.set_value(
            SETTINGS_ANALYSIS_SORT_COLUMN_KEY, self._sort_column
        )
        self._settings.set_value(
            SETTINGS_ANALYSIS_SORT_DESC_KEY, self._sort_desc
        )
        self.refresh()

    def reset_sort(self) -> None:
        if self._sort_column == "default" and not self._sort_desc:
            return
        self._sort_column = "default"
        self._sort_desc = False
        self._settings.set_value(SETTINGS_ANALYSIS_SORT_COLUMN_KEY, "default")
        self._settings.set_value(SETTINGS_ANALYSIS_SORT_DESC_KEY, False)
        self.refresh()

    def _sort_rows(
        self, rows: list[Any], column: str, descending: bool
    ) -> list[Any]:
        if column == "default" or not rows:
            return rows

        def value(row: dict[str, Any]) -> Any:
            if column == "size":
                return int(row.get("size_bytes") or 0)
            if column == "uses":
                return int(row.get("uses") or 0)
            if column == "status":
                return STATUS_SORT_ORDER.get(str(row.get("status") or ""), 99)
            if column == "has_error":
                return 1 if row.get("has_error") else 0
            if column == "source":
                return "model"
            return str(row.get(column) or "").casefold()

        return sorted(rows, key=value, reverse=descending)

    @staticmethod
    def _normalize_object_filter(value: Any) -> str:
        text = str(value or "").strip().lower()
        return text if text in OBJECT_FILTERS else "all"

    def set_object_filter(self, value: str) -> None:
        normalized = self._normalize_object_filter(value)
        if normalized == self._object_filter:
            return
        self._object_filter = normalized
        self._settings.set_value(
            SETTINGS_ANALYSIS_OBJECT_FILTER_KEY, normalized
        )
        self.refresh()

    def set_include_personal(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self._include_personal:
            return
        self._include_personal = enabled
        self._settings.set_value(SETTINGS_ANALYSIS_PERSONAL_KEY, enabled)
        self.refresh()

    def set_unused_only(self, value: bool) -> None:
        enabled = bool(value)
        if enabled == self._unused_only:
            return
        self._unused_only = enabled
        self._settings.set_value(SETTINGS_ANALYSIS_UNUSED_ONLY_KEY, enabled)
        self.refresh()

    # -- analisa -----------------------------------------------------------
    def request(self) -> AnalysisRequest:
        if not self._workspace_id or not self._dataset_id:
            raise ExtractionError("Pilih workspace dan semantic model dulu.")
        workspace_name, dataset_name = resolve_names(
            self.database(), self._workspace_id, self._dataset_id
        )
        return AnalysisRequest(
            workspace_id=self._workspace_id,
            dataset_id=self._dataset_id,
            workspace_name=workspace_name,
            dataset_name=dataset_name,
            database=self.database(),
            include_other_workspaces=self._include_other,
            include_personal=self._include_personal,
        )

    def analyze(self) -> bool:
        principal = self._settings.principal()
        if not principal.is_complete:
            self._status = MISSING_CREDENTIALS
            self._status_color = ERROR_COLOR
            self.refresh()
            return False
        try:
            request = self.request()
        except ExtractionError as exc:
            self._status = str(exc)
            self._status_color = ERROR_COLOR
            self.refresh()
            return False

        self._stop.clear()
        self._running = True
        self._status = "Menganalisa ukuran dan pemakaian kolom..."
        self._status_color = ""
        self._progress = "Menyiapkan koneksi XMLA..."
        self.refresh()

        def job(log):
            return analyze_dataset(
                **request.to_run_kwargs(),
                principal=principal,
                log=log,
                progress=self._emit_progress,
                should_stop=self._stop.is_set,
            )

        if self._runner.submit("Analisa Semantic Model", job, self.apply_result) is False:
            self._running = False
            self._status = "Pekerjaan lain masih berjalan; coba lagi setelah selesai."
            self._status_color = ERROR_COLOR
            self._progress = ""
            self.refresh()
            return False
        return True

    def stop(self) -> None:
        if not self._running:
            return
        self._stop.set()
        self._status = "Menghentikan setelah report yang sedang dipindai..."
        self.refresh()

    def _emit_progress(self, index: int, total: int, name: str) -> None:
        self.progress_changed.emit(index, total, name)

    def _on_progress(self, index: int, total: int, name: str) -> None:
        self._progress = f"Report {index}/{total}: {name}"
        self.refresh()

    def apply_result(self, result: Any) -> None:
        self._running = False
        self._progress = ""
        if not isinstance(result, AnalysisResult):
            self._status = "Analisa selesai tanpa hasil yang dikenali."
            self._status_color = ERROR_COLOR
            self.refresh()
            return
        self._result = result
        self._dataset_id = result.dataset_id
        self._settings.set_value(SETTINGS_ANALYSIS_DATASET_KEY, result.dataset_id)
        self._status = f"Analisa selesai: {result.coverage}."
        self._status_color = OK_COLOR if result.coverage_complete else ERROR_COLOR
        self.refresh()
        self.log.emit(
            f"Analisa {result.dataset_name}: {len(result.columns)} kolom, "
            f"{len(result.unused)} tidak dipakai "
            f"({format_bytes(result.unused_bytes)})."
        )

    # -- hasil -------------------------------------------------------------
    @property
    def result(self) -> AnalysisResult | None:
        return self._result

    def visible_columns(self) -> list[Any]:
        if self._result is None:
            return []
        rows = column_rows(self._result)
        if self._unused_only:
            rows = [row for row in rows if row["status"] == "Tidak dipakai"]
        return rows

    def visible_objects(self) -> list[Any]:
        """Baris kolom + measure sesuai filter ``object_filter``."""
        if self._result is None:
            return []
        rows: list[Any] = []
        if self._object_filter in {"all", "columns"}:
            rows.extend(column_rows(self._result))
        if self._object_filter in {"all", "measures"}:
            rows.extend(measure_rows(self._result))
        if self._unused_only:
            rows = [row for row in rows if row["status"] == "Tidak dipakai"]
        return self._sort_rows(rows, self._sort_column, self._sort_desc)

    def default_output_path(self) -> Path:
        if self._result is not None:
            return OUTPUTS_DIR / output_file_name(
                self._result.dataset_name, self._result.dataset_id
            )
        return OUTPUTS_DIR / "Analisa_Semantic_Model.xlsx"

    def export(self, target: Path | str) -> Path:
        if self._result is None:
            raise ExtractionError("Belum ada hasil analisa untuk diekspor.")
        return write_workbook(self._result, target)

    # -- state -------------------------------------------------------------
    def build_state(self) -> AnalysisState:
        text, color = credential_status(self._settings.principal())
        summary = ""
        coverage = ""
        if self._result is not None:
            summary = (
                f"{format_bytes(self._result.dataset_bytes)} · "
                f"{len(self._result.columns)} kolom · "
                f"{len(self._result.measures)} measure · "
                f"{len(self._result.unused)} tidak dipakai "
                f"({format_bytes(self._result.unused_bytes)}) · "
                f"{len(self._result.unused_measures)} measure tidak dipakai · "
                f"{self._result.report_total} report"
            )
            coverage = self._result.coverage
        can_run = (
            not self._busy
            and not self._running
            and self._settings.principal().is_complete
            and bool(self._workspace_id)
            and self._dataset_id in self._dataset_entries
        )
        return AnalysisState(
            idle=not self._busy,
            credential_text=text,
            credential_color=color,
            workspaces=self._workspaces,
            workspace_id=self._workspace_id,
            datasets=self._datasets,
            dataset_id=self._dataset_id,
            include_other_workspaces=self._include_other,
            include_personal=self._include_personal,
            object_filter=self._object_filter,
            sort_column=self._sort_column,
            sort_desc=self._sort_desc,
            unused_only=self._unused_only,
            status=self._status,
            status_color=self._status_color,
            progress=self._progress,
            summary=summary,
            coverage=coverage,
            has_result=self._result is not None,
            can_run=can_run,
            running=self._running,
            catalog_hint=self._hint,
        )
