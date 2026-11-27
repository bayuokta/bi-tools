"""Penjaga akses server lokal: token sesi, Host, dan Origin.

Server hanya mendengarkan ``127.0.0.1``, tetapi itu saja tidak cukup: halaman
web lain di komputer yang sama bisa mengirim permintaan ke port lokal. Karena
itu setiap permintaan (kecuali ``/api/health``) wajib membawa cookie token yang
dibuat saat server dijalankan, dan ``Host``/``Origin`` harus menunjuk ke server
ini. Token tidak pernah ditulis ke log atau berkas preferensi.
"""

from __future__ import annotations

import json
import secrets
from http.cookies import SimpleCookie
from typing import Awaitable, Callable, Iterable, Sequence
from urllib.parse import parse_qs

COOKIE_NAME = "bi_tools_session"
TOKEN_PARAM = "t"
EXEMPT_PATHS = ("/api/health",)

Scope = dict
Message = dict
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def new_token() -> str:
    """Token acak per proses server (32 byte)."""
    return secrets.token_urlsafe(32)


def _header(scope: Scope, name: str) -> str:
    wanted = name.lower().encode("latin-1")
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return value.decode("latin-1")
    return ""


def _cookie_value(scope: Scope, name: str) -> str:
    raw = _header(scope, "cookie")
    if not raw:
        return ""
    jar = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # noqa: BLE001 - cookie rusak diperlakukan kosong
        return ""
    morsel = jar.get(name)
    return morsel.value if morsel else ""


def _query_token(scope: Scope) -> str:
    raw = scope.get("query_string", b"")
    if not raw:
        return ""
    try:
        values = parse_qs(raw.decode("latin-1"))
    except (UnicodeDecodeError, ValueError):
        return ""
    items = values.get(TOKEN_PARAM) or []
    return items[0] if items else ""


def _same_token(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return secrets.compare_digest(candidate, expected)


def _is_exempt(path: str) -> bool:
    return any(path == item or path.startswith(item + "/") for item in EXEMPT_PATHS)


async def _send_json(send: Send, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


MISSING_TOKEN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>BI Tools - unknown session</title>
<style>
body{font-family:"Segoe UI",sans-serif;background:#0e1116;color:#e9edf3;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
main{max-width:32rem;padding:2rem;border:1px solid #28303d;border-radius:8px;
background:#151a22}
h1{font-size:1.15rem;margin:0 0 .6rem}
p{line-height:1.55;margin:.4rem 0;color:#b9c2d0}
code{background:#10151c;border:1px solid #28303d;border-radius:4px;
padding:.1rem .35rem;color:#f2c811}
</style></head><body><main>
<h1>Unknown server session</h1>
<p>This page can only be opened through the link created by the application.</p>
<p>Start <code>BI Tools</code> again (or <code>python -m server</code> from
source), then use the link shown in the console window.</p>
<p>If the server is already running, close this tab and open the link from the console.</p>
</main></body></html>
"""


class LocalGuard:
    """Middleware ASGI murni: token cookie, validasi Host, dan Origin."""

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        *,
        allowed_hosts: Sequence[str] = (),
        allowed_origins: Sequence[str] = (),
        cookie_name: str = COOKIE_NAME,
    ) -> None:
        self.app = app
        self.token = token
        self.allowed_hosts = {item.lower() for item in allowed_hosts}
        self.allowed_origins = {item.lower() for item in allowed_origins}
        self.cookie_name = cookie_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if _is_exempt(path):
            await self.app(scope, receive, send)
            return

        host = _header(scope, "host").lower()
        if self.allowed_hosts and host not in self.allowed_hosts:
            await _send_json(
                send, 400, {"detail": "Unknown host for the local server."}
            )
            return

        if scope.get("method") in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = _header(scope, "origin").lower()
            if origin and self.allowed_origins and origin not in self.allowed_origins:
                await _send_json(send, 403, {"detail": "Origin permintaan ditolak."})
                return

        query_token = _query_token(scope)
        cookie_token = _cookie_value(scope, self.cookie_name)
        if not _same_token(cookie_token, self.token) and not _same_token(
            query_token, self.token
        ):
            if path in {"/", "/index.html"}:
                body = MISSING_TOKEN_HTML.encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"text/html; charset=utf-8"),
                            (b"content-length", str(len(body)).encode("ascii")),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            await _send_json(send, 401, {"detail": "Invalid session token."})
            return

        bootstrap = _same_token(query_token, self.token) and not _same_token(
            cookie_token, self.token
        )
        if bootstrap and path in {"/", "/index.html"}:
            # Token di URL hanya dipakai sekali; setelah cookie dipasang,
            # browser diarahkan ke alamat bersih agar token tidak tersimpan
            # di riwayat/Bookmark.
            await send(
                {
                    "type": "http.response.start",
                    "status": 303,
                    "headers": [
                        (b"location", b"/"),
                        (
                            b"set-cookie",
                            (
                                f"{self.cookie_name}={self.token}; Path=/; "
                                "HttpOnly; SameSite=Strict"
                            ).encode("latin-1"),
                        ),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        await self.app(scope, receive, send)


def allowed_for(port: int) -> tuple[list[str], list[str]]:
    """Daftar Host/Origin yang sah untuk port server."""
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}"]
    origins = [f"http://{item}" for item in hosts]
    return hosts, origins


def header_items(scope: Scope) -> Iterable[tuple[bytes, bytes]]:
    """Utilitas kecil untuk uji: header mentah dari scope ASGI."""
    return scope.get("headers", [])
