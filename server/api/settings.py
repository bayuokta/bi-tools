"""Endpoint preferensi, kredensial, dan tes token."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from .. import settings as keys
from ..presenters import settings as presenter
from . import settings_of, submit_job

router = APIRouter(prefix="/api/settings", tags=["settings"])


class CredentialsIn(BaseModel):
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str | None = Field(default=None)


class RlsIn(BaseModel):
    username: str = ""
    roles: Any = Field(default="")


class PathsIn(BaseModel):
    lineage_db: str = ""


class CatalogIn(BaseModel):
    mode: str = "auto"
    include_personal: bool = False


class UiIn(BaseModel):
    theme: str | None = None
    motion: bool | None = None
    show_console: bool | None = None
    language: str | None = None


class ExtractionIn(BaseModel):
    scope_local: str | None = None
    scope_service: str | None = None
    active_tab: str | None = None
    out_dir: str | None = None


class SharedDbIn(BaseModel):
    source: str = ""
    auto_download: bool = True


class TenantIn(BaseModel):
    tenant_id: str = ""


@router.post("/sign-in")
def sign_in(request: Request) -> dict[str, Any]:
    from ..auth_state import sign_in as _sign_in

    store = settings_of(request)
    _sign_in(store)
    return presenter.build_state(store)


@router.post("/sign-out")
def sign_out(request: Request) -> dict[str, Any]:
    from ..auth_state import sign_out as _sign_out

    store = settings_of(request)
    _sign_out(store)
    return presenter.build_state(store)


@router.put("/tenant")
def save_tenant(payload: TenantIn, request: Request) -> dict[str, Any]:
    store = settings_of(request)
    store.set(keys.AUTH_TENANT_KEY, payload.tenant_id.strip())
    return presenter.build_state(store)


@router.put("/shared-db")
def save_shared_db(payload: SharedDbIn, request: Request) -> dict[str, Any]:
    return presenter.save_shared_db(
        settings_of(request), payload.source, payload.auto_download
    )


@router.post("/snapshot/download")
def download_snapshot(request: Request) -> dict[str, Any]:
    return presenter.download_shared_db(settings_of(request))


@router.get("")
def read_settings(request: Request) -> dict[str, Any]:
    return presenter.build_state(settings_of(request))


@router.put("/credentials")
def save_credentials(payload: CredentialsIn, request: Request) -> dict[str, Any]:
    return presenter.save_credentials(
        settings_of(request),
        payload.tenant_id,
        payload.client_id,
        payload.client_secret,
    )


@router.put("/rls")
def save_rls(payload: RlsIn, request: Request) -> dict[str, Any]:
    return presenter.save_rls(settings_of(request), payload.username, payload.roles)


@router.put("/paths")
def save_paths(payload: PathsIn, request: Request) -> dict[str, Any]:
    return presenter.save_paths(settings_of(request), payload.lineage_db)


@router.put("/catalog")
def save_catalog(payload: CatalogIn, request: Request) -> dict[str, Any]:
    return presenter.save_catalog(
        settings_of(request), payload.mode, payload.include_personal
    )


@router.put("/ui")
def save_ui(payload: UiIn, request: Request) -> dict[str, Any]:
    return presenter.save_ui(
        settings_of(request),
        payload.theme,
        payload.motion,
        payload.show_console,
        payload.language,
    )


@router.put("/extraction")
def save_extraction(payload: ExtractionIn, request: Request) -> dict[str, Any]:
    return presenter.save_extraction(
        settings_of(request),
        scope_local=payload.scope_local,
        scope_service=payload.scope_service,
        active_tab=payload.active_tab,
        out_dir=payload.out_dir,
    )


@router.post("/test-token", status_code=202)
def test_token(request: Request) -> dict[str, Any]:
    store = settings_of(request)
    return submit_job(
        request,
        "test_token",
        "Tes koneksi Power BI",
        lambda log, cancel: presenter.test_token_job(store, log, cancel),
    )
