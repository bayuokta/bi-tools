"""Lineage graph satu kolom/measure dari hasil analisa semantic model.

Modul ini tidak memakai XMLA, REST, atau SQLite: seluruh data diambil dari
``AnalysisResult`` yang sudah ada di sesi analisa (ukuran kolom, referensi
model, pemakaian report, dan ekspresi M). Hasilnya berupa node + edge + tata
letak siap gambar (upstream di kiri, objek terpilih di tengah, pemakai di
kanan), sehingga ``web\\app.js`` hanya merender dan tidak menyusun lineage.

Arah edge selalu "penyedia data -> pemakai": tabel M -> kolom, kolom -> measure
yang memakainya, measure -> report -> halaman -> visual/filter. Dengan begitu
semua edge mengalir dari kiri ke kanan.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any, Iterable, Mapping

from core.m_lineage import (
    build_lineage as build_m_lineage,
    column_confidence,
    warning_rows,
)

MAX_NODES = 250
MAX_USAGE_PER_PAGE = 8
MAX_DEPTH = 8
MAX_M_STEPS = 8

DIRECTIONS = ("both", "upstream", "downstream")
CATEGORIES = (
    "all",
    "measures",
    "columns",
    "relationships",
    "sorting",
    "security",
    "field-parameters",
    "reports",
    "calculations",
)
CATEGORY_KINDS = {
    "measures": {"measure"},
    "columns": {"column"},
    "relationships": {"relationship"},
    "sorting": {"sort"},
    "security": {"security"},
    "field-parameters": {"field-parameter"},
    "reports": {"report", "page", "visual", "filter"},
    "calculations": {"calculation", "kpi", "table"},
}

# Urutan dalam satu kolom layout: sumber M dulu, lalu model, lalu report.
GROUP_ORDER = {"mquery": 0, "model": 1, "report": 2, "page": 3, "usage": 4, "more": 5}

NODE_W = 230
NODE_H = 64
COL_GAP = 140
ROW_GAP = 16
PAD = 28

REPORT_KINDS = {
    "field": "visual",
    "filter-report": "filter",
    "filter-page": "filter",
    "filter-visual": "filter",
    "filter-query": "filter",
    "sort": "sort",
    "format": "visual",
}

_MODEL_KINDS = {
    "calculated column",
    "calculated table column",
    "calculated table",
    "calculation item",
    "KPI",
    "relationship",
    "sort by",
    "hierarchy",
    "RLS",
    "column permission",
    "field parameter",
}


def _parse_object(text: str) -> tuple[str, str]:
    """Baca ``'Tabel'[Kolom]`` menjadi pasangan tabel/kolom."""
    value = str(text or "").strip()
    if not value:
        return "", ""
    match = re.match(r"^'((?:[^']|'')+)'\s*\[([^\]]+)\]$", value)
    if not match:
        match = re.match(r"^([^\[\]]+?)\s*\[([^\]]+)\]$", value)
    if not match:
        return "", ""
    return match.group(1).replace("''", "'"), match.group(2)


def _column_id(table: str, column: str) -> str:
    return f"col:{table}:{column}"


def _measure_id(table: str, measure: str) -> str:
    return f"measure:{table}:{measure}"


def _mquery_id(table: str) -> str:
    return f"mquery:{table}"


class _Graph:
    """Akumulator node/edge dengan batas jumlah node."""

    def __init__(self, max_nodes: int) -> None:
        self.max_nodes = max(20, int(max_nodes))
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, str]] = {}
        self.truncated = 0

    def add(self, node: Mapping[str, Any]) -> bool:
        node_id = str(node.get("id") or "")
        if not node_id:
            return False
        if node_id in self.nodes:
            current = self.nodes[node_id]
            current["count"] = int(current.get("count") or 0) + int(
                node.get("count") or 0
            )
            if node.get("level") is not None:
                current["level"] = min(
                    int(current.get("level") or node["level"]),
                    int(node["level"]),
                )
            return True
        if len(self.nodes) >= self.max_nodes:
            self.truncated += 1
            return False
        payload = dict(node)
        payload.setdefault("count", 0)
        self.nodes[node_id] = payload
        return True

    def link(self, source: str, target: str, kind: str) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        if source == target:
            return
        self.edges.setdefault(
            (source, target, kind),
            {"from": source, "to": target, "kind": kind},
        )

    def add_report_chain(
        self,
        *,
        owner_id: str,
        records: Iterable[Mapping[str, Any]],
        base_depth: int,
        depth: int,
        report_names: Mapping[str, str],
    ) -> None:
        """Tambahkan rantai report -> halaman -> visual/filter di kanan owner."""
        if base_depth + 1 > depth:
            return
        grouped: dict[str, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, Mapping):
                continue
            report_id = str(record.get("report_id") or "")
            report_name = str(record.get("report_name") or "")
            key = report_id or report_name or "?"
            entry = grouped.setdefault(
                key,
                {
                    "report_id": report_id,
                    "name": report_name or report_names.get(report_id, ""),
                    "pages": defaultdict(list),
                },
            )
            if not entry["name"] and report_name:
                entry["name"] = report_name
            page_id = str(record.get("page_id") or "")
            page_name = str(record.get("page_name") or "")
            page_key = page_id or page_name or "?"
            entry["pages"][page_key].append(record)

        for report_key in sorted(grouped):
            report = grouped[report_key]
            report_node_id = f"report:{report['report_id'] or report['name'] or '?'}"
            short_id = str(report["report_id"] or "")[:8]
            added = self.add(
                {
                    "id": report_node_id,
                    "kind": "report",
                    "label": report["name"] or "(report)",
                    "context": short_id,
                    "group": "report",
                    "side": "downstream",
                    "level": base_depth + 1,
                }
            )
            if not added and report_node_id not in self.nodes:
                continue
            self.link(owner_id, report_node_id, "usage")
            if base_depth + 2 > depth:
                continue
            for page_key in sorted(report["pages"]):
                page_records = report["pages"][page_key]
                page_name = ""
                page_id = ""
                for record in page_records:
                    page_name = page_name or str(record.get("page_name") or "")
                    page_id = page_id or str(record.get("page_id") or "")
                page_node_id = f"page:{report_node_id}:{page_id or page_name or '?'}"
                if not self.add(
                    {
                        "id": page_node_id,
                        "kind": "page",
                        "label": page_name or "(no page)",
                        "context": (report["name"] or "") +
                        (f" ({short_id})" if short_id else ""),
                        "group": "page",
                        "side": "downstream",
                        "level": base_depth + 2,
                    }
                ) and page_node_id not in self.nodes:
                    continue
                self.link(report_node_id, page_node_id, "page")
                if base_depth + 3 > depth:
                    continue
                self._add_usage_nodes(
                    page_node_id,
                    page_records,
                    report_node_id=report_node_id,
                    page_name=page_name,
                    level=base_depth + 3,
                )

    def _add_usage_nodes(
        self,
        page_node_id: str,
        records: list[Mapping[str, Any]],
        *,
        report_node_id: str,
        page_name: str,
        level: int,
    ) -> None:
        unique: dict[str, dict[str, Any]] = {}
        for record in records:
            usage_kind = str(record.get("usage_kind") or "field")
            kind = REPORT_KINDS.get(usage_kind, "usage")
            visual_id = str(record.get("visual_id") or "")
            if kind == "visual":
                label = (
                    str(record.get("visual_title") or "")
                    or str(record.get("visual_type") or "")
                    or str(record.get("detail") or "")
                    or "(usage)"
                )
            else:
                label = (
                    str(record.get("detail") or "")
                    or str(record.get("visual_title") or "")
                    or str(record.get("visual_type") or "")
                    or "(usage)"
                )
            key = f"{usage_kind}:{visual_id or label}"
            entry = unique.setdefault(
                key,
                {
                    "kind": kind,
                    "usage_kind": usage_kind,
                    "label": label,
                    "detail": str(record.get("detail") or ""),
                    "count": 0,
                    "hidden": True,
                },
            )
            entry["count"] += 1
            entry["hidden"] = entry["hidden"] and bool(record.get("is_hidden"))
            if kind != "visual" and not entry["detail"]:
                entry["detail"] = str(record.get("detail") or "")
        ordered = sorted(
            unique.items(),
            key=lambda item: (
                REPORT_KINDS.get(item[1]["usage_kind"], "usage"),
                item[1]["label"].casefold(),
            ),
        )
        visuals = [item for item in ordered if item[1]["kind"] == "visual"]
        others = [item for item in ordered if item[1]["kind"] != "visual"]
        kept = visuals[:MAX_USAGE_PER_PAGE] + others[:MAX_USAGE_PER_PAGE]
        extra = visuals[MAX_USAGE_PER_PAGE:] + others[MAX_USAGE_PER_PAGE:]
        for key, entry in kept:
            node_id = f"usage:{report_node_id}:{page_node_id}:{key}"
            if not self.add(
                {
                    "id": node_id,
                    "kind": entry["kind"],
                    "label": entry["label"],
                    "context": page_name,
                    "group": "usage",
                    "detail": entry["detail"],
                    "count": entry["count"],
                    "hidden": entry["hidden"],
                    "side": "downstream",
                    "level": level,
                }
            ):
                continue
            self.link(page_node_id, node_id, entry["kind"])
        if extra:
            total = sum(int(entry["count"]) for _key, entry in extra)
            node_id = f"more:{report_node_id}:{page_node_id}"
            if self.add(
                {
                    "id": node_id,
                    "kind": "more",
                    "label": f"+{len(extra)}",
                    "context": page_name,
                    "group": "more",
                    "count": total,
                    "side": "downstream",
                    "level": level,
                }
            ):
                self.link(page_node_id, node_id, "usage")


def _build_outline(graph: _Graph, seed_id: str) -> dict[str, Any]:
    """Struktur pohon upstream/downstream untuk tampilan outline."""
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges.values():
        outgoing[edge["from"]].add(edge["to"])
        incoming[edge["to"]].add(edge["from"])

    def sort_key(node_id: str) -> tuple[Any, ...]:
        node = graph.nodes[node_id]
        return (
            GROUP_ORDER.get(str(node.get("group") or ""), 9),
            str(node.get("kind") or ""),
            str(node.get("label") or "").casefold(),
            node_id,
        )

    def build(
        node_id: str,
        adjacency: Mapping[str, set[str]],
        level: int,
        seen: set[str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for child_id in sorted(adjacency.get(node_id, ()), key=sort_key):
            node = graph.nodes.get(child_id)
            if node is None:
                continue
            item = {
                "id": child_id,
                "kind": str(node.get("kind") or ""),
                "label": str(node.get("label") or ""),
                "context": str(node.get("context") or ""),
                "status": str(node.get("status") or ""),
                "count": int(node.get("count") or 0),
                "children": [],
            }
            if child_id in seen:
                item["repeat"] = True
            elif level <= 10:
                seen.add(child_id)
                item["children"] = build(child_id, adjacency, level + 1, seen)
            items.append(item)
        return items

    return {
        "upstream": build(seed_id, incoming, 1, {seed_id}),
        "downstream": build(seed_id, outgoing, 1, {seed_id}),
    }


def build_lineage(
    result: Any,
    *,
    kind: str,
    table: str,
    name: str,
    direction: str = "both",
    depth: int = 4,
    max_nodes: int = MAX_NODES,
    category: str = "all",
) -> dict[str, Any]:
    """Susun graph lineage satu kolom/measure dari ``AnalysisResult``.

    ``ValueError`` dilempar untuk input yang tidak valid atau seed yang tidak
    ada di hasil analisa; pemanggil (presenter) memetakannya ke
    ``ExtractionError``.
    """
    wanted = str(kind or "").strip().lower()
    if wanted not in {"column", "measure"}:
        raise ValueError("Jenis lineage harus 'column' atau 'measure'.")
    mode = str(direction or "both").strip().lower()
    if mode not in DIRECTIONS:
        raise ValueError("Arah lineage harus 'both', 'upstream', atau 'downstream'.")
    try:
        limit = max(1, min(MAX_DEPTH, int(depth or 4)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Kedalaman lineage harus angka 1-8.") from exc
    scope = str(category or "all").strip().lower()
    if scope not in CATEGORIES:
        raise ValueError("Kategori dependensi tidak dikenal.")

    column_analyses: dict[str, Any] = {}
    measure_analyses: dict[str, Any] = {}
    for analysis in getattr(result, "columns", []) or []:
        column = getattr(analysis, "column", None)
        if column is None:
            continue
        column_analyses[_column_id(column.table, column.column)] = analysis
    for analysis in getattr(result, "measures", []) or []:
        measure = getattr(analysis, "measure", None)
        if measure is None:
            continue
        measure_analyses[_measure_id(measure.table, measure.measure)] = analysis

    column_lookup = {
        (analysis.column.table.casefold(), analysis.column.column.casefold()): node_id
        for node_id, analysis in column_analyses.items()
    }
    measure_lookup = {
        (analysis.measure.table.casefold(), analysis.measure.measure.casefold()): node_id
        for node_id, analysis in measure_analyses.items()
    }

    if wanted == "column":
        seed_id = column_lookup.get((str(table).casefold(), str(name).casefold()))
    else:
        seed_id = measure_lookup.get((str(table).casefold(), str(name).casefold()))
    if not seed_id:
        raise ValueError(
            "Kolom/measure tidak ditemukan di hasil analisa. Jalankan analisa ulang."
        )

    extra_nodes: dict[str, dict[str, Any]] = {}
    deps: dict[str, set[str]] = defaultdict(set)
    users: dict[str, set[str]] = defaultdict(set)

    def depend(consumer: str, provider: str) -> None:
        if not consumer or not provider or consumer == provider:
            return
        deps[consumer].add(provider)
        users[provider].add(consumer)

    def add_extra(
        node_id: str,
        *,
        kind: str,
        label: str,
        context: str = "",
        detail: str = "",
        group: str = "model",
    ) -> str:
        extra_nodes.setdefault(
            node_id,
            {
                "id": node_id,
                "kind": kind,
                "label": label,
                "context": context,
                "detail": detail,
                "group": group,
            },
        )
        return node_id

    def resolve_measure(text: str) -> str | None:
        ref_table, ref_name = _parse_object(text)
        if not ref_table or not ref_name:
            return None
        return measure_lookup.get((ref_table.casefold(), ref_name.casefold()))

    def resolve_column(text: str) -> str | None:
        ref_table, ref_name = _parse_object(text)
        if not ref_table or not ref_name:
            return None
        return column_lookup.get((ref_table.casefold(), ref_name.casefold()))

    def ref_node(kind: str, object_text: str, detail: str) -> str | None:
        """Node sintetis untuk pemakaian model di luar kolom/measure."""
        label = object_text
        context = ""
        group = "model"
        node_kind = "usage"
        if kind == "relationship":
            other_table, other_name = _parse_object(object_text)
            label = f"{other_table}[{other_name}]" if other_table else object_text
            context = other_table
            node_kind = "relationship"
            identity = f"rel:{other_table}:{other_name}"
        elif kind == "sort by":
            owner_table, owner_name = _parse_object(object_text)
            label = owner_name or object_text
            context = owner_table
            node_kind = "sort"
            identity = f"sort:{owner_table}:{owner_name}"
        elif kind == "hierarchy":
            owner_table, owner_name = _parse_object(object_text)
            label = owner_name or object_text
            context = owner_table
            node_kind = "hierarchy"
            identity = f"hierarchy:{owner_table}:{owner_name}"
        elif kind in {"RLS", "column permission"}:
            label = object_text or ("OLS" if kind == "column permission" else "RLS")
            node_kind = "security"
            detail = "OLS" if kind == "column permission" else "RLS"
            identity = f"security:{kind}:{object_text}"
        elif kind == "field parameter":
            parameter = object_text.strip("'") or object_text
            label = parameter
            node_kind = "field-parameter"
            identity = f"field-parameter:{parameter}"
        elif kind == "calculated table":
            label = object_text.strip("'") or object_text
            node_kind = "table"
            identity = f"table:{label}"
        elif kind in {"calculation item", "KPI"}:
            label = object_text
            node_kind = "calculation" if kind == "calculation item" else "kpi"
            identity = f"{node_kind}:{object_text}"
        else:
            label = object_text or detail or kind
            identity = f"ref:{kind}:{object_text}"
        return add_extra(
            identity,
            kind=node_kind,
            label=label,
            context=context,
            detail=detail or kind,
            group=group,
        )

    # --- bangun graf dependensi/pemakaian dari referensi model ------------
    for owner_id, analysis in column_analyses.items():
        column = analysis.column
        for reference in getattr(analysis, "model_refs", []) or []:
            ref_kind = str(reference.kind or "")
            object_text = str(reference.object or "")
            detail = str(reference.detail or "")
            if ref_kind == "measure":
                consumer = resolve_measure(object_text)
                if consumer:
                    depend(consumer, owner_id)
            elif ref_kind in {"calculated column", "calculated table column"}:
                consumer = resolve_column(object_text)
                if consumer:
                    depend(consumer, owner_id)
            elif ref_kind == "langkah M":
                mquery = add_extra(
                    _mquery_id(column.table),
                    kind="mquery",
                    label=column.table,
                    context="M",
                )
                depend(owner_id, mquery)
            elif ref_kind in _MODEL_KINDS:
                node_id = ref_node(ref_kind, object_text, detail)
                if node_id:
                    depend(node_id, owner_id)

    for owner_id, analysis in measure_analyses.items():
        for reference in getattr(analysis, "model_refs", []) or []:
            ref_kind = str(reference.kind or "")
            object_text = str(reference.object or "")
            detail = str(reference.detail or "")
            if ref_kind == "measure":
                consumer = resolve_measure(object_text)
                if consumer:
                    depend(consumer, owner_id)
            elif ref_kind in {"calculation item", "KPI", "calculated table"}:
                node_id = ref_node(ref_kind, object_text, detail)
                if node_id:
                    depend(node_id, owner_id)
            elif ref_kind in _MODEL_KINDS:
                node_id = ref_node(ref_kind, object_text, detail)
                if node_id:
                    depend(node_id, owner_id)

    # Tabel M + langkah M untuk kolom seed yang bukan hasil kalkulasi.
    mqueries: dict[str, dict[str, str]] = {}
    for item in getattr(result, "m_queries", []) or []:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("kind") or "") != "Tabel":
            continue
        table_name = str(item.get("name") or "")
        if table_name:
            mqueries[table_name] = {
                "source": str(item.get("source") or ""),
                "expression": str(item.get("expression") or ""),
            }
    m_edges: list[tuple[str, str]] = []
    m_step_truncated = 0
    m_lineage_meta: dict[str, Any] | None = None
    if wanted == "column":
        seed_column = column_analyses[seed_id].column
        seed_table = seed_column.table
        table_query = mqueries.get(seed_table)
        if table_query is not None:
            mquery = add_extra(
                _mquery_id(seed_table),
                kind="mquery",
                label=seed_table,
                context=table_query.get("source", ""),
            )
            expression = table_query.get("expression", "")
            datasource: str | None = None
            has_steps = False
            m_lineage_meta = {
                "table": seed_table,
                "status": "unavailable",
                "reason": "Tabel tidak punya ekspresi M.",
                "warnings": [],
            }
            if expression:
                parsed = build_m_lineage(expression)
                aliases: dict[str, Any] = {}
                for key, parsed_column in (parsed.columns or {}).items():
                    for alias in [
                        key,
                        parsed_column.source_column,
                        *(parsed_column.chain or []),
                    ]:
                        if alias:
                            aliases.setdefault(str(alias).casefold(), parsed_column)

                def step_node(step: Any) -> str:
                    step_id = (
                        f"mstep:{seed_table}:{step.step or 'step'}:"
                        f"{step.column or ''}"
                    )
                    add_extra(
                        step_id,
                        kind="mstep",
                        label=str(step.step or step.column or "M step"),
                        context=str(step.function or ""),
                        detail=str(step.column or ""),
                        group="mquery",
                    )
                    return step_id

                column_lineage = aliases.get(seed_column.column.casefold())
                own_steps = (
                    list(getattr(column_lineage, "steps", []) or [])
                    if column_lineage is not None
                    else []
                )
                if len(own_steps) > MAX_M_STEPS:
                    m_step_truncated += len(own_steps) - MAX_M_STEPS
                    own_steps = own_steps[-MAX_M_STEPS:]
                own_ids = [step_node(step) for step in own_steps]
                if own_ids:
                    branches: list[list[str]] = []
                    used_names = list(
                        getattr(column_lineage, "columns_used", []) or []
                    )[:3]
                    for used_name in used_names:
                        source_column = aliases.get(str(used_name).casefold())
                        if source_column is None:
                            continue
                        source_steps = list(
                            getattr(source_column, "steps", []) or []
                        )[-4:]
                        ids = [step_node(step) for step in source_steps]
                        if ids:
                            branches.append(ids)
                    for branch in branches:
                        for previous, current in zip(branch, branch[1:]):
                            m_edges.append((previous, current))
                        m_edges.append((branch[-1], own_ids[0]))
                    for previous, current in zip(own_ids, own_ids[1:]):
                        m_edges.append((previous, current))
                    if branches:
                        for branch in branches:
                            m_edges.append((mquery, branch[0]))
                    else:
                        m_edges.append((mquery, own_ids[0]))
                    m_edges.append((own_ids[-1], seed_id))
                    has_steps = True
                if parsed.origin or parsed.source_object:
                    datasource = add_extra(
                        f"datasource:{seed_table}",
                        kind="datasource",
                        label=str(
                            parsed.source_object or parsed.origin or "Datasource"
                        ),
                        context=str(parsed.origin or ""),
                        group="mquery",
                    )
                status = column_confidence(parsed, seed_column.column)
                reason = ""
                if status == "unavailable":
                    reason = "Kolom tidak ditemukan di hasil lineage M."
                else:
                    seed_key = seed_column.column.casefold()
                    for warning in parsed.warnings:
                        if (
                            warning.column
                            and warning.column.casefold() == seed_key
                        ):
                            reason = warning.detail
                            break
                    if not reason and column_lineage is not None:
                        reason = str(column_lineage.detail or "")
                    if not reason:
                        for warning in parsed.warnings:
                            if not warning.column:
                                reason = warning.detail
                                break
                m_lineage_meta = {
                    "table": seed_table,
                    "status": status,
                    "reason": reason,
                    "warnings": warning_rows(parsed),
                }
            if not has_steps:
                m_edges.append((mquery, seed_id))
            if datasource:
                m_edges.append((datasource, mquery))
            for provider, consumer in m_edges:
                depend(consumer, provider)
            if has_steps:
                deps[seed_id].discard(mquery)
                users[mquery].discard(seed_id)

    def walk(adjacency: Mapping[str, set[str]]) -> dict[str, int]:
        found = {seed_id: 0}
        queue: deque[str] = deque([seed_id])
        while queue:
            current = queue.popleft()
            level = found[current]
            if level >= limit:
                continue
            for neighbour in sorted(adjacency.get(current, ())):
                if neighbour in found:
                    continue
                found[neighbour] = level + 1
                queue.append(neighbour)
        return found

    sides: dict[str, tuple[str, int]] = {seed_id: ("root", 0)}
    if mode in {"both", "upstream"}:
        for node_id, level in walk(deps).items():
            if node_id == seed_id:
                continue
            sides[node_id] = ("upstream", level)
    if mode in {"both", "downstream"}:
        for node_id, level in walk(users).items():
            if node_id == seed_id:
                continue
            current = sides.get(node_id)
            if current and abs(current[1]) <= level:
                continue
            if current and current[0] == "upstream" and current[1] == level:
                continue
            sides[node_id] = ("downstream", level)

    # Rantai langkah M melewati batas `depth` model agar tetap utuh.
    if m_edges and mode in {"both", "upstream"}:
        levels = {seed_id: 0}
        for _pass in range(len(m_edges) + 4):
            changed = False
            for provider, consumer in m_edges:
                if consumer not in levels:
                    continue
                need = levels[consumer] + 1
                if levels.get(provider, 0) < need:
                    levels[provider] = need
                    changed = True
            if not changed:
                break
        for node_id, level in levels.items():
            if node_id != seed_id:
                sides[node_id] = ("upstream", max(1, level))

    def node_payload(node_id: str) -> dict[str, Any] | None:
        if node_id in column_analyses:
            analysis = column_analyses[node_id]
            column = analysis.column
            return {
                "id": node_id,
                "kind": "column",
                "label": column.column,
                "context": column.table,
                "status": str(analysis.status or ""),
                "hidden": bool(getattr(column, "is_hidden", False)),
                "group": "model",
            }
        if node_id in measure_analyses:
            analysis = measure_analyses[node_id]
            measure = analysis.measure
            return {
                "id": node_id,
                "kind": "measure",
                "label": measure.measure,
                "context": measure.table,
                "status": str(analysis.status or ""),
                "hidden": bool(getattr(measure, "is_hidden", False)),
                "group": "model",
            }
        return extra_nodes.get(node_id)

    graph = _Graph(max_nodes)
    seed_payload = node_payload(seed_id)
    if seed_payload is None:
        raise ValueError("Objek lineage tidak punya metadata yang bisa digambar.")
    seed_payload = {**seed_payload, "group": "selected"}
    graph.add(seed_payload)

    ordered = sorted(
        (node_id for node_id in sides if node_id != seed_id),
        key=lambda node_id: (
            abs(sides[node_id][1]),
            0 if sides[node_id][0] == "upstream" else 1,
            node_id.casefold(),
        ),
    )
    for node_id in ordered:
        payload = node_payload(node_id)
        if payload is None:
            continue
        graph.add(payload)

    for consumer, providers in deps.items():
        for provider in providers:
            graph.link(provider, consumer, "depend")
    for provider, consumers in users.items():
        for consumer in consumers:
            graph.link(provider, consumer, "depend")

    # Rantai report untuk seed dan pemakai langsung (agar kolom yang dipakai
    # measure tetap menampilkan report yang memakai measure itu).
    if mode in {"both", "downstream"} and bool(
        getattr(result, "reports_included", True)
    ):
        report_names = {
            str(item.get("report_id") or ""): str(
                item.get("report_name") or item.get("name") or ""
            )
            for item in (getattr(result, "reports", []) or [])
            if isinstance(item, Mapping)
        }
        candidates = sorted(
            (
                (abs(sides[node_id][1]), node_id)
                for node_id in sides
                if sides[node_id][0] != "upstream"
                and (node_id in column_analyses or node_id in measure_analyses)
            ),
            key=lambda item: (item[0], item[1].casefold()),
        )
        for level, node_id in candidates:
            analysis = column_analyses.get(node_id) or measure_analyses.get(node_id)
            records = list(getattr(analysis, "report_records", []) or [])
            if not records:
                continue
            graph.add_report_chain(
                owner_id=node_id,
                records=records,
                base_depth=level,
                depth=limit,
                report_names=report_names,
            )

    # --- filter kategori dependensi (submenu View dependencies) -----------
    if scope != "all":
        allowed = set(CATEGORY_KINDS[scope])
        seed_kind = str(graph.nodes.get(seed_id, {}).get("kind") or "")
        if seed_kind:
            allowed.add(seed_kind)
        allowed_ids = {
            node_id
            for node_id, node in graph.nodes.items()
            if node_id == seed_id or node.get("kind") in allowed
        }
        graph.nodes = {
            node_id: node
            for node_id, node in graph.nodes.items()
            if node_id in allowed_ids
        }
        graph.edges = {
            key: edge
            for key, edge in graph.edges.items()
            if edge["from"] in allowed_ids and edge["to"] in allowed_ids
        }

    # --- tata letak: upstream negatif, seed 0, downstream positif ---------
    for node_id, node in graph.nodes.items():
        if node_id in sides:
            side, level = sides[node_id]
        else:
            side = str(node.get("side") or "downstream")
            level = int(node.get("level") or 1)
        column = 0 if side == "root" else (-level if side == "upstream" else level)
        node["column"] = column
        node["side"] = side
        node["level"] = level

    # Node yang dipakai beberapa pemilik (mis. report yang sama) dapat bertabrakan
    # kolom; geser hanya node rantai report agar report/halaman/visual selalu di
    # kanan pemakainya. Edge antar-objek model boleh se-kolom (digambar melengkung).
    for _pass in range(12):
        changed = False
        for edge in graph.edges.values():
            target = graph.nodes.get(edge["to"])
            source = graph.nodes.get(edge["from"])
            if source is None or target is None:
                continue
            if target.get("group") not in {"report", "page", "usage", "more"}:
                continue
            if target["column"] > source["column"]:
                continue
            target["column"] = source["column"] + 1
            changed = True
        if not changed:
            break

    by_column: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in graph.nodes.values():
        by_column[int(node["column"])].append(node)

    if not by_column:
        by_column[0].append(graph.nodes[seed_id])

    for items in by_column.values():
        items.sort(
            key=lambda node: (
                GROUP_ORDER.get(str(node.get("group") or ""), 9),
                str(node.get("kind") or ""),
                str(node.get("label") or "").casefold(),
                str(node.get("id") or ""),
            )
        )
    max_height = max(
        len(items) * NODE_H + (len(items) - 1) * ROW_GAP
        for items in by_column.values()
    )
    min_column = min(by_column)
    columns = len(by_column)
    for column, items in by_column.items():
        height = len(items) * NODE_H + (len(items) - 1) * ROW_GAP
        start = PAD + (max_height - height) / 2
        x = PAD + (column - min_column) * (NODE_W + COL_GAP)
        for index, node in enumerate(items):
            node["x"] = x
            node["y"] = start + index * (NODE_H + ROW_GAP)
            node["w"] = NODE_W
            node["h"] = NODE_H

    nodes = [
        {key: value for key, value in node.items() if not key.startswith("_")}
        for node in graph.nodes.values()
    ]
    nodes.sort(key=lambda node: (node.get("column", 0), node.get("y", 0)))

    notices: list[dict[str, Any]] = []
    if mode in {"both", "downstream"} and not bool(
        getattr(result, "reports_included", True)
    ):
        notices.append({"code": "reports_excluded"})
    if graph.truncated:
        notices.append({"code": "truncated", "count": graph.truncated})
    if m_step_truncated:
        notices.append(
            {"code": "m_steps_truncated", "count": m_step_truncated}
        )
    if len(graph.edges) == 0:
        notices.append({"code": "no_dependencies"})

    return {
        "seed": {
            "id": seed_id,
            "kind": wanted,
            "table": table,
            "name": name,
        },
        "direction": mode,
        "depth": limit,
        "category": scope,
        "m_lineage": m_lineage_meta,
        "nodes": nodes,
        "edges": list(graph.edges.values()),
        "outline": _build_outline(graph, seed_id),
        "groups": [
            {"id": "mquery", "label": "M query"},
            {"id": "model", "label": "Model dependencies"},
            {"id": "report", "label": "Report usage"},
        ],
        "width": PAD * 2 + (columns - 1) * (NODE_W + COL_GAP) + NODE_W,
        "height": PAD * 2 + max_height,
        "truncated": graph.truncated,
        "notices": notices,
    }
