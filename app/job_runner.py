"""Satu tempat menjalankan pekerjaan GUI di thread terpisah.

``JobRunner`` membungkus :class:`app.worker.ExtractionWorker` sehingga tab tidak
perlu menyentuh ``QThread`` atau menyimpan referensi worker sendiri. Semua
pemanggil (tab Metadata, TSD, Lineage, Pengaturan) memakai runner yang sama
lewat injeksi dari :class:`app.main_window.MainWindow`.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from .worker import ExtractionWorker, Job

SuccessHandler = Callable[[Any], None]


class JobRunner(QObject):
    """Fasad untuk pekerjaan latar: log, status sibuk, sukses, dan gagal."""

    log = Signal(str)
    started = Signal(str)
    busy_changed = Signal(bool)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: ExtractionWorker | None = None
        self._on_success: SuccessHandler | None = None

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def submit(
        self,
        title: str,
        job: Job,
        on_success: SuccessHandler | None = None,
    ) -> bool:
        """Jalankan ``job``; kembalikan ``False`` bila masih ada pekerjaan lain."""
        if self.is_busy():
            return False
        self.log.emit(f"=== {title} ===")
        self._on_success = on_success
        self._set_busy(True)
        self.started.emit(title)

        worker = ExtractionWorker(job)
        worker.log.connect(self.log)
        worker.succeeded.connect(self._handle_success)
        worker.failed.connect(self._handle_failure)
        worker.finished.connect(self._handle_finished)
        self._worker = worker
        worker.start()
        return True

    def _handle_success(self, result: Any) -> None:
        callback = self._on_success
        if callback is not None:
            callback(result)
        self.succeeded.emit(result)
        self.log.emit("Selesai.")

    def _handle_failure(self, message: str) -> None:
        self.log.emit(f"ERROR: {message}")
        self.failed.emit(message)

    def _handle_finished(self) -> None:
        self._worker = None
        self._on_success = None
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self.busy_changed.emit(busy)


class WindowSubmitter:
    """Adaptor untuk jendela yang hanya punya ``start_job`` (mis. tiruan uji)."""

    def __init__(self, window: Any) -> None:
        self._window = window

    def submit(
        self,
        title: str,
        job: Job,
        on_success: SuccessHandler | None = None,
    ) -> bool:
        self._window.start_job(title, job, on_success)
        return True
