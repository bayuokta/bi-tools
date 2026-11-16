"""Sub-tab ekstraksi report dari Power BI Service (+ model via XMLA), view pasif.

Workspace dipilih dari katalog di SQLite dan endpoint XMLA diturunkan oleh view
model. Dataset/report dimuat lewat view model (JobRunner), bukan dari widget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QWidget,
)

from .extraction_base import ExtractionBase
from .settings import SETTINGS_SCOPE_SERVICE_KEY
from .settings_store import AppSettings
from .viewmodels.metadata import ServiceMetadataState, ServiceMetadataViewModel
from .widgets import searchable_combo, sync_combo

if TYPE_CHECKING:
    from .main_window import MainWindow


class ServiceExtractionTab(ExtractionBase):
    """Ambil report lewat Fabric API dan/atau model lewat XMLA endpoint."""

    SECTION_ORDER = ("scope", "model", "source", "output")

    def __init__(
        self,
        window: MainWindow,
        *,
        settings: AppSettings,
        runner: Any,
    ) -> None:
        self.vm = ServiceMetadataViewModel(
            settings, runner, scope_key=SETTINGS_SCOPE_SERVICE_KEY
        )
        self._credentials_missing = False
        self._missing_credentials: tuple[str, ...] = ()
        self._credentials_warned = False
        super().__init__(window, view_model=self.vm)

        self.workspace.currentIndexChanged.connect(self.vm.select_workspace)
        self.model_workspace.currentIndexChanged.connect(self.vm.select_workspace)
        self.report.currentIndexChanged.connect(self.vm.select_report)
        self.catalog.currentIndexChanged.connect(self.vm.select_catalog)
        self.workspace_reload.clicked.connect(self.vm.reload_workspaces)
        self.contents_reload.clicked.connect(self.vm.reload_contents)
        self.settings_button.clicked.connect(lambda: self.window.open_settings_tab())

    def showEvent(self, event: Any) -> None:  # noqa: N802 - nama Qt
        super().showEvent(event)
        # Baca ulang katalog SQLite: mungkin baru diisi dari tab Pengaturan.
        self.vm.reload_workspaces()
        self._maybe_warn_credentials()

    # -- UI ----------------------------------------------------------------
    def _build_source_box(self) -> QWidget:
        self.workspace = self._combo("Pilih workspace...")
        self.workspace_reload = QPushButton("Muat ulang daftar")
        workspace_row = QWidget()
        workspace_layout = QHBoxLayout(workspace_row)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.addWidget(self.workspace, 1)
        workspace_layout.addWidget(self.workspace_reload)

        self.workspace_hint = QLabel("")
        self.workspace_hint.setWordWrap(True)
        self.workspace_hint.setStyleSheet("color: #a05000;")
        self.workspace_hint.setVisible(False)

        self.settings_button = QPushButton("Buka Pengaturan")
        self.settings_button.setVisible(False)

        self.report = self._combo("Pilih report...")
        self.contents_reload = QPushButton("Muat ulang dataset & report")
        report_row = QWidget()
        report_layout = QHBoxLayout(report_row)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.addWidget(self.report, 1)
        report_layout.addWidget(self.contents_reload)

        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setVisible(False)

        self.report_note = QLabel("")
        self.report_note.setWordWrap(True)
        self.report_note.setStyleSheet("color: #a05000;")
        self.report_note.setVisible(False)

        form = QFormLayout()
        form.addRow("Workspace:", workspace_row)
        form.addRow("", self.workspace_hint)
        form.addRow("", self.settings_button)
        form.addRow("Report:", report_row)
        form.addRow("", self.message)
        form.addRow(self.report_note)
        box = QGroupBox("Sumber report (Power BI Service)")
        box.setLayout(form)
        return box

    def _build_model_rows(self, form: QFormLayout) -> None:
        self.model_workspace = self._combo("Pilih workspace...")
        self.endpoint = QLineEdit(self.vm.endpoint)
        self.endpoint.setReadOnly(True)
        self.endpoint.setPlaceholderText("Otomatis dari workspace yang dipilih")
        self.endpoint.setToolTip(
            "Endpoint XMLA diturunkan dari workspace yang dipilih "
            "(powerbi://api.powerbi.com/v1.0/myorg/<nama workspace>). "
            "XMLA Read harus aktif untuk dataset ini."
        )
        self.catalog = self._combo("Pilih dataset...")
        self.catalog.setToolTip(
            "Catalog adalah nama dataset di workspace. Nilainya terisi otomatis "
            "dari dataset report yang dipilih."
        )
        form.addRow("Workspace:", self.model_workspace)
        form.addRow("Endpoint XMLA:", self.endpoint)
        form.addRow("Catalog:", self.catalog)

    @staticmethod
    def _combo(placeholder: str) -> QComboBox:
        return searchable_combo(placeholder)

    # -- render ------------------------------------------------------------
    def render_source(self, state: ServiceMetadataState) -> None:
        sync_combo(self.workspace, state.workspaces, state.workspace_index)
        sync_combo(
            self.model_workspace, state.workspaces, state.workspace_index
        )
        sync_combo(self.catalog, state.datasets, state.dataset_index)
        sync_combo(self.report, state.reports, state.report_index)
        self._render_text(self.endpoint, state.endpoint_text)

        self._credentials_missing = state.credentials_missing
        self._missing_credentials = state.missing_credentials
        if not state.credentials_missing:
            self._credentials_warned = False

        text = state.loading_text or state.message
        self.message.setText(text)
        self.message.setVisible(bool(text))
        self.message.setStyleSheet(
            "color: #606060;" if state.loading_text else "color: #a05000;"
        )

        self.workspace_hint.setText(state.workspace_hint)
        self.workspace_hint.setVisible(bool(state.workspace_hint))
        self.settings_button.setVisible(state.settings_shortcut_visible)
        self.report_note.setText(state.report_note)
        self.report_note.setVisible(state.report_note_visible)

        self.workspace.setEnabled(state.workspace_active)
        self.model_workspace.setEnabled(state.workspace_active)
        self.workspace_reload.setEnabled(state.workspace_active)
        self.settings_button.setEnabled(state.workspace_active)
        self.contents_reload.setEnabled(
            state.workspace_active and bool(state.workspace_id)
        )
        self.report.setEnabled(state.source_active)
        self.catalog.setEnabled(state.model_inputs_active)

    @staticmethod
    def _render_text(widget: QLineEdit, value: str) -> None:
        """Isi field tanpa memicu sinyal balik ke view model."""
        if widget.text() == value:
            return
        widget.blockSignals(True)
        widget.setText(value)
        widget.blockSignals(False)

    # -- peringatan kredensial ---------------------------------------------
    def _maybe_warn_credentials(self) -> None:
        """Tampilkan peringatan sekali per sesi bila service principal kurang."""
        if not self._credentials_missing or self._credentials_warned:
            return
        self._credentials_warned = True
        if self._warn_credentials():
            self.window.open_settings_tab()

    def _warn_credentials(self) -> bool:
        """Dialog peringatan; ``True`` bila pengguna memilih Buka Pengaturan."""
        missing = ", ".join(self._missing_credentials) or "service principal"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Kredensial belum lengkap")
        box.setText(
            "Service principal belum lengkap; ekstraksi dari Power BI Service "
            "belum bisa dijalankan."
        )
        box.setInformativeText(f"Field yang belum diisi: {missing}.")
        open_button = box.addButton(
            "Buka Pengaturan", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton("Tutup", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(open_button)
        box.exec()
        return box.clickedButton() is open_button
