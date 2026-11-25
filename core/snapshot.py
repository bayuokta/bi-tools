"""Snapshot SQLite bersama: publish oleh sync, unduh/validasi oleh aplikasi.

SQLite tidak boleh dibuka langsung dari folder SharePoint/OneDrive yang
disinkronkan. Program sync membuat snapshot konsisten (``VACUUM INTO``),
menulis checksum, lalu aplikasi menyalin snapshot ke cache lokal dan membukanya
read-only.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ExtractionError
from .lineage_store import connect, initialize

SCHEMA_VERSION = 1
CHECKSUM_SUFFIX = ".sha256"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _set_meta(path: Path, values: dict[str, str]) -> None:
    conn = connect(path)
    try:
        initialize(conn)
        for key, value in values.items():
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(key), str(value)),
            )
        conn.commit()
    finally:
        conn.close()


def read_meta(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        try:
            rows = conn.execute("SELECT key, value FROM meta").fetchall()
        except sqlite3.OperationalError:
            return {}
    finally:
        conn.close()
    return {str(key): str(value or "") for key, value in rows}


def _quick_check(path: Path) -> None:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()
    finally:
        conn.close()
    if not result or str(result[0]).lower() != "ok":
        raise ExtractionError(
            f"Snapshot database rusak: {result[0] if result else 'tidak diketahui'}"
        )


def ensure_schema(path: Path) -> dict[str, str]:
    """Pastikan snapshot punya skema yang dikenal aplikasi ini."""
    meta = read_meta(path)
    version = str(meta.get("schema_version") or "").strip()
    if version and version.isdigit() and int(version) > SCHEMA_VERSION:
        raise ExtractionError(
            "Snapshot database memakai skema yang lebih baru "
            f"({version}) daripada aplikasi ({SCHEMA_VERSION}). Perbarui aplikasi."
        )
    return meta


def publish_snapshot(
    database: Path | str,
    target: Path | str,
    *,
    extra_meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Buat snapshot konsisten dari ``database`` lalu tulis ke ``target``."""
    source = Path(database).expanduser().resolve()
    destination = Path(target).expanduser().resolve()
    if not source.exists():
        raise ExtractionError(f"Database sumber tidak ditemukan: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)

    _set_meta(
        source,
        {
            "schema_version": str(SCHEMA_VERSION),
            "generated_at": _now(),
            **(extra_meta or {}),
        },
    )

    with tempfile.TemporaryDirectory(prefix="bi-tools-snapshot-") as tmp:
        snapshot = Path(tmp) / "snapshot.db"
        conn = sqlite3.connect(source)
        try:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
            conn.execute("VACUUM INTO ?", (str(snapshot),))
        finally:
            conn.close()
        _quick_check(snapshot)
        checksum = sha256_file(snapshot)

        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copyfile(snapshot, temporary)
        os.replace(temporary, destination)
        Path(str(destination) + CHECKSUM_SUFFIX).write_text(
            checksum + "\n", encoding="ascii"
        )
    return {
        "path": str(destination),
        "checksum": checksum,
        "size": destination.stat().st_size,
        "generated_at": _now(),
    }


def prepare_local_snapshot(
    source: Path | str, local: Path | str
) -> dict[str, Any]:
    """Salin snapshot dari folder share ke cache lokal dan validasi."""
    origin = Path(source).expanduser().resolve()
    destination = Path(local).expanduser().resolve()
    if not origin.exists():
        raise ExtractionError(f"Snapshot tidak ditemukan: {origin}")
    if origin == destination:
        _quick_check(destination)
        return {"path": str(destination), "updated": False, "meta": ensure_schema(destination)}

    checksum_file = Path(str(origin) + CHECKSUM_SUFFIX)
    expected = ""
    if checksum_file.exists():
        expected = checksum_file.read_text(encoding="ascii").strip().lower()
    actual = sha256_file(origin)
    if expected and expected != actual:
        raise ExtractionError(
            "Checksum snapshot tidak cocok; unduhan tidak lengkap atau file berubah."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(origin, temporary)
    _quick_check(temporary)
    meta = ensure_schema(temporary)
    os.replace(temporary, destination)
    return {
        "path": str(destination),
        "updated": True,
        "checksum": actual,
        "meta": meta,
    }
