"""Sub-tab ekstraksi dari file ``.pbix`` lokal (view pasif)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from .extraction_base import ExtractionBase
from .settings import SETTINGS_SCOPE_LOCAL_KEY
from .settings_store import AppSettings
from .viewmodels.metadata import LocalMetadataState, LocalMetadataViewModel
from .widgets import PathRow

if TYPE_CHECKING:
    from .main_window import MainWindow


class LocalExtractionTab(ExtractionBase):
    """Pilih file .pbix, deteksi jenis sumber, lalu jalankan report/model."""

    SECTION_ORDER = ("scope", "model", "source", "output")

    def __init__(
        self,
        window: MainWindow,
        *,
        settings: AppSettings,
        runner: Any,
    ) -> None:
        self.vm = LocalMetadataViewModel(
            settings,
            runner,
            scope_key=SETTINGS_SCOPE_LOCAL_KEY,
        )
        super().__init__(window, view_model=self.vm)

        self._detect_timer = QTimer(self)
        self._detect_timer.setSingleShot(True)
        self._detect_timer.setInterval(250)
        self._detect_timer.timeout.connect(self.vm.detect_source)
        self.pbix.edit.textChanged.connect(self._on_pbix_changed)

    # -- UI ----------------------------------------------------------------
    def _build_source_box(self) -> QWidget:
        self.pbix = PathRow(self.vm.pbix_text, file_filter="Power BI (*.pbix)")
        self.kind_label = QLabel("Mendeteksi jenis sumber...")
        self.kind_label.setWordWrap(True)
        self.dataset_label = QLabel("")
        self.dataset_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("File .pbix:", self.pbix)
        form.addRow("Jenis:", self.kind_label)
        form.addRow("Detail:", self.dataset_label)
        box = QGroupBox("Sumber report (file lokal)")
        box.setLayout(form)
        return box

    def _build_model_rows(self, form: QFormLayout) -> None:
        self.instance = QComboBox()
        self.instance.setMinimumWidth(480)
        self.refresh_button = QPushButton("Muat ulang")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.instance, 1)
        row.addWidget(self.refresh_button)
        self.instance_row = QWidget()
        self.instance_row.setLayout(row)
        form.addRow("Instance Power BI Desktop:", self.instance_row)
        self.instance.currentIndexChanged.connect(self.vm.select_instance)
        self.refresh_button.clicked.connect(self.refresh_instances)

    # -- input -------------------------------------------------------------
    def _on_pbix_changed(self, text: str) -> None:
        self.vm.set_pbix(text)
        self._detect_timer.start()

    # -- instance ----------------------------------------------------------
    def refresh_instances(self) -> None:
        self.vm.refresh_instances()

    def apply_instances(self, instances: list[Any]) -> None:
        self.vm.apply_instances(instances)

    # -- render ------------------------------------------------------------
    def render_source(self, state: LocalMetadataState) -> None:
        self.kind_label.setText(state.kind_text)
        self.dataset_label.setText(state.dataset_text)
        self.instance.setEnabled(state.model_inputs_active)
        self.refresh_button.setEnabled(state.model_inputs_active)
        self._render_instances(state)

    def _render_instances(self, state: LocalMetadataState) -> None:
        expected = ([None] if state.instance_placeholder else []) + list(
            state.instances
        )
        if self._combo_signature() == expected:
            # Isi combo tidak berubah; cukup pastikan pilihan sesuai state.
            if self.instance.currentIndex() != state.instance_index:
                self.instance.blockSignals(True)
                self.instance.setCurrentIndex(state.instance_index)
                self.instance.blockSignals(False)
            return
        self.instance.blockSignals(True)
        try:
            self.instance.clear()
            if state.instance_placeholder:
                self.instance.addItem("-- pilih instance --", None)
            for item in state.instances:
                self.instance.addItem(item.label, item)
            self.instance.setCurrentIndex(state.instance_index)
        finally:
            self.instance.blockSignals(False)

    def _combo_signature(self) -> list[Any]:
        return [self.instance.itemData(i) for i in range(self.instance.count())]
