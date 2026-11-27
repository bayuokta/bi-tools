"""Upload snapshot ke SharePoint lewat Microsoft Graph (app-only).

Hanya program sync yang memakai modul ini. Kredensial service principal harus
punya izin aplikasi Graph ``Sites.Selected`` (disarankan) atau
``Sites.ReadWrite.All`` yang sudah di-consent, plus grant untuk site tujuan.

Seluruh HTTP lewat :class:`core.api.transport.Transport`; modul ini hanya
menyusun path Graph, memecah file besar menjadi chunk, dan memetakan error.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from core.api import ApiError, Transport
from core.auth import EntraTokens, ServicePrincipal
from core.errors import ExtractionError

GRAPH_API = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
SIMPLE_UPLOAD_LIMIT = 10 * 1024 * 1024
CHUNK_SIZE = 10 * 1024 * 1024
CHUNK_ALIGN = 320 * 1024

Log = Callable[[str], None]


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


def _segments(value: str) -> list[str]:
    return [part for part in str(value or "").replace("\\", "/").split("/") if part]


def _quote(parts: list[str]) -> str:
    return "/".join(quote(part, safe="") for part in parts)


def _body(response: Any) -> dict[str, Any]:
    """Body JSON Graph; 202/204 bisa kosong sehingga tidak boleh melempar."""
    try:
        value = response.json()
    except ValueError:
        return {}
    return dict(value) if isinstance(value, dict) else {}


@dataclass(frozen=True)
class SharePointTarget:
    """Lokasi tujuan upload di SharePoint."""

    hostname: str
    site_path: str
    library: str = ""
    folder: str = ""

    @classmethod
    def from_values(
        cls,
        hostname: str,
        site_path: str,
        library: str = "",
        folder: str = "",
    ) -> "SharePointTarget":
        host = str(hostname or "").strip()
        for prefix in ("https://", "http://"):
            if host.lower().startswith(prefix):
                host = host[len(prefix) :]
        host = host.strip().strip("/")
        site = str(site_path or "").strip()
        if site.lower().startswith(("http://", "https://")):
            site = site.split("://", 1)[1]
            site = site.split("/", 1)[1] if "/" in site else ""
        site = "/".join(_segments(site))
        if not host:
            raise ExtractionError("SharePoint hostname is required (without https://).")
        if not site:
            raise ExtractionError(
                "SharePoint site path is required (e.g. /teams/BIDataRepository)."
            )
        return cls(
            hostname=host,
            site_path=site,
            library=str(library or "").strip(),
            folder="/".join(_segments(folder)),
        )

    @property
    def label(self) -> str:
        where = f"{self.hostname}/{self.site_path}"
        if self.library:
            where += f" · {self.library}"
        if self.folder:
            where += f"/{self.folder}"
        return where


class GraphUploader:
    """Upload file ke document library SharePoint dengan upload session."""

    def __init__(
        self,
        principal: ServicePrincipal,
        target: SharePointTarget,
        *,
        session: Any | None = None,
        msal_app: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        timeout: int = 300,
        chunk_size: int = CHUNK_SIZE,
        simple_limit: int = SIMPLE_UPLOAD_LIMIT,
        log: Log = _silent,
    ) -> None:
        principal.validate()
        self.target = target
        self._log = log
        self._chunk_size = max(1, int(chunk_size))
        self._simple_limit = max(1, int(simple_limit))
        tokens = EntraTokens(principal, msal_app=msal_app)
        self._transport = Transport(
            tokens.provider(GRAPH_SCOPE),
            GRAPH_API,
            session=session,
            sleep=sleep,
            timeout=timeout,
            log=log,
        )
        self._site: dict[str, Any] | None = None
        self._drive: dict[str, Any] | None = None
        self._folder_ready = False

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "GraphUploader":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- Graph -------------------------------------------------------------
    def _get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        return _body(self._request("GET", path, **kwargs))

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            return self._transport.request(method, path, **kwargs)
        except ApiError as exc:
            if exc.status_code in (401, 403):
                raise ExtractionError(
                    "Graph access denied. Make sure the application permission "
                    "`Sites.Selected` (or `Sites.ReadWrite.All`) is "
                    f"consented and site {self.target.label} has been granted. "
                    f"Detail: {exc}"
                ) from exc
            raise ExtractionError(str(exc)) from exc

    def site(self) -> dict[str, Any]:
        if self._site is None:
            data = self._get(f"/sites/{self.target.hostname}:/{self.target.site_path}")
            if not data.get("id"):
                raise ExtractionError(
                    f"SharePoint site not found: {self.target.label}."
                )
            self._site = data
        return self._site

    def drives(self) -> list[dict[str, Any]]:
        site_id = str(self.site().get("id") or "")
        data = self._get(f"/sites/{site_id}/drives", params={"$select": "id,name,webUrl"})
        rows = data.get("value")
        return [dict(row) for row in rows or [] if isinstance(row, dict)]

    def drive(self) -> dict[str, Any]:
        if self._drive is None:
            drives = self.drives()
            if not drives:
                raise ExtractionError("The site has no document library.")
            wanted = (self.target.library or "").strip().casefold()
            chosen = None
            if wanted and wanted != "default":
                chosen = next(
                    (
                        row
                        for row in drives
                        if str(row.get("name") or "").strip().casefold() == wanted
                    ),
                    None,
                )
                if chosen is None:
                    names = ", ".join(str(row.get("name") or "") for row in drives)
                    raise ExtractionError(
                        f"Library '{self.target.library}' was not found. "
                        f"Options: {names}."
                    )
            else:
                chosen = next(
                    (
                        row
                        for row in drives
                        if str(row.get("name") or "").casefold() == "documents"
                    ),
                    drives[0],
                )
            self._drive = chosen
        return self._drive

    @property
    def _drive_id(self) -> str:
        return str(self.drive().get("id") or "")

    def _remote(self, name: str = "") -> str:
        parts = _segments(self.target.folder)
        if name:
            parts.append(name)
        return _quote(parts)

    def ensure_folder(self) -> None:
        """Buat folder tujuan bertingkat; folder yang sudah ada dilewati."""
        if self._folder_ready:
            return
        created: list[str] = []
        for segment in _segments(self.target.folder):
            url = (
                f"/drives/{self._drive_id}/root:/{_quote(created)}:/children"
                if created
                else f"/drives/{self._drive_id}/root/children"
            )
            self._request(
                "POST",
                url,
                json={
                    "name": segment,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "replace",
                },
                allow=(200, 201, 409),
            )
            created.append(segment)
        self._folder_ready = True

    def upload(self, path: Path | str, *, name: str = "") -> dict[str, Any]:
        """Upload satu file; nama di SharePoint default sama dengan nama file."""
        source = Path(path).expanduser()
        if not source.is_file():
            raise ExtractionError(f"Upload file not found: {source}")
        self.ensure_folder()
        remote_name = str(name or source.name)
        remote = self._remote(remote_name)
        size = source.stat().st_size
        if size <= self._simple_limit:
            response = self._request(
                "PUT",
                f"/drives/{self._drive_id}/root:/{remote}:/content",
                data=source.read_bytes(),
                headers={"Content-Type": "application/octet-stream"},
                allow=(200, 201),
            )
            item = _body(response)
        else:
            item = self._upload_session(source, remote)
        return {
            "name": str(item.get("name") or remote_name),
            "size": int(item.get("size") or size),
            "webUrl": str(item.get("webUrl") or ""),
        }

    def _upload_session(self, source: Path, remote: str) -> dict[str, Any]:
        session = _body(
            self._request(
                "POST",
                f"/drives/{self._drive_id}/root:/{remote}:/createUploadSession",
                json={
                    "item": {
                        "@microsoft.graph.conflictBehavior": "replace",
                        "name": source.name,
                    }
                },
                allow=(200, 201),
            )
        )
        upload_url = str(session.get("uploadUrl") or "")
        if not upload_url:
            raise ExtractionError("Graph did not return an uploadUrl.")
        total = source.stat().st_size
        chunk = self._chunk_size
        offset = 0
        last: dict[str, Any] = {}
        with source.open("rb") as handle:
            while offset < total:
                handle.seek(offset)
                payload = handle.read(chunk)
                if not payload:
                    break
                end = offset + len(payload) - 1
                response = self._request(
                    "PUT",
                    upload_url,
                    data=payload,
                    headers={
                        "Content-Range": f"bytes {offset}-{end}/{total}",
                        "Content-Length": str(len(payload)),
                    },
                    allow=(200, 201, 202),
                )
                last = _body(response)
                offset = end + 1
                self._log(f"Upload chunk {offset}/{total} byte")
        if offset < total:
            raise ExtractionError(
                f"Upload stopped at {offset} of {total} bytes: {source.name}"
            )
        return last

    def list_files(self, limit: int = 20) -> list[dict[str, Any]]:
        """Isi folder tujuan (untuk perintah ``check``)."""
        remote = self._remote()
        path = (
            f"/drives/{self._drive_id}/root:/{remote}:/children"
            if remote
            else f"/drives/{self._drive_id}/root/children"
        )
        data = self._get(
            path,
            params={
                "$select": "name,size,lastModifiedDateTime",
                "$top": max(1, int(limit)),
            },
        )
        rows = data.get("value")
        return [dict(row) for row in rows or [] if isinstance(row, dict)]

    def check(self) -> dict[str, Any]:
        """Ringkas site, library, dan isi folder untuk verifikasi manual."""
        site = self.site()
        drive = self.drive()
        folder = self._remote()
        return {
            "target": self.target.label,
            "site": str(site.get("displayName") or ""),
            "site_url": str(site.get("webUrl") or ""),
            "library": str(drive.get("name") or ""),
            "library_url": str(drive.get("webUrl") or ""),
            "path": folder,
            "files": self.list_files(),
        }
