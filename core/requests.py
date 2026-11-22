"""Objek permintaan (request) yang dipakai GUI dan CLI.

Request memisahkan pemetaan input pengguna dari use case di :mod:`core.jobs`,
:mod:`core.tsd`, dan :mod:`core.pbi_capture`. Modul ini tidak memakai Qt,
sehingga GUI dan CLI memakai aturan yang sama:

- satu daftar cakupan (``both``/``report``/``model``) menentukan langkah yang
  dijalankan;
- validasi GUID, endpoint, dan path terjadi sebelum pekerjaan berat dimulai;
- ``CaptureOptions`` disusun di satu tempat, bukan di dua tab/argparse.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from .errors import ExtractionError
from .fabric_api import ServiceReportRef

SCOPE_BOTH = "both"
SCOPE_REPORT = "report"
SCOPE_MODEL = "model"
SCOPES = (SCOPE_BOTH, SCOPE_REPORT, SCOPE_MODEL)


def validate_scope(scope: str) -> str:
    """Normalisasi cakupan ekstraksi; nilai asing ditolak."""
    value = str(scope or SCOPE_BOTH).strip().lower()
    if value not in SCOPES:
        raise ExtractionError(
            "Cakupan ekstraksi harus salah satu: " + ", ".join(SCOPES) + "."
        )
    return value


def split_scope(scope: str) -> tuple[bool, bool]:
    """Kembalikan ``(extract_report, extract_model)`` untuk satu cakupan."""
    value = validate_scope(scope)
    return value != SCOPE_MODEL, value != SCOPE_REPORT


def _path(value: Path | str) -> Path:
    return Path(value).expanduser()


@dataclass(frozen=True)
class LocalMetadataRequest:
    """Ekstraksi dari file ``.pbix`` lokal lewat instance Power BI Desktop."""

    out_dir: Path
    scope: str = SCOPE_BOTH
    pbix: Path | None = None
    port: int | None = None
    catalog: str | None = None
    include_usage: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", validate_scope(self.scope))
        object.__setattr__(self, "out_dir", _path(self.out_dir))
        if self.pbix is not None:
            object.__setattr__(self, "pbix", _path(self.pbix))
        if self.port is not None and int(self.port) <= 0:
            raise ExtractionError(f"Port instance Desktop tidak valid: {self.port}.")

    @property
    def extract_report(self) -> bool:
        return split_scope(self.scope)[0]

    @property
    def extract_model(self) -> bool:
        return split_scope(self.scope)[1]

    def to_job_kwargs(self) -> dict[str, Any]:
        """Argumen :func:`core.jobs.run_metadata_job` untuk sumber lokal."""
        return {
            "pbix": self.pbix,
            "out_dir": self.out_dir,
            "port": self.port,
            "catalog": self.catalog,
            "include_report_usage": self.include_usage,
            "extract_report": self.extract_report,
            "extract_model": self.extract_model,
            "validate_with_existing": True,
        }


MAX_BATCH_REPORTS = 25


@dataclass(frozen=True)
class ServiceMetadataRequest:
    """Ekstraksi report via Fabric API dan/atau model via endpoint XMLA."""

    out_dir: Path
    workspace_id: str = ""
    report_id: str = ""
    report_ids: tuple[str, ...] = ()
    report_names: tuple[tuple[str, str], ...] = ()
    endpoint: str = ""
    catalog: str = ""
    scope: str = SCOPE_BOTH
    include_usage: bool = True

    def __post_init__(self) -> None:
        scope = validate_scope(self.scope)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "out_dir", _path(self.out_dir))
        object.__setattr__(self, "workspace_id", (self.workspace_id or "").strip())
        object.__setattr__(self, "report_id", (self.report_id or "").strip())
        raw_ids = self.report_ids
        if isinstance(raw_ids, str):
            raw_ids = raw_ids.split(",")
        report_ids: list[str] = []
        for item in raw_ids or ():
            value = str(item or "").strip()
            if value and value not in report_ids:
                report_ids.append(value)
        object.__setattr__(self, "report_ids", tuple(report_ids))
        names: list[tuple[str, str]] = []
        raw_names = self.report_names or ()
        if isinstance(raw_names, dict):
            raw_names = list(raw_names.items())
        for item in raw_names:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                key, value = str(item[0] or "").strip(), str(item[1] or "").strip()
                if key and value:
                    names.append((key, value))
        object.__setattr__(self, "report_names", tuple(names))
        object.__setattr__(self, "endpoint", (self.endpoint or "").strip())
        object.__setattr__(self, "catalog", (self.catalog or "").strip())

        if report_ids and len(report_ids) > MAX_BATCH_REPORTS:
            raise ExtractionError(
                f"Maksimal {MAX_BATCH_REPORTS} report per batch; "
                f"dipilih {len(report_ids)}."
            )
        if scope != SCOPE_MODEL:
            if not self.workspace_id or not (self.report_id or report_ids):
                raise ExtractionError(
                    "Sumber report Power BI Service belum lengkap: isi Workspace ID "
                    "dan Report ID (atau pilih beberapa report)."
                )
            # Validasi GUID dilakukan di satu tempat: ServiceReportRef.
            for item in self.report_ids or ((self.report_id,) if self.report_id else ()):
                ServiceReportRef.from_ids(self.workspace_id, item)
        if scope != SCOPE_REPORT and not self.endpoint:
            raise ExtractionError(
                "Endpoint XMLA workspace belum diisi; model service tidak bisa "
                "diekstrak tanpa endpoint."
            )
        if report_ids and scope == SCOPE_MODEL:
            raise ExtractionError(
                "Batch report tidak bisa dipakai dengan cakupan model saja."
            )

    @property
    def extract_report(self) -> bool:
        return split_scope(self.scope)[0]

    @property
    def extract_model(self) -> bool:
        return split_scope(self.scope)[1]

    @property
    def service_ref(self) -> ServiceReportRef | None:
        """Referensi report pertama; ``None`` bila cakupan hanya model."""
        refs = self.service_refs
        return refs[0] if refs else None

    @property
    def service_refs(self) -> tuple[ServiceReportRef, ...]:
        """Semua referensi report (satu atau batch); kosong bila model saja."""
        if not self.extract_report:
            return ()
        ids = self.report_ids or ((self.report_id,) if self.report_id else ())
        return tuple(
            ServiceReportRef.from_ids(self.workspace_id, item) for item in ids
        )

    @property
    def batch(self) -> bool:
        return len(self.report_ids) > 1

    def to_job_kwargs(self) -> dict[str, Any]:
        """Argumen :func:`core.jobs.run_metadata_job` untuk sumber service.

        Token dan provider tidak termasuk karena objek runtime disiapkan
        pemanggil (GUI/CLI), bukan bagian dari input pengguna.
        """
        payload: dict[str, Any] = {
            "service_mode": True,
            "endpoint": self.endpoint or None,
            "catalog": self.catalog or None,
            "port": None,
            "out_dir": self.out_dir,
            "include_report_usage": self.include_usage,
            "extract_report": self.extract_report,
            "extract_model": self.extract_model,
            "validate_with_existing": True,
        }
        refs = self.service_refs
        if len(refs) > 1:
            payload["service_reports"] = refs
            if self.report_names:
                payload["service_report_names"] = dict(self.report_names)
        else:
            payload["service_report"] = refs[0] if refs else None
        return payload


@dataclass(frozen=True)
class TsdRequest:
    """Input generate dokumen TSD dari workbook metadata."""

    report_workbook: Path
    model_workbook: Path | None = None
    out_file: Path | None = None
    manual_path: Path | None = None
    manual: Mapping[str, Any] | None = None
    report_name: str = ""
    report_id: str = ""
    draft: bool = True
    expand_all: bool = False
    generated_at: str | None = None
    template_path: Path | None = None
    include_decorative: bool = False

    def __post_init__(self) -> None:
        report = _path(self.report_workbook)
        if report.suffix.lower() != ".xlsx":
            raise ExtractionError(f"Workbook report harus file .xlsx: {report}")
        object.__setattr__(self, "report_workbook", report)
        object.__setattr__(self, "model_workbook", self._optional(self.model_workbook))
        object.__setattr__(self, "out_file", self._optional(self.out_file))
        object.__setattr__(self, "manual_path", self._optional(self.manual_path))
        object.__setattr__(
            self, "template_path", self._optional(self.template_path)
        )
        object.__setattr__(self, "report_name", (self.report_name or "").strip())
        object.__setattr__(self, "report_id", (self.report_id or "").strip())
        generated = (self.generated_at or "").strip()
        object.__setattr__(self, "generated_at", generated or None)

    @staticmethod
    def _optional(value: Path | str | None) -> Path | None:
        return _path(value) if value else None

    def to_run_kwargs(self) -> dict[str, Any]:
        """Argumen :func:`core.tsd.run_tsd` (tanpa ``capture`` dan ``log``)."""
        return {
            "report_workbook": self.report_workbook,
            "model_workbook": self.model_workbook,
            "out_file": self.out_file,
            "manual_path": self.manual_path,
            "manual": self.manual,
            "report_name": self.report_name,
            "report_id": self.report_id,
            "draft": self.draft,
            "expand_all": self.expand_all,
            "generated_at": self.generated_at,
            "template_path": self.template_path,
            "include_decorative_visuals": self.include_decorative,
        }


@dataclass(frozen=True)
class CaptureRequest:
    """Input capture screenshot Power BI Service (embed + RLS + Playwright)."""

    workspace_id: str
    report_id: str
    rls_username: str = ""
    rls_roles: tuple[str, ...] = ()
    scope: str = "both"
    scale: float = 1.0
    headless: bool = True
    output_root: Path | None = None
    refresh: bool = False
    reveal_bookmarks: bool = True
    mobile: bool = True
    include_decorative: bool = False
    hints_workbook: Path | None = None
    auto_install_browser: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspace_id", (self.workspace_id or "").strip())
        object.__setattr__(self, "report_id", (self.report_id or "").strip())
        object.__setattr__(self, "rls_username", (self.rls_username or "").strip())
        object.__setattr__(self, "rls_roles", tuple(self.rls_roles or ()))
        object.__setattr__(self, "scope", str(self.scope or "both").strip().lower())
        if self.output_root is not None:
            object.__setattr__(self, "output_root", _path(self.output_root))
        if self.hints_workbook is not None:
            object.__setattr__(self, "hints_workbook", _path(self.hints_workbook))

    def to_options(self, token_provider: Any | None = None) -> Any:
        """Susun ``CaptureOptions``; validasi GUID/skala memakai aturan runner."""
        from .pbi_capture.assets import DECORATIVE_VISUAL_TYPES
        from .pbi_capture.credentials import CaptureCredentials
        from .pbi_capture.runner import CaptureOptions

        exclude = (
            ()
            if self.include_decorative
            else tuple(sorted(DECORATIVE_VISUAL_TYPES))
        )
        return CaptureOptions(
            workspace_id=self.workspace_id,
            report_id=self.report_id,
            credentials=CaptureCredentials(
                rls_username=self.rls_username,
                rls_roles=self.rls_roles,
            ),
            token_provider=token_provider,
            scope=self.scope,
            scale=self.scale,
            headless=self.headless,
            output_root=self.output_root,
            refresh=self.refresh,
            reveal_bookmarks=self.reveal_bookmarks,
            mobile=self.mobile,
            exclude_visual_types=exclude,
            hints_workbook=self.hints_workbook,
            auto_install_browser=self.auto_install_browser,
        )


# ---------------------------------------------------------------------------
# Analisa Semantic Model
# ---------------------------------------------------------------------------
def _guid(value: str, label: str) -> str:
    """Normalisasi GUID; nilai kosong/asing ditolak dengan pesan yang jelas."""
    text = str(value or "").strip()
    if not text:
        raise ExtractionError(f"{label} masih kosong.")
    try:
        parsed = UUID(text)
    except ValueError as exc:
        raise ExtractionError(f"{label} bukan GUID yang valid: {text}.") from exc
    return str(parsed)


@dataclass(frozen=True)
class AnalysisRequest:
    """Input analisa kolom semantic model Power BI Service (read-only).

    Nama workspace/dataset dipakai untuk endpoint XMLA dan catalog; bila kosong,
    CLI/GUI mengisinya dari katalog SQLite (:func:`core.usage_service.resolve_names`).
    """

    workspace_id: str
    dataset_id: str
    workspace_name: str = ""
    dataset_name: str = ""
    output: Path | None = None
    database: Path | None = None
    include_other_workspaces: bool = True
    include_personal: bool = False
    include_reports: bool = True
    refresh: bool = False
    max_reports: int | None = None
    scan_workers: int = 2

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "workspace_id", _guid(self.workspace_id, "Workspace ID")
        )
        object.__setattr__(self, "dataset_id", _guid(self.dataset_id, "Semantic model ID"))
        object.__setattr__(self, "workspace_name", str(self.workspace_name or "").strip())
        object.__setattr__(self, "dataset_name", str(self.dataset_name or "").strip())
        if self.output is not None:
            target = _path(self.output)
            if target.suffix.lower() not in {".xlsx"}:
                target = target.with_suffix(".xlsx")
            object.__setattr__(self, "output", target)
        object.__setattr__(self, "database", self.database and _path(self.database))
        if self.max_reports is not None:
            value = int(self.max_reports)
            if value <= 0:
                raise ExtractionError(
                    f"Batas report per analisa harus > 0: {self.max_reports}."
                )
            object.__setattr__(self, "max_reports", value)
        try:
            workers = int(self.scan_workers)
        except (TypeError, ValueError) as exc:
            raise ExtractionError(
                f"Jumlah worker scan report tidak valid: {self.scan_workers}."
            ) from exc
        if workers < 1 or workers > 4:
            raise ExtractionError(
                f"Jumlah worker scan report harus 1-4: {self.scan_workers}."
            )
        object.__setattr__(self, "scan_workers", workers)

    def to_run_kwargs(self) -> dict[str, Any]:
        """Argumen :func:`core.usage_service.analyze_dataset` (tanpa kredensial)."""
        payload: dict[str, Any] = {
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
            "include_other_workspaces": self.include_other_workspaces,
            "include_personal": self.include_personal,
            "include_reports": self.include_reports,
            "refresh": self.refresh,
            "max_reports": self.max_reports,
            "scan_workers": self.scan_workers,
        }
        if self.database is not None:
            payload["database"] = self.database
        return payload


# ---------------------------------------------------------------------------
# Partisi semantic model (inventaris read-only + refresh lewat XMLA)
# ---------------------------------------------------------------------------
PARTITION_CONFIRMATION = "PROCESS"


@dataclass(frozen=True)
class PartitionRequest:
    """Input inventaris partisi satu semantic model Power BI Service."""

    workspace_id: str
    dataset_id: str
    workspace_name: str = ""
    dataset_name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "workspace_id", _guid(self.workspace_id, "Workspace ID")
        )
        object.__setattr__(self, "dataset_id", _guid(self.dataset_id, "Semantic model ID"))
        object.__setattr__(self, "workspace_name", str(self.workspace_name or "").strip())
        object.__setattr__(self, "dataset_name", str(self.dataset_name or "").strip())

    def to_inventory_kwargs(self) -> dict[str, Any]:
        """Argumen :func:`core.partition_service.read_partition_inventory`."""
        return {
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "dataset_id": self.dataset_id,
            "dataset_name": self.dataset_name,
        }


@dataclass(frozen=True)
class PartitionRefreshRequest(PartitionRequest):
    """Input refresh partisi; konfirmasi wajib ``PROCESS``."""

    targets: tuple[tuple[str, str], ...] = ()
    refresh_type: str = "full"
    confirmation: str = ""

    def __post_init__(self) -> None:
        PartitionRequest.__post_init__(self)
        pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in self.targets or ():
            if isinstance(item, Mapping):
                table = str(item.get("table") or "").strip()
                partition = str(item.get("partition") or "").strip()
            else:
                try:
                    table, partition = item
                except (TypeError, ValueError) as exc:
                    raise ExtractionError(
                        "Target partisi harus berisi pasangan (table, partition)."
                    ) from exc
                table = str(table or "").strip()
                partition = str(partition or "").strip()
            if not table or not partition:
                raise ExtractionError("Nama tabel dan partisi tidak boleh kosong.")
            key = (table, partition)
            if key not in seen:
                seen.add(key)
                pairs.append(key)
        if not pairs:
            raise ExtractionError("Pilih minimal satu partisi untuk diproses.")
        object.__setattr__(self, "targets", tuple(pairs))

        from .partition_plan import normalize_refresh_type

        normalized = normalize_refresh_type(self.refresh_type)
        object.__setattr__(self, "refresh_type", normalized)
        confirmation = str(self.confirmation or "").strip().upper()
        if confirmation != PARTITION_CONFIRMATION:
            raise ExtractionError(
                f"Ketik {PARTITION_CONFIRMATION} untuk mengonfirmasi refresh partisi."
            )
        object.__setattr__(self, "confirmation", confirmation)

    def to_refresh_kwargs(self) -> dict[str, Any]:
        """Argumen :func:`core.partition_service.process_partitions`."""
        payload = self.to_inventory_kwargs()
        payload.update(
            {
                "targets": self.targets,
                "refresh_type": self.refresh_type,
            }
        )
        return payload

# ---------------------------------------------------------------------------
# Perbandingan semantic model (read-only)
# ---------------------------------------------------------------------------
COMPARE_SIDE_DATASET = "dataset"
COMPARE_SIDE_DESKTOP = "desktop"


@dataclass(frozen=True)
class CompareSide:
    """Satu sisi perbandingan: dataset Service atau instance Desktop."""

    kind: str = COMPARE_SIDE_DATASET
    workspace_id: str = ""
    dataset_id: str = ""
    workspace_name: str = ""
    dataset_name: str = ""
    port: int = 0
    catalog: str = ""

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip().lower()
        if kind not in {COMPARE_SIDE_DATASET, COMPARE_SIDE_DESKTOP}:
            raise ExtractionError("Tipe sumber harus 'dataset' atau 'desktop'.")
        object.__setattr__(self, "kind", kind)
        if kind == COMPARE_SIDE_DATASET:
            object.__setattr__(
                self, "workspace_id", _guid(self.workspace_id, "Workspace ID")
            )
            object.__setattr__(
                self, "dataset_id", _guid(self.dataset_id, "Semantic model ID")
            )
            object.__setattr__(
                self, "workspace_name", str(self.workspace_name or "").strip()
            )
            object.__setattr__(
                self, "dataset_name", str(self.dataset_name or "").strip()
            )
        else:
            try:
                port = int(self.port)
            except (TypeError, ValueError) as exc:
                raise ExtractionError("Port instance Desktop tidak valid.") from exc
            if port <= 0:
                raise ExtractionError("Pilih instance Power BI Desktop dulu.")
            catalog = str(self.catalog or "").strip()
            if not catalog:
                raise ExtractionError("Catalog instance Desktop masih kosong.")
            object.__setattr__(self, "port", port)
            object.__setattr__(self, "catalog", catalog)

    @classmethod
    def from_payload(cls, value: Mapping[str, Any] | None) -> "CompareSide":
        payload = dict(value or {})
        return cls(
            kind=str(payload.get("type") or payload.get("kind") or ""),
            workspace_id=str(payload.get("workspace_id") or ""),
            dataset_id=str(payload.get("dataset_id") or ""),
            workspace_name=str(payload.get("workspace_name") or ""),
            dataset_name=str(payload.get("dataset_name") or ""),
            port=payload.get("port") or 0,
            catalog=str(payload.get("catalog") or ""),
        )

    @property
    def identity(self) -> tuple[str, str, str]:
        if self.kind == COMPARE_SIDE_DESKTOP:
            return (self.kind, str(self.port), self.catalog.casefold())
        return (self.kind, self.workspace_id, self.dataset_id)

    def to_payload(self) -> dict[str, Any]:
        if self.kind == COMPARE_SIDE_DESKTOP:
            return {
                "type": self.kind,
                "port": self.port,
                "catalog": self.catalog,
            }
        return {
            "type": self.kind,
            "workspace_id": self.workspace_id,
            "dataset_id": self.dataset_id,
            "workspace_name": self.workspace_name,
            "dataset_name": self.dataset_name,
        }


@dataclass(frozen=True)
class CompareRequest:
    """Input perbandingan dua semantic model; tidak pernah menulis target."""

    source: CompareSide
    target: CompareSide
    options: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, CompareSide) or not isinstance(
            self.target, CompareSide
        ):
            raise ExtractionError("Sumber dan target perbandingan tidak valid.")
        if self.source.identity == self.target.identity:
            raise ExtractionError("Sumber dan target tidak boleh model yang sama.")

    @classmethod
    def from_payload(cls, value: Mapping[str, Any] | None) -> "CompareRequest":
        payload = dict(value or {})
        source = CompareSide.from_payload(payload.get("source"))
        target = CompareSide.from_payload(payload.get("target"))
        options = payload.get("options")
        if options is not None and not isinstance(options, Mapping):
            raise ExtractionError("Opsi perbandingan tidak valid.")
        return cls(source=source, target=target, options=options)

    def to_run_kwargs(self) -> dict[str, Any]:
        return {
            "source": self.source.to_payload(),
            "target": self.target.to_payload(),
            "options": dict(self.options or {}),
        }

