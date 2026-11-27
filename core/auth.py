"""Kredensial Microsoft Entra yang dipakai bersama oleh semua jalur.

Satu :class:`ServicePrincipal` dipakai untuk:

- Fabric REST API          -> :data:`FABRIC_SCOPE`
- Power BI REST API        -> :data:`POWERBI_SCOPE`
- XMLA endpoint (ADOMD/DMV)-> :data:`POWERBI_SCOPE` (token yang sama)
- TOM (bila dipakai nanti)-> :data:`POWERBI_SCOPE`

Token hanya disimpan di memori proses. Modul ini sengaja tidak mengimpor
pythonnet/.NET: CLI report dan lineage harus tetap jalan tanpa .NET. Objek
token .NET dibangun di :mod:`core.xmla_client` dengan token dari sini.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

import msal
from dotenv import load_dotenv

from .errors import ExtractionError
from .pbix import ROOT

FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"
POWERBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
TOKEN_MARGIN_SECONDS = 120
DEFAULT_ENV_FILE = ROOT / ".env"


class TokenProvider(Protocol):
    """Sumber access token yang masih berlaku (dipakai client REST)."""

    def get_token(self) -> str:
        """Kembalikan access token; ambil token baru bila sudah kedaluwarsa."""


@dataclass(frozen=True)
class ServicePrincipal:
    """Kredensial service principal (aplikasi Microsoft Entra)."""

    tenant_id: str
    client_id: str
    client_secret: str

    @classmethod
    def from_values(
        cls,
        tenant_id: str,
        client_id: str,
        client_secret: str,
    ) -> "ServicePrincipal":
        return cls(
            tenant_id=(tenant_id or "").strip(),
            client_id=(client_id or "").strip(),
            client_secret=(client_secret or "").strip(),
        )

    @classmethod
    def from_env(cls, env_file: Path | str | None = None) -> "ServicePrincipal":
        """Baca kredensial dari environment, dengan fallback file .env.

        ``load_dotenv`` tidak menimpa variabel environment yang sudah ada, sehingga
        nilai dari shell tetap diprioritaskan.
        """
        path = Path(env_file).expanduser() if env_file else DEFAULT_ENV_FILE
        if path.exists():
            load_dotenv(path, override=False)
        return cls.from_values(
            os.getenv("TENANT_ID", ""),
            os.getenv("CLIENT_ID", ""),
            os.getenv("CLIENT_SECRET", ""),
        )

    @property
    def missing(self) -> list[str]:
        values = (
            ("TENANT_ID", self.tenant_id),
            ("CLIENT_ID", self.client_id),
            ("CLIENT_SECRET", self.client_secret),
        )
        return [name for name, value in values if not value]

    @property
    def is_complete(self) -> bool:
        return not self.missing

    def validate(self) -> None:
        if self.missing:
            raise ExtractionError(
                "Service principal credentials are incomplete. Fill "
                + ", ".join(self.missing)
                + " in the API credentials dialog (GUI) or environment/.env (CLI)."
            )


@dataclass(frozen=True)
class Token:
    """Access token beserta waktu refresh (epoch detik).

    ``expires_on`` sengaja dimajukan :data:`TOKEN_MARGIN_SECONDS` agar pemakai
    token (termasuk XMLA/ADOMD) meminta token baru sebelum benar-benar
    kedaluwarsa.
    """

    value: str
    expires_on: int


def _read_token_result(result: Any, scope: str) -> Token:
    if not isinstance(result, dict) or "access_token" not in result:
        detail = ""
        if isinstance(result, dict):
            detail = result.get("error_description") or result.get("error") or ""
        raise ExtractionError(
            f"Failed to get a Microsoft Entra token for {scope}"
            + (f": {detail}" if detail else ".")
        )
    expires_in = int(result.get("expires_in") or 3600)
    # Nilai ini adalah waktu refresh, bukan waktu kedaluwarsa sebenarnya.
    expires_on = int(time.time()) + max(60, expires_in - TOKEN_MARGIN_SECONDS)
    return Token(value=str(result["access_token"]), expires_on=expires_on)


def _token_result(access: Any) -> Token:
    """Ubah hasil azure-identity menjadi :class:`Token` (waktu refresh)."""
    value = str(getattr(access, "token", "") or "")
    if not value:
        raise ExtractionError("The Microsoft Entra token is empty.")
    expires_on = int(getattr(access, "expires_on", 0) or 0)
    if not expires_on:
        expires_on = int(time.time()) + 3600
    return Token(value=value, expires_on=expires_on - TOKEN_MARGIN_SECONDS)


def _claims(token: str) -> dict[str, Any]:
    """Baca klaim JWT tanpa verifikasi; hanya untuk menampilkan akun."""
    try:
        payload = str(token).split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
    except Exception:  # noqa: BLE001 - token rusak/bukan JWT
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class UserSession:
    """Sesi login akun 365 tanpa client id (azure-identity bawaan).

    Token REST/Fabric dikelola ``InteractiveBrowserCredential``; XMLA tidak
    memakai token ini (lihat :mod:`core.xmla_client` mode interactive).
    """

    tenant_id: str = ""
    cache_name: str = "bi-tools"
    signed_in: bool = False
    account: str = ""
    fabric_error: str = ""
    is_user: bool = True
    interactive_xmla: bool = True
    _credential: Any = None
    _tokens: dict[str, Token] = field(default_factory=dict)
    _signing_in: bool = False
    _lock: Any = field(default_factory=threading.RLock)

    @property
    def missing(self) -> list[str]:
        return [] if self.signed_in else ["sign-in"]

    @property
    def is_complete(self) -> bool:
        return self.signed_in

    def validate(self) -> None:
        if not self.signed_in:
            raise ExtractionError(
                "Not signed in. Open Settings and click Sign in with a Microsoft 365 account."
            )

    def configure(self, tenant_id: str = "", cache_name: str = "") -> None:
        tenant = (tenant_id or "").strip()
        cache = (cache_name or "").strip()
        with self._lock:
            changed = tenant != self.tenant_id or (
                bool(cache) and cache != self.cache_name
            )
            self.tenant_id = tenant
            if cache:
                self.cache_name = cache
            if changed:
                self._credential = None
                self._tokens.clear()
                self.signed_in = False
                self.account = ""
                self.fabric_error = ""

    def credential(self) -> Any:
        with self._lock:
            if self._credential is None:
                try:
                    from azure.identity import (
                        InteractiveBrowserCredential,
                        TokenCachePersistenceOptions,
                    )
                except ImportError as exc:  # pragma: no cover - dependensi paket
                    raise ExtractionError(
                        "azure-identity is not installed; run pip install azure-identity."
                    ) from exc
                options: dict[str, Any] = {
                    "cache_persistence_options": TokenCachePersistenceOptions(
                        name=self.cache_name
                    )
                }
                if self.tenant_id and self.tenant_id != "organizations":
                    options["tenant_id"] = self.tenant_id
                self._credential = InteractiveBrowserCredential(**options)
            return self._credential

    def get(self, scope: str = POWERBI_SCOPE, *, force: bool = False) -> Token:
        if not self.signed_in and not self._signing_in:
            raise ExtractionError(
                "Not signed in. Open Settings and click Sign in with a Microsoft 365 account."
            )
        with self._lock:
            if not force:
                cached = self._tokens.get(scope)
                if cached is not None and time.time() < cached.expires_on:
                    return cached
            access = self.credential().get_token(scope)
            token = _token_result(access)
            self._tokens[scope] = token
            claims = _claims(token.value)
            account = (
                claims.get("preferred_username")
                or claims.get("upn")
                or claims.get("unique_name")
                or claims.get("name")
                or self.account
            )
            if account:
                self.account = str(account)
            return token

    def sign_in(self) -> None:
        """Login interaktif dan verifikasi token Power BI + Fabric."""
        self._signing_in = True
        try:
            self.get(POWERBI_SCOPE, force=True)
            self.signed_in = True
            try:
                self.get(FABRIC_SCOPE, force=True)
                self.fabric_error = ""
            except Exception as exc:  # noqa: BLE001 - Fabric opsional saat login
                self.fabric_error = str(exc)
        finally:
            self._signing_in = False

    def sign_out(self) -> None:
        with self._lock:
            self._credential = None
            self._tokens.clear()
            self.signed_in = False
            self.account = ""
            self.fabric_error = ""

    def invalidate(self, scope: str | None = None) -> None:
        with self._lock:
            if scope is None:
                self._tokens.clear()
            else:
                self._tokens.pop(scope, None)


_USER_SESSION = UserSession()
_USER_SESSION_LOCK = threading.RLock()


def user_session() -> UserSession:
    """Sesi login global milik proses server (satu instance per pengguna)."""
    with _USER_SESSION_LOCK:
        return _USER_SESSION


def reset_user_session() -> None:
    """Kosongkan sesi login (dipakai uji dan saat server berhenti)."""
    with _USER_SESSION_LOCK:
        _USER_SESSION.sign_out()


class EntraTokens:
    """Token untuk satu identitas: service principal atau sesi user."""

    def __init__(
        self,
        principal: Any,
        *,
        msal_app: Any | None = None,
    ) -> None:
        self.principal = principal
        self._user: UserSession | None = (
            principal if getattr(principal, "is_user", False) else None
        )
        if self._user is None:
            principal.validate()
        self._app: Any | None = msal_app
        self._cache: dict[str, Token] = {}

    def _application(self) -> Any:
        """Buat MSAL client saat token pertama diminta (tanpa I/O di UI thread)."""
        if self._app is None:
            try:
                self._app = msal.ConfidentialClientApplication(
                    self.principal.client_id,
                    authority=(
                        "https://login.microsoftonline.com/"
                        f"{self.principal.tenant_id}"
                    ),
                    client_credential=self.principal.client_secret,
                )
            except ValueError as exc:
                raise ExtractionError(
                    "Invalid Microsoft Entra tenant configuration: "
                    f"{exc}. Check the Tenant ID (GUID or tenant domain)."
                ) from exc
        return self._app

    def get(self, scope: str = POWERBI_SCOPE, *, force: bool = False) -> Token:
        """Token untuk ``scope``; ambil ulang bila kedaluwarsa atau ``force``."""
        if self._user is not None:
            return self._user.get(scope, force=force)
        if not force:
            cached = self._cache.get(scope)
            if cached is not None and time.time() < cached.expires_on:
                return cached
        token = _read_token_result(
            self._application().acquire_token_for_client(scopes=[scope]), scope
        )
        self._cache[scope] = token
        return token

    def invalidate(self, scope: str | None = None) -> None:
        if self._user is not None:
            self._user.invalidate(scope)
            return
        if scope is None:
            self._cache.clear()
        else:
            self._cache.pop(scope, None)

    def provider(self, scope: str = POWERBI_SCOPE) -> "MsalTokenProvider":
        return MsalTokenProvider(self, scope)


class MsalTokenProvider:
    """Adapter :class:`EntraTokens` ke antarmuka ``get_token() -> str``."""

    def __init__(self, tokens: EntraTokens, scope: str = POWERBI_SCOPE) -> None:
        self.tokens = tokens
        self.scope = scope

    def get_token(self) -> str:
        return self.tokens.get(self.scope).value

    def token(self) -> Token:
        return self.tokens.get(self.scope)


class DeferredTokenProvider:
    """Token provider yang baru dibuat saat token pertama diminta.

    Used capture screenshot: generate ulang dari cache tidak boleh meminta
    kredensial atau membuka koneksi apa pun.
    """

    def __init__(self, factory: Callable[[], TokenProvider]) -> None:
        self._factory = factory
        self._inner: TokenProvider | None = None

    def get_token(self) -> str:
        if self._inner is None:
            self._inner = self._factory()
        return self._inner.get_token()


def fabric_provider(tokens: EntraTokens) -> MsalTokenProvider:
    """Token provider untuk Fabric REST API."""
    return tokens.provider(FABRIC_SCOPE)


def powerbi_provider(tokens: EntraTokens) -> MsalTokenProvider:
    """Token provider untuk Power BI REST API dan XMLA endpoint."""
    return tokens.provider(POWERBI_SCOPE)
