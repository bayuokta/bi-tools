"""Tab top-level Metadata & TSD.

Berisi tiga sub-tab: **Local** (file .pbix), **Power BI Service** (Fabric API +
XMLA), dan **Generate TSD**. Pembacaan instance Power BI Desktop dilakukan sekali
oleh container ini lalu dibagikan ke kedua sub-tab ekstraksi.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .job_runner import WindowSubmitter
from .local_tab import LocalExtractionTab
from .service_tab import ServiceExtractionTab
from .settings import (
    SETTINGS_ACTIVE_TAB_KEY,
    SETTINGS_REPORT_SOURCE_KEY,
)
from .settings_store import AppSettings

if TYPE_CHECKING:
    from .main_window import MainWindow

TAB_LOCAL = "local"
TAB_SERVICE = "service"
TAB_TSD = "tsd"
TAB_ORDER = (TAB_LOCAL, TAB_SERVICE, TAB_TSD)


class MetadataTab(QWidget):
    """Wadah sub-tab Local, Power BI Service, dan Generate TSD."""

    def __init__(
        self,
        window: MainWindow,
        *,
        settings: AppSettings | None = None,
        tsd: QWidget | None = None,
    ) -> None:
        super().__init__()
        self.window = window
        self._settings = settings or AppSettings()
        self._tsd = tsd
        self._runner = getattr(window, "runner", None) or WindowSubmitter(window)

        self.local_tab = LocalExtractionTab(
            window, settings=self._settings, runner=self._runner
        )
        self.service_tab = ServiceExtractionTab(
            window, settings=self._settings, runner=self._runner
        )

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.local_tab, "Local")
        self.tabs.addTab(self.service_tab, "Power BI Service")
        if tsd is not None:
            self.tabs.addTab(tsd, "Generate TSD")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)

        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._restore_active_tab()

    # -- sub-tab aktif -----------------------------------------------------
    def _restore_active_tab(self) -> None:
        saved = self._settings.value(SETTINGS_ACTIVE_TAB_KEY, "", type=str)
        if saved not in TAB_ORDER:
            legacy = self._settings.value(SETTINGS_REPORT_SOURCE_KEY, "", type=str)
            saved = legacy if legacy in (TAB_LOCAL, TAB_SERVICE) else TAB_LOCAL
        index = TAB_ORDER.index(saved)
        if index >= self.tabs.count():
            index = 0
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(index)
        self.tabs.blockSignals(False)

    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < len(TAB_ORDER):
            self._settings.set_value(SETTINGS_ACTIVE_TAB_KEY, TAB_ORDER[index])

    @property
    def active_tab(self) -> str:
        return TAB_ORDER[self.tabs.currentIndex()]

    def show_tsd(self, folder: Path | str | None = None) -> None:
        """Pilih sub-tab Generate TSD dan arahkan workbook ke folder hasil."""
        if self._tsd is None:
            return
        index = self.tabs.indexOf(self._tsd)
        if index >= 0:
            self.tabs.setCurrentIndex(index)
        if folder is not None:
            self._tsd.set_workbooks(Path(folder))
        self._tsd.refresh()

    # -- instance Power BI Desktop ----------------------------------------
    def refresh_instances(self) -> None:
        # Satu job pembacaan instance; hanya sub-tab Local yang memakainya.
        self.local_tab.refresh_instances()

    # -- status ------------------------------------------------------------
    def set_busy(self, busy: bool) -> None:
        self.local_tab.set_busy(busy)
        self.service_tab.set_busy(busy)
        if self._tsd is not None:
            self._tsd.set_busy(busy)


# Nama lama tetap tersedia agar import lama tidak langsung patah.
ExtractionTab = MetadataTab
