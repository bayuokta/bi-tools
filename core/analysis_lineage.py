"""Lineage graph satu kolom/measure dari hasil analisa semantic model.

Modul ini tidak memakai XMLA, REST, atau SQLite: seluruh data diambil dari
``AnalysisResult`` yang sudah ada di sesi analisa (ukuran kolom, referensi
model, pemakaian report, dan ekspresi M). Hasilnya berupa node + edge + tata
letak siap gambar (artifact Semantic Model/Report, grup Model dependencies/M
query/page, lalu kartu), sehingga ``web\\app.js`` hanya merender dan tidak
menyusun lineage.

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
    lineage_confidence,
    warning_rows,
)

MAX_NODES = 250
MAX_USAGE_PER_PAGE = 8
MAX_DEPTH = 8
MAX_M_STEPS = 8
MAX_M_COLUMNS = 3
OUTLINE_MAX_ROWS = 2000

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
COL_GAP = 40
ROW_GAP = 16
PAD = 28

# Tata letak bergrup: artifact (Semantic Model / Report) -> grup -> kartu.
GROUP_PAD = 16
GROUP_HEAD = 44
GROUP_GAP = 24
ART_PAD = 18
ART_HEAD = 52
ART_GAP = 72
BAND_GAP = 28
DIRECT_EDGE_LIMIT = 160
PAGE_EDGE_LIMIT = 220

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


def _direct_reference(reference: Any) -> bool:
    """True bila referensi adalah dependency langsung (depth 1)."""
    try:
        return int(getattr(reference, "depth", 1) or 1) <= 1
    except (TypeError, ValueError):
        return True


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


def _m_source_detail(parsed: Any) -> str:
    """Keterangan sumber untuk node datasource (path/URL, parameter, native)."""
    parts = [str(item) for item in (getattr(parsed, "details", []) or []) if item]
    params = [str(item) for item in (getattr(parsed, "source_params", []) or []) if item]
    if params:
        parts.append("param:" + ", ".join(params))
    if getattr(parsed, "native_query", False):
        parts.append("native query")
    return " · ".join(parts)


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
            container_id = f"artifact:{report_node_id}"
            short_id = str(report["report_id"] or "")[:8]
            added = self.add(
                {
                    "id": report_node_id,
                    "kind": "report",
                    "label": report["name"] or "(report)",
                    "context": short_id,
                    "group": "report",
                    "role": "artifact-head",
                    "container": container_id,
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
                page_order = 0
                for record in page_records:
                    try:
                        candidate = int(record.get("page_order") or 0)
                    except (TypeError, ValueError):
                        candidate = 0
                    if candidate and (not page_order or candidate < page_order):
                        page_order = candidate
                if not self.add(
                    {
                        "id": page_node_id,
                        "kind": "page",
                        "label": page_name or "(no page)",
                        "context": (report["name"] or "") +
                        (f" ({short_id})" if short_id else ""),
                        "group": "page",
                        "role": "group-head",
                        "container": container_id,
                        "group_key": page_node_id,
                        "order": page_order,
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
                    container_id=container_id,
                )

    def _add_usage_nodes(
        self,
        page_node_id: str,
        records: list[Mapping[str, Any]],
        *,
        report_node_id: str,
        page_name: str,
        level: int,
        container_id: str,
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
                    "visual_title": str(record.get("visual_title") or ""),
                    "visual_type": str(record.get("visual_type") or ""),
                    "count": 0,
                    "hidden": True,
                },
            )
            entry["count"] += 1
            entry["hidden"] = entry["hidden"] and bool(record.get("is_hidden"))
            if kind != "visual" and not entry["detail"]:
                entry["detail"] = str(record.get("detail") or "")
            if not entry["visual_title"]:
                entry["visual_title"] = str(record.get("visual_title") or "")
            if not entry["visual_type"]:
                entry["visual_type"] = str(record.get("visual_type") or "")
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
                    "role": "card",
                    "container": container_id,
                    "group_key": page_node_id,
                    "usage_kind": entry["usage_kind"],
                    "detail": entry["detail"],
                    "visual_title": entry["visual_title"],
                    "visual_type": entry["visual_type"],
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
                    "role": "card",
                    "container": container_id,
                    "group_key": page_node_id,
                    "count": total,
                    "side": "downstream",
                    "level": level,
                }
            ):
                self.link(page_node_id, node_id, "usage")


def _node_sort_key(node: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        GROUP_ORDER.get(str(node.get("group") or ""), 9),
        str(node.get("kind") or ""),
        str(node.get("label") or "").casefold(),
        str(node.get("id") or ""),
    )


def _container_kind(container_id: str) -> str:
    if container_id.startswith("artifact:source:"):
        return "datasource"
    if container_id.startswith("artifact:report:"):
        return "report"
    return "model"


def _group_kind(group_id: str) -> str:
    if group_id.startswith("mquery:"):
        return "mquery"
    if group_id.startswith("source:"):
        return "source"
    if group_id.startswith("page:"):
        return "page"
    return "model"


def _finalize_mquery_groups(
    graph: _Graph,
    outputs: Mapping[str, str] | None,
) -> None:
    """Tentukan peran kartu tabel M: header rantai langkah atau kartu model.

    Rantai langkah M menjadikan tabel + langkah + kolom output satu grup, dan
    kartu tabel menjadi header grup. Tanpa langkah, kartu tabel pindah ke grup
    model agar tidak ada grup M kosong yang menggantung.
    """
    step_groups = {
        str(node.get("group_key") or "")
        for node in graph.nodes.values()
        if str(node.get("kind") or "") == "mstep"
    }
    for node in graph.nodes.values():
        if str(node.get("kind") or "") != "mquery":
            continue
        group_key = str(node.get("group_key") or "")
        if group_key in step_groups:
            node["role"] = "group-head"
        else:
            node["group_key"] = "model"
            node["role"] = "card"
    for node_id, group_key in (outputs or {}).items():
        if group_key not in step_groups:
            continue
        node = graph.nodes.get(node_id)
        if node is not None:
            node["group_key"] = group_key


def _group_edges(
    graph: _Graph, node_ids: set[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Edge internal grup (tanpa header grup)."""
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges.values():
        if edge["from"] in node_ids and edge["to"] in node_ids:
            outgoing[edge["from"]].append(edge["to"])
            incoming[edge["to"]].append(edge["from"])
    return outgoing, incoming


def _layout_tree(group: dict[str, Any], graph: _Graph) -> None:
    """Tidy tree/layered DAG: parent di tengah anak-anaknya."""
    nodes = list(group["nodes"])
    if not nodes:
        group["w"] = NODE_W + 2 * GROUP_PAD
        group["h"] = GROUP_HEAD + GROUP_PAD
        return
    node_ids = {str(node["id"]) for node in nodes}
    outgoing, incoming = _group_edges(graph, node_ids)
    columns = sorted({int(node.get("column") or 0) for node in nodes})
    layer_index = {column: index for index, column in enumerate(columns)}
    layers: list[list[dict[str, Any]]] = [[] for _ in columns]
    for node in nodes:
        layers[layer_index[int(node.get("column") or 0)]].append(node)
    for layer in layers:
        layer.sort(key=_node_sort_key)

    order = {str(node["id"]): index for layer in layers for index, node in enumerate(layer)}
    layer_of = {
        str(node["id"]): index
        for index, layer in enumerate(layers)
        for node in layer
    }

    def barycenter(
        node_id: str, neighbours: list[str]
    ) -> float:
        values = [order[item] for item in neighbours if item in order]
        return sum(values) / len(values) if values else float(order[node_id])

    for _pass in range(4):
        for layer in layers[1:]:
            layer.sort(
                key=lambda node: (
                    barycenter(str(node["id"]), incoming[str(node["id"])]),
                    _node_sort_key(node),
                )
            )
            for index, node in enumerate(layer):
                order[str(node["id"])] = index
        for layer in reversed(layers[:-1]):
            layer.sort(
                key=lambda node: (
                    barycenter(str(node["id"]), outgoing[str(node["id"])]),
                    _node_sort_key(node),
                )
            )
            for index, node in enumerate(layer):
                order[str(node["id"])] = index

    row_h = NODE_H + ROW_GAP
    y: dict[str, float] = {}
    for layer in layers:
        for index, node in enumerate(layer):
            y[str(node["id"])] = index * row_h

    def pack(layer: list[dict[str, Any]]) -> None:
        """Rapatkan satu kolom tanpa mengubah urutan vertikalnya."""
        ordered = sorted(
            layer,
            key=lambda node: (y[str(node["id"])], _node_sort_key(node)),
        )
        cursor: float | None = None
        for node in ordered:
            node_id = str(node["id"])
            value = y[node_id]
            if cursor is not None and value < cursor:
                value = cursor
            y[node_id] = value
            cursor = value + row_h

    # Kanan -> kiri: induk di tengah anak-anaknya pada kolom berikutnya.
    for index in range(len(layers) - 1, -1, -1):
        layer = layers[index]
        for node in layer:
            node_id = str(node["id"])
            children = [
                y[item] for item in outgoing[node_id]
                if item in y and layer_of[item] == index + 1
            ]
            if children:
                y[node_id] = sum(children) / len(children)
    for layer in layers:
        pack(layer)

    # Kiri -> kanan: daun kanan dengan beberapa induk di tengah induknya.
    for index, layer in enumerate(layers):
        for node in layer:
            node_id = str(node["id"])
            if outgoing.get(node_id):
                continue
            parents = [
                y[item] for item in incoming[node_id]
                if item in y and layer_of[item] == index - 1
            ]
            if len(parents) >= 2:
                y[node_id] = sum(parents) / len(parents)
    for layer in layers:
        pack(layer)

    minimum = min(y.values(), default=0.0)
    for node in nodes:
        node["_col"] = layer_index[int(node.get("column") or 0)]
        node["_y"] = y[str(node["id"])] - minimum
    max_y = max(float(node["_y"]) for node in nodes)
    group["columns"] = len(layers)
    group["rows"] = int(round(max_y / row_h)) + 1
    group["w"] = (
        len(layers) * NODE_W + (len(layers) - 1) * COL_GAP + 2 * GROUP_PAD
    )
    group["h"] = GROUP_HEAD + max_y + NODE_H + GROUP_PAD
    if group["kind"] == "mquery":
        # Nomor langkah mengikuti kolom rantai (kiri -> kanan).
        for node in nodes:
            if str(node.get("kind") or "") == "mstep":
                node["step"] = int(node["_col"]) + 1


def _layout_group_cards(group: dict[str, Any], graph: _Graph) -> None:
    """Hitung ukuran grup dan posisi kartu relatif terhadap grup."""
    nodes = list(group["nodes"])
    if not nodes:
        group["columns"] = 1
        group["rows"] = 0
        group["w"] = NODE_W + 2 * GROUP_PAD
        group["h"] = GROUP_HEAD + GROUP_PAD
        return
    if group["kind"] == "page":
        # Halaman memakai satu kolom kartu agar edge tidak melompati kolom.
        ordered = sorted(nodes, key=_node_sort_key)
        for index, node in enumerate(ordered):
            node["_col"], node["_y"] = 0, index * (NODE_H + ROW_GAP)
        group["columns"] = 1
        group["rows"] = len(ordered)
        group["w"] = NODE_W + 2 * GROUP_PAD
        group["h"] = (
            GROUP_HEAD
            + len(ordered) * NODE_H
            + (len(ordered) - 1) * ROW_GAP
            + GROUP_PAD
        )
        return
    _layout_tree(group, graph)



def _layout_container(container: dict[str, Any]) -> None:
    """Hitung ukuran artifact dan posisi grup relatif terhadap artifact."""
    kind = container["kind"]
    if kind == "datasource":
        for node in container["loose"]:
            node["_gx"] = ART_PAD
            node["_gy"] = ART_HEAD
        container["w"] = NODE_W + 2 * ART_PAD
        container["h"] = ART_HEAD + NODE_H + ART_PAD
        return

    groups = list(container["groups"].values())
    if kind == "report":
        def page_key(group: dict[str, Any]) -> tuple[Any, ...]:
            head = group.get("head") or {}
            try:
                order = int(head.get("order") or 0)
            except (TypeError, ValueError):
                order = 0
            return (
                order if order > 0 else 10**9,
                str(group.get("label") or "").casefold(),
                str(group.get("id") or ""),
            )

        pages = sorted(
            (group for group in groups if group["kind"] == "page"),
            key=page_key,
        )
        if not pages:
            container["w"] = NODE_W + 2 * ART_PAD
            container["h"] = ART_HEAD + ART_PAD
            return
        cell_w = max(group["w"] for group in pages)
        y = ART_HEAD
        for group in pages:
            group["_gx"] = ART_PAD
            group["_gy"] = y
            y += group["h"] + GROUP_GAP
        container["w"] = cell_w + 2 * ART_PAD
        container["h"] = y - GROUP_GAP + ART_PAD
        return

    # Artifact model: pita M query di kiri, lalu grup dependensi model.
    mquery_groups = sorted(
        (group for group in groups if group["kind"] == "mquery"),
        key=lambda group: (group["label"].casefold(), group["id"]),
    )
    model_groups = sorted(
        (group for group in groups if group["kind"] == "model"),
        key=lambda group: group["id"],
    )
    m_width = max((group["w"] for group in mquery_groups), default=0)
    m_total = (
        sum(group["h"] for group in mquery_groups)
        + GROUP_GAP * max(0, len(mquery_groups) - 1)
    )
    model_width = max((group["w"] for group in model_groups), default=0)
    model_total = (
        sum(group["h"] for group in model_groups)
        + GROUP_GAP * max(0, len(model_groups) - 1)
    )
    content_height = max(m_total, model_total)
    m_start = ART_HEAD + max(0, (content_height - m_total) // 2)
    model_start = ART_HEAD + max(0, (content_height - model_total) // 2)
    model_x = ART_PAD + (m_width + BAND_GAP if mquery_groups else 0)
    y = m_start
    for group in mquery_groups:
        group["_gx"] = ART_PAD
        group["_gy"] = y
        y += group["h"] + GROUP_GAP
    y = model_start
    for group in model_groups:
        group["_gx"] = model_x
        group["_gy"] = y
        y += group["h"] + GROUP_GAP
    if not mquery_groups and not model_groups:
        container["w"] = NODE_W + 2 * ART_PAD
        container["h"] = ART_HEAD + ART_PAD
        return
    container["w"] = model_x + model_width + ART_PAD
    container["h"] = ART_HEAD + content_height + ART_PAD


def _canvas_edges(
    graph: _Graph,
) -> tuple[list[dict[str, str]], str, list[dict[str, str]]]:
    """Edge kanvas dengan tingkat detail adaptif dan edge highlight langsung.

    ``canvas_edges`` adalah edge yang digambar (bisa dipadatkan ke halaman atau
    report). ``highlight_edges`` selalu memakai edge langsung ``owner -> kartu``
    agar klik kartu tidak melebar ke seluruh report.
    """
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges.values():
        outgoing[edge["from"]].append(edge["to"])
        incoming[edge["to"]].append(edge["from"])

    def node_of(node_id: str) -> dict[str, Any]:
        return graph.nodes.get(node_id) or {}

    def kind_of(node_id: str) -> str:
        return str(node_of(node_id).get("kind") or "")

    def is_head(node_id: str) -> bool:
        role = str(node_of(node_id).get("role") or "")
        return role in {"artifact-head", "group-head"} or kind_of(node_id) in {
            "report",
            "page",
        }

    def add(
        target: dict[tuple[str, str], dict[str, str]],
        source: str,
        consumer: str,
        kind: str,
    ) -> None:
        if not source or not consumer or source == consumer:
            return
        if source not in graph.nodes or consumer not in graph.nodes:
            return
        if is_head(source):
            return
        target.setdefault((source, consumer), {
            "from": source,
            "to": consumer,
            "kind": kind or "depend",
        })

    base: dict[tuple[str, str], dict[str, str]] = {}
    usage: dict[tuple[str, str], dict[str, str]] = {}
    for edge in graph.edges.values():
        source = edge["from"]
        target = edge["to"]
        if is_head(source) or is_head(target):
            continue
        if kind_of(target) in {"visual", "filter", "sort", "usage", "more"}:
            add(usage, source, target, kind_of(target))
        else:
            add(base, source, target, edge["kind"])

    reports = [
        node_id for node_id, node in graph.nodes.items()
        if str(node.get("kind") or "") == "report"
    ]
    for report_id in sorted(reports):
        owners = [
            item for item in incoming.get(report_id, []) if not is_head(item)
        ]
        pages = [
            item for item in outgoing.get(report_id, [])
            if kind_of(item) == "page"
        ]
        report_usage = [
            item for item in outgoing.get(report_id, [])
            if str(node_of(item).get("role") or "") == "card"
        ]
        anchor = pages or report_usage
        for owner in owners:
            if not anchor:
                add(usage, owner, report_id, "usage")
                continue
            for child in anchor:
                usages = [
                    item for item in outgoing.get(child, [])
                    if str(node_of(item).get("role") or "") == "card"
                ]
                if usages:
                    for item in usages:
                        add(usage, owner, item, kind_of(item))
                else:
                    add(usage, owner, child, "usage")

    level = "usage"
    chosen = usage
    if len(usage) > DIRECT_EDGE_LIMIT:
        page_edges: dict[tuple[str, str], dict[str, str]] = {}
        for source, consumer in usage:
            page_id = str(node_of(consumer).get("group_key") or "")
            if kind_of(page_id) == "page":
                add(page_edges, source, page_id, "usage")
            else:
                add(page_edges, source, consumer, "usage")
        if len(page_edges) <= PAGE_EDGE_LIMIT:
            level = "page"
            chosen = page_edges
        else:
            report_head = {
                str(node.get("container") or ""): node_id
                for node_id, node in graph.nodes.items()
                if str(node.get("kind") or "") == "report"
            }
            report_edges: dict[tuple[str, str], dict[str, str]] = {}
            for source, consumer in usage:
                container = str(node_of(consumer).get("container") or "")
                target = report_head.get(container)
                if target:
                    add(report_edges, source, target, "usage")
                else:
                    add(report_edges, source, consumer, "usage")
            level = "report"
            chosen = report_edges

    combined = dict(base)
    combined.update(chosen)
    rows = sorted(
        combined.values(),
        key=lambda edge: (
            edge["from"], edge["to"], edge["kind"]
        ),
    )
    highlight = dict(base)
    highlight.update(usage)
    highlight_rows = sorted(
        highlight.values(),
        key=lambda edge: (
            edge["from"], edge["to"], edge["kind"]
        ),
    )
    return rows, level, highlight_rows


def _layout_graph(
    graph: _Graph,
    sides: Mapping[str, tuple[str, int]],
    seed_id: str,
    *,
    model_label: str = "",
    model_context: str = "",
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
    int,
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    str,
]:
    """Susun tata letak bergrup: artifact -> grup -> kartu."""
    for node_id, node in graph.nodes.items():
        side, level = sides.get(node_id) or (
            str(node.get("side") or "downstream"),
            int(node.get("level") or 1),
        )
        level = int(level or 0)
        node["side"] = side
        node["level"] = level
        node["column"] = (
            0 if side == "root" else (-level if side == "upstream" else level)
        )
        node.setdefault("role", "card")
        node.setdefault("container", "artifact:model")
        node.setdefault("group_key", "model")

    containers: dict[str, dict[str, Any]] = {}
    groups: dict[str, dict[str, Any]] = {}

    def ensure_container(container_id: str) -> dict[str, Any]:
        container = containers.get(container_id)
        if container is None:
            container = {
                "id": container_id,
                "kind": _container_kind(container_id),
                "label": "",
                "label_key": "",
                "sub": "",
                "sub_key": "",
                "groups": {},
                "loose": [],
                "head": None,
            }
            containers[container_id] = container
        return container

    for node in graph.nodes.values():
        container_id = str(node.get("container") or "artifact:model")
        role = str(node.get("role") or "card")
        node["container_id"] = container_id
        container = ensure_container(container_id)
        if role == "artifact-head":
            container["head"] = node
            node["group_id"] = ""
            continue
        if container["kind"] == "datasource":
            container["loose"].append(node)
            node["group_id"] = ""
            continue
        group_id = str(node.get("group_key") or "model")
        group = groups.get(group_id)
        if group is None:
            group = {
                "id": group_id,
                "container": container_id,
                "kind": _group_kind(group_id),
                "label": "",
                "label_key": "",
                "sub": "",
                "sub_key": "",
                "nodes": [],
                "head": None,
            }
            groups[group_id] = group
        container["groups"][group_id] = group
        node["group_id"] = group_id
        if role == "group-head":
            group["head"] = node
        else:
            group["nodes"].append(node)

    for container in containers.values():
        if container["kind"] == "model":
            container["label"] = model_label or "Semantic Model"
            container["sub_key"] = "Semantic Model"
            container["sub"] = model_context
        elif container["kind"] == "report":
            head = container["head"]
            if head is not None:
                container["label"] = str(head.get("label") or "Report")
                container["sub_key"] = "Report"
                container["sub"] = str(head.get("context") or "")
        else:
            head = container["head"] or (
                container["loose"][0] if container["loose"] else None
            )
            if head is not None:
                container["label"] = str(head.get("label") or "Datasource")
                container["sub_key"] = "Datasource"
                container["sub"] = str(head.get("context") or "")
        for group in container["groups"].values():
            if group["kind"] == "model":
                group["label_key"] = "Model dependencies"
                group["sub_key"] = "DAX and model objects"
            elif group["kind"] == "mquery":
                source = next(
                    (
                        node for node in group["nodes"] + (
                            [group["head"]] if group["head"] else []
                        )
                        if str(node.get("kind") or "") == "mquery"
                    ),
                    None,
                )
                if source is not None:
                    group["label"] = str(source.get("label") or "")
                group["sub_key"] = "M query"
                group["sub"] = ""
            elif group["kind"] == "page":
                head = group["head"]
                group["label"] = (
                    str(head.get("label") or "(no page)")
                    if head is not None
                    else "(no page)"
                )
                group["sub_key"] = "Page"
                group["sub"] = ""

    for group in groups.values():
        _layout_group_cards(group, graph)
    for container in containers.values():
        _layout_container(container)

    sources = sorted(
        (c for c in containers.values() if c["kind"] == "datasource"),
        key=lambda c: (c["label"].casefold(), c["id"]),
    )
    model_containers = sorted(
        (c for c in containers.values() if c["kind"] == "model"),
        key=lambda c: c["id"],
    )
    reports = sorted(
        (c for c in containers.values() if c["kind"] == "report"),
        key=lambda c: (c["label"].casefold(), c["id"]),
    )
    label_counts: dict[str, int] = {}
    for container in reports:
        label = str(container.get("label") or "")
        label_counts[label] = label_counts.get(label, 0) + 1
    for container in reports:
        label = str(container.get("label") or "")
        if label_counts.get(label, 0) > 1:
            head = container.get("head") or {}
            short = str(head.get("context") or "").strip()
            if not short:
                short = str(container.get("id") or "").rsplit(":", 1)[-1][:8]
            container["label"] = f"{label} ({short})"
    reports.sort(key=lambda c: (c["label"].casefold(), c["id"]))

    source_width = NODE_W + 2 * ART_PAD if sources else 0
    model_x = PAD + (source_width + ART_GAP if sources else 0)
    y = PAD
    for container in model_containers:
        container["x"] = model_x
        container["y"] = y
        y += container["h"] + ART_GAP
    model_width = max((c["w"] for c in model_containers), default=0)

    # Datasource disejajarkan dengan kartu pertama grup M (atau baris seed).
    anchor_y = PAD + ART_HEAD + GROUP_HEAD
    if model_containers:
        model = model_containers[0]
        mquery_groups = [
            group for group in model["groups"].values()
            if group["kind"] == "mquery"
        ]
        if mquery_groups:
            first = min(mquery_groups, key=lambda group: group["_gy"])
            anchor_y = model["y"] + int(first["_gy"]) + GROUP_HEAD
        else:
            anchor_y = model["y"] + ART_HEAD + GROUP_HEAD
    y = max(PAD, anchor_y - ART_HEAD)
    for container in sources:
        container["x"] = PAD
        container["y"] = y
        y += container["h"] + ART_GAP

    cursor = model_x + model_width + ART_GAP
    for container in reports:
        container["x"] = cursor
        container["y"] = PAD
        cursor += container["w"] + ART_GAP

    max_right = max(
        (c["x"] + c["w"] for c in containers.values()), default=PAD + NODE_W
    )
    max_bottom = max(
        (c["y"] + c["h"] for c in containers.values()), default=PAD + NODE_H
    )
    width = max(PAD + NODE_W, max_right + PAD)
    height = max(PAD + NODE_H, max_bottom + PAD)

    for container in containers.values():
        container["head_x"] = container["x"] + ART_PAD
        container["head_y"] = container["y"] + 12
        container["head_w"] = container["w"] - 2 * ART_PAD
        container["head_h"] = ART_HEAD - 16
        if container["kind"] == "datasource":
            for node in container["loose"]:
                node["x"] = container["x"] + int(node.pop("_gx"))
                node["y"] = container["y"] + int(node.pop("_gy"))
                node["w"] = NODE_W
                node["h"] = NODE_H
            continue
        for group in container["groups"].values():
            group["x"] = container["x"] + int(group.pop("_gx"))
            group["y"] = container["y"] + int(group.pop("_gy"))
            group["head_x"] = group["x"] + GROUP_PAD
            group["head_y"] = group["y"] + 8
            group["head_w"] = group["w"] - 2 * GROUP_PAD
            group["head_h"] = GROUP_HEAD - 14
            head = group["head"]
            if head is not None:
                head["x"] = group["head_x"]
                head["y"] = group["head_y"]
                head["w"] = group["head_w"]
                head["h"] = group["head_h"]
            for node in group["nodes"]:
                node["x"] = (
                    group["x"]
                    + GROUP_PAD
                    + int(node.pop("_col")) * (NODE_W + COL_GAP)
                )
                node["y"] = (
                    group["y"]
                    + GROUP_HEAD
                    + int(node.pop("_y"))
                )
                node["w"] = NODE_W
                node["h"] = NODE_H
        head = container["head"]
        if head is not None:
            head["x"] = container["head_x"]
            head["y"] = container["head_y"]
            head["w"] = container["head_w"]
            head["h"] = container["head_h"]

    node_rows = [
        {key: value for key, value in node.items() if not key.startswith("_")}
        for node in graph.nodes.values()
    ]
    node_rows.sort(
        key=lambda node: (
            str(node.get("container_id") or ""),
            str(node.get("group_id") or ""),
            0 if node.get("role") == "card" else 1,
            int(node.get("x") or 0),
            int(node.get("y") or 0),
            str(node.get("id") or ""),
        )
    )

    artifact_rows = []
    for container in sorted(
        containers.values(), key=lambda c: (c["x"], c["y"], c["id"])
    ):
        members = [
            str(node.get("id") or "")
            for node in container["loose"]
        ]
        for group in container["groups"].values():
            members.extend(
                str(node.get("id") or "") for node in group["nodes"]
            )
            if group["head"] is not None:
                members.append(str(group["head"].get("id") or ""))
        if container["head"] is not None:
            members.append(str(container["head"].get("id") or ""))
        artifact_rows.append(
            {
                "id": container["id"],
                "kind": container["kind"],
                "label": container["label"],
                "label_key": container["label_key"],
                "sub": container["sub"],
                "sub_key": container["sub_key"],
                "x": int(container["x"]),
                "y": int(container["y"]),
                "w": int(container["w"]),
                "h": int(container["h"]),
                "head_x": int(container["head_x"]),
                "head_y": int(container["head_y"]),
                "head_w": int(container["head_w"]),
                "head_h": int(container["head_h"]),
                "head_id": str(
                    (container["head"] or {}).get("id") or ""
                ),
                "members": sorted(set(members)),
            }
        )

    group_rows = []
    for group in sorted(
        groups.values(),
        key=lambda g: (str(g["container"]), int(g["x"]), int(g["y"])),
    ):
        group_rows.append(
            {
                "id": group["id"],
                "container": group["container"],
                "kind": group["kind"],
                "label": group["label"],
                "label_key": group["label_key"],
                "sub": group["sub"],
                "sub_key": group["sub_key"],
                "x": int(group["x"]),
                "y": int(group["y"]),
                "w": int(group["w"]),
                "h": int(group["h"]),
                "head_x": int(group["head_x"]),
                "head_y": int(group["head_y"]),
                "head_w": int(group["head_w"]),
                "head_h": int(group["head_h"]),
                "head_id": str((group["head"] or {}).get("id") or ""),
                "members": sorted(
                    str(node.get("id") or "") for node in group["nodes"]
                ),
            }
        )

    canvas_edges, edge_level, highlight_edges = _canvas_edges(graph)

    # Garis pohon induk-anak untuk header grup yang tidak muncul di canvas_edges.
    tree_rows: list[dict[str, str]] = []
    tree_seen: set[tuple[str, str]] = set()

    def add_tree(parent: str, child: str) -> None:
        if not parent or not child or parent == child:
            return
        if (parent, child) in tree_seen:
            return
        if parent not in graph.nodes or child not in graph.nodes:
            return
        tree_seen.add((parent, child))
        tree_rows.append({"from": parent, "to": child, "kind": "tree"})

    for container in containers.values():
        head = container["head"]
        if container["kind"] != "report" or head is None:
            continue
        for group in container["groups"].values():
            if group["kind"] == "page" and group["head"] is not None:
                add_tree(str(head["id"]), str(group["head"]["id"]))
    for group in groups.values():
        head = group["head"]
        if head is None:
            continue
        node_ids = {str(node["id"]) for node in group["nodes"]}
        _outgoing, incoming = _group_edges(graph, node_ids)
        roots = sorted(
            str(node["id"]) for node in group["nodes"]
            if not incoming.get(str(node["id"]))
        )
        for child in roots:
            add_tree(str(head["id"]), child)
    tree_rows.sort(key=lambda edge: (edge["from"], edge["to"]))

    return (
        node_rows,
        artifact_rows,
        group_rows,
        int(width),
        int(height),
        canvas_edges,
        highlight_edges,
        tree_rows,
        edge_level,
    )



def _build_outline(
    graph: _Graph, seed_id: str, *, expand_repeats: bool = False
) -> dict[str, Any]:
    """Struktur pohon upstream/downstream untuk tampilan outline."""
    incoming: dict[str, set[str]] = defaultdict(set)
    outgoing: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges.values():
        outgoing[edge["from"]].add(edge["to"])
        incoming[edge["to"]].add(edge["from"])
    budget = [OUTLINE_MAX_ROWS]

    def sort_key(node_id: str) -> tuple[Any, ...]:
        node = graph.nodes[node_id]
        return (
            GROUP_ORDER.get(str(node.get("group") or ""), 9),
            str(node.get("kind") or ""),
            str(node.get("label") or "").casefold(),
            node_id,
        )

    def upstream_ids(node_id: str) -> list[str]:
        """Parent upstream tanpa node mstep (langsung ke M query/datasource)."""
        ids: list[str] = []
        kept: set[str] = set()
        visited_steps: set[str] = set()

        def visit(current: str) -> None:
            for child_id in sorted(incoming.get(current, ()), key=sort_key):
                node = graph.nodes.get(child_id)
                if node is None:
                    continue
                if str(node.get("kind") or "") == "mstep":
                    if child_id in visited_steps:
                        continue
                    visited_steps.add(child_id)
                    visit(child_id)
                    continue
                if child_id not in kept:
                    kept.add(child_id)
                    ids.append(child_id)

        visit(node_id)
        return ids

    def build(
        node_id: str,
        adjacency: Mapping[str, set[str]],
        level: int,
        seen: set[str],
        collapse_msteps: bool = False,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if collapse_msteps:
            children = upstream_ids(node_id)
        else:
            children = sorted(adjacency.get(node_id, ()), key=sort_key)
        for child_id in children:
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
                "detail": str(node.get("detail") or ""),
                "usage_kind": str(node.get("usage_kind") or ""),
                "visual_title": str(node.get("visual_title") or ""),
                "visual_type": str(node.get("visual_type") or ""),
                "hidden": bool(node.get("hidden")),
                "children": [],
            }
            repeated = child_id in seen
            if repeated:
                item["repeat"] = True
            if level <= 10 and budget[0] > 0 and (expand_repeats or not repeated):
                budget[0] -= 1
                if expand_repeats:
                    branch = set(seen)
                    branch.add(child_id)
                else:
                    seen.add(child_id)
                    branch = seen
                item["children"] = build(
                    child_id,
                    adjacency,
                    level + 1,
                    branch,
                    collapse_msteps,
                )
            items.append(item)
        return items

    return {
        "upstream": build(
            seed_id, incoming, 1, {seed_id}, collapse_msteps=True
        ),
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
    outline_mode: str = "compact",
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
    outline_style = str(outline_mode or "compact").strip().lower()
    if outline_style not in {"compact", "full"}:
        raise ValueError("Mode outline harus 'compact' atau 'full'.")

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
        group_key: str = "",
        container: str = "",
    ) -> str:
        if not group_key:
            group_key = f"mquery:{label}" if group == "mquery" else "model"
        if not container:
            container = "artifact:model"
        extra_nodes.setdefault(
            node_id,
            {
                "id": node_id,
                "kind": kind,
                "label": label,
                "context": context,
                "detail": detail,
                "group": group,
                "role": "card",
                "group_key": group_key,
                "container": container,
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
            if not _direct_reference(reference):
                continue
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
                    group="mquery",
                    group_key=_mquery_id(column.table),
                )
                depend(owner_id, mquery)
            elif ref_kind in _MODEL_KINDS:
                node_id = ref_node(ref_kind, object_text, detail)
                if node_id:
                    depend(node_id, owner_id)

    for owner_id, analysis in measure_analyses.items():
        for reference in getattr(analysis, "model_refs", []) or []:
            if not _direct_reference(reference):
                continue
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

    m_edges: list[tuple[str, str]] = []
    m_step_truncated = 0
    m_columns_truncated = 0
    m_lineage_meta: dict[str, Any] | None = None
    m_outputs: dict[str, str] = {}

    def add_m_chain(analysis: Any, *, is_seed: bool) -> str | None:
        """Bangun rantai M satu kolom; kembalikan grup M bila punya langkah."""
        nonlocal m_lineage_meta, m_step_truncated
        column = analysis.column
        table_name = column.table
        table_query = mqueries.get(table_name)
        if table_query is None:
            return None
        group_key = _mquery_id(table_name)
        mquery = add_extra(
            group_key,
            kind="mquery",
            label=table_name,
            context=table_query.get("source", ""),
            group="mquery",
            group_key=group_key,
        )
        expression = table_query.get("expression", "")
        datasource: str | None = None
        has_steps = False
        meta = {
            "table": table_name,
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
                    f"mstep:{table_name}:{step.step or 'step'}:"
                    f"{step.column or ''}"
                )
                add_extra(
                    step_id,
                    kind="mstep",
                    label=str(step.step or step.column or "M step"),
                    context=str(step.function or ""),
                    detail=str(step.column or ""),
                    group="mquery",
                    group_key=group_key,
                )
                return step_id

            column_lineage = aliases.get(column.column.casefold())
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
                m_outputs[_column_id(table_name, column.column)] = group_key
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
                m_edges.append(
                    (own_ids[-1], _column_id(table_name, column.column))
                )
                has_steps = True
            if parsed.origin or parsed.source_object:
                datasource = add_extra(
                    f"datasource:{table_name}",
                    kind="datasource",
                    label=str(
                        parsed.source_object or parsed.origin or "Datasource"
                    ),
                    context=str(parsed.origin or ""),
                    detail=_m_source_detail(parsed),
                    group="mquery",
                    group_key=f"source:{table_name}",
                    container=f"artifact:source:{table_name}",
                )
            status = column_confidence(parsed, column.column)
            reason = ""
            if status == "unavailable":
                reason = "Kolom tidak ditemukan di hasil lineage M."
            else:
                seed_key = column.column.casefold()
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
            meta = {
                "table": table_name,
                "status": status,
                "reason": reason,
                "warnings": warning_rows(parsed),
            }
        if not has_steps:
            m_edges.append(
                (mquery, _column_id(table_name, column.column))
            )
        if datasource:
            m_edges.append((datasource, mquery))
        if is_seed:
            m_lineage_meta = meta
        return group_key if has_steps else None

    if wanted == "column":
        add_m_chain(column_analyses[seed_id], is_seed=True)
    elif wanted == "measure":
        candidates = [
            (node_id, column_analyses[node_id])
            for node_id in walk(deps)
            if node_id in column_analyses
            and node_id != seed_id
            and column_analyses[node_id].column.table in mqueries
        ]
        candidates.sort(
            key=lambda pair: (
                pair[1].column.table.casefold(),
                pair[1].column.column.casefold(),
            )
        )
        if len(candidates) > MAX_M_COLUMNS:
            m_columns_truncated = len(candidates) - MAX_M_COLUMNS
            candidates = candidates[:MAX_M_COLUMNS]
        for _node_id, analysis in candidates:
            add_m_chain(analysis, is_seed=False)

    for provider, consumer in m_edges:
        depend(consumer, provider)
    for node_id, group_key in m_outputs.items():
        # Rantai M lengkap menggantikan edge tabel -> kolom yang kasar.
        deps[node_id].discard(group_key)
        users[group_key].discard(node_id)

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
        for _pass in range(len(m_edges) + 4):
            changed = False
            for provider, consumer in m_edges:
                current = sides.get(consumer)
                if consumer != seed_id and (
                    current is None or current[0] != "upstream"
                ):
                    continue
                need = 1 if consumer == seed_id else current[1] + 1
                old = sides.get(provider)
                if old is None or old[0] != "upstream" or old[1] < need:
                    sides[provider] = ("upstream", need)
                    changed = True
            if not changed:
                break

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
                "role": "card",
                "group_key": "model",
                "container": "artifact:model",
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
                "role": "card",
                "group_key": "model",
                "container": "artifact:model",
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

    _finalize_mquery_groups(graph, m_outputs)

    (
        nodes,
        artifacts,
        group_rows,
        width,
        height,
        canvas_edges,
        highlight_edges,
        tree_edges,
        edge_level,
    ) = _layout_graph(
        graph,
        sides,
        seed_id,
        model_label=str(getattr(result, "dataset_name", "") or ""),
        model_context=str(getattr(result, "workspace_name", "") or ""),
    )

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
    if m_columns_truncated:
        notices.append(
            {"code": "m_columns_truncated", "count": m_columns_truncated}
        )
    if edge_level != "usage":
        notices.append(
            {
                "code": "edges_collapsed",
                "level": edge_level,
                "count": len(canvas_edges),
            }
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
        "canvas_edges": canvas_edges,
        "highlight_edges": highlight_edges,
        "tree_edges": tree_edges,
        "outline": _build_outline(
            graph, seed_id, expand_repeats=outline_style == "full"
        ),
        "artifacts": artifacts,
        "groups": group_rows,
        "width": width,
        "height": height,
        "truncated": graph.truncated,
        "notices": notices,
    }


def _model_node_payload(analysis: Any) -> dict[str, Any] | None:
    """Payload node model untuk satu ``ColumnAnalysis``/``MeasureAnalysis``."""
    column = getattr(analysis, "column", None)
    if column is not None:
        return {
            "id": _column_id(column.table, column.column),
            "kind": "column",
            "label": column.column,
            "context": column.table,
            "status": str(getattr(analysis, "status", "") or ""),
            "hidden": bool(getattr(column, "is_hidden", False)),
            "group": "model",
            "role": "card",
            "group_key": "model",
            "container": "artifact:model",
        }
    measure = getattr(analysis, "measure", None)
    if measure is not None:
        return {
            "id": _measure_id(measure.table, measure.measure),
            "kind": "measure",
            "label": measure.measure,
            "context": measure.table,
            "status": str(getattr(analysis, "status", "") or ""),
            "hidden": bool(getattr(measure, "is_hidden", False)),
            "group": "model",
            "role": "card",
            "group_key": "model",
            "container": "artifact:model",
        }
    return None


def build_table_lineage(
    result: Any,
    *,
    table: str,
    direction: str = "both",
    depth: int = 4,
    max_nodes: int = MAX_NODES,
    outline_mode: str = "compact",
) -> dict[str, Any]:
    """Graph lineage level tabel: M query -> tabel -> kolom/measure -> report."""
    name = str(table or "").strip()
    if not name:
        raise ValueError("Nama tabel harus diisi.")
    mode = str(direction or "both").strip().lower()
    if mode not in DIRECTIONS:
        raise ValueError("Arah lineage harus 'both', 'upstream', atau 'downstream'.")
    try:
        limit = max(1, min(MAX_DEPTH, int(depth or 4)))
    except (TypeError, ValueError) as exc:
        raise ValueError("Kedalaman lineage harus angka 1-8.") from exc
    outline_style = str(outline_mode or "compact").strip().lower()
    if outline_style not in {"compact", "full"}:
        raise ValueError("Mode outline harus 'compact' atau 'full'.")

    wanted = name.casefold()
    column_analyses = [
        item
        for item in (getattr(result, "columns", []) or [])
        if getattr(getattr(item, "column", None), "table", "").casefold() == wanted
    ]
    measure_analyses = {
        _measure_id(item.measure.table, item.measure.measure): item
        for item in (getattr(result, "measures", []) or [])
        if getattr(item, "measure", None) is not None
    }
    table_measures = [
        item
        for item in measure_analyses.values()
        if item.measure.table.casefold() == wanted
    ]
    mqueries: dict[str, dict[str, str]] = {}
    for item in getattr(result, "m_queries", []) or []:
        if not isinstance(item, Mapping) or str(item.get("kind") or "") != "Tabel":
            continue
        table_name = str(item.get("name") or "")
        if table_name:
            mqueries[table_name] = {
                "source": str(item.get("source") or ""),
                "expression": str(item.get("expression") or ""),
            }
    if not column_analyses and not table_measures and name not in mqueries:
        raise ValueError(
            "Tabel tidak ditemukan di hasil analisa. Jalankan analisa ulang."
        )

    graph = _Graph(max_nodes)
    seed_id = f"table:{name}"
    graph.add(
        {
            "id": seed_id,
            "kind": "table",
            "label": name,
            "context": "",
            "group": "selected",
            "role": "card",
            "group_key": "model",
            "container": "artifact:model",
        }
    )
    sides: dict[str, tuple[str, int]] = {seed_id: ("root", 0)}
    m_lineage_meta: dict[str, Any] | None = None

    if mode in {"both", "upstream"} and name in mqueries:
        query = mqueries[name]
        mquery = _mquery_id(name)
        if graph.add(
            {
                "id": mquery,
                "kind": "mquery",
                "label": name,
                "context": query.get("source", ""),
                "group": "mquery",
                "role": "card",
                "group_key": mquery,
                "container": "artifact:model",
            }
        ):
            graph.link(mquery, seed_id, "depend")
            sides[mquery] = ("upstream", 1)
        expression = query.get("expression", "")
        m_lineage_meta = {
            "table": name,
            "status": "unavailable",
            "reason": "Tabel tidak punya ekspresi M.",
            "warnings": [],
        }
        if expression:
            parsed = build_m_lineage(expression)
            reason = ""
            for warning in parsed.warnings:
                reason = warning.detail
                break
            m_lineage_meta = {
                "table": name,
                "status": lineage_confidence(parsed),
                "reason": reason,
                "warnings": warning_rows(parsed),
            }
            if parsed.origin or parsed.source_object:
                datasource = f"datasource:{name}"
                if graph.add(
                    {
                        "id": datasource,
                        "kind": "datasource",
                        "label": str(
                            parsed.source_object or parsed.origin or "Datasource"
                        ),
                        "context": str(parsed.origin or ""),
                        "detail": _m_source_detail(parsed),
                        "group": "mquery",
                        "role": "card",
                        "group_key": f"source:{name}",
                        "container": f"artifact:source:{name}",
                    }
                ):
                    graph.link(datasource, mquery, "depend")
                    sides[datasource] = ("upstream", 2)

    if mode in {"both", "downstream"}:
        for analysis in sorted(
            column_analyses, key=lambda item: item.column.column.casefold()
        ):
            payload = _model_node_payload(analysis)
            if payload is None or not graph.add(payload):
                continue
            graph.link(seed_id, payload["id"], "depend")
            sides[payload["id"]] = ("downstream", 1)

        for analysis in column_analyses:
            column_id = _column_id(analysis.column.table, analysis.column.column)
            if column_id not in graph.nodes:
                continue
            for reference in getattr(analysis, "model_refs", []) or []:
                if not _direct_reference(reference):
                    continue
                if str(reference.kind or "") != "measure":
                    continue
                ref_table, ref_name = _parse_object(str(reference.object or ""))
                measure_id = _measure_id(ref_table, ref_name)
                target = measure_analyses.get(measure_id)
                if target is None:
                    continue
                payload = _model_node_payload(target)
                if payload is None:
                    continue
                if graph.add(payload):
                    sides[measure_id] = ("downstream", 2)
                graph.link(column_id, measure_id, "depend")

        for analysis in table_measures:
            measure_id = _measure_id(analysis.measure.table, analysis.measure.measure)
            payload = _model_node_payload(analysis)
            if payload is None:
                continue
            if graph.add(payload):
                sides[measure_id] = ("downstream", 2)
            graph.link(seed_id, measure_id, "depend")

        if bool(getattr(result, "reports_included", True)):
            report_names = {
                str(item.get("report_id") or ""): str(
                    item.get("report_name") or item.get("name") or ""
                )
                for item in (getattr(result, "reports", []) or [])
                if isinstance(item, Mapping)
            }
            for analysis in column_analyses:
                column_id = _column_id(analysis.column.table, analysis.column.column)
                if column_id not in graph.nodes:
                    continue
                records = list(getattr(analysis, "report_records", []) or [])
                if records:
                    graph.add_report_chain(
                        owner_id=column_id,
                        records=records,
                        base_depth=1,
                        depth=limit,
                        report_names=report_names,
                    )
            for measure_id, analysis in measure_analyses.items():
                if measure_id not in graph.nodes:
                    continue
                records = list(getattr(analysis, "report_records", []) or [])
                if records:
                    graph.add_report_chain(
                        owner_id=measure_id,
                        records=records,
                        base_depth=int(
                            sides.get(measure_id, ("downstream", 2))[1]
                        ),
                        depth=limit,
                        report_names=report_names,
                    )

    _finalize_mquery_groups(graph, None)

    (
        nodes,
        artifacts,
        group_rows,
        width,
        height,
        canvas_edges,
        highlight_edges,
        tree_edges,
        edge_level,
    ) = _layout_graph(
        graph,
        sides,
        seed_id,
        model_label=str(getattr(result, "dataset_name", "") or ""),
        model_context=str(getattr(result, "workspace_name", "") or ""),
    )

    notices: list[dict[str, Any]] = []
    if mode in {"both", "downstream"} and not bool(
        getattr(result, "reports_included", True)
    ):
        notices.append({"code": "reports_excluded"})
    if graph.truncated:
        notices.append({"code": "truncated", "count": graph.truncated})
    if edge_level != "usage":
        notices.append(
            {
                "code": "edges_collapsed",
                "level": edge_level,
                "count": len(canvas_edges),
            }
        )
    if len(graph.edges) == 0:
        notices.append({"code": "no_dependencies"})

    return {
        "seed": {
            "id": seed_id,
            "kind": "table",
            "table": name,
            "name": name,
        },
        "direction": mode,
        "depth": limit,
        "category": "all",
        "m_lineage": m_lineage_meta,
        "nodes": nodes,
        "edges": list(graph.edges.values()),
        "canvas_edges": canvas_edges,
        "highlight_edges": highlight_edges,
        "tree_edges": tree_edges,
        "outline": _build_outline(
            graph, seed_id, expand_repeats=outline_style == "full"
        ),
        "artifacts": artifacts,
        "groups": group_rows,
        "width": width,
        "height": height,
        "truncated": graph.truncated,
        "notices": notices,
    }
