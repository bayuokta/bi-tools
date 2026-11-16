"""View model tab Lineage.

Memegang database terpilih, status scan/pencarian, root lineage, arah/kedalaman,
penyusunan detail node, dan ekspor CSV. Widget hanya merender
:class:`LineageState`, tabel hasil, dan tree lineage.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from PySide6.QtCore import QObject, Signal

from core.errors import ExtractionError
from core.lineage_layout import LayoutGraph
from core.lineage_service import (
    database_summary,
    export_csv as write_export,
    graph_for,
    node_lineage,
    search_nodes,
)
from core.lineage_store import DEFAULT_DB
from core.pbix import ROOT

from ..settings_store import AppSettings

SEARCH_LIMIT = 300


@dataclass(frozen=True)
class LineageState:
    """Keadaan tab Lineage yang dirender view."""

    idle: bool
    has_db: bool
    has_root: bool
    has_result: bool
    search_status: str
    lineage_status: str


class LineageViewModel(QObject):
    """Satu sumber kebenaran untuk pencarian, lineage, dan ekspor."""

    state_changed = Signal(object)
    log = Signal(str)
    error = Signal(str, str)
    results_changed = Signal(object)
    lineage_changed = Signal(object)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self._settings = settings
        self._database = Path(settings.lineage_db() or DEFAULT_DB).expanduser()
        self._busy = False
        self._has_db = False
        self._root: dict[str, Any] | None = None
        self._result: dict[str, Any] | None = None
        self._direction = "downstream"
        self._depth = 15
        self._results: list[dict[str, Any]] = []
        self._search_status = "Belum ada pencarian."
        self._lineage_status = ""
        self._settings.changed.connect(self._on_settings_changed)

    # -- siklus ------------------------------------------------------------
    def start(self) -> None:
        self.refresh_stats()

    def refresh(self) -> None:
        self.state_changed.emit(
            LineageState(
                idle=not self._busy,
                has_db=self._has_db,
                has_root=self._root is not None,
                has_result=self._result is not None,
                search_status=self._search_status,
                lineage_status=self._lineage_status,
            )
        )

    def set_busy(self, busy: bool) -> None:
        busy = bool(busy)
        if busy == self._busy:
            return
        self._busy = busy
        self.refresh()

    # -- turunan -----------------------------------------------------------
    @property
    def database(self) -> Path:
        return self._database

    @property
    def root(self) -> dict[str, Any] | None:
        return self._root

    @property
    def result(self) -> dict[str, Any] | None:
        return self._result

    @property
    def direction(self) -> str:
        return self._direction

    @property
    def depth(self) -> int:
        return self._depth

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def results(self) -> list[dict[str, Any]]:
        return self._results

    # -- database ----------------------------------------------------------
    def refresh_stats(self) -> None:
        summary = database_summary(self._database)
        self._has_db = summary.readable
        if not summary.exists:
            self._search_status = (
                "Database belum ada. Jalankan Sinkronisasi data di tab Pengaturan."
            )
        elif not summary.readable:
            self._search_status = f"Database tidak bisa dibaca: {summary.error}"
        self.refresh()

    def _reset_after_database_change(self) -> None:
        self._results = []
        self.results_changed.emit([])
        self._search_status = "Belum ada pencarian."
        self.reset_lineage()
        self.refresh_stats()

    def _on_settings_changed(self, group: str) -> None:
        if group == "paths":
            value = Path(
                self._settings.lineage_db() or DEFAULT_DB
            ).expanduser()
            if value != self._database:
                self._database = value
                self._reset_after_database_change()

    # -- pencarian ---------------------------------------------------------
    def search(self, query: str, workspace: str = "", node_type: str = "") -> None:
        if self._busy or not self._has_db:
            return
        query = (query or "").strip()
        workspace = (workspace or "").strip()
        node_type = str(node_type or "")
        if not query and not workspace and not node_type:
            self._search_status = "Isi kata kunci atau filter terlebih dahulu."
            self.refresh()
            return
        try:
            rows = search_nodes(
                self._database, query, workspace, node_type, limit=SEARCH_LIMIT
            )
        except ExtractionError as exc:
            self._fail("Pencarian gagal", str(exc))
            return

        self._results = rows
        self.results_changed.emit(rows)
        if rows:
            capped = (
                " (batas tercapai; perjelas kata kunci)"
                if len(rows) >= SEARCH_LIMIT
                else ""
            )
            self._search_status = f"{len(rows)} hasil{capped}."
            self.refresh()
            self.load_lineage(str(rows[0].get("node_id") or ""))
        else:
            self._search_status = "Tidak ada hasil."
            self.reset_lineage()
            self.refresh()

    # -- lineage -----------------------------------------------------------
    def load_lineage(self, node_id: str | None = None) -> None:
        target = node_id or (self._root or {}).get("node_id")
        if not target:
            return
        try:
            result = node_lineage(
                self._database, str(target), self._direction, self._depth
            )
        except ExtractionError as exc:
            self._fail("Lineage gagal", str(exc))
            return

        if result is None:
            self._root = None
            self._result = None
            self._lineage_status = (
                "Node tidak ditemukan di database. Jalankan scan ulang."
            )
            self.lineage_changed.emit(None)
            self.refresh()
            return

        self._result = result
        self._root = result.get("root")
        count = len(result.get("nodes", []))
        direction = "downstream" if self._direction == "downstream" else "upstream"
        if count:
            self._lineage_status = (
                f"{count} item {direction} · maksimum {self._depth} level."
            )
        else:
            self._lineage_status = f"Tidak ada item {direction} dari node ini."
        self.lineage_changed.emit(result)
        self.refresh()

    def reload_lineage(self) -> None:
        if self._root is not None and not self._busy:
            self.load_lineage(str(self._root.get("node_id") or ""))

    def reset_lineage(self) -> None:
        self._root = None
        self._result = None
        self._lineage_status = ""
        self.lineage_changed.emit(None)
        self.refresh()

    def set_direction(self, direction: str) -> None:
        if direction == self._direction:
            return
        self._direction = direction
        self.reload_lineage()

    def set_depth(self, value: int) -> None:
        depth = int(value)
        if depth == self._depth:
            return
        self._depth = depth
        self.reload_lineage()

    # -- tampilan node -----------------------------------------------------
    @staticmethod
    def detail_text(node: Mapping[str, Any]) -> str:
        """Teks panel Detail untuk satu node."""
        lines = [
            f"Tipe        : {node.get('node_type') or '-'}",
            f"Nama        : {node.get('name') or '-'}",
        ]
        if node.get("workspace_name"):
            lines.append(f"Workspace   : {node['workspace_name']}")
        if node.get("workspace_id"):
            lines.append(f"Workspace ID: {node['workspace_id']}")
        lines.append(f"Owner       : {node.get('owner') or '-'}")
        if node.get("last_modified_at"):
            lines.append(f"Diubah      : {node['last_modified_at']}")
        if node.get("endorsement") and node.get("endorsement") != "None":
            lines.append(f"Endorsement : {node['endorsement']}")
        if node.get("sensitivity_label"):
            lines.append(f"Sensitivitas: {node['sensitivity_label']}")
        if node.get("depth") is not None:
            lines.append(f"Kedalaman   : {node['depth']}")
        if node.get("edge_type"):
            lines.append(f"Relasi      : {node['edge_type']}")
        if node.get("is_active") in (0, False):
            lines.append("Status      : nonaktif (tidak terlihat pada scan terakhir)")

        datasource_fields = (
            ("Tipe sumber", "datasource_type"),
            ("Server", "server"),
            ("Database", "database_name"),
            ("Path/URL", "path_or_url"),
            ("Gateway ID", "gateway_id"),
        )
        present = [
            (label, node[key]) for label, key in datasource_fields if node.get(key)
        ]
        if present:
            lines.extend(["", "Datasource:"])
            lines.extend(f"  {label:<11}: {value}" for label, value in present)

        details = node.get("connection_details")
        if details:
            lines.extend(
                [
                    "",
                    "Connection details:",
                    json.dumps(details, indent=2, ensure_ascii=False),
                ]
            )

        lines.extend(["", f"Node ID     : {node.get('node_id') or '-'}"])
        return "\n".join(lines)

    # -- visual ------------------------------------------------------------
    def graph(self) -> LayoutGraph | None:
        node_id = str((self._root or {}).get("node_id") or "")
        if not node_id:
            return None
        try:
            return graph_for(self._database, node_id, self._depth)
        except ExtractionError as exc:
            self._fail("Visual lineage gagal", str(exc))
            return None
        except ValueError as exc:
            self._fail("Visual lineage gagal", str(exc))
            return None

    # -- export ------------------------------------------------------------
    def default_export_path(self) -> Path:
        root_name = str((self._result or {}).get("root", {}).get("name") or "lineage")
        safe_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", root_name).strip(" ._")
        return ROOT / f"Lineage_{safe_name[:80] or 'lineage'}.csv"

    def export_csv(self, target: Path | str) -> Path | None:
        if self._result is None:
            return None
        try:
            written = write_export(Path(target), self._result)
        except OSError as exc:
            self._fail("Gagal menulis CSV", str(exc))
            return None
        self.log.emit(f"CSV lineage: {written}")
        self._lineage_status = f"CSV ditulis: {written.name}"
        self.refresh()
        return written

    # -- error -------------------------------------------------------------
    def _fail(self, title: str, message: str) -> None:
        self.log.emit(f"ERROR: {message}")
        self.error.emit(title, message)
