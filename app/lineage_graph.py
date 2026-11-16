"""Kanvas visual lineage bergaya Power BI Service memakai QGraphicsView."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyleOptionGraphicsItem,
    QVBoxLayout,
    QWidget,
)

from core.lineage_layout import MAX_NODES, LayoutEdge, LayoutGraph, LayoutNode

from .lineage_style import TYPE_ORDER, type_badge, type_color

CARD_WIDTH = 236.0
CARD_HEIGHT = 82.0
COLUMN_GAP = 310.0
ROW_GAP = 104.0
MIN_ZOOM = 0.03
MAX_ZOOM = 3.0

EDGE_COLORS = {
    "feeds": "#7b1fa2",
    "uses_dataset": "#1565c0",
    "pinned_to": "#00695c",
    "contains": "#8a94a3",
}
DEFAULT_EDGE_COLOR = "#8a94a3"


def _edge_color(edge_type: str) -> str:
    return EDGE_COLORS.get(edge_type, DEFAULT_EDGE_COLOR)


def graph_key(graph: LayoutGraph) -> tuple:
    """Ringkasan isi graph untuk mendeteksi perubahan sebelum menggambar ulang."""
    return (
        graph.root.node_id,
        graph.truncated,
        tuple(
            (node.node_id, node.column, node.row, node.name, node.node_type)
            for node in graph.nodes
        ),
        tuple(
            (edge.source_id, edge.target_id, edge.edge_type) for edge in graph.edges
        ),
    )


class NodeItem(QGraphicsObject):
    """Kartu satu item lineage: badge tipe, nama, dan workspace."""

    double_clicked = Signal(str)

    def __init__(self, node: LayoutNode) -> None:
        super().__init__()
        self.node = node
        self._font = QFont()
        self._hover = False
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self._tooltip(node))
        self._name = self._elide(node.name, CARD_WIDTH - 20, bold=True)
        workspace = node.workspace_name or "Tanpa workspace"
        self._workspace = self._elide(workspace, CARD_WIDTH - 20, bold=False)
        self._type_label = self._elide(node.node_type, CARD_WIDTH - 58, bold=False)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, CARD_WIDTH, CARD_HEIGHT)

    def _elide(self, text: str, width: float, *, bold: bool) -> str:
        font = QFont(self._font)
        font.setPointSizeF(9.5 if bold else 8.0)
        font.setBold(bold)
        metrics = QFontMetrics(font)
        return metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(width))

    @staticmethod
    def _tooltip(node: LayoutNode) -> str:
        payload = node.payload
        lines = [node.name, f"{node.node_type} · {node.workspace_name or '-'}"]
        if payload.get("owner"):
            lines.append(f"Owner: {payload['owner']}")
        if payload.get("datasource_type"):
            lines.append(f"Datasource: {payload['datasource_type']}")
        for label, key in (("Server", "server"), ("Database", "database_name")):
            if payload.get(key):
                lines.append(f"{label}: {payload[key]}")
        if payload.get("path_or_url"):
            lines.append(f"Path/URL: {payload['path_or_url']}")
        if payload.get("last_modified_at"):
            lines.append(f"Diubah: {payload['last_modified_at']}")
        if payload.get("is_active") in (0, False):
            lines.append("Nonaktif pada scan terakhir")
        lines.append(f"Node ID: {node.node_id}")
        return "\n".join(lines)

    def paint(
        self,
        painter: QPainter,
        _option: QStyleOptionGraphicsItem,
        _widget: QWidget | None = None,
    ) -> None:
        color = QColor(type_color(self.node.node_type))
        rect = self.boundingRect()
        body = QPainterPath()
        body.addRoundedRect(rect, 8, 8)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillPath(body, QColor("#ffffff"))

        painter.save()
        painter.setClipPath(body)
        painter.fillRect(QRectF(0, 0, CARD_WIDTH, 5), color)
        painter.restore()

        if self.node.side == "root":
            border = QPen(color, 2.2)
        elif self._hover:
            border = QPen(QColor("#6d9ad1"), 1.8)
        else:
            border = QPen(QColor("#d3dae3"), 1.0)
        painter.setPen(border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(body)

        badge_rect = QRectF(10, 15, 30, 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(badge_rect, 4, 4)
        badge_font = QFont(self._font)
        badge_font.setPointSizeF(8.0)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, type_badge(self.node.node_type))

        type_font = QFont(self._font)
        type_font.setPointSizeF(8.0)
        painter.setFont(type_font)
        painter.setPen(QColor("#6b7684"))
        painter.drawText(
            QRectF(48, 15, CARD_WIDTH - 60, 18),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._type_label,
        )

        name_font = QFont(self._font)
        name_font.setPointSizeF(9.5)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.setPen(QColor("#1f2933"))
        painter.drawText(
            QRectF(10, 38, CARD_WIDTH - 20, 20),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._name,
        )

        workspace_font = QFont(self._font)
        workspace_font.setPointSizeF(8.0)
        painter.setFont(workspace_font)
        painter.setPen(QColor("#7b8794"))
        painter.drawText(
            QRectF(10, 58, CARD_WIDTH - 20, 16),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._workspace,
        )

    def right_anchor(self) -> QPointF:
        return QPointF(self.x() + CARD_WIDTH, self.y() + CARD_HEIGHT / 2)

    def left_anchor(self) -> QPointF:
        return QPointF(self.x(), self.y() + CARD_HEIGHT / 2)

    def hoverEnterEvent(self, event) -> None:  # noqa: ANN001 - signature Qt
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: ANN001 - signature Qt
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: ANN001 - signature Qt
        self.double_clicked.emit(self.node.node_id)
        event.accept()


class LineageView(QGraphicsView):
    """Kanvas dengan pan (drag), zoom (Ctrl+wheel atau tombol), dan fit."""

    def __init__(self, scene: QGraphicsScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor("#f4f6f9"))
        self._zoom = 1.0

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)
        step = 32.0
        if self._zoom < 0.15:
            step = 640.0
        elif self._zoom < 0.4:
            step = 160.0
        pen = QPen(QColor("#e7ebf0"), 0.0)
        painter.setPen(pen)
        left = rect.left() - (rect.left() % step)
        top = rect.top() - (rect.top() % step)
        x = left
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = top
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step

    def fit(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(
            rect.adjusted(-60, -60, 60, 60),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        self._zoom = self.transform().m11()

    def zoom_by(self, factor: float) -> None:
        current = self.transform().m11()
        if current <= 0:
            return
        target = min(max(current * factor, MIN_ZOOM), MAX_ZOOM)
        self.scale(target / current, target / current)
        self._zoom = target

    def wheelEvent(self, event) -> None:  # noqa: ANN001 - signature Qt
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            event.accept()
            return
        super().wheelEvent(event)


class LineageGraphWindow(QDialog):
    """Jendela non-modal berisi kanvas lineage dua arah untuk satu root."""

    node_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("Visual lineage")
        self.resize(1140, 740)
        self._graph: LayoutGraph | None = None
        self._nodes: dict[str, NodeItem] = {}
        self._edge_labels: list[QGraphicsSimpleTextItem] = []

        self.title = QLabel("Belum ada item.")
        self.title.setTextFormat(Qt.TextFormat.RichText)
        self.title.setWordWrap(True)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #55606d;")

        self.fit_button = QPushButton("Fit")
        self.fit_button.setToolTip("Muat seluruh graph dalam tampilan.")
        self.zoom_in_button = QPushButton("Zoom +")
        self.zoom_out_button = QPushButton("Zoom -")
        self.labels = QCheckBox("Label relasi")
        self.labels.setToolTip("Tampilkan tipe relasi di tengah garis.")
        self.hint = QLabel("Drag untuk menggeser · Ctrl+wheel untuk zoom · klik dua kali kartu untuk menjadikannya root.")
        self.hint.setStyleSheet("color: #7b8794;")

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.addWidget(self.fit_button)
        toolbar.addWidget(self.zoom_in_button)
        toolbar.addWidget(self.zoom_out_button)
        toolbar.addSpacing(12)
        toolbar.addWidget(self.labels)
        toolbar.addStretch(1)
        toolbar.addWidget(self.hint)

        self.scene = QGraphicsScene(self)
        self.view = LineageView(self.scene, self)

        self.legend = QLabel("")
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet("color: #55606d;")

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        layout.addLayout(toolbar)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.legend)

        self.fit_button.clicked.connect(self.view.fit)
        self.zoom_in_button.clicked.connect(lambda: self.view.zoom_by(1.2))
        self.zoom_out_button.clicked.connect(lambda: self.view.zoom_by(1 / 1.2))
        self.labels.toggled.connect(self._toggle_labels)

    # -- isi kanvas --------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: ANN001 - signature Qt
        """Gambar ulang bingkai setelah jendela tampil agar zoom sesuai viewport."""
        super().showEvent(event)
        if self._graph is not None:
            QTimer.singleShot(0, self.view.fit)

    def matches(self, graph: LayoutGraph) -> bool:
        """True bila graph sama dengan yang sedang tampil (tanpa perlu gambar ulang)."""
        return self._graph is not None and graph_key(self._graph) == graph_key(graph)

    def set_graph(self, graph: LayoutGraph) -> None:
        """Ganti isi kanvas dengan graph baru dan atur ulang tampilan."""
        self._graph = graph
        self.scene.clear()
        self._nodes.clear()
        self._edge_labels.clear()

        for node in graph.nodes:
            item = NodeItem(node)
            item.setPos(
                QPointF(
                    node.column * COLUMN_GAP,
                    node.row * ROW_GAP - CARD_HEIGHT / 2,
                )
            )
            item.double_clicked.connect(self.node_activated)
            self.scene.addItem(item)
            self._nodes[node.node_id] = item

        for edge in graph.edges:
            self._add_edge(edge)

        self._toggle_labels(self.labels.isChecked())
        self._render_header(graph)
        self.view.fit()

    def _add_edge(self, edge: LayoutEdge) -> None:
        source = self._nodes.get(edge.source_id)
        target = self._nodes.get(edge.target_id)
        if source is None or target is None:
            return
        if source.node.column >= target.node.column:
            return

        start = source.right_anchor()
        end = target.left_anchor()
        span = max(abs(end.x() - start.x()) / 2, 50.0)
        path = QPainterPath(start)
        path.cubicTo(
            QPointF(start.x() + span, start.y()),
            QPointF(end.x() - span, end.y()),
            end,
        )
        color = QColor(_edge_color(edge.edge_type))
        pen = QPen(color, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line = QGraphicsPathItem(path)
        line.setPen(pen)
        line.setZValue(0)
        line.setToolTip(edge.edge_type or "relasi")
        self.scene.addItem(line)

        arrow = QGraphicsPolygonItem(
            QPolygonF(
                [
                    end,
                    QPointF(end.x() - 9, end.y() - 4.5),
                    QPointF(end.x() - 9, end.y() + 4.5),
                ]
            )
        )
        arrow.setBrush(color)
        arrow.setPen(Qt.PenStyle.NoPen)
        arrow.setZValue(0)
        arrow.setToolTip(edge.edge_type or "relasi")
        self.scene.addItem(arrow)

        label = QGraphicsSimpleTextItem(edge.edge_type or "")
        label_font = QFont(self.font())
        label_font.setPointSizeF(7.5)
        label.setFont(label_font)
        label.setBrush(QColor("#6b7684"))
        middle = QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)
        label.setPos(middle.x() - label.boundingRect().width() / 2, middle.y() - 9)
        label.setZValue(2)
        label.setToolTip(edge.edge_type or "relasi")
        label.setVisible(self.labels.isChecked())
        self.scene.addItem(label)
        self._edge_labels.append(label)

    def _toggle_labels(self, visible: bool) -> None:
        for label in self._edge_labels:
            label.setVisible(visible)

    def _render_header(self, graph: LayoutGraph) -> None:
        root = graph.root
        color = type_color(root.node_type)
        self.title.setText(
            f"<b>{_escape(root.name)}</b> "
            f"<span style='color:{color}'>[{_escape(root.node_type)}]</span>"
            f"<br><span style='color:#55606d'>{_escape(root.workspace_name or 'Tanpa workspace')}</span>"
        )
        upstream = sum(1 for node in graph.nodes if node.side == "upstream")
        downstream = sum(1 for node in graph.nodes if node.side == "downstream")
        parts = [
            f"{len(graph.nodes)} node",
            f"{len(graph.edges)} relasi",
            f"{upstream} upstream",
            f"{downstream} downstream",
        ]
        if graph.truncated:
            parts.append(
                f"{graph.truncated} node tidak ditampilkan (batas {MAX_NODES})"
            )
        self.status.setText(" · ".join(parts))

        present = {node.node_type for node in graph.nodes}
        items = []
        for node_type in TYPE_ORDER:
            if node_type in present:
                items.append(
                    f"<span style='color:{type_color(node_type)}'>●</span> {_escape(node_type)}"
                )
        self.legend.setText("&nbsp;&nbsp;".join(items))
        self.setWindowTitle(f"Visual lineage · {root.name}")


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
