"""Identitas RLS untuk capture screenshot Power BI Service.

Kredensial aplikasi tidak lagi disimpan di sini: token diambil dari
:class:`core.auth.EntraTokens` (service principal yang sama dengan Fabric/Power
BI REST dan XMLA). Modul ini hanya menyimpan identitas efektif untuk
``GenerateToken``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

from ..pbix import ROOT

DEFAULT_ENV_FILE = ROOT / ".env"


def split_roles(value: Iterable[str] | str | None) -> tuple[str, ...]:
    """Ubah "HO,Region" atau list menjadi tuple role tanpa entri kosong."""
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.replace(";", ",")
        parts = text.split(",")
    else:
        parts = list(value)
    return tuple(str(part).strip() for part in parts if str(part).strip())


@dataclass(frozen=True)
class CaptureCredentials:
    """Identitas RLS (effective identity) untuk embed token."""

    rls_username: str = ""
    rls_roles: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env_file: Path | str | None = None) -> "CaptureCredentials":
        """Baca RLS_USERNAME/RLS_ROLES dari environment atau ``.env``."""
        path = Path(env_file).expanduser() if env_file else DEFAULT_ENV_FILE
        if path.exists():
            load_dotenv(path, override=False)
        return cls(
            rls_username=os.getenv("RLS_USERNAME", "").strip(),
            rls_roles=split_roles(os.getenv("RLS_ROLES", "")),
        )
