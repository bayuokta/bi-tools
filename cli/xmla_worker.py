"""Worker ADOMD di proses terpisah dengan message loop (Tk).

Server tidak membuka ADOMD untuk login interaktif karena dialog MSOLAP tidak
bisa dipompa dari thread job uvicorn. Worker ini meniru ``pbi_one_login``:
koneksi dibuka di main thread Tk, dialog muncul sekali, lalu server mengirim
query lewat JSON per baris.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import tkinter as tk
from typing import Any

from core.xmla_client import load_adomd, _clean, DMV_RE

IDLE_SECONDS = 600


class _Session:
    def __init__(self) -> None:
        self.connection: Any = None
        self.command_cls: Any = None
        self.catalog = ""
        self.server_version = ""

    def open(self, endpoint: str, catalog: str) -> dict[str, Any]:
        self.close()
        connection_cls, command_cls, _ = load_adomd()
        data_source = str(endpoint or "").strip()
        if not data_source or not str(catalog or "").strip():
            raise ValueError("Endpoint dan catalog wajib diisi.")
        connection_string = (
            "Provider=MSOLAP;"
            f"Data Source={data_source};"
            f"Catalog={catalog};"
            "Connect Timeout=60;"
        )
        connection = connection_cls(connection_string)
        connection.Open()
        self.connection = connection
        self.command_cls = command_cls
        self.catalog = str(catalog)
        self.server_version = str(getattr(connection, "ServerVersion", "") or "")
        return {
            "catalog": self.catalog,
            "server_version": self.server_version,
        }

    def close(self) -> None:
        connection = self.connection
        self.connection = None
        self.command_cls = None
        if connection is not None:
            try:
                connection.Close()
            except Exception:  # noqa: BLE001
                pass

    def query(self, sql: str, timeout: int | None = None) -> list[dict[str, Any]]:
        if self.connection is None or self.command_cls is None:
            raise RuntimeError("Koneksi XMLA belum dibuka.")
        command = self.command_cls(sql, self.connection)
        if timeout is not None:
            command.CommandTimeout = int(timeout)
        reader = command.ExecuteReader()
        try:
            names = [reader.GetName(index) for index in range(reader.FieldCount)]
            rows: list[dict[str, Any]] = []
            while reader.Read():
                rows.append(
                    {name: _clean(reader[index]) for index, name in enumerate(names)}
                )
            return rows
        finally:
            reader.Close()


def _respond(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True, default=str), flush=True)


def _handle(session: _Session, request: dict[str, Any], root: tk.Tk) -> None:
    op = str(request.get("op") or "").strip()
    try:
        if op == "open":
            root.deiconify()
            try:
                # Dialog MSOLAP bisa tertutup jendela lain; pastikan di depan.
                root.attributes("-topmost", True)
                root.lift()
                root.focus_force()
            except tk.TclError:
                pass
            root.update()
            try:
                result = session.open(
                    str(request.get("endpoint") or ""),
                    str(request.get("catalog") or ""),
                )
            finally:
                try:
                    root.attributes("-topmost", False)
                except tk.TclError:
                    pass
                root.withdraw()
            _respond({"ok": True, **result})
        elif op == "query":
            sql = str(request.get("query") or "")
            rows = session.query(sql, request.get("timeout"))
            _respond({"ok": True, "rows": rows})
        elif op == "dmv":
            name = str(request.get("dmv") or "")
            if not DMV_RE.match(name):
                raise ValueError(f"Nama DMV tidak valid: {name}")
            rows = session.query(f"SELECT * FROM $SYSTEM.{name}")
            _respond({"ok": True, "rows": rows})
        elif op == "ping":
            _respond({"ok": True})
        elif op == "close":
            session.close()
            _respond({"ok": True})
        else:
            raise ValueError(f"Operasi worker tidak dikenal: {op}")
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

    last_activity = {"time": time.monotonic()}

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
            last_activity["time"] = time.monotonic()
            _handle(session, request, root)
            if str(request.get("op") or "") == "close":
                root.after(10, root.destroy)
                return
        if time.monotonic() - last_activity["time"] > IDLE_SECONDS:
            session.close()
            root.destroy()
            return
        root.after(50, poll)

    def shutdown() -> None:
        session.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", shutdown)
    root.after(50, poll)
    try:
        root.mainloop()
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
