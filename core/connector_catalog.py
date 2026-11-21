"""Katalog konektor M dari dokumentasi Microsoft (snapshot statis).

Katalog dibuat oleh ``sync_connector_catalog.py`` dan disimpan di
``rules/m_connectors.json``. Modul ini hanya membaca aset tersebut; tidak ada
network saat runtime.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

from core.paths import RULES_DIR

CATALOG_PATH = RULES_DIR / "m_connectors.json"


@dataclass(frozen=True)
class CatalogEntry:
    """Satu fungsi/connector pada katalog dokumentasi."""

    name: str
    description: str = ""
    url: str = ""
    category: str = ""
    source: str = ""
    parameters: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, CatalogEntry]:
    """Peta nama konektor (casefold) -> metadata dokumentasi."""
    if not CATALOG_PATH.exists():
        return {}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries: dict[str, CatalogEntry] = {}
    for key in ("functions", "undocumented"):
        for item in data.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            parameters = item.get("parameters") or []
            entries[name.casefold()] = CatalogEntry(
                name=name,
                description=str(item.get("description") or ""),
                url=str(item.get("url") or item.get("doc_url") or ""),
                category=str(item.get("category") or ""),
                source=str(item.get("source") or ""),
                parameters=tuple(str(value) for value in parameters),
            )
    return entries


def catalog_names() -> set[str]:
    """Nama konektor yang tercatat di katalog (casefold)."""
    return set(load_catalog())
