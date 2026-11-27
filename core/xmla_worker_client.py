"""Client server untuk worker ADOMD interaktif (proses Tk + message loop)."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any, Callable

from .paths import APP_DIR, cli_argv
from .xmla_client import DMV_RE, XmlaError

# Login MSOLAP tidak punya timeout sendiri; batasi agar job tidak menggantung.
OPEN_TIMEOUT_SECONDS = 300.0
LOGIN_WAIT_MESSAGE = (
    "Waiting for XMLA login: complete the 'BI Tools - XMLA login' window..."
)
LOGIN_DONE_MESSAGE = "XMLA login completed."


def open_timeout_message(seconds: float) -> str:
    return (
        f"XMLA login did not complete within {int(seconds)} detik. "
        "Ulangi analisa lalu selesaikan jendela 'BI Tools - XMLA login'."
    )



class WorkerXmlaClient:
    """Antarmuka mirip :class:`core.xmla_client.XmlaClient` lewat IPC JSON."""

    def __init__(self, endpoint: str, catalog: str) -> None:
        self.endpoint = endpoint
        self.catalog = catalog
        self.connection = None
        self.command_cls = None
        self.catalog_info: dict[str, Any] = {}
        self.server_version = ""
        self.connection_string = ""
        self._lock = threading.RLock()
        self._lines: "queue.Queue[str | None]" = queue.Queue()
        self._stderr: list[str] = []
        command = cli_argv(["xmla-worker"])
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(APP_DIR),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        try:
            response = self._request(
                {"op": "open", "endpoint": endpoint, "catalog": catalog},
                timeout=OPEN_TIMEOUT_SECONDS,
                timeout_message=open_timeout_message(OPEN_TIMEOUT_SECONDS),
            )
        except Exception:
            self.terminate()
            raise
        self.server_version = str(response.get("server_version") or "")
        self.connection_string = f"Data Source={endpoint};Initial Catalog={catalog}"

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            text = line.rstrip()
            if text:
                self._stderr.append(text)
                if len(self._stderr) > 80:
                    del self._stderr[:20]

    def _request(
        self,
        payload: dict[str, Any],
        *,
        timeout: float,
        timeout_message: str = "",
    ) -> dict[str, Any]:
        message = timeout_message or (
            "The XMLA worker did not respond in time. "
            "Complete the login dialog that appears."
        )
        with self._lock:
            if self._process.poll() is not None:
                raise XmlaError(
                    "The XMLA worker stopped. "
                    + (self._stderr[-1] if self._stderr else "No details.")
                )
            assert self._process.stdin is not None
            try:
                self._process.stdin.write(json.dumps(payload) + "\n")
                self._process.stdin.flush()
            except OSError as exc:
                raise XmlaError(f"The XMLA worker could not be written to: {exc}") from exc
            deadline = time.monotonic() + float(timeout)
            response: dict[str, Any] | None = None
            while response is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise XmlaError(message)
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty as exc:
                    raise XmlaError(message) from exc
                if line is None:
                    raise XmlaError(
                        "The XMLA worker stopped. "
                        + (self._stderr[-1] if self._stderr else "No details.")
                    )
                try:
                    value = json.loads(line)
                except ValueError:
                    # Baris non-JSON (mis. peringatan pythonnet) diabaikan.
                    self._stderr.append(line.strip())
                    continue
                if not isinstance(value, dict):
                    self._stderr.append(line.strip())
                    continue
                response = value
            if not isinstance(response, dict) or not response.get("ok"):
                error = response.get("error") if isinstance(response, dict) else ""
                raise XmlaError(str(error or "The XMLA worker failed."))
            return response

    def query_sql(self, sql: str, timeout: int | None = None) -> list[dict[str, Any]]:
        response = self._request(
            {"op": "query", "query": sql, "timeout": timeout},
            timeout=max(120, int(timeout or 120) + 30),
        )
        rows = response.get("rows")
        return rows if isinstance(rows, list) else []

    def query(self, dmv: str) -> list[dict[str, Any]]:
        if not DMV_RE.match(dmv):
            raise XmlaError(f"Invalid DMV name: {dmv}")
        response = self._request({"op": "dmv", "dmv": dmv}, timeout=180)
        rows = response.get("rows")
        return rows if isinstance(rows, list) else []

    def close(self) -> None:
        # Worker dipakai ulang untuk dataset yang sama selama server hidup.
        return None

    def terminate(self) -> None:
        process = getattr(self, "_process", None)
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            process.terminate()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "WorkerXmlaClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()


_WORKERS: dict[tuple[str, str], WorkerXmlaClient] = {}
_WORKERS_LOCK = threading.RLock()


def get_worker_client(
    endpoint: str, catalog: str, *, log: Callable[[str], None] | None = None
) -> WorkerXmlaClient:
    key = (str(endpoint), str(catalog))
    with _WORKERS_LOCK:
        worker = _WORKERS.get(key)
        if worker is not None:
            process = getattr(worker, "_process", None)
            if process is not None and process.poll() is None:
                return worker
            worker.terminate()
            _WORKERS.pop(key, None)
        if log is not None:
            log(LOGIN_WAIT_MESSAGE)
        try:
            worker = WorkerXmlaClient(str(endpoint), str(catalog))
        except Exception:
            if log is not None:
                log("XMLA login failed.")
            raise
        _WORKERS[key] = worker
        if log is not None:
            log(LOGIN_DONE_MESSAGE)
        return worker


def stop_workers() -> None:
    with _WORKERS_LOCK:
        for worker in _WORKERS.values():
            worker.terminate()
        _WORKERS.clear()
