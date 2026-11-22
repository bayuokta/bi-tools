"""Perbandingan dua semantic model (read-only).

Modul ini hanya menyusun snapshot metadata dari ``LiveModel`` dan
membandingkannya. Tidak ada koneksi tulis, TOM, atau perubahan model.
"""

from __future__ import annotations

import difflib
from typing import Any, Iterable, Mapping

from .model import LiveModel, build_columns, build_measures, read_model_metadata

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
    "Column": 1,
    "Measure": 2,
    "Relationship": 3,
    "Expression": 4,
    "M query": 5,
    "Role": 6,
}
STATUS_ORDER = {
    STATUS_DIFFERENT: 0,
    STATUS_SOURCE_ONLY: 1,
    STATUS_TARGET_ONLY: 2,
    STATUS_SAME: 3,
}

DEFAULT_OPTIONS = {
    "measures": True,
    "relationships": True,
    "expressions": True,
    "format_string": False,
    "roles": True,
}


def normalize_options(value: Mapping[str, Any] | None) -> dict[str, bool]:
    """Opsi compare dengan default yang aman (semua metadata utama)."""
    raw = dict(DEFAULT_OPTIONS)
    for key in raw:
        if value is not None and key in value:
            raw[key] = bool(value.get(key))
    return raw


def snapshot_from_model(model: LiveModel) -> dict[str, Any]:
    """Snapshot metadata yang siap dibandingkan dari satu ``LiveModel``."""
    columns, _excluded, _warnings = build_columns(model)
    measures = build_measures(model)
    metadata = read_model_metadata(model)
    return {
        "model": str(model.model_row.get("Name") or model.catalog or ""),
        "catalog": str(model.catalog or ""),
        "tables": list(metadata.get("tables") or []),
        "columns": columns,
        "measures": measures,
        "relationships": list(metadata.get("relationships") or []),
        "expressions": list(metadata.get("expressions") or []),
        "partitions": list(metadata.get("partitions") or []),
        "roles": list(metadata.get("roles") or []),
    }


def _text(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip()
    return text or "—"


def _key(*parts: Any) -> str:
    return "|".join(str(part or "").casefold() for part in parts)


def _definition(name: str, properties: Iterable[tuple[str, str]]) -> str:
    lines = [name]
    for label, value in properties:
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


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


def _item(
    object_type: str,
    key: str,
    source: Mapping[str, Any] | None,
    target: Mapping[str, Any] | None,
    *,
    source_name: str,
    target_name: str,
    source_definition: str,
    target_definition: str,
    parent: str = "",
    properties: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if source is not None and target is not None:
        changed = [
            property_
            for property_ in (properties or [])
            if property_["source"] != property_["target"]
        ]
        status = STATUS_DIFFERENT if changed else STATUS_SAME
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
    return {
        "id": object_type.casefold().replace(" ", "-") + ":" + key,
        "type": object_type,
        "key": key,
        "name": source_name or target_name,
        "source_name": source_name,
        "target_name": target_name,
        "parent": parent,
        "status": status,
        "action": action,
        "properties": properties or [],
        "source_definition": source_definition,
        "target_definition": target_definition,
        "diff": _line_diff(source_definition, target_definition),
    }


def _compare_properties(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    fields: Iterable[tuple[str, str]],
) -> list[dict[str, Any]]:
    return [
        {
            "name": label,
            "source": _text(source.get(key)),
            "target": _text(target.get(key)),
        }
        for key, label in fields
    ]


def _table_items(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fields = (("is_hidden", "Hidden"), ("storage_mode", "Storage mode"), ("description", "Description"))
    source = {_key(row.get("table")): row for row in source_rows}
    target = {_key(row.get("table")): row for row in target_rows}
    items: list[dict[str, Any]] = []
    for key in sorted(set(source) | set(target)):
        left = source.get(key)
        right = target.get(key)
        name = str((left or right or {}).get("table") or "")
        props = _compare_properties(left or {}, right or {}, fields)
        items.append(
            _item(
                "Table",
                key,
                left,
                right,
                source_name=str((left or {}).get("table") or ""),
                target_name=str((right or {}).get("table") or ""),
                source_definition=_definition(name, [(p["name"], p["source"]) for p in props]),
                target_definition=_definition(name, [(p["name"], p["target"]) for p in props]),
                properties=props,
            )
        )
    return items


def _column_items(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
    options: Mapping[str, bool],
) -> list[dict[str, Any]]:
    fields = [
        ("data_type", "Data type"),
        ("summarize_by", "Summarize by"),
        ("sort_by_column", "Sort by"),
        ("is_hidden", "Hidden"),
        ("display_folder", "Display folder"),
        ("expression", "Calculated expression"),
    ]
    if options.get("format_string"):
        fields.insert(1, ("format_string", "Format string"))
    source = {_key(row.get("table"), row.get("column")): row for row in source_rows}
    target = {_key(row.get("table"), row.get("column")): row for row in target_rows}
    items: list[dict[str, Any]] = []
    for key in sorted(set(source) | set(target)):
        left = source.get(key)
        right = target.get(key)
        current = left or right or {}
        label = f"{current.get('table')}[{current.get('column')}]"
        props = _compare_properties(left or {}, right or {}, fields)
        items.append(
            _item(
                "Column",
                key,
                left,
                right,
                source_name=str((left or {}).get("column") or ""),
                target_name=str((right or {}).get("column") or ""),
                parent=str(current.get("table") or ""),
                source_definition=_definition(label, [(p["name"], p["source"]) for p in props]),
                target_definition=_definition(label, [(p["name"], p["target"]) for p in props]),
                properties=props,
            )
        )
    return items


def _measure_items(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
    options: Mapping[str, bool],
) -> list[dict[str, Any]]:
    fields = [
        ("expression", "Expression"),
        ("data_type", "Data type"),
        ("is_hidden", "Hidden"),
        ("display_folder", "Display folder"),
        ("description", "Description"),
    ]
    if options.get("format_string"):
        fields.insert(2, ("format_string", "Format string"))
    source = {_key(row.get("table"), row.get("measure")): row for row in source_rows}
    target = {_key(row.get("table"), row.get("measure")): row for row in target_rows}
    items: list[dict[str, Any]] = []
    for key in sorted(set(source) | set(target)):
        left = source.get(key)
        right = target.get(key)
        current = left or right or {}
        label = f"{current.get('table')}[{current.get('measure')}]"
        props = _compare_properties(left or {}, right or {}, fields)
        items.append(
            _item(
                "Measure",
                key,
                left,
                right,
                source_name=str((left or {}).get("measure") or ""),
                target_name=str((right or {}).get("measure") or ""),
                parent=str(current.get("table") or ""),
                source_definition=_definition(label, [(p["name"], p["source"]) for p in props]),
                target_definition=_definition(label, [(p["name"], p["target"]) for p in props]),
                properties=props,
            )
        )
    return items


def _relationship_key(row: Mapping[str, Any]) -> str:
    return _key(
        row.get("from_table"),
        row.get("from_column"),
        row.get("to_table"),
        row.get("to_column"),
    )


def _relationship_items(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fields = (
        ("cross_filtering", "Cross filter"),
        ("security_filtering", "Security filter"),
        ("is_active", "Active"),
        ("from_cardinality", "From cardinality"),
        ("to_cardinality", "To cardinality"),
        ("join_on_date_behavior", "Join on date"),
    )
    source = {_relationship_key(row): row for row in source_rows}
    target = {_relationship_key(row): row for row in target_rows}
    items: list[dict[str, Any]] = []
    for key in sorted(set(source) | set(target)):
        left = source.get(key)
        right = target.get(key)
        current = left or right or {}
        label = (
            f"'{current.get('from_table')}'[{current.get('from_column')}] -> "
            f"'{current.get('to_table')}'[{current.get('to_column')}]"
        )
        props = [
            {
                "name": "From",
                "source": f"'{current.get('from_table')}'[{current.get('from_column')}]",
                "target": f"'{current.get('from_table')}'[{current.get('from_column')}]",
            },
            {
                "name": "To",
                "source": f"'{current.get('to_table')}'[{current.get('to_column')}]",
                "target": f"'{current.get('to_table')}'[{current.get('to_column')}]",
            },
            *_compare_properties(left or {}, right or {}, fields),
        ]
        items.append(
            _item(
                "Relationship",
                key,
                left,
                right,
                source_name=label,
                target_name=label,
                source_definition=_definition(label, [(p["name"], p["source"]) for p in props]),
                target_definition=_definition(label, [(p["name"], p["target"]) for p in props]),
                properties=props,
            )
        )
    return items


def _expression_items(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fields = (("kind", "Kind"), ("data_type", "Data type"), ("expression", "Expression"))
    source = {_key(row.get("name")): row for row in source_rows}
    target = {_key(row.get("name")): row for row in target_rows}
    items: list[dict[str, Any]] = []
    for key in sorted(set(source) | set(target)):
        left = source.get(key)
        right = target.get(key)
        props = _compare_properties(left or {}, right or {}, fields)
        items.append(
            _item(
                "Expression",
                key,
                left,
                right,
                source_name=str((left or {}).get("name") or ""),
                target_name=str((right or {}).get("name") or ""),
                source_definition=str((left or {}).get("expression") or ""),
                target_definition=str((right or {}).get("expression") or ""),
                properties=props,
            )
        )
    return items


def _m_query_items(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    fields = (("mode", "Mode"), ("source_type", "Source type"), ("source", "M query"))
    source = {
        _key(row.get("table"), row.get("partition")): row for row in source_rows
    }
    target = {
        _key(row.get("table"), row.get("partition")): row for row in target_rows
    }
    items: list[dict[str, Any]] = []
    for key in sorted(set(source) | set(target)):
        left = source.get(key)
        right = target.get(key)
        current = left or right or {}
        props = _compare_properties(left or {}, right or {}, fields)
        items.append(
            _item(
                "M query",
                key,
                left,
                right,
                source_name=str((left or {}).get("partition") or ""),
                target_name=str((right or {}).get("partition") or ""),
                parent=str(current.get("table") or ""),
                source_definition=str((left or {}).get("source") or ""),
                target_definition=str((right or {}).get("source") or ""),
                properties=props,
            )
        )
    return items


def _role_properties(row: Mapping[str, Any] | None) -> list[tuple[str, str]]:
    if not row:
        return []
    members = sorted(
        str(member.get("name") or "") for member in (row.get("members") or [])
    )
    permissions = sorted(
        (
            str(permission.get("table") or ""),
            str(permission.get("expression") or ""),
        )
        for permission in (row.get("permissions") or [])
    )
    lines = [
        ("Model permission", _text(row.get("model_permission"))),
        ("Members", ", ".join(members) or "—"),
    ]
    for table, expression in permissions:
        lines.append((f"RLS {table}", expression or "—"))
    return lines


def _role_items(
    source_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    source = {_key(row.get("name")): row for row in source_rows}
    target = {_key(row.get("name")): row for row in target_rows}
    items: list[dict[str, Any]] = []
    for key in sorted(set(source) | set(target)):
        left = source.get(key)
        right = target.get(key)
        name = str((left or right or {}).get("name") or "")
        left_props = dict(_role_properties(left))
        right_props = dict(_role_properties(right))
        props = [
            {
                "name": label,
                "source": _text(left_props.get(label)),
                "target": _text(right_props.get(label)),
            }
            for label in sorted(set(left_props) | set(right_props))
        ]
        items.append(
            _item(
                "Role",
                key,
                left,
                right,
                source_name=name,
                target_name=name,
                source_definition=_definition(name, list(left_props.items())),
                target_definition=_definition(name, list(right_props.items())),
                properties=props,
            )
        )
    return items


def compare_snapshots(
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bandingkan dua snapshot dan kembalikan item + statistik."""
    settings = normalize_options(options)
    items: list[dict[str, Any]] = []
    items.extend(_table_items(source.get("tables") or [], target.get("tables") or []))
    if settings["measures"]:
        items.extend(
            _column_items(source.get("columns") or [], target.get("columns") or [], settings)
        )
        items.extend(
            _measure_items(source.get("measures") or [], target.get("measures") or [], settings)
        )
    if settings["relationships"]:
        items.extend(
            _relationship_items(
                source.get("relationships") or [], target.get("relationships") or []
            )
        )
    if settings["expressions"]:
        items.extend(
            _expression_items(
                source.get("expressions") or [], target.get("expressions") or []
            )
        )
        items.extend(
            _m_query_items(
                source.get("partitions") or [], target.get("partitions") or []
            )
        )
    if settings["roles"]:
        items.extend(_role_items(source.get("roles") or [], target.get("roles") or []))

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
        "stats": {**counts, "by_type": by_type},
    }
