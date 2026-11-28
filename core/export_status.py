"""Status tampilan ekspor yang mengikuti Measure Killer (read-only).

Measure Killer membedakan objek yang hanya dipakai objek tak terpakai
(``Used by unused``) dan kolom duplikat yang disarankan dihapus manual
(``Unused (remove manually)``). Modul ini menurunkan status itu dari
``AnalysisResult`` tanpa mengubah verdict internal/UI.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .relationship_export import relationship_usage

_REF = re.compile(r"^'?(?P<table>[^'\]]+)'?\[(?P<name>[^\]]+)\]$")


def _parse_ref(value: Any) -> tuple[str, str] | None:
    text = str(value or "").strip()
    match = _REF.match(text)
    if not match:
        return None
    return match.group("table").strip(), match.group("name").strip()


def _pair_key(left: tuple[str, str], right: tuple[str, str]) -> frozenset:
    return frozenset(
        ((left[0].casefold(), left[1].casefold()), (right[0].casefold(), right[1].casefold()))
    )


def _relationship_statuses(result: Any) -> tuple[dict[str, str], dict[frozenset, str]]:
    usage = relationship_usage(result)
    by_name: dict[str, str] = {}
    by_pair: dict[frozenset, str] = {}
    for relationship in getattr(result, "relationships", []) or []:
        if not isinstance(relationship, Mapping):
            continue
        key = str(
            relationship.get("relationship_id")
            or relationship.get("name")
            or relationship.get("id")
            or ""
        )
        entries = usage.get(key, [])
        if entries:
            status = (
                "Used"
                if any(str(entry.get("status") or "") != "Unused" for entry in entries)
                else "Used by unused"
            )
        else:
            status = "Used" if bool(relationship.get("is_active")) else "Unused"
        by_name[key] = status
        pair = _pair_key(
            (
                str(relationship.get("from_table") or ""),
                str(relationship.get("from_column") or ""),
            ),
            (
                str(relationship.get("to_table") or ""),
                str(relationship.get("to_column") or ""),
            ),
        )
        by_pair[pair] = status
    return by_name, by_pair


def _relationship_ref_status(
    ref: Any, own: tuple[str, str], by_pair: Mapping[frozenset, str]
) -> str:
    target = _parse_ref(getattr(ref, "object", ""))
    if target is None:
        return "Used"
    return by_pair.get(_pair_key(own, target), "Used")


def relationship_status_map(result: Any) -> dict[str, str]:
    """Status hubungan (``Used``/``Used by unused``/``Unused``) per ID."""
    return _relationship_statuses(result)[0]


def effective_status_map(result: Any) -> dict[tuple[str, str, str], str]:
    """Peta ``(kind, table, name)`` -> status ekspor Measure Killer."""
    measures = {
        (item.measure.table.casefold(), item.measure.measure.casefold()): item
        for item in (getattr(result, "measures", []) or [])
    }
    columns = {
        (item.column.table.casefold(), item.column.column.casefold()): item
        for item in (getattr(result, "columns", []) or [])
    }
    _, rel_by_pair = _relationship_statuses(result)
    base: dict[tuple[str, str, str], str] = {}
    for key, item in measures.items():
        base[("measure", key[0], key[1])] = str(getattr(item, "status", "") or "")
    for key, item in columns.items():
        base[("column", key[0], key[1])] = str(getattr(item, "status", "") or "")

    def ref_effective(kind: str, table: str, name: str) -> str:
        key = (kind.casefold(), table.casefold(), name.casefold())
        return base.get(key, "Used")

    result_map: dict[tuple[str, str, str], str] = {}
    for key, item in measures.items():
        status = str(getattr(item, "status", "") or "")
        records = list(getattr(item, "report_records", []) or [])
        refs = list(getattr(item, "model_refs", []) or [])
        if not records and refs:
            inactive = []
            for ref in refs:
                kind = str(getattr(ref, "kind", "") or "").casefold()
                target = _parse_ref(getattr(ref, "object", ""))
                if kind in {"measure", "calculated column"} and target:
                    inactive.append(
                        ref_effective("measure", target[0], target[1]) in {"Unused", "Used by unused"}
                        or ref_effective("column", target[0], target[1]) in {"Unused", "Used by unused"}
                    )
                elif kind == "relationship":
                    inactive.append(
                        _relationship_ref_status(ref, key, rel_by_pair)
                        in {"Unused", "Used by unused"}
                    )
                else:
                    inactive.append(False)
            if inactive and all(inactive):
                status = "Used by unused"
        result_map[("measure", key[0], key[1])] = status

    for key, item in columns.items():
        status = str(getattr(item, "status", "") or "")
        records = list(getattr(item, "report_records", []) or [])
        refs = list(getattr(item, "model_refs", []) or [])
        if not records and refs:
            inactive = []
            for ref in refs:
                kind = str(getattr(ref, "kind", "") or "").casefold()
                target = _parse_ref(getattr(ref, "object", ""))
                if kind in {"measure", "calculated column"} and target:
                    inactive.append(
                        ref_effective("measure", target[0], target[1]) in {"Unused", "Used by unused"}
                        or ref_effective("column", target[0], target[1]) in {"Unused", "Used by unused"}
                    )
                elif kind == "relationship":
                    inactive.append(
                        _relationship_ref_status(ref, key, rel_by_pair)
                        in {"Unused", "Used by unused"}
                    )
                else:
                    inactive.append(False)
            if inactive and all(inactive):
                status = "Used by unused"
        if status == "Unused" and not refs and not records:
            source = str(getattr(item.column, "source_column", "") or "")
            parsed = _parse_ref(source)
            if parsed and parsed[0].casefold() != key[0]:
                status = "Unused (remove manually)"
        result_map[("column", key[0], key[1])] = status

    return result_map


def effective_status(result: Any, kind: str, table: str, name: str) -> str:
    key = (kind.casefold(), table.casefold(), name.casefold())
    return effective_status_map(result).get(key, "")
