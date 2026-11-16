"""Tab Analisa Semantic Model (view pasif).

Menampilkan ukuran kolom, status pemakaian, dan alasan per kolom. Semua
keputusan (pilihan workspace/dataset, cakupan report, filter "hanya tidak
dipakai", verdict) berasal dari :class:`app.viewmodels.analysis.AnalysisViewModel`;
widget ini hanya membangun tampilan dan meneruskan input.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .settings_store import AppSettings
from .viewmodels.analysis import SORT_KEYS, AnalysisState, AnalysisViewModel
from .widgets import searchable_combo, sync_combo

HEADERS = (
    "Name",
    "Type",
    "Table / Page",
    "Source",
    "Data Type",
    "Size",
    "Status",
    "Uses",
    "Format string",
    "Has error",
    "Display folder",
)

STATUS_COLORS = {
    "Tidak dipakai": "#b00020",
    "Dipakai": "#1f7a1f",
    "Wajib dipertahankan": "#8a5a00",
    "Perlu dicek": "#555555",
}

GROUP_ORDER = (
    ("Used in visuals", ("field",)),
    ("Used in filters", ("filter-report", "filter-page", "filter-visual", "filter-query")),
    ("Used in sorting & formatting", ("sort", "format", "calculation")),
)

USAGE_LABELS = {
    "field": "Field visual",
    "filter-report": "Filter report",
    "filter-page": "Filter halaman",
    "filter-visual": "Filter visual",
    "filter-query": "Filter query",
    "sort": "Sort",
    "format": "Formatting",
    "calculation": "Visual calculation",
}


class AnalysisTab(QWidget):
    """Tab top-level untuk analisa ukuran + pemakaian kolom."""

    def __init__(
        self,
        window: Any,
        *,
        settings: AppSettings | None = None,
    ) -> None:
        super().__init__()
        self.window = window
        self.vm = AnalysisViewModel(settings or AppSettings(), window.runner)
        self._state: AnalysisState | None = None

        self._build_ui()
        self.vm.state_changed.connect(self.render)
        self.vm.log.connect(self.window.log)

        self.workspace.currentIndexChanged.connect(self._on_workspace)
        self.dataset.currentIndexChanged.connect(self._on_dataset)
        self.reload_button.clicked.connect(self.vm.reload_workspaces)
        self.reload_datasets_button.clicked.connect(self.vm.load_datasets)
        self.analyze_button.clicked.connect(self.vm.analyze)
        self.stop_button.clicked.connect(self.vm.stop)
        self.include_other.toggled.connect(self.vm.set_include_other)
        self.include_personal.toggled.connect(self.vm.set_include_personal)
        self.object_filter.currentIndexChanged.connect(
            lambda _index: self.vm.set_object_filter(
                str(self.object_filter.currentData() or "all")
            )
        )
        self.unused_only.toggled.connect(self.vm.set_unused_only)
        self.search.textChanged.connect(lambda _text: self._fill_tree())
        self.export_button.clicked.connect(self._export)
        self.expand_button.clicked.connect(self.tree.expandAll)
        self.collapse_button.clicked.connect(self.tree.collapseAll)
        self.tree.itemDoubleClicked.connect(self._on_double_click)

        self.vm.start()
        self.render(self.vm.build_state())

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        self.workspace = searchable_combo("Cari workspace...")
        self.dataset = searchable_combo("Cari semantic model...")
        self.reload_button = QPushButton("Muat ulang")
        self.reload_button.setToolTip("Baca ulang katalog workspace dari SQLite.")
        self.reload_datasets_button = QPushButton("Muat ulang")
        self.reload_datasets_button.setToolTip(
            "Baca ulang daftar semantic model di workspace terpilih."
        )
        self.settings_button = QPushButton("Pengaturan...")
        self.settings_button.clicked.connect(
            lambda: self.window.open_settings_tab()
        )

        workspace_row = QHBoxLayout()
        workspace_row.setContentsMargins(0, 0, 0, 0)
        workspace_row.addWidget(self.workspace, 1)
        workspace_row.addWidget(self.reload_button)
        workspace_row.addWidget(self.settings_button)

        dataset_row = QHBoxLayout()
        dataset_row.setContentsMargins(0, 0, 0, 0)
        dataset_row.addWidget(self.dataset, 1)
        dataset_row.addWidget(self.reload_datasets_button)

        self.include_other = QCheckBox(
            "Sertakan report dari workspace lain (admin API)"
        )
        self.include_other.setToolTip(
            "Mematikan opsi ini membatasi pencarian pemakaian ke report di "
            "workspace dataset saja."
        )
        self.include_personal = QCheckBox(
            "Sertakan report My Workspace (personal)"
        )
        self.include_personal.setToolTip(
            "Report di My Workspace user tidak dapat diakses service principal "
            "dan dilewati secara default agar tidak membuat cakupan selalu "
            "tidak lengkap."
        )
        self.analyze_button = QPushButton("Analisa")
        self.stop_button = QPushButton("Hentikan")
        self.stop_button.setEnabled(False)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addWidget(self.include_other)
        action_row.addWidget(self.include_personal)
        action_row.addStretch(1)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.analyze_button)

        self.credential_status = QLabel()
        self.credential_status.setWordWrap(True)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.progress = QLabel()
        self.progress.setStyleSheet("color: #666;")
        self.catalog_hint = QLabel()
        self.catalog_hint.setWordWrap(True)
        self.catalog_hint.setStyleSheet("color: #8a5a00;")

        source_form = QVBoxLayout()
        source_form.setContentsMargins(0, 0, 0, 0)
        source_form.addWidget(QLabel("Workspace:"))
        source_form.addLayout(workspace_row)
        source_form.addWidget(QLabel("Semantic model:"))
        source_form.addLayout(dataset_row)
        source_form.addLayout(action_row)
        source_form.addWidget(self.credential_status)
        source_form.addWidget(self.catalog_hint)
        source_form.addWidget(self.status)
        source_form.addWidget(self.progress)
        source_box = QGroupBox("Sumber dan analisa")
        source_box.setLayout(source_form)

        self.summary = QLabel("Belum ada hasil analisa.")
        font = self.summary.font()
        font.setBold(True)
        self.summary.setFont(font)
        self.summary.setWordWrap(True)
        self.coverage = QLabel()
        self.coverage.setWordWrap(True)
        self.coverage.setStyleSheet("color: #666;")

        self.search = QLineEdit()
        self.search.setPlaceholderText("Cari nama kolom, tabel, atau display folder...")
        self.object_filter = QComboBox()
        self.object_filter.addItem("Kolom + measure", "all")
        self.object_filter.addItem("Kolom saja", "columns")
        self.object_filter.addItem("Measure saja", "measures")
        self.object_filter.setToolTip(
            "Pilih objek yang ditampilkan: kolom, measure, atau keduanya."
        )
        self.unused_only = QCheckBox("Hanya tidak dipakai")
        self.export_button = QPushButton("Export XLSX...")
        self.expand_button = QPushButton("Expand")
        self.collapse_button = QPushButton("Collapse")
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(self.search, 1)
        filter_row.addWidget(self.object_filter)
        filter_row.addWidget(self.unused_only)
        filter_row.addWidget(self.expand_button)
        filter_row.addWidget(self.collapse_button)
        filter_row.addWidget(self.export_button)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(HEADERS))
        self.tree.setHeaderLabels(list(HEADERS))
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setUniformRowHeights(True)
        # Matikan sorting bawaan SEBELUM mengaktifkan header clickable:
        # QTreeView.setSortingEnabled(False) ikut mematikan sectionsClickable.
        self.tree.setSortingEnabled(False)
        header = self.tree.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._on_header_clicked)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        widths = (280, 130, 170, 90, 100, 90, 170, 60, 130, 80, 150)
        for index, width in enumerate(widths):
            self.tree.setColumnWidth(index, width)

        self.note = QLabel(
            "Read-only: tidak ada perubahan ke model. Subscription, alert, "
            "Excel/ad-hoc, Q&A, dan personalisasi user tidak terdeteksi; "
            "“Tidak dipakai” berarti tidak dipakai artefak yang bisa dibaca."
        )
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #8a5a00;")

        layout = QVBoxLayout(self)
        layout.addWidget(source_box)
        layout.addWidget(self.summary)
        layout.addWidget(self.coverage)
        layout.addLayout(filter_row)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.note)

    # -- siklus ------------------------------------------------------------
    def showEvent(self, event: Any) -> None:  # noqa: N802 - nama Qt
        super().showEvent(event)
        self.vm.reload_workspaces()
        state = self.vm.build_state()
        if state.workspace_id and not state.datasets:
            self.vm.load_datasets()

    def set_busy(self, busy: bool) -> None:
        self.vm.set_busy(busy)

    # -- render ------------------------------------------------------------
    def render(self, state: AnalysisState) -> None:
        self._state = state
        self.credential_status.setText(state.credential_text)
        self.credential_status.setStyleSheet(
            f"color: {state.credential_color};" if state.credential_color else ""
        )
        self.catalog_hint.setText(state.catalog_hint)
        self.catalog_hint.setVisible(bool(state.catalog_hint))
        self.status.setText(state.status)
        self.status.setStyleSheet(
            f"color: {state.status_color};" if state.status_color else ""
        )
        self.progress.setText(state.progress)
        self.progress.setVisible(bool(state.progress))
        self.summary.setText(state.summary or "Belum ada hasil analisa.")
        self.coverage.setText(state.coverage)

        self._fill_combo(
            self.workspace, state.workspaces, state.workspace_id
        )
        self._fill_combo(self.dataset, state.datasets, state.dataset_id)
        if self.include_other.isChecked() != state.include_other_workspaces:
            self.include_other.blockSignals(True)
            self.include_other.setChecked(state.include_other_workspaces)
            self.include_other.blockSignals(False)
        if self.include_personal.isChecked() != state.include_personal:
            self.include_personal.blockSignals(True)
            self.include_personal.setChecked(state.include_personal)
            self.include_personal.blockSignals(False)
        if self.unused_only.isChecked() != state.unused_only:
            self.unused_only.blockSignals(True)
            self.unused_only.setChecked(state.unused_only)
            self.unused_only.blockSignals(False)
        index = self.object_filter.findData(state.object_filter)
        if index >= 0 and self.object_filter.currentIndex() != index:
            self.object_filter.blockSignals(True)
            self.object_filter.setCurrentIndex(index)
            self.object_filter.blockSignals(False)
        header = self.tree.header()
        if state.sort_column in SORT_KEYS:
            header.setSortIndicator(
                SORT_KEYS.index(state.sort_column),
                Qt.SortOrder.DescendingOrder
                if state.sort_desc
                else Qt.SortOrder.AscendingOrder,
            )
            header.setSortIndicatorShown(True)
        else:
            header.setSortIndicatorShown(False)

        idle = state.idle
        self.workspace.setEnabled(idle)
        self.dataset.setEnabled(idle)
        self.reload_button.setEnabled(idle)
        self.reload_datasets_button.setEnabled(idle and bool(state.workspace_id))
        self.include_other.setEnabled(idle)
        self.include_personal.setEnabled(idle)
        self.analyze_button.setEnabled(state.can_run)
        self.stop_button.setEnabled(state.running)
        # Hasil yang sudah ada tetap bisa dibaca/diurutkan saat job lain
        # berjalan (mis. refresh instance / muat dataset); hanya analisa
        # yang sedang berjalan yang mengunci tampilan.
        view_idle = not state.running
        self.search.setEnabled(view_idle)
        self.object_filter.setEnabled(view_idle)
        self.unused_only.setEnabled(view_idle)
        self.export_button.setEnabled(view_idle and state.has_result)
        self.tree.setEnabled(view_idle)
        self._fill_tree()

    def _fill_combo(
        self,
        combo: QComboBox,
        items: tuple[tuple[str, str], ...],
        selected: str,
    ) -> None:
        labels = [label for label, _value in items]
        index = next(
            (
                position
                for position, (_label, value) in enumerate(items)
                if value == selected
            ),
            -1,
        )
        sync_combo(combo, labels, index)
        for position, (_label, value) in enumerate(items):
            combo.setItemData(position, value, Qt.ItemDataRole.UserRole)

    def _current_id(self, combo: QComboBox) -> str:
        index = combo.currentIndex()
        if index < 0:
            return ""
        return str(combo.itemData(index) or "")

    def _fill_tree(self) -> None:
        self.tree.clear()
        if self.vm.result is None:
            return
        needle = self.search.text().strip().casefold()
        for row in self.vm.visible_objects():
            analysis = row["analysis"]
            expression = getattr(
                getattr(analysis, "measure", None), "expression", ""
            )
            haystack = " ".join(
                [
                    str(row["name"]),
                    str(row["table"]),
                    str(row["display_folder"]),
                    str(row["type"]),
                    str(row["format_string"]),
                    str(expression),
                ]
            ).casefold()
            if needle and needle not in haystack:
                continue
            self.tree.addTopLevelItem(self._object_item(row))

    def _object_item(self, row: dict[str, Any]) -> QTreeWidgetItem:
        item = QTreeWidgetItem(
            [
                str(row["name"]),
                str(row["type"]),
                str(row["table"]),
                "Model",
                str(row["data_type"]),
                str(row["size"]),
                str(row["status"]),
                str(row["uses"]),
                str(row["format_string"]),
                "Yes" if row["has_error"] else "No",
                str(row["display_folder"]),
            ]
        )
        analysis = row["analysis"]
        color = STATUS_COLORS.get(str(row["status"]), "")
        if color:
            brush = QBrush(QColor(color))
            item.setForeground(0, brush)
            item.setForeground(6, brush)
        item.setToolTip(6, analysis.reason)
        if getattr(analysis, "measure", None) is not None:
            item.setToolTip(
                0,
                f"{analysis.reason}\n"
                f"DAX: {analysis.measure.expression or '(kosong)'}",
            )
        else:
            item.setToolTip(
                0,
                f"{analysis.reason}\n"
                f"Data {analysis.column.size_data_bytes:,} byte + hierarki "
                f"{analysis.column.size_hierarchy_bytes:,} byte + dictionary "
                f"{analysis.column.size_dictionary_bytes:,} byte\n"
                f"Total {analysis.column.size_total_bytes:,} byte · "
                f"Baris: {analysis.column.rows:,}".replace(",", "."),
            )

        for label, kinds in GROUP_ORDER:
            records = [
                record
                for record in analysis.report_records
                if str(record.get("usage_kind") or "") in kinds
            ]
            if records:
                item.addChild(self._records_group(label, records))

        if analysis.model_refs:
            group = QTreeWidgetItem(
                [f"Used in artifacts ({len(analysis.model_refs)})"]
            )
            group.setFirstColumnSpanned(True)
            group.setForeground(0, QBrush(QColor("#555555")))
            for reference in analysis.model_refs:
                child = QTreeWidgetItem(
                    [
                        reference.object,
                        reference.kind,
                        "",
                        "Model",
                        "Blocking" if reference.blocking else "Indirect",
                        "",
                        "",
                        "",
                        reference.detail,
                        "",
                        "",
                    ]
                )
                group.addChild(child)
            item.addChild(group)
        return item

    def _records_group(
        self, label: str, records: list[dict[str, Any]]
    ) -> QTreeWidgetItem:
        group = QTreeWidgetItem([f"{label} ({len(records)})"])
        group.setFirstColumnSpanned(True)
        group.setForeground(0, QBrush(QColor("#555555")))
        by_report: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            key = str(record.get("report_id") or "")
            by_report.setdefault(key, []).append(record)
        for report_records in by_report.values():
            first = report_records[0]
            report_name = str(first.get("report_name") or "(report)")
            report_item = QTreeWidgetItem(
                [
                    report_name,
                    f"{len(report_records)} titik",
                    "",
                    "Report",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
            report_item.setForeground(0, QBrush(QColor("#1f4e79")))
            url = str(first.get("report_url") or "")
            if url:
                report_item.setData(0, Qt.ItemDataRole.UserRole, url)
                report_item.setToolTip(0, "Klik dua kali untuk membuka report.")
            for record in sorted(
                report_records,
                key=lambda row: (
                    str(row.get("page_name") or ""),
                    str(row.get("visual_title") or ""),
                ),
            ):
                report_item.addChild(
                    QTreeWidgetItem(
                        [
                            str(record.get("visual_title") or "(report)"),
                            USAGE_LABELS.get(
                                str(record.get("usage_kind") or ""),
                                str(record.get("usage_kind") or ""),
                            ),
                            str(record.get("page_name") or ""),
                            str(record.get("visual_type") or ""),
                            str(record.get("field_kind") or ""),
                            str(record.get("aggregation") or ""),
                            "hidden" if record.get("is_hidden") else "",
                            "",
                            str(record.get("detail") or ""),
                            "",
                            "",
                        ]
                    )
                )
            group.addChild(report_item)
        return group

    # -- handler -----------------------------------------------------------
    def _on_workspace(self, index: int) -> None:
        if index < 0:
            return
        self.vm.set_workspace(self._current_id(self.workspace))

    def _on_header_clicked(self, index: int) -> None:
        if 0 <= index < len(SORT_KEYS):
            self.vm.set_sort(SORT_KEYS[index])

    def _header_menu(self, position: Any) -> None:
        menu = QMenu(self)
        reset = menu.addAction("Reset urutan")
        reset.setEnabled(
            self._state is not None and self._state.sort_column != "default"
        )
        if menu.exec(self.tree.header().mapToGlobal(position)) is reset:
            self.vm.reset_sort()

    def _on_dataset(self, index: int) -> None:
        if index < 0:
            return
        self.vm.set_dataset(self._current_id(self.dataset))

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        url = item.data(0, Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(str(url)))
            return
        item.setExpanded(not item.isExpanded())

    def _export(self) -> None:
        if self.vm.result is None:
            return
        default = str(self.vm.default_output_path())
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan hasil analisa", default, "Workbook Excel (*.xlsx)"
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".xlsx")
        try:
            written = self.vm.export(target)
        except Exception as exc:  # noqa: BLE001 - tampilkan pesan ke pengguna
            QMessageBox.critical(self, "Export gagal", str(exc))
            return
        self.window.log(f"Hasil analisa ditulis ke {written}.")
