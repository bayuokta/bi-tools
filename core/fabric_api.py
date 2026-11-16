"""Client Microsoft Fabric REST API untuk mengambil report public definition.

Alur: POST .../getDefinition, tangani long running operation (202 + Location),
decode part InlineBase64, lalu simpan sebagai folder PBIR agar bisa dibaca
`core.report.extract_report`.

Modul inti tanpa I/O terminal; kesalahan dilaporkan sebagai ExtractionError.
"""

from __future__ import annotations

import base64
import binascii
import json
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from uuid import UUID

from .api import Transport, retry_after
from .auth import TokenProvider
from .errors import ExtractionError

FABRIC_API = "https://api.fabric.microsoft.com/v1"
MAX_RETRIES = 8
MAX_POLLS = 30
DEFAULT_TIMEOUT = 120
DEFAULT_POLL_WAIT = 5

PBIR = "PBIR"
PBIR_LEGACY = "PBIR-Legacy"
UNKNOWN_FORMAT = "unknown"

Log = Callable[[str], None]


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""



@dataclass(frozen=True)
class ServiceReportRef:
    """Identitas report di Power BI Service."""

    workspace_id: str
    report_id: str

    @classmethod
    def from_ids(cls, workspace_id: str, report_id: str) -> "ServiceReportRef":
        return cls(
            _validate_uuid(workspace_id, "Workspace ID"),
            _validate_uuid(report_id, "Report ID"),
        )


@dataclass(frozen=True)
class ServiceSourceInfo:
    """Ringkasan sumber report Power BI Service (pengganti PbixSourceInfo)."""

    workspace_id: str
    report_id: str
    report_format: str = ""

    @property
    def kind(self) -> str:
        return "service_report"

    @property
    def label(self) -> str:
        if not self.report_id:
            return "Power BI Service (XMLA endpoint)"
        return "Power BI Service (report public definition)"

    @property
    def has_pbir(self) -> bool:
        return self.report_format != PBIR_LEGACY

    @property
    def has_local_model(self) -> bool:
        return False

    @property
    def is_live_connection(self) -> bool:
        return True


@dataclass(frozen=True)
class DefinitionPart:
    path: str
    payload: bytes


@dataclass(frozen=True)
class ReportDefinition:
    report_format: str
    parts: tuple[DefinitionPart, ...]
    model_reference: str = ""

    def paths(self) -> set[str]:
        return {part.path for part in self.parts}


def _validate_uuid(value: str, label: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ExtractionError(f"{label} masih kosong.")
    try:
        return str(UUID(text))
    except ValueError as exc:
        hint = ""
        if text.lower() == "me":
            hint = " URL menunjuk ke My workspace; gunakan URL workspace biasa."
        raise ExtractionError(f"{label} bukan GUID yang valid: {text}.{hint}") from exc


def parse_report_url(text: str) -> ServiceReportRef:
    """Ambil workspace dan report ID dari URL report Power BI/Fabric."""
    raw = (text or "").strip()
    if not raw:
        raise ExtractionError("URL report Power BI Service masih kosong.")

    parsed = urlparse(raw)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    lowered = [segment.lower() for segment in segments]
    if "groups" in lowered:
        group_index = lowered.index("groups")
        if group_index + 1 >= len(segments):
            raise ExtractionError("URL report tidak memuat workspace ID.")
        if "reports" not in lowered[group_index + 1 :]:
            raise ExtractionError("URL report tidak memuat bagian /reports/<reportId>.")
        report_index = lowered.index("reports", group_index + 1)
        if report_index + 1 >= len(segments):
            raise ExtractionError("URL report tidak memuat report ID.")
        return ServiceReportRef.from_ids(segments[group_index + 1], segments[report_index + 1])

    tokens = [token for token in raw.replace(",", " ").split() if token]
    if len(tokens) == 2:
        return ServiceReportRef.from_ids(tokens[0], tokens[1])

    raise ExtractionError(
        "Format URL report tidak dikenali. Contoh: "
        "https://app.powerbi.com/groups/<workspaceId>/reports/<reportId>"
    )


def _decode_payload(path: str, item: dict[str, Any]) -> bytes:
    payload_type = str(item.get("payloadType") or "InlineBase64")
    if payload_type != "InlineBase64":
        raise ExtractionError(
            f"Part definition {path} memakai payloadType {payload_type} yang belum didukung."
        )
    encoded = str(item.get("payload") or "").strip()
    if not encoded:
        raise ExtractionError(f"Part definition {path} tidak memuat payload.")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ExtractionError(f"Payload base64 tidak valid untuk part {path}.") from exc


def _detect_format(paths: set[str]) -> str:
    if any(path.startswith("definition/pages/") for path in paths):
        return PBIR
    if "report.json" in paths:
        return PBIR_LEGACY
    return UNKNOWN_FORMAT


def _model_reference(parts: tuple[DefinitionPart, ...]) -> str:
    for part in parts:
        if part.path != "definition.pbir":
            continue
        try:
            data = json.loads(part.payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ""
        reference = data.get("datasetReference") or {}
        connection = str((reference.get("byConnection") or {}).get("connectionString") or "")
        if connection:
            return connection.removeprefix("semanticmodelid=").strip()
        return str((reference.get("byPath") or {}).get("path") or "")
    return ""


def parse_definition_response(payload: dict[str, Any]) -> ReportDefinition:
    """Ubah respons getDefinition menjadi parts yang sudah didecode."""
    raw = payload.get("definition")
    if not isinstance(raw, dict):
        raw = payload
    items = raw.get("parts") or []
    parts: list[DefinitionPart] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        parts.append(DefinitionPart(path=path, payload=_decode_payload(path, item)))
    if not parts:
        raise ExtractionError("Respons getDefinition tidak memuat part definition.")

    unique = tuple(parts)
    return ReportDefinition(
        report_format=_detect_format({part.path for part in unique}),
        parts=unique,
        model_reference=_model_reference(unique),
    )


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/").strip())
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ExtractionError(f"Path part definition tidak aman: {value}")
    return path


def materialize_definition(definition: ReportDefinition, target_root: Path) -> Path:
    """Tulis part PBIR ke folder kerja dan kembalikan folder `definition`."""
    paths = definition.paths()
    if not any(path.startswith("definition/") for path in paths):
        if "report.json" in paths:
            raise ExtractionError(
                "Report di Power BI Service masih memakai format PBIR-Legacy "
                "(satu file report.json). Buka report di Power BI Desktop, simpan "
                "ulang sebagai PBIR, lalu publish lagi sebelum ekstraksi."
            )
        raise ExtractionError(
            "Definition report tidak memuat folder definition/ (PBIR). "
            "Format report dari service tidak dikenali."
        )

    root = Path(target_root)
    for part in definition.parts:
        if not part.path.startswith("definition/"):
            continue  # StaticResources dan definition.pbir tidak dibutuhkan ekstraksi
        destination = root / Path(*_safe_relative_path(part.path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(part.payload)

    report_def = root / "definition"
    if not (report_def / "pages" / "pages.json").exists():
        raise ExtractionError(
            "Definition PBIR tidak lengkap: definition/pages/pages.json tidak ditemukan."
        )
    return report_def


class FabricReportClient:
    """Client Fabric API untuk report definition (LRO + retry 429)."""

    def __init__(
        self,
        token_provider: TokenProvider,
        *,
        session: Any | None = None,
        log: Log = _silent,
        sleep: Callable[[float], None] = time.sleep,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        max_polls: int = MAX_POLLS,
        poll_wait: float | None = None,
    ) -> None:
        self._transport = Transport(
            token_provider,
            FABRIC_API,
            session=session,
            sleep=sleep,
            max_retries=max_retries,
            timeout=timeout,
            log=log,
        )
        self._log = log
        self._max_polls = max_polls
        # ``poll_wait`` mempercepat operasi LRO yang sudah selesai tetapi
        # memberi Retry-After besar (getDefinition: Retry-After 20 dtk,
        # operasi selesai ~1 dtk). Default None = perilaku lama.
        self._poll_wait = poll_wait

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> "FabricReportClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- HTTP -------------------------------------------------------------
    def _json(self, response: Any, action: str) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ExtractionError(
                f"Respons Fabric API untuk {action} bukan JSON yang valid."
            ) from exc
        if not isinstance(data, dict):
            raise ExtractionError(f"Respons Fabric API untuk {action} tidak dikenali.")
        return data

    def _poll_operation(self, response: Any) -> dict[str, Any]:
        location = response.headers.get("Location") or response.headers.get(
            "x-ms-operation-id"
        )
        if not location:
            raise ExtractionError(
                "Fabric API menerima permintaan tetapi tidak memberi header Location "
                "untuk memantau operasi."
            )
        if not location.lower().startswith("http"):
            location = f"{FABRIC_API}/operations/{location}"

        initial_wait = retry_after(response, DEFAULT_POLL_WAIT)
        wait = DEFAULT_POLL_WAIT
        if self._poll_wait is not None:
            initial_wait = min(initial_wait, self._poll_wait)
            wait = self._poll_wait
        data = self._transport.poll_status(
            location,
            initial_wait=initial_wait,
            wait=wait,
            max_polls=self._max_polls,
            ready=lambda body: "definition" in body,
        )
        if "definition" in data:
            return data
        result = self._transport.json(
            "GET", location.rstrip("/") + "/result"
        )
        if not isinstance(result, dict):
            raise ExtractionError("Hasil getDefinition bukan object JSON.")
        return result

    # -- API --------------------------------------------------------------
    def get_report_definition(self, service: ServiceReportRef) -> ReportDefinition:
        """Ambil report public definition dari Fabric API."""
        path = (
            f"workspaces/{service.workspace_id}"
            f"/reports/{service.report_id}/getDefinition"
        )
        response = self._transport.request(
            "POST", path, allow=(200, 202)
        )
        if int(response.status_code) == 200:
            return parse_definition_response(self._json(response, "getDefinition"))
        return parse_definition_response(self._poll_operation(response))

