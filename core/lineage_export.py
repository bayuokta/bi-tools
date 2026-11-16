"""Export hasil lineage ke CSV."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

CSV_FIELDS = [
    "depth",
    "type",
    "name",
    "workspace",
    "owner",
    "node_id",
    "path",
    "datasource_type",
    "server",
    "database",
    "path_or_url",
    "gateway_id",
    "connection_details",
]


def lineage_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Ubah hasil ``lineage()`` menjadi baris CSV dengan jalur dari root."""
    by_id = {node["node_id"]: node for node in result.get("nodes", [])}
    root = result["root"]
    by_id[root["node_id"]] = root

    def path_for(node: dict[str, Any]) -> str:
        path: list[str] = []
        current: dict[str, Any] | None = node
        seen: set[str] = set()
        while current is not None:
            node_id = current.get("node_id")
            if node_id in seen:
                break
            seen.add(node_id)
            path.insert(0, current.get("name") or "?")
            parent = current.get("parent")
            current = by_id.get(parent) if parent else None
        return " > ".join(path)

    rows: list[dict[str, Any]] = []
    for node in sorted(
        result.get("nodes", []),
        key=lambda item: (
            item.get("depth", 0),
            item.get("node_type") or "",
            (item.get("name") or "").casefold(),
        ),
    ):
        rows.append(
            {
                "depth": node.get("depth", 0),
                "type": node.get("node_type") or "",
                "name": node.get("name") or "",
                "workspace": node.get("workspace_name") or "",
                "owner": node.get("owner") or "",
                "node_id": node.get("node_id") or "",
                "path": path_for(node),
                "datasource_type": node.get("datasource_type") or "",
                "server": node.get("server") or "",
                "database": node.get("database_name") or "",
                "path_or_url": node.get("path_or_url") or "",
                "gateway_id": node.get("gateway_id") or "",
                "connection_details": json.dumps(
                    node.get("connection_details") or {},
                    ensure_ascii=False,
                ),
            }
        )
    return rows


def write_lineage_csv(path: Path | str, result: dict[str, Any]) -> Path:
    """Tulis CSV UTF-8 dengan BOM agar Excel membaca karakter non-ASCII."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows: Iterable[dict[str, Any]] = lineage_rows(result)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return target
