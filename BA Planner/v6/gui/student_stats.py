from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
from typing import Any, Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from gui.student_filters import FILTER_FIELD_LABELS, format_filter_value, get_student_value

STAT_FIELDS: tuple[str, ...] = (
    "owned",
    "student_star",
    "weapon_state",
    "school",
    "rarity",
    "attack_type",
    "defense_type",
    "combat_class",
    "role",
    "position",
    "weapon_type",
    "cover_type",
    "range_type",
)

STAT_FIELD_LABELS: dict[str, str] = {"owned": "Ownership"} | FILTER_FIELD_LABELS

PALETTE: tuple[str, ...] = (
    "#73c0ff",
    "#f0c040",
    "#66d9a3",
    "#ff8a65",
    "#ba9cff",
    "#4dd0e1",
    "#ffb74d",
    "#90caf9",
)


@dataclass(frozen=True, slots=True)
class DistributionRow:
    label: str
    count: int
    percent: float
    color: str


@dataclass(slots=True)
class SunburstNode:
    label: str
    value: float = 0.0
    children: list["SunburstNode"] = field(default_factory=list)
    color: str | None = None

    def total(self) -> float:
        child_total = sum(child.total() for child in self.children)
        return max(float(self.value or 0.0), child_total)


@dataclass(frozen=True, slots=True)
class _SunburstSegment:
    label: str
    path: str
    value: float
    depth: int
    start_angle: float
    span_angle: float
    inner_radius: float
    outer_radius: float
    color: str


def build_distribution(students: Sequence[Any], field_name: str) -> list[DistributionRow]:
    total = len(students)
    if total == 0:
        return []

    counts: Counter[str] = Counter()
    for student in students:
        if field_name == "owned":
            label = "Owned" if getattr(student, "owned", True) else "Unowned"
        else:
            value = get_student_value(student, field_name)
            label = format_filter_value(field_name, value) if value else "(Missing)"
        counts[label] += 1

    rows: list[DistributionRow] = []
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    for index, (label, count) in enumerate(ordered):
        rows.append(
            DistributionRow(
                label=label,
                count=count,
                percent=(count / total) * 100.0,
                color=PALETTE[index % len(PALETTE)],
            )
        )
    return rows


def _point_at(center: QPointF, radius: float, angle_degrees: float) -> QPointF:
    radians = math.radians(angle_degrees)
    return QPointF(center.x() + math.cos(radians) * radius, center.y() - math.sin(radians) * radius)


def _sector_path(
    center: QPointF,
    inner_radius: float,
    outer_radius: float,
    start_angle: float,
    span_angle: float,
) -> QPainterPath:
    outer_rect = QRectF(
        center.x() - outer_radius,
        center.y() - outer_radius,
        outer_radius * 2,
        outer_radius * 2,
    )
    inner_rect = QRectF(
        center.x() - inner_radius,
        center.y() - inner_radius,
        inner_radius * 2,
        inner_radius * 2,
    )
    end_angle = start_angle + span_angle
    path = QPainterPath()
    path.moveTo(_point_at(center, outer_radius, start_angle))
    path.arcTo(outer_rect, start_angle, span_angle)
    path.lineTo(_point_at(center, inner_radius, end_angle))
    path.arcTo(inner_rect, end_angle, -span_angle)
    path.closeSubpath()
    return path


def _mix_color(color: QColor, target: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    return QColor(
        int(color.red() + (target.red() - color.red()) * amount),
        int(color.green() + (target.green() - color.green()) * amount),
        int(color.blue() + (target.blue() - color.blue()) * amount),
    )


class SunburstWidget(QWidget):
    def __init__(self, ui_scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_scale = ui_scale
        self._root = SunburstNode("No data")
        self._segments: list[_SunburstSegment] = []
        self._hover_segment: _SunburstSegment | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(int(520 * ui_scale), int(430 * ui_scale))

    def setRoot(self, root: SunburstNode) -> None:
        self._root = root
        self._hover_segment = None
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#101a24"))

        rect = self.rect().adjusted(16, 14, -16, -14)
        size = min(rect.width(), rect.height())
        if size <= 24:
            return

        center = QPointF(rect.center())
        max_radius = size / 2
        root_total = self._root.total()
        self._segments = []

        if root_total <= 0 or not self._root.children:
            painter.setPen(QColor("#7b95aa"))
            painter.drawText(rect, Qt.AlignCenter, "No data available")
            return

        max_depth = self._max_depth(self._root)
        center_radius = max(42.0 * self._ui_scale, max_radius * 0.17)
        ring_width = max(34.0 * self._ui_scale, (max_radius - center_radius) / max(1, max_depth))

        self._draw_children(
            painter,
            self._root.children,
            center,
            1,
            90.0,
            -360.0,
            center_radius,
            ring_width,
            self._root.label,
        )
        self._draw_center(painter, center, center_radius, root_total)

    def mouseMoveEvent(self, event) -> None:
        segment = self._segment_at(event.position())
        if segment == self._hover_segment:
            return
        self._hover_segment = segment
        if segment is None:
            QToolTip.hideText()
            return
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f"{segment.path}\n{segment.value:,.0f}",
            self,
        )

    def leaveEvent(self, _event) -> None:
        self._hover_segment = None
        QToolTip.hideText()

    def _draw_children(
        self,
        painter: QPainter,
        nodes: Sequence[SunburstNode],
        center: QPointF,
        depth: int,
        start_angle: float,
        span_angle: float,
        center_radius: float,
        ring_width: float,
        parent_path: str,
    ) -> None:
        total = sum(node.total() for node in nodes)
        if total <= 0:
            return

        cursor = start_angle
        siblings = [node for node in nodes if node.total() > 0]
        for index, node in enumerate(siblings):
            node_total = node.total()
            node_span = span_angle * (node_total / total)
            color = self._node_color(node, index, depth)
            inner_radius = center_radius + (depth - 1) * ring_width
            outer_radius = inner_radius + ring_width - max(2.0, 2.0 * self._ui_scale)
            path = _sector_path(center, inner_radius, outer_radius, cursor, node_span)

            painter.setPen(QPen(QColor("#101a24"), max(1, int(1.2 * self._ui_scale))))
            painter.setBrush(QColor(color))
            painter.drawPath(path)

            segment_path = f"{parent_path} > {node.label}"
            self._segments.append(
                _SunburstSegment(
                    label=node.label,
                    path=segment_path,
                    value=node_total,
                    depth=depth,
                    start_angle=cursor,
                    span_angle=node_span,
                    inner_radius=inner_radius,
                    outer_radius=outer_radius,
                    color=color,
                )
            )
            self._draw_label(painter, center, inner_radius, outer_radius, cursor, node_span, node.label)
            if node.children:
                self._draw_children(
                    painter,
                    node.children,
                    center,
                    depth + 1,
                    cursor,
                    node_span,
                    center_radius,
                    ring_width,
                    segment_path,
                )
            cursor += node_span

    def _draw_center(self, painter: QPainter, center: QPointF, radius: float, root_total: float) -> None:
        painter.setPen(QPen(QColor("#26384b"), max(1, int(1.2 * self._ui_scale))))
        painter.setBrush(QColor("#0b1118"))
        painter.drawEllipse(center, radius - 3, radius - 3)

        title_font = QFont()
        title_font.setPointSizeF(max(8.0, 10.5 * self._ui_scale))
        title_font.setBold(True)
        value_font = QFont()
        value_font.setPointSizeF(max(9.0, 13.0 * self._ui_scale))
        value_font.setBold(True)

        text_rect = QRectF(center.x() - radius * 0.86, center.y() - radius * 0.52, radius * 1.72, radius * 1.04)
        painter.setPen(QColor("#7b95aa"))
        painter.setFont(title_font)
        painter.drawText(text_rect.adjusted(0, -8 * self._ui_scale, 0, 0), Qt.AlignCenter, self._root.label)
        painter.setPen(QColor("#d8e7f3"))
        painter.setFont(value_font)
        painter.drawText(text_rect.adjusted(0, 14 * self._ui_scale, 0, 0), Qt.AlignCenter, f"{root_total:,.0f}")

    def _draw_label(
        self,
        painter: QPainter,
        center: QPointF,
        inner_radius: float,
        outer_radius: float,
        start_angle: float,
        span_angle: float,
        label: str,
    ) -> None:
        if abs(span_angle) < 13.0:
            return
        middle_angle = start_angle + span_angle / 2.0
        radius = (inner_radius + outer_radius) / 2.0
        point = _point_at(center, radius, middle_angle)
        font = QFont()
        font.setPointSizeF(max(7.0, 8.0 * self._ui_scale))
        font.setBold(abs(span_angle) > 34.0)
        metrics = QFontMetrics(font)
        max_width = max(24, int((abs(span_angle) / 360.0) * 2.0 * math.pi * radius * 0.72))
        text = metrics.elidedText(label, Qt.ElideRight, max_width)
        text_rect = QRectF(point.x() - max_width / 2, point.y() - 9 * self._ui_scale, max_width, 18 * self._ui_scale)
        painter.setFont(font)
        painter.setPen(QColor("#f2f6fb"))
        painter.drawText(text_rect, Qt.AlignCenter, text)

    def _segment_at(self, point: QPointF) -> _SunburstSegment | None:
        rect = self.rect()
        center = QPointF(rect.center())
        dx = point.x() - center.x()
        dy = center.y() - point.y()
        radius = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(dy, dx))
        if angle < 0:
            angle += 360.0

        for segment in reversed(self._segments):
            if not (segment.inner_radius <= radius <= segment.outer_radius):
                continue
            if self._angle_in_segment(angle, segment.start_angle, segment.span_angle):
                return segment
        return None

    @staticmethod
    def _angle_in_segment(angle: float, start: float, span: float) -> bool:
        end = start + span
        if span < 0:
            start, end = end, start
        angle = angle % 360.0
        start = start % 360.0
        end = end % 360.0
        if start <= end:
            return start <= angle <= end
        return angle >= start or angle <= end

    @staticmethod
    def _max_depth(node: SunburstNode) -> int:
        if not node.children:
            return 0
        return 1 + max(SunburstWidget._max_depth(child) for child in node.children)

    @staticmethod
    def _node_color(node: SunburstNode, index: int, depth: int) -> str:
        if node.color:
            return node.color
        base = QColor(PALETTE[index % len(PALETTE)])
        if depth > 1:
            base = _mix_color(base, QColor("#ffffff"), min(0.22, depth * 0.055))
        return base.name()


class DonutWidget(QWidget):
    def __init__(self, percent: float, color: str, center_text: str, ui_scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._percent = percent
        self._color = QColor(color)
        self._center_text = center_text
        self._ui_scale = ui_scale
        self.setMinimumSize(int(116 * ui_scale), int(116 * ui_scale))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(8, 8, -8, -8)
        size = min(rect.width(), rect.height())
        square = QRectF(
            rect.center().x() - size / 2,
            rect.center().y() - size / 2,
            size,
            size,
        )
        thickness = max(8, int(14 * self._ui_scale))

        track_pen = QPen(QColor("#223241"), thickness)
        track_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(square, 0, 360 * 16)

        value_pen = QPen(self._color, thickness)
        value_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(value_pen)
        painter.drawArc(square, 90 * 16, int(-self._percent / 100.0 * 360 * 16))

        painter.setPen(QColor("#d8e7f3"))
        font = QFont()
        font.setPointSizeF(max(8.0, 11.0 * self._ui_scale))
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(square, Qt.AlignCenter, self._center_text)


class StatsDialog(QDialog):
    def __init__(self, parent: QWidget, students: Sequence[Any], ui_scale: float) -> None:
        super().__init__(parent)
        self._students = list(students)
        self._ui_scale = ui_scale
        self._rows: list[DistributionRow] = []
        self.setWindowTitle("Student Statistics")
        self.resize(int(1120 * ui_scale), int(860 * ui_scale))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(int(18 * ui_scale), int(18 * ui_scale), int(18 * ui_scale), int(18 * ui_scale))
        layout.setSpacing(int(12 * ui_scale))

        header = QFrame()
        header.setObjectName("statsHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(int(16 * ui_scale), int(16 * ui_scale), int(16 * ui_scale), int(16 * ui_scale))
        header_layout.setSpacing(int(12 * ui_scale))

        title_wrap = QVBoxLayout()
        title = QLabel("Statistics")
        title.setObjectName("statsTitle")
        subtitle = QLabel("Distribution is based on the students currently visible in the viewer.")
        subtitle.setObjectName("statsSub")
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)
        header_layout.addLayout(title_wrap, 1)

        header_layout.addWidget(QLabel("Attribute"))
        self._field_combo = QComboBox()
        for field_name in STAT_FIELDS:
            self._field_combo.addItem(STAT_FIELD_LABELS[field_name], field_name)
        self._field_combo.currentIndexChanged.connect(self._refresh)
        header_layout.addWidget(self._field_combo)
        layout.addWidget(header)

        self._summary = QLabel("")
        self._summary.setObjectName("statsSummary")
        layout.addWidget(self._summary)

        body = QHBoxLayout()
        body.setSpacing(int(12 * ui_scale))
        layout.addLayout(body, 1)

        left = QFrame()
        left.setObjectName("statsPanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(int(14 * ui_scale), int(14 * ui_scale), int(14 * ui_scale), int(14 * ui_scale))
        left_layout.setSpacing(int(10 * ui_scale))
        left_layout.addWidget(QLabel("Top segments"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._card_host = QWidget()
        self._card_grid = QGridLayout(self._card_host)
        self._card_grid.setContentsMargins(0, 0, 0, 0)
        self._card_grid.setHorizontalSpacing(int(10 * ui_scale))
        self._card_grid.setVerticalSpacing(int(10 * ui_scale))
        scroll.setWidget(self._card_host)
        left_layout.addWidget(scroll, 1)
        body.addWidget(left, 3)

        right = QFrame()
        right.setObjectName("statsPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(int(14 * ui_scale), int(14 * ui_scale), int(14 * ui_scale), int(14 * ui_scale))
        right_layout.setSpacing(int(10 * ui_scale))
        right_layout.addWidget(QLabel("All values"))

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Value", "Students", "Percent"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.NoSelection)
        self._table.setFocusPolicy(Qt.NoFocus)
        self._table.horizontalHeader().setStretchLastSection(True)
        right_layout.addWidget(self._table, 1)

        plan_panel = QFrame()
        plan_panel.setObjectName("planPanel")
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(int(12 * ui_scale), int(12 * ui_scale), int(12 * ui_scale), int(12 * ui_scale))
        plan_layout.setSpacing(int(6 * ui_scale))
        plan_title = QLabel("Plan progress")
        plan_title.setObjectName("planTitle")
        plan_layout.addWidget(plan_title)
        plan_layout.addWidget(QLabel("This space is reserved for future goal tracking."))
        plan_layout.addWidget(QLabel("Once the planning window exists, we can show target completion here."))
        right_layout.addWidget(plan_panel)
        body.addWidget(right, 2)

        self.setStyleSheet(
            f"""
            QDialog, QWidget {{ background: #0b1118; color: #d8e7f3; }}
            QFrame#statsHeader, QFrame#statsPanel, QFrame#planPanel {{
                background: #101a24;
                border: 1px solid #1b2a38;
                border-radius: {int(14 * ui_scale)}px;
            }}
            QLabel#statsTitle {{ font-size: {int(22 * ui_scale)}px; font-weight: 700; color: #73c0ff; }}
            QLabel#statsSub, QLabel#statsSummary {{ color: #7b95aa; }}
            QLabel#planTitle {{ font-size: {int(15 * ui_scale)}px; font-weight: 700; color: #84d0ff; }}
            QComboBox, QTableWidget {{
                background: #16212d;
                border: 1px solid #243648;
                border-radius: {int(9 * ui_scale)}px;
                padding: {int(6 * ui_scale)}px;
            }}
            QHeaderView::section {{
                background: #16212d;
                color: #7b95aa;
                border: 0;
                padding: {int(6 * ui_scale)}px;
            }}
            """
        )

        self._refresh()

    def _refresh(self) -> None:
        field_name = self._field_combo.currentData()
        self._rows = build_distribution(self._students, field_name)
        total = sum(row.count for row in self._rows)
        self._summary.setText(f"{STAT_FIELD_LABELS[field_name]} distribution across {total} students")
        self._rebuild_cards()
        self._rebuild_table()

    def _rebuild_cards(self) -> None:
        while self._card_grid.count():
            item = self._card_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for index, row in enumerate(self._rows[:6]):
            card = QFrame()
            card.setObjectName("statsPanel")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(int(12 * self._ui_scale), int(12 * self._ui_scale), int(12 * self._ui_scale), int(12 * self._ui_scale))
            card_layout.setSpacing(int(8 * self._ui_scale))
            donut = DonutWidget(row.percent, row.color, f"{row.percent:.1f}%", self._ui_scale)
            card_layout.addWidget(donut, 0, Qt.AlignCenter)

            label = QLabel(row.label)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignCenter)
            card_layout.addWidget(label)

            count = QLabel(f"{row.count} students")
            count.setAlignment(Qt.AlignCenter)
            count.setStyleSheet("color: #7b95aa;")
            card_layout.addWidget(count)
            self._card_grid.addWidget(card, index // 3, index % 3)

    def _rebuild_table(self) -> None:
        self._table.setRowCount(len(self._rows))
        for row_index, row in enumerate(self._rows):
            label_item = QTableWidgetItem(row.label)
            count_item = QTableWidgetItem(str(row.count))
            percent_item = QTableWidgetItem(f"{row.percent:.1f}%")
            label_item.setForeground(QColor(row.color))
            count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            percent_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row_index, 0, label_item)
            self._table.setItem(row_index, 1, count_item)
            self._table.setItem(row_index, 2, percent_item)
        self._table.resizeColumnsToContents()
