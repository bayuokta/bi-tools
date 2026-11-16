"""Tab GUI generate dokumen TSD dari workbook metadata (view pasif)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.pbi_capture.assets import SCOPE_LABELS
from core.report import MODEL_WORKBOOK_NAME, OUT_FILE
from core.tsd import SCREENSHOT_ASSET_DIR

from .forms import section, text_value
from .job_runner import WindowSubmitter
from .settings_store import AppSettings
from .viewmodels.tsd import TsdState, TsdViewModel
from .widgets import PathRow, searchable_combo, sync_combo

if TYPE_CHECKING:
    from .main_window import MainWindow


class ManualJsonDialog(QDialog):
    """Dialog editor JSON untuk seluruh override manual."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit konteks manual TSD")
        self.resize(760, 560)
        self._data: dict[str, Any] | None = None

        self.editor = QPlainTextEdit(text)
        hint = QLabel(
            "Edit objek JSON. Perubahan hanya disimpan setelah tombol OK."
        )
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.editor, 1)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        try:
            data = json.loads(self.editor.toPlainText() or "{}")
        except json.JSONDecodeError as exc:
            QMessageBox.warning(
                self, "JSON tidak valid", f"Baris {exc.lineno}: {exc.msg}"
            )
            return
        if not isinstance(data, dict):
            QMessageBox.warning(self, "JSON tidak valid", "Akar JSON harus objek.")
            return
        self._data = data
        self.accept()

    def data(self) -> dict[str, Any] | None:
        return self._data


class TsdTab(QWidget):
    """Tab: pilih workbook, isi konteks manual, lalu render TSD HTML."""

    def __init__(
        self,
        window: MainWindow,
        *,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self.window = window
        settings = settings or AppSettings()
        runner = getattr(window, "runner", None) or WindowSubmitter(window)
        self.vm = TsdViewModel(settings, runner)
        self._build_ui()

        self.vm.state_changed.connect(self.render)
        self.vm.log.connect(self.window.log)
        self._load_manual(quiet=True)
        self.vm.start()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        form = self.vm.form
        self.report_workbook = PathRow(form.report_workbook, file_filter="Excel (*.xlsx)")
        self.model_workbook = PathRow(form.model_workbook, file_filter="Excel (*.xlsx)")
        self.report_status = QLabel()
        self.model_status = QLabel()
        for label in (self.report_status, self.model_status):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.template_label = QLabel()
        self.template_label.setWordWrap(True)
        self.template_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        source_form = QFormLayout()
        source_form.addRow("Report workbook:", self.report_workbook)
        source_form.addRow("", self.report_status)
        source_form.addRow("Model workbook:", self.model_workbook)
        source_form.addRow("", self.model_status)
        source_form.addRow("Template:", self.template_label)
        source_box = QGroupBox("Sumber metadata")
        source_box.setLayout(source_form)

        self.manual = PathRow(form.manual_path, mode="save", file_filter="JSON (*.json)")
        self.manual.edit.setPlaceholderText("Otomatis: <nama output>.json")
        self.manual_status = QLabel()
        self.manual_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.load_manual_button = QPushButton("Muat")
        self.save_manual_button = QPushButton("Simpan")
        self.edit_json_button = QPushButton("Edit JSON...")
        manual_buttons = QHBoxLayout()
        manual_buttons.setContentsMargins(0, 0, 0, 0)
        manual_buttons.addWidget(self.load_manual_button)
        manual_buttons.addWidget(self.save_manual_button)
        manual_buttons.addWidget(self.edit_json_button)
        manual_buttons.addStretch(1)
        manual_buttons_widget = QWidget()
        manual_buttons_widget.setLayout(manual_buttons)

        manual_form = QFormLayout()
        manual_form.addRow("Konteks manual:", self.manual)
        manual_form.addRow("", self.manual_status)
        manual_form.addRow("", manual_buttons_widget)
        manual_box = QGroupBox("Konteks manual")
        manual_box.setLayout(manual_form)

        self.report_name = QLineEdit(self.vm.report_name)
        self.report_name.setToolTip(
            "Nama report dipakai untuk judul dokumen dan nama file output otomatis. "
            "Field dokumen, penandatangan, dan narasi diisi lewat konteks manual "
            "(Edit JSON... atau file sidecar)."
        )

        self.draft = QCheckBox("Mode draft (field kosong menjadi TODO)")
        self.draft.setChecked(form.draft)
        self.expand_all = QCheckBox("Buka semua panel expand")
        self.expand_all.setChecked(form.expand_all)
        self.generated_at = QLineEdit(self.vm.generated_at)
        options_form = QFormLayout()
        options_form.addRow("Nama report:", self.report_name)
        options_form.addRow("Tanggal dokumen:", self.generated_at)
        options_form.addRow("", self.draft)
        options_form.addRow("", self.expand_all)
        options_box = QGroupBox("Opsi render")
        options_box.setLayout(options_form)

        self.screenshots = QCheckBox(
            "Ambil screenshot page, visual & mobile dari Power BI Service"
        )
        self.screenshots.setChecked(form.screenshots)
        self.screenshots.setToolTip(
            "Kredensial memakai service principal yang sama dengan ekstraksi dan "
            "lineage (diisi di tab Pengaturan). Token tidak disimpan; cache PNG "
            f"ada di {SCREENSHOT_ASSET_DIR}\\<nama report>."
        )
        self.shot_workspace = searchable_combo("Pilih workspace...")
        self.shot_workspace_reload = QPushButton("Muat ulang daftar")
        workspace_row = QWidget()
        workspace_layout = QHBoxLayout(workspace_row)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.addWidget(self.shot_workspace, 1)
        workspace_layout.addWidget(self.shot_workspace_reload)
        self.shot_workspace_hint = QLabel("")
        self.shot_workspace_hint.setWordWrap(True)
        self.shot_workspace_hint.setStyleSheet("color: #a05000;")
        self.shot_workspace_hint.setVisible(False)
        self.settings_button = QPushButton("Buka Pengaturan")
        self.settings_button.setVisible(False)
        self.shot_report = searchable_combo("Pilih report...")
        self.shot_report_reload = QPushButton("Muat ulang report")
        report_row = QWidget()
        report_layout = QHBoxLayout(report_row)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.addWidget(self.shot_report, 1)
        report_layout.addWidget(self.shot_report_reload)
        self.shot_message = QLabel("")
        self.shot_message.setWordWrap(True)
        self.shot_message.setVisible(False)
        self.rls_username = QLineEdit(form.rls_username)
        self.rls_roles = QLineEdit(form.rls_roles)
        self.rls_roles.setPlaceholderText("HO, Region")
        self.shot_scope = QComboBox()
        for key in ("both", "pages", "visuals"):
            self.shot_scope.addItem(SCOPE_LABELS[key], key)
        index = self.shot_scope.findData(form.shot_scope)
        self.shot_scope.setCurrentIndex(index if index >= 0 else 0)
        self.shot_scale = QComboBox()
        self.shot_scale.addItem("1x (file ringkas)", 1.0)
        self.shot_scale.addItem("2x (lebih tajam)", 2.0)
        index = self.shot_scale.findData(form.shot_scale)
        self.shot_scale.setCurrentIndex(index if index >= 0 else 0)
        self.shot_mobile = QCheckBox(
            "Sertakan layout mobile di 2.2.7.2 (bila report punya phone layout)"
        )
        self.shot_mobile.setChecked(form.shot_mobile)
        self.shot_mobile.setToolTip(
            "Hanya halaman yang punya mobile layout yang diambil; halaman lain "
            "dilewati dan 2.2.7.2 diberi catatan."
        )
        self.shot_headed = QCheckBox("Tampilkan browser saat capture (debug)")
        self.include_decorative = QCheckBox(
            "Sertakan shape/image/tombol sebagai baris visual"
        )
        self.include_decorative.setChecked(form.include_decorative)
        self.include_decorative.setToolTip(
            "Default: objek dekoratif tetap terlihat di screenshot halaman, "
            "tetapi tidak dibuatkan baris visual sendiri."
        )
        self.shot_status = QLabel()
        self.shot_status.setWordWrap(True)
        self.shot_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.capture_button = QPushButton("Ambil screenshot")
        self.clear_shots_button = QPushButton("Hapus cache")
        shot_buttons = QHBoxLayout()
        shot_buttons.setContentsMargins(0, 0, 0, 0)
        shot_buttons.addWidget(self.capture_button)
        shot_buttons.addWidget(self.clear_shots_button)
        shot_buttons.addStretch(1)
        shot_buttons_widget = QWidget()
        shot_buttons_widget.setLayout(shot_buttons)

        shots_form = QFormLayout()
        shots_form.addRow("", self.screenshots)
        shots_form.addRow("Workspace:", workspace_row)
        shots_form.addRow("", self.shot_workspace_hint)
        shots_form.addRow("", self.settings_button)
        shots_form.addRow("Report:", report_row)
        shots_form.addRow("", self.shot_message)
        shots_form.addRow("RLS username:", self.rls_username)
        shots_form.addRow("RLS roles:", self.rls_roles)
        shots_form.addRow("Cakupan:", self.shot_scope)
        shots_form.addRow("Skala:", self.shot_scale)
        shots_form.addRow("", self.shot_mobile)
        shots_form.addRow("", self.shot_headed)
        shots_form.addRow("", self.include_decorative)
        shots_form.addRow("Cache:", self.shot_status)
        shots_form.addRow("", shot_buttons_widget)
        shots_box = QGroupBox("Screenshot Report (Power BI Service)")
        shots_box.setLayout(shots_form)

        self.out_dir = PathRow(form.out_dir, mode="dir")
        self.out_name = QLineEdit(self.vm.out_name)
        self.out_status = QLabel()
        self.out_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.open_button = QPushButton("Buka HTML")
        self.open_folder_button = QPushButton("Buka folder")
        output_buttons = QHBoxLayout()
        output_buttons.setContentsMargins(0, 0, 0, 0)
        output_buttons.addWidget(self.open_button)
        output_buttons.addWidget(self.open_folder_button)
        output_buttons.addStretch(1)
        output_buttons_widget = QWidget()
        output_buttons_widget.setLayout(output_buttons)

        output_form = QFormLayout()
        output_form.addRow("Folder:", self.out_dir)
        output_form.addRow("Nama file:", self.out_name)
        output_form.addRow("", self.out_status)
        output_form.addRow("", output_buttons_widget)
        output_box = QGroupBox("Output")
        output_box.setLayout(output_form)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(source_box)
        content_layout.addWidget(manual_box)
        content_layout.addWidget(options_box)
        content_layout.addWidget(shots_box)
        content_layout.addWidget(output_box)
        content_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)

        self.run_button = QPushButton("Generate TSD")
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.run_button)

        self._connect_inputs()

    def _connect_inputs(self) -> None:
        self.report_workbook.edit.textChanged.connect(
            lambda text: self.vm.apply(report_workbook=text)
        )
        self.model_workbook.edit.textChanged.connect(
            lambda text: self.vm.apply(model_workbook=text)
        )
        self.manual.edit.textChanged.connect(
            lambda text: self.vm.apply(manual_path=text)
        )
        self.manual.edit.editingFinished.connect(lambda: self._load_manual(quiet=True))
        self.out_dir.edit.textChanged.connect(lambda text: self.vm.apply(out_dir=text))
        self.report_name.textChanged.connect(self.vm.set_report_name)
        self.out_name.textEdited.connect(self.vm.set_out_name)
        self.screenshots.toggled.connect(
            lambda checked: self.vm.apply(screenshots=checked)
        )
        self.shot_workspace.currentIndexChanged.connect(self.vm.select_workspace)
        self.shot_report.currentIndexChanged.connect(self.vm.select_report)
        self.shot_workspace_reload.clicked.connect(self.vm.reload_workspaces)
        self.shot_report_reload.clicked.connect(self.vm.reload_reports)
        self.settings_button.clicked.connect(lambda: self.window.open_settings_tab())
        self.rls_username.textChanged.connect(self._on_rls_changed)
        self.rls_roles.textChanged.connect(self._on_rls_changed)
        self.shot_scope.currentIndexChanged.connect(
            lambda _index: self.vm.apply(
                shot_scope=self.shot_scope.currentData() or "both"
            )
        )
        self.shot_scale.currentIndexChanged.connect(
            lambda _index: self.vm.apply(
                shot_scale=float(self.shot_scale.currentData() or 1.0)
            )
        )
        self.shot_mobile.toggled.connect(
            lambda checked: self.vm.apply(shot_mobile=checked)
        )
        self.shot_headed.toggled.connect(
            lambda checked: self.vm.set_headless(not checked)
        )
        self.include_decorative.toggled.connect(
            lambda checked: self.vm.apply(include_decorative=checked)
        )
        self.draft.toggled.connect(lambda checked: self.vm.apply(draft=checked))
        self.expand_all.toggled.connect(
            lambda checked: self.vm.apply(expand_all=checked)
        )
        self.generated_at.textChanged.connect(self.vm.set_generated_at)
        self.load_manual_button.clicked.connect(self._load_manual)
        self.save_manual_button.clicked.connect(self._save_manual)
        self.edit_json_button.clicked.connect(self._edit_json)
        self.capture_button.clicked.connect(self.vm.capture_now)
        self.clear_shots_button.clicked.connect(self._clear_cache)
        self.run_button.clicked.connect(self._run)
        self.open_button.clicked.connect(self._open_output)
        self.open_folder_button.clicked.connect(self._open_folder)

    # -- render ------------------------------------------------------------
    def render(self, state: TsdState) -> None:
        self.report_status.setText(state.report_status)
        self.model_status.setText(state.model_status)
        self.template_label.setText(state.template_status)
        self.manual_status.setText(state.manual_status)
        self.out_status.setText(state.output_status)
        self.shot_status.setText(state.cache_status)
        self._set_text(self.out_name, state.out_name)
        self._set_text(self.rls_username, state.rls_username)
        self._set_text(self.rls_roles, state.rls_roles)

        sync_combo(self.shot_workspace, state.workspaces, state.workspace_index)
        sync_combo(self.shot_report, state.reports, state.report_index)
        self.shot_workspace_hint.setText(state.workspace_hint)
        self.shot_workspace_hint.setVisible(bool(state.workspace_hint))
        self.settings_button.setVisible(state.settings_shortcut_visible)
        text = state.loading_text or state.message
        self.shot_message.setText(text)
        self.shot_message.setVisible(bool(text))
        self.shot_message.setStyleSheet(
            "color: #606060;" if state.loading_text else "color: #a05000;"
        )

        for widget in (
            self.report_workbook,
            self.model_workbook,
            self.manual,
            self.load_manual_button,
            self.save_manual_button,
            self.edit_json_button,
            self.report_name,
            self.draft,
            self.expand_all,
            self.generated_at,
            self.screenshots,
            self.rls_username,
            self.rls_roles,
            self.shot_scope,
            self.shot_scale,
            self.shot_mobile,
            self.shot_headed,
            self.include_decorative,
            self.out_dir,
            self.out_name,
        ):
            widget.setEnabled(state.idle)

        self.shot_workspace.setEnabled(state.idle and state.picker_active)
        self.shot_workspace_reload.setEnabled(state.idle and state.picker_active)
        self.settings_button.setEnabled(state.idle)
        self.shot_report.setEnabled(state.idle and state.reports_active)
        self.shot_report_reload.setEnabled(state.idle and state.reports_active)

        self.run_button.setEnabled(state.can_run)
        self.capture_button.setEnabled(state.can_capture)
        self.clear_shots_button.setEnabled(state.can_clear_cache)
        self.open_button.setEnabled(state.idle and state.output_exists)
        self.open_folder_button.setEnabled(state.idle and state.folder_ready)

    def showEvent(self, event: Any) -> None:  # noqa: N802 - nama Qt
        super().showEvent(event)
        # Katalog bisa baru disinkronkan dari tab Pengaturan.
        self.vm.reload_workspaces()

    @staticmethod
    def _set_text(widget: QLineEdit, value: str) -> None:
        if widget.text() == value:
            return
        widget.blockSignals(True)
        widget.setText(value)
        widget.blockSignals(False)

    # -- konteks manual ----------------------------------------------------
    def _load_manual(self, quiet: bool = False) -> None:
        data = self.vm.load_manual(quiet=quiet)
        if data is not None:
            self._fill_form(data)

    def _fill_form(self, manual: Mapping[str, Any]) -> None:
        """Isi widget dari sidecar: hanya meta render dan nama report.

        Field dokumen, penandatangan, dan narasi tidak punya widget lagi; isinya
        dibiarkan di sidecar JSON agar tidak tertimpa nilai kosong.
        """
        meta = section(manual, "meta")
        report = section(manual, "report")

        if "draft" in meta:
            self.draft.setChecked(bool(meta["draft"]))
        if "expand_all" in meta:
            self.expand_all.setChecked(bool(meta["expand_all"]))
        name = text_value(report.get("name"))
        if name:
            self.report_name.setText(name)

    def _collect_manual(self) -> dict[str, Any]:
        """Gabungkan input GUI ke sidecar tanpa menghapus kunci lain.

        Hanya ``meta`` dan nama report yang ditulis dari widget. Kunci
        ``document.*``/``report.*`` lain dibiarkan apa adanya; menulis string
        kosong akan menimpa isian manual yang sah saat merge.
        """
        manual = copy.deepcopy(self.vm.manual_data) if self.vm.manual_data else {}
        meta = section(manual, "meta")
        meta.update(
            {
                "draft": self.draft.isChecked(),
                "expand_all": self.expand_all.isChecked(),
            }
        )
        manual["meta"] = meta

        name = self.report_name.text().strip()
        if name:
            report = section(manual, "report")
            report["name"] = name
            manual["report"] = report
        return manual

    def _save_manual(self) -> None:
        self.vm.save_manual(self._collect_manual())

    def _edit_json(self) -> None:
        payload = self.vm.manual_data or self._collect_manual()
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        dialog = ManualJsonDialog(text, self)
        if not dialog.exec():
            return
        data = dialog.data()
        if data is None:
            return
        if self.vm.save_manual(data) is None:
            return
        self._fill_form(data)

    # -- eksekusi ----------------------------------------------------------
    def _run(self) -> None:
        self.vm.run(self._collect_manual())

    def _on_rls_changed(self, _text: str) -> None:
        self.vm.set_rls(self.rls_username.text(), self.rls_roles.text())

    def _clear_cache(self) -> None:
        folder = self.vm.assets_dir
        if not folder.exists():
            self.window.log(f"Cache screenshot belum ada: {folder}")
            return
        answer = QMessageBox.question(
            self,
            "Hapus cache screenshot",
            f"Hapus folder cache berikut?\n{folder}",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.vm.clear_cache()

    # -- aksi file ---------------------------------------------------------
    def _open_output(self) -> None:
        path = self.vm.output_path
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_folder(self) -> None:
        folder = self.vm.output_path.parent
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # -- dipanggil jendela utama ------------------------------------------
    def set_workbooks(self, folder: Path) -> None:
        """Arahkan workbook ke folder hasil ekstraksi."""
        folder = Path(folder)
        changes: dict[str, Any] = {"out_dir": str(folder)}
        report = folder / OUT_FILE.name
        model = folder / MODEL_WORKBOOK_NAME
        if report.exists():
            changes["report_workbook"] = str(report)
        if model.exists():
            changes["model_workbook"] = str(model)
        self.vm.apply(**changes)
        self.report_workbook.set_text(self.vm.form.report_workbook)
        self.model_workbook.set_text(self.vm.form.model_workbook)
        self.out_dir.set_text(self.vm.form.out_dir)

    def refresh(self) -> None:
        self.vm.refresh()

    def set_busy(self, busy: bool) -> None:
        self.vm.set_busy(busy)
