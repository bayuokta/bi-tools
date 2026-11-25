"""Lapisan HTTP bersama untuk REST API Power BI dan Fabric.

Hanya modul ini yang boleh mengimpor ``requests``. Client per produk cukup
menyusun path/parameter, lalu memetakan respons menjadi dataclass.

Tanggung jawab transport:

- menempelkan token Bearer dari ``token_provider`` pada setiap percobaan;
- retry ``429`` mengikuti ``Retry-After`` dan ``5xx`` dengan backoff;
- mengubah respons error menjadi :class:`ApiError` yang menyimpan status,
  kode error, dan ``x-ms-request-id`` untuk tiket support;
- memantau long running operation (``202`` + ``Location``) dengan batas poll;
- mengikuti pagination ``@odata.nextLink``.

Token tidak pernah ditulis ke pesan error maupun log.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Iterator, Protocol

import requests

from ..errors import ExtractionError

DEFAULT_MAX_RETRIES = 8
DEFAULT_TIMEOUT = 120
MAX_BACKOFF_SECONDS = 60
# Throttling Power BI bisa meminta tunggu puluhan menit; menunggu diam-diam di
# dalam request membuat GUI/CLI tampak menggantung. Di atas batas ini request
# digagalkan dengan pesan yang menyebut perkiraan waktu coba lagi.
DEFAULT_MAX_RETRY_AFTER = 300.0

Log = Callable[[str], None]


class TokenProvider(Protocol):
    def get_token(self) -> str: ...


class ApiError(ExtractionError):
    """Kegagalan REST API dengan status HTTP dan detail dari server."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "",
        request_id: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id


def _silent(_message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


def _header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", None) or {}
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value)
    return ""


def retry_after(response: Any, default: float = 30) -> float:
    """Nilai ``Retry-After`` dalam detik; ``default`` bila tidak valid."""
    raw = _header(response, "Retry-After").strip()
    if not raw:
        return default
    try:
        return max(1.0, float(raw))
    except (TypeError, ValueError):
        return default


def _detail(response: Any) -> tuple[str, str]:
    """(pesan, kode) dari body error; kosong bila tidak bisa dibaca."""
    payload: Any = None
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - body error bisa apa saja
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or ""
            code = error.get("code") or ""
            if message or code:
                return str(message or ""), str(code or "")
        elif isinstance(error, str) and error:
            return error, ""
        for key in ("message", "Message", "detail", "error_description"):
            value = payload.get(key)
            if value:
                return str(value), ""
    text = str(getattr(response, "text", "") or "").strip().replace("\n", " ")
    return text[:400], ""


class Transport:
    """HTTP client dengan token per request, retry, LRO, dan pagination."""

    def __init__(
        self,
        token_provider: TokenProvider,
        base_url: str = "",
        *,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: float = DEFAULT_TIMEOUT,
        retry_status: tuple[int, ...] = (429, 500, 502, 503, 504),
        max_retry_after: float = DEFAULT_MAX_RETRY_AFTER,
        log: Log = _silent,
    ) -> None:
        self._token_provider = token_provider
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(1, int(max_retries))
        self.retry_status = tuple(int(code) for code in retry_status)
        self.max_retry_after = float(max_retry_after)
        self._session = session or requests.Session()
        self._owned_session = session is None
        self._sleep = sleep
        self._log = log

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owned_session:
            self._session.close()

    def __enter__(self) -> "Transport":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- HTTP --------------------------------------------------------------
    def _url(self, path_or_url: str) -> str:
        if str(path_or_url).lower().startswith(("http://", "https://")):
            return str(path_or_url)
        if not self.base_url:
            return str(path_or_url)
        return f"{self.base_url}/{str(path_or_url).lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token_provider.get_token()}"}

    def _backoff(self, attempt: int) -> float:
        return float(min(MAX_BACKOFF_SECONDS, 2**attempt))

    def _error(
        self, method: str, url: str, response: Any, note: str = ""
    ) -> ApiError:
        status = int(getattr(response, "status_code", 0) or 0)
        detail, code = _detail(response)
        message = f"{method} {url} gagal (HTTP {status})"
        if detail:
            message += f": {detail}"
        message += note
        if 200 <= status < 300:
            message += (
                " (status sukses ini tidak ada di daftar allow pemanggil; "
                "tambahkan bila memang jawaban normal endpoint)"
            )
        if status in (401, 403):
            message += (
                " (periksa izin service principal dan pengaturan Admin API tenant)"
            )
        return ApiError(
            message,
            status_code=status,
            code=code,
            request_id=_header(response, "x-ms-request-id"),
        )

    def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        data: bytes | None = None,
        allow: tuple[int, ...] = (200,),
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Kirim request; kembalikan respons untuk status di ``allow``.

        ``data`` dipakai untuk body biner (mis. upload Graph); jangan digabung
        dengan ``json`` pada request yang sama.
        """
        if data is not None and json is not None:
            raise ExtractionError("Body request tidak boleh berisi data dan json sekaligus.")
        if str(method or "").strip().upper() == "DELETE":
            # Kebijakan tool: tidak pernah memakai metode HTTP DELETE. Operasi
            # hapus/bersihkan memakai POST (mis. cache/clear, jobs/{id}/cancel).
            raise ExtractionError(
                "Metode HTTP DELETE dilarang di tool ini. Gunakan POST "
                "(mis. .../clear atau .../cancel); larangan berlaku untuk API "
                "Power BI, Fabric, maupun API lokal."
            )
        url = self._url(path_or_url)
        optional: dict[str, Any] = {}
        if params is not None:
            optional["params"] = params
        if json is not None:
            optional["json"] = json
        if data is not None:
            optional["data"] = data
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = self._session.request(
                    method,
                    url,
                    headers={**self._headers(), **(headers or {})},
                    timeout=self.timeout,
                    **optional,
                )
            except requests.RequestException as exc:
                last_error = exc
                wait = self._backoff(attempt)
                self._log(
                    f"{method} {url} gagal dihubungi; coba lagi dalam {wait:.0f}s"
                )
                self._sleep(wait)
                continue

            status = int(getattr(response, "status_code", 0) or 0)
            if status in allow:
                return response
            if status in self.retry_status and attempt < self.max_retries - 1:
                wait = retry_after(response) if status == 429 else self._backoff(attempt)
                if wait > self.max_retry_after:
                    raise self._error(
                        method,
                        url,
                        response,
                        note=(
                            " - permintaan ditunda server (throttling); "
                            f"coba lagi dalam ±{wait / 60:.0f} menit"
                        ),
                    )
                self._log(
                    f"{method} {url} -> HTTP {status}; coba lagi dalam {wait:.0f}s"
                )
                self._sleep(wait)
                continue
            raise self._error(method, url, response)

        detail = f": {last_error}" if last_error else ""
        raise ApiError(
            f"{method} {url} gagal setelah {self.max_retries} percobaan{detail}"
        )

    def _parse_json(self, path_or_url: str, response: Any) -> Any:
        content = getattr(response, "content", None)
        if content is not None and not content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(
                f"Respons {self._url(path_or_url)} bukan JSON valid"
            ) from exc

    def json(self, method: str, path_or_url: str, **kwargs: Any) -> Any:
        """Request lalu kembalikan body JSON (``{}`` bila body kosong)."""
        response = self.request(method, path_or_url, **kwargs)
        return self._parse_json(path_or_url, response)

    def pages(
        self,
        path_or_url: str,
        *,
        key: str = "value",
        limit: int = 100,
    ) -> Iterator[dict[str, Any]]:
        """Iterasi item list sambil mengikuti ``@odata.nextLink``."""
        url = path_or_url
        seen = 0
        for _ in range(max(1, limit)):
            data = self.json("GET", url)
            if isinstance(data, list):
                items = data
                next_link = ""
            elif isinstance(data, dict):
                value = data.get(key)
                items = value if isinstance(value, list) else []
                next_link = str(data.get("@odata.nextLink") or "")
            else:
                return
            for item in items:
                if isinstance(item, dict):
                    seen += 1
                    yield item
            if not next_link:
                return
            url = next_link

    def _poll_delay(self, response: Any, wait: float) -> float:
        """Jeda poll berikutnya; tolak permintaan tunggu yang tak wajar."""
        delay = retry_after(response, wait)
        if delay > self.max_retry_after:
            raise ApiError(
                "Server meminta tunggu "
                f"±{delay / 60:.0f} menit sebelum operasi bisa dilanjutkan "
                "(throttling); coba lagi nanti."
            )
        return delay

    def poll_status(
        self,
        path_or_url: str,
        *,
        initial_wait: float = 0,
        wait: float = 5,
        max_polls: int = 30,
        done: tuple[str, ...] = ("succeeded", "completed"),
        failed: tuple[str, ...] = ("failed", "cancelled", "canceled"),
        ready: Callable[[dict[str, Any]], bool] | None = None,
    ) -> dict[str, Any]:
        """Pantau operasi sampai selesai; kembalikan body status terakhir.

        ``ready`` dipakai bila hasil akhir sudah ada di body (mis. Fabric
        ``getDefinition`` mengembalikan ``definition`` tanpa field ``status``).
        """
        delay = initial_wait
        for _ in range(max(1, max_polls)):
            if delay:
                self._sleep(delay)
            response = self.request("GET", path_or_url, allow=(200, 202))
            if int(getattr(response, "status_code", 0) or 0) == 202:
                delay = self._poll_delay(response, wait)
                continue
            data = self._parse_json(path_or_url, response)
            if not isinstance(data, dict):
                raise ApiError("Status operasi bukan object JSON.")
            if ready is not None and ready(data):
                return data
            status = str(data.get("status") or "").lower()
            if status in done:
                return data
            if status in failed:
                detail = data.get("error") or data.get("message") or status
                raise ApiError(f"Operasi {status}: {detail}")
            delay = self._poll_delay(response, wait)
        raise ApiError(
            f"Batas waktu menunggu operasi ({max_polls} polling)."
        )
