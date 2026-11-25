"""Ekspor definisi semantic model dari TOM ke TMDL dan TMSL.

Hanya dijalankan di proses CLI anak (``bi-tools-cli tom-worker``); modul ini
memuat TOM hanya saat :func:`export_model` dipanggil, sehingga aman diimpor
tanpa .NET.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ExtractionError


def _database(server: Any, catalog: str) -> Any:
    try:
        return server.Databases.GetByName(catalog)
    except Exception as exc:  # noqa: BLE001 - pesan engine tidak seragam
        try:
            available = [str(item.Name) for item in server.Databases]
        except Exception:  # noqa: BLE001
            available = []
        detail = f" Dataset tersedia: {', '.join(available)}." if available else ""
        raise ExtractionError(
            f"Dataset '{catalog}' tidak ditemukan di server TOM.{detail}"
        ) from exc


def export_model(server: Any, catalog: str, target: Path | str) -> dict[str, Any]:
    """Tulis definisi model ke ``definition/`` (TMDL) + ``model.bim`` (TMSL)."""
    from .tom_client import load_tom

    load_tom()
    from Microsoft.AnalysisServices.Tabular import (  # noqa: WPS433 - lazy .NET
        JsonSerializer,
        SerializeOptions,
        TmdlSerializer,
    )

    database = _database(server, catalog)
    root = Path(target).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    tmdl_dir = root / "definition"
    try:
        TmdlSerializer.SerializeDatabaseToFolder(database, str(tmdl_dir))
    except Exception as exc:  # noqa: BLE001 - serializer melempar .NET exception
        raise ExtractionError(f"Serialisasi TMDL gagal: {exc}") from exc

    try:
        text = str(JsonSerializer.SerializeDatabase(database, SerializeOptions()))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"Serialisasi TMSL gagal: {exc}") from exc
    (root / "model.bim").write_text(text, encoding="utf-8")

    files = [path for path in root.rglob("*") if path.is_file()]
    return {
        "catalog": catalog,
        "files": len(files),
        "bytes": sum(path.stat().st_size for path in files),
    }
