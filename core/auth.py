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

import os
import time
from dataclasses import dataclass
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
                "Kredensial service principal belum lengkap. Isi "
                + ", ".join(self.missing)
                + " di dialog Kredensial API (GUI) atau environment/.env (CLI)."
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
            f"Gagal mengambil token Microsoft Entra untuk {scope}"
            + (f": {detail}" if detail else ".")
        )
    expires_in = int(result.get("expires_in") or 3600)
    # Nilai ini adalah waktu refresh, bukan waktu kedaluwarsa sebenarnya.
    expires_on = int(time.time()) + max(60, expires_in - TOKEN_MARGIN_SECONDS)
    return Token(value=str(result["access_token"]), expires_on=expires_on)


class EntraTokens:
    """Satu MSAL client untuk satu service principal, cache token per scope."""

    def __init__(
        self,
        principal: ServicePrincipal,
        *,
        msal_app: Any | None = None,
    ) -> None:
        principal.validate()
        self.principal = principal
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
                    "Konfigurasi tenant Microsoft Entra tidak valid: "
                    f"{exc}. Periksa Tenant ID (GUID atau domain tenant)."
                ) from exc
        return self._app

    def get(self, scope: str = POWERBI_SCOPE, *, force: bool = False) -> Token:
        """Token untuk ``scope``; ambil ulang bila kedaluwarsa atau ``force``."""
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

    Dipakai capture screenshot: generate ulang dari cache tidak boleh meminta
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
