"""Uji antrean job: sibuk, log, SSE, pembatalan, dan endpoint HTTP."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
import warnings
from pathlib import Path

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated"
)

from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app
from server.jobs import (
    BusyError,
    JobManager,
    JobNotFound,
    MAX_LOG_LINES,
    format_event,
    stream_events,
)
from server.settings_store import SettingsStore


def wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class JobManagerTests(unittest.TestCase):
    def test_job_finishes_with_result_and_log(self) -> None:
        manager = JobManager()
        job = manager.submit(
            "demo", lambda log, cancel: (log("baris satu"), {"nilai": 1})[1]
        )
        self.assertTrue(wait_until(lambda: not job.running))
        snapshot = manager.snapshot(job.id)

        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["result"], {"nilai": 1})
        self.assertEqual(snapshot["log"], ["baris satu"])

    def test_second_submit_is_rejected_while_running(self) -> None:
        manager = JobManager()
        release = threading.Event()
        job = manager.submit("lama", lambda log, cancel: release.wait(5))
        self.assertTrue(wait_until(lambda: manager.current is not None))
        with self.assertRaises(BusyError):
            manager.submit("baru", lambda log, cancel: None)
        release.set()
        self.assertTrue(wait_until(lambda: not job.running))

    def test_error_is_captured(self) -> None:
        manager = JobManager()

        def boom(log, cancel):
            raise RuntimeError("gagal uji")

        job = manager.submit("gagal", boom)
        self.assertTrue(wait_until(lambda: not job.running))
        snapshot = manager.snapshot(job.id)
        self.assertEqual(snapshot["status"], "error")
        self.assertEqual(snapshot["error"], "gagal uji")

    def test_cancel_marks_request(self) -> None:
        manager = JobManager()
        release = threading.Event()
        job = manager.submit("lama", lambda log, cancel: cancel.wait(5) or release.wait(5))
        self.assertTrue(wait_until(lambda: manager.current is not None))
        manager.cancel(job.id)
        self.assertTrue(wait_until(lambda: not job.running))
        self.assertEqual(manager.snapshot(job.id)["status"], "cancelled")
        release.set()

    def test_unknown_job_raises(self) -> None:
        manager = JobManager()
        with self.assertRaises(JobNotFound):
            manager.get("tidak-ada")

    def test_log_is_capped(self) -> None:
        manager = JobManager()

        def banyak(log, cancel):
            for index in range(MAX_LOG_LINES + 10):
                log(f"baris {index}")

        job = manager.submit("log", banyak)
        self.assertTrue(wait_until(lambda: not job.running))
        self.assertEqual(len(job.lines), MAX_LOG_LINES)
        self.assertEqual(job.lines[-1], f"baris {MAX_LOG_LINES + 9}")

    def test_stream_events_contains_log_state_and_end(self) -> None:
        manager = JobManager()
        job = manager.submit("demo", lambda log, cancel: (log("halo"), "ok")[1])
        self.assertTrue(wait_until(lambda: not job.running))
        frames = "".join(stream_events(job, 0, ping=0.05))

        self.assertIn("event: log", frames)
        self.assertIn("halo", frames)
        self.assertIn("event: state", frames)
        self.assertIn("event: end", frames)
        self.assertTrue(frames.endswith("\n\n"))

    def test_format_event_is_json(self) -> None:
        frame = format_event("log", {"line": "a b"})
        self.assertTrue(frame.startswith("event: log\ndata: "))
        self.assertIn('"line": "a b"', frame)


class JobEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        web = root / "web"
        web.mkdir()
        (web / "index.html").write_text("ok", encoding="utf-8")
        self.manager = JobManager()
        store = SettingsStore(root / "settings.json", registry_reader=lambda: {})
        self.app = create_app(
            settings_store=store, job_manager=self.manager, web_root=web
        )
        self.client = TestClient(self.app)

    def test_unknown_job_is_404(self) -> None:
        self.assertEqual(self.client.get("/api/jobs/tidak-ada").status_code, 404)

    def test_snapshot_and_stream(self) -> None:
        job = self.manager.submit("demo", lambda log, cancel: (log("satu"), 2)[1])
        self.assertTrue(wait_until(lambda: not job.running))

        snapshot = self.client.get(f"/api/jobs/{job.id}").json()
        self.assertEqual(snapshot["status"], "done")
        self.assertEqual(snapshot["result"], 2)

        stream = self.client.get(f"/api/jobs/{job.id}/stream")
        self.assertEqual(stream.status_code, 200)
        self.assertIn("text/event-stream", stream.headers["content-type"])
        self.assertIn("event: log", stream.text)
        self.assertIn("event: end", stream.text)

    def test_history_lists_jobs(self) -> None:
        job = self.manager.submit("demo", lambda log, cancel: 1)
        self.assertTrue(wait_until(lambda: not job.running))
        body = self.client.get("/api/jobs").json()
        self.assertEqual(body["jobs"][0]["id"], job.id)


if __name__ == "__main__":
    unittest.main()
