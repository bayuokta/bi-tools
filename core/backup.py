"""Backup definisi semantic model dan report dari Power BI Service.

Model diekspor lewat TOM (TMDL + TMSL), report lewat Fabric ``getDefinition``.
Hasilnya satu ZIP per item di folder run per workspace. Modul ini read-only dan
tidak memakai Admin API.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .auth import EntraTokens, fabric_provider
from .errors import ExtractionError
from .fabric_api import FabricReportClient, ReportDefinition, ServiceReportRef
from .paths import outputs_dir
from .tom_worker_client import get_tom_worker
from .version import __version__
from .xmla_client import workspace_endpoint

Log = Callable[[str], None]
Progress = Callable[[int, int, str], None]

KIND_MODEL = "model"
KIND_REPORT = "report"
KINDS = (KIND_MODEL, KIND_REPORT)
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

INVALID_NAME = re.compile(r"[^0-9A-Za-z._ -]+")


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _local_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M")


def safe_name(value: str, *, limit: int = 60) -> str:
    """Nama aman untuk file/folder (tanpa karakter terlarang Windows)."""
    text = INVALID_NAME.sub("_", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return (text[:limit].rstrip(" .") or "item")


def default_folder() -> Path:
    return outputs_dir() / "backups"


def _item_file(kind: str, name: str, item_id: str) -> str:
    prefix = "semantic_model" if kind == KIND_MODEL else "report"
    suffix = str(item_id or "").replace("-", "")[:8]
    return f"{prefix}_{safe_name(name)}_{suffix}.zip"


def _safe_part_path(root: Path, relative: str) -> Path:
    path = PurePosixPath(str(relative or "").replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ExtractionError(f"Unsafe report part: {relative!r}.")
    return root.joinpath(*path.parts)


def write_report_parts(definition: ReportDefinition, target: Path | str) -> int:
    """Tulis seluruh part definisi apa adanya (PBIR maupun PBIR-Legacy)."""
    root = Path(target)
    count = 0
    for part in definition.parts:
        destination = _safe_part_path(root, part.path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(part.payload)
        count += 1
    if count == 0:
        raise ExtractionError("The report definition contains no parts.")
    return count


def write_zip(source: Path | str, target: Path | str) -> int:
    """Zip seluruh isi folder (path relatif dipertahankan); kembalikan byte."""
    root = Path(source)
    files = [path for path in root.rglob("*") if path.is_file()]
    if not files:
        raise ExtractionError("No files to archive.")
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(root).as_posix())
    return destination.stat().st_size


@dataclass(frozen=True)
class BackupItem:
    """Satu item yang akan dibackup."""

    kind: str
    item_id: str
    name: str
    report_type: str = ""
    report_format: str = ""
    dataset_id: str = ""

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip().lower()
        if kind not in KINDS:
            raise ExtractionError(f"Unknown backup item type: {self.kind}.")
        name = str(self.name or "").strip()
        if not name:
            raise ExtractionError("Backup item name is empty.")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "name", name)

    @classmethod
    def from_payload(cls, value: Any) -> "BackupItem":
        row = dict(value or {})
        return cls(
            kind=str(row.get("kind") or ""),
            item_id=str(row.get("id") or row.get("item_id") or "").strip(),
            name=str(row.get("name") or ""),
            report_type=str(row.get("report_type") or row.get("reportType") or ""),
            report_format=str(row.get("report_format") or ""),
            dataset_id=str(row.get("dataset_id") or "").strip(),
        )

    @property
    def label(self) -> str:
        return f"{'Model' if self.kind == KIND_MODEL else 'Report'} {self.name}"


@dataclass(frozen=True)
class BackupOptions:
    """Parameter satu kali backup."""

    workspace_id: str
    workspace_name: str
    items: tuple[BackupItem, ...]
    folder: Path
    prefix: str = "Backup"

    def __post_init__(self) -> None:
        if not self.items:
            raise ExtractionError("Select at least one item to back up.")
        folder = Path(self.folder).expanduser()
        if not folder.is_absolute():
            raise ExtractionError("Backup folder must be absolute.")
        object.__setattr__(self, "folder", folder)
        object.__setattr__(self, "prefix", safe_name(self.prefix or "Backup"))


@dataclass
class BackupEntry:
    """Hasil backup satu item."""

    kind: str
    item_id: str
    name: str
    status: str
    message: str = ""
    file: str = ""
    size: int = 0
    source: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.item_id,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "file": self.file,
            "size": self.size,
            "source": self.source,
        }


@dataclass
class BackupResult:
    """Ringkasan satu kali backup."""

    folder: Path
    run_dir: Path
    manifest: Path
    items: list[BackupEntry] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0

    @property
    def size(self) -> int:
        return sum(item.size for item in self.items)

    @property
    def ok_count(self) -> int:
        return sum(1 for item in self.items if item.status == STATUS_OK)

    def payload(self) -> dict[str, Any]:
        return {
            "folder": str(self.folder),
            "run_dir": str(self.run_dir),
            "manifest": str(self.manifest),
            "items": [item.payload() for item in self.items],
            "files": len([item for item in self.items if item.file]),
            "size": self.size,
            "ok": self.ok_count,
            "failed": sum(1 for item in self.items if item.status == STATUS_FAILED),
            "skipped": sum(1 for item in self.items if item.status == STATUS_SKIPPED),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 2),
        }


def ensure_pbism(root: Path | str) -> None:
    """Lengkapi ``definition.pbism`` agar ZIP bisa dipakai restore Fabric."""
    path = Path(root) / "definition.pbism"
    if path.exists():
        return
    path.write_text(
        json.dumps({"version": "4.0", "settings": {}}, indent=2),
        encoding="utf-8",
    )


def _backup_model(
    client: FabricReportClient,
    workspace_id: str,
    item: BackupItem,
    endpoint: str,
    target: Path,
    *,
    log: Log = _silent,
) -> str:
    """Tulis definisi model; Fabric dulu, TOM sebagai cadangan.

    Fabric ``getDefinition`` memberi TMDL + ``definition.pbism`` sehingga ZIP
    siap dipakai restore. TOM tetap dipakai untuk ``model.bim`` dan sebagai
    cadangan bila endpoint semantic model tidak tersedia.
    """
    log(f"Downloading Fabric model definition {item.name}...")
    try:
        definition = client.get_semantic_model_definition(
            workspace_id, item.item_id
        )
        write_report_parts(definition, target)
        ensure_pbism(target)
        log(f"Definisi Fabric model {item.name}: {len(definition.parts)} part.")
    except Exception as exc:  # noqa: BLE001 - fallback TOM
        log(
            f"Fabric model definition {item.name} is not available "
            f"({str(exc).splitlines()[0][:160]}); using TOM."
        )
        worker = get_tom_worker(endpoint, item.name)
        worker.export(str(target))
        ensure_pbism(target)
        return "tom"

    try:
        tom_dir = target / "_tom"
        worker = get_tom_worker(endpoint, item.name)
        worker.export(str(tom_dir))
        model_bim = tom_dir / "model.bim"
        if model_bim.is_file():
            shutil.copyfile(model_bim, target / "model.bim")
    except Exception as exc:  # noqa: BLE001 - model.bim opsional
        log(f"model.bim {item.name} skipped: {str(exc).splitlines()[0][:160]}")
    finally:
        shutil.rmtree(target / "_tom", ignore_errors=True)
    return "fabric"


def _is_paginated(item: BackupItem) -> bool:
    return str(item.report_type or "") == "PaginatedReport"


def run_backup(
    options: BackupOptions,
    principal: Any,
    *,
    log: Log = _silent,
    progress: Progress | None = None,
    cancel: Any | None = None,
) -> BackupResult:
    """Backup item terpilih; kegagalan satu item tidak menghentikan item lain."""
    principal.validate()
    workspace_id = str(options.workspace_id or "").strip()
    if not workspace_id:
        raise ExtractionError("No backup workspace selected.")
    workspace_name = str(options.workspace_name or "").strip()
    if not workspace_name:
        raise ExtractionError("The backup workspace name is unknown.")

    options.folder.mkdir(parents=True, exist_ok=True)
    run_dir = options.folder / (
        f"{options.prefix}_{safe_name(workspace_name)}_{_local_stamp()}"
    )
    suffix = 2
    while run_dir.exists():
        run_dir = options.folder / (
            f"{options.prefix}_{safe_name(workspace_name)}_{_local_stamp()}_{suffix}"
        )
        suffix += 1
    run_dir.mkdir(parents=True)

    started_at = _now()
    clock = time.perf_counter()
    tokens = EntraTokens(principal)
    endpoint = workspace_endpoint(principal.tenant_id or "myorg", workspace_name)
    client: FabricReportClient | None = None
    entries: list[BackupEntry] = []
    total = len(options.items)
    log(f"Backup: {workspace_name} ({total} item) -> {run_dir}")

    try:
        for index, item in enumerate(options.items, start=1):
            entry = BackupEntry(
                kind=item.kind, item_id=item.item_id, name=item.name, status=""
            )
            if cancel is not None and cancel.is_set():
                entry.status = STATUS_SKIPPED
                entry.message = "Dibatalkan."
                entries.append(entry)
                continue
            if item.kind == KIND_REPORT and _is_paginated(item):
                entry.status = STATUS_SKIPPED
                entry.message = "Paginated (RDL) reports are not supported yet."
                entries.append(entry)
                log(f"Skipped {item.label}: RDL is not supported yet.")
                if progress:
                    progress(index, total, item.label)
                continue

            temp = Path(tempfile.mkdtemp(prefix="bi-tools-backup-"))
            try:
                if client is None:
                    client = FabricReportClient(
                        fabric_provider(tokens), poll_wait=1, log=log
                    )
                if item.kind == KIND_MODEL:
                    entry.source = _backup_model(
                        client,
                        workspace_id,
                        item,
                        endpoint,
                        temp,
                        log=log,
                    )
                else:
                    service = ServiceReportRef.from_ids(workspace_id, item.item_id)
                    definition = client.get_report_definition(service)
                    write_report_parts(definition, temp)
                    entry.source = "fabric"
                archive = run_dir / _item_file(item.kind, item.name, item.item_id)
                size = write_zip(temp, archive)
            except Exception as exc:  # noqa: BLE001 - item gagal, lanjut item lain
                entry.status = STATUS_FAILED
                entry.message = str(exc).splitlines()[0][:300]
                log(f"Failed {item.label}: {entry.message}")
            else:
                entry.status = STATUS_OK
                entry.file = archive.name
                entry.size = size
                log(f"Backup {item.label}: {archive.name} ({size} byte)")
            finally:
                shutil.rmtree(temp, ignore_errors=True)
            entries.append(entry)
            if progress:
                progress(index, total, item.label)
    finally:
        if client is not None:
            client.close()

    finished_at = _now()
    duration = time.perf_counter() - clock
    result = BackupResult(
        folder=options.folder,
        run_dir=run_dir,
        manifest=run_dir / "manifest.json",
        items=entries,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration,
    )
    manifest = {
        "app": {"name": "BI Tools", "version": __version__},
        "workspace": {"id": workspace_id, "name": workspace_name},
        "prefix": options.prefix,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration, 2),
        "items": [item.payload() for item in entries],
        "totals": {
            "items": len(entries),
            "ok": result.ok_count,
            "failed": sum(
                1 for item in entries if item.status == STATUS_FAILED
            ),
            "skipped": sum(
                1 for item in entries if item.status == STATUS_SKIPPED
            ),
            "size": result.size,
        },
    }
    result.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(
        f"Done: {result.ok_count}/{len(entries)} item, "
        f"{result.size} byte, {duration:.1f} detik."
    )
    return result


def history(folder: Path | str, *, limit: int = 10) -> list[dict[str, Any]]:
    """Riwayat backup dari folder (membaca ``manifest.json`` setiap run)."""
    root = Path(folder).expanduser()
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for run_dir in sorted(root.glob("Backup_*"), reverse=True):
        if not run_dir.is_dir():
            continue
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data.get("items") or []
        rows.append(
            {
                "run": run_dir.name,
                "path": str(run_dir),
                "finished_at": str(data.get("finished_at") or ""),
                "items": len(items),
                "ok": int((data.get("totals") or {}).get("ok") or 0),
                "failed": int((data.get("totals") or {}).get("failed") or 0),
                "skipped": int((data.get("totals") or {}).get("skipped") or 0),
                "size": int((data.get("totals") or {}).get("size") or 0),
                "workspace": str((data.get("workspace") or {}).get("name") or ""),
            }
        )
        if len(rows) >= limit:
            break
    return rows


def read_manifest(run_dir: Path | str) -> dict[str, Any]:
    path = Path(run_dir) / "manifest.json"
    if not path.is_file():
        raise ExtractionError(f"Backup manifest not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExtractionError(f"The backup manifest could not be read: {exc}") from exc
