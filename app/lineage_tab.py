"""Tab GUI lineage item Power BI Service (view pasif).

Widget hanya membangun tampilan, meneruskan input ke :class:`LineageViewModel`,
dan merender state/tabel/tree. Akses database read-only ada di
``core.lineage_service``; keputusan status/ekspor ada di view model.
"""

from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .lineage_graph import LineageGraphWindow
from .lineage_style import TYPE_COLORS, TYPE_ORDER
from .settings_store import AppSettings
from .viewmodels.lineage import LineageState, LineageViewModel

if TYPE_CHECKING:
    from .main_window import MainWindow

SEARCH_TYPES = [
    ("", "Semua tipe"),
    ("Report", "Report"),
    ("SemanticModel", "Semantic Model"),
    ("Dataflow", "Dataflow"),
    ("Dashboard", "Dashboard"),
    ("Datasource", "Datasource"),
]
ROOT_HINT = "Pilih item pada tabel hasil pencarian, atau klik dua kali node di tree."


class LineageTab(QWidget):
    """Scan lineage ke SQLite, cari item, lalu tampilkan tree upstream/downstream."""

    def __init__(
        self,
        window: MainWindow,
        *,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self.window = window
        settings = settings or AppSettings()
        self.vm = LineageViewModel(settings)
        self._filling = False
        self._graph_window: LineageGraphWindow | None = None

        self._build_ui()

        self.vm.state_changed.connect(self.render)
        self.vm.log.connect(self.window.log)
        self.vm.error.connect(self._show_error)
        self.vm.results_changed.connect(self._fill_results)
        self.vm.lineage_changed.connect(self._render_lineage)

        self.search_button.clicked.connect(self.run_search)
        self.query.returnPressed.connect(self.run_search)
        self.workspace_filter.returnPressed.connect(self.run_search)
        self.results.itemSelectionChanged.connect(self._on_results_selection)
        self.upstream_button.clicked.connect(lambda: self._set_direction("upstream"))
        self.downstream_button.clicked.connect(
            lambda: self._set_direction("downstream")
        )
        self.depth.valueChanged.connect(self.vm.set_depth)
        self.visual_button.clicked.connect(self._open_visual)
        self.tree.currentItemChanged.connect(self._on_tree_current)
        self.tree.itemDoubleClicked.connect(self._open_tree_node)
        self.export_button.clicked.connect(self._export_csv)

        self.vm.start()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        # -- pencarian -----------------------------------------------------
        self.query = QLineEdit()
        self.query.setPlaceholderText(
            "Cari nama Report, Semantic Model, Dataflow, Dashboard, atau Datasource"
        )
        self.query.setClearButtonEnabled(True)
        self.search_button = QPushButton("Cari")
        self.workspace_filter = QLineEdit()
        self.workspace_filter.setPlaceholderText("Filter nama workspace (opsional)")
        self.workspace_filter.setClearButtonEnabled(True)
        self.type_filter = QComboBox()
        for value, label in SEARCH_TYPES:
            self.type_filter.addItem(label, value)

        self.search_status = QLabel("Belum ada pencarian.")
        self.search_status.setWordWrap(True)
        self.results = QTableWidget(0, 4)
        self.results.setHorizontalHeaderLabels(["Tipe", "Nama", "Workspace", "Owner"])
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results.setAlternatingRowColors(True)
        self.results.setWordWrap(False)
        self.results.verticalHeader().setVisible(False)
        result_header = self.results.horizontalHeader()
        result_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        result_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        result_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        result_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        query_row = QHBoxLayout()
        query_row.setContentsMargins(0, 0, 0, 0)
        query_row.addWidget(QLabel("Kata kunci:"))
        query_row.addWidget(self.query, 1)
        query_row.addWidget(self.search_button)
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel("Workspace:"))
        filter_row.addWidget(self.workspace_filter, 1)
        filter_row.addWidget(QLabel("Tipe:"))
        filter_row.addWidget(self.type_filter)

        search_layout = QVBoxLayout()
        search_layout.addLayout(query_row)
        search_layout.addLayout(filter_row)
        search_layout.addWidget(self.search_status)
        search_layout.addWidget(self.results, 1)
        search_box = QGroupBox("Pencarian item")
        search_box.setLayout(search_layout)

        # -- lineage -------------------------------------------------------
        self.root_label = QLabel(ROOT_HINT)
        self.root_label.setWordWrap(True)
        self.root_label.setTextFormat(Qt.TextFormat.RichText)

        self.upstream_button = QPushButton("Upstream")
        self.upstream_button.setCheckable(True)
        self.upstream_button.setToolTip(
            "Item yang menjadi sumber data node ini (misal dataflow atau datasource)."
        )
        self.downstream_button = QPushButton("Downstream")
        self.downstream_button.setCheckable(True)
        self.downstream_button.setChecked(True)
        self.downstream_button.setToolTip(
            "Item yang memakai data node ini (misal report atau dashboard)."
        )
        self.direction_group = QButtonGroup(self)
        self.direction_group.setExclusive(True)
        self.direction_group.addButton(self.upstream_button)
        self.direction_group.addButton(self.downstream_button)

        self.depth = QSpinBox()
        self.depth.setRange(1, 30)
        self.depth.setValue(self.vm.depth)
        self.depth.setSuffix(" level")

        self.visual_button = QPushButton("Visual lineage...")
        self.visual_button.setToolTip(
            "Buka kanvas dua arah: upstream di kiri, downstream di kanan."
        )

        direction_row = QHBoxLayout()
        direction_row.setContentsMargins(0, 0, 0, 0)
        direction_row.addWidget(QLabel("Arah:"))
        direction_row.addWidget(self.upstream_button)
        direction_row.addWidget(self.downstream_button)
        direction_row.addSpacing(12)
        direction_row.addWidget(QLabel("Kedalaman:"))
        direction_row.addWidget(self.depth)
        direction_row.addSpacing(12)
        direction_row.addWidget(self.visual_button)
        direction_row.addStretch(1)

        self.lineage_status = QLabel("")
        self.lineage_status.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Tipe", "Relasi"])
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        tree_header = self.tree.header()
        tree_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tree_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        lineage_layout = QVBoxLayout()
        lineage_layout.addWidget(self.root_label)
        lineage_layout.addLayout(direction_row)
        lineage_layout.addWidget(self.lineage_status)
        lineage_layout.addWidget(self.tree, 1)
        lineage_box = QGroupBox("Lineage")
        lineage_box.setLayout(lineage_layout)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Detail node akan tampil di sini.")
        self.detail.setFont(
            QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        )
        detail_layout = QVBoxLayout()
        detail_layout.addWidget(self.detail, 1)
        detail_box = QGroupBox("Detail")
        detail_box.setLayout(detail_layout)

        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_splitter.addWidget(lineage_box)
        right_splitter.addWidget(detail_box)
        right_splitter.setStretchFactor(0, 3)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setSizes([380, 220])

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(search_box)
        splitter.addWidget(right_splitter)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([430, 620])

        self.export_button = QPushButton("Export CSV...")
        hint = QLabel("Klik dua kali node pada tree untuk menjadikannya root baru.")
        hint.setStyleSheet("color: #666;")
        footer = QHBoxLayout()
        footer.addWidget(self.export_button)
        footer.addWidget(hint, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(footer)

    # -- siklus ------------------------------------------------------------
    def showEvent(self, event: Any) -> None:  # noqa: N802 - nama Qt
        super().showEvent(event)
        # Hasil Sinkronisasi data di tab Pengaturan langsung terlihat.
        self.vm.refresh_stats()
        if self.vm.root is not None:
            self.vm.reload_lineage()

    # -- render ------------------------------------------------------------
    def render(self, state: LineageState) -> None:
        self.search_status.setText(state.search_status)
        self.lineage_status.setText(state.lineage_status)

        idle = state.idle
        self.query.setEnabled(idle and state.has_db)
        self.workspace_filter.setEnabled(idle and state.has_db)
        self.type_filter.setEnabled(idle and state.has_db)
        self.search_button.setEnabled(idle and state.has_db)
        self.results.setEnabled(idle)

        self.upstream_button.setEnabled(idle and state.has_root)
        self.downstream_button.setEnabled(idle and state.has_root)
        self.depth.setEnabled(idle and state.has_root)
        self.visual_button.setEnabled(idle and state.has_root)
        self.tree.setEnabled(idle)
        self.export_button.setEnabled(idle and state.has_result)

    # -- pencarian ---------------------------------------------------------
    def run_search(self) -> None:
        self.vm.search(
            self.query.text(),
            self.workspace_filter.text(),
            str(self.type_filter.currentData() or ""),
        )

    def _fill_results(self, rows: list[dict[str, Any]]) -> None:
        self._filling = True
        try:
            self.results.blockSignals(True)
            self.results.setRowCount(0)
            for row in rows:
                index = self.results.rowCount()
                self.results.insertRow(index)
                values = (
                    row.get("node_type") or "",
                    row.get("name") or "",
                    row.get("workspace_name") or "",
                    row.get("owner") or "",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    if column == 1:
                        item.setToolTip(str(row.get("node_id") or ""))
                    self.results.setItem(index, column, item)
                self.results.item(index, 0).setData(
                    Qt.ItemDataRole.UserRole, row
                )
            if rows:
                self.results.selectRow(0)
        finally:
            self.results.blockSignals(False)
            self._filling = False

    def _on_results_selection(self) -> None:
        if self._filling:
            return
        selected = self.results.selectionModel().selectedRows()
        if not selected:
            return
        item = self.results.item(selected[0].row(), 0)
        if item is None:
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(row, dict) and row.get("node_id"):
            self.vm.load_lineage(str(row["node_id"]))

    # -- lineage -----------------------------------------------------------
    def _set_direction(self, direction: str) -> None:
        self.vm.set_direction(direction)

    def _render_lineage(self, result: dict[str, Any] | None) -> None:
        self.tree.clear()
        self.detail.clear()
        if not result:
            self.root_label.setText(ROOT_HINT)
            if self._graph_window is not None:
                self._graph_window.close()
            return
        self._render_root()
        self._render_tree(result)
        self._refresh_visual()

    def _render_root(self) -> None:
        root = self.vm.root or {}
        name = escape(str(root.get("name") or "(tanpa nama)"))
        node_type = escape(str(root.get("node_type") or "-"))
        workspace = escape(str(root.get("workspace_name") or "-"))
        owner = escape(str(root.get("owner") or "-"))
        self.root_label.setText(
            f"<b>{name}</b> <span style='color:#666'>[{node_type}]</span><br>"
            f"<span style='color:#555'>Workspace: {workspace} &middot; Owner: {owner}</span>"
        )

    def _make_tree_item(
        self,
        node: dict[str, Any],
        edge_label: str,
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            [
                str(node.get("name") or "(tanpa nama)"),
                str(node.get("node_type") or ""),
                edge_label,
            ]
        )
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        item.setToolTip(0, str(node.get("node_id") or ""))
        color = TYPE_COLORS.get(str(node.get("node_type") or ""))
        if color:
            brush = QBrush(QColor(color))
            for column in range(3):
                item.setForeground(column, brush)
        if node.get("is_active") in (0, False):
            font = item.font(0)
            font.setItalic(True)
            item.setFont(0, font)
        return item

    def _render_tree(self, result: dict[str, Any]) -> None:
        self.tree.clear()
        root = result["root"]
        root_item = self._make_tree_item(root, "root")
        font = root_item.font(0)
        font.setBold(True)
        root_item.setFont(0, font)
        self.tree.addTopLevelItem(root_item)

        children: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for node in result.get("nodes", []):
            parent = node.get("parent")
            if parent:
                children[str(parent)].append(node)

        ranks = {name: index for index, name in enumerate(TYPE_ORDER)}

        def add_children(parent_item: QTreeWidgetItem, parent_id: str) -> None:
            for node in sorted(
                children.get(parent_id, []),
                key=lambda item: (
                    ranks.get(str(item.get("node_type") or ""), 99),
                    str(item.get("name") or "").casefold(),
                ),
            ):
                child = self._make_tree_item(
                    node,
                    str(node.get("edge_type") or ""),
                )
                parent_item.addChild(child)
                add_children(child, str(node.get("node_id") or ""))

        add_children(root_item, str(root.get("node_id") or ""))
        root_item.setExpanded(True)
        self.tree.expandAll()
        self.tree.setCurrentItem(root_item)
        self.tree.scrollToItem(root_item)

    def _on_tree_current(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        if current is None:
            return
        node = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(node, dict):
            self.detail.setPlainText(self.vm.detail_text(node))

    def _open_tree_node(
        self,
        item: QTreeWidgetItem,
        _column: int,
    ) -> None:
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(node, dict) and node.get("node_id"):
            self.vm.load_lineage(str(node["node_id"]))

    # -- visual ------------------------------------------------------------
    def _open_visual(self) -> None:
        if self.vm.busy or self.vm.root is None:
            return
        graph = self.vm.graph()
        if graph is None:
            return
        window = self._graph_window
        if window is None:
            window = LineageGraphWindow(self)
            window.node_activated.connect(
                self._activate_graph_node,
                Qt.ConnectionType.QueuedConnection,
            )
            self._graph_window = window
        window.set_graph(graph)
        window.show()
        window.raise_()
        window.activateWindow()

    def _refresh_visual(self) -> None:
        """Perbarui kanvas bila sedang terbuka setelah root/depth berubah."""
        window = self._graph_window
        if window is None or not window.isVisible():
            return
        graph = self.vm.graph()
        if graph is not None and not window.matches(graph):
            window.set_graph(graph)

    def _activate_graph_node(self, node_id: str) -> None:
        if self.vm.busy or not node_id:
            return
        root = self.vm.root or {}
        if str(root.get("node_id") or "") == node_id:
            return
        self.vm.load_lineage(node_id)

    # -- export ------------------------------------------------------------
    def _export_csv(self) -> None:
        if self.vm.result is None:
            return
        default = self.vm.default_export_path()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Simpan lineage sebagai CSV",
            str(default),
            "CSV (*.csv)",
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".csv")
        self.vm.export_csv(target)

    # -- status ------------------------------------------------------------
    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def set_busy(self, busy: bool) -> None:
        self.vm.set_busy(busy)
