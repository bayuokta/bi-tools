"""Jendela utama: tab, panel log, dan status pekerjaan."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, QTimer

from .analysis_tab import AnalysisTab
from .job_runner import JobRunner
from .lineage_tab import LineageTab
from .settings_store import AppSettings
from .settings_tab import SettingsTab
from .tabs import MetadataTab
from .tsd_tab import TsdTab
from .worker import Job


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Power BI Metadata Tools")
        self.resize(980, 760)

        self.runner = JobRunner(self)
        self.runner.log.connect(self.log)
        self.runner.busy_changed.connect(self._set_busy)
        self.runner.succeeded.connect(self._on_succeeded)
        self.runner.failed.connect(self._on_failed)

        self.settings = settings or AppSettings(parent=self)
        # TSD dibuat lebih dulu karena dipakai sebagai sub-tab Metadata & TSD.
        self.tsd_tab = TsdTab(self, settings=self.settings)
        self.extraction_tab = MetadataTab(
            self, settings=self.settings, tsd=self.tsd_tab
        )
        self.lineage_tab = LineageTab(self, settings=self.settings)
        self.analysis_tab = AnalysisTab(self, settings=self.settings)
        self.settings_tab = SettingsTab(self, settings=self.settings)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.extraction_tab, "Metadata & TSD")
        self.tabs.addTab(self.analysis_tab, "Analisa Semantic Model")
        self.tabs.addTab(self.lineage_tab, "Lineage")
        self.tabs.addTab(self.settings_tab, "Pengaturan")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setPlaceholderText("Log ekstraksi akan tampil di sini.")

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setTextVisible(False)

        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(self.progress)
        log_layout.addWidget(self.log_view, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
        splitter.addWidget(log_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Siap")
        QTimer.singleShot(0, self.extraction_tab.refresh_instances)

    def log(self, message: str) -> None:
        for line in str(message).splitlines() or [""]:
            self.log_view.appendPlainText(line)

    def is_busy(self) -> bool:
        return self.runner.is_busy()

    def start_job(
        self,
        title: str,
        job: Job,
        on_success: Callable[[Any], None],
    ) -> None:
        if not self.runner.submit(title, job, on_success):
            QMessageBox.information(
                self,
                "Sedang berjalan",
                "Tunggu pekerjaan yang sedang berjalan selesai.",
            )
            return
        self.statusBar().showMessage(f"{title} berjalan...")

    def _on_succeeded(self, _result: Any) -> None:
        self.statusBar().showMessage("Ekstraksi selesai", 8000)

    def _on_failed(self, message: str) -> None:
        self.statusBar().showMessage("Ekstraksi gagal", 8000)
        QMessageBox.critical(self, "Ekstraksi gagal", message)

    def _set_busy(self, busy: bool) -> None:
        self.progress.setVisible(busy)
        self.extraction_tab.set_busy(busy)
        self.analysis_tab.set_busy(busy)
        self.lineage_tab.set_busy(busy)
        self.settings_tab.set_busy(busy)

    def open_settings_tab(self) -> None:
        """Pindah ke tab Pengaturan (satu tempat kredensial dan path)."""
        self.tabs.setCurrentWidget(self.settings_tab)

    def open_tsd_tab(self, folder: Path | None = None) -> None:
        """Pindah ke sub-tab Generate TSD dan arahkan ke folder hasil ekstraksi."""
        self.tabs.setCurrentWidget(self.extraction_tab)
        self.extraction_tab.show_tsd(folder)


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    settings = AppSettings()
    # Sesi selalu mulai bersih: pilihan workspace/report/dataset dikosongkan,
    # preferensi dan kredensial tetap tersimpan.
    settings.reset_session()
    window = MainWindow(settings=settings)
    window.show()
    return app.exec()
