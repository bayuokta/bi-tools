"""Uji JobRunner: pekerjaan latar, sinyal log/busy, dan penolakan saat sibuk."""

from __future__ import annotations

import unittest

try:
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

    QT_AVAILABLE = True
except ImportError:  # pragma: no cover - tergantung environment
    QT_AVAILABLE = False

from core.errors import ExtractionError

if QT_AVAILABLE:
    from app.job_runner import JobRunner


@unittest.skipUnless(QT_AVAILABLE, "PySide6 tidak tersedia")
class JobRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def _run(self, job):
        runner = JobRunner()
        logs: list[str] = []
        succeeded: list[object] = []
        failed: list[str] = []
        started: list[str] = []
        runner.log.connect(logs.append)
        runner.succeeded.connect(succeeded.append)
        runner.failed.connect(failed.append)
        runner.started.connect(started.append)

        loop = QEventLoop()
        runner.busy_changed.connect(lambda busy: None if busy else loop.quit())
        QTimer.singleShot(5000, loop.quit)
        self.assertTrue(runner.submit("Pekerjaan uji", job))
        loop.exec()
        self.assertFalse(runner.is_busy())
        return logs, started, succeeded, failed

    def test_success_emits_result_and_closes_log(self) -> None:
        logs, started, succeeded, failed = self._run(lambda log: 42)

        self.assertEqual(started, ["Pekerjaan uji"])
        self.assertEqual(succeeded, [42])
        self.assertEqual(failed, [])
        self.assertIn("=== Pekerjaan uji ===", logs)
        self.assertEqual(logs[-1], "Selesai.")

    def test_job_log_is_forwarded(self) -> None:
        logs, _started, _succeeded, _failed = self._run(
            lambda log: log("sedang bekerja") or "ok"
        )
        self.assertIn("sedang bekerja", logs)

    def test_extraction_error_becomes_failure_signal(self) -> None:
        def job(_log):
            raise ExtractionError("kredensial belum lengkap")

        logs, _started, succeeded, failed = self._run(job)

        self.assertEqual(succeeded, [])
        self.assertEqual(failed, ["kredensial belum lengkap"])
        self.assertIn("ERROR: kredensial belum lengkap", logs)
        self.assertNotIn("Selesai.", logs)

    def test_running_worker_rejects_second_submit(self) -> None:
        class RunningWorker:
            def isRunning(self) -> bool:
                return True

        runner = JobRunner()
        runner._worker = RunningWorker()  # noqa: SLF001 - simulasi worker aktif

        self.assertTrue(runner.is_busy())
        self.assertFalse(runner.submit("kedua", lambda log: None))


if __name__ == "__main__":
    unittest.main()
