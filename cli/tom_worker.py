"""Worker TOM di proses terpisah dengan Tk message loop (login MSOLAP)."""

from __future__ import annotations

import json
import queue
import sys
import threading
import tkinter as tk
from typing import Any

from core.partition_plan import build_refresh_tmsl, partition_payload
from core.tom_client import (
    TomError,
    execute_refresh,
    list_partitions,
    load_tom,
)
from core.tom_compare import serialize_snapshot


class _Session:
    def __init__(self) -> None:
        self.server: Any = None
        self.catalog = ""

    def open(self, endpoint: str, catalog: str) -> dict[str, Any]:
        self.close()
        server_cls, _token, _offset = load_tom()
        data_source = str(endpoint or "").strip()
        name = str(catalog or "").strip()
        if not data_source or not name:
            raise ValueError("Endpoint dan catalog wajib diisi.")
        variants = (
            "Interactive Login=Enabled; Identity Mode=Connection;",
            "Interactive Login=Always; Identity Mode=Connection;",
            "",
        )
        errors: list[str] = []
        for props in variants:
            server = server_cls()
            connection = (
                "Provider=MSOLAP;"
                f"Data Source={data_source};"
                f"Initial Catalog={name};"
                "Connect Timeout=60;"
                f"{props}"
            )
            try:
                server.Connect(connection)
            except Exception as exc:  # noqa: BLE001 - coba variasi berikutnya
                errors.append(str(exc))
                try:
                    server.Dispose()
                except Exception:  # noqa: BLE001
                    pass
                continue
            self.server = server
            self.catalog = name
            return {"catalog": name}
        raise TomError("Koneksi TOM gagal: " + " | ".join(errors[:2]))

    def close(self) -> None:
        server = self.server
        self.server = None
        if server is not None:
            try:
                server.Dispose()
            except Exception:  # noqa: BLE001
                pass

    def inventory(self) -> list[dict[str, Any]]:
        if self.server is None:
            raise TomError("Koneksi TOM belum dibuka.")
        return partition_payload(list_partitions(self.server, self.catalog))

    def refresh(
        self, targets: list[dict[str, Any]], refresh_type: str
    ) -> list[dict[str, Any]]:
        if self.server is None:
            raise TomError("Koneksi TOM belum dibuka.")
        pairs = [
            (str(item.get("table") or ""), str(item.get("partition") or ""))
            for item in targets
            if isinstance(item, dict)
        ]
        tmsl = build_refresh_tmsl(self.catalog, pairs, refresh_type)
        execute_refresh(self.server, tmsl)
        return partition_payload(list_partitions(self.server, self.catalog))

    def snapshot(self, options: dict[str, Any]) -> str:
        if self.server is None:
            raise TomError("Koneksi TOM belum dibuka.")
        return serialize_snapshot(self.server, self.catalog, options)


def _respond(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True, default=str), flush=True)


def _handle(session: _Session, request: dict[str, Any]) -> None:
    op = str(request.get("op") or "").strip()
    try:
        if op == "open":
            _respond(
                {
                    "ok": True,
                    **session.open(
                        str(request.get("endpoint") or ""),
                        str(request.get("catalog") or ""),
                    ),
                }
            )
        elif op == "inventory":
            _respond({"ok": True, "partitions": session.inventory()})
        elif op == "refresh":
            rows = session.refresh(
                list(request.get("targets") or []),
                str(request.get("refresh_type") or "full"),
            )
            _respond({"ok": True, "partitions": rows})
        elif op == "snapshot":
            _respond(
                {
                    "ok": True,
                    "snapshot": session.snapshot(dict(request.get("options") or {})),
                }
            )
        elif op == "ping":
            _respond({"ok": True})
        elif op == "close":
            session.close()
            _respond({"ok": True})
        else:
            raise ValueError(f"Operasi worker TOM tidak dikenal: {op}")
    except Exception as exc:  # noqa: BLE001 - diteruskan ke server
        _respond({"ok": False, "error": str(exc)})


def main(argv: list[str] | None = None) -> int:
    session = _Session()
    requests: "queue.Queue[dict[str, Any] | None]" = queue.Queue()

    def read_stdin() -> None:
        for line in sys.stdin:
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                requests.put(value)
        requests.put(None)

    threading.Thread(target=read_stdin, daemon=True).start()
    root = tk.Tk()
    root.title("BI Tools - XMLA login")
    root.geometry("360x100+80+80")
    tk.Label(
        root,
        text="Selesaikan login XMLA di jendela yang muncul.\n"
        "Jendela ini boleh diminimalkan setelah selesai.",
        justify="center",
    ).pack(padx=12, pady=12)
    root.update()

    def poll() -> None:
        while True:
            try:
                request = requests.get_nowait()
            except queue.Empty:
                break
            if request is None:
                session.close()
                root.destroy()
                return
            _handle(session, request)
            if str(request.get("op") or "") == "close":
                root.after(10, root.destroy)
                return
        root.after(50, poll)

    root.protocol("WM_DELETE_WINDOW", lambda: (session.close(), root.destroy()))
    root.after(50, poll)
    try:
        root.mainloop()
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
