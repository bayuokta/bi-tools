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
    report_ids: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "service_report"

    @property
    def label(self) -> str:
        if self.report_ids:
            return f"Power BI Service (batch {len(self.report_ids)} report)"
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
        raise ExtractionError(f"{label} is still empty.")
    try:
        return str(UUID(text))
    except ValueError as exc:
        hint = ""
        if text.lower() == "me":
            hint = " URL menunjuk ke My workspace; gunakan URL workspace biasa."
        raise ExtractionError(f"{label} is not a valid GUID: {text}.{hint}") from exc


def parse_report_url(text: str) -> ServiceReportRef:
    """Ambil workspace dan report ID dari URL report Power BI/Fabric."""
    raw = (text or "").strip()
    if not raw:
        raise ExtractionError("The Power BI Service report URL is still empty.")

    parsed = urlparse(raw)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    lowered = [segment.lower() for segment in segments]
    if "groups" in lowered:
        group_index = lowered.index("groups")
        if group_index + 1 >= len(segments):
            raise ExtractionError("The report URL does not contain a workspace ID.")
        if "reports" not in lowered[group_index + 1 :]:
            raise ExtractionError("The report URL does not contain the /reports/<reportId> segment.")
        report_index = lowered.index("reports", group_index + 1)
        if report_index + 1 >= len(segments):
            raise ExtractionError("The report URL does not contain a report ID.")
        return ServiceReportRef.from_ids(segments[group_index + 1], segments[report_index + 1])

    tokens = [token for token in raw.replace(",", " ").split() if token]
    if len(tokens) == 2:
        return ServiceReportRef.from_ids(tokens[0], tokens[1])

    raise ExtractionError(
        "Unrecognized report URL format. Example: "
        "https://app.powerbi.com/groups/<workspaceId>/reports/<reportId>"
    )


def _decode_payload(path: str, item: dict[str, Any]) -> bytes:
    payload_type = str(item.get("payloadType") or "InlineBase64")
    if payload_type != "InlineBase64":
        raise ExtractionError(
            f"Part definition {path} uses payloadType {payload_type} which is not supported yet."
        )
    encoded = str(item.get("payload") or "").strip()
    if not encoded:
        raise ExtractionError(f"Part definition {path} has no payload.")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ExtractionError(f"Invalid base64 payload for part {path}.") from exc


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
        raise ExtractionError("The getDefinition response contains no definition parts.")

    unique = tuple(parts)
    return ReportDefinition(
        report_format=_detect_format({part.path for part in unique}),
        parts=unique,
        model_reference=_model_reference(unique),
    )


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/").strip())
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ExtractionError(f"Unsafe definition part path: {value}")
    return path


def materialize_definition(definition: ReportDefinition, target_root: Path) -> Path:
    """Tulis part PBIR ke folder kerja dan kembalikan folder `definition`."""
    paths = definition.paths()
    if not any(path.startswith("definition/") for path in paths):
        if "report.json" in paths:
            raise ExtractionError(
                "The Power BI Service report still uses PBIR-Legacy "
                "(a single report.json). Open it in Power BI Desktop, save it "
                "again as PBIR, then publish again before extraction."
            )
        raise ExtractionError(
            "The report definition has no definition/ folder (PBIR). "
            "The report format from the service was not recognized."
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
            "Incomplete PBIR definition: definition/pages/pages.json was not found."
        )
    return report_def


def definition_payload(parts: Any) -> dict[str, Any]:
    """Payload ``updateDefinition``/create dari part biner (base64)."""
    import base64

    return {
        "definition": {
            "parts": [
                {
                    "path": str(part.path),
                    "payload": base64.b64encode(bytes(part.payload)).decode("ascii"),
                    "payloadType": "InlineBase64",
                }
                for part in parts
            ]
        }
    }


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
        if not hasattr(token_provider, "get_token"):
            raise ExtractionError(
                "FabricReportClient needs a token provider with get_token(); "
                "use auth.fabric_provider(EntraTokens) instead of EntraTokens."
            )
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
                f"Fabric API response for {action} is not valid JSON."
            ) from exc
        if not isinstance(data, dict):
            raise ExtractionError(f"Fabric API response for {action} was not recognized.")
        return data

    def _poll_operation(
        self, response: Any, *, expect_result: bool = True
    ) -> dict[str, Any]:
        location = response.headers.get("Location") or response.headers.get(
            "x-ms-operation-id"
        )
        if not location:
            raise ExtractionError(
                "The Fabric API accepted the request but did not return a Location "
                "header to monitor the operation."
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
        if not expect_result:
            # updateDefinition menyelesaikan operasi tanpa payload hasil;
            # memanggil /result dijawab HTTP 400 "The operation has no result".
            return data
        result = self._transport.json(
            "GET", location.rstrip("/") + "/result"
        )
        if not isinstance(result, dict):
            raise ExtractionError("The getDefinition result is not a JSON object.")
        return result

    # -- API --------------------------------------------------------------
    # -- semantic model & report definition (restore) ---------------------
    def get_semantic_model_definition(
        self, workspace_id: str, model_id: str
    ) -> ReportDefinition:
        """Ambil definisi semantic model (TMDL/TMSL) untuk backup."""
        path = (
            f"workspaces/{workspace_id}"
            f"/semanticModels/{model_id}/getDefinition"
        )
        response = self._transport.request("POST", path, allow=(200, 202))
        data = (
            self._json(response, "getDefinition model")
            if int(response.status_code) == 200
            else self._poll_operation(response)
        )
        return parse_definition_response(data)

    def get_semantic_model_tmsl(
        self, workspace_id: str, model_id: str
    ) -> dict[str, Any]:
        """Ambil definisi semantic model dalam format TMSL (``model.bim``)."""
        path = (
            f"workspaces/{workspace_id}"
            f"/semanticModels/{model_id}/getDefinition?format=TMSL"
        )
        response = self._transport.request("POST", path, allow=(200, 202))
        data = (
            self._json(response, "getDefinition model TMSL")
            if int(response.status_code) == 200
            else self._poll_operation(response)
        )
        parts = ((data.get("definition") or {}).get("parts") or [])
        part = next(
            (
                item
                for item in parts
                if str(item.get("path") or "") == "model.bim"
            ),
            None,
        )
        if part is None:
            raise ExtractionError(
                "The TMSL semantic model definition has no model.bim part."
            )
        payload = _decode_payload("model.bim", part)
        try:
            result = json.loads(payload.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExtractionError("model.bim is not valid JSON.") from exc
        if not isinstance(result, dict):
            raise ExtractionError("model.bim does not contain a JSON object.")
        return result

    def update_semantic_model_definition(
        self, workspace_id: str, model_id: str, parts: Any
    ) -> dict[str, Any]:
        path = (
            f"workspaces/{workspace_id}"
            f"/semanticModels/{model_id}/updateDefinition"
        )
        response = self._transport.request(
            "POST", path, json=definition_payload(parts), allow=(200, 202)
        )
        if int(response.status_code) == 200:
            return self._json(response, "updateDefinition model")
        return self._poll_operation(response, expect_result=False)

    def create_semantic_model(
        self, workspace_id: str, display_name: str, parts: Any
    ) -> dict[str, Any]:
        body = {"displayName": str(display_name)}
        body.update(definition_payload(parts))
        response = self._transport.request(
            "POST",
            f"workspaces/{workspace_id}/semanticModels",
            json=body,
            allow=(200, 201, 202),
        )
        if int(response.status_code) in (200, 201):
            return self._json(response, "create model")
        return self._poll_operation(response)

    def update_report_definition(
        self, workspace_id: str, report_id: str, parts: Any
    ) -> dict[str, Any]:
        path = (
            f"workspaces/{workspace_id}"
            f"/reports/{report_id}/updateDefinition"
        )
        response = self._transport.request(
            "POST", path, json=definition_payload(parts), allow=(200, 202)
        )
        if int(response.status_code) == 200:
            return self._json(response, "updateDefinition report")
        return self._poll_operation(response, expect_result=False)

    def create_report(
        self, workspace_id: str, display_name: str, parts: Any
    ) -> dict[str, Any]:
        body = {"displayName": str(display_name)}
        body.update(definition_payload(parts))
        response = self._transport.request(
            "POST",
            f"workspaces/{workspace_id}/reports",
            json=body,
            allow=(200, 201, 202),
        )
        if int(response.status_code) in (200, 201):
            return self._json(response, "create report")
        return self._poll_operation(response)

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

