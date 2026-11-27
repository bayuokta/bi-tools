"""Orkestrasi inventaris dan proses partisi semantic model.

Modul ini **tidak** memuat TOM maupun ADOMD. Keduanya dijalankan di proses CLI
terpisah karena membawa versi assembly ``Microsoft.AnalysisServices`` yang
tidak kompatibel dalam satu proses:

- ``partition --inventory-json`` / ``partition --refresh-json`` memakai TOM;
- ``partition --dmv-json`` memakai ADOMD untuk ``RECORDS_COUNT`` per partisi.

Dengan begitu proses server (yang memakai ADOMD untuk ekstraksi/analisa) tetap
sehat setelah halaman Partisi dipakai. Token dikirim lewat stdin, tidak pernah
menjadi argumen baris perintah atau file.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from .auth import POWERBI_SCOPE, EntraTokens, ServicePrincipal
from .column_stats import STORAGE_DMV, partition_row_counts
from .errors import ExtractionError
from .partition_plan import (
    PartitionInfo,
    normalize_refresh_type,
    partitions_from_payload,
)
from .paths import APP_DIR, cli_argv
from .xmla_client import workspace_endpoint

Log = Callable[[str], None]
TOM_TIMEOUT = 180


def _silent(_message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _endpoint(principal: ServicePrincipal, workspace_name: str) -> str:
    return workspace_endpoint(principal.tenant_id or "myorg", workspace_name)


def _token_payload(tokens: EntraTokens | None, interactive: bool = False) -> dict[str, Any]:
    if interactive or tokens is None:
        return {"interactive": True}
    token = tokens.get(POWERBI_SCOPE)
    return {"token": token.value, "expires_on": token.expires_on}


def _cli_command(mode: str, endpoint: str, dataset_name: str) -> list[str]:
    return cli_argv(
        [
            "partition",
            mode,
            "--endpoint",
            endpoint,
            "--catalog",
            dataset_name,
        ]
    )


def _cli_env() -> dict[str, str]:
    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _error_line(text: str) -> str:
    detail = (text or "").strip()
    line = next((item.strip() for item in detail.splitlines() if item.strip()), "")
    if line.upper().startswith("ERROR:"):
        return line[len("ERROR:") :].strip()
    return line


def _run_json_process(
    command: list[str], payload: str, *, timeout: int | None
) -> str:
    """Jalankan proses anak tanpa streaming log (inventaris/DMV)."""
    completed = subprocess.run(
        command,
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(APP_DIR),
        env=_cli_env(),
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        line = _error_line(completed.stderr or completed.stdout)
        raise ExtractionError(line or "The CLI process failed without a message.")
    return completed.stdout or ""


def _run_stream_process(
    command: list[str], payload: str, log: Log, *, timeout: int | None = None
) -> str:
    """Jalankan proses anak sambil meneruskan stderr sebagai log job."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=str(APP_DIR),
        env=_cli_env(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    chunks: list[str] = []

    def read_stdout() -> None:
        try:
            chunks.append(process.stdout.read() if process.stdout else "")
        except Exception:  # noqa: BLE001 - proses mungkin ditutup
            chunks.append("")

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    errors: list[str] = []
    try:
        if process.stdin is not None:
            try:
                process.stdin.write(payload)
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        if process.stderr is not None:
            for line in process.stderr:
                text = line.rstrip()
                if not text:
                    continue
                errors.append(text)
                log(text)
        process.wait(timeout=timeout)
    finally:
        reader.join(timeout=10)
        if process.poll() is None:
            process.kill()
    if process.returncode != 0:
        line = _error_line("\n".join(errors))
        raise ExtractionError(line or "The CLI process failed without a message.")
    return "".join(chunks)


def _tom_partitions_subprocess(
    endpoint: str,
    dataset_name: str,
    tokens: EntraTokens | None,
    interactive: bool = False,
) -> list[PartitionInfo]:
    """Baca metadata partisi lewat proses anak yang hanya memuat TOM."""
    if interactive:
        from .tom_worker_client import get_tom_worker

        return partitions_from_payload(get_tom_worker(endpoint, dataset_name).inventory())
    text = _run_json_process(
        _cli_command("--inventory-json", endpoint, dataset_name),
        json.dumps(_token_payload(tokens, interactive)),
        timeout=TOM_TIMEOUT,
    )
    return partitions_from_payload(json.loads(text or "[]"))


def _tom_refresh_subprocess(
    endpoint: str,
    dataset_name: str,
    tokens: EntraTokens | None,
    targets: Sequence[tuple[str, str]],
    refresh_type: str,
    log: Log,
    interactive: bool = False,
) -> list[PartitionInfo]:
    """Kirim satu TMSL lewat proses anak TOM; log progres ikut diteruskan."""
    if interactive:
        from .tom_worker_client import get_tom_worker

        rows = get_tom_worker(endpoint, dataset_name).refresh(
            [
                {"table": table, "partition": partition}
                for table, partition in targets
            ],
            refresh_type,
        )
        return partitions_from_payload(rows)
    payload = _token_payload(tokens, interactive)
    payload.update(
        {
            "targets": [
                {"table": table, "partition": partition}
                for table, partition in targets
            ],
            "refresh_type": refresh_type,
        }
    )
    text = _run_stream_process(
        _cli_command("--refresh-json", endpoint, dataset_name),
        json.dumps(payload),
        log,
    )
    return partitions_from_payload(json.loads(text or "[]"))


def _dmv_rows_subprocess(
    endpoint: str,
    dataset_name: str,
    tokens: EntraTokens | None,
    interactive: bool = False,
) -> list[dict[str, Any]]:
    """Ambil DMV di proses CLI terpisah yang hanya memuat ADOMD."""
    text = _run_json_process(
        _cli_command("--dmv-json", endpoint, dataset_name),
        json.dumps(_token_payload(tokens, interactive)),
        timeout=TOM_TIMEOUT,
    )
    return json.loads(text or "[]")


def _row_counts(
    endpoint: str,
    dataset_name: str,
    tokens: EntraTokens | None,
    log: Log,
    interactive: bool = False,
) -> tuple[dict[tuple[str, str], int], list[str]]:
    try:
        if interactive:
            from .xmla_worker_client import get_worker_client

            segments = get_worker_client(endpoint, dataset_name).query(STORAGE_DMV)
        else:
            segments = _dmv_rows_subprocess(
                endpoint, dataset_name, tokens, interactive
            )
    except Exception as exc:  # noqa: BLE001 - row count bersifat best-effort
        message = f"Partition row counts are not available: {exc}"
        log(message)
        return {}, [message]
    return partition_row_counts(segments), []


def inventory_rows(
    partitions: Iterable[PartitionInfo],
    row_counts: Mapping[tuple[str, str], int] | None = None,
) -> list[dict[str, Any]]:
    """Serialisasi partisi ke baris JSON untuk web/CLI."""
    counts = row_counts or {}
    rows: list[dict[str, Any]] = []
    for partition in partitions:
        key = (partition.table, partition.name)
        rows.append(
            {
                "table": partition.table,
                "partition": partition.name,
                "rows": counts.get(key),
                "range": partition.range.label,
                "range_start": partition.range.start,
                "range_end": partition.range.end,
                "range_source": partition.range.source,
                "mode": partition.mode,
                "data_view": partition.data_view,
                "source_type": partition.source_type,
                "state": partition.state,
                "last_processed": partition.refreshed_time,
                "modified": partition.modified_time,
                "description": partition.description,
                "is_calculated": partition.is_calculated,
                "expression": partition.expression,
            }
        )
    return rows


def _payload(
    *,
    workspace_id: str,
    workspace_name: str,
    dataset_id: str,
    dataset_name: str,
    endpoint: str,
    partitions: Sequence[PartitionInfo],
    row_counts: Mapping[tuple[str, str], int],
    warnings: Sequence[str],
    loaded_at: str | None = None,
) -> dict[str, Any]:
    return {
        "workspace": {"id": workspace_id, "name": workspace_name},
        "dataset": {"id": dataset_id, "name": dataset_name},
        "endpoint": endpoint,
        "partitions": inventory_rows(partitions, row_counts),
        "warnings": list(warnings),
        "loaded_at": loaded_at or _now(),
    }


def _should_stop(cancel: Any) -> bool:
    return bool(cancel and cancel())


def read_partition_inventory(
    *,
    workspace_id: str,
    workspace_name: str,
    dataset_id: str,
    dataset_name: str,
    principal: ServicePrincipal,
    log: Log = _silent,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Baca inventaris partisi satu semantic model (tanpa menulis apa pun)."""
    principal.validate()
    tokens = EntraTokens(principal)
    endpoint = _endpoint(principal, workspace_name)
    log(f"Workspace: {workspace_name}")
    log(f"Semantic model: {dataset_name}")

    if _should_stop(should_stop):
        raise ExtractionError("Pembacaan partisi dibatalkan.")
    interactive = bool(getattr(principal, "interactive_xmla", False))
    partitions = _tom_partitions_subprocess(
        endpoint, dataset_name, tokens, interactive
    )

    row_counts, warnings = _row_counts(
        endpoint, dataset_name, tokens, log, interactive
    )
    log(
        f"Partitions read: {len(partitions)}; row counts available for "
        f"{len(row_counts)} partisi."
    )
    return _payload(
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        endpoint=endpoint,
        partitions=partitions,
        row_counts=row_counts,
        warnings=warnings,
    )


def process_partitions(
    *,
    workspace_id: str,
    workspace_name: str,
    dataset_id: str,
    dataset_name: str,
    targets: Iterable[tuple[str, str]],
    refresh_type: str,
    principal: ServicePrincipal,
    log: Log = _silent,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Jalankan satu TMSL refresh untuk semua partisi terpilih."""
    principal.validate()
    normalized = normalize_refresh_type(refresh_type)
    pairs = tuple((str(table).strip(), str(name).strip()) for table, name in targets)
    if not pairs:
        raise ExtractionError("Select at least one partition to process.")

    tokens = EntraTokens(principal)
    endpoint = _endpoint(principal, workspace_name)
    log(f"Workspace: {workspace_name}")
    log(f"Semantic model: {dataset_name}")
    log(f"Refresh type: {normalized}")
    log(f"Target partisi: {len(pairs)}")
    if _should_stop(should_stop):
        raise ExtractionError("Partition refresh cancelled before sending.")

    log(
        "Sending the TMSL refresh; the command cannot be cancelled once sent."
    )
    interactive = bool(getattr(principal, "interactive_xmla", False))
    refreshed = _tom_refresh_subprocess(
        endpoint, dataset_name, tokens, pairs, normalized, log, interactive
    )
    log("Refresh completed; reading partition row counts.")

    row_counts, warnings = _row_counts(
        endpoint, dataset_name, tokens, log, interactive
    )
    payload = _payload(
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        endpoint=endpoint,
        partitions=refreshed,
        row_counts=row_counts,
        warnings=warnings,
    )
    payload["refresh"] = {
        "type": normalized,
        "targets": [
            {"table": table, "partition": partition} for table, partition in pairs
        ],
        "completed_at": _now(),
        "message": (
            f"Refresh {normalized} finished for {len(pairs)} partitions. "
            "Check Refresh history in the Power BI Service to confirm "
            "via XMLA Endpoint."
        ),
    }
    return payload
