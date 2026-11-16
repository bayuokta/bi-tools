"""Kerangka widget bersama sub-tab ekstraksi Local dan Power BI Service.

Kelas ini hanya membangun widget, meneruskan input pengguna ke view model, dan
merender :class:`MetadataState`. Keputusan cakupan, enable/disable, dan
penyusunan request ada di ``app.viewmodels.metadata``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.requests import SCOPE_BOTH, SCOPE_MODEL, SCOPE_REPORT

from .viewmodels.metadata import MetadataState, MetadataViewModel
from .widgets import PathRow

if TYPE_CHECKING:
    from .main_window import MainWindow

SCOPE_OPTIONS = [
    ("Report + semantic model", SCOPE_BOTH),
    ("Report saja", SCOPE_REPORT),
    ("Semantic model saja", SCOPE_MODEL),
]


class ExtractionBase(QWidget):
    """View pasif untuk satu alur ekstraksi (local atau service)."""

    SECTION_ORDER: tuple[str, ...] = ("source", "scope", "model", "output")

    def __init__(
        self,
        window: MainWindow,
        *,
        view_model: MetadataViewModel,
    ) -> None:
        super().__init__()
        self.window = window
        self.vm = view_model

        self.scope = QComboBox()
        for label, key in SCOPE_OPTIONS:
            self.scope.addItem(label, key)

        scope_form = QFormLayout()
        scope_form.addRow("Cakupan:", self.scope)
        self.scope_box = QGroupBox("Cakupan ekstraksi")
        self.scope_box.setLayout(scope_form)

        model_form = QFormLayout()
        self._build_model_rows(model_form)
        self.model_box = QGroupBox("Semantic model")
        self.model_box.setLayout(model_form)

        self.out_dir = PathRow(self.vm.out_dir, mode="dir")
        self.report_status = QLabel()
        self.model_status = QLabel()
        for label in (self.report_status, self.model_status):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.open_report_button = QPushButton("Buka report")
        self.open_model_button = QPushButton("Buka model")
        self.open_folder_button = QPushButton("Buka folder")
        self.tsd_button = QPushButton("Buat TSD...")
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_report_button)
        buttons.addWidget(self.open_model_button)
        buttons.addWidget(self.open_folder_button)
        buttons.addWidget(self.tsd_button)
        buttons.addStretch(1)

        output_form = QFormLayout()
        output_form.addRow("Folder:", self.out_dir)
        output_form.addRow("Report:", self.report_status)
        output_form.addRow("Model:", self.model_status)
        output_form.addRow("", buttons)
        self.output_box = QGroupBox("Output")
        self.output_box.setLayout(output_form)

        self.run_button = QPushButton("Jalankan ekstraksi")

        content = QWidget()
        layout = QVBoxLayout(content)
        self.source_box = self._build_source_box()
        sections = {
            "source": self.source_box,
            "scope": self.scope_box,
            "model": self.model_box,
            "output": self.output_box,
        }
        for key in self.SECTION_ORDER:
            layout.addWidget(sections[key])
        layout.addWidget(self.run_button)
        layout.addStretch(1)
        self.content = content

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.scope.currentIndexChanged.connect(self._on_scope_changed)
        self.out_dir.edit.textEdited.connect(self._on_out_dir_edited)
        self.run_button.clicked.connect(lambda: self.vm.submit())
        self.open_report_button.clicked.connect(lambda: self._open(self.vm.report_out))
        self.open_model_button.clicked.connect(lambda: self._open(self.vm.model_out))
        self.open_folder_button.clicked.connect(self._open_folder)
        self.tsd_button.clicked.connect(self._open_tsd)

        self.vm.state_changed.connect(self.render)
        self.vm.log.connect(self.window.log)
        self.vm.start()

    # -- hook subclass -----------------------------------------------------
    def _build_source_box(self) -> QWidget:
        raise NotImplementedError

    def _build_model_rows(self, form: QFormLayout) -> None:
        """Baris grup Semantic model, ditentukan masing-masing sub-tab."""
        raise NotImplementedError

    def render_source(self, state: MetadataState) -> None:
        """Render widget khas sumber (instance atau URL/endpoint)."""

    # -- input -------------------------------------------------------------
    def _on_scope_changed(self, _index: int) -> None:
        if self.scope.count():
            self.vm.set_scope(self.scope.currentData())

    def _on_out_dir_edited(self, text: str) -> None:
        self.vm.set_out_dir(text)

    # -- render ------------------------------------------------------------
    def render(self, state: MetadataState) -> None:
        self._render_scope(state.scope)
        self._render_out_dir(state.out_folder)

        self.scope.setEnabled(state.idle)
        self.model_box.setEnabled(state.idle)
        self.out_dir.setEnabled(state.idle)
        self.run_button.setEnabled(state.can_run)

        self.report_status.setText(state.report_status)
        self.model_status.setText(state.model_status)
        self.open_report_button.setEnabled(state.report_exists)
        self.open_model_button.setEnabled(state.model_exists)
        self.open_folder_button.setEnabled(state.folder_exists)

        self.render_source(state)

    def _render_scope(self, scope: str) -> None:
        index = next(
            (i for i, (_label, key) in enumerate(SCOPE_OPTIONS) if key == scope), -1
        )
        if index < 0 or index == self.scope.currentIndex():
            return
        self.scope.blockSignals(True)
        self.scope.setCurrentIndex(index)
        self.scope.blockSignals(False)

    def _render_out_dir(self, folder: Path) -> None:
        if self.out_dir.text() != str(folder):
            self.out_dir.set_text(folder)

    # -- aksi --------------------------------------------------------------
    def _open(self, path: Path) -> None:
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_folder(self) -> None:
        folder = self.vm.out_dir
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_tsd(self) -> None:
        self.window.open_tsd_tab(self.vm.out_dir)

    def set_busy(self, busy: bool) -> None:
        self.vm.set_busy(busy)
