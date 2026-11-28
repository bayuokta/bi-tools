"""Unloaded M queries/parameters and the tables that use them.

Tab "Unloaded M queries" lists shared M queries and parameters (objects that
are not loaded as tables) together with every table whose Power Query
expression references them, directly or through another shared query. The
data is derived from ``AnalysisResult.m_queries`` plus the table status/uses
already computed by :mod:`core.table_export`.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from .m_lineage import parse_let, strip_comments
from .table_export import build_table_groups

_QUERY_KINDS = {"m query", "expression"}
_PARAMETER_KINDS = {"m parameter", "parameter"}

_STRING_LITERAL = re.compile(r'(?<!#)"(?:[^"]|"")*"')
_SHARED_REFERENCE = re.compile(r'#"[^"]+"')


def _kind(value: Any) -> str:
    text = str(value or "").strip()
    lowered = text.casefold()
    if lowered in _QUERY_KINDS:
        return "M Query"
    if lowered in _PARAMETER_KINDS:
        return "M Parameter"
    return ""


def _visible_text(expression: str) -> str:
    """Buang komentar dan string literal; pertahankan referensi ``#"Nama"``."""
    return _STRING_LITERAL.sub('""', strip_comments(expression))


def _identifiers(text: str, names: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for name in names:
        if not name:
            continue
        pattern = r"(?<![\w#])" + re.escape(name) + r"(?![\w])"
        if re.search(pattern, text):
            found.add(name)
    return found


def _scan(
    expression: str,
    parameters: set[str],
    shared: set[str],
) -> tuple[set[str], set[str]]:
    """Parameter dan shared query yang dirujuk langsung oleh satu ekspresi."""
    text = _visible_text(expression)
    steps, _ = parse_let(expression)
    bindings = {name.casefold() for name, _ in steps}
    references = {
        reference[2:-1] for reference in _SHARED_REFERENCE.findall(text)
    }
    direct_params = {
        name
        for name in parameters
        if name.casefold() not in bindings
    }
    direct_params = _identifiers(text, direct_params)
    direct_queries = {
        name for name in shared if name.casefold() not in bindings
    }
    direct_queries = _identifiers(text, direct_queries)
    for reference in references:
        if reference in parameters:
            direct_params.add(reference)
        elif reference in shared:
            direct_queries.add(reference)
    return direct_params, direct_queries


def _closure(
    expression: str,
    parameters: set[str],
    shared: dict[str, str],
) -> tuple[set[str], set[str]]:
    """Parameter/referensi langsung dan transitif lewat shared query."""
    params, refs = _scan(expression, parameters, set(shared))
    found_params = set(params)
    found_refs = set(refs)
    queue = list(refs)
    seen = set(refs)
    while queue:
        name = queue.pop()
        nested = shared.get(name)
        if not nested:
            continue
        params_nested, refs_nested = _scan(
            nested, parameters, set(shared)
        )
        found_params |= params_nested
        for ref in refs_nested:
            if ref not in seen and ref in shared:
                seen.add(ref)
                found_refs.add(ref)
                queue.append(ref)
    return found_params, found_refs


def build_unloaded_queries(result: Any) -> list[dict[str, Any]]:
    """Susun root M query/parameter beserta daftar tabel pemakainya."""
    dataset = str(getattr(result, "dataset_name", "") or "")
    rows = [
        row
        for row in (getattr(result, "m_queries", []) or [])
        if isinstance(row, Mapping)
    ]

    expressions: list[dict[str, Any]] = []
    tables: dict[str, set[str]] = {}
    for index, row in enumerate(rows):
        kind = _kind(row.get("kind"))
        name = str(row.get("name") or "")
        expression = str(row.get("expression") or "")
        position = row.get("position")
        position = int(position) if position is not None else index
        if kind:
            expressions.append(
                {
                    "name": name,
                    "kind": kind,
                    "expression": expression,
                    "position": position,
                }
            )
        elif str(row.get("kind") or "").casefold() == "table" and name and expression:
            tables.setdefault(name, set()).add(expression)

    parameters = {
        item["name"] for item in expressions if item["kind"] == "M Parameter"
    }
    shared = {
        item["name"]: item["expression"]
        for item in expressions
        if item["kind"] == "M Query"
    }
    usage_params: dict[str, set[str]] = {name: set() for name in parameters}
    usage_queries: dict[str, set[str]] = {name: set() for name in shared}

    for table, table_expressions in tables.items():
        used_params: set[str] = set()
        used_queries: set[str] = set()
        for expression in table_expressions:
            params, refs = _closure(expression, parameters, shared)
            used_params |= params
            used_queries |= refs
        for name in used_params:
            usage_params.setdefault(name, set()).add(table)
        for name in used_queries:
            usage_queries.setdefault(name, set()).add(table)

    groups = {
        str(group.get("table") or "").casefold(): group
        for group in build_table_groups(result)
    }

    expressions.sort(
        key=lambda item: (
            0 if item["kind"] == "M Query" else 1,
            int(item["position"]),
            item["name"].casefold(),
        )
    )
    roots: list[dict[str, Any]] = []
    for item in expressions:
        name = item["name"]
        used_by = (
            usage_queries.get(name, set())
            if item["kind"] == "M Query"
            else usage_params.get(name, set())
        )
        usages: list[dict[str, Any]] = []
        for table in sorted(used_by, key=str.casefold):
            group = groups.get(table.casefold()) or {}
            usages.append(
                {
                    "name": table,
                    "type": "Table",
                    "source": dataset,
                    "status": str(group.get("status") or ""),
                    "uses": int(group.get("uses") or 0),
                }
            )
        roots.append(
            {
                "name": name,
                "type": item["kind"],
                "source": dataset,
                "status": "Used" if usages else "Unused",
                "uses": len(usages),
                "expression": item["expression"],
                "usages": usages,
            }
        )
    return roots
