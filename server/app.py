"""Pabrik aplikasi FastAPI untuk antarmuka web BI Tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Sequence

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from core.errors import ExtractionError
from core.version import APP_NAME, __version__

from .api import (
    analysis,
    backup,
    catalog,
    compare,
    files,
    jobs,
    lineage,
    metadata,
    partitions,
    settings,
    system,
    tsd,
)
from .config import web_dir
from .jobs import JobManager, JobNotFound
from .security import LocalGuard
from .settings_store import SettingsError, SettingsStore

ROUTERS = (
    system.router,
    settings.router,
    catalog.router,
    backup.router,
    metadata.router,
    tsd.router,
    analysis.router,
    compare.router,
    lineage.router,
    partitions.router,
    files.router,
    jobs.router,
)


class NoCacheStatic:
    """Bungkus mount statis agar browser tidak memakai aset basi.

    Starlette hanya mengirim ``ETag``/``Last-Modified``. Tanpa
    ``Cache-Control`` Chrome memakai heuristic caching sehingga file lama bisa
    dipakai berhari-hari setelah aplikasi diperbarui. Hanya respons mount
    statis yang diubah; endpoint ``/api/*`` tidak disentuh.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_no_cache(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", b"no-store"))
                message = dict(message, headers=headers)
            await send(message)

        await self.app(scope, receive, send_no_cache)


def create_app(
    *,
    settings_store: SettingsStore | None = None,
    job_manager: JobManager | None = None,
    token: str = "",
    allowed_hosts: Sequence[str] = (),
    allowed_origins: Sequence[str] = (),
    shutdown: Callable[[], None] | None = None,
    web_root: Path | str | None = None,
) -> FastAPI:
    """Bangun aplikasi; parameter eksplisit dipakai uji tanpa jaringan."""
    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings_store or SettingsStore()
    app.state.jobs = job_manager or JobManager()
    app.state.shutdown = shutdown
    app.state.web_root = Path(web_root) if web_root else web_dir()

    for router in ROUTERS:
        app.include_router(router)

    @app.exception_handler(ExtractionError)
    async def _extraction_error(_request: Request, exc: ExtractionError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(SettingsError)
    async def _settings_error(_request: Request, exc: SettingsError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(JobNotFound)
    async def _job_missing(_request: Request, exc: JobNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Job tidak ditemukan: {exc.args[0] if exc.args else ''}"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    if app.state.web_root.is_dir():
        app.mount(
            "/",
            NoCacheStatic(StaticFiles(directory=str(app.state.web_root), html=True)),
            name="web",
        )
    else:

        @app.get("/", include_in_schema=False)
        def missing_ui() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": f"Aset web tidak ditemukan: {app.state.web_root}",
                },
            )

    if token:
        app.add_middleware(
            LocalGuard,
            token=token,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )

    return app
