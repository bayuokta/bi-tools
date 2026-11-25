"""Orkestrasi sync: katalog workspace -> lineage -> katalog report -> snapshot.

Satu implementasi dipakai oleh CLI ``bi-tools-sync`` dan notebook Fabric, supaya
urutan, log, dan isi snapshot tidak berbeda antar jalur.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.auth import ServicePrincipal
from core.errors import ExtractionError
from core.snapshot import publish_snapshot

from .catalog import WorkspaceSyncResult, run_workspace_sync, sync_report_catalog
from .lineage import LineageScanResult, run_lineage_scan

Log = Callable[[str], None]
MODES = ("auto", "admin", "member")


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


@dataclass(frozen=True)
class SyncOptions:
    """Parameter satu kali sync.

    ``database`` adalah database kerja lokal (boleh sementara di notebook),
    ``snapshot`` file hasil yang dibaca aplikasi interaktif.
    """

    database: Path
    snapshot: Path
    mode: str = "auto"
    full: bool = False
    include_personal: bool = False
    skip_catalog: bool = False
    skip_lineage: bool = False
    skip_reports: bool = False

    def validate(self) -> None:
        if self.mode not in MODES:
            raise ExtractionError(f"Mode sinkronisasi tidak dikenal: {self.mode}")
        if self.skip_catalog and self.skip_lineage and self.skip_reports:
            raise ExtractionError(
                "Semua langkah sync dilewati; tidak ada yang bisa diterbitkan."
            )


@dataclass(frozen=True)
class SyncResult:
    """Ringkasan satu kali sync."""

    database: Path
    snapshot: Path
    size: int
    checksum: str
    generated_at: str
    mode: str
    full: bool
    catalog: WorkspaceSyncResult | None = None
    lineage: LineageScanResult | None = None
    report_count: int = 0
    report_error: str = ""
    duration_seconds: float = 0.0
    steps: dict[str, Any] = field(default_factory=dict)


def run_sync(
    options: SyncOptions,
    principal: ServicePrincipal,
    *,
    log: Log = _silent,
) -> SyncResult:
    """Jalankan seluruh langkah sync lalu terbitkan snapshot.

    Kegagalan katalog report dicatat dan tidak membatalkan snapshot (sama
    seperti perilaku CLI sebelumnya); kegagalan katalog workspace atau lineage
    menghentikan proses karena snapshot tanpa keduanya menyesatkan.
    """
    options.validate()
    principal.validate()

    database = Path(options.database).expanduser()
    snapshot = Path(options.snapshot).expanduser()
    clock = time.perf_counter()
    catalog: WorkspaceSyncResult | None = None
    lineage: LineageScanResult | None = None
    report_count = 0
    report_error = ""

    if not options.skip_catalog:
        catalog = run_workspace_sync(database, principal, mode=options.mode, log=log)
        log(f"Katalog: {catalog.workspace_count} workspace (mode {catalog.mode})")

    if not options.skip_lineage:
        lineage = run_lineage_scan(
            database,
            principal,
            mode=options.mode,
            full=options.full,
            include_personal=options.include_personal,
            log=log,
        )
        log(
            f"Lineage: {lineage.workspace_count} workspace, "
            f"{lineage.node_count} node, {lineage.edge_count} edge"
        )

    if not options.skip_reports:
        try:
            report_count = sync_report_catalog(principal, database, log=log)
        except Exception as exc:  # noqa: BLE001 - katalog report opsional
            report_error = str(exc)
            log(f"Katalog report dilewati: {exc}")
        else:
            log(f"Katalog report: {report_count} report")

    summary = publish_snapshot(
        database,
        snapshot,
        extra_meta={
            "mode": options.mode,
            "full": "1" if options.full else "0",
        },
    )
    log(f"Snapshot: {summary['path']} ({summary['size']} byte)")

    return SyncResult(
        database=database,
        snapshot=Path(str(summary["path"])),
        size=int(summary["size"]),
        checksum=str(summary["checksum"]),
        generated_at=str(summary.get("generated_at") or ""),
        mode=options.mode,
        full=options.full,
        catalog=catalog,
        lineage=lineage,
        report_count=report_count,
        report_error=report_error,
        duration_seconds=time.perf_counter() - clock,
        steps={
            "catalog": catalog is not None,
            "lineage": lineage is not None,
            "reports": report_error == "",
        },
    )
