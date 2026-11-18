"""Antrean pekerjaan server dengan log live.

Pekerjaan ``core`` berjalan sinkron dan memakai callback ``log``. Server web
menjalankannya di satu thread pekerja (satu pekerjaan pada satu waktu) lalu
menyiarkan baris log ke browser lewat SSE.
Setiap job menyimpan riwayat log di memori supaya refresh halaman atau
koneksi SSE yang terputus tidak kehilangan progres.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

MAX_LOG_LINES = 5000
KEEP_JOBS = 20
EventLog = Callable[[str], None]
CancelCheck = Callable[[], bool]


class BusyError(RuntimeError):
    """Sudah ada pekerjaan yang berjalan."""

    def __init__(self, job: "Job") -> None:
        super().__init__(
            f"Pekerjaan lain masih berjalan: {job.label or job.kind}. "
            "Tunggu sampai selesai."
        )
        self.job = job


class JobNotFound(KeyError):
    """ID job tidak dikenal (mis. server baru dijalankan ulang)."""


def _json_ready(value: Any) -> Any:
    """Ubah hasil job menjadi struktur yang aman untuk JSON."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "__fspath__"):
        return str(value)
    return str(value)


@dataclass
class Job:
    """Satu pekerjaan beserta riwayat log dan hasil akhirnya."""

    id: str
    kind: str
    label: str = ""
    status: str = "running"
    lines: list[str] = field(default_factory=list)
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)

    def log(self, message: str) -> None:
        """Callback log yang diteruskan ke ``core``."""
        text = str(message)
        with self.condition:
            self.lines.append(text)
            if len(self.lines) > MAX_LOG_LINES:
                del self.lines[: len(self.lines) - MAX_LOG_LINES]
            self.condition.notify_all()

    @property
    def running(self) -> bool:
        return self.status == "running"

    @property
    def cancelled(self) -> bool:
        return self.cancel_requested.is_set()

    def finish(self, *, status: str, result: Any = None, error: str = "") -> None:
        with self.condition:
            self.status = status
            self.result = _json_ready(result)
            self.error = error
            self.finished_at = time.time()
            self.condition.notify_all()

    def snapshot(self, *, include_log: bool = True) -> dict[str, Any]:
        with self.condition:
            finished = self.finished_at or time.time()
            payload = {
                "id": self.id,
                "kind": self.kind,
                "label": self.label,
                "status": self.status,
                "error": self.error,
                "result": self.result,
                "created_at": self.created_at,
                "finished_at": self.finished_at,
                "duration": round(finished - self.created_at, 1),
                "line_count": len(self.lines),
                "cancel_requested": self.cancel_requested.is_set(),
            }
            if include_log:
                payload["log"] = list(self.lines)
            return payload


def format_event(event: str, payload: Any) -> str:
    """Satu bingkai SSE."""
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def stream_events(job: Job, start: int = 0, *, ping: float = 15.0) -> Iterator[str]:
    """Generator SSE: log baru, lalu state akhir dan ``end``."""
    index = max(0, int(start))
    while True:
        with job.condition:
            lines = job.lines[index:]
            index += len(lines)
            finished = not job.running
            if not lines and not finished:
                job.condition.wait(ping)
                lines = job.lines[index:]
                index += len(lines)
                finished = not job.running
        for offset, line in enumerate(lines):
            yield format_event(
                "log", {"index": index - len(lines) + offset, "line": line}
            )
        if finished:
            yield format_event("state", job.snapshot())
            yield format_event("end", {"status": job.status})
            return
        if not lines:
            yield ": ping\n\n"


class JobManager:
    """Pemilik thread pekerja dan riwayat job (satu job berjalan)."""

    def __init__(self, *, keep: int = KEEP_JOBS) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._current: Job | None = None
        self._keep = max(1, int(keep))

    @property
    def current(self) -> Job | None:
        with self._lock:
            job = self._current
            return job if job is not None and job.running else None

    def submit(
        self,
        kind: str,
        func: Callable[[EventLog, threading.Event], Any],
        *,
        label: str = "",
    ) -> Job:
        """Jalankan ``func(log, cancel)`` di thread baru; tolak bila sibuk."""
        with self._lock:
            active = self._current
            if active is not None and active.running:
                raise BusyError(active)
            job = Job(
                id=uuid.uuid4().hex[:12],
                kind=kind,
                label=label or kind,
            )
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._current = job
            self._trim()
        thread = threading.Thread(
            target=self._run,
            args=(job, func),
            name=f"bi-tools-{kind}",
            daemon=True,
        )
        thread.start()
        return job

    def _run(
        self,
        job: Job,
        func: Callable[[EventLog, threading.Event], Any],
    ) -> None:
        try:
            result = func(job.log, job.cancel_requested)
        except BaseException as exc:  # noqa: BLE001 - dilaporkan ke browser
            status = "cancelled" if job.cancelled else "error"
            message = str(exc) or exc.__class__.__name__
            job.finish(status=status, error=message)
        else:
            status = "cancelled" if job.cancelled else "done"
            job.finish(status=status, result=result)

    def _trim(self) -> None:
        finished = [
            item
            for item in self._order
            if item != (self._current.id if self._current else "")
            and not self._jobs[item].running
        ]
        for job_id in finished[: max(0, len(finished) - self._keep)]:
            self._order.remove(job_id)
            self._jobs.pop(job_id, None)

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def snapshot(self, job_id: str, *, include_log: bool = True) -> dict[str, Any]:
        return self.get(job_id).snapshot(include_log=include_log)

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        if job.running:
            job.cancel_requested.set()
            job.log("Permintaan berhenti dikirim; menunggu langkah yang berjalan.")
        return job.snapshot(include_log=False)

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            ordered = list(reversed(self._order))
        return [self._jobs[job_id].snapshot(include_log=False) for job_id in ordered]
