"""Warna, urutan, dan badge tipe node lineage untuk tab dan kanvas."""

from __future__ import annotations

TYPE_ORDER = ["Workspace", "Dataflow", "SemanticModel", "Report", "Dashboard", "Datasource"]
TYPE_COLORS = {
    "Dataflow": "#7b1fa2",
    "SemanticModel": "#1565c0",
    "Report": "#2e7d32",
    "Dashboard": "#00695c",
    "Datasource": "#b26a00",
    "Workspace": "#5f6b7a",
}
TYPE_BADGES = {
    "Workspace": "W",
    "Dataflow": "DF",
    "SemanticModel": "SM",
    "Report": "R",
    "Dashboard": "D",
    "Datasource": "DS",
}
DEFAULT_COLOR = "#5f6b7a"


def type_color(node_type: str | None) -> str:
    return TYPE_COLORS.get(str(node_type or ""), DEFAULT_COLOR)


def type_badge(node_type: str | None) -> str:
    return TYPE_BADGES.get(str(node_type or ""), "?")
