"""Tata letak kanvas lineage: root di tengah, upstream ke kiri, downstream ke kanan.

Modul ini tidak memakai Qt; hasilnya berupa kolom dan baris dalam satuan grid yang
kemudian dipetakan ke koordinat piksel oleh ``app\\lineage_graph.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MAX_NODES = 300

SIDE_ROOT = "root"
SIDE_UPSTREAM = "upstream"
SIDE_DOWNSTREAM = "downstream"


@dataclass(frozen=True)
class LayoutNode:
    """Satu kartu pada kanvas. ``column`` negatif berarti upstream."""

    node_id: str
    node_type: str
    name: str
    workspace_name: str | None
    depth: int
    column: int
    row: float
    side: str
    payload: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class LayoutEdge:
    """Relasi antar kartu; arah data selalu ``source`` -> ``target``."""

    source_id: str
    target_id: str
    edge_type: str


@dataclass(frozen=True)
class LayoutGraph:
    root: LayoutNode
    nodes: tuple[LayoutNode, ...]
    edges: tuple[LayoutEdge, ...]
    truncated: int = 0

    def node(self, node_id: str) -> LayoutNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    @property
    def columns(self) -> int:
        if not self.nodes:
            return 1
        return 1 + max(abs(node.column) for node in self.nodes)

    @property
    def max_rows(self) -> float:
        return max((abs(node.row) for node in self.nodes), default=0.0)


def build_graph(
    downstream: dict[str, Any] | None = None,
    upstream: dict[str, Any] | None = None,
    *,
    max_nodes: int = MAX_NODES,
) -> LayoutGraph:
    """Gabungkan hasil ``lineage()`` dua arah menjadi satu graph siap gambar.

    Node yang muncul di kedua arah dipakai sekali pada kedalaman terkecil
    (downstream diprioritaskan bila seri). Jumlah node dibatasi ``max_nodes``
    dengan mempertahankan node yang paling dekat root.
    """
    results: list[tuple[str, dict[str, Any]]] = []
    for side, data in (
        (SIDE_DOWNSTREAM, downstream),
        (SIDE_UPSTREAM, upstream),
    ):
        if not data:
            continue
        if not (data.get("root") or {}).get("node_id"):
            continue
        results.append((side, data))
    if not results:
        raise ValueError("downstream or upstream lineage results are required")

    root_payload = dict(results[0][1]["root"])
    root_id = str(root_payload["node_id"])
    for _side, data in results[1:]:
        if str(data["root"].get("node_id") or "") != root_id:
            raise ValueError("the two lineage results have different roots")

    # Kumpulkan kandidat, urutkan yang paling dekat root agar batas node
    # memotong cabang terdalam terlebih dahulu.
    candidates: list[tuple[int, int, int, str, dict[str, Any]]] = []
    order = 0
    for side, data in results:
        priority = 0 if side == SIDE_DOWNSTREAM else 1
        for node in data.get("nodes") or []:
            node_id = str(node.get("node_id") or "")
            if not node_id or node_id == root_id:
                continue
            try:
                distance = int(node.get("depth") or 0)
            except (TypeError, ValueError):
                continue
            candidates.append(
                (
                    max(distance, 0),
                    priority,
                    order,
                    side,
                    {**node, "node_id": node_id},
                )
            )
            order += 1

    limit = max(int(max_nodes), 1)
    kept: list[tuple[int, int, int, str, dict[str, Any]]] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: item[:3]):
        node_id = str(candidate[4]["node_id"])
        if node_id in seen:
            continue
        if len(kept) + 1 >= limit:
            break
        seen.add(node_id)
        kept.append(candidate)

    unique_ids = {str(candidate[4]["node_id"]) for candidate in candidates}
    truncated = max(len(unique_ids) - len(kept), 0)

    payloads: dict[str, dict[str, Any]] = {root_id: root_payload}
    columns: dict[str, int] = {root_id: 0}
    sides: dict[str, str] = {root_id: SIDE_ROOT}
    for distance, _priority, _order, side, node in kept:
        node_id = str(node["node_id"])
        payloads[node_id] = node
        columns[node_id] = distance if side == SIDE_DOWNSTREAM else -distance
        sides[node_id] = side

    edges: list[LayoutEdge] = []
    edge_seen: set[tuple[str, str, str]] = set()
    for _distance, _priority, _order, side, node in kept:
        parent = node.get("parent")
        if not parent or str(parent) not in payloads:
            continue
        if side == SIDE_DOWNSTREAM:
            source, target = str(parent), str(node["node_id"])
        else:
            source, target = str(node["node_id"]), str(parent)
        key = (source, target, str(node.get("edge_type") or ""))
        if key in edge_seen:
            continue
        edge_seen.add(key)
        edges.append(LayoutEdge(*key))

    # Baris per kolom: satu parent (jalur terpendek) menjadi acuan urutan.
    row_of: dict[str, float] = {root_id: 0.0}
    grouped: dict[int, list[str]] = {}
    for node_id, column in columns.items():
        grouped.setdefault(column, []).append(node_id)
    pending = sorted(
        (column for column in grouped if column != 0),
        key=lambda column: (abs(column), column < 0),
    )
    for column in pending:
        node_ids = grouped[column]

        def sort_key(node_id: str) -> tuple[float, str, str]:
            parent = payloads[node_id].get("parent")
            parent_row = row_of.get(str(parent), 0.0) if parent else 0.0
            return (
                parent_row,
                str(payloads[node_id].get("name") or "").casefold(),
                node_id,
            )

        node_ids.sort(key=sort_key)
        offset = (len(node_ids) - 1) / 2
        for index, node_id in enumerate(node_ids):
            row_of[node_id] = index - offset

    layout_nodes: list[LayoutNode] = []
    for node_id in sorted(
        payloads,
        key=lambda item: (columns[item], row_of[item], str(payloads[item].get("name") or "").casefold()),
    ):
        payload = payloads[node_id]
        layout_nodes.append(
            LayoutNode(
                node_id=node_id,
                node_type=str(payload.get("node_type") or "Unknown"),
                name=str(payload.get("name") or "(unnamed)"),
                workspace_name=payload.get("workspace_name"),
                depth=abs(columns[node_id]),
                column=columns[node_id],
                row=row_of[node_id],
                side=sides[node_id],
                payload=payload,
            )
        )

    root = next(node for node in layout_nodes if node.node_id == root_id)
    return LayoutGraph(
        root=root,
        nodes=tuple(layout_nodes),
        edges=tuple(edges),
        truncated=truncated,
    )
