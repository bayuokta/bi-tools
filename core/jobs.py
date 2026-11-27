"""Orkestrasi ekstraksi yang dipakai bersama oleh CLI dan GUI."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .auth import EntraTokens, TokenProvider
from .errors import ExtractionError
from .fabric_api import (
    FabricReportClient,
    ReportDefinition,
    ServiceReportRef,
    ServiceSourceInfo,
    materialize_definition,
)
from .model import DEFAULT_OUT as DEFAULT_MODEL_OUT
from .model import run_model
from .pbix import (
    PbixSourceInfo,
    detect_pbix_source,
    display_path,
    report_workspace,
    resolve_pbix,
)
from .paths import outputs_dir
from .report import OUT_FILE, resolve_validation_model, run_report

Log = Callable[[str], None]


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


@dataclass(frozen=True)
class MetadataJobResult:
    """Ringkasan satu kali ekstraksi; report dan model sama-sama opsional."""

    source: PbixSourceInfo | ServiceSourceInfo
    report: dict[str, Any] | None
    model: dict[str, Any] | None
    report_out: Path | None
    model_out: Path | None
    model_error: str = ""
    outputs: tuple[Path, ...] = ()
    batch: tuple[dict[str, Any], ...] = ()
    summary_out: Path | None = None

    @property
    def output_count(self) -> int:
        return len(self.outputs)


def _run_report_from_definition(
    report_def: Path,
    report_source: str,
    *,
    model_workbook: Path | None,
    no_model: bool,
    out_file: Path | None,
    report_kind: str,
    validation_dir: Path | None,
    log: Log,
) -> dict[str, Any]:
    tables, inventory, model_source = resolve_validation_model(
        no_model, model_workbook, validation_dir
    )
    return run_report(
        report_def,
        report_source,
        tables,
        inventory,
        model_source,
        out_file or OUT_FILE,
        report_kind=report_kind,
        log=log,
    )


def run_report_job(
    pbix: Path | None = None,
    model_workbook: Path | None = None,
    no_model: bool = False,
    out_file: Path | None = None,
    extract_to: str | None = None,
    report_kind: str = "",
    validation_dir: Path | None = None,
    log: Log = _silent,
) -> dict[str, Any]:
    """Ekstrak report dari .pbix, validasi model opsional, lalu tulis Report_Metadata.xlsx.

    ``validation_dir`` dipakai untuk mencari workbook model di folder output bila
    ``model_workbook`` tidak diberikan.
    """
    with report_workspace(extract_to) as workdir:
        report_def, report_source = resolve_pbix(pbix, workdir)
        return _run_report_from_definition(
            report_def,
            report_source,
            model_workbook=model_workbook,
            no_model=no_model,
            out_file=out_file,
            report_kind=report_kind,
            validation_dir=validation_dir,
            log=log,
        )


def fetch_service_report_definition(
    service: ServiceReportRef,
    token_provider: TokenProvider,
    *,
    client: FabricReportClient | None = None,
    log: Log = _silent,
) -> ReportDefinition:
    """Ambil definition mentah report service; client bisa diganti tiruan pada uji."""
    owned = client is None
    fabric = client or FabricReportClient(token_provider, log=log)
    try:
        log(
            f"Fetching report definition {service.report_id} "
            f"from workspace {service.workspace_id}..."
        )
        return fabric.get_report_definition(service)
    finally:
        if owned:
            fabric.close()


def run_service_report_job(
    service: ServiceReportRef,
    token_provider: TokenProvider,
    model_workbook: Path | None = None,
    no_model: bool = False,
    out_file: Path | None = None,
    report_kind: str = "",
    validation_dir: Path | None = None,
    client: FabricReportClient | None = None,
    log: Log = _silent,
) -> dict[str, Any]:
    """Ambil report public definition dari Power BI Service lalu tulis workbook report.

    ``client`` bisa diganti objek tiruan pada uji; bila None, FabricReportClient
    dibuat dan ditutup otomatis.
    """
    definition = fetch_service_report_definition(
        service, token_provider, client=client, log=log
    )
    log(f"Format definition : {definition.report_format}")
    if definition.model_reference:
        log(f"Semantic model    : {definition.model_reference}")
    with report_workspace(None) as workdir:
        report_def = materialize_definition(definition, workdir)
        report_source = (
            f"service Power BI workspace {service.workspace_id} "
            f"report {service.report_id} ({definition.report_format})"
        )
        return _run_report_from_definition(
            report_def,
            report_source,
            model_workbook=model_workbook,
            no_model=no_model,
            out_file=out_file,
            report_kind=report_kind,
            validation_dir=validation_dir,
            log=log,
        )


def _run_service_metadata_job(
    service: ServiceReportRef | None,
    token_provider: TokenProvider | None,
    *,
    out_dir: Path | None,
    endpoint: str | None,
    catalog: str | None,
    port: int | None,
    include_report_usage: bool,
    extract_report: bool,
    extract_model: bool,
    validate_with_existing: bool,
    tokens: EntraTokens | None = None,
    log: Log,
) -> MetadataJobResult:
    """Jalur Power BI Service: report via getDefinition, model via XMLA manual."""
    if not extract_report and not extract_model:
        raise ExtractionError(
            "Nothing to extract: both report and model scopes are disabled."
        )
    if extract_report and service is None:
        raise ExtractionError(
            "No Power BI Service report source selected (report URL or Workspace ID + Report ID)."
        )
    if extract_report and token_provider is None:
        raise ExtractionError("The Fabric token is not ready for the Power BI Service source.")
    if extract_model and not endpoint and port is None:
        log(
            "Model            : skipped (no Desktop instance selected / empty XMLA endpoint)"
        )
        extract_model = False

    usage = bool(include_report_usage and extract_model and extract_report)
    if include_report_usage and extract_model and not usage:
        log("Usage report     : skipped (report scope is not active)")

    target_dir = (out_dir or outputs_dir()).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    report_out = target_dir / OUT_FILE.name
    model_out = target_dir / DEFAULT_MODEL_OUT.name

    log("Source type      : Power BI Service")
    if service is not None:
        log(f"Workspace        : {service.workspace_id}")
        log(f"Report           : {service.report_id}")
    if extract_model:
        if endpoint:
            log(f"Endpoint XMLA    : {endpoint}")
        else:
            log(f"Instance Desktop : port {port}")
        if catalog:
            log(f"Catalog          : {catalog}")

    definition: ReportDefinition | None = None
    report_def: Path | None = None
    with report_workspace(None) as workdir:
        if extract_report:
            definition = fetch_service_report_definition(
                service, token_provider, log=log
            )
            log(f"Format definition : {definition.report_format}")
            if definition.model_reference:
                log(f"Semantic model    : {definition.model_reference}")
            report_def = materialize_definition(definition, workdir)

        model_result: dict[str, Any] | None = None
        model_path: Path | None = None
        model_error = ""
        if extract_model:
            log("")
            log("=== Semantic model extraction (XMLA) ===")
            try:
                model_result = run_model(
                    endpoint=endpoint,
                    catalog=catalog,
                    port=port,
                    report=None,
                    report_definition=report_def if usage else None,
                    report_label=(
                        f"report Power BI Service {service.report_id}"
                        if usage and service is not None
                        else ""
                    ),
                    no_report=not usage,
                    out_file=model_out,
                    tokens=tokens,
                    log=log,
                )
                model_path = model_out
            except ExtractionError as exc:
                model_error = str(exc)
                log(f"WARNING: model extraction skipped: {exc}")
                if extract_report:
                    log("WARNING: the report is still extracted without model validation.")
                else:
                    log("WARNING: no model file was created.")
                if model_out.exists():
                    log(
                        f"WARNING: {display_path(model_out)} was not updated "
                        "and may be out of date."
                    )

        report_result: dict[str, Any] | None = None
        report_path: Path | None = None
        if extract_report:
            log("")
            log("=== Report extraction ===")
            report_result = _run_report_from_definition(
                report_def,
                f"service Power BI workspace {service.workspace_id} "
                f"report {service.report_id} ({definition.report_format})",
                model_workbook=model_path,
                no_model=model_path is None
                and (bool(model_error) or not validate_with_existing),
                out_file=report_out,
                report_kind="Power BI Service",
                validation_dir=target_dir,
                log=log,
            )
            report_path = report_out

    if report_path is None and model_path is None:
        reason = model_error or "no work selected"
        raise ExtractionError(
            "No files were created: report and model extraction did not run "
            f"({reason})."
        )

    outputs: list[Path] = []
    if report_path is not None:
        outputs.append(report_path)
    if model_path is not None:
        outputs.append(model_path)
    log("")
    log(f"Done. {len(outputs)} files created: " + ", ".join(display_path(p) for p in outputs))

    return MetadataJobResult(
        source=ServiceSourceInfo(
            service.workspace_id if service is not None else "",
            service.report_id if service is not None else "",
            definition.report_format if definition is not None else "",
        ),
        report=report_result,
        model=model_result,
        report_out=report_path,
        model_out=model_path,
        model_error=model_error,
        outputs=tuple(outputs),
    )


def _safe_folder(value: str, fallback: str = "Report") -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:80] or fallback


def _write_batch_summary(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "Workspace",
        "Report ID",
        "Report Name",
        "Status",
        "Pages",
        "Visuals",
        "Fields",
        "Output",
        "Message",
    ]
    frame = pd.DataFrame(rows, columns=columns)
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="Batch_Summary", index=False)
    return path


def _run_service_batch_job(
    reports: Sequence[ServiceReportRef],
    token_provider: TokenProvider | None,
    *,
    out_dir: Path | None,
    endpoint: str | None,
    catalog: str | None,
    port: int | None,
    include_report_usage: bool,
    extract_model: bool,
    validate_with_existing: bool,
    names: dict[str, str] | None = None,
    tokens: EntraTokens | None = None,
    log: Log = _silent,
    progress: Any = None,
    should_stop: Any = None,
) -> MetadataJobResult:
    """Ekstrak beberapa report Power BI Service (satu workspace/dataset).

    Model diekstrak sekali tanpa usage report (usage gabungan belum didukung),
    setiap report ditulis ke folder ``<Nama>_<8 ID>/Report_Metadata.xlsx``, dan
    ringkasan ditulis ke ``Batch_Summary.xlsx``. Kegagalan satu report tidak
    membatalkan report lain.
    """
    if not reports:
        raise ExtractionError("Batch reports are empty.")
    if token_provider is None:
        raise ExtractionError("The Fabric token is not ready for batch reports.")
    workspace_id = reports[0].workspace_id
    if any(item.workspace_id != workspace_id for item in reports):
        raise ExtractionError(
            "Batch reports must be in the same workspace."
        )
    if extract_model and not endpoint and port is None:
        log("Model            : skipped (empty XMLA endpoint)")
        extract_model = False
    if include_report_usage and extract_model:
        log(
            "Usage report     : skipped for batches (the model is extracted once; "
            "run a single report for combined usage)."
        )

    target_dir = (out_dir or outputs_dir()).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    model_out = target_dir / DEFAULT_MODEL_OUT.name
    summary_out = target_dir / "Batch_Summary.xlsx"

    log("Source type      : Power BI Service (batch)")
    log(f"Workspace        : {workspace_id}")
    log(f"Reports          : {len(reports)}")
    if extract_model:
        log(f"Endpoint XMLA    : {endpoint or f'port {port}'}")
        if catalog:
            log(f"Catalog          : {catalog}")

    model_result: dict[str, Any] | None = None
    model_path: Path | None = None
    model_error = ""
    if extract_model:
        log("")
        log("=== Semantic model extraction (XMLA) ===")
        try:
            model_result = run_model(
                endpoint=endpoint,
                catalog=catalog,
                port=port,
                no_report=True,
                out_file=model_out,
                tokens=tokens,
                log=log,
            )
            model_path = model_out
        except ExtractionError as exc:
            model_error = str(exc)
            log(f"WARNING: model extraction skipped: {exc}")
            log("WARNING: the report is still extracted without model validation.")

    rows: list[dict[str, Any]] = []
    outputs: list[Path] = []
    client = FabricReportClient(token_provider, log=log)
    try:
        for index, service in enumerate(reports, start=1):
            if should_stop is not None and should_stop():
                rows.append(
                    {
                        "Workspace": workspace_id,
                        "Report ID": service.report_id,
                        "Report Name": (names or {}).get(service.report_id, ""),
                        "Status": "cancelled",
                        "Pages": 0,
                        "Visuals": 0,
                        "Fields": 0,
                        "Output": "",
                        "Message": "Cancelled by the user.",
                    }
                )
                log("Batch stopped at the user request.")
                break
            name = str((names or {}).get(service.report_id) or "")
            label = f"{name or 'Report'} ({service.report_id[:8]})"
            if progress is not None:
                progress(index, len(reports), label)
            log("")
            log(f"[{index}/{len(reports)}] {label}")
            row: dict[str, Any] = {
                "Workspace": workspace_id,
                "Report ID": service.report_id,
                "Report Name": name,
                "Status": "failed",
                "Pages": 0,
                "Visuals": 0,
                "Fields": 0,
                "Output": "",
                "Message": "",
            }
            try:
                with report_workspace(None) as workdir:
                    definition = client.get_report_definition(service)
                    log(f"Format definition : {definition.report_format}")
                    report_def = materialize_definition(definition, workdir)
                    folder = target_dir / (
                        f"{_safe_folder(name, 'Report')}_{service.report_id[:8]}"
                    )
                    folder.mkdir(parents=True, exist_ok=True)
                    report_out = folder / OUT_FILE.name
                    result = _run_report_from_definition(
                        report_def,
                        f"service Power BI workspace {workspace_id} "
                        f"report {service.report_id} ({definition.report_format})",
                        model_workbook=model_path,
                        no_model=model_path is None
                        and (bool(model_error) or not validate_with_existing),
                        out_file=report_out,
                        report_kind="Power BI Service",
                        validation_dir=folder,
                        log=log,
                    )
                row.update(
                    {
                        "Status": "ok",
                        "Pages": int(result.get("pages") or 0),
                        "Visuals": int(result.get("visuals") or 0),
                        "Fields": int(result.get("fields") or 0),
                        "Output": str(report_out),
                        "Message": (
                            f"{int(result.get('validation_issues') or 0)} validation issues"
                        ),
                    }
                )
                outputs.append(report_out)
            except Exception as exc:  # noqa: BLE001 - lanjut report lain
                message = str(exc).splitlines()[0][:300]
                row["Message"] = message
                log(f"  FAILED: {message}")
            rows.append(row)
    finally:
        client.close()

    if extract_model and model_path is not None:
        outputs.insert(0, model_path)
    summary = _write_batch_summary(summary_out, rows)
    outputs.append(summary)
    done = sum(1 for row in rows if row.get("Status") == "ok")
    log("")
    log(
        f"Batch finished: {done}/{len(reports)} reports succeeded. "
        f"Summary: {display_path(summary)}"
    )
    source = ServiceSourceInfo(
        workspace_id=workspace_id,
        report_id="",
        report_ids=tuple(item.report_id for item in reports),
    )
    return MetadataJobResult(
        source=source,
        report=None,
        model=model_result,
        report_out=None,
        model_out=model_path,
        model_error=model_error,
        outputs=tuple(outputs),
        batch=tuple(rows),
        summary_out=summary,
    )


def run_metadata_job(
    pbix: Path | None = None,
    out_dir: Path | None = None,
    endpoint: str | None = None,
    catalog: str | None = None,
    port: int | None = None,
    include_report_usage: bool = True,
    extract_model: bool = True,
    extract_report: bool = True,
    validate_with_existing: bool = True,
    service_mode: bool = False,
    service_report: ServiceReportRef | None = None,
    service_reports: Sequence[ServiceReportRef] | None = None,
    service_report_names: dict[str, str] | None = None,
    token_provider: TokenProvider | None = None,
    tokens: EntraTokens | None = None,
    log: Log = _silent,
    progress: Any = None,
    should_stop: Any = None,
) -> MetadataJobResult:
    """Deteksi jenis .pbix lalu jalankan report dan/atau model sesuai cakupan.

    - ``extract_report``/``extract_model`` menentukan file yang dibuat; report dan
      model sama-sama opsional, tetapi minimal satu harus berjalan.
    - Model lokal: model diekstrak via XMLA lebih dulu, lalu report divalidasi
      dengan workbook model yang baru dibuat.
    - ``validate_with_existing``: bila model tidak diekstrak, report tetap
      divalidasi memakai workbook model yang ada di folder output lalu folder tooling.
    - Live connection: hanya report; validasi memakai workbook yang ada bila tersedia.
    - Kegagalan model tidak membatalkan report; report tetap dibuat tanpa validasi.
    - Cakupan model saja tanpa sumber model yang bisa diekstrak dianggap error.
    - ``service_mode`` mengalihkan sumber ke Power BI Service: report lewat Fabric
      API, model lewat endpoint XMLA manual (``endpoint`` + ``catalog``).
    - ``service_reports`` (lebih dari satu) menjalankan batch: model diekstrak
      sekali, setiap report ke folder sendiri, ringkasan `Batch_Summary.xlsx`.
    """
    if service_mode and service_reports:
        if len(service_reports) > 1:
            return _run_service_batch_job(
                service_reports,
                token_provider,
                out_dir=out_dir,
                endpoint=endpoint,
                catalog=catalog,
                port=port,
                include_report_usage=include_report_usage,
                extract_model=extract_model,
                validate_with_existing=validate_with_existing,
                names=service_report_names,
                tokens=tokens,
                log=log,
                progress=progress,
                should_stop=should_stop,
            )
        service_report = service_reports[0]
    if service_mode or service_report is not None:
        return _run_service_metadata_job(
            service_report,
            token_provider,
            out_dir=out_dir,
            endpoint=endpoint,
            catalog=catalog,
            port=port,
            include_report_usage=include_report_usage,
            extract_report=extract_report,
            extract_model=extract_model,
            validate_with_existing=validate_with_existing,
            tokens=tokens,
            log=log,
        )

    if pbix is None:
        raise ExtractionError(
            "A .pbix file is required (--report). There is no default file."
        )
    pbix_path = pbix.resolve()

    source = detect_pbix_source(pbix_path)
    log(f"Source type      : {source.label}")
    if source.has_local_model:
        log("Model            : stored inside the .pbix (extraction via XMLA)")
    elif source.is_live_connection:
        dataset = f" {source.dataset_id}" if source.dataset_id else ""
        log(f"Model            : not available (live connection to dataset{dataset})")
    else:
        log("Model            : not available (source type not recognized)")
    if not source.has_pbir:
        log("WARNING: Report/definition not found; the file may still use legacy Report/Layout.")
    if not extract_report:
        log("Report           : skipped (semantic model scope only)")

    target_dir = (out_dir or outputs_dir()).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    report_out = target_dir / OUT_FILE.name
    model_out = target_dir / DEFAULT_MODEL_OUT.name

    model_result: dict[str, Any] | None = None
    model_path: Path | None = None
    model_error = ""
    model_target_missing = not endpoint and port is None and not catalog
    if not source.has_local_model:
        model_skip_reason = (
            "thin report" if source.is_live_connection else "source type not recognized"
        )
    elif not extract_model:
        model_skip_reason = "model extraction option is off"
    elif model_target_missing:
        model_skip_reason = "no Desktop instance selected / not open"
    else:
        model_skip_reason = ""

    if model_skip_reason:
        log(f"Model            : skipped ({model_skip_reason})")
    else:
        log("")
        log("=== Semantic model extraction (XMLA) ===")
        try:
            model_result = run_model(
                endpoint=endpoint,
                catalog=catalog,
                port=port,
                report=pbix_path,
                no_report=not include_report_usage,
                out_file=model_out,
                tokens=tokens,
                log=log,
            )
            model_path = model_out
        except ExtractionError as exc:
            model_error = str(exc)
            model_skip_reason = str(exc)
            log(f"WARNING: model extraction skipped: {exc}")
            if extract_report:
                log("WARNING: the report is still extracted without model validation.")
            else:
                log("WARNING: no model file was created.")
            if model_out.exists():
                log(f"WARNING: {display_path(model_out)} was not updated and may be out of date.")

    report_result: dict[str, Any] | None = None
    report_path: Path | None = None
    if extract_report:
        log("")
        log("=== Report extraction ===")
        report_result = run_report_job(
            pbix=pbix_path,
            model_workbook=model_path,
            # model yang gagal diekstrak tidak boleh diganti workbook lama (bisa usang)
            no_model=model_path is None and (bool(model_error) or not validate_with_existing),
            out_file=report_out,
            report_kind=source.label,
            validation_dir=target_dir,
            log=log,
        )
        report_path = report_out

    if report_path is None and model_path is None:
        if not extract_report and not extract_model:
            reason = "both scopes (report and model) are disabled"
        else:
            reason = model_error or model_skip_reason or "no work selected"
        raise ExtractionError(
            "No files were created: report extraction was skipped and model extraction "
            f"did not run ({reason})."
        )

    outputs: list[Path] = []
    if report_path is not None:
        outputs.append(report_path)
    if model_path is not None:
        outputs.append(model_path)
    log("")
    log(f"Done. {len(outputs)} files created: " + ", ".join(display_path(path) for path in outputs))

    return MetadataJobResult(
        source=source,
        report=report_result,
        model=model_result,
        report_out=report_path,
        model_out=model_path,
        model_error=model_error,
        outputs=tuple(outputs),
    )
