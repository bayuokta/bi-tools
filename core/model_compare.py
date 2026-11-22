"""Perbandingan snapshot TOM (read-only) berdasarkan definisi TMDL/TMSL persis.

Snapshot disusun oleh proses CLI anak memakai TOM. Modul ini tidak memuat TOM
dan tidak mem-parse properti model; ia hanya membandingkan string definisi yang
sudah diserialisasi TOM.
"""

from __future__ import annotations

import difflib
from typing import Any, Mapping

STATUS_SAME = "same"
STATUS_DIFFERENT = "different"
STATUS_SOURCE_ONLY = "source_only"
STATUS_TARGET_ONLY = "target_only"

ACTION_SKIP = "Skip"
ACTION_CREATE = "Create"
ACTION_UPDATE = "Update"
ACTION_DELETE = "Delete"

TYPE_ORDER = {
    "Table": 0,
    "Relationship": 1,
    "Measure": 2,
    "Calculation item": 3,
    "Data source": 4,
    "Expression": 5,
    "Perspective": 6,
    "Culture": 7,
    "Role": 8,
}
STATUS_ORDER = {
    STATUS_DIFFERENT: 0,
    STATUS_SOURCE_ONLY: 1,
    STATUS_TARGET_ONLY: 2,
    STATUS_SAME: 3,
}

# Default mengikuti ALM Toolkit (BismNormalizer app.config).
DEFAULT_OPTIONS = {
    "measures": True,
    "relationships": True,
    "expressions": True,
    "roles": False,
    "perspectives": False,
    "cultures": False,
    "partitions": False,
    "annotations": False,
    "lineage_tag": False,
    "tmsl": False,
    "measure_dependencies": True,
}


def normalize_options(value: Mapping[str, Any] | None) -> dict[str, bool]:
    """Opsi compare dengan default ALM Toolkit."""
    raw = dict(DEFAULT_OPTIONS)
    for key in raw:
        if value is not None and key in value:
            raw[key] = bool(value.get(key))
    return raw


def _normalized(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def _line_diff(source_text: str, target_text: str) -> dict[str, list[dict[str, Any]]]:
    source = source_text.splitlines() if source_text else []
    target = target_text.splitlines() if target_text else []
    changed_source: set[int] = set()
    changed_target: set[int] = set()
    matcher = difflib.SequenceMatcher(None, source, target, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            changed_source.update(range(i1, i2))
        if tag in {"replace", "insert"}:
            changed_target.update(range(j1, j2))
    return {
        "source": [
            {"number": index + 1, "text": line, "changed": index in changed_source}
            for index, line in enumerate(source)
        ],
        "target": [
            {"number": index + 1, "text": line, "changed": index in changed_target}
            for index, line in enumerate(target)
        ],
    }


def _object_map(snapshot: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for item in snapshot.get("objects") or []:
        object_type = str(item.get("type") or "")
        key = str(item.get("key") or "")
        if not object_type or not key:
            continue
        result[(object_type.casefold(), key.casefold())] = dict(item)
    return result


def _item(
    object_type: str,
    key: str,
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_text = _normalized(str((source or {}).get("definition") or ""))
    target_text = _normalized(str((target or {}).get("definition") or ""))
    if source is not None and target is not None:
        status = STATUS_SAME if source_text == target_text else STATUS_DIFFERENT
    elif source is not None:
        status = STATUS_SOURCE_ONLY
    else:
        status = STATUS_TARGET_ONLY
    action = {
        STATUS_SAME: ACTION_SKIP,
        STATUS_DIFFERENT: ACTION_UPDATE,
        STATUS_SOURCE_ONLY: ACTION_CREATE,
        STATUS_TARGET_ONLY: ACTION_DELETE,
    }[status]
    current = source or target or {}
    return {
        "id": object_type.casefold().replace(" ", "-") + ":" + key.casefold(),
        "type": object_type,
        "key": key,
        "name": str(current.get("name") or ""),
        "source_name": str((source or {}).get("name") or ""),
        "target_name": str((target or {}).get("name") or ""),
        "parent": str(current.get("parent") or ""),
        "status": status,
        "action": action,
        "source_definition": source_text,
        "target_definition": target_text,
        "diff": _line_diff(source_text, target_text),
        "properties": [],
    }


def compare_snapshots(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bandingkan dua snapshot TOM dan kembalikan item + statistik."""
    settings = normalize_options(options)
    source_objects = _object_map(source)
    target_objects = _object_map(target)
    items: list[dict[str, Any]] = []
    for object_type, key in sorted(
        set(source_objects) | set(target_objects),
        key=lambda pair: (
            TYPE_ORDER.get(pair[0].title(), 99),
            pair[1],
        ),
    ):
        left = source_objects.get((object_type, key))
        right = target_objects.get((object_type, key))
        display_type = str((left or right or {}).get("type") or object_type)
        display_key = str((left or right or {}).get("key") or key)
        items.append(_item(display_type, display_key, left, right))

    items.sort(
        key=lambda item: (
            STATUS_ORDER.get(item["status"], 9),
            TYPE_ORDER.get(item["type"], 99),
            item["parent"].casefold(),
            item["name"].casefold(),
        )
    )
    counts = {
        "total": len(items),
        STATUS_SAME: 0,
        STATUS_DIFFERENT: 0,
        STATUS_SOURCE_ONLY: 0,
        STATUS_TARGET_ONLY: 0,
    }
    by_type: dict[str, int] = {}
    for item in items:
        counts[item["status"]] += 1
        by_type[item["type"]] = by_type.get(item["type"], 0) + 1
    return {
        "options": settings,
        "items": items,
        "warnings": [
            *list(source.get("warnings") or []),
            *list(target.get("warnings") or []),
        ],
        "stats": {**counts, "by_type": by_type},
    }
