"""Komponen UI kecil yang dipakai ulang."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)


class PathRow(QWidget):
    """Kotak isian path dengan tombol Pilih."""

    def __init__(
        self,
        value: Path | str = "",
        *,
        mode: str = "open",
        file_filter: str = "Semua file (*)",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._filter = file_filter
        self.edit = QLineEdit(str(value))
        self.button = QPushButton("Pilih...")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)
        self.button.clicked.connect(self._browse)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, value: Path | str) -> None:
        self.edit.setText(str(value))

    def _browse(self) -> None:
        start = self.text() or str(Path.home())
        if self._mode == "save":
            path, _ = QFileDialog.getSaveFileName(self, "Simpan sebagai", start, self._filter)
        elif self._mode == "dir":
            path = QFileDialog.getExistingDirectory(self, "Pilih folder", start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Pilih file", start, self._filter)
        if path:
            self.edit.setText(path)


def searchable_combo(placeholder: str) -> QComboBox:
    """Combo yang bisa dicari (contains, tanpa membedakan huruf besar/kecil)."""
    combo = QComboBox()
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.setMaxVisibleItems(20)
    combo.setPlaceholderText(placeholder)
    completer = combo.completer()
    if completer is not None:
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    return combo


def sync_combo(combo: QComboBox, items: Sequence[str], index: int) -> None:
    """Isi combo tanpa memicu sinyal balik ke view model."""
    current = tuple(combo.itemText(position) for position in range(combo.count()))
    if current != tuple(items):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(list(items))
        combo.blockSignals(False)
    target = index if 0 <= index < combo.count() else -1
    if combo.currentIndex() != target:
        combo.blockSignals(True)
        combo.setCurrentIndex(target)
        combo.blockSignals(False)
