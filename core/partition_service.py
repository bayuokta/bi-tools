"""Orkestrasi inventaris dan proses partisi semantic model.

Inventaris memakai dua koneksi yang berbagi token yang sama:

- TOM untuk metadata partisi (state, mode, source, refresh time, ekspresi M);
- ADOMD/DMV untuk ``RECORDS_COUNT`` per partisi.

Proses refresh tetap satu perintah TMSL untuk semua partisi terpilih. Modul ini
tidak mencetak ke terminal dan tidak menyimpan token ke disk.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

from .auth import POWERBI_SCOPE, EntraTokens, ServicePrincipal
from .paths import APP_DIR, cli_argv
from .column_stats import STORAGE_DMV, partition_row_counts
from .errors import ExtractionError
from .tom_client import (
    PartitionInfo,
    build_refresh_tmsl,
    connect_server,
    execute_refresh,
    list_partitions,
    normalize_refresh_type,
    validate_refresh_targets,
)
from .xmla_client import workspace_endpoint

Log = Callable[[str], None]


def _silent(_message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _endpoint(principal: ServicePrincipal, workspace_name: str) -> str:
    return workspace_endpoint(principal.tenant_id or "myorg", workspace_name)


def _dmv_rows_subprocess(
    endpoint: str, dataset_name: str, tokens: EntraTokens
) -> list[dict[str, Any]]:
    """Ambil DMV di proses CLI terpisah yang hanya memuat ADOMD.

    TOM dan ADOMD membawa versi assembly ``Microsoft.AnalysisServices`` yang
    berbeda dan tidak bisa hidup di satu proses. Token dikirim lewat stdin,
    tidak pernah menjadi argumen baris perintah atau file.
    """
    token = tokens.get(POWERBI_SCOPE)
    command = cli_argv(
        [
            "partition",
            "--dmv-json",
            "--endpoint",
            endpoint,
            "--catalog",
            dataset_name,
        ]
    )
    payload = json.dumps({"token": token.value, "expires_on": token.expires_on})
    completed = subprocess.run(
        command,
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(APP_DIR),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        line = next((item.strip() for item in detail.splitlines() if item.strip()), "")
        raise RuntimeError(line or "Proses DMV gagal tanpa pesan.")
    return json.loads(completed.stdout or "[]")


def _row_counts(
    endpoint: str,
    dataset_name: str,
    tokens: EntraTokens,
    log: Log,
    *,
    open_factory: Callable[..., Any] | None = None,
) -> tuple[dict[tuple[str, str], int], list[str]]:
    try:
        if open_factory is None:
            segments = _dmv_rows_subprocess(endpoint, dataset_name, tokens)
        else:
            with open_factory(
                endpoint=endpoint, catalog=dataset_name, tokens=tokens
            ) as client:
                segments = client.query(STORAGE_DMV)
    except Exception as exc:  # noqa: BLE001 - row count bersifat best-effort
        message = f"Jumlah baris partisi tidak tersedia: {exc}"
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
    connect_factory: Callable[..., Any] | None = None,
    open_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Baca inventaris partisi satu semantic model (tanpa menulis apa pun)."""
    principal.validate()
    tokens = EntraTokens(principal)
    endpoint = _endpoint(principal, workspace_name)
    log(f"Workspace: {workspace_name}")
    log(f"Semantic model: {dataset_name}")

    connect = connect_factory or connect_server
    with connect(endpoint, dataset_name, tokens) as server:
        if _should_stop(should_stop):
            raise ExtractionError("Pembacaan partisi dibatalkan.")
        partitions = list_partitions(server, dataset_name)

    row_counts, warnings = _row_counts(
        endpoint,
        dataset_name,
        tokens,
        log,
        open_factory=open_factory,
    )
    log(
        f"Partisi dibaca: {len(partitions)}; jumlah baris tersedia untuk "
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
    connect_factory: Callable[..., Any] | None = None,
    open_factory: Callable[..., Any] | None = None,
    execute_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Jalankan satu TMSL refresh untuk semua partisi terpilih."""
    principal.validate()
    normalized = normalize_refresh_type(refresh_type)
    pairs = tuple((str(table).strip(), str(name).strip()) for table, name in targets)
    if not pairs:
        raise ExtractionError("Pilih minimal satu partisi untuk diproses.")

    tokens = EntraTokens(principal)
    endpoint = _endpoint(principal, workspace_name)
    log(f"Workspace: {workspace_name}")
    log(f"Semantic model: {dataset_name}")
    log(f"Refresh type: {normalized}")
    log(f"Target partisi: {len(pairs)}")

    connect = connect_factory or connect_server
    execute = execute_factory or execute_refresh
    with connect(endpoint, dataset_name, tokens) as server:
        if _should_stop(should_stop):
            raise ExtractionError("Refresh partisi dibatalkan sebelum dikirim.")
        partitions = list_partitions(server, dataset_name)
        by_key = {(item.table, item.name): item for item in partitions}
        missing = [key for key in pairs if key not in by_key]
        if missing:
            listing = ", ".join(f"{table}/{name}" for table, name in missing)
            raise ExtractionError(
                f"Partisi tidak ditemukan di model: {listing}. Muat ulang inventaris."
            )
        selected = [by_key[key] for key in pairs]
        validate_refresh_targets(normalized, selected)
        tmsl = build_refresh_tmsl(dataset_name, pairs, normalized)
        log(
            f"Mengirim refresh TMSL untuk {len(pairs)} partisi; "
            "perintah tidak bisa dibatalkan setelah dikirim."
        )
        execute(server, tmsl)
        log("Perintah refresh selesai; membaca ulang status partisi.")
        refreshed = list_partitions(server, dataset_name)

    row_counts, warnings = _row_counts(
        endpoint,
        dataset_name,
        tokens,
        log,
        open_factory=open_factory,
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
            f"Refresh {normalized} selesai untuk {len(pairs)} partisi. "
            "Periksa Refresh history di Power BI Service untuk konfirmasi "
            "Via XMLA Endpoint."
        ),
    }
    return payload
