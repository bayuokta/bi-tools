"""Klien HTTP minimal Power BI REST API untuk alur embed token.

Endpoint yang dipakai:
- GET  /groups/{g}/reports/{r}    -> datasetId, datasetWorkspaceId
- GET  /groups/{g}/datasets/{d}   -> isEffectiveIdentityRolesRequired
- POST /GenerateToken             -> composite embed token (dengan RLS)

REST API Power BI tidak punya endpoint daftar visual; enumerasi page/visual
dilakukan lewat embedded JS client di :mod:`core.pbi_capture.capture`.

Seluruh HTTP (token, retry, error) ditangani :class:`core.api.Transport`.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ..api import ApiError, Transport
from ..errors import ExtractionError

BASE_URL = "https://api.powerbi.com/v1.0/myorg"

Log = Callable[[str], None]


def _silent(_message: str) -> None:
    pass


# Nama lama dipertahankan agar pemanggil yang menangkap error ini tetap jalan.
PowerBIError = ApiError


class _CallableProvider:
    """Adapter callable lama ``() -> str`` ke antarmuka ``get_token()``."""

    def __init__(self, fetch: Callable[[], str]) -> None:
        self._fetch = fetch

    def get_token(self) -> str:
        return self._fetch()


def _as_provider(value: Any) -> Any:
    if hasattr(value, "get_token"):
        return value
    return _CallableProvider(value)


class PowerBIClient:
    """Klien REST Power BI dengan token per request + retry/backoff."""

    def __init__(
        self,
        token_provider: Any,
        timeout: int = 30,
        max_retries: int = 6,
        sleep: Callable[[float], None] = time.sleep,
        log: Log = _silent,
    ) -> None:
        self._transport = Transport(
            _as_provider(token_provider),
            BASE_URL,
            sleep=sleep,
            max_retries=max_retries,
            timeout=timeout,
            log=log,
        )

    def close(self) -> None:
        self._transport.close()

    # ------------------------------------------------------------------- API
    def get_report(self, workspace_id: str, report_id: str) -> dict:
        data = self._transport.json(
            "GET", f"groups/{workspace_id}/reports/{report_id}"
        )
        return data if isinstance(data, dict) else {}

    def get_dataset(self, workspace_id: str, dataset_id: str) -> dict:
        data = self._transport.json(
            "GET", f"groups/{workspace_id}/datasets/{dataset_id}"
        )
        return data if isinstance(data, dict) else {}

    def generate_embed_token(self, body: dict) -> str:
        """POST /GenerateToken (composite) -> embed token."""
        data = self._transport.json("POST", "GenerateToken", json=body)
        token = data.get("token") if isinstance(data, dict) else ""
        if not token:
            raise ExtractionError("The GenerateToken response contains no token.")
        return str(token)
