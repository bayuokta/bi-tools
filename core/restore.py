"""Restore definisi model/report dari ZIP backup ke workspace tujuan.

Memakai Fabric REST API (``updateDefinition``/create), bukan XMLA tulis. ZIP
divalidasi dulu (struktur, path aman, ukuran) sebelum ada penulisan.
"""

from __future__ import annotations

import json
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .auth import EntraTokens, fabric_provider
from .backup import KIND_MODEL, KIND_REPORT, default_folder, history
from .errors import ExtractionError
from .fabric_api import DefinitionPart, FabricReportClient

Log = Callable[[str], None]
MAX_ENTRIES = 5000
MAX_UNCOMPRESSED = 500 * 1024 * 1024


def _silent(message: str) -> None:
    """Log default: tidak menampilkan apa pun."""


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H%M")


def _guess_kind(paths: set[str]) -> str:
    if "definition.pbism" in paths:
        return KIND_MODEL
    if "definition/model.tmdl" in paths or "definition/database.tmdl" in paths:
        return KIND_MODEL
    if "definition.pbir" in paths or "report.json" in paths:
        return KIND_REPORT
    return ""


def _platform_name(parts: dict[str, bytes]) -> str:
    raw = parts.get(".platform")
    if not raw:
        return ""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ""
    metadata = data.get("metadata") or {}
    return str(metadata.get("displayName") or "").strip()


def _base_name(path: Path) -> str:
    stem = path.stem
    for prefix in ("semantic_model_", "report_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix) :]
            break
    if len(stem) > 9 and stem[-9] == "_" and all(
        char in "0123456789abcdef" for char in stem[-8:].lower()
    ):
        stem = stem[:-9]
    return stem or path.stem


@dataclass(frozen=True)
class ArchiveInfo:
    """Isi ZIP backup yang sudah divalidasi."""

    path: Path
    kind: str
    name: str
    parts: tuple[DefinitionPart, ...]
    has_model_bim: bool
    source_workspace: str = ""
    size: int = 0


def inspect_archive(path: Path | str, *, strict: bool = True) -> ArchiveInfo:
    """Baca dan validasi ZIP backup; tidak menulis apa pun."""
    source = Path(path).expanduser()
    if not source.is_file():
        raise ExtractionError(f"Backup file not found: {source}")
    if source.suffix.lower() != ".zip":
        raise ExtractionError("The backup file must be a .zip file.")
    parts: list[DefinitionPart] = []
    paths: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(source) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if len(infos) > MAX_ENTRIES:
                raise ExtractionError("The backup ZIP contains too many files.")
            for info in infos:
                relative = PurePosixPath(info.filename.replace("\\", "/"))
                if relative.is_absolute() or ".." in relative.parts:
                    raise ExtractionError(
                        f"Unsafe path in ZIP: {info.filename!r}."
                    )
                total += int(info.file_size or 0)
                if total > MAX_UNCOMPRESSED:
                    raise ExtractionError(
                        "Isi ZIP backup terlalu besar setelah diekstrak."
                    )
                payload = archive.read(info)
                clean = relative.as_posix()
                paths.add(clean)
                parts.append(DefinitionPart(clean, payload))
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"The backup file is not a valid ZIP: {exc}") from exc

    kind = _guess_kind(paths)
    if not kind:
        raise ExtractionError(
            "Unrecognized backup type (not a semantic model or report)."
        )

    if strict and kind == KIND_MODEL and not (
        "definition/model.tmdl" in paths or "model.bim" in paths
    ):
        raise ExtractionError(
            "The model ZIP contains neither definition/model.tmdl nor model.bim."
        )
    if strict and kind == KIND_REPORT and not (
        "definition.pbir" in paths or "report.json" in paths
    ):
        raise ExtractionError(
            "The report ZIP contains neither definition.pbir nor report.json."
        )

    payloads = {part.path: part.payload for part in parts}
    if strict and "model.bim" in payloads:
        try:
            json.loads(payloads["model.bim"].decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ExtractionError(
                f"model.bim in the ZIP is not valid JSON: {exc}"
            ) from exc
    name = _platform_name(payloads) or _base_name(source)
    return ArchiveInfo(
        path=source,
        kind=kind,
        name=name,
        parts=tuple(parts),
        has_model_bim="model.bim" in paths,
        size=source.stat().st_size,
    )


def list_restore_files(folder: Path | str = "") -> list[dict[str, Any]]:
    """Daftar ZIP dari manifest backup, terbaru dulu."""
    root = Path(folder).expanduser() if folder else default_folder()
    rows: list[dict[str, Any]] = []
    for item in history(root, limit=100):
        run_dir = Path(item["path"])
        try:
            manifest = json.loads(
                (run_dir / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue
        for entry in manifest.get("items") or []:
            if not isinstance(entry, dict):
                continue
            file_name = str(entry.get("file") or "")
            if entry.get("status") != "ok" or not file_name:
                continue
            path = run_dir / file_name
            if not path.is_file():
                continue
            rows.append(
                {
                    "file": file_name,
                    "path": str(path),
                    "run": run_dir.name,
                    "kind": str(entry.get("kind") or ""),
                    "name": str(entry.get("name") or ""),
                    "size": int(entry.get("size") or path.stat().st_size),
                    "source": str(entry.get("source") or ""),
                    "workspace": item["workspace"],
                    "finished_at": item["finished_at"],
                }
            )
    rows.sort(key=lambda row: row["finished_at"], reverse=True)
    return rows


@dataclass(frozen=True)
class RestoreOptions:
    """Parameter satu kali restore."""

    file: Path
    workspace_id: str
    workspace_name: str
    overwrite: bool = False
    target_id: str = ""
    target_name: str = ""
    validate: bool = True

    def __post_init__(self) -> None:
        path = Path(self.file).expanduser()
        if not path.is_absolute():
            raise ExtractionError("Backup file path must be absolute.")
        object.__setattr__(self, "file", path)
        if self.overwrite and not str(self.target_id or "").strip():
            raise ExtractionError("Select the target item to overwrite.")
        if not self.overwrite and str(self.target_id or "").strip():
            raise ExtractionError("A target item is only used when overwriting.")


@dataclass
class RestoreResult:
    """Ringkasan satu kali restore."""

    file: Path
    workspace_id: str
    workspace_name: str
    kind: str
    action: str
    item_id: str
    display_name: str
    size: int
    started_at: str
    finished_at: str
    duration_seconds: float

    def payload(self) -> dict[str, Any]:
        return {
            "file": str(self.file),
            "file_name": self.file.name,
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "kind": self.kind,
            "action": self.action,
            "id": self.item_id,
            "name": self.display_name,
            "size": self.size,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 2),
        }


def _restore_parts(
    info: ArchiveInfo, *, create: bool
) -> tuple[DefinitionPart, ...]:
    parts = list(info.parts)
    if info.kind == KIND_MODEL:
        # Fabric menolak TMDL dan TMSL sekaligus: pilih satu format.
        has_tmdl = any(
            part.path.startswith("definition/") for part in parts
        )
        if has_tmdl:
            parts = [part for part in parts if part.path != "model.bim"]
        else:
            parts = [
                part
                for part in parts
                if part.path in ("model.bim", "definition.pbism", ".platform")
            ]
    if create:
        parts = [part for part in parts if part.path != ".platform"]
    if info.kind == KIND_MODEL and not any(
        part.path == "definition.pbism" for part in parts
    ):
        parts.append(
            DefinitionPart(
                "definition.pbism",
                json.dumps({"version": "4.0", "settings": {}}).encode("utf-8"),
            )
        )
    return tuple(parts)


def run_restore(
    options: RestoreOptions,
    principal: Any,
    *,
    log: Log = _silent,
    cancel: Any | None = None,
) -> RestoreResult:
    """Validasi lalu tulis definisi ke workspace tujuan."""
    principal.validate()
    if cancel is not None and cancel.is_set():
        raise ExtractionError("Restore dibatalkan sebelum dimulai.")
    info = inspect_archive(options.file, strict=options.validate)
    workspace = str(options.workspace_name or "").strip()
    if not workspace:
        raise ExtractionError("The target workspace name is unknown.")

    started_at = datetime.now().isoformat(timespec="seconds")
    clock = time.perf_counter()
    tokens = EntraTokens(principal)
    client = FabricReportClient(
        fabric_provider(tokens), poll_wait=1, log=log
    )
    action = "updated" if options.overwrite else "created"
    display_name = (
        options.target_name.strip()
        if options.overwrite and options.target_name.strip()
        else info.name
    )
    if not options.overwrite:
        display_name = f"{info.name} restored {_stamp()}"
    parts = _restore_parts(info, create=not options.overwrite)
    log(
        f"Restore {info.kind} '{info.name}' -> {workspace} "
        f"({'overwrite' if options.overwrite else 'new'})"
    )
    item_id = str(options.target_id or "").strip()
    try:
        if info.kind == KIND_MODEL:
            if options.overwrite:
                client.update_semantic_model_definition(
                    options.workspace_id, item_id, parts
                )
            else:
                response = client.create_semantic_model(
                    options.workspace_id, display_name, parts
                )
                item_id = str((response or {}).get("id") or "")
        else:
            if options.overwrite:
                client.update_report_definition(
                    options.workspace_id, item_id, parts
                )
            else:
                response = client.create_report(
                    options.workspace_id, display_name, parts
                )
                item_id = str((response or {}).get("id") or "")
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - pesan API tidak seragam
        raise ExtractionError(
            f"Restore {info.kind} '{info.name}' failed: {exc}"
        ) from exc
    finally:
        client.close()

    finished_at = datetime.now().isoformat(timespec="seconds")
    result = RestoreResult(
        file=info.path,
        workspace_id=options.workspace_id,
        workspace_name=workspace,
        kind=info.kind,
        action=action,
        item_id=item_id,
        display_name=display_name,
        size=info.size,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=time.perf_counter() - clock,
    )
    log(
        f"Done: {info.kind} {action} "
        f"({info.size} byte, {result.duration_seconds:.1f} detik)."
    )
    return result
