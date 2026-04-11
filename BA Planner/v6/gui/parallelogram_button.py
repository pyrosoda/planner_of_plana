from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QPushButton, QSizePolicy, QWidget


@dataclass(slots=True)
class ParallelogramButtonStyle:
    normal_asset: Path
    hover_asset: Path | None = None
    pressed_asset: Path | None = None
    disabled_asset: Path | None = None
    fixed_height: int = 50
    source_left_slice: int = 94
    source_right_slice: int = 94
    source_overlap_x: int = 58
    strip_gap_x: int = 8
    source_overlap_y: int = 0
    content_padding_left: int = 48
    content_padding_right: int = 20
    content_padding_top: int = 36
    content_padding_bottom: int = 30
    text_optical_offset_x: int = 2
    text_optical_offset_y: int = -2
    icon_gap: int = 8
    pressed_content_offset_y: int = 2
    hit_alpha_threshold: int = 8
    mask_alpha_threshold: int = 2
    hover_overlay: QColor = field(default_factory=lambda: QColor(255, 255, 255, 28))
    hover_glow: QColor = field(default_factory=lambda: QColor(255, 255, 255, 52))
    pressed_overlay: QColor = field(default_factory=lambda: QColor(35, 44, 72, 28))
    disabled_overlay: QColor = field(default_factory=lambda: QColor(245, 247, 252, 96))
    text_color: QColor = field(default_factory=lambda: QColor("#324164"))
    disabled_text_color: QColor = field(default_factory=lambda: QColor("#8c94a7"))
    text_shadow_color: QColor = field(default_factory=lambda: QColor(255, 255, 255, 170))


def build_card_button_style(asset_path: str | Path, ui_scale: float = 1.0) -> ParallelogramButtonStyle:
    scale = max(0.8, float(ui_scale))
    return ParallelogramButtonStyle(
        normal_asset=Path(asset_path),
        fixed_height=max(40, int(round(50 * scale))),
        source_left_slice=94,
        source_right_slice=94,
        source_overlap_x=58,
        strip_gap_x=max(3, int(round(8 * scale))),
        content_padding_left=max(34, int(round(48 * scale))),
        content_padding_right=max(14, int(round(20 * scale))),
        text_optical_offset_x=max(0, int(round(2 * scale))),
    )


class ParallelogramButton(QPushButton):
    _image_cache: dict[Path, QImage] = {}

    def __init__(
        self,
        text: str = "",
        *,
        style: ParallelogramButtonStyle,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self._style = style
        self._normal_image = self._load_image(style.normal_asset)
        self._render_cache: dict[tuple[int, int, str], QImage] = {}
        self._mask_image: QImage | None = None
        self._base_size = self._normal_image.size()
        self._base_scale = style.fixed_height / max(1, self._base_size.height())
        self._base_width = max(1, int(round(self._base_size.width() * self._base_scale)))

        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFlat(True)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; padding: 0px; margin: 0px; }"
        )
        self.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        self.setFixedHeight(style.fixed_height)
        self.setMinimumWidth(self._base_width)
        self._update_mask()

    @property
    def button_style(self) -> ParallelogramButtonStyle:
        return self._style

    def strip_overlap(self) -> int:
        return max(0, self._scale_source_value(self._style.source_overlap_x))

    def vertical_overlap(self) -> int:
        return max(0, self._scale_source_value(self._style.source_overlap_y))

    def sizeHint(self) -> QSize:
        return QSize(max(self._base_width, self._content_width_hint()), self._style.fixed_height)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._base_width, self._style.fixed_height)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.updateGeometry()
        self._notify_strip_parent()

    def setIcon(self, icon: QIcon) -> None:
        super().setIcon(icon)
        self.updateGeometry()
        self._notify_strip_parent()

    def setIconSize(self, size: QSize) -> None:
        super().setIconSize(size)
        self.updateGeometry()
        self._notify_strip_parent()

    def hitButton(self, pos) -> bool:  # type: ignore[override]
        if not self.rect().contains(pos):
            return False
        image = self._base_mask_image()
        if image is None:
            return False
        if not (0 <= pos.x() < image.width() and 0 <= pos.y() < image.height()):
            return False
        return image.pixelColor(pos).alpha() >= self._style.hit_alpha_threshold

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_mask()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.EnabledChange, QEvent.FontChange):
            self.update()
            self.updateGeometry()
            self._notify_strip_parent()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(self.rect(), self._background_for_state())
        self._paint_content(painter)
        painter.end()

    def _notify_strip_parent(self) -> None:
        parent = self.parentWidget()
        if isinstance(parent, ParallelogramButtonRow):
            parent.relayout()

    def _background_for_state(self) -> QImage:
        state = self._state_key()
        key = (self.width(), self.height(), state)
        cached = self._render_cache.get(key)
        if cached is not None:
            return cached

        source_path = self._asset_for_state(state)
        if source_path is None:
            image = QImage(self._compose_image(self._normal_image, self.size()))
            image = self._apply_state_effect(image, state)
        else:
            image = self._compose_image(self._load_image(source_path), self.size())
        self._render_cache[key] = image
        return image

    def _base_mask_image(self) -> QImage | None:
        if self._mask_image is None or self._mask_image.size() != self.size():
            self._update_mask()
        return self._mask_image

    def _update_mask(self) -> None:
        if self.width() <= 0 or self.height() <= 0:
            return
        key = (self.width(), self.height(), "normal")
        image = self._render_cache.get(key)
        if image is None:
            image = self._compose_image(self._normal_image, self.size())
            self._render_cache[key] = image
        self._mask_image = image

        mask_source = QImage(image.size(), QImage.Format_ARGB32_Premultiplied)
        mask_source.fill(Qt.transparent)
        for y in range(image.height()):
            for x in range(image.width()):
                alpha = image.pixelColor(x, y).alpha()
                if alpha >= self._style.mask_alpha_threshold:
                    mask_source.setPixelColor(x, y, QColor(255, 255, 255, 255))
        self.setMask(QPixmap.fromImage(mask_source).mask())

    def _compose_image(self, source_image: QImage, target_size: QSize) -> QImage:
        scaled = source_image.scaledToHeight(
            max(1, target_size.height()),
            Qt.SmoothTransformation,
        )
        if target_size.width() <= scaled.width():
            return scaled

        scale = scaled.height() / max(1, source_image.height())
        left = max(1, int(round(self._style.source_left_slice * scale)))
        right = max(1, int(round(self._style.source_right_slice * scale)))
        if left + right >= scaled.width():
            left = max(1, scaled.width() // 2 - 1)
            right = max(1, scaled.width() - left - 1)
        center_width = max(1, scaled.width() - left - right)
        dest_center_width = max(1, target_size.width() - left - right)

        result = QImage(target_size, QImage.Format_ARGB32_Premultiplied)
        result.fill(Qt.transparent)

        painter = QPainter(result)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(QRect(0, 0, left, target_size.height()), scaled, QRect(0, 0, left, scaled.height()))
        painter.drawImage(
            QRect(left, 0, dest_center_width, target_size.height()),
            scaled,
            QRect(left, 0, center_width, scaled.height()),
        )
        painter.drawImage(
            QRect(left + dest_center_width, 0, right, target_size.height()),
            scaled,
            QRect(scaled.width() - right, 0, right, scaled.height()),
        )
        painter.end()
        return result

    def _apply_state_effect(self, image: QImage, state: str) -> QImage:
        if state == "hover":
            return self._apply_hover_effect(image)
        if state == "pressed":
            return self._apply_pressed_effect(image)
        if state == "disabled":
            return self._apply_disabled_effect(image)
        return image

    def _apply_hover_effect(self, image: QImage) -> QImage:
        result = QImage(image)
        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode_Screen)
        painter.fillRect(result.rect(), self._style.hover_overlay)
        glow = QLinearGradient(0, 0, 0, result.height())
        glow.setColorAt(0.0, self._style.hover_glow)
        glow.setColorAt(0.38, QColor(255, 255, 255, 0))
        painter.fillRect(result.rect(), glow)
        painter.end()
        return result

    def _apply_pressed_effect(self, image: QImage) -> QImage:
        result = QImage(image)
        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode_SourceAtop)
        painter.fillRect(result.rect(), self._style.pressed_overlay)
        shade = QLinearGradient(0, 0, 0, result.height())
        shade.setColorAt(0.0, QColor(24, 30, 48, 24))
        shade.setColorAt(0.7, QColor(255, 255, 255, 0))
        painter.fillRect(result.rect(), shade)
        painter.end()
        return result

    def _apply_disabled_effect(self, image: QImage) -> QImage:
        result = QImage(image)
        for y in range(result.height()):
            for x in range(result.width()):
                color = result.pixelColor(x, y)
                alpha = color.alpha()
                if alpha == 0:
                    continue
                gray = int(round((color.red() * 0.299) + (color.green() * 0.587) + (color.blue() * 0.114)))
                color.setRed(int(round(gray * 0.84 + color.red() * 0.16)))
                color.setGreen(int(round(gray * 0.84 + color.green() * 0.16)))
                color.setBlue(int(round(gray * 0.84 + color.blue() * 0.16)))
                result.setPixelColor(x, y, color)

        painter = QPainter(result)
        painter.setCompositionMode(QPainter.CompositionMode_Screen)
        painter.fillRect(result.rect(), self._style.disabled_overlay)
        painter.end()
        return result

    def _paint_content(self, painter: QPainter) -> None:
        content_rect = self._content_rect()
        if content_rect.width() <= 2 or content_rect.height() <= 2:
            return

        if self.isDown() and self.isEnabled():
            content_rect.translate(0, max(1, self._scale_source_value(self._style.pressed_content_offset_y)))

        icon = self.icon()
        icon_size = self._resolved_icon_size(content_rect.height())
        icon_width = 0
        gap = 0
        if not icon.isNull():
            icon_width = icon_size.width()
            gap = max(0, self._scale_source_value(self._style.icon_gap)) if self.text() else 0

        metrics = QFontMetrics(self.font())
        text_width_budget = max(0, content_rect.width() - icon_width - gap)
        text = metrics.elidedText(self.text(), Qt.ElideRight, text_width_budget)
        text_width = metrics.horizontalAdvance(text)
        layout_width = icon_width + gap + text_width
        start_x = content_rect.x() + max(0, (content_rect.width() - layout_width) // 2)
        if not icon.isNull():
            mode = QIcon.Disabled if not self.isEnabled() else QIcon.Normal
            pixmap = icon.pixmap(icon_size, mode)
            pixmap_y = content_rect.y() + max(0, (content_rect.height() - icon_size.height()) // 2)
            painter.drawPixmap(start_x, pixmap_y, pixmap)
            start_x += icon_width + gap

        if text:
            text_rect = QRect(start_x, content_rect.y(), max(1, text_width), content_rect.height())
            shadow_rect = QRect(text_rect)
            shadow_rect.translate(0, 1)
            painter.setPen(self._style.text_shadow_color if self.isEnabled() else QColor(255, 255, 255, 100))
            painter.drawText(shadow_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.setPen(self._style.text_color if self.isEnabled() else self._style.disabled_text_color)
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)

    def _content_rect(self) -> QRect:
        rect = self.rect()
        left = self._scale_source_value(self._style.content_padding_left)
        right = self._scale_source_value(self._style.content_padding_right)
        top = self._scale_source_value(self._style.content_padding_top)
        bottom = self._scale_source_value(self._style.content_padding_bottom)
        rect = rect.adjusted(left, top, -right, -bottom)
        rect.translate(
            self._scale_source_value(self._style.text_optical_offset_x),
            self._scale_source_value(self._style.text_optical_offset_y),
        )
        return rect

    def _content_width_hint(self) -> int:
        metrics = QFontMetrics(self.font())
        width = 0
        width += self._scale_source_value(self._style.content_padding_left)
        width += self._scale_source_value(self._style.content_padding_right)
        width += metrics.horizontalAdvance(self.text())
        if not self.icon().isNull():
            icon_size = self._resolved_icon_size(self.height())
            width += icon_size.width() + self._scale_source_value(self._style.icon_gap)
        return width

    def _resolved_icon_size(self, content_height: int) -> QSize:
        icon_size = self.iconSize()
        if icon_size.isValid() and icon_size.width() > 0 and icon_size.height() > 0:
            return icon_size
        side = max(14, int(round(content_height * 0.58)))
        return QSize(side, side)

    def _state_key(self) -> str:
        if not self.isEnabled():
            return "disabled"
        if self.isDown():
            return "pressed"
        if self.underMouse():
            return "hover"
        return "normal"

    def _asset_for_state(self, state: str) -> Path | None:
        if state == "hover":
            return self._style.hover_asset
        if state == "pressed":
            return self._style.pressed_asset
        if state == "disabled":
            return self._style.disabled_asset
        return self._style.normal_asset

    def _scale_source_value(self, value: int) -> int:
        return max(0, int(round(value * self.height() / max(1, self._base_size.height()))))

    @classmethod
    def _load_image(cls, path: Path) -> QImage:
        resolved = Path(path).resolve()
        cached = cls._image_cache.get(resolved)
        if cached is not None:
            return cached
        image = QImage(str(resolved))
        if image.isNull():
            raise FileNotFoundError(f"Unable to load button asset: {resolved}")
        cls._image_cache[resolved] = image
        return image


class ParallelogramButtonRow(QWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        orientation: Qt.Orientation = Qt.Horizontal,
    ) -> None:
        super().__init__(parent)
        self._orientation = orientation
        self._buttons: list[ParallelogramButton] = []
        if orientation == Qt.Horizontal:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        else:
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

    def addButton(self, button: ParallelogramButton) -> None:
        button.setParent(self)
        button.installEventFilter(self)
        button.show()
        self._buttons.append(button)
        button.raise_()
        self.relayout()

    def buttons(self) -> tuple[ParallelogramButton, ...]:
        return tuple(self._buttons)

    def sizeHint(self) -> QSize:
        return self._layout_size(use_minimum=False)

    def minimumSizeHint(self) -> QSize:
        return self._layout_size(use_minimum=True)

    def relayout(self) -> None:
        self.updateGeometry()
        if self.width() > 0 and self.height() > 0:
            self._apply_layout(self.rect())
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_layout(self.rect())

    def eventFilter(self, watched, event) -> bool:
        if watched in self._buttons and event.type() in (
            QEvent.EnabledChange,
            QEvent.FontChange,
            QEvent.Hide,
            QEvent.LayoutRequest,
            QEvent.Show,
        ):
            self.relayout()
        return super().eventFilter(watched, event)

    def _layout_size(self, *, use_minimum: bool) -> QSize:
        visible = [button for button in self._buttons if button.isVisible()]
        if not visible:
            return QSize(0, 0)

        sizes = [button.minimumSizeHint() if use_minimum else button.sizeHint() for button in visible]
        if self._orientation == Qt.Horizontal:
            width = sum(size.width() for size in sizes) - self._total_overlap(visible, horizontal=True)
            height = max(size.height() for size in sizes)
        else:
            width = max(size.width() for size in sizes)
            height = sum(size.height() for size in sizes) - self._total_overlap(visible, horizontal=False)
        return QSize(max(0, width), max(0, height))

    def _apply_layout(self, rect: QRect) -> None:
        visible = [button for button in self._buttons if button.isVisible()]
        if not visible:
            return

        if self._orientation == Qt.Horizontal:
            lengths = [button.sizeHint().width() for button in visible]
            minimums = [button.minimumSizeHint().width() for button in visible]
            overlaps = [self._shared_overlap(visible[index], visible[index + 1], horizontal=True) for index in range(len(visible) - 1)]
            target_sum = rect.width() + sum(overlaps)
            widths = self._fit_lengths(lengths, minimums, target_sum)
            x = rect.x()
            for index, button in enumerate(visible):
                height = min(button.sizeHint().height(), rect.height())
                y = rect.y() + max(0, (rect.height() - height) // 2)
                button.setGeometry(x, y, widths[index], height)
                button.raise_()
                x += widths[index]
                if index < len(overlaps):
                    x -= overlaps[index]
        else:
            lengths = [button.sizeHint().height() for button in visible]
            minimums = [button.minimumSizeHint().height() for button in visible]
            overlaps = [self._shared_overlap(visible[index], visible[index + 1], horizontal=False) for index in range(len(visible) - 1)]
            target_sum = rect.height() + sum(overlaps)
            heights = self._fit_lengths(lengths, minimums, target_sum)
            y = rect.y()
            for index, button in enumerate(visible):
                width = min(button.sizeHint().width(), rect.width())
                x = rect.x() + max(0, (rect.width() - width) // 2)
                button.setGeometry(x, y, width, heights[index])
                button.raise_()
                y += heights[index]
                if index < len(overlaps):
                    y -= overlaps[index]

    def _fit_lengths(self, lengths: list[int], minimums: list[int], target_sum: int) -> list[int]:
        fitted = list(lengths)
        current_sum = sum(fitted)
        if current_sum < target_sum:
            extra = target_sum - current_sum
            index = 0
            while extra > 0 and fitted:
                fitted[index % len(fitted)] += 1
                extra -= 1
                index += 1
            return fitted

        excess = current_sum - target_sum
        while excess > 0:
            candidates = [index for index, value in enumerate(fitted) if value > minimums[index]]
            if not candidates:
                break
            candidates.sort(key=lambda index: fitted[index] - minimums[index], reverse=True)
            for index in candidates:
                if excess == 0:
                    break
                if fitted[index] > minimums[index]:
                    fitted[index] -= 1
                    excess -= 1
        return fitted

    def _shared_overlap(
        self,
        previous: ParallelogramButton,
        current: ParallelogramButton,
        *,
        horizontal: bool,
    ) -> int:
        if horizontal:
            gap = max(
                previous._scale_source_value(previous.button_style.strip_gap_x),
                current._scale_source_value(current.button_style.strip_gap_x),
            )
            return max(0, min(previous.strip_overlap(), current.strip_overlap()) - gap)
        return min(previous.vertical_overlap(), current.vertical_overlap())

    def _total_overlap(self, buttons: list[ParallelogramButton], *, horizontal: bool) -> int:
        if len(buttons) < 2:
            return 0
        return sum(
            self._shared_overlap(buttons[index], buttons[index + 1], horizontal=horizontal)
            for index in range(len(buttons) - 1)
        )
