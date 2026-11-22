"""Identitas dan versi aplikasi: satu sumber untuk web, CLI, dan packaging.

``__version__`` adalah satu-satunya tempat nomor versi ditulis. Spec PyInstaller
memakainya untuk version resource ``.exe``, skrip Inno Setup menerimanya lewat
``/DMyAppVersion``, dan alur rilis GitHub memeriksa bahwa tag ``vX.Y.Z`` sama
dengan nilai di sini. Jangan menulis nomor versi di file lain.

Format yang didukung: ``MAJOR.MINOR.PATCH`` dengan sufiks opsional
(``-rc1``), mis. ``0.2.0`` atau ``0.3.0-rc1``.
"""

from __future__ import annotations

import re

APP_NAME = "BI Tools"
__version__ = "0.6.1"

_VERSION_RE = re.compile(r"^(?P<num>\d+\.\d+\.\d+)(?:-(?P<tag>[0-9A-Za-z.-]+))?$")


def version_tuple() -> tuple[int, int, int, int]:
    """Versi sebagai 4 angka (dipakai version resource Windows)."""
    parts = [int(part) for part in __version__.split("-")[0].split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])  # type: ignore[return-value]


def is_release_version(value: str | None = None) -> bool:
    """Apakah versi berbentuk ``X.Y.Z`` tanpa sufiks prarilis."""
    match = _VERSION_RE.match(value or __version__)
    return bool(match and not match.group("tag"))


def require_release_version() -> str:
    """Kembalikan versi atau lempar ``ValueError`` untuk format tak dikenal."""
    value = __version__
    if not _VERSION_RE.match(value):
        raise ValueError(
            f"Versi aplikasi tidak valid: {value!r} (harus MAJOR.MINOR.PATCH)"
        )
    return value


__all__ = [
    "APP_NAME",
    "__version__",
    "is_release_version",
    "require_release_version",
    "version_tuple",
]
