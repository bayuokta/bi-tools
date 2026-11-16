"""Sumber report: ekstraksi Report/definition (PBIR GA) dan deteksi jenis .pbix."""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .errors import ExtractionError
from .paths import APP_DIR

ROOT = APP_DIR
PBIR_PREFIX = "Report/definition/"

LOCAL_MODEL = "local_model"
LIVE_CONNECTION = "live_connection"
UNSUPPORTED = "unsupported"

KIND_LABELS = {
    LOCAL_MODEL: "Model lokal (Import/DirectQuery)",
    LIVE_CONNECTION: "Live connection (thin report)",
    UNSUPPORTED: "Jenis sumber tidak dikenali",
}


@dataclass(frozen=True)
class PbixSourceInfo:
    """Hasil deteksi jenis sumber dari isi file .pbix."""

    path: Path
    kind: str
    has_datamodel: bool
    has_pbir: bool
    connection_type: str = ""
    dataset_id: str = ""
    report_id: str = ""

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, KIND_LABELS[UNSUPPORTED])

    @property
    def has_local_model(self) -> bool:
        return self.kind == LOCAL_MODEL

    @property
    def is_live_connection(self) -> bool:
        return self.kind == LIVE_CONNECTION


def display_path(path: Path) -> str:
    """Path relatif terhadap folder tooling bila memungkinkan."""
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _decode_json(raw: bytes) -> dict[str, Any]:
    """Baca JSON dari entry .pbix; kembalikan {} bila tidak valid."""
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            data = json.loads(raw.decode(encoding))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        return data if isinstance(data, dict) else {}
    return {}


def _validate_pbix_path(pbix_path: Path) -> Path:
    path = Path(pbix_path)
    if path.is_dir():
        raise ExtractionError(
            f"Sumber report harus file .pbix, bukan folder: {path}. "
            "Dukungan folder PBIR sudah dihapus."
        )
    if path.suffix.lower() != ".pbix":
        raise ExtractionError(f"Sumber report tidak dikenali: {path}. Gunakan file .pbix.")
    if not path.exists():
        raise ExtractionError(f"File .pbix tidak ditemukan: {path}")
    return path


def detect_pbix_source(pbix_path: Path) -> PbixSourceInfo:
    """Deteksi jenis sumber dari isi .pbix, tanpa membuka Power BI Desktop.

    - Ada entry ``DataModel`` -> model lokal (Import/DirectQuery/composite).
    - Tanpa ``DataModel`` tetapi ada koneksi service live -> thin report.
    - Selain itu -> tidak dikenali.
    """
    path = _validate_pbix_path(pbix_path)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"File bukan .pbix/ZIP yang valid: {path} ({exc})") from exc

    with archive:
        members = set(archive.namelist())
        has_pbir = (
            f"{PBIR_PREFIX}report.json" in members
            and f"{PBIR_PREFIX}pages/pages.json" in members
        )
        has_datamodel = "DataModel" in members
        connections = _decode_json(archive.read("Connections")) if "Connections" in members else {}

    connection_type = ""
    for entry in connections.get("Connections") or []:
        if not isinstance(entry, dict):
            continue
        candidate = str(entry.get("ConnectionType") or "")
        if candidate.startswith("pbiService"):
            connection_type = candidate
            break

    artifacts = [item for item in (connections.get("RemoteArtifacts") or []) if isinstance(item, dict)]
    first_artifact = artifacts[0] if artifacts else {}
    dataset_id = str(first_artifact.get("DatasetId") or "")
    report_id = str(first_artifact.get("ReportId") or "")
    if not dataset_id:
        for entry in connections.get("Connections") or []:
            if isinstance(entry, dict) and entry.get("PbiModelDatabaseName"):
                dataset_id = str(entry["PbiModelDatabaseName"])
                break

    if has_datamodel:
        kind = LOCAL_MODEL
    elif connection_type or dataset_id:
        kind = LIVE_CONNECTION
    else:
        kind = UNSUPPORTED

    return PbixSourceInfo(
        path=path,
        kind=kind,
        has_datamodel=has_datamodel,
        has_pbir=has_pbir,
        connection_type=connection_type,
        dataset_id=dataset_id,
        report_id=report_id,
    )


def extract_pbix_definition(pbix_path: Path, target_root: Path) -> Path:
    """Ekstrak hanya Report/definition/** dari .pbix ke target_root."""
    try:
        archive = zipfile.ZipFile(pbix_path)
    except zipfile.BadZipFile as exc:
        raise ExtractionError(f"File bukan .pbix/ZIP yang valid: {pbix_path} ({exc})") from exc

    with archive:
        members = [
            name
            for name in archive.namelist()
            if name.startswith(PBIR_PREFIX) and not name.endswith("/")
        ]
        if f"{PBIR_PREFIX}report.json" not in members or f"{PBIR_PREFIX}pages/pages.json" not in members:
            raise ExtractionError(
                "PBIR definition tidak ditemukan di dalam .pbix. "
                "File ini kemungkinan masih memakai Report/Layout legacy; "
                "simpan ulang dengan Power BI Desktop yang mendukung PBIR GA."
            )

        for member in members:
            relative = Path(member)
            if relative.is_absolute() or ".." in relative.parts:
                continue
            destination = target_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)

    return target_root / "Report" / "definition"


def resolve_pbix(report_path: Path | None, workdir: Path) -> tuple[Path, str]:
    """Kembalikan (folder Report/definition, label sumber).

    Path ``.pbix`` wajib disebutkan pemanggil; tidak ada file bawaan.
    """
    if report_path is None:
        raise ExtractionError(
            "File .pbix wajib ditentukan (--report). Tidak ada file bawaan."
        )

    report_path = _validate_pbix_path(report_path.resolve())
    definition = extract_pbix_definition(report_path, workdir)
    return definition, f"pbix {display_path(report_path)} (Report/definition)"


@contextlib.contextmanager
def report_workspace(extract_to: str | None) -> Iterator[Path]:
    """Folder kerja untuk hasil ekstraksi pbix (temporary atau extract_to)."""
    if extract_to:
        target = Path(extract_to).resolve()
        target.mkdir(parents=True, exist_ok=True)
        yield target
        return
    with tempfile.TemporaryDirectory(prefix="report_pbix_") as temporary:
        yield Path(temporary)
