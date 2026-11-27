"""Client server untuk worker TOM interaktif (proses Tk terpisah)."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any

from .errors import ExtractionError
from .paths import APP_DIR, cli_argv


class TomWorkerClient:
    def __init__(self, endpoint: str, catalog: str) -> None:
        self.endpoint = endpoint
        self.catalog = catalog
        self._lock = threading.RLock()
        self._lines: "queue.Queue[str | None]" = queue.Queue()
        self._stderr: list[str] = []
        self._process = subprocess.Popen(
            cli_argv(["tom-worker"]),
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
            self._request(
                {"op": "open", "endpoint": endpoint, "catalog": catalog},
                timeout=900,
            )
        except Exception:
            self.terminate()
            raise

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

    def _request(self, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        with self._lock:
            if self._process.poll() is not None:
                raise ExtractionError(
                    "The TOM worker stopped. "
                    + (self._stderr[-1] if self._stderr else "No details.")
                )
            assert self._process.stdin is not None
            try:
                self._process.stdin.write(json.dumps(payload) + "\n")
                self._process.stdin.flush()
            except OSError as exc:
                raise ExtractionError(f"The TOM worker could not be written to: {exc}") from exc
            deadline = time.monotonic() + float(timeout)
            response: dict[str, Any] | None = None
            while response is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ExtractionError(
                        "The TOM worker did not respond in time."
                    )
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty as exc:
                    raise ExtractionError(
                        "The TOM worker did not respond in time."
                    ) from exc
                if line is None:
                    raise ExtractionError(
                        "The TOM worker stopped. "
                        + (self._stderr[-1] if self._stderr else "No details.")
                    )
                try:
                    value = json.loads(line)
                except ValueError:
                    self._stderr.append(line.strip())
                    continue
                if isinstance(value, dict):
                    response = value
            if not response.get("ok"):
                raise ExtractionError(str(response.get("error") or "The TOM worker failed."))
            return response

    def inventory(self) -> list[dict[str, Any]]:
        response = self._request({"op": "inventory"}, timeout=300)
        rows = response.get("partitions")
        return rows if isinstance(rows, list) else []

    def refresh(
        self, targets: list[dict[str, str]], refresh_type: str
    ) -> list[dict[str, Any]]:
        response = self._request(
            {"op": "refresh", "targets": targets, "refresh_type": refresh_type},
            timeout=1800,
        )
        rows = response.get("partitions")
        return rows if isinstance(rows, list) else []

    def export(self, target: str) -> dict[str, Any]:
        """Ekspor definisi model (TMDL + TMSL) ke folder ``target``."""
        response = self._request({"op": "export", "target": str(target)}, timeout=1800)
        return {
            "files": int(response.get("files") or 0),
            "bytes": int(response.get("bytes") or 0),
            "catalog": str(response.get("catalog") or self.catalog),
        }

    def snapshot(self, options: dict[str, Any]) -> dict[str, Any]:
        response = self._request(
            {"op": "snapshot", "options": options}, timeout=600
        )
        value = response.get("snapshot")
        try:
            data = json.loads(value) if isinstance(value, str) else value
        except ValueError as exc:
            raise ExtractionError(f"Invalid TOM snapshot: {exc}") from exc
        if not isinstance(data, dict):
            raise ExtractionError("The TOM snapshot contains no comparable objects.")
        return data

    def close(self) -> None:
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


_WORKERS: dict[tuple[str, str], TomWorkerClient] = {}
_LOCK = threading.RLock()


def get_tom_worker(endpoint: str, catalog: str) -> TomWorkerClient:
    key = (str(endpoint), str(catalog))
    with _LOCK:
        worker = _WORKERS.get(key)
        if worker is not None:
            process = getattr(worker, "_process", None)
            if process is not None and process.poll() is None:
                return worker
            worker.terminate()
            _WORKERS.pop(key, None)
        worker = TomWorkerClient(str(endpoint), str(catalog))
        _WORKERS[key] = worker
        return worker


def stop_workers() -> None:
    with _LOCK:
        for worker in _WORKERS.values():
            worker.terminate()
        _WORKERS.clear()
