from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QSizePolicy, QWidget


@dataclass(slots=True)
class ParallelogramCardStyle:
    asset_path: Path
    outer_margin: int = 0
    hit_alpha_threshold: int = 8
    outline_enabled: bool = True
    outline_ratio: float = 0.02
    outline_color: QColor = field(default_factory=lambda: QColor(255, 255, 255, 84))
    hover_overlay: QColor = field(default_factory=lambda: QColor(255, 255, 255, 18))
    selected_overlay: QColor = field(default_factory=lambda: QColor(242, 102, 179, 92))
    selected_glow: QColor = field(default_factory=lambda: QColor(255, 184, 221, 148))
    selected_shadow: QColor = field(default_factory=lambda: QColor(242, 102, 179, 120))
    selected_expand: int = 10
    selected_lift_y: int = 4
    name_panel_color: QColor = field(default_factory=lambda: QColor(10, 12, 18, 196))
    name_text_color: QColor = field(default_factory=lambda: QColor("#f2f2f2"))
    unowned_overlay: QColor = field(default_factory=lambda: QColor(6, 8, 14, 118))
    grid_overlap_x: int = 18
    grid_gap_x: int = 6
    grid_gap_y: int = 10
    grid_edge_padding: int = 4
    panel_height: int = 36
    panel_bottom: int = 0
    panel_padding_x: int = 10
    divider_height: int = 4
    unowned_badge_width: int = 68
    unowned_badge_height: int = 22
    unowned_badge_top: int = 12
    unowned_badge_inset_left: int = 12
    unowned_badge_inset_right: int = 16


def build_card_style(asset_path: str | Path, ui_scale: float = 1.0) -> ParallelogramCardStyle:
    scale = max(0.8, float(ui_scale))
    return ParallelogramCardStyle(
        asset_path=Path(asset_path),
        outer_margin=0,
        outline_enabled=False,
        grid_overlap_x=max(8, int(round(18 * scale))),
        grid_gap_x=max(2, int(round(6 * scale))),
        grid_gap_y=max(6, int(round(10 * scale))),
        grid_edge_padding=max(2, int(round(4 * scale))),
        selected_expand=max(6, int(round(10 * scale))),
        selected_lift_y=max(2, int(round(4 * scale))),
        panel_height=max(28, int(round(36 * scale))),
        panel_bottom=0,
        panel_padding_x=max(8, int(round(10 * scale))),
        divider_height=max(3, int(round(4 * scale))),
        unowned_badge_width=max(54, int(round(68 * scale))),
        unowned_badge_height=max(18, int(round(22 * scale))),
        unowned_badge_top=max(8, int(round(12 * scale))),
        unowned_badge_inset_left=max(8, int(round(12 * scale))),
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
        if not self._style.outline_enabled:
            key = (size.width(), size.height(), 0)
            cached = self._outline_cache.get(key)
            if cached is not None:
                return cached
            outline = QImage(size, QImage.Format_ARGB32_Premultiplied)
            outline.fill(Qt.transparent)
            self._outline_cache[key] = outline
            return outline

        thickness = max(1, int(round(min(size.width(), size.height()) * self._style.outline_ratio)))
        key = (size.width(), size.height(), thickness)
        cached = self._outline_cache.get(key)
        if cached is not None:
            return cached

        outline = QImage(size, QImage.Format_ARGB32_Premultiplied)
        outline.fill(Qt.transparent)
        rows = self._row_bounds(size)
        top_y = 0
        bottom_y = max(0, size.height() - 1)
        left_top, right_top = rows[top_y]
        left_bottom, right_bottom = rows[bottom_y]

        path = QPainterPath()
        path.moveTo(left_top + 0.5, top_y + 0.5)
        path.lineTo(right_top + 0.5, top_y + 0.5)
        path.lineTo(right_bottom + 0.5, bottom_y + 0.5)
        path.lineTo(left_bottom + 0.5, bottom_y + 0.5)
        path.closeSubpath()

        painter = QPainter(outline)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(self._style.outline_color, thickness)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
        painter.end()

        outline = self.apply_alpha_mask(outline)

        self._outline_cache[key] = outline
        return outline

    def _scaled_asset(self, size: QSize) -> QImage:
        key = (size.width(), size.height())
        cached = self._scaled_cache.get(key)
        if cached is not None:
            return cached
        image = QImage(size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        scaled = self._base.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(image)
        painter.drawImage((size.width() - scaled.width()) // 2, (size.height() - scaled.height()) // 2, scaled)
        painter.end()
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
        show_name_panel: bool = True,
        show_unowned_badge: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._card_asset = card_asset
        self.student_id = student_id
        self._title = title
        self._owned = owned
        self._divider_left = divider_left
        self._divider_right = divider_right
        self._show_name_panel = show_name_panel
        self._show_unowned_badge = show_unowned_badge
        self._selected = False
        self._hovered = False
        self._pressed = False
        self._drag_hidden = False
        self._pixmap = QPixmap()
        self._scaled_portrait = QPixmap()
        self._scaled_portrait_key: tuple[int, int, int] | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def setData(self, *, title: str, owned: bool, divider_left: QColor, divider_right: QColor) -> None:
        if (
            self._title == title
            and self._owned == owned
            and self._divider_left == divider_left
            and self._divider_right == divider_right
        ):
            return
        self._title = title
        self._owned = owned
        self._divider_left = divider_left
        self._divider_right = divider_right
        self.update()

    def setDisplayOptions(self, *, show_name_panel: bool | None = None, show_unowned_badge: bool | None = None) -> None:
        changed = False
        if show_name_panel is not None and self._show_name_panel != show_name_panel:
            self._show_name_panel = show_name_panel
            changed = True
        if show_unowned_badge is not None and self._show_unowned_badge != show_unowned_badge:
            self._show_unowned_badge = show_unowned_badge
            changed = True
        if changed:
            self.update()

    def setPixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self._scaled_portrait = QPixmap()
        self._scaled_portrait_key = None
        self.update()

    def setSelected(self, selected: bool) -> None:
        if self._selected == selected:
            return
        self._selected = selected
        self.update()

    def setDragHidden(self, hidden: bool) -> None:
        if self._drag_hidden == hidden:
            return
        self._drag_hidden = hidden
        self.update()

    def sizeHint(self) -> QSize:
        return self._card_asset.base_size

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scaled_portrait = QPixmap()
        self._scaled_portrait_key = None
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
        if self._drag_hidden:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        size = self.size()
        if self._selected:
            glow_shadow = self._card_asset.masked_fill(size, self._card_asset.style.selected_shadow)
            painter.drawImage(QPoint(0, 2), glow_shadow)
            shadow = self._card_asset.masked_fill(size, QColor(0, 0, 0, 86))
            painter.drawImage(QPoint(0, 5), shadow)
        elif self._hovered:
            shadow = self._card_asset.masked_fill(size, QColor(0, 0, 0, 40))
            painter.drawImage(QPoint(0, 4), shadow)

        card_image = QImage(size, QImage.Format_ARGB32_Premultiplied)
        card_image.fill(Qt.transparent)
        card_painter = QPainter(card_image)
        card_painter.setRenderHint(QPainter.Antialiasing, True)
        card_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        card_painter.drawImage(0, 0, self._card_asset.background(size, hovered=self._hovered, selected=self._selected))
        self._paint_portrait(card_painter)
        card_painter.drawImage(0, 0, self._card_asset.outline(size))
        if self._show_name_panel:
            self._paint_name_panel(card_painter)
        if self._selected:
            sheen = QLinearGradient(0, 0, 0, size.height())
            sheen.setColorAt(0.0, QColor(255, 255, 255, 54))
            sheen.setColorAt(0.22, QColor(255, 255, 255, 14))
            sheen.setColorAt(0.6, QColor(255, 255, 255, 0))
            card_painter.setCompositionMode(QPainter.CompositionMode_Screen)
            card_painter.fillRect(card_image.rect(), sheen)
        if not self._owned:
            card_painter.fillRect(card_image.rect(), self._card_asset.style.unowned_overlay)
        card_painter.end()

        painter.drawImage(self.rect(), self._card_asset.apply_alpha_mask(card_image))
        if not self._owned and self._show_unowned_badge:
            self._paint_unowned_badge(painter)
        painter.end()

    def _paint_portrait(self, painter: QPainter) -> None:
        if self._pixmap.isNull():
            return
        key = (int(self._pixmap.cacheKey()), self.width(), self.height())
        if self._scaled_portrait_key != key or self._scaled_portrait.isNull():
            scaled = self._pixmap.scaledToWidth(self.width(), Qt.SmoothTransformation)
            if scaled.height() < self.height():
                scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self._scaled_portrait = scaled
            self._scaled_portrait_key = key
        scaled = self._scaled_portrait
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    def _paint_name_panel(self, painter: QPainter) -> None:
        style = self._card_asset.style
        panel_height = min(style.panel_height, max(20, self.height() // 3))
        panel_top = max(0, self.height() - panel_height - style.panel_bottom)
        panel_bottom = max(0, self.height() - 1)

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

        panel_overlay = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        panel_overlay.fill(Qt.transparent)
        overlay_painter = QPainter(panel_overlay)
        overlay_painter.fillRect(
            QRect(0, panel_top, self.width(), max(1, panel_bottom - panel_top + 1)),
            style.name_panel_color,
        )
        overlay_painter.end()
        painter.drawImage(0, 0, self._card_asset.apply_alpha_mask(panel_overlay))

        left_top, right_top = self._card_asset.row_bounds(self.size(), panel_top)
        left_bottom, right_bottom = self._card_asset.row_bounds(self.size(), panel_bottom)
        text_left = max(left_top, left_bottom) + style.panel_padding_x
        text_right = min(right_top, right_bottom) - style.panel_padding_x
        text_rect = QRect(text_left, panel_top + 4, max(1, text_right - text_left), max(1, panel_height - 6))
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(12.6, min(self.width(), self.height()) * 0.072))
        painter.setFont(font)
        painter.setPen(style.name_text_color)
        painter.drawText(text_rect, Qt.AlignCenter | Qt.TextSingleLine, self._title)

    def _paint_unowned_badge(self, painter: QPainter) -> None:
        style = self._card_asset.style
        expand = style.selected_expand if self._selected else 0
        inset = expand // 2
        reference_size = QSize(
            max(1, self.width() - expand),
            max(1, self.height() - expand),
        )
        badge_y = inset + style.unowned_badge_top
        sample_y = min(reference_size.height() - 1, style.unowned_badge_top + style.unowned_badge_height // 2)
        left_bound, right_bound = self._card_asset.row_bounds(reference_size, sample_y)
        badge_x = max(style.unowned_badge_inset_left, left_bound + style.unowned_badge_inset_left)
        available_width = max(
            32,
            right_bound - badge_x - style.unowned_badge_inset_right,
        )
        badge_rect = QRect(
            inset + badge_x,
            badge_y,
            min(style.unowned_badge_width, available_width),
            style.unowned_badge_height,
        )
        shadow_rect = QRect(badge_rect)
        shadow_rect.translate(0, 1)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawRoundedRect(shadow_rect, 10, 10)
        painter.setBrush(QColor(6, 8, 14, 222))
        painter.setPen(QPen(QColor(255, 255, 255, 42), 1))
        painter.drawRoundedRect(badge_rect, 10, 10)
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(7.2, min(reference_size.width(), reference_size.height()) * 0.034))
        painter.setFont(font)
        painter.setPen(self._card_asset.style.name_text_color)
        painter.drawText(badge_rect, Qt.AlignCenter, "UNOWNED")


class StudentPortraitWidget(QWidget):
    def __init__(self, card_asset: ParallelogramCardAsset, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card_asset = card_asset
        self._pixmap = QPixmap()
        self._owned = True
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def clear(self) -> None:
        self._pixmap = QPixmap()
        self.update()

    def setPixmap(self, pixmap: QPixmap, *, owned: bool = True) -> None:
        self._pixmap = pixmap
        self._owned = owned
        self.update()

    def _card_size(self) -> QSize:
        if self.width() <= 0 or self.height() <= 0:
            return QSize()
        height = self.height()
        width = max(1, int(round(height * self._card_asset.aspect_ratio)))
        if width > self.width():
            width = self.width()
            height = max(1, int(round(width / max(0.01, self._card_asset.aspect_ratio))))
        return QSize(max(1, width), max(1, height))

    def card_size(self) -> QSize:
        return self._card_size()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        card_size = self._card_size()
        if card_size.isEmpty():
            painter.end()
            return

        card_x = (self.width() - card_size.width()) // 2
        card_y = (self.height() - card_size.height()) // 2

        card_image = QImage(card_size, QImage.Format_ARGB32_Premultiplied)
        card_image.fill(Qt.transparent)
        card_painter = QPainter(card_image)
        card_painter.setRenderHint(QPainter.Antialiasing, True)
        card_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        card_painter.drawImage(0, 0, self._card_asset.background(card_size, hovered=False, selected=False))
        self._paint_portrait(card_painter)
        card_painter.drawImage(0, 0, self._card_asset.outline(card_size))
        if not self._owned:
            card_painter.fillRect(card_image.rect(), self._card_asset.style.unowned_overlay)
        card_painter.end()

        painter.drawImage(card_x, card_y, self._card_asset.apply_alpha_mask(card_image))
        if not self._owned:
            painter.save()
            painter.translate(card_x, card_y)
            self._paint_unowned_badge(painter)
            painter.restore()
        painter.end()

    def _paint_portrait(self, painter: QPainter) -> None:
        if self._pixmap.isNull():
            return
        size = painter.viewport().size()
        scaled = self._pixmap.scaledToWidth(size.width(), Qt.SmoothTransformation)
        if scaled.height() < size.height():
            scaled = self._pixmap.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = (size.width() - scaled.width()) // 2
        y = (size.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)

    def _paint_unowned_badge(self, painter: QPainter) -> None:
        style = self._card_asset.style
        size = self._card_size()
        sample_y = min(size.height() - 1, style.unowned_badge_top + style.unowned_badge_height // 2)
        left_bound, right_bound = self._card_asset.row_bounds(size, sample_y)
        badge_x = max(style.unowned_badge_inset_left, left_bound + style.unowned_badge_inset_left)
        available_width = max(32, right_bound - badge_x - style.unowned_badge_inset_right)
        badge_rect = QRect(
            badge_x,
            style.unowned_badge_top,
            min(style.unowned_badge_width, available_width),
            style.unowned_badge_height,
        )
        shadow_rect = QRect(badge_rect)
        shadow_rect.translate(0, 1)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawRoundedRect(shadow_rect, 10, 10)
        painter.setBrush(QColor(6, 8, 14, 222))
        painter.setPen(QPen(QColor(255, 255, 255, 42), 1))
        painter.drawRoundedRect(badge_rect, 10, 10)
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(7.2, min(size.width(), size.height()) * 0.034))
        painter.setFont(font)
        painter.setPen(self._card_asset.style.name_text_color)
        painter.drawText(badge_rect, Qt.AlignCenter, "UNOWNED")


class ParallelogramCardGrid(QScrollArea):
    current_changed = Signal(object, object)
    selection_changed = Signal(object)
    card_double_clicked = Signal(str)
    layout_changed = Signal(int, int)
    order_changed = Signal(object)
    card_drag_moved = Signal(str, object)
    card_drag_finished = Signal(str, object)

    def __init__(
        self,
        card_asset: ParallelogramCardAsset,
        ui_scale: float = 1.0,
        parent: QWidget | None = None,
        *,
        multi_select: bool = False,
        reorder_enabled: bool = False,
        drag_enabled: bool = False,
        min_card_width: int | None = None,
    ) -> None:
        super().__init__(parent)
        self._card_asset = card_asset
        self._ui_scale = ui_scale
        self._multi_select = multi_select
        self._reorder_enabled = reorder_enabled
        self._drag_enabled = drag_enabled
        self._content = QWidget()
        self._content.setAttribute(Qt.WA_StyledBackground, True)
        self.setWidget(self._content)
        self.setWidgetResizable(False)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards: list[StudentCardWidget] = []
        self._card_by_id: dict[str, StudentCardWidget] = {}
        self._current_id: str | None = None
        self._selected_ids: set[str] = set()
        self._drag_candidate_id: str | None = None
        self._drag_start_global = QPoint()
        self._drag_start_card_pos = QPoint()
        self._drag_preview: QLabel | None = None
        self._drag_preview_offset = QPoint()
        self._drag_hidden_card: StudentCardWidget | None = None
        self._drop_placeholder_index: int | None = None
        self._external_drop_placeholder_active = False
        self._app_drag_filter_installed = False
        self._dragging_reorder = False
        self._drag_threshold = max(8, int(round(8 * max(0.8, ui_scale))))
        self._base_size = card_asset.base_size
        self._min_card_width = (
            max(1, int(min_card_width))
            if min_card_width is not None
            else max(160, int(round(self._base_size.width() * max(0.72, min(1.0, ui_scale)))))
        )
        self._current_card_size = QSize(self._base_size)

    def clear_cards(self) -> None:
        self._clear_drag_preview()
        self._current_id = None
        self._selected_ids.clear()
        self._card_by_id.clear()
        while self._cards:
            card = self._cards.pop()
            card.deleteLater()
        edge = self._card_asset.style.grid_edge_padding
        self._content.resize(edge * 2, edge * 2)
        self.viewport().update()

    def _attach_card(self, card: StudentCardWidget) -> None:
        card.setParent(self._content)
        card.clicked.connect(self._on_card_clicked)
        card.double_clicked.connect(self.card_double_clicked)
        if self._reorder_enabled or self._drag_enabled:
            card.installEventFilter(self)
        card.show()

    def set_reorder_enabled(self, enabled: bool) -> None:
        if self._reorder_enabled == enabled:
            return
        self._reorder_enabled = enabled
        for card in self._cards:
            if enabled or self._drag_enabled:
                card.installEventFilter(self)
            else:
                card.removeEventFilter(self)

    def set_drag_enabled(self, enabled: bool) -> None:
        if self._drag_enabled == enabled:
            return
        self._drag_enabled = enabled
        for card in self._cards:
            if enabled or self._reorder_enabled:
                card.installEventFilter(self)
            else:
                card.removeEventFilter(self)

    def card_ids(self) -> list[str]:
        return [card.student_id for card in self._cards]

    def add_card(self, card: StudentCardWidget) -> None:
        self._attach_card(card)
        self._cards.append(card)
        self._card_by_id[card.student_id] = card
        self._relayout()

    def add_cards(self, cards: list[StudentCardWidget]) -> None:
        for card in cards:
            self._attach_card(card)
            self._cards.append(card)
            self._card_by_id[card.student_id] = card
        self._relayout()

    def set_cards(self, cards: list[StudentCardWidget]) -> None:
        old_cards = set(self._cards)
        next_cards = list(cards)
        next_card_set = set(next_cards)

        for card in next_cards:
            if card not in old_cards:
                self._attach_card(card)
            else:
                card.show()

        for card in old_cards - next_card_set:
            card.hide()
            card.deleteLater()

        self._cards = next_cards
        self._card_by_id = {card.student_id: card for card in next_cards}
        self._selected_ids &= set(self._card_by_id)
        if self._current_id not in self._card_by_id:
            self._current_id = None

        if self._cards:
            self._relayout()
        else:
            edge = self._card_asset.style.grid_edge_padding
            self._content.resize(edge * 2, edge * 2)
            self.viewport().update()

    def current_card_id(self) -> str | None:
        return self._current_id

    def selected_card_ids(self) -> set[str]:
        return set(self._selected_ids)

    def set_selected_card_ids(self, student_ids: set[str]) -> None:
        if not self._multi_select:
            self.set_current_card(next(iter(student_ids), None))
            return
        next_ids = {student_id for student_id in student_ids if student_id in self._card_by_id}
        if next_ids == self._selected_ids:
            return
        self._selected_ids = next_ids
        for student_id, card in self._card_by_id.items():
            card.setSelected(student_id in self._selected_ids)
        self._relayout()
        self.selection_changed.emit(set(self._selected_ids))

    def _on_card_clicked(self, student_id: str) -> None:
        if not self._multi_select:
            self.set_current_card(student_id)
            return
        if student_id in self._selected_ids:
            self._selected_ids.remove(student_id)
        else:
            self._selected_ids.add(student_id)
        card = self._card_by_id.get(student_id)
        if card is not None:
            card.setSelected(student_id in self._selected_ids)
            card.raise_()
        self._relayout()
        self.current_changed.emit(student_id, None)
        self.selection_changed.emit(set(self._selected_ids))

    def set_current_card(self, student_id: str | None) -> None:
        if self._multi_select:
            if student_id is None:
                self.set_selected_card_ids(set())
                return
            selected = set(self._selected_ids)
            if student_id in selected:
                selected.remove(student_id)
            else:
                selected.add(student_id)
            self.set_selected_card_ids(selected)
            return
        if student_id == self._current_id:
            return
        previous = self._current_id
        if previous in self._card_by_id:
            self._card_by_id[previous].setSelected(False)
        self._current_id = student_id
        self._relayout()
        if student_id in self._card_by_id:
            card = self._card_by_id[student_id]
            card.setSelected(True)
            self.ensureVisible(card.x(), card.y(), card.width(), card.height())
            card.raise_()
        self.current_changed.emit(student_id, previous)

    def card(self, student_id: str) -> StudentCardWidget | None:
        return self._card_by_id.get(student_id)

    def set_card_pixmap(self, student_id: str, pixmap: QPixmap) -> None:
        card = self._card_by_id.get(student_id)
        if card is not None:
            card.setPixmap(pixmap)

    def _index_at_content_pos(self, pos: QPoint, cards: list[StudentCardWidget] | None = None) -> int:
        target_cards = self._cards if cards is None else cards
        if not target_cards:
            return -1
        margin = max(12, self._card_asset.style.grid_gap_y)
        for index, card in enumerate(target_cards):
            if card.geometry().adjusted(-margin, -margin, margin, margin).contains(pos):
                return index
        return min(
            range(len(target_cards)),
            key=lambda index: (
                (target_cards[index].geometry().center().x() - pos.x()) ** 2
                + (target_cards[index].geometry().center().y() - pos.y()) ** 2
            ),
        )

    def _start_drag_preview(self, card: StudentCardWidget, global_pos: QPoint, card_pos: QPoint) -> None:
        if self._drag_preview is not None:
            return
        pixmap = QPixmap(card.size())
        pixmap.fill(Qt.transparent)
        card.render(pixmap)
        preview = QLabel(None, Qt.ToolTip | Qt.FramelessWindowHint)
        preview.setAttribute(Qt.WA_TranslucentBackground, True)
        preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        preview.setPixmap(pixmap)
        preview.resize(card.size())
        preview.setWindowOpacity(0.94)
        self._drag_preview = preview
        self._drag_preview_offset = QPoint(card_pos)
        self._drag_hidden_card = card
        self._drop_placeholder_index = None
        card.setDragHidden(True)
        self._relayout()
        self._update_drag_preview(global_pos)
        preview.show()

    def _update_drag_preview(self, global_pos: QPoint) -> None:
        if self._drag_preview is None:
            return
        self._drag_preview.move(global_pos - self._drag_preview_offset)

    @staticmethod
    def _retire_drag_preview(preview: QLabel) -> None:
        preview.hide()
        preview.deleteLater()

    def _finish_drag_visuals(self, *, defer_preview: bool = False) -> bool:
        needs_relayout = (
            self._drag_hidden_card is not None
            or self._drop_placeholder_index is not None
            or self._external_drop_placeholder_active
        )
        hidden_card = self._drag_hidden_card
        self._drag_hidden_card = None
        if hidden_card is not None:
            hidden_card.setDragHidden(False)
        preview = self._drag_preview
        self._drag_preview = None
        if preview is not None:
            if defer_preview:
                QTimer.singleShot(16, lambda preview=preview: self._retire_drag_preview(preview))
            else:
                self._retire_drag_preview(preview)
        self._drop_placeholder_index = None
        self._external_drop_placeholder_active = False
        return needs_relayout

    def _clear_drag_preview(self) -> None:
        if self._finish_drag_visuals():
            self._relayout()

    def _update_drop_placeholder(self, global_pos: QPoint, *, dragged_card: StudentCardWidget) -> None:
        if not self._reorder_enabled:
            return
        next_index = self.drop_index_for_global_pos(
            global_pos,
            exclude_student_id=dragged_card.student_id,
            stable_index=self._drop_placeholder_index,
        )
        if next_index == self._drop_placeholder_index:
            return
        self._drop_placeholder_index = next_index
        self._relayout()

    def set_external_drop_placeholder(self, index: int | None) -> None:
        if index is None:
            self.clear_external_drop_placeholder()
            return
        next_index = max(0, min(int(index), len(self._cards)))
        if self._external_drop_placeholder_active and self._drop_placeholder_index == next_index:
            return
        self._external_drop_placeholder_active = True
        self._drop_placeholder_index = next_index
        self._relayout()

    def clear_external_drop_placeholder(self) -> None:
        if not self._external_drop_placeholder_active and self._drop_placeholder_index is None:
            return
        self._external_drop_placeholder_active = False
        self._drop_placeholder_index = None
        self._relayout()

    def _install_app_drag_filter(self) -> None:
        if self._app_drag_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._app_drag_filter_installed = True

    def _remove_app_drag_filter(self) -> None:
        if not self._app_drag_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._app_drag_filter_installed = False

    def _cancel_card_drag(self, card: StudentCardWidget | None) -> None:
        if card is not None and QWidget.mouseGrabber() is card:
            card.releaseMouse()
        self._drag_candidate_id = None
        self._dragging_reorder = False
        self._remove_app_drag_filter()
        self._clear_drag_preview()

    def _handle_card_drag_move(self, card: StudentCardWidget, global_pos: QPoint, buttons: Qt.MouseButtons) -> bool:
        if not (buttons & Qt.LeftButton):
            self._cancel_card_drag(card)
            return True
        distance = (global_pos - self._drag_start_global).manhattanLength()
        if not self._dragging_reorder and distance < self._drag_threshold:
            return False
        self._dragging_reorder = True
        self._start_drag_preview(card, global_pos, self._drag_start_card_pos)
        self._update_drag_preview(global_pos)
        self._update_drop_placeholder(global_pos, dragged_card=card)
        if self._drag_enabled:
            self.card_drag_moved.emit(card.student_id, global_pos)
        return True

    def _finish_card_drag(self, card: StudentCardWidget, global_pos: QPoint) -> bool:
        was_dragging = self._dragging_reorder
        drop_index = (
            self._drop_placeholder_index
            if self._drop_placeholder_index is not None
            else self.drop_index_for_global_pos(global_pos, exclude_student_id=card.student_id)
            if was_dragging and self._reorder_enabled
            else None
        )
        self._drag_candidate_id = None
        self._dragging_reorder = False
        if QWidget.mouseGrabber() is card:
            card.releaseMouse()
        self._remove_app_drag_filter()
        if not was_dragging:
            self._clear_drag_preview()
            return False
        if hasattr(card, "_pressed"):
            card._pressed = False
            card.update()
        needs_relayout = self._finish_drag_visuals(defer_preview=True)
        if self._reorder_enabled and drop_index is not None:
            remaining_cards = [candidate for candidate in self._cards if candidate is not card]
            clamped_index = max(0, min(drop_index, len(remaining_cards)))
            next_cards = list(remaining_cards)
            next_cards.insert(clamped_index, card)
            if next_cards != self._cards:
                self._cards = next_cards
                needs_relayout = True
        if needs_relayout:
            self._relayout()
        self.set_current_card(card.student_id)
        card.repaint()
        self._content.repaint()
        self.viewport().repaint()
        if self._reorder_enabled:
            self.order_changed.emit(self.card_ids())
        if self._drag_enabled:
            self.card_drag_finished.emit(card.student_id, global_pos)
        return True

    def eventFilter(self, watched, event) -> bool:
        if (
            getattr(self, "_app_drag_filter_installed", False)
            and getattr(self, "_drag_candidate_id", None)
            and watched not in getattr(self, "_cards", ())
        ):
            card = self._card_by_id.get(self._drag_candidate_id)
            if card is None:
                self._cancel_card_drag(None)
                return False
            event_type = event.type()
            if event_type == QEvent.MouseMove:
                return self._handle_card_drag_move(card, event.globalPosition().toPoint(), event.buttons())
            if event_type == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                return self._finish_card_drag(card, event.globalPosition().toPoint())
            return False

        if (
            not (getattr(self, "_reorder_enabled", False) or getattr(self, "_drag_enabled", False))
            or not hasattr(self, "_cards")
            or watched not in self._cards
        ):
            return super().eventFilter(watched, event)

        card = watched
        event_type = event.type()
        if event_type == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._card_asset.contains(card.size(), event.position().toPoint()):
                self._drag_candidate_id = card.student_id
                self._drag_start_global = event.globalPosition().toPoint()
                self._drag_start_card_pos = event.position().toPoint()
                self._dragging_reorder = False
                card.grabMouse()
                self._install_app_drag_filter()
            return False

        if event_type == QEvent.MouseMove and self._drag_candidate_id == card.student_id:
            handled = self._handle_card_drag_move(card, event.globalPosition().toPoint(), event.buttons())
            if handled:
                event.accept()
                return True
            return False

        if event_type == QEvent.MouseButtonRelease and self._drag_candidate_id == card.student_id:
            if self._finish_card_drag(card, event.globalPosition().toPoint()):
                event.accept()
                return True
            return False

        return super().eventFilter(watched, event)

    def current_card_size(self) -> QSize:
        return QSize(self._current_card_size)

    def set_min_card_width(self, width: int) -> None:
        next_width = max(1, int(width))
        if next_width == self._min_card_width:
            return
        self._min_card_width = next_width
        self._relayout()

    def drop_index_for_global_pos(
        self,
        global_pos: QPoint,
        *,
        exclude_student_id: str | None = None,
        stable_index: int | None = None,
    ) -> int:
        target_cards = [
            card
            for card in self._cards
            if exclude_student_id is None or card.student_id != exclude_student_id
        ]
        if not target_cards:
            return 0
        content_pos = self._content.mapFromGlobal(global_pos)
        edge, columns, card_width, card_height, advance_x, row_advance = self._grid_metrics()
        if columns <= 0:
            return 0

        total_rows = max(1, (len(target_cards) + columns - 1) // columns)
        row_margin = max(8, int(round(card_height * 0.18)))
        if content_pos.y() < edge - row_margin:
            candidate = 0
        elif content_pos.y() >= edge + total_rows * row_advance - row_advance + card_height + row_margin:
            candidate = len(target_cards)
        else:
            row = max(0, min(total_rows - 1, (content_pos.y() - edge) // max(1, row_advance)))
            row_start = row * columns
            row_count = max(0, min(columns, len(target_cards) - row_start))
            if row_count <= 0:
                candidate = len(target_cards)
            else:
                col = max(0, min(columns - 1, (content_pos.x() - edge) // max(1, advance_x)))
                col = min(col, row_count - 1)
                slot_left = edge + col * advance_x
                slot_mid = slot_left + card_width // 2
                hysteresis = max(6, int(round(card_width * 0.08)))
                if stable_index is not None:
                    stable_row = max(0, min(total_rows - 1, stable_index // max(1, columns)))
                    stable_col = max(0, min(columns - 1, stable_index % max(1, columns)))
                    if stable_row == row and abs(stable_col - col) <= 1 and abs(content_pos.x() - slot_mid) <= hysteresis:
                        return max(0, min(len(target_cards), stable_index))
                insert_after = content_pos.x() > slot_mid + hysteresis
                if abs(content_pos.x() - slot_mid) <= hysteresis and stable_index is not None:
                    return max(0, min(len(target_cards), stable_index))
                candidate = row_start + col + (1 if insert_after else 0)
        return max(0, min(len(target_cards), candidate))

    def visible_card_ids(self) -> set[str]:
        viewport_rect = self.viewport().rect()
        result: set[str] = set()
        for card in self._cards:
            top_left = card.mapTo(self.viewport(), card.rect().topLeft())
            card_rect = QRect(top_left, card.size())
            if card_rect.intersects(viewport_rect):
                result.add(card.student_id)
        return result

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _grid_metrics(self) -> tuple[int, int, int, int, int, int]:
        edge = self._card_asset.style.grid_edge_padding
        available_width = max(1, self.viewport().width() - edge * 2)
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
        row_advance = card_height + gap_y
        return edge, columns, card_width, card_height, advance_x, row_advance

    def _relayout(self) -> None:
        if not self._cards:
            return
        edge, columns, card_width, card_height, advance_x, row_advance = self._grid_metrics()

        if card_width != self._current_card_size.width() or card_height != self._current_card_size.height():
            self._current_card_size = QSize(card_width, card_height)
            self.layout_changed.emit(card_width, card_height)

        dragged_card = self._drag_hidden_card
        layout_cards = [card for card in self._cards if card is not dragged_card]
        slots: list[StudentCardWidget | None] = list(layout_cards)
        if (
            (dragged_card is not None or self._external_drop_placeholder_active)
            and self._reorder_enabled
            and self._drop_placeholder_index is not None
        ):
            placeholder_index = max(0, min(self._drop_placeholder_index, len(slots)))
            slots.insert(placeholder_index, None)

        if not slots:
            self._content.resize(edge * 2, edge * 2)
            return

        for index, card in enumerate(slots):
            if card is None:
                continue
            row = index // columns
            col = index % columns
            x = edge + col * advance_x
            y = edge + row * row_advance
            if card.student_id == self._current_id or card.student_id in self._selected_ids:
                expand = self._card_asset.style.selected_expand
                lift = self._card_asset.style.selected_lift_y
                card.setGeometry(
                    x - expand // 2,
                    max(0, y - lift - expand // 2),
                    card_width + expand,
                    card_height + expand,
                )
            else:
                card.setGeometry(x, y, card_width, card_height)
            card.raise_()

        rows = (len(slots) + columns - 1) // columns
        selected_extra = self._card_asset.style.selected_expand
        content_width = edge * 2 + card_width + max(0, columns - 1) * advance_x + selected_extra
        content_height = edge * 2 + rows * card_height + max(0, rows - 1) * (row_advance - card_height) + selected_extra + self._card_asset.style.selected_lift_y
        self._content.resize(content_width, content_height)
