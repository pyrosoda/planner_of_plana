from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QListWidget, QScrollArea, QSizePolicy, QWidget


@dataclass(slots=True)
class ParallelogramCardStyle:
    asset_path: Path
    outer_margin: int = 0
    hit_alpha_threshold: int = 8
    outline_ratio: float = 0.02
    outline_color: QColor = field(default_factory=lambda: QColor(255, 255, 255, 84))
    hover_overlay: QColor = field(default_factory=lambda: QColor(255, 255, 255, 18))
    selected_overlay: QColor = field(default_factory=lambda: QColor(242, 102, 179, 58))
    selected_glow: QColor = field(default_factory=lambda: QColor(242, 102, 179, 76))
    name_panel_color: QColor = field(default_factory=lambda: QColor(10, 12, 18, 196))
    name_text_color: QColor = field(default_factory=lambda: QColor("#f2f2f2"))
    unowned_overlay: QColor = field(default_factory=lambda: QColor(6, 8, 14, 118))
    grid_overlap_x: int = 18
    grid_gap_x: int = 6
    grid_gap_y: int = 10
    panel_height: int = 32
    panel_bottom: int = 10
    panel_padding_x: int = 10
    divider_height: int = 4
    unowned_badge_width: int = 68
    unowned_badge_height: int = 22
    unowned_badge_top: int = 12
    unowned_badge_inset_left: int = 24
    unowned_badge_inset_right: int = 16


def build_card_style(asset_path: str | Path, ui_scale: float = 1.0) -> ParallelogramCardStyle:
    scale = max(0.8, float(ui_scale))
    return ParallelogramCardStyle(
        asset_path=Path(asset_path),
        outer_margin=0,
        grid_overlap_x=max(8, int(round(18 * scale))),
        grid_gap_x=max(2, int(round(6 * scale))),
        grid_gap_y=max(6, int(round(10 * scale))),
        panel_height=max(24, int(round(32 * scale))),
        panel_bottom=max(6, int(round(10 * scale))),
        panel_padding_x=max(8, int(round(10 * scale))),
        divider_height=max(3, int(round(4 * scale))),
        unowned_badge_width=max(54, int(round(68 * scale))),
        unowned_badge_height=max(18, int(round(22 * scale))),
        unowned_badge_top=max(8, int(round(12 * scale))),
        unowned_badge_inset_left=max(16, int(round(24 * scale))),
        unowned_badge_inset_right=max(10, int(round(16 * scale))),
    )


class ParallelogramCardAsset:
    _image_cache: dict[Path, QImage] = {}

    def __init__(self, style: ParallelogramCardStyle) -> None:
        self._style = style
        self._base = self._load_image(style.asset_path)
        self._scaled_cache: dict[tuple[int, int], QImage] = {}
        self._row_bounds_cache: dict[tuple[int, int], list[tuple[int, int]]] = {}
        self._outline_cache: dict[tuple[int, int, int], QImage] = {}
        self._mask_cache: dict[tuple[int, int], QImage] = {}

    @property
    def style(self) -> ParallelogramCardStyle:
        return self._style

    @property
    def aspect_ratio(self) -> float:
        return self._base.width() / max(1, self._base.height())

    @property
    def base_size(self) -> QSize:
        return self._base.size()

    def row_bounds(self, size: QSize, y: int) -> tuple[int, int]:
        bounds = self._row_bounds(size)
        if not bounds:
            return 0, max(0, size.width() - 1)
        return bounds[max(0, min(len(bounds) - 1, y))]

    def card_rect(self, item_rect: QRect) -> QRect:
        margin = self._style.outer_margin
        return item_rect.adjusted(margin, margin, -margin, -margin)

    def contains(self, card_size: QSize, local_pos: QPoint) -> bool:
        if (
            card_size.width() <= 0
            or card_size.height() <= 0
            or local_pos.x() < 0
            or local_pos.y() < 0
            or local_pos.x() >= card_size.width()
            or local_pos.y() >= card_size.height()
        ):
            return False

        source_x = min(self._base.width() - 1, int(local_pos.x() * self._base.width() / card_size.width()))
        source_y = min(self._base.height() - 1, int(local_pos.y() * self._base.height() / card_size.height()))
        return self._base.pixelColor(source_x, source_y).alpha() >= self._style.hit_alpha_threshold

    def background(self, card_size: QSize, *, hovered: bool, selected: bool) -> QImage:
        result = QImage(self._scaled_asset(card_size))
        painter = QPainter(result)
        if hovered:
            painter.setCompositionMode(QPainter.CompositionMode_Screen)
            painter.fillRect(result.rect(), self._style.hover_overlay)
        if selected:
            painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            painter.fillRect(result.rect(), self._style.selected_overlay)
            glow = QLinearGradient(0, 0, 0, result.height())
            glow.setColorAt(0.0, self._style.selected_glow)
            glow.setColorAt(0.36, QColor(255, 255, 255, 0))
            painter.setCompositionMode(QPainter.CompositionMode_Screen)
            painter.fillRect(result.rect(), glow)
        painter.end()
        return result

    def apply_alpha_mask(self, image: QImage) -> QImage:
        result = QImage(image)
        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, self._scaled_asset(image.size()))
        painter.end()
        return result

    def masked_fill(self, size: QSize, color: QColor) -> QImage:
        image = QImage(size, QImage.Format_ARGB32_Premultiplied)
        image.fill(color)
        return self.apply_alpha_mask(image)

    def mask_image(self, size: QSize) -> QImage:
        key = (size.width(), size.height())
        cached = self._mask_cache.get(key)
        if cached is not None:
            return cached

        scaled = self._scaled_asset(size)
        mask = QImage(size, QImage.Format_ARGB32_Premultiplied)
        mask.fill(Qt.transparent)
        for y in range(size.height()):
            for x in range(size.width()):
                if scaled.pixelColor(x, y).alpha() >= self._style.hit_alpha_threshold:
                    mask.setPixelColor(x, y, QColor(255, 255, 255, 255))
        self._mask_cache[key] = mask
        return mask

    def outline(self, size: QSize) -> QImage:
        thickness = max(1, int(round(min(size.width(), size.height()) * self._style.outline_ratio)))
        key = (size.width(), size.height(), thickness)
        cached = self._outline_cache.get(key)
        if cached is not None:
            return cached

        scaled = self._scaled_asset(size)
        outline = QImage(size, QImage.Format_ARGB32_Premultiplied)
        outline.fill(Qt.transparent)
        for y in range(size.height()):
            for x in range(size.width()):
                if scaled.pixelColor(x, y).alpha() < self._style.hit_alpha_threshold:
                    continue
                is_edge = False
                for dy in range(-thickness, thickness + 1):
                    for dx in range(-thickness, thickness + 1):
                        if max(abs(dx), abs(dy)) > thickness:
                            continue
                        nx = x + dx
                        ny = y + dy
                        if (
                            nx < 0
                            or ny < 0
                            or nx >= size.width()
                            or ny >= size.height()
                            or scaled.pixelColor(nx, ny).alpha() < self._style.hit_alpha_threshold
                        ):
                            is_edge = True
                            break
                    if is_edge:
                        break
                if is_edge:
                    outline.setPixelColor(x, y, self._style.outline_color)

        self._outline_cache[key] = outline
        return outline

    def _scaled_asset(self, size: QSize) -> QImage:
        key = (size.width(), size.height())
        cached = self._scaled_cache.get(key)
        if cached is not None:
            return cached
        image = self._base.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._scaled_cache[key] = image
        return image

    def _row_bounds(self, size: QSize) -> list[tuple[int, int]]:
        key = (size.width(), size.height())
        cached = self._row_bounds_cache.get(key)
        if cached is not None:
            return cached

        image = self._scaled_asset(size)
        bounds: list[tuple[int, int]] = []
        for y in range(image.height()):
            left = None
            right = None
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() >= self._style.hit_alpha_threshold:
                    if left is None:
                        left = x
                    right = x
            if left is None or right is None:
                bounds.append((0, max(0, image.width() - 1)))
            else:
                bounds.append((left, right))
        self._row_bounds_cache[key] = bounds
        return bounds

    @classmethod
    def _load_image(cls, path: Path) -> QImage:
        resolved = Path(path).resolve()
        cached = cls._image_cache.get(resolved)
        if cached is not None:
            return cached
        image = QImage(str(resolved))
        if image.isNull():
            raise FileNotFoundError(f"Unable to load card asset: {resolved}")
        cls._image_cache[resolved] = image
        return image


class MaskedCardListWidget(QListWidget):
    def __init__(self, card_asset: ParallelogramCardAsset, parent=None) -> None:
        super().__init__(parent)
        self._card_asset = card_asset

    def mousePressEvent(self, event) -> None:
        if not self._accepts_viewport_point(event.position().toPoint()):
            event.ignore()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if not self._accepts_viewport_point(event.position().toPoint()):
            event.ignore()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._accepts_viewport_point(event.position().toPoint()):
            event.ignore()
            return
        super().mouseDoubleClickEvent(event)

    def _accepts_viewport_point(self, viewport_pos: QPoint) -> bool:
        item = self.itemAt(viewport_pos)
        if item is None:
            return True
        card_rect = self._card_asset.card_rect(self.visualItemRect(item))
        if not card_rect.contains(viewport_pos):
            return False
        local_pos = viewport_pos - card_rect.topLeft()
        return self._card_asset.contains(card_rect.size(), local_pos)


class StudentCardWidget(QWidget):
    clicked = Signal(str)
    double_clicked = Signal(str)

    def __init__(
        self,
        *,
        card_asset: ParallelogramCardAsset,
        student_id: str,
        title: str,
        owned: bool,
        divider_left: QColor,
        divider_right: QColor,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._card_asset = card_asset
        self.student_id = student_id
        self._title = title
        self._owned = owned
        self._divider_left = divider_left
        self._divider_right = divider_right
        self._selected = False
        self._hovered = False
        self._pressed = False
        self._pixmap = QPixmap()
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def setPixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def setSelected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.update()

    def sizeHint(self) -> QSize:
        return self._card_asset.base_size

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_mask()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._hovered = True
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hovered = False
        self._pressed = False
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._card_asset.contains(self.size(), event.position().toPoint()):
            self._pressed = True
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        was_pressed = self._pressed
        self._pressed = False
        self.update()
        if (
            was_pressed
            and event.button() == Qt.LeftButton
            and self._card_asset.contains(self.size(), event.position().toPoint())
        ):
            self.clicked.emit(self.student_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._card_asset.contains(self.size(), event.position().toPoint()):
            self.double_clicked.emit(self.student_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _update_mask(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        mask = self._card_asset.mask_image(self.size())
        self.setMask(QPixmap.fromImage(mask).mask())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        size = self.size()
        shadow_alpha = 72 if self._selected else 40 if self._hovered else 0
        if shadow_alpha:
            shadow = self._card_asset.masked_fill(size, QColor(0, 0, 0, shadow_alpha))
            painter.drawImage(QPoint(0, 4), shadow)

        card_image = QImage(size, QImage.Format_ARGB32_Premultiplied)
        card_image.fill(Qt.transparent)
        card_painter = QPainter(card_image)
        card_painter.setRenderHint(QPainter.Antialiasing, True)
        card_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        card_painter.drawImage(0, 0, self._card_asset.background(size, hovered=self._hovered, selected=self._selected))
        self._paint_portrait(card_painter)
        card_painter.drawImage(0, 0, self._card_asset.outline(size))
        self._paint_name_panel(card_painter)
        if not self._owned:
            card_painter.fillRect(card_image.rect(), self._card_asset.style.unowned_overlay)
            self._paint_unowned_badge(card_painter)
        card_painter.end()

        painter.drawImage(self.rect(), self._card_asset.apply_alpha_mask(card_image))
        painter.end()

    def _paint_portrait(self, painter: QPainter) -> None:
        if self._pixmap.isNull():
            return
        target_width = self.width()
        scaled = self._pixmap.scaledToWidth(target_width, Qt.SmoothTransformation)
        if scaled.height() < self.height():
            scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    def _paint_name_panel(self, painter: QPainter) -> None:
        style = self._card_asset.style
        panel_height = min(style.panel_height, max(20, self.height() // 3))
        panel_top = max(0, self.height() - panel_height - style.panel_bottom)
        panel_bottom = min(self.height() - 1, panel_top + panel_height)

        left_top, right_top = self._card_asset.row_bounds(self.size(), panel_top)
        left_bottom, right_bottom = self._card_asset.row_bounds(self.size(), panel_bottom)
        panel_path = QPainterPath()
        panel_path.moveTo(left_top, panel_top)
        panel_path.lineTo(right_top, panel_top)
        panel_path.lineTo(right_bottom, panel_bottom)
        panel_path.lineTo(left_bottom, panel_bottom)
        panel_path.closeSubpath()

        divider_h = style.divider_height
        divider_top = max(0, panel_top - divider_h)
        div_left_a, div_right_a = self._card_asset.row_bounds(self.size(), divider_top)
        div_left_b, div_right_b = self._card_asset.row_bounds(self.size(), panel_top)
        divider_mid_top = (div_left_a + div_right_a) // 2
        divider_mid_bottom = (div_left_b + div_right_b) // 2

        left_divider = QPainterPath()
        left_divider.moveTo(div_left_a, divider_top)
        left_divider.lineTo(divider_mid_top, divider_top)
        left_divider.lineTo(divider_mid_bottom, panel_top)
        left_divider.lineTo(div_left_b, panel_top)
        left_divider.closeSubpath()

        right_divider = QPainterPath()
        right_divider.moveTo(divider_mid_top, divider_top)
        right_divider.lineTo(div_right_a, divider_top)
        right_divider.lineTo(div_right_b, panel_top)
        right_divider.lineTo(divider_mid_bottom, panel_top)
        right_divider.closeSubpath()

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._divider_left)
        painter.drawPath(left_divider)
        painter.setBrush(self._divider_right)
        painter.drawPath(right_divider)
        painter.setBrush(style.name_panel_color)
        painter.drawPath(panel_path)

        text_left = max(left_top, left_bottom) + style.panel_padding_x
        text_right = min(right_top, right_bottom) - style.panel_padding_x
        text_rect = QRect(text_left, panel_top + 4, max(1, text_right - text_left), max(1, panel_height - 6))
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(8.4, min(self.width(), self.height()) * 0.042))
        painter.setFont(font)
        painter.setPen(style.name_text_color)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextSingleLine, self._title)

    def _paint_unowned_badge(self, painter: QPainter) -> None:
        style = self._card_asset.style
        badge_y = style.unowned_badge_top
        left_bound, right_bound = self._card_asset.row_bounds(
            self.size(),
            min(self.height() - 1, badge_y + style.unowned_badge_height // 2),
        )
        badge_x = max(style.unowned_badge_inset_left, left_bound + style.unowned_badge_inset_left)
        available_width = max(
            32,
            right_bound - badge_x - style.unowned_badge_inset_right,
        )
        badge_rect = QRect(
            badge_x,
            badge_y,
            min(style.unowned_badge_width, available_width),
            style.unowned_badge_height,
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(6, 8, 14, 186))
        painter.drawRoundedRect(badge_rect, 10, 10)
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(7.2, min(self.width(), self.height()) * 0.034))
        painter.setFont(font)
        painter.setPen(self._card_asset.style.name_text_color)
        painter.drawText(badge_rect, Qt.AlignCenter, "UNOWNED")


class ParallelogramCardGrid(QScrollArea):
    current_changed = Signal(object, object)
    card_double_clicked = Signal(str)
    layout_changed = Signal(int, int)

    def __init__(self, card_asset: ParallelogramCardAsset, ui_scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card_asset = card_asset
        self._ui_scale = ui_scale
        self._content = QWidget()
        self._content.setAttribute(Qt.WA_StyledBackground, True)
        self.setWidget(self._content)
        self.setWidgetResizable(False)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards: list[StudentCardWidget] = []
        self._card_by_id: dict[str, StudentCardWidget] = {}
        self._current_id: str | None = None
        self._base_size = card_asset.base_size
        self._min_card_width = max(160, int(round(self._base_size.width() * max(0.72, min(1.0, ui_scale)))))
        self._current_card_size = QSize(self._base_size)

    def clear_cards(self) -> None:
        self._current_id = None
        self._card_by_id.clear()
        while self._cards:
            card = self._cards.pop()
            card.deleteLater()
        self._content.resize(0, 0)
        self.viewport().update()

    def add_card(self, card: StudentCardWidget) -> None:
        card.setParent(self._content)
        card.clicked.connect(self.set_current_card)
        card.double_clicked.connect(self.card_double_clicked)
        card.show()
        self._cards.append(card)
        self._card_by_id[card.student_id] = card
        self._relayout()

    def current_card_id(self) -> str | None:
        return self._current_id

    def set_current_card(self, student_id: str | None) -> None:
        if student_id == self._current_id:
            return
        previous = self._current_id
        if previous in self._card_by_id:
            self._card_by_id[previous].setSelected(False)
        self._current_id = student_id
        if student_id in self._card_by_id:
            card = self._card_by_id[student_id]
            card.setSelected(True)
            self.ensureVisible(card.x(), card.y(), card.width(), card.height())
        self.current_changed.emit(student_id, previous)

    def card(self, student_id: str) -> StudentCardWidget | None:
        return self._card_by_id.get(student_id)

    def set_card_pixmap(self, student_id: str, pixmap: QPixmap) -> None:
        card = self._card_by_id.get(student_id)
        if card is not None:
            card.setPixmap(pixmap)

    def current_card_size(self) -> QSize:
        return QSize(self._current_card_size)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        if not self._cards:
            return
        available_width = max(1, self.viewport().width())
        overlap_x = self._card_asset.style.grid_overlap_x
        gap_x = self._card_asset.style.grid_gap_x
        gap_y = self._card_asset.style.grid_gap_y
        shared_overlap = max(0, overlap_x - gap_x)

        columns = 1
        while True:
            next_columns = columns + 1
            candidate_width = (available_width + shared_overlap * (next_columns - 1)) // next_columns
            if candidate_width < self._min_card_width:
                break
            columns = next_columns

        card_width = max(self._min_card_width, (available_width + shared_overlap * (columns - 1)) // columns)
        card_height = max(1, int(round(card_width / self._card_asset.aspect_ratio)))
        advance_x = max(1, card_width - shared_overlap)

        if card_width != self._current_card_size.width() or card_height != self._current_card_size.height():
            self._current_card_size = QSize(card_width, card_height)
            self.layout_changed.emit(card_width, card_height)

        for index, card in enumerate(self._cards):
            row = index // columns
            col = index % columns
            x = col * advance_x
            y = row * (card_height + gap_y)
            card.setGeometry(x, y, card_width, card_height)
            card.raise_()

        rows = (len(self._cards) + columns - 1) // columns
        content_width = card_width + max(0, columns - 1) * advance_x
        content_height = rows * card_height + max(0, rows - 1) * gap_y
        self._content.resize(content_width, content_height)
