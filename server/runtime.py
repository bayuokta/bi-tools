"""Menjalankan server lokal: satu instance, port, token, dan browser.

Alur: pastikan hanya satu server, pilih port, buat token, tulis penanda di
``data\\server.json``, jalankan uvicorn di thread utama (agar Ctrl+C bekerja),
lalu buka browser dari thread pembantu setelah ``/api/health`` menjawab.
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any

from core.version import APP_NAME, __version__

from .config import DEFAULT_HOST, DEFAULT_PORT, PORT_ATTEMPTS, state_file
from .jobs import JobManager
from .security import allowed_for, new_token
from .settings_store import SettingsStore, default_path

HEALTH_TIMEOUT = 0.6
START_TIMEOUT = 20.0


class InstanceLock:
    """Mutex bernama Windows agar dua server tidak berjalan bersamaan."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str = "Local\\BIToolsWebServer") -> None:
        self.name = name
        self._handle: Any = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            return True
        if ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle is None or os.name != "nt":
            return
        ctypes.WinDLL("kernel32").CloseHandle(self._handle)
        self._handle = None


def _health(port: int, timeout: float = HEALTH_TIMEOUT) -> dict[str, Any] | None:
    url = f"http://{DEFAULT_HOST}:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def read_state() -> dict[str, Any] | None:
    path = state_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_state(*, port: int, token: str) -> dict[str, Any]:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "port": port,
        "token": token,
        "url": f"http://{DEFAULT_HOST}:{port}/",
        "version": __version__,
        "started": datetime.now().isoformat(timespec="seconds"),
    }
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return payload


def clear_state() -> None:
    path = state_file()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return


def find_running() -> dict[str, Any] | None:
    """Server lain yang masih sehat (dibaca dari penanda + /api/health)."""
    entry = read_state()
    if not entry:
        return None
    try:
        port = int(entry.get("port") or 0)
    except (TypeError, ValueError):
        return None
    if port <= 0:
        return None
    if _health(port) is None:
        return None
    token = str(entry.get("token") or "")
    if not token:
        return None
    entry["port"] = port
    entry["token_url"] = f"http://{DEFAULT_HOST}:{port}/?t={token}"
    return entry


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((DEFAULT_HOST, port))
        except OSError:
            return False
    return True


def choose_port(preferred: int = DEFAULT_PORT, attempts: int = PORT_ATTEMPTS) -> int:
    for port in range(preferred, preferred + max(1, attempts)):
        if _port_free(port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((DEFAULT_HOST, 0))
        return int(sock.getsockname()[1])


def _wait_for_server(port: int, timeout: float = START_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _health(port) is not None:
            return True
        time.sleep(0.25)
    return False


def _open_when_ready(port: int, token_url: str, timeout: float = START_TIMEOUT) -> None:
    if not _wait_for_server(port, timeout):
        print(
            "Server belum menjawab; buka manual tautan di atas setelah siap.",
            flush=True,
        )
        return
    try:
        webbrowser.open(token_url)
    except Exception:  # noqa: BLE001 - browser opsional
        print("Tidak bisa membuka browser otomatis; buka tautan di atas.", flush=True)


def _banner(port: int, token_url: str, settings_path: Path) -> None:
    line = "=" * 64
    print(line, flush=True)
    print(f"{APP_NAME} {__version__} - antarmuka web lokal", flush=True)
    print(line, flush=True)
    print(f"Alamat     : http://{DEFAULT_HOST}:{port}/", flush=True)
    print(f"Tautan sesi: {token_url}", flush=True)
    print(f"Preferensi : {settings_path}", flush=True)
    print("Tekan Ctrl+C untuk menghentikan server.", flush=True)
    print(line, flush=True)


def run(
    port: int | None = None,
    *,
    open_browser: bool = True,
    settings_path: Path | str | None = None,
    web_root: Path | str | None = None,
) -> int:
    """Jalankan server; kembalikan kode keluar untuk ``__main__``."""
    lock = InstanceLock()
    if not lock.acquire():
        entry = find_running()
        if entry is None:
            entry = _wait_for_state()
        if entry is None:
            print(
                "Server sudah berjalan tetapi tautannya belum tersedia. "
                "Tutup jendela konsol server lama atau periksa Task Manager.",
                flush=True,
            )
            return 1
        print(f"{APP_NAME} sudah berjalan di {entry['url']}", flush=True)
        print(f"Tautan sesi: {entry['token_url']}", flush=True)
        if open_browser:
            webbrowser.open(entry["token_url"])
        return 0

    wrote_state = False
    try:
        existing = find_running()
        if existing is not None:
            print(f"{APP_NAME} sudah berjalan di {existing['url']}", flush=True)
            print(f"Tautan sesi: {existing['token_url']}", flush=True)
            if open_browser:
                webbrowser.open(existing["token_url"])
            return 0

        store = SettingsStore(settings_path)
        store.reset_session()
        store.set_auth_mode("user")
        if store.shared_db_source() and store.shared_db_auto():
            from .shared_db import download_snapshot

            try:
                download_snapshot(store)
            except Exception as exc:  # noqa: BLE001 - snapshot opsional saat start
                print(f"Snapshot database bersama tidak bisa dimuat: {exc}")
        chosen = choose_port(int(port) if port else DEFAULT_PORT)
        token = new_token()
        hosts, origins = allowed_for(chosen)

        from .app import create_app

        manager = JobManager()
        app = create_app(
            settings_store=store,
            job_manager=manager,
            token=token,
            allowed_hosts=hosts,
            allowed_origins=origins,
            web_root=web_root,
        )

        import uvicorn

        config = uvicorn.Config(
            app,
            host=DEFAULT_HOST,
            port=chosen,
            log_level="warning",
            log_config=None,
            access_log=False,
        )
        server = uvicorn.Server(config)
        app.state.shutdown = lambda: setattr(server, "should_exit", True)

        write_state(port=chosen, token=token)
        wrote_state = True
        token_url = f"http://{DEFAULT_HOST}:{chosen}/?t={token}"
        _banner(chosen, token_url, store.path)
        if open_browser:
            threading.Thread(
                target=_open_when_ready,
                args=(chosen, token_url),
                name="bi-tools-open-browser",
                daemon=True,
            ).start()
        try:
            server.run()
        except KeyboardInterrupt:  # pragma: no cover - ditangani uvicorn
            pass
        except Exception as exc:  # noqa: BLE001 - tampilkan pesan ke konsol
            print(f"Server gagal dijalankan: {exc}", flush=True)
            return 1
        print("Server berhenti.", flush=True)
        return 0
    finally:
        try:
            from core.tom_worker_client import stop_workers as stop_tom_workers
            from core.xmla_worker_client import stop_workers as stop_xmla_workers

            stop_xmla_workers()
            stop_tom_workers()
        except Exception:  # noqa: BLE001 - shutdown tetap harus lanjut
            pass
        if wrote_state:
            clear_state()
        lock.release()


def _wait_for_state(timeout: float = START_TIMEOUT) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        entry = find_running()
        if entry is not None:
            return entry
        time.sleep(0.25)
    return None


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m server",
        description="Server lokal antarmuka web BI Tools (127.0.0.1).",
    )
    parser.add_argument("--port", type=int, default=None, help="port yang dipakai")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="jangan buka browser otomatis",
    )
    parser.add_argument(
        "--settings",
        default=None,
        help=f"berkas preferensi JSON (default: {default_path()})",
    )
    parser.add_argument(
        "--web-root",
        default=None,
        help="folder aset web (default: web di folder aplikasi)",
    )
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    return run(
        port=args.port,
        open_browser=not args.no_browser,
        settings_path=args.settings,
        web_root=args.web_root,
    )
