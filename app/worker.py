"""Menjalankan ekstraksi di thread terpisah agar jendela tidak macet."""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from core.errors import ExtractionError

Job = Callable[[Callable[[str], None]], Any]


class ExtractionWorker(QThread):
    log = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, job: Job) -> None:
        super().__init__()
        self._job = job

    def run(self) -> None:
        try:
            result = self._job(self.log.emit)
        except ExtractionError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 - ditampilkan ke pengguna
            self.log.emit(traceback.format_exc())
            self.failed.emit(f"Terjadi kesalahan tak terduga: {exc}")
        else:
            self.succeeded.emit(result)
