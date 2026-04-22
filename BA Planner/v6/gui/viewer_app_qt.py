"""
Standalone Qt-based student viewer process.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import core.student_meta as student_meta
from core.config import get_storage_paths
from core.db import init_db
from core.equipment_items import EQUIPMENT_EXP_ITEMS, EQUIPMENT_SERIES, WEAPON_PART_ITEMS
from core.inventory_profiles import inventory_item_display_name
from core.oparts import OPART_ORDERED_ITEM_IDS, OPART_WB_ITEMS
from core.planning import (
    MAX_TARGET_EQUIP_LEVEL,
    MAX_TARGET_EQUIP_TIER,
    MAX_TARGET_EX_SKILL,
    MAX_TARGET_LEVEL,
    MAX_TARGET_SKILL,
    MAX_TARGET_STAR,
    MAX_TARGET_WEAPON_LEVEL,
    MAX_TARGET_WEAPON_STAR,
    StudentGoal,
    load_plan,
    save_plan,
)
from core.planning_calc import PlanCostSummary, calculate_goal_cost, calculate_plan_totals
from PySide6.QtCore import QEvent, QObject, QRect, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QIcon, QImage, QIntValidator, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QScrollArea,
    QSizePolicy,
)

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

PORTRAIT_DIR = BASE_DIR / "templates" / "students_portraits"
UI_FONT_PATH = BASE_DIR / "gui" / "font" / "경기천년제목_Medium.ttf"
POLI_BG_DIR = BASE_DIR / "templates" / "icons" / "temp"
SCHOOL_LOGO_DIR = BASE_DIR / "templates" / "icons" / "school_logo"
EQUIPMENT_ICON_DIR = BASE_DIR / "templates" / "icons" / "equipment"
INVENTORY_DETAIL_DIR = BASE_DIR / "templates" / "inventory_detail"
CARD_BUTTON_ASSET = POLI_BG_DIR / "square.png"
MAIN_UI_PALETTE_PATH = BASE_DIR / "gui" / "main_ui_color_palete.txt"
THUMB_STYLE_VERSION = "v5-parallelogram-card-fit"
DETAIL_SLANT = 0.22

_REPORT_NAME_TO_ICON = {
    "초급활동보고서": "report_0",
    "소급활동보고서": "report_0",
    "일반활동보고서": "report_1",
    "상급활동보고서": "report_2",
    "최상급활동보고서": "report_3",
}
_REPORT_ICON_TO_NAME = {
    "report_0": "초급 활동 보고서",
    "report_1": "일반 활동 보고서",
    "report_2": "상급 활동 보고서",
    "report_3": "최상급 활동 보고서",
}
_REPORT_ID_TO_ICON = {
    **{icon_id: icon_id for icon_id in _REPORT_ICON_TO_NAME},
    **{f"Item_Icon_ExpItem_{tier}": f"report_{tier}" for tier in range(4)},
}
_REPORT_ORDER = ("report_3", "report_2", "report_1", "report_0")
_WORKBOOK_ID_TO_NAME = {
    "Item_Icon_WorkBook_PotentialAttack": "Attack WB",
    "Item_Icon_WorkBook_PotentialMaxHP": "Max HP WB",
    "Item_Icon_WorkBook_PotentialHealPower": "Heal Power WB",
}
_WB_ITEM_IDS = tuple(item_id for item_id, _name in OPART_WB_ITEMS)
_OPART_ITEM_IDS = tuple(item_id for item_id in OPART_ORDERED_ITEM_IDS if item_id not in _WB_ITEM_IDS)
_SCHOOL_SEQUENCE = (
    "Hyakkiyako",
    "RedWinter",
    "Trinity",
    "Gehenna",
    "Abydos",
    "Millennium",
    "Arius",
    "Shanhaijing",
    "Valkyrie",
    "Highlander",
    "Wildhunt",
)

from gui.student_filters import (
    FILTER_FIELD_LABELS,
    FILTER_FIELD_ORDER,
    active_filter_count,
    build_filter_options,
    matches_student_filters,
    summarize_filters,
)
from gui.parallelogram_button import (
    ParallelogramButton,
    ParallelogramButtonRow,
    build_card_button_style,
)
from gui.parallelogram_card import (
    ParallelogramCardAsset,
    ParallelogramCardGrid,
    StudentCardWidget,
    StudentPortraitWidget,
    build_card_style,
)
from gui.student_stats import DonutWidget, build_distribution


def _normalize_hex(color: str, fallback: str) -> str:
    value = (color or "").strip()
    if len(value) == 7 and value.startswith("#"):
        return value.lower()
    return fallback.lower()


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(red: int, green: int, blue: int) -> str:
    return f"#{max(0, min(255, red)):02x}{max(0, min(255, green)):02x}{max(0, min(255, blue)):02x}"


def _hex_to_colorref(color: str) -> int:
    red, green, blue = _hex_to_rgb(color)
    return red | (green << 8) | (blue << 16)


def _mix_hex(color_a: str, color_b: str, amount_from_b: float) -> str:
    amount = max(0.0, min(1.0, amount_from_b))
    ar, ag, ab = _hex_to_rgb(color_a)
    br, bg, bb = _hex_to_rgb(color_b)
    return _rgb_to_hex(
        int(round(ar + (br - ar) * amount)),
        int(round(ag + (bg - ag) * amount)),
        int(round(ab + (bb - ab) * amount)),
    )


def _load_main_palette() -> tuple[str, str, str, str, str]:
    fallback = ("#f266b3", "#efe4f2", "#313b59", "#2c3140", "#f2f2f2")
    if not MAIN_UI_PALETTE_PATH.exists():
        return fallback

    try:
        values = [entry.strip() for entry in MAIN_UI_PALETTE_PATH.read_text(encoding="utf-8").split(",")]
    except Exception:
        return fallback

    if len(values) < 5:
        return fallback

    return tuple(_normalize_hex(values[index], fallback[index]) for index in range(5))  # type: ignore[return-value]


def _preferred_text_hex(background: str) -> str:
    red, green, blue = _hex_to_rgb(background)
    luminance = (0.299 * red) + (0.587 * green) + (0.114 * blue)
    return "#101722" if luminance >= 170 else "#f2f2f2"


PALETTE_ACCENT, PALETTE_SOFT, PALETTE_PANEL, PALETTE_PANEL_ALT, PALETTE_TEXT = _load_main_palette()

BG = _mix_hex(PALETTE_PANEL_ALT, "#090b12", 0.3)
SURFACE = PALETTE_PANEL
SURFACE_ALT = PALETTE_PANEL_ALT
INK = PALETTE_TEXT
MUTED = _mix_hex(PALETTE_TEXT, PALETTE_PANEL_ALT, 0.38)
BORDER = _mix_hex(PALETTE_SOFT, PALETTE_PANEL_ALT, 0.72)
ACCENT = PALETTE_ACCENT
ACCENT_STRONG = _mix_hex(PALETTE_ACCENT, "#ffffff", 0.14)
ACCENT_SOFT = _mix_hex(PALETTE_ACCENT, PALETTE_PANEL_ALT, 0.58)
ACCENT_PALE = _mix_hex(PALETTE_SOFT, PALETTE_PANEL_ALT, 0.55)
SHADOW = _mix_hex(PALETTE_PANEL_ALT, "#000000", 0.35)

if os.name == "nt":
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
else:
    _dwmapi = None
    _user32 = None


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def _set_windows_caption_theme(hwnd: int, caption_hex: str, text_hex: str) -> None:
    if _dwmapi is None or not hwnd:
        return

    attributes = (
        (35, _hex_to_colorref(caption_hex)),
        (36, _hex_to_colorref(text_hex)),
        (34, _hex_to_colorref(caption_hex)),
    )
    for attribute, value in attributes:
        color = ctypes.c_int(value)
        try:
            _dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                attribute,
                ctypes.byref(color),
                ctypes.sizeof(color),
            )
        except Exception:
            return


def _windows_work_area(hwnd: int) -> QRect | None:
    if _user32 is None or not hwnd:
        return None
    try:
        monitor = _user32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)
        if not monitor:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        work = info.rcWork
        return QRect(work.left, work.top, max(1, work.right - work.left), max(1, work.bottom - work.top))
    except Exception:
        return None


def get_qt_ui_scale(
    app: QApplication,
    base_width: int | None = None,
    base_height: int = 1080,
    min_scale: float = 0.8,
    max_scale: float = 1.8,
) -> float:
    raw = os.getenv("BA_UI_SCALE")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass

    screen = app.primaryScreen()
    if screen is None:
        return 1.0

    geometry = screen.availableGeometry()
    height = max(1, geometry.height())
    scale = height / float(base_height)
    if base_width:
        width = max(1, geometry.width())
        scale = min(scale, width / float(base_width))
    return max(min_scale, min(max_scale, scale))


def scale_px(value: int | float, scale: float) -> int:
    return max(1, int(round(float(value) * scale)))


def _school_short_label(school: str | None) -> str:
    mapping = {
        "Abydos": "ABY",
        "Arius": "ARI",
        "Gehenna": "GEH",
        "Highlander": "HIG",
        "Hyakkiyako": "HYA",
        "Millennium": "MIL",
        "RedWinter": "RED",
        "Red Winter": "RED",
        "Sakugawa": "SAK",
        "Shanhaijing": "SHA",
        "SRT": "SRT",
        "Tokiwadai": "TOK",
        "Trinity": "TRI",
        "Valkyrie": "VAL",
        "Wildhunt": "WLD",
    }
    return mapping.get((school or "").strip(), "ETC")


def _school_accent_color(school: str | None) -> str:
    mapping = {
        "Abydos": "#00bcd4",
        "Arius": "#7d8597",
        "Gehenna": "#6a1b9a",
        "Highlander": "#2a9d8f",
        "Hyakkiyako": "#ff8f00",
        "Millennium": "#1565c0",
        "RedWinter": "#d84315",
        "Red Winter": "#d84315",
        "Sakugawa": "#00897b",
        "Shanhaijing": "#ef6c00",
        "SRT": "#455a64",
        "Tokiwadai": "#5e35b1",
        "Trinity": "#f06292",
        "Valkyrie": "#546e7a",
        "Wildhunt": "#8e24aa",
    }
    return mapping.get((school or "").strip(), "#5c6ea8")


def _role_label(role: str | None) -> str:
    mapping = {
        "tanker": "Tank",
        "dealer": "Striker",
        "healer": "Healer",
        "supporter": "Support",
        "t_s": "TS",
    }
    return mapping.get((role or "").strip().lower(), "-")


def _position_label(position: str | None) -> str:
    mapping = {
        "front": "Front",
        "middle": "Middle",
        "back": "Back",
    }
    return mapping.get((position or "").strip().lower(), "-")


def _attack_color(attack_type: str | None) -> str:
    mapping = {
        "Explosive": "#920008",
        "Piercing": "#bd8901",
        "Mystic": "#226f9b",
        "Sonic": "#9945a8",
        "Break": "#228b22",
        "Demolition": "#228b22",
        "Disassembly": "#228b22",
        "Composite": "#228b22",
    }
    return mapping.get((attack_type or "").strip(), "#5c6ea8")


def _defense_accent_color(defense_type: str | None) -> str:
    mapping = {
        "Light": _attack_color("Explosive"),
        "Heavy": _attack_color("Piercing"),
        "Special": _attack_color("Mystic"),
        "Elastic": _attack_color("Sonic"),
        "Composite": "#228b22",
    }
    return mapping.get((defense_type or "").strip(), BORDER)


def _student_divider_colors(record: "StudentRecord") -> tuple[str, str]:
    primary = _attack_color(record.attack_type)
    secondary = _defense_accent_color(record.defense_type)
    return primary, secondary


def _school_logo_path(school: str | None) -> Path | None:
    mapping = {
        "Abydos": "School_Icon_ABYDOS.png",
        "Arius": "School_Icon_Arius.png",
        "ETC": "School_Icon_ETC.png",
        "Gehenna": "School_Icon_GEHENNA.png",
        "Highlander": "School_Icon_HIGHLANDER.png",
        "Hyakkiyako": "School_Icon_HYAKKIYAKO.png",
        "Millennium": "School_Icon_MILLENNIUM.png",
        "RedWinter": "School_Icon_REDWINTER.png",
        "Red Winter": "School_Icon_REDWINTER.png",
        "Sakugawa": "School_Icon_SAKUGAWA.png",
        "Shanhaijing": "School_Icon_SHANHAIJING.png",
        "SRT": "School_Icon_SRT.png",
        "Tokiwadai": "School_Icon_Tokiwadai.png",
        "Trinity": "School_Icon_TRINITY.png",
        "Valkyrie": "School_Icon_VALKYRIE.png",
        "Wildhunt": "School_Icon_WILDHUNT.png",
    }
    filename = mapping.get((school or "").strip(), "School_Icon_ETC.png")
    path = SCHOOL_LOGO_DIR / filename
    return path if path.exists() else None


def _tinted_pixmap(pixmap: QPixmap, color: str, size: QSize | None = None) -> QPixmap:
    source = pixmap
    if size is not None and size.isValid():
        source = pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if source.isNull():
        return QPixmap()
    canvas = QPixmap(source.size())
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.drawPixmap(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(canvas.rect(), QColor(color))
    painter.end()
    return canvas


class ParallelogramPanel(QWidget):
    def __init__(
        self,
        fill: str = "rgba(55, 65, 98, 0.45)",
        border: str = "#4b5b84",
        slant: float = 0.22,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._fill = QColor(fill)
        self._border = QColor(border)
        self._slant_ratio = max(0.08, min(float(slant), 0.36))
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def setColors(self, fill: str, border: str | None = None) -> None:
        self._fill = QColor(fill)
        self._border = QColor(border or fill)
        self.update()

    def _slant_for_size(self, width: int, height: int) -> int:
        return max(8, min(int(round(height * self._slant_ratio)), max(8, width // 4)))

    def edge_bounds_at_y(self, y: float) -> tuple[float, float]:
        width = max(1, self.width())
        height = max(1, self.height())
        slant = self._slant_for_size(width, height)
        progress = 0.0 if height <= 1 else max(0.0, min(1.0, y / float(height - 1)))
        left = slant * (1.0 - progress)
        right = (width - 1) - (slant * progress)
        return left, right

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        width = max(1, self.width())
        height = max(1, self.height())
        slant = self._slant_for_size(width, height)
        path = self._rounded_parallelogram_path(width, height, slant)
        painter.fillPath(path, self._fill)
        painter.setPen(QPen(self._border, 1))
        painter.drawPath(path)
        painter.end()

    @staticmethod
    def _rounded_parallelogram_path(width: int, height: int, slant: int) -> QPainterPath:
        points = [
            (float(slant), 0.0),
            (float(width - 1), 0.0),
            (float(width - slant - 1), float(height - 1)),
            (0.0, float(height - 1)),
        ]
        edge_lengths = []
        for index in range(4):
            ax, ay = points[index]
            bx, by = points[(index + 1) % 4]
            edge_lengths.append(math.hypot(bx - ax, by - ay))

        radius = max(4.0, min(height * 0.18, width * 0.12, min(edge_lengths) * 0.28))

        def _offset(point_from: tuple[float, float], point_to: tuple[float, float], distance: float) -> tuple[float, float]:
            fx, fy = point_from
            tx, ty = point_to
            length = math.hypot(tx - fx, ty - fy)
            if length <= 1e-6:
                return fx, fy
            ratio = distance / length
            return fx + ((tx - fx) * ratio), fy + ((ty - fy) * ratio)

        path = QPainterPath()
        start = _offset(points[0], points[1], radius)
        path.moveTo(*start)
        for index in (1, 2, 3, 0):
            current = points[index]
            prev_point = points[(index - 1) % 4]
            next_point = points[(index + 1) % 4]
            edge_in = _offset(current, prev_point, radius)
            edge_out = _offset(current, next_point, radius)
            path.lineTo(*edge_in)
            path.quadTo(current[0], current[1], edge_out[0], edge_out[1])
        path.closeSubpath()
        return path


class EquipmentDetailCard(ParallelogramPanel):
    def __init__(self, ui_scale: float, *, fill: str, border: str, slant: float, parent: QWidget | None = None) -> None:
        super().__init__(fill=fill, border=border, slant=slant, parent=parent)
        self._ui_scale = ui_scale
        self._icon = QPixmap()
        self._value_text = "-"
        self._caption_text = "-"
        self._value_color = QColor(INK)
        self._caption_color = QColor(MUTED)
        self.setMinimumHeight(scale_px(110, ui_scale))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setData(self, *, icon: QPixmap | None, value: str, caption: str) -> None:
        self._icon = icon or QPixmap()
        self._value_text = value
        self._caption_text = caption
        self.update()

    def clearData(self) -> None:
        self._icon = QPixmap()
        self._value_text = "-"
        self._caption_text = "-"
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        height = max(1, self.height())
        width = max(1, self.width())
        y_icon = height * 0.26
        y_value = height * 0.67
        y_caption = height * 0.84

        if not self._icon.isNull():
            icon_size = scale_px(60, self._ui_scale)
            scaled = self._icon.scaled(icon_size, icon_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            left, right = self.edge_bounds_at_y(y_icon)
            center_x = (left + right) / 2.0
            painter.drawPixmap(int(round(center_x - (scaled.width() / 2))), int(round(y_icon - (scaled.height() / 2))), scaled)

        value_font = QFont(self.font())
        value_font.setBold(True)
        value_font.setPixelSize(scale_px(24, self._ui_scale))
        painter.setFont(value_font)
        painter.setPen(self._value_color)
        value_metrics = QFontMetrics(value_font)
        value_width = min(width, value_metrics.horizontalAdvance(self._value_text) + scale_px(12, self._ui_scale))
        left, right = self.edge_bounds_at_y(y_value)
        value_center_x = (left + right) / 2.0
        value_rect = QRect(
            int(round(value_center_x - (value_width / 2))),
            int(round(y_value - scale_px(16, self._ui_scale))),
            int(round(value_width)),
            scale_px(28, self._ui_scale),
        )
        painter.drawText(value_rect, Qt.AlignCenter, self._value_text)

        caption_font = QFont(self.font())
        caption_font.setPixelSize(scale_px(12, self._ui_scale))
        painter.setFont(caption_font)
        painter.setPen(self._caption_color)
        caption_metrics = QFontMetrics(caption_font)
        left, right = self.edge_bounds_at_y(y_caption)
        caption_center_x = (left + right) / 2.0
        caption_width_limit = max(scale_px(42, self._ui_scale), int(right - left - scale_px(12, self._ui_scale)))
        caption_text = caption_metrics.elidedText(self._caption_text, Qt.ElideRight, caption_width_limit)
        caption_rect = QRect(
            int(round(caption_center_x - (caption_width_limit / 2))),
            int(round(y_caption - scale_px(10, self._ui_scale))),
            caption_width_limit,
            scale_px(18, self._ui_scale),
        )
        painter.drawText(caption_rect, Qt.AlignCenter, caption_text)
        painter.end()


class DetailProgressStrip(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._star_count = 0
        self._weapon_star_count = 0
        self._show_weapon = False
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setProgress(self, star_count: int, weapon_star_count: int, show_weapon: bool) -> None:
        self._star_count = max(0, min(5, int(star_count)))
        self._weapon_star_count = max(0, min(4, int(weapon_star_count)))
        self._show_weapon = bool(show_weapon)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        active_rect = self.rect().adjusted(0, 0, 0, -1)
        segment_gap = 4
        segment_count = 5 + (4 if self._show_weapon else 0)
        if segment_count <= 0:
            painter.end()
            return

        segment_width = max(10, int((active_rect.width() - (segment_gap * (segment_count - 1))) / segment_count))
        segment_height = max(8, active_rect.height())
        y = active_rect.y() + max(0, (active_rect.height() - segment_height) // 2)

        for index in range(segment_count):
            x = active_rect.x() + (index * (segment_width + segment_gap))
            path = ParallelogramPanel._rounded_parallelogram_path(segment_width, segment_height, max(4, int(round(segment_height * DETAIL_SLANT))))

            painter.save()
            painter.translate(x, y)
            if index < 5:
                filled = index < self._star_count
                fill = QColor("#ffd84a" if filled else _mix_hex("#ffd84a", SURFACE_ALT, 0.78))
                border = QColor("#ffe88f" if filled else _mix_hex("#ffe88f", SURFACE_ALT, 0.58))
            else:
                weapon_index = index - 5
                filled = weapon_index < self._weapon_star_count
                fill = QColor("#69c6ff" if filled else _mix_hex("#69c6ff", SURFACE_ALT, 0.8))
                border = QColor("#b6e6ff" if filled else _mix_hex("#b6e6ff", SURFACE_ALT, 0.6))
            painter.fillPath(path, fill)
            painter.setPen(QPen(border, 1))
            painter.drawPath(path)
            painter.restore()

        painter.end()


EQUIPMENT_TIER_MAX_LEVEL = {
    0: 0,
    1: 10,
    2: 20,
    3: 30,
    4: 40,
    5: 45,
    6: 50,
    7: 55,
    8: 60,
    9: 65,
    10: 70,
}


class PlanEditorCell(ParallelogramPanel):
    clicked = Signal()

    def __init__(self, label: str = "", *, compact: bool = False, ui_scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(fill=SURFACE_ALT, border=BORDER, slant=DETAIL_SLANT, parent=parent)
        self._label = label
        self._text_color = QColor(INK)
        self._current_marker = False
        self._clickable = True
        self._compact = compact
        self._ui_scale = ui_scale
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(scale_px(15 if compact else 20, self._ui_scale))

    def setCellState(
        self,
        *,
        label: str | None = None,
        fill: str,
        border: str,
        text_color: str,
        current_marker: bool = False,
        clickable: bool = True,
    ) -> None:
        if label is not None:
            self._label = label
        self.setColors(fill, border)
        self._text_color = QColor(text_color)
        self._current_marker = current_marker
        self._clickable = clickable
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._clickable and self.isEnabled():
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(scale_px(8 if self._compact else 10, self._ui_scale))
        painter.setFont(font)
        painter.setPen(self._text_color)
        rect = self.rect().adjusted(scale_px(4, self._ui_scale), 0, -scale_px(4, self._ui_scale), 0)
        painter.drawText(rect, Qt.AlignCenter, self._label)
        if self._current_marker:
            marker_h = max(2, scale_px(2, self._ui_scale))
            marker_rect = QRect(
                scale_px(6, self._ui_scale),
                self.height() - marker_h - scale_px(3, self._ui_scale),
                max(scale_px(12, self._ui_scale), self.width() - scale_px(12, self._ui_scale)),
                marker_h,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#f4fbff"))
            painter.drawRoundedRect(marker_rect, marker_h, marker_h)
        painter.end()


class PlanSegmentSelector(QWidget):
    valueChanged = Signal(int)

    def __init__(
        self,
        count: int,
        *,
        color_break: int = 0,
        active_fill: str = ACCENT_STRONG,
        active_border: str = ACCENT,
        inactive_fill: str | None = None,
        inactive_border: str | None = None,
        ui_scale: float = 1.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._count = count
        self._color_break = color_break
        self._fallback_fill = active_fill
        self._fallback_border = active_border
        self._inactive_fill = inactive_fill if inactive_fill is not None else _mix_hex(SURFACE_ALT, BG, 0.08)
        self._inactive_border = inactive_border if inactive_border is not None else _mix_hex(BORDER, SURFACE_ALT, 0.18)
        self._ui_scale = ui_scale
        self._minimum_value = 0
        self._value = 0
        self._enabled_count = count
        self._cells: list[PlanEditorCell] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(2, self._ui_scale))
        for index in range(1, count + 1):
            cell = PlanEditorCell(compact=True, ui_scale=self._ui_scale)
            cell.clicked.connect(lambda idx=index: self._on_cell_clicked(idx))
            self._cells.append(cell)
            layout.addWidget(cell, 1)
        self._refresh_cells()

    def setState(self, *, minimum_value: int, value: int, enabled_count: int | None = None) -> None:
        self._minimum_value = max(0, min(self._count, minimum_value))
        self._enabled_count = max(0, min(self._count, enabled_count if enabled_count is not None else self._count))
        self._value = max(self._minimum_value, min(self._enabled_count, value))
        self._refresh_cells()

    def value(self) -> int:
        return self._value

    def _colors_for_index(self, index: int) -> tuple[str, str]:
        if self._color_break and index > self._color_break:
            return "#69c6ff", "#b6e6ff"
        if self._color_break:
            return "#ffd84a", "#ffe88f"
        return self._fallback_fill, self._fallback_border

    def _refresh_cells(self) -> None:
        for index, cell in enumerate(self._cells, start=1):
            accent_fill, accent_border = self._colors_for_index(index)
            clickable = self.isEnabled() and index <= self._enabled_count
            if not clickable:
                fill = _mix_hex(SURFACE_ALT, BG, 0.22)
                border = _mix_hex(BORDER, SURFACE_ALT, 0.4)
                text_color = MUTED
            elif index <= self._value:
                if index <= self._minimum_value:
                    fill = _mix_hex(accent_fill, SURFACE_ALT, 0.2)
                    border = _mix_hex(accent_border, "#ffffff", 0.12)
                else:
                    fill = accent_fill
                    border = accent_border
                text_color = "#112031"
            else:
                fill = self._inactive_fill
                border = self._inactive_border
                text_color = MUTED
            cell.setCellState(fill=fill, border=border, text_color=text_color, clickable=clickable)

    def _on_cell_clicked(self, index: int) -> None:
        if index > self._enabled_count:
            return
        candidate = max(self._minimum_value, index)
        if index == self._value:
            candidate = max(self._minimum_value, index - 1)
        if candidate == self._value:
            return
        self._value = candidate
        self._refresh_cells()
        self.valueChanged.emit(candidate)


class PlanOptionStrip(QWidget):
    valueClicked = Signal(int)

    def __init__(self, options: list[int], *, compact: bool = True, ui_scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = list(options)
        self._selected_value = self._options[0] if self._options else 0
        self._current_value: int | None = None
        self._enabled_values: set[int] = set(self._options)
        self._ui_scale = ui_scale
        self._cells: dict[int, PlanEditorCell] = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(4, self._ui_scale))
        for option in self._options:
            cell = PlanEditorCell(str(option), compact=compact, ui_scale=self._ui_scale)
            cell.clicked.connect(lambda value=option: self.valueClicked.emit(value))
            self._cells[option] = cell
            layout.addWidget(cell, 1)
        self._refresh_cells()

    def setState(self, *, selected_value: int, current_value: int | None = None, enabled_values: set[int] | None = None) -> None:
        self._selected_value = selected_value
        self._current_value = current_value
        self._enabled_values = set(self._options if enabled_values is None else enabled_values)
        self._refresh_cells()

    def _refresh_cells(self) -> None:
        for value, cell in self._cells.items():
            enabled = self.isEnabled() and value in self._enabled_values
            is_selected = value == self._selected_value
            is_current = self._current_value is not None and value == self._current_value
            if not enabled:
                fill = _mix_hex(SURFACE_ALT, BG, 0.22)
                border = _mix_hex(BORDER, SURFACE_ALT, 0.4)
                text_color = MUTED
            elif is_selected:
                fill = ACCENT_STRONG
                border = ACCENT
                text_color = "#ffffff"
            elif is_current:
                fill = _mix_hex(PALETTE_SOFT, SURFACE_ALT, 0.44)
                border = _mix_hex("#ffffff", PALETTE_SOFT, 0.22)
                text_color = INK
            else:
                fill = _mix_hex(SURFACE_ALT, BG, 0.08)
                border = _mix_hex(BORDER, SURFACE_ALT, 0.18)
                text_color = MUTED
            cell.setCellState(
                fill=fill,
                border=border,
                text_color=text_color,
                current_marker=is_current and not is_selected,
                clickable=enabled,
            )


class PlanStepper(QWidget):
    valueChanged = Signal(int)

    def __init__(self, max_value: int, *, ui_scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_value = max_value
        self._ui_scale = ui_scale
        self._minimum_value = 0
        self._value = 0
        self._updating = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(8, self._ui_scale))

        self._input = QLineEdit("0")
        self._input.setObjectName("planValueInput")
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setValidator(QIntValidator(0, self._max_value, self))
        self._input.setMinimumHeight(scale_px(34, self._ui_scale))
        self._input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._input.textEdited.connect(self._on_text_edited)
        self._input.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self._input, 1)

        self._min_label = QLabel("MIN 0")
        self._min_label.setObjectName("detailMiniSub")
        self._min_label.setAlignment(Qt.AlignCenter)
        self._min_label.setMinimumWidth(scale_px(52, self._ui_scale))
        layout.addWidget(self._min_label)

        self._max_button = QPushButton("MAX")
        self._max_button.setObjectName("planQuickButton")
        self._max_button.setMinimumHeight(scale_px(34, self._ui_scale))
        self._max_button.setMinimumWidth(scale_px(54, self._ui_scale))
        self._max_button.clicked.connect(self._set_to_max)
        layout.addWidget(self._max_button)

        self._refresh()

    def setState(self, *, minimum_value: int, value: int) -> None:
        self._minimum_value = max(0, min(self._max_value, minimum_value))
        self._value = max(self._minimum_value, min(self._max_value, value))
        self._refresh()

    def value(self) -> int:
        return self._value

    def setMaximumValue(self, maximum_value: int) -> None:
        self._max_value = max(0, int(maximum_value))
        self._input.setValidator(QIntValidator(0, self._max_value, self))
        self._minimum_value = min(self._minimum_value, self._max_value)
        self._value = min(self._value, self._max_value)
        self._refresh()

    def setEnabled(self, enabled: bool) -> None:
        super().setEnabled(enabled)
        self._refresh()

    def _commit_value(self, candidate: int, *, emit_signal: bool) -> None:
        candidate = max(self._minimum_value, min(self._max_value, int(candidate)))
        changed = candidate != self._value
        self._value = candidate
        self._refresh()
        if emit_signal and changed:
            self.valueChanged.emit(candidate)

    def _on_text_edited(self, text: str) -> None:
        if self._updating:
            return
        stripped = text.strip()
        if not stripped:
            return
        self._commit_value(int(stripped), emit_signal=True)

    def _on_editing_finished(self) -> None:
        text = self._input.text().strip()
        if not text:
            self._refresh()
            return
        self._commit_value(int(text), emit_signal=True)

    def _set_to_max(self) -> None:
        if not self.isEnabled():
            return
        self._commit_value(self._max_value, emit_signal=True)

    def _refresh(self) -> None:
        self._updating = True
        try:
            self._input.setText(str(self._value))
        finally:
            self._updating = False
        self._input.setPlaceholderText(str(self._minimum_value))
        self._min_label.setText(f"MIN {self._minimum_value}")
        enabled = self.isEnabled()
        self._input.setEnabled(enabled)
        self._max_button.setEnabled(enabled and self._value < self._max_value)


class PlanDualDigitSelector(QWidget):
    valueChanged = Signal(int)

    def __init__(self, max_value: int, *, ui_scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._max_value = max_value
        self._ui_scale = ui_scale
        self._minimum_value = 0
        self._value = 0
        self._tens_options = list(range((max_value // 10) + 1))
        self._tens_strip = PlanOptionStrip(self._tens_options, ui_scale=self._ui_scale)
        self._ones_strip = PlanOptionStrip(list(range(10)), ui_scale=self._ui_scale)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(6, self._ui_scale))

        tens_caption = QLabel("10s")
        tens_caption.setObjectName("detailSectionTitle")
        layout.addWidget(tens_caption)
        self._tens_strip.valueClicked.connect(self._on_tens_clicked)
        layout.addWidget(self._tens_strip)

        ones_caption = QLabel("1s")
        ones_caption.setObjectName("detailSectionTitle")
        layout.addWidget(ones_caption)
        self._ones_strip.valueClicked.connect(self._on_ones_clicked)
        layout.addWidget(self._ones_strip)

    def setState(self, *, minimum_value: int, value: int) -> None:
        self._minimum_value = max(0, min(self._max_value, minimum_value))
        self._value = max(self._minimum_value, min(self._max_value, value))
        self._refresh_strips()

    def value(self) -> int:
        return self._value

    def setMaximumValue(self, maximum_value: int) -> None:
        self._max_value = max(0, int(maximum_value))
        self._tens_options = list(range((self._max_value // 10) + 1))
        self._minimum_value = min(self._minimum_value, self._max_value)
        self._value = min(self._value, self._max_value)
        self._refresh_strips()

    def _refresh_strips(self) -> None:
        current_tens, current_ones = divmod(self._minimum_value, 10)
        selected_tens, selected_ones = divmod(self._value, 10)
        max_ones = self._max_value - (selected_tens * 10) if selected_tens == max(self._tens_options) else 9
        enabled_ones = {value for value in range(max(0, min(9, max_ones)) + 1)}
        self._tens_strip.setState(selected_value=selected_tens, current_value=current_tens, enabled_values=set(self._tens_options))
        self._ones_strip.setState(selected_value=selected_ones, current_value=current_ones, enabled_values=enabled_ones)

    def _apply_candidate(self, candidate: int) -> None:
        clamped = max(self._minimum_value, min(self._max_value, candidate))
        if clamped == self._value:
            self._refresh_strips()
            return
        self._value = clamped
        self._refresh_strips()
        self.valueChanged.emit(clamped)

    def _on_tens_clicked(self, tens: int) -> None:
        ones = self._value % 10
        self._apply_candidate((tens * 10) + ones)

    def _on_ones_clicked(self, ones: int) -> None:
        tens = self._value // 10
        self._apply_candidate((tens * 10) + ones)


def _parse_tier_number(tier: str | None) -> int | None:
    value = (tier or "").strip().upper()
    if not value.startswith("T"):
        return None
    try:
        return int(value[1:])
    except ValueError:
        return None


def _equipment_icon_path(student_id: str, slot_index: int, tier: str | None) -> Path | None:
    tier_number = _parse_tier_number(tier)
    if tier_number is None:
        return None
    slots = student_meta.equipment_slots(student_id)
    if slot_index < 1 or slot_index > len(slots):
        return None
    slot_name = slots[slot_index - 1]
    if not slot_name:
        return None
    path = EQUIPMENT_ICON_DIR / f"Equipment_Icon_{slot_name}_Tier{tier_number}.png"
    return path if path.exists() else None


def _inventory_name_token(value: str | None) -> str:
    return "".join(str(value or "").split()).lower()


def _report_icon_token(name: str | None) -> str | None:
    return _REPORT_NAME_TO_ICON.get(_inventory_name_token(name))


def _report_icon_for_entry(item_id: str | None, name: str | None) -> str | None:
    if item_id:
        icon_token = _REPORT_ID_TO_ICON.get(item_id)
        if icon_token:
            return icon_token
    return _report_icon_token(name)


def _inventory_icon_path(item_id: str | None, name: str | None) -> Path | None:
    report_icon = _report_icon_for_entry(item_id, name)
    if report_icon:
        path = POLI_BG_DIR / f"{report_icon}.png"
        if path.exists():
            return path

    if item_id:
        if item_id in _WORKBOOK_ID_TO_NAME:
            path = POLI_BG_DIR / f"{item_id}.png"
            if path.exists():
                return path
        if item_id.startswith("Item_Icon_SkillBook_"):
            path = INVENTORY_DETAIL_DIR / "tech_notes" / f"{item_id}.png"
            if path.exists():
                return path
        if item_id.startswith("Item_Icon_Material_ExSkill_"):
            path = INVENTORY_DETAIL_DIR / "tactical_bd" / f"{item_id}.png"
            if path.exists():
                return path
        if item_id in _OPART_ITEM_IDS or item_id in _WB_ITEM_IDS:
            path = INVENTORY_DETAIL_DIR / "ooparts" / f"{item_id}.png"
            if path.exists():
                return path
        if item_id.startswith("Equipment_Icon_") and "_Tier" in item_id:
            path = INVENTORY_DETAIL_DIR / "equipment" / f"{item_id}.png"
            if path.exists():
                return path
        if item_id.startswith("Equipment_Icon_Exp_") or item_id.startswith("Equipment_Icon_WeaponExpGrowth"):
            path = POLI_BG_DIR / f"{item_id}.png"
            if path.exists():
                return path

    if name:
        path = INVENTORY_DETAIL_DIR / "ooparts" / f"{name}.png"
        if path.exists():
            return path
        path = INVENTORY_DETAIL_DIR / "activity_reports" / f"{name}.png"
        if path.exists():
            return path

    return None


def _inventory_quantity_value(raw_quantity: object) -> int | None:
    try:
        if raw_quantity in (None, ""):
            return None
        return int(str(raw_quantity).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _inventory_display_label(item_key: str, payload: dict) -> str:
    item_id = payload.get("item_id")
    if item_id:
        item_id_text = str(item_id)
        report_icon = _REPORT_ID_TO_ICON.get(item_id_text)
        if report_icon:
            return _REPORT_ICON_TO_NAME.get(report_icon, item_id_text)
        workbook_name = _WORKBOOK_ID_TO_NAME.get(item_id_text)
        if workbook_name:
            return workbook_name
    display_name = inventory_item_display_name(str(item_id)) if item_id else None
    return str(display_name or payload.get("name") or item_key)


def _load_ui_font_family() -> str | None:
    if not UI_FONT_PATH.exists():
        return None
    font_id = QFontDatabase.addApplicationFont(str(UI_FONT_PATH))
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    return families[0] if families else None


def _int_or_none(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class StudentRecord:
    student_id: str
    display_name: str
    owned: bool
    farmable: str | None
    level: int | None
    star: int
    weapon_state: str | None
    weapon_star: int | None
    weapon_level: int | None
    ex_skill: int | None
    skill1: int | None
    skill2: int | None
    skill3: int | None
    equip1: str | None
    equip2: str | None
    equip3: str | None
    equip4: str | None
    equip1_level: int | None
    equip2_level: int | None
    equip3_level: int | None
    stat_hp: int | None
    stat_atk: int | None
    stat_heal: int | None
    school: str | None
    rarity: str | None
    attack_type: str | None
    defense_type: str | None
    combat_class: str | None
    role: str | None
    position: str | None
    weapon_type: str | None
    cover_type: str | None
    range_type: str | None

    @property
    def title(self) -> str:
        return self.display_name or self.student_id


def load_students() -> list[StudentRecord]:
    records_by_id: dict[str, StudentRecord] = {}
    paths = get_storage_paths()
    db_path = paths.db_path
    current_json = paths.current_students_json

    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM students ORDER BY student_id").fetchall()
            conn.close()
            for row in rows:
                record = _row_to_record(dict(row), owned=True)
                records_by_id[record.student_id] = record
        except Exception:
            pass

    if not records_by_id and current_json.exists():
        try:
            payload = json.loads(current_json.read_text(encoding="utf-8"))
            for value in payload.values():
                record = _row_to_record(value, owned=True)
                records_by_id[record.student_id] = record
        except Exception:
            pass

    for student_id in student_meta.all_ids():
        if student_id not in records_by_id:
            records_by_id[student_id] = _row_to_record({"student_id": student_id}, owned=False)

    return list(records_by_id.values())


def load_inventory_snapshot() -> dict[str, dict]:
    paths = get_storage_paths()
    inventory_json = paths.current_inventory_json
    payload: dict[str, dict] = {}
    loaded_from_db = False

    db_path = paths.db_path
    if db_path.exists():
        try:
            init_db(db_path)
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT item_key, item_id, name, quantity, item_index, item_source, last_seen_at, last_scan_id
                FROM inventory_current
                ORDER BY COALESCE(item_index, 999999), item_key
                """
            ).fetchall()
            conn.close()
            if rows:
                payload = {
                    str(row["item_key"]): {
                        "item_id": row["item_id"],
                        "name": row["name"],
                        "quantity": row["quantity"],
                        "index": row["item_index"],
                        "item_source": row["item_source"],
                        "last_seen_at": row["last_seen_at"],
                        "last_scan_id": row["last_scan_id"],
                    }
                    for row in rows
                }
                loaded_from_db = True
        except Exception:
            payload = {}

    if not payload:
        if not inventory_json.exists():
            return {}
        try:
            raw_payload = json.loads(inventory_json.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw_payload, dict):
            return {}
        payload = raw_payload

    def _looks_like_inventory_id(value: object) -> bool:
        return isinstance(value, str) and ("_Icon_" in value or value.startswith("Item_"))

    def _entry_rank(entry: dict) -> tuple[int, int, int, int]:
        quantity = str(entry.get("quantity") or "").strip()
        return (
            int(quantity not in ("", "0")),
            int(bool(entry.get("item_id"))),
            int(bool(entry.get("last_seen_at"))),
            len(quantity),
        )

    normalized: dict[str, dict] = {}
    changed = False
    for key, raw_value in payload.items():
        if not isinstance(raw_value, dict):
            continue
        entry = dict(raw_value)
        key_text = str(key)
        item_id = entry.get("item_id") or (key_text if _looks_like_inventory_id(key_text) else None)
        if item_id and entry.get("item_id") != item_id:
            entry["item_id"] = item_id
            changed = True
        display_name = inventory_item_display_name(str(item_id)) if item_id else None
        if display_name and entry.get("name") != display_name:
            entry["name"] = display_name
            changed = True
        canonical_key = str(item_id or entry.get("name") or key_text)
        if canonical_key != key_text:
            changed = True
        current = normalized.get(canonical_key)
        if current is None or _entry_rank(entry) > _entry_rank(current):
            primary, secondary = entry, current
        else:
            primary, secondary = current, entry
        if secondary:
            primary = dict(primary)
            for merge_key in ("item_id", "name", "quantity", "index", "item_source", "last_seen_at", "last_scan_id"):
                if primary.get(merge_key) in (None, "") and secondary.get(merge_key) not in (None, ""):
                    primary[merge_key] = secondary.get(merge_key)
                    changed = True
        normalized[canonical_key] = primary

    if changed:
        try:
            inventory_json.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    if not loaded_from_db and normalized:
        try:
            init_db(db_path)
            conn = sqlite3.connect(db_path)
            with conn:
                conn.execute("DELETE FROM inventory_current")
                conn.executemany(
                    """
                    INSERT INTO inventory_current (
                        item_key, item_id, name, quantity,
                        item_index, item_source, last_seen_at, last_scan_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            item_key,
                            entry.get("item_id"),
                            entry.get("name"),
                            entry.get("quantity"),
                            entry.get("index"),
                            entry.get("item_source"),
                            entry.get("last_seen_at"),
                            entry.get("last_scan_id"),
                        )
                        for item_key, entry in normalized.items()
                    ],
                )
            conn.close()
        except Exception:
            pass

    return normalized


def _row_to_record(row: dict, owned: bool) -> StudentRecord:
    student_id = row.get("student_id") or ""
    canonical_name = student_meta.field(student_id, "display_name")
    return StudentRecord(
        student_id=student_id,
        display_name=canonical_name or row.get("display_name") or student_id or "",
        owned=owned,
        farmable=row.get("farmable") or student_meta.field(student_id, "farmable"),
        level=row.get("level"),
        star=int(row.get("student_star") or 0),
        weapon_state=row.get("weapon_state"),
        weapon_star=row.get("weapon_star"),
        weapon_level=row.get("weapon_level"),
        ex_skill=row.get("ex_skill"),
        skill1=row.get("skill1"),
        skill2=row.get("skill2"),
        skill3=row.get("skill3"),
        equip1=row.get("equip1"),
        equip2=row.get("equip2"),
        equip3=row.get("equip3"),
        equip4=row.get("equip4"),
        equip1_level=row.get("equip1_level"),
        equip2_level=row.get("equip2_level"),
        equip3_level=row.get("equip3_level"),
        stat_hp=row.get("stat_hp"),
        stat_atk=row.get("stat_atk"),
        stat_heal=row.get("stat_heal"),
        school=row.get("school") or student_meta.field(student_id, "school"),
        rarity=row.get("rarity") or student_meta.field(student_id, "rarity"),
        attack_type=row.get("attack_type") or student_meta.field(student_id, "attack_type"),
        defense_type=row.get("defense_type") or student_meta.field(student_id, "defense_type"),
        combat_class=row.get("combat_class") or student_meta.field(student_id, "combat_class"),
        role=row.get("role") or student_meta.field(student_id, "role"),
        position=row.get("position") or student_meta.field(student_id, "position"),
        weapon_type=row.get("weapon_type") or student_meta.field(student_id, "weapon_type"),
        cover_type=row.get("cover_type") or student_meta.field(student_id, "cover_type"),
        range_type=row.get("range_type") or student_meta.field(student_id, "range_type"),
    )


def portrait_path(student_id: str) -> Path | None:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = PORTRAIT_DIR / f"{student_id}{ext}"
        if path.exists():
            return path
    return None


def thumb_cache_path(student_id: str, width: int, height: int) -> Path:
    return BASE_DIR / "cache" / "student_thumbs" / THUMB_STYLE_VERSION / f"{width}x{height}" / f"{student_id}.png"


def _render_card_portrait(student_id: str, source: Path, width: int, height: int) -> Image.Image:
    with Image.open(source) as img:
        portrait = img.convert("RGBA")

    if portrait.width <= 0 or portrait.height <= 0:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))

    alpha = portrait.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        portrait = portrait.crop(bbox)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    scale = min((width * 0.98) / portrait.width, (height * 0.98) / portrait.height)
    scaled = portrait.resize(
        (
            max(1, int(round(portrait.width * scale))),
            max(1, int(round(portrait.height * scale))),
        ),
        Image.LANCZOS,
    )
    offset = (
        (width - scaled.width) // 2,
        (height - scaled.height) // 2,
    )
    canvas.paste(scaled, offset, scaled)
    return canvas


def ensure_thumbnail(student_id: str, width: int = 128, height: int | None = None) -> Path | None:
    if not HAS_PIL:
        return portrait_path(student_id)
    if height is None:
        height = width

    source = portrait_path(student_id)
    if source is None:
        return None

    target = thumb_cache_path(student_id, width, height)
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        canvas = _render_card_portrait(student_id, source, width, height)
        canvas.save(target, format="PNG")
        return target
    except Exception:
        return source


def make_placeholder_icon(width: int = 128, height: int | None = None) -> QIcon:
    if height is None:
        height = width
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    return QIcon(pixmap)


def make_unowned_icon(student_id: str, width: int = 128, height: int | None = None) -> QIcon:
    if height is None:
        height = width
    source = ensure_thumbnail(student_id, width, height)
    if source and source.exists():
        pixmap = QPixmap(str(source))
        if not pixmap.isNull():
            return QIcon(_make_dimmed_pixmap(pixmap.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation), width, height))
    return QIcon(_make_dimmed_pixmap(QPixmap(width, height), width, height, fill="#1a2430"))


def _make_dimmed_pixmap(pixmap: QPixmap, width: int, height: int, fill: str | None = None) -> QPixmap:
    canvas = QPixmap(width, height)
    canvas.fill(QColor(fill or Qt.transparent))
    painter = QPainter(canvas)
    x = max(0, (width - pixmap.width()) // 2)
    y = max(0, (height - pixmap.height()) // 2)
    painter.setOpacity(0.35)
    painter.drawPixmap(x, y, pixmap)
    painter.setOpacity(1.0)
    painter.fillRect(canvas.rect(), QColor(0, 0, 0, 96))
    painter.setPen(QColor("#d8e7f3"))
    painter.drawText(canvas.rect(), Qt.AlignCenter, "UNOWNED")
    painter.end()
    return canvas


class ThumbSignals(QObject):
    loaded = Signal(str, str, int, int)


class ThumbTask(QRunnable):
    def __init__(self, student_id: str, width: int, height: int):
        super().__init__()
        self.student_id = student_id
        self.width = width
        self.height = height
        self.signals = ThumbSignals()

    def run(self) -> None:
        path = ensure_thumbnail(self.student_id, self.width, self.height)
        self.signals.loaded.emit(self.student_id, str(path) if path else "", self.width, self.height)


class FilterDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        filter_options: dict[str, list],
        selected_filters: dict[str, set[str]],
        ui_scale: float,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Student Filters")
        self.resize(scale_px(740, ui_scale), scale_px(760, ui_scale))
        self._checkboxes: dict[str, list[tuple[str, QCheckBox]]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            scale_px(16, ui_scale),
            scale_px(16, ui_scale),
            scale_px(16, ui_scale),
            scale_px(16, ui_scale),
        )
        layout.setSpacing(scale_px(12, ui_scale))

        intro = QLabel("Select one or more values in each attribute. Students must match every populated attribute.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(scale_px(10, ui_scale))

        for key in FILTER_FIELD_ORDER:
            options = filter_options.get(key) or []
            if not options:
                continue
            group = QGroupBox(FILTER_FIELD_LABELS[key])
            group_layout = QGridLayout(group)
            group_layout.setContentsMargins(
                scale_px(12, ui_scale),
                scale_px(12, ui_scale),
                scale_px(12, ui_scale),
                scale_px(12, ui_scale),
            )
            group_layout.setHorizontalSpacing(scale_px(12, ui_scale))
            group_layout.setVerticalSpacing(scale_px(8, ui_scale))
            pairs: list[tuple[str, QCheckBox]] = []
            for index, option in enumerate(options):
                checkbox = QCheckBox(option.label)
                checkbox.setChecked(option.value in selected_filters.get(key, set()))
                group_layout.addWidget(checkbox, index // 3, index % 3)
                pairs.append((option.value, checkbox))
            self._checkboxes[key] = pairs
            body_layout.addWidget(group)

        body_layout.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Reset
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self._reset)
        layout.addWidget(buttons)

    def selected_filters(self) -> dict[str, set[str]]:
        return {
            key: {value for value, checkbox in pairs if checkbox.isChecked()}
            for key, pairs in self._checkboxes.items()
        }

    def _reset(self) -> None:
        for pairs in self._checkboxes.values():
            for _value, checkbox in pairs:
                checkbox.setChecked(False)


class ResourceStudentListItem(QWidget):
    toggled = Signal(str, bool)

    def __init__(self, student_id: str, *, ui_scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.student_id = student_id
        self._ui_scale = ui_scale
        self.setObjectName("planBand")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            scale_px(12, self._ui_scale),
            scale_px(10, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(10, self._ui_scale),
        )
        layout.setSpacing(scale_px(10, self._ui_scale))

        self._check = QCheckBox()
        self._check.stateChanged.connect(lambda state: self.toggled.emit(self.student_id, state == Qt.Checked))
        layout.addWidget(self._check, 0, Qt.AlignTop)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(scale_px(3, self._ui_scale))

        self._title = QLabel(student_id)
        self._title.setObjectName("sectionTitle")
        text_wrap.addWidget(self._title)

        self._status = QLabel("")
        self._status.setObjectName("detailSub")
        self._status.setWordWrap(True)
        text_wrap.addWidget(self._status)

        self._cost = QLabel("")
        self._cost.setObjectName("detailMiniSub")
        self._cost.setWordWrap(True)
        text_wrap.addWidget(self._cost)

        layout.addLayout(text_wrap, 1)

    def setChecked(self, checked: bool) -> None:
        previous = self._check.blockSignals(True)
        try:
            self._check.setChecked(checked)
        finally:
            self._check.blockSignals(previous)

    def setTexts(self, *, title: str, status: str, cost: str) -> None:
        self._title.setText(title)
        self._status.setText(status)
        self._cost.setText(cost)


class InventoryListItem(QFrame):
    def __init__(self, *, ui_scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_scale = ui_scale
        self.setObjectName("planBand")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            scale_px(12, self._ui_scale),
            scale_px(10, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(10, self._ui_scale),
        )
        layout.setSpacing(scale_px(10, self._ui_scale))

        self._icon = QLabel()
        self._icon.setFixedSize(scale_px(44, self._ui_scale), scale_px(44, self._ui_scale))
        self._icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon, 0, Qt.AlignVCenter)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(scale_px(2, self._ui_scale))

        self._name = QLabel("-")
        self._name.setObjectName("sectionTitle")
        self._name.setWordWrap(True)
        text_wrap.addWidget(self._name)

        self._meta = QLabel("")
        self._meta.setObjectName("detailMiniSub")
        self._meta.setWordWrap(True)
        text_wrap.addWidget(self._meta)
        layout.addLayout(text_wrap, 1)

        self._quantity = QLabel("-")
        self._quantity.setObjectName("detailMiniValue")
        self._quantity.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._quantity, 0, Qt.AlignVCenter)

    def setData(self, *, icon_path: Path | None, name: str, quantity: str, meta: str = "") -> None:
        self._name.setText(name)
        self._quantity.setText(quantity)
        self._meta.setText(meta)

        if icon_path is not None and icon_path.exists():
            pixmap = QPixmap(str(icon_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(self._icon.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._icon.setPixmap(scaled)
                return
        self._icon.setPixmap(QPixmap())




class StudentViewerWindow(QMainWindow):
    def __init__(self, ui_scale: float):
        super().__init__()
        self._ui_scale = ui_scale
        self._startup_window_applied = False
        self._applying_work_area = False
        self._detail_panel: QFrame | None = None
        self._detail_scroll: QScrollArea | None = None
        self._hero_wrap: QFrame | None = None
        self._student_card_asset = ParallelogramCardAsset(build_card_style(CARD_BUTTON_ASSET, ui_scale))
        self._card_button_style = build_card_button_style(CARD_BUTTON_ASSET, ui_scale)
        self._base_thumb_width = scale_px(self._student_card_asset.base_size.width(), ui_scale)
        self._thumb_width = self._base_thumb_width
        self._thumb_height = scale_px(self._student_card_asset.base_size.height(), ui_scale)
        outer_margin = self._student_card_asset.style.outer_margin * 2
        self._grid_width = self._thumb_width + outer_margin
        self._grid_height = self._thumb_height + outer_margin
        self.setWindowTitle("Blue Archive Planner")
        self.resize(scale_px(1560, ui_scale), scale_px(980, ui_scale))

        self._pool = QThreadPool.globalInstance()
        self._all_students = load_students()
        self._records_by_id = {record.student_id: record for record in self._all_students}
        self._filtered_students = list(self._all_students)
        self._item_by_id: dict[str, StudentCardWidget] = {}
        self._plan_card_by_id: dict[str, StudentCardWidget] = {}
        self._thumb_loading: set[tuple[str, int, int]] = set()
        self._pending_thumb_requests: list[tuple[str, int, int]] = []
        self._pending_thumb_lookup: set[tuple[str, int, int]] = set()
        self._thumb_batch_size = 16
        self._placeholder_icon = make_placeholder_icon(self._thumb_width, self._thumb_height)
        self._unowned_icon_cache: dict[str, QIcon] = {}
        self._large_pixmap: QPixmap | None = None
        self._selected_filters: dict[str, set[str]] = {key: set() for key in FILTER_FIELD_ORDER}
        self._filter_options = build_filter_options(self._all_students)
        self._plan_path = get_storage_paths().current_dir / "growth_plan.json"
        self._plan = load_plan(self._plan_path)
        self._plan_editor_guard = False
        self._selected_plan_student_id: str | None = None
        self._plan_segment_inputs: dict[str, PlanSegmentSelector] = {}
        self._plan_level_inputs: dict[str, PlanStepper] = {}
        self._plan_level_rows: dict[str, QWidget] = {}
        self._plan_level_row_labels: dict[str, QLabel] = {}
        self._plan_equipment_labels: dict[str, QLabel] = {}
        self._plan_stat_rows: dict[str, QWidget] = {}
        self._resource_selected_ids: set[str] = set()
        self._resource_current_student_id: str | None = None
        self._resource_syncing_controls = False
        self._inventory_snapshot = load_inventory_snapshot()
        storage_paths = get_storage_paths()
        self._storage_watch_paths = (
            storage_paths.current_students_json,
            storage_paths.current_inventory_json,
            self._plan_path,
        )
        self._storage_mtimes = self._snapshot_storage_mtimes()
        self._stats_cards_layout: QGridLayout | None = None
        self._stats_summary_host: QWidget | None = None
        self._card_layout_guard = False
        self._thumb_pump = QTimer(self)
        self._thumb_pump.setSingleShot(False)
        self._thumb_pump.setInterval(0)
        self._thumb_pump.timeout.connect(self._drain_thumb_queue)
        self._storage_watch_timer = QTimer(self)
        self._storage_watch_timer.setSingleShot(False)
        self._storage_watch_timer.setInterval(1000)
        self._storage_watch_timer.timeout.connect(self._poll_storage_changes)
        self._storage_watch_timer.start()

        self._build_ui()
        self._apply_filters()
        self._refresh_plan_lists()
        self._refresh_plan_totals()
        self._refresh_stats_tab()
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._startup_window_applied:
            return
        self._startup_window_applied = True
        QTimer.singleShot(0, self._apply_startup_window_state)

    def _snapshot_storage_mtimes(self) -> dict[Path, int | None]:
        mtimes: dict[Path, int | None] = {}
        for path in self._storage_watch_paths:
            try:
                mtimes[path] = path.stat().st_mtime_ns
            except OSError:
                mtimes[path] = None
        return mtimes

    def _poll_storage_changes(self) -> None:
        current_mtimes = self._snapshot_storage_mtimes()
        if current_mtimes == self._storage_mtimes:
            return
        self._storage_mtimes = current_mtimes
        self._reload_data()

    def _apply_startup_window_state(self) -> None:
        self._apply_work_area_geometry()
        QTimer.singleShot(0, self._sync_hero_height)
        if os.name == "nt":
            self.winId()
            _set_windows_caption_theme(int(self.winId()), PALETTE_SOFT, _preferred_text_hex(PALETTE_SOFT))

    def _apply_work_area_geometry(self) -> None:
        screen = self.windowHandle().screen() if self.windowHandle() else QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QRect()
        if os.name == "nt":
            self.winId()
            work_area = _windows_work_area(int(self.winId()))
            if work_area is not None:
                available = work_area
        if available.isEmpty():
            return
        self._applying_work_area = True
        try:
            self.setWindowState(self.windowState() & ~Qt.WindowMaximized)
            self.setGeometry(available)
            self.move(available.topLeft())
            self.resize(available.size())
        finally:
            self._applying_work_area = False

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("viewerRoot")
        self.setCentralWidget(root)

        outer_layout = QVBoxLayout(root)
        outer_layout.setContentsMargins(
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
        )
        outer_layout.setSpacing(scale_px(12, self._ui_scale))

        tabs = QTabWidget()
        tabs.setObjectName("mainTabs")
        outer_layout.addWidget(tabs, 1)

        students_tab = QWidget()
        tabs.addTab(students_tab, "Students")
        self._build_students_tab(students_tab)

        plan_tab = QWidget()
        tabs.addTab(plan_tab, "Plans")
        self._build_plan_tab(plan_tab)

        resource_tab = QWidget()
        tabs.addTab(resource_tab, "Resources")
        self._build_resource_tab(resource_tab)

        inventory_tab = QWidget()
        tabs.addTab(inventory_tab, "Inventory")
        self._build_inventory_tab(inventory_tab)

        stats_tab = QWidget()
        tabs.addTab(stats_tab, "Statistics")
        self._build_stats_tab(stats_tab)

        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background: {BG}; color: {INK}; }}
            QLabel {{ background: transparent; }}
            QTabWidget::pane {{
                border: 1px solid {BORDER};
                border-radius: {scale_px(18, self._ui_scale)}px;
                background: {SURFACE};
                top: -1px;
            }}
            QTabBar::tab {{
                background: transparent;
                color: {MUTED};
                padding: {scale_px(10, self._ui_scale)}px {scale_px(14, self._ui_scale)}px;
                margin-right: {scale_px(6, self._ui_scale)}px;
                border-radius: {scale_px(10, self._ui_scale)}px;
            }}
            QTabBar::tab:hover {{
                background: {ACCENT_SOFT};
                color: {INK};
            }}
            QTabBar::tab:selected {{
                background: {ACCENT_PALE};
                color: {ACCENT_STRONG};
                font-weight: 700;
            }}
            QFrame#header, QFrame#panel, QFrame#statPanel, QFrame#summaryCard {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: {scale_px(14, self._ui_scale)}px;
            }}
            QFrame#heroWrap {{
                background: {SURFACE_ALT};
                border: 1px solid {BORDER};
                border-radius: {scale_px(18, self._ui_scale)}px;
            }}
            QLabel#title {{ font-size: {scale_px(24, self._ui_scale)}px; font-weight: 800; color: {INK}; }}
            QLabel#count, QLabel#detailSub, QLabel#filterSummary, QLabel#sectionSub, QLabel#kpiValueSub {{ color: {MUTED}; }}
            QLabel#sectionTitle {{ font-size: {scale_px(15, self._ui_scale)}px; font-weight: 800; color: {INK}; }}
            QLabel#badge {{
                background: {ACCENT_PALE};
                color: {ACCENT_STRONG};
                border: 1px solid {ACCENT_SOFT};
                border-radius: {scale_px(9, self._ui_scale)}px;
                padding: {scale_px(4, self._ui_scale)}px {scale_px(8, self._ui_scale)}px;
            }}
            QLabel#metricValue {{ font-size: {scale_px(22, self._ui_scale)}px; font-weight: 800; color: {INK}; }}
            QLabel#metricLabel {{ color: {MUTED}; font-size: {scale_px(11, self._ui_scale)}px; text-transform: uppercase; }}
            QLineEdit, QComboBox, QPushButton {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: {scale_px(9, self._ui_scale)}px;
                padding: {scale_px(8, self._ui_scale)}px {scale_px(10, self._ui_scale)}px;
                min-height: {scale_px(22, self._ui_scale)}px;
            }}
            QPushButton {{
                background: {ACCENT};
                color: white;
                border: 1px solid {ACCENT_STRONG};
                font-weight: 700;
            }}
            QPushButton:hover {{ background: {ACCENT_STRONG}; }}
            QComboBox, QLineEdit {{
                background: {SURFACE_ALT};
                color: {INK};
            }}
            QCheckBox {{
                color: {MUTED};
                spacing: {scale_px(8, self._ui_scale)}px;
            }}
            QListWidget {{
                background: {SURFACE_ALT};
                border: 1px solid {BORDER};
                border-radius: {scale_px(12, self._ui_scale)}px;
                padding: 0px;
            }}
            QListWidget::item {{
                background: transparent;
                border: none;
                padding: 0px;
            }}
            QListWidget::item:selected {{
                background: transparent;
                border: none;
            }}
            QAbstractItemView {{
                selection-background-color: transparent;
            }}
            QLabel#hero {{
                background: transparent;
                border: none;
                border-radius: {scale_px(16, self._ui_scale)}px;
            }}
            QLabel#detailName {{ font-size: {scale_px(28, self._ui_scale)}px; font-weight: 700; }}
            QFrame#detailCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {SURFACE_ALT}, stop:1 {SURFACE});
                border: 1px solid {BORDER};
                border-radius: {scale_px(18, self._ui_scale)}px;
            }}
            QLabel#detailInlineName {{
                font-size: {scale_px(24, self._ui_scale)}px;
                font-weight: 800;
                color: {INK};
            }}
            QLabel#detailInlineSub, QLabel#detailMetaLine, QLabel#detailSectionTitle, QLabel#detailSkillLabel, QLabel#detailEquipCaption {{
                color: {MUTED};
            }}
            QLabel#detailSectionTitle {{
                font-size: {scale_px(11, self._ui_scale)}px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#detailChip {{
                border-radius: {scale_px(10, self._ui_scale)}px;
                padding: {scale_px(5, self._ui_scale)}px {scale_px(10, self._ui_scale)}px;
                font-weight: 700;
            }}
            QLabel#detailBigValue {{
                font-size: {scale_px(44, self._ui_scale)}px;
                font-weight: 900;
            }}
            QLabel#detailMiniValue {{
                font-size: {scale_px(20, self._ui_scale)}px;
                font-weight: 800;
                color: {INK};
            }}
            QLabel#detailMiniSub {{
                color: {MUTED};
                font-size: {scale_px(12, self._ui_scale)}px;
            }}
            QFrame#planSectionPanel {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_mix_hex(SURFACE, '#ffffff', 0.06)}, stop:1 {_mix_hex(SURFACE, SURFACE_ALT, 0.18)});
                border: 1px solid {_mix_hex(BORDER, '#ffffff', 0.08)};
                border-radius: {scale_px(16, self._ui_scale)}px;
            }}
            QFrame#planBand {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {_mix_hex(SURFACE_ALT, '#ffffff', 0.03)}, stop:1 {_mix_hex(SURFACE_ALT, BG, 0.14)});
                border: 1px solid {_mix_hex(BORDER, SURFACE_ALT, 0.24)};
                border-radius: {scale_px(12, self._ui_scale)}px;
            }}
            QWidget#planTransparent {{
                background: transparent;
                border: none;
            }}
            QLineEdit#planValueInput {{
                background: {_mix_hex(SURFACE_ALT, BG, 0.04)};
                border: 1px solid {_mix_hex(BORDER, '#ffffff', 0.08)};
                border-radius: {scale_px(11, self._ui_scale)}px;
                padding: {scale_px(6, self._ui_scale)}px {scale_px(10, self._ui_scale)}px;
                font-size: {scale_px(17, self._ui_scale)}px;
                font-weight: 800;
                color: {INK};
            }}
            QLineEdit#planValueInput:disabled {{
                color: {MUTED};
                background: {_mix_hex(SURFACE_ALT, BG, 0.22)};
            }}
            QPushButton#planQuickButton {{
                background: {ACCENT};
                color: white;
                border: 1px solid {ACCENT_STRONG};
                border-radius: {scale_px(11, self._ui_scale)}px;
                padding: {scale_px(6, self._ui_scale)}px {scale_px(12, self._ui_scale)}px;
                font-size: {scale_px(12, self._ui_scale)}px;
                font-weight: 800;
                min-width: {scale_px(58, self._ui_scale)}px;
            }}
            QPushButton#planQuickButton:disabled {{
                background: {_mix_hex(ACCENT, SURFACE_ALT, 0.45)};
                color: {MUTED};
                border-color: {_mix_hex(ACCENT_STRONG, SURFACE_ALT, 0.4)};
            }}
            QLabel#detailSkillValue {{
                color: {INK};
                font-size: {scale_px(21, self._ui_scale)}px;
                font-weight: 800;
            }}
            QLabel#detailEquipValue {{
                color: {INK};
                font-size: {scale_px(22, self._ui_scale)}px;
                font-weight: 800;
            }}
            QLabel#statValue {{ color: {INK}; font-weight: 700; }}
            QGroupBox {{
                border: 1px solid {BORDER};
                border-radius: {scale_px(12, self._ui_scale)}px;
                margin-top: {scale_px(10, self._ui_scale)}px;
                padding-top: {scale_px(12, self._ui_scale)}px;
                background: {SURFACE};
                font-weight: 700;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: {scale_px(12, self._ui_scale)}px;
                padding: 0 {scale_px(4, self._ui_scale)}px;
                color: {INK};
            }}
            QSpinBox {{
                background: {SURFACE_ALT};
                border: 1px solid {BORDER};
                border-radius: {scale_px(8, self._ui_scale)}px;
                padding: {scale_px(6, self._ui_scale)}px {scale_px(8, self._ui_scale)}px;
            }}
            QScrollBar:vertical {{
                background: {SURFACE_ALT};
                width: {scale_px(12, self._ui_scale)}px;
                margin: {scale_px(4, self._ui_scale)}px;
                border-radius: {scale_px(6, self._ui_scale)}px;
            }}
            QScrollBar::handle:vertical {{
                background: {ACCENT_SOFT};
                min-height: {scale_px(36, self._ui_scale)}px;
                border-radius: {scale_px(6, self._ui_scale)}px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
                border: none;
                height: 0px;
            }}
            """
        )

    def _build_students_tab(self, root: QWidget) -> None:
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(12, self._ui_scale))

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
        )
        header_layout.setSpacing(scale_px(12, self._ui_scale))

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(scale_px(4, self._ui_scale))
        title = QLabel("Blue Archive Planner")
        title.setObjectName("title")
        title_wrap.addWidget(title)
        subtitle = QLabel("Browse your students, inspect current progression, and build upgrade plans.")
        subtitle.setObjectName("count")
        title_wrap.addWidget(subtitle)
        header_layout.addLayout(title_wrap, 1)

        self._count_label = QLabel("")
        self._count_label.setObjectName("count")
        header_layout.addWidget(self._count_label)
        layout.addWidget(header)

        toolbar = QFrame()
        toolbar.setObjectName("panel")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        toolbar_layout.setSpacing(scale_px(10, self._ui_scale))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by student name, id, or tag")
        self._search.textChanged.connect(self._apply_filters)
        toolbar_layout.addWidget(self._search, 3)

        self._sort_mode = QComboBox()
        self._sort_mode.addItem("Star desc", "star_desc")
        self._sort_mode.addItem("Star asc", "star_asc")
        self._sort_mode.addItem("Level desc", "level_desc")
        self._sort_mode.addItem("Name asc", "name_asc")
        self._sort_mode.currentIndexChanged.connect(self._apply_filters)
        toolbar_layout.addWidget(self._sort_mode, 1)

        self._show_unowned = QCheckBox("Show unowned students")
        self._show_unowned.setChecked(True)
        self._show_unowned.stateChanged.connect(self._apply_filters)
        toolbar_layout.addWidget(self._show_unowned)

        self._hide_jp_only = QCheckBox("Hide JP-only students")
        self._hide_jp_only.stateChanged.connect(self._apply_filters)
        toolbar_layout.addWidget(self._hide_jp_only)

        toolbar_buttons = ParallelogramButtonRow()
        self._filter_button = ParallelogramButton("Filters", style=self._card_button_style)
        self._filter_button.clicked.connect(self._open_filter_dialog)
        toolbar_buttons.addButton(self._filter_button)

        refresh_button = ParallelogramButton("Refresh", style=self._card_button_style)
        refresh_button.clicked.connect(self._reload_data)
        toolbar_buttons.addButton(refresh_button)
        toolbar_layout.addWidget(toolbar_buttons, 0, Qt.AlignVCenter)
        layout.addWidget(toolbar)

        self._filter_summary = QLabel("No filters applied")
        self._filter_summary.setWordWrap(True)
        self._filter_summary.setObjectName("filterSummary")
        layout.addWidget(self._filter_summary)

        content = QSplitter(Qt.Horizontal)
        content.setChildrenCollapsible(False)
        layout.addWidget(content, 1)

        list_panel = QFrame()
        list_panel.setObjectName("panel")
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        list_layout.setSpacing(scale_px(10, self._ui_scale))

        detail = QFrame()
        detail.setObjectName("panel")
        detail_shell_layout = QVBoxLayout(detail)
        detail_shell_layout.setContentsMargins(0, 0, 0, 0)
        detail_shell_layout.setSpacing(0)
        detail_scroll = QScrollArea()
        self._detail_scroll = detail_scroll
        detail_scroll.setFrameShape(QScrollArea.NoFrame)
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        detail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        detail_shell_layout.addWidget(detail_scroll)
        detail_body = QWidget()
        self._detail_panel = detail_body  # type: ignore[assignment]
        detail_scroll.setWidget(detail_body)
        detail_layout = QVBoxLayout(detail_body)
        detail_layout.setContentsMargins(
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
        )
        detail_layout.setSpacing(scale_px(10, self._ui_scale))

        hero_wrap = QFrame()
        self._hero_wrap = hero_wrap
        hero_wrap.setObjectName("heroWrap")
        hero_layout = QVBoxLayout(hero_wrap)
        hero_layout.setContentsMargins(
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
        )
        self._hero = StudentPortraitWidget(self._student_card_asset)
        self._hero.setObjectName("hero")
        self._hero.setMinimumWidth(scale_px(286, self._ui_scale))
        hero_layout.addWidget(self._hero)
        detail_layout.addWidget(hero_wrap)

        detail_card = QFrame()
        detail_card.setObjectName("detailCard")
        detail_card_layout = QVBoxLayout(detail_card)
        detail_card_layout.setContentsMargins(
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
        )
        detail_card_layout.setSpacing(scale_px(8, self._ui_scale))

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(scale_px(6, self._ui_scale))
        self._detail_attack_bar = ParallelogramPanel(fill=ACCENT_SOFT, border=ACCENT, slant=DETAIL_SLANT)
        self._detail_attack_bar.setFixedHeight(scale_px(8, self._ui_scale))
        self._detail_defense_bar = ParallelogramPanel(fill=ACCENT_PALE, border=PALETTE_SOFT, slant=DETAIL_SLANT)
        self._detail_defense_bar.setFixedHeight(scale_px(8, self._ui_scale))
        bar_row.addWidget(self._detail_attack_bar, 1)
        bar_row.addWidget(self._detail_defense_bar, 1)
        detail_card_layout.addLayout(bar_row)

        self._detail_progress_strip = DetailProgressStrip()
        detail_card_layout.addWidget(self._detail_progress_strip)

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(scale_px(10, self._ui_scale))
        self._detail_school_icon = QLabel()
        self._detail_school_icon.setFixedSize(scale_px(26, self._ui_scale), scale_px(26, self._ui_scale))
        self._detail_school_icon.setScaledContents(False)
        name_row.addWidget(self._detail_school_icon, 0, Qt.AlignTop)
        name_col = QVBoxLayout()
        name_col.setContentsMargins(0, 0, 0, 0)
        name_col.setSpacing(scale_px(2, self._ui_scale))
        self._name = QLabel("Select a student")
        self._name.setObjectName("detailInlineName")
        self._subtitle = QLabel("")
        self._subtitle.setObjectName("detailInlineSub")
        self._detail_badges = QLabel("")
        self._detail_badges.setObjectName("detailMetaLine")
        self._detail_badges.setWordWrap(True)
        name_col.addWidget(self._name)
        name_col.addWidget(self._subtitle)
        name_col.addWidget(self._detail_badges)
        name_row.addLayout(name_col, 1)
        detail_card_layout.addLayout(name_row)

        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 0, 0, 0)
        chip_row.setSpacing(scale_px(8, self._ui_scale))
        self._detail_attack_chip = QLabel("-")
        self._detail_attack_chip.setObjectName("detailChip")
        self._detail_defense_chip = QLabel("-")
        self._detail_defense_chip.setObjectName("detailChip")
        chip_row.addWidget(self._detail_attack_chip, 0, Qt.AlignLeft)
        chip_row.addWidget(self._detail_defense_chip, 0, Qt.AlignLeft)
        chip_row.addStretch(1)
        detail_card_layout.addLayout(chip_row)

        self._detail_plan_button = ParallelogramButton("Add To Plan", style=self._card_button_style)
        self._detail_plan_button.clicked.connect(self._add_current_student_to_plan)
        self._detail_plan_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._detail_plan_button.setFixedHeight(scale_px(32, self._ui_scale))
        plan_row = QHBoxLayout()
        plan_row.setContentsMargins(0, 0, 0, 0)
        plan_row.addWidget(self._detail_plan_button, 1)
        detail_card_layout.addLayout(plan_row)

        stat_row = QHBoxLayout()
        stat_row.setContentsMargins(0, 0, 0, 0)
        stat_row.setSpacing(scale_px(6, self._ui_scale))
        level_card = ParallelogramPanel(fill=_mix_hex(PALETTE_SOFT, SURFACE_ALT, 0.52), border=PALETTE_SOFT, slant=DETAIL_SLANT)
        level_layout = QVBoxLayout(level_card)
        level_layout.setContentsMargins(scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale))
        level_layout.setSpacing(scale_px(6, self._ui_scale))
        level_title = QLabel("LEVEL")
        level_title.setObjectName("detailSectionTitle")
        level_title.setAlignment(Qt.AlignCenter)
        self._detail_level_value = QLabel("-")
        self._detail_level_value.setObjectName("detailBigValue")
        self._detail_level_value.setAlignment(Qt.AlignCenter)
        level_layout.addWidget(level_title)
        level_layout.addStretch(1)
        level_layout.addWidget(self._detail_level_value)
        level_layout.addStretch(1)
        stat_row.addWidget(level_card, 3)

        side_cards = QVBoxLayout()
        side_cards.setContentsMargins(0, 0, 0, 0)
        side_cards.setSpacing(scale_px(6, self._ui_scale))
        position_card = ParallelogramPanel(fill=_mix_hex(PALETTE_PANEL, PALETTE_SOFT, 0.16), border=PALETTE_SOFT, slant=DETAIL_SLANT)
        position_layout = QVBoxLayout(position_card)
        position_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(10, self._ui_scale), scale_px(12, self._ui_scale), scale_px(10, self._ui_scale))
        position_layout.setSpacing(scale_px(2, self._ui_scale))
        self._detail_position_value = QLabel("-")
        self._detail_position_value.setObjectName("detailMiniValue")
        self._detail_position_value.setAlignment(Qt.AlignCenter)
        position_layout.addStretch(1)
        position_layout.addWidget(self._detail_position_value)
        position_layout.addStretch(1)
        side_cards.addWidget(position_card)

        class_card = ParallelogramPanel(fill=_mix_hex(PALETTE_PANEL, PALETTE_SOFT, 0.16), border=PALETTE_SOFT, slant=DETAIL_SLANT)
        class_layout = QVBoxLayout(class_card)
        class_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(10, self._ui_scale), scale_px(12, self._ui_scale), scale_px(10, self._ui_scale))
        class_layout.setSpacing(scale_px(2, self._ui_scale))
        self._detail_class_value = QLabel("-")
        self._detail_class_value.setObjectName("detailMiniValue")
        self._detail_class_value.setAlignment(Qt.AlignCenter)
        class_layout.addStretch(1)
        class_layout.addWidget(self._detail_class_value)
        class_layout.addStretch(1)
        side_cards.addWidget(class_card)

        self._detail_weapon_card = ParallelogramPanel(fill=_mix_hex(PALETTE_PANEL_ALT, PALETTE_SOFT, 0.12), border=PALETTE_SOFT, slant=DETAIL_SLANT)
        weapon_layout = QVBoxLayout(self._detail_weapon_card)
        weapon_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(10, self._ui_scale), scale_px(12, self._ui_scale), scale_px(10, self._ui_scale))
        weapon_layout.setSpacing(scale_px(2, self._ui_scale))
        self._detail_weapon_value = QLabel("-")
        self._detail_weapon_value.setObjectName("detailMiniValue")
        self._detail_weapon_value.setAlignment(Qt.AlignCenter)
        self._detail_weapon_sub = QLabel("-")
        self._detail_weapon_sub.setObjectName("detailMiniSub")
        self._detail_weapon_sub.setAlignment(Qt.AlignCenter)
        weapon_layout.addStretch(1)
        weapon_layout.addWidget(self._detail_weapon_value)
        weapon_layout.addStretch(1)
        side_cards.addWidget(self._detail_weapon_card)
        stat_row.addLayout(side_cards, 2)
        detail_card_layout.addLayout(stat_row)

        skill_row = QHBoxLayout()
        skill_row.setContentsMargins(0, 0, 0, 0)
        skill_row.setSpacing(scale_px(4, self._ui_scale))
        self._detail_skill_labels: dict[str, QLabel] = {}
        for index, (key, label) in enumerate((("ex", "EX"), ("s1", "N"), ("s2", "P"), ("s3", "S"))):
            skill_card = ParallelogramPanel(fill=_mix_hex(PALETTE_PANEL, PALETTE_ACCENT, 0.14), border=PALETTE_SOFT, slant=DETAIL_SLANT)
            skill_layout = QVBoxLayout(skill_card)
            skill_layout.setContentsMargins(scale_px(10, self._ui_scale), scale_px(10, self._ui_scale), scale_px(10, self._ui_scale), scale_px(10, self._ui_scale))
            skill_layout.setSpacing(scale_px(4, self._ui_scale))
            top = QLabel(label)
            top.setObjectName("detailSkillLabel")
            top.setAlignment(Qt.AlignCenter)
            value = QLabel("-")
            value.setObjectName("detailSkillValue")
            value.setAlignment(Qt.AlignCenter)
            self._detail_skill_labels[key] = value
            skill_layout.addStretch(1)
            skill_layout.addWidget(top)
            skill_layout.addWidget(value)
            skill_layout.addStretch(1)
            skill_row.addWidget(skill_card, 1)
        detail_card_layout.addLayout(skill_row)

        equip_row = QHBoxLayout()
        equip_row.setContentsMargins(0, 0, 0, 0)
        equip_row.setSpacing(0)
        self._detail_equip_cards: dict[str, EquipmentDetailCard] = {}
        for slot in ("equip1", "equip2", "equip3"):
            card = EquipmentDetailCard(
                self._ui_scale,
                fill=_mix_hex(PALETTE_PANEL_ALT, PALETTE_SOFT, 0.18),
                border=PALETTE_SOFT,
                slant=DETAIL_SLANT,
            )
            equip_row.addWidget(card, 1)
            self._detail_equip_cards[slot] = card
        detail_card_layout.addLayout(equip_row)

        self._detail_stats_line = QLabel("-")
        self._detail_stats_line.setObjectName("detailMetaLine")
        self._detail_stats_line.setAlignment(Qt.AlignCenter)
        self._detail_stats_line.setWordWrap(True)
        detail_card_layout.addWidget(self._detail_stats_line)
        detail_layout.addWidget(detail_card)
        detail_layout.addStretch(1)
        self._student_grid = ParallelogramCardGrid(self._student_card_asset, self._ui_scale)
        self._student_grid.setObjectName("studentGrid")
        self._student_grid.current_changed.connect(self._on_student_card_changed)
        self._student_grid.layout_changed.connect(self._on_student_grid_layout_changed)
        list_layout.addWidget(self._student_grid, 1)

        detail.setMinimumWidth(scale_px(332, self._ui_scale))
        detail.setMaximumWidth(scale_px(376, self._ui_scale))
        content.addWidget(list_panel)
        content.addWidget(detail)
        content.setStretchFactor(0, 5)
        content.setStretchFactor(1, 1)
        content.setSizes([scale_px(1168, self._ui_scale), scale_px(352, self._ui_scale)])
        content.splitterMoved.connect(lambda *_: QTimer.singleShot(0, self._sync_hero_height))
        QTimer.singleShot(0, self._sync_hero_height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._sync_hero_height)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and not self._applying_work_area:
            if self.windowState() & Qt.WindowMaximized:
                QTimer.singleShot(0, self._apply_work_area_geometry)
            QTimer.singleShot(0, self._sync_hero_height)

    def _sync_hero_height(self) -> None:
        if self._hero_wrap is None or self._detail_panel is None or not hasattr(self, "_hero"):
            return
        wrap_width = self._hero_wrap.width()
        if wrap_width <= 0:
            return
        inset = scale_px(32, self._ui_scale)
        card_width = max(1, wrap_width - inset)
        card_height = max(1, int(round(card_width / max(0.01, self._student_card_asset.aspect_ratio))))
        preferred_height = card_height + inset
        detail_height = self._detail_scroll.viewport().height() if self._detail_scroll is not None else self._detail_panel.height()
        max_height = max(scale_px(196, self._ui_scale), int(detail_height * 0.37)) if detail_height > 0 else preferred_height
        wrap_height = min(preferred_height, max_height)
        self._hero_wrap.setFixedHeight(wrap_height)

    def eventFilter(self, watched, event) -> bool:
        return super().eventFilter(watched, event)

    def _refresh_card_layout(self) -> None:
        if self._card_layout_guard or not hasattr(self, "_student_grid"):
            return
        sizes = [self._student_grid.current_card_size()]
        if hasattr(self, "_plan_grid"):
            sizes.append(self._plan_grid.current_card_size())
        thumb_width = max(size.width() for size in sizes)
        thumb_height = max(size.height() for size in sizes)
        outer_margin = self._student_card_asset.style.outer_margin * 2
        grid_width = thumb_width + outer_margin
        grid_height = thumb_height + outer_margin

        if thumb_width <= 0 or thumb_height <= 0:
            return

        if (
            thumb_width == self._thumb_width
            and thumb_height == self._thumb_height
            and grid_width == self._grid_width
            and grid_height == self._grid_height
        ):
            return

        self._card_layout_guard = True
        try:
            self._thumb_width = thumb_width
            self._thumb_height = thumb_height
            self._grid_width = grid_width
            self._grid_height = grid_height
            self._placeholder_icon = make_placeholder_icon(self._thumb_width, self._thumb_height)
            self._unowned_icon_cache.clear()
            self._clear_thumb_requests()
            for student_id in sorted(set(self._item_by_id) | set(self._plan_card_by_id)):
                self._enqueue_thumb(student_id)
        finally:
            self._card_layout_guard = False

    def _build_resource_tab(self, root: QWidget) -> None:
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(12, self._ui_scale))

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
        )
        header_layout.setSpacing(scale_px(12, self._ui_scale))

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(scale_px(4, self._ui_scale))
        title = QLabel("Resource Manager")
        title.setObjectName("title")
        title_wrap.addWidget(title)
        subtitle = QLabel("Inspect single-student costs or aggregate growth requirements for the students currently in view.")
        subtitle.setObjectName("count")
        subtitle.setWordWrap(True)
        title_wrap.addWidget(subtitle)
        header_layout.addLayout(title_wrap, 1)
        layout.addWidget(header)

        toolbar = QFrame()
        toolbar.setObjectName("panel")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        toolbar_layout.setSpacing(scale_px(10, self._ui_scale))

        self._resource_search = QLineEdit()
        self._resource_search.setPlaceholderText("Search the same filtered student set")
        self._resource_search.textChanged.connect(self._on_resource_search_changed)
        toolbar_layout.addWidget(self._resource_search, 3)

        self._resource_sort_mode = QComboBox()
        self._resource_sort_mode.addItem("Star desc", "star_desc")
        self._resource_sort_mode.addItem("Star asc", "star_asc")
        self._resource_sort_mode.addItem("Level desc", "level_desc")
        self._resource_sort_mode.addItem("Name asc", "name_asc")
        self._resource_sort_mode.currentIndexChanged.connect(self._on_resource_sort_changed)
        toolbar_layout.addWidget(self._resource_sort_mode, 1)

        self._resource_show_unowned = QCheckBox("Show unowned students")
        self._resource_show_unowned.stateChanged.connect(self._on_resource_show_unowned_changed)
        toolbar_layout.addWidget(self._resource_show_unowned)

        self._resource_hide_jp_only = QCheckBox("Hide JP-only students")
        self._resource_hide_jp_only.stateChanged.connect(self._on_resource_hide_jp_only_changed)
        toolbar_layout.addWidget(self._resource_hide_jp_only)

        resource_toolbar_buttons = ParallelogramButtonRow()
        self._resource_filter_button = ParallelogramButton("Filters", style=self._card_button_style)
        self._resource_filter_button.clicked.connect(self._open_filter_dialog)
        resource_toolbar_buttons.addButton(self._resource_filter_button)
        resource_refresh_button = ParallelogramButton("Refresh", style=self._card_button_style)
        resource_refresh_button.clicked.connect(self._reload_data)
        resource_toolbar_buttons.addButton(resource_refresh_button)
        toolbar_layout.addWidget(resource_toolbar_buttons, 0, Qt.AlignVCenter)
        layout.addWidget(toolbar)

        self._resource_filter_summary = QLabel("No filters applied")
        self._resource_filter_summary.setWordWrap(True)
        self._resource_filter_summary.setObjectName("filterSummary")
        layout.addWidget(self._resource_filter_summary)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left_panel = QFrame()
        left_panel.setObjectName("panel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        left_layout.setSpacing(scale_px(10, self._ui_scale))

        left_title = QLabel("Students in scope")
        left_title.setObjectName("sectionTitle")
        left_layout.addWidget(left_title)
        self._resource_list_summary = QLabel("")
        self._resource_list_summary.setObjectName("detailSub")
        self._resource_list_summary.setWordWrap(True)
        left_layout.addWidget(self._resource_list_summary)

        self._resource_list = QListWidget()
        self._resource_list.currentItemChanged.connect(self._on_resource_item_changed)
        left_layout.addWidget(self._resource_list, 1)

        right_panel = QFrame()
        right_panel.setObjectName("panel")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        right_layout.setSpacing(scale_px(10, self._ui_scale))

        self._resource_mode_tabs = QTabWidget()

        single_tab = QWidget()
        single_layout = QVBoxLayout(single_tab)
        single_layout.setContentsMargins(0, 0, 0, 0)
        single_layout.setSpacing(scale_px(10, self._ui_scale))
        single_options = QFrame()
        single_options.setObjectName("planSectionPanel")
        single_options_layout = QVBoxLayout(single_options)
        single_options_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        single_options_layout.setSpacing(scale_px(8, self._ui_scale))
        single_title = QLabel("Single student mode")
        single_title.setObjectName("sectionTitle")
        single_options_layout.addWidget(single_title)
        self._resource_single_summary = QLabel("Select a student from the left list.")
        self._resource_single_summary.setObjectName("detailSub")
        self._resource_single_summary.setWordWrap(True)
        single_options_layout.addWidget(self._resource_single_summary)
        single_layout.addWidget(single_options, 0)
        self._resource_single_output = QListWidget()
        single_layout.addWidget(self._resource_single_output, 1)
        self._resource_mode_tabs.addTab(single_tab, "Single")

        aggregate_tab = QWidget()
        aggregate_layout = QVBoxLayout(aggregate_tab)
        aggregate_layout.setContentsMargins(0, 0, 0, 0)
        aggregate_layout.setSpacing(scale_px(10, self._ui_scale))
        aggregate_options = QFrame()
        aggregate_options.setObjectName("planSectionPanel")
        aggregate_options_layout = QVBoxLayout(aggregate_options)
        aggregate_options_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        aggregate_options_layout.setSpacing(scale_px(8, self._ui_scale))
        aggregate_title = QLabel("Aggregate mode")
        aggregate_title.setObjectName("sectionTitle")
        aggregate_options_layout.addWidget(aggregate_title)
        aggregate_row = QHBoxLayout()
        aggregate_row.setSpacing(scale_px(8, self._ui_scale))
        aggregate_label = QLabel("Combine:")
        aggregate_label.setObjectName("detailSub")
        aggregate_row.addWidget(aggregate_label)
        self._resource_aggregate_scope = QComboBox()
        self._resource_aggregate_scope.addItem("Checked students", "checked")
        self._resource_aggregate_scope.addItem("Planned students", "planned")
        self._resource_aggregate_scope.addItem("Visible planned students", "visible_planned")
        self._resource_aggregate_scope.currentIndexChanged.connect(self._refresh_resource_view)
        aggregate_row.addWidget(self._resource_aggregate_scope, 1)
        aggregate_options_layout.addLayout(aggregate_row)

        aggregate_buttons = QHBoxLayout()
        aggregate_buttons.setSpacing(scale_px(8, self._ui_scale))
        for label, handler in (("Check visible", self._resource_check_visible), ("Check planned", self._resource_check_visible_planned), ("Clear", self._resource_clear_checked)):
            button = QPushButton(label)
            button.setObjectName("planQuickButton")
            button.clicked.connect(handler)
            aggregate_buttons.addWidget(button)
        aggregate_buttons.addStretch(1)
        aggregate_options_layout.addLayout(aggregate_buttons)

        self._resource_aggregate_summary = QLabel("Choose a scope to combine growth costs.")
        self._resource_aggregate_summary.setObjectName("detailSub")
        self._resource_aggregate_summary.setWordWrap(True)
        aggregate_options_layout.addWidget(self._resource_aggregate_summary)
        aggregate_layout.addWidget(aggregate_options, 0)
        self._resource_aggregate_output = QListWidget()
        aggregate_layout.addWidget(self._resource_aggregate_output, 1)
        self._resource_mode_tabs.addTab(aggregate_tab, "Aggregate")

        self._resource_mode_tabs.currentChanged.connect(self._refresh_resource_view)
        right_layout.addWidget(self._resource_mode_tabs, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self._sync_resource_controls_from_students()
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _build_inventory_tab(self, root: QWidget) -> None:
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(12, self._ui_scale))

        header = QFrame()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
        )
        header_layout.setSpacing(scale_px(4, self._ui_scale))

        title = QLabel("Inventory")
        title.setObjectName("title")
        header_layout.addWidget(title)

        subtitle = QLabel("Review the latest scanned inventory with icons, grouped by equipment slot and item type.")
        subtitle.setObjectName("count")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)

        self._inventory_summary = QLabel("No scanned inventory is available yet.")
        self._inventory_summary.setObjectName("filterSummary")
        self._inventory_summary.setWordWrap(True)
        header_layout.addWidget(self._inventory_summary)
        layout.addWidget(header)

        self._inventory_root_tabs = QTabWidget()
        self._inventory_equipment_lists: dict[str, QListWidget] = {}
        self._inventory_equipment_summaries: dict[str, QLabel] = {}
        self._inventory_item_lists: dict[str, QListWidget] = {}
        self._inventory_item_summaries: dict[str, QLabel] = {}

        equipment_root = QWidget()
        equipment_layout = QVBoxLayout(equipment_root)
        equipment_layout.setContentsMargins(0, 0, 0, 0)
        equipment_layout.setSpacing(scale_px(10, self._ui_scale))
        self._inventory_equipment_tabs = QTabWidget()

        for series in EQUIPMENT_SERIES:
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            tab_layout.setSpacing(scale_px(10, self._ui_scale))

            panel = QFrame()
            panel.setObjectName("planSectionPanel")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(
                scale_px(14, self._ui_scale),
                scale_px(14, self._ui_scale),
                scale_px(14, self._ui_scale),
                scale_px(14, self._ui_scale),
            )
            panel_layout.setSpacing(scale_px(8, self._ui_scale))
            section_title = QLabel(f"{series.icon_key} equipment")
            section_title.setObjectName("sectionTitle")
            panel_layout.addWidget(section_title)
            summary = QLabel("No scanned items in this category yet.")
            summary.setObjectName("detailSub")
            summary.setWordWrap(True)
            panel_layout.addWidget(summary)
            tab_layout.addWidget(panel, 0)

            item_list = QListWidget()
            tab_layout.addWidget(item_list, 1)
            self._inventory_equipment_tabs.addTab(tab, series.icon_key)
            self._inventory_equipment_lists[series.icon_key] = item_list
            self._inventory_equipment_summaries[series.icon_key] = summary

        equipment_layout.addWidget(self._inventory_equipment_tabs, 1)
        self._inventory_root_tabs.addTab(equipment_root, "Equipment")

        item_root = QWidget()
        item_layout = QVBoxLayout(item_root)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(scale_px(10, self._ui_scale))
        self._inventory_item_tabs = QTabWidget()

        for key, label in (
            ("ooparts", "Ooparts"),
            ("wb", "WB"),
            ("stones", "Stones"),
            ("reports", "Reports"),
            ("weapon_parts", "Weapon Parts"),
            ("tech_notes", "Tech Notes"),
            ("bd", "BD"),
            ("other", "Other"),
        ):
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            tab_layout.setContentsMargins(0, 0, 0, 0)
            tab_layout.setSpacing(scale_px(10, self._ui_scale))

            panel = QFrame()
            panel.setObjectName("planSectionPanel")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(
                scale_px(14, self._ui_scale),
                scale_px(14, self._ui_scale),
                scale_px(14, self._ui_scale),
                scale_px(14, self._ui_scale),
            )
            panel_layout.setSpacing(scale_px(8, self._ui_scale))
            section_title = QLabel(label)
            section_title.setObjectName("sectionTitle")
            panel_layout.addWidget(section_title)
            summary = QLabel("No scanned items in this category yet.")
            summary.setObjectName("detailSub")
            summary.setWordWrap(True)
            panel_layout.addWidget(summary)
            tab_layout.addWidget(panel, 0)

            item_list = QListWidget()
            tab_layout.addWidget(item_list, 1)
            self._inventory_item_tabs.addTab(tab, label)
            self._inventory_item_lists[key] = item_list
            self._inventory_item_summaries[key] = summary

        item_layout.addWidget(self._inventory_item_tabs, 1)
        self._inventory_root_tabs.addTab(item_root, "Items")

        layout.addWidget(self._inventory_root_tabs, 1)
        self._refresh_inventory_tab()

    def _sync_resource_controls_from_students(self) -> None:
        if not hasattr(self, "_resource_search"):
            return
        self._resource_syncing_controls = True
        try:
            self._resource_search.setText(self._search.text())
            target_sort = self._sort_mode.currentData()
            for index in range(self._resource_sort_mode.count()):
                if self._resource_sort_mode.itemData(index) == target_sort:
                    self._resource_sort_mode.setCurrentIndex(index)
                    break
            self._resource_show_unowned.setChecked(self._show_unowned.isChecked())
            self._resource_hide_jp_only.setChecked(self._hide_jp_only.isChecked())
            self._resource_filter_summary.setText(self._filter_summary.text())
            self._resource_filter_button.setText(self._filter_button.text())
        finally:
            self._resource_syncing_controls = False

    def _on_resource_search_changed(self, text: str) -> None:
        if self._resource_syncing_controls:
            return
        if self._search.text() != text:
            self._search.setText(text)

    def _on_resource_sort_changed(self, _index: int) -> None:
        if self._resource_syncing_controls:
            return
        target_sort = self._resource_sort_mode.currentData()
        if self._sort_mode.currentData() == target_sort:
            return
        for index in range(self._sort_mode.count()):
            if self._sort_mode.itemData(index) == target_sort:
                self._sort_mode.setCurrentIndex(index)
                return

    def _on_resource_show_unowned_changed(self, _state: int) -> None:
        if self._resource_syncing_controls:
            return
        checked = self._resource_show_unowned.isChecked()
        if self._show_unowned.isChecked() != checked:
            self._show_unowned.setChecked(checked)

    def _on_resource_hide_jp_only_changed(self, _state: int) -> None:
        if self._resource_syncing_controls:
            return
        checked = self._resource_hide_jp_only.isChecked()
        if self._hide_jp_only.isChecked() != checked:
            self._hide_jp_only.setChecked(checked)

    def _resource_compact_cost_text(self, summary: PlanCostSummary | None) -> str:
        if summary is None:
            return "No planned target yet"
        total_materials = sum(summary.star_materials.values()) + sum(summary.equipment_materials.values()) + sum(summary.skill_books.values()) + sum(summary.ex_ooparts.values()) + sum(summary.skill_ooparts.values()) + sum(summary.stat_materials.values())
        return f"Credits {summary.credits:,} · EXP {summary.level_exp:,} · Items {total_materials:,}"

    def _resource_focus_label(self, record: StudentRecord, summary: PlanCostSummary | None) -> str:
        goal_map = self._plan_goal_map()
        status = []
        status.append("Planned" if record.student_id in goal_map else "Not planned")
        status.append("Owned" if record.owned else "Unowned")
        if summary is None:
            return " · ".join(status)
        buckets = [
            ("skill", sum(summary.skill_books.values()) + sum(summary.ex_ooparts.values()) + sum(summary.skill_ooparts.values())),
            ("equipment", sum(summary.equipment_materials.values())),
            ("star", sum(summary.star_materials.values())),
            ("stat", sum(summary.stat_materials.values())),
        ]
        label, amount = max(buckets, key=lambda item: item[1])
        if amount > 0:
            status.append(f"{label.title()}-heavy")
        return " · ".join(status)

    def _resource_goal_for_student(self, student_id: str) -> StudentGoal | None:
        return self._plan_goal_map().get(student_id)

    def _resource_summary_for_student(self, student_id: str) -> PlanCostSummary | None:
        record = self._records_by_id.get(student_id)
        goal = self._resource_goal_for_student(student_id)
        if record is None or goal is None:
            return None
        return calculate_goal_cost(record, goal)

    def _resource_current_student(self) -> str | None:
        item = self._resource_list.currentItem() if hasattr(self, "_resource_list") else None
        return str(item.data(Qt.UserRole)) if item is not None else None

    def _refresh_resource_students_list(self) -> None:
        if not hasattr(self, "_resource_list"):
            return
        current_id = self._resource_current_student_id or self._resource_current_student()
        self._resource_list.clear()
        goal_map = self._plan_goal_map()
        visible_planned = 0
        for record in self._filtered_students:
            summary = self._resource_summary_for_student(record.student_id)
            if record.student_id in goal_map:
                visible_planned += 1
            item = QListWidgetItem()
            item.setData(Qt.UserRole, record.student_id)
            widget = ResourceStudentListItem(record.student_id, ui_scale=self._ui_scale)
            widget.setChecked(record.student_id in self._resource_selected_ids)
            widget.setTexts(
                title=record.title,
                status=self._resource_focus_label(record, summary),
                cost=self._resource_compact_cost_text(summary),
            )
            widget.toggled.connect(self._on_resource_item_toggled)
            item.setSizeHint(QSize(scale_px(240, self._ui_scale), scale_px(84, self._ui_scale)))
            self._resource_list.addItem(item)
            self._resource_list.setItemWidget(item, widget)
            if current_id == record.student_id:
                self._resource_list.setCurrentItem(item)

        if self._resource_list.currentItem() is None and self._resource_list.count() > 0:
            self._resource_list.setCurrentRow(0)
        self._resource_list_summary.setText(
            f"{len(self._filtered_students)} visible students · {visible_planned} with planner targets · {len(self._resource_selected_ids & {record.student_id for record in self._filtered_students})} checked"
        )

    def _on_resource_item_toggled(self, student_id: str, checked: bool) -> None:
        if checked:
            self._resource_selected_ids.add(student_id)
        else:
            self._resource_selected_ids.discard(student_id)
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _on_resource_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._resource_current_student_id = str(current.data(Qt.UserRole)) if current is not None else None
        self._refresh_resource_view()

    def _resource_check_visible(self) -> None:
        self._resource_selected_ids.update(record.student_id for record in self._filtered_students)
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _resource_check_visible_planned(self) -> None:
        goal_map = self._plan_goal_map()
        self._resource_selected_ids.update(record.student_id for record in self._filtered_students if record.student_id in goal_map)
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _resource_clear_checked(self) -> None:
        self._resource_selected_ids.clear()
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _resource_total_for_ids(self, student_ids: list[str] | tuple[str, ...] | set[str]) -> tuple[PlanCostSummary, int, int]:
        goal_map = self._plan_goal_map()
        ordered_ids = [student_id for student_id in student_ids if student_id in self._records_by_id]
        goals = [goal_map[student_id] for student_id in ordered_ids if student_id in goal_map]
        plan = self._plan.__class__(version=getattr(self._plan, "version", 1), goals=goals)
        records = {student_id: self._records_by_id[student_id] for student_id in ordered_ids if student_id in goal_map}
        return calculate_plan_totals(records, plan), len(ordered_ids), len(goals)

    def _set_output_from_summary(self, target: QListWidget, summary: PlanCostSummary | None) -> None:
        target.clear()
        if summary is None:
            target.addItem("No planner target is available for this selection yet.")
            return

        sections: list[tuple[str, list[tuple[str, int]]]] = []
        if summary.credits:
            sections.append(("Credits", [("Credits", summary.credits)]))
        if summary.level_exp:
            sections.append(("Level EXP", [("Level EXP", summary.level_exp)] + sorted(summary.level_exp_items.items(), key=lambda item: (-item[1], item[0]))))
        if summary.equipment_exp or summary.equipment_exp_items:
            rows = []
            if summary.equipment_exp:
                rows.append(("Equipment EXP", summary.equipment_exp))
            rows.extend(sorted(summary.equipment_exp_items.items(), key=lambda item: (-item[1], item[0])))
            sections.append(("Equipment EXP", rows))
        if summary.weapon_exp or summary.weapon_exp_items:
            rows = []
            if summary.weapon_exp:
                rows.append(("Weapon EXP", summary.weapon_exp))
            rows.extend(sorted(summary.weapon_exp_items.items(), key=lambda item: (-item[1], item[0])))
            sections.append(("Weapon EXP", rows))
        for heading, mapping in (("Star materials", summary.star_materials), ("Equipment materials", summary.equipment_materials), ("Skill books", summary.skill_books), ("EX ooparts", summary.ex_ooparts), ("Skill ooparts", summary.skill_ooparts), ("Stat materials", summary.stat_materials)):
            if mapping:
                sections.append((heading, sorted(mapping.items(), key=lambda item: (-item[1], item[0]))))
        if summary.stat_levels:
            sections.append(("Stat targets", sorted(summary.stat_levels.items(), key=lambda item: item[0])))

        if not sections and summary.warnings:
            for warning in dict.fromkeys(summary.warnings):
                target.addItem(warning)
            return

        for heading, rows in sections:
            heading_item = QListWidgetItem(heading)
            heading_item.setFlags(Qt.ItemIsEnabled)
            target.addItem(heading_item)
            for key, value in rows:
                target.addItem(f"  {key}: {value:,}" if isinstance(value, int) else f"  {key}: {value}")
        if summary.warnings:
            target.addItem("Notes")
            for warning in dict.fromkeys(summary.warnings):
                target.addItem(f"  {warning}")

    def _refresh_resource_view(self) -> None:
        if not hasattr(self, "_resource_mode_tabs"):
            return
        self._refresh_resource_single_view()
        self._refresh_resource_aggregate_view()

    def _refresh_resource_single_view(self) -> None:
        student_id = self._resource_current_student_id or self._resource_current_student()
        if not student_id:
            self._resource_single_summary.setText("Select a student from the left list.")
            self._set_output_from_summary(self._resource_single_output, None)
            return
        record = self._records_by_id.get(student_id)
        summary = self._resource_summary_for_student(student_id)
        if record is None:
            self._resource_single_summary.setText("Student data is unavailable.")
            self._set_output_from_summary(self._resource_single_output, None)
            return
        if summary is None:
            self._resource_single_summary.setText(f"{record.title} is currently not in the planner. Add a target in the Plans tab to see required resources.")
            self._set_output_from_summary(self._resource_single_output, None)
            return
        self._resource_single_summary.setText(
            f"{record.title} · {self._resource_focus_label(record, summary)} · {self._resource_compact_cost_text(summary)}"
        )
        self._set_output_from_summary(self._resource_single_output, summary)

    def _refresh_resource_aggregate_view(self) -> None:
        scope = self._resource_aggregate_scope.currentData() if hasattr(self, "_resource_aggregate_scope") else "checked"
        goal_map = self._plan_goal_map()
        if scope == "planned":
            student_ids = [goal.student_id for goal in self._plan.goals]
            label = "all planned students"
        elif scope == "visible_planned":
            student_ids = [record.student_id for record in self._filtered_students if record.student_id in goal_map]
            label = "visible planned students"
        else:
            student_ids = [record.student_id for record in self._filtered_students if record.student_id in self._resource_selected_ids]
            label = "checked students"
        summary, selected_count, contributing_count = self._resource_total_for_ids(student_ids)
        self._resource_aggregate_summary.setText(
            f"Combining {selected_count} {label}. {contributing_count} of them currently have planner targets and contribute to the total."
        )
        if contributing_count == 0:
            self._set_output_from_summary(self._resource_aggregate_output, None)
            return
        self._set_output_from_summary(self._resource_aggregate_output, summary)

    def _refresh_resource_inventory_view(self) -> None:
        self._refresh_inventory_tab()
        return
        if not hasattr(self, "_resource_inventory_output"):
            return
        self._resource_inventory_output.clear()
        inventory = self._inventory_snapshot or {}
        if not inventory:
            self._resource_inventory_summary.setText("No scanned inventory is available yet.")
            self._resource_inventory_output.addItem("Run an item or equipment scan to populate current inventory.")
            return

        def sort_key(item: tuple[str, dict]) -> tuple[int, str]:
            _, payload = item
            raw_quantity = payload.get("quantity")
            try:
                quantity = int(str(raw_quantity).replace(",", ""))
            except Exception:
                quantity = -1
            name = str(payload.get("name") or item[0])
            return (-quantity, name)

        ordered = sorted(inventory.items(), key=sort_key)
        total_quantity = 0
        for _, payload in ordered:
            try:
                total_quantity += int(str(payload.get("quantity") or "0").replace(",", ""))
            except Exception:
                continue

        self._resource_inventory_summary.setText(
            f"{len(ordered)} items in current inventory snapshot · total quantity {total_quantity:,}"
        )
        for key, payload in ordered:
            name = str(payload.get("name") or key)
            quantity = payload.get("quantity") or "?"
            self._resource_inventory_output.addItem(f"{name}: {quantity}")

    def _inventory_classify_item(self, item_key: str, payload: dict) -> str:
        item_id = str(payload.get("item_id") or "")
        name = _inventory_display_label(item_key, payload)
        if item_id in _OPART_ITEM_IDS:
            return "ooparts"
        if item_id in _WB_ITEM_IDS or item_id in _WORKBOOK_ID_TO_NAME:
            return "wb"
        if item_id.startswith("Equipment_Icon_Exp_"):
            return "stones"
        if item_id.startswith("Equipment_Icon_WeaponExpGrowth"):
            return "weapon_parts"
        if item_id.startswith("Item_Icon_SkillBook_"):
            return "tech_notes"
        if item_id.startswith("Item_Icon_Material_ExSkill_"):
            return "bd"
        if _report_icon_for_entry(item_id or None, name):
            return "reports"
        return "other"

    def _set_inventory_list_items(self, target: QListWidget, summary: QLabel, entries: list[tuple[str, dict]]) -> None:
        target.clear()
        if not entries:
            summary.setText("No scanned items in this category yet.")
            target.addItem("Run an item or equipment scan to populate this category.")
            return

        total_quantity = sum(
            quantity
            for _item_key, payload in entries
            if (quantity := _inventory_quantity_value(payload.get("quantity"))) is not None
        )
        summary.setText(f"{len(entries)} items 쨌 total quantity {total_quantity:,}")

        for item_key, payload in entries:
            item_id = payload.get("item_id")
            name = _inventory_display_label(item_key, payload)
            quantity_value = _inventory_quantity_value(payload.get("quantity"))
            quantity = f"{quantity_value:,}" if quantity_value is not None else str(payload.get("quantity") or "?")
            widget = InventoryListItem(ui_scale=self._ui_scale)
            widget.setData(
                icon_path=_inventory_icon_path(str(item_id) if item_id else None, name),
                name=name,
                quantity=quantity,
                meta="",
            )
            item = QListWidgetItem()
            item.setFlags(Qt.ItemIsEnabled)
            item.setSizeHint(QSize(scale_px(320, self._ui_scale), scale_px(72, self._ui_scale)))
            target.addItem(item)
            target.setItemWidget(item, widget)

    def _refresh_inventory_tab(self) -> None:
        if not hasattr(self, "_inventory_root_tabs"):
            return

        inventory = self._inventory_snapshot or {}
        if not inventory:
            self._inventory_summary.setText("No scanned inventory is available yet. Run an item or equipment scan to populate this tab.")
            for key, widget in self._inventory_equipment_lists.items():
                self._set_inventory_list_items(widget, self._inventory_equipment_summaries[key], [])
            for key, widget in self._inventory_item_lists.items():
                self._set_inventory_list_items(widget, self._inventory_item_summaries[key], [])
            return

        total_quantity = sum(
            quantity
            for payload in inventory.values()
            if (quantity := _inventory_quantity_value(payload.get("quantity"))) is not None
        )
        latest_seen = max((str(payload.get("last_seen_at") or "") for payload in inventory.values()), default="")
        latest_suffix = f" 쨌 last updated {latest_seen}" if latest_seen else ""
        self._inventory_summary.setText(
            f"{len(inventory)} scanned entries 쨌 total quantity {total_quantity:,}{latest_suffix}"
        )

        equipment_groups: dict[str, list[tuple[str, dict]]] = {series.icon_key: [] for series in EQUIPMENT_SERIES}
        item_groups: dict[str, list[tuple[str, dict]]] = {
            "ooparts": [],
            "wb": [],
            "stones": [],
            "reports": [],
            "weapon_parts": [],
            "tech_notes": [],
            "bd": [],
            "other": [],
        }

        for item_key, payload in inventory.items():
            item_id = str(payload.get("item_id") or "")
            if item_id.startswith("Equipment_Icon_") and "_Tier" in item_id:
                series_key = item_id.removeprefix("Equipment_Icon_").split("_Tier", 1)[0]
                if series_key in equipment_groups:
                    equipment_groups[series_key].append((item_key, payload))
                    continue
            item_groups[self._inventory_classify_item(item_key, payload)].append((item_key, payload))

        opart_order = {item_id: index for index, item_id in enumerate(_OPART_ITEM_IDS)}
        wb_order = {
            item_id: index
            for index, item_id in enumerate(tuple(_WORKBOOK_ID_TO_NAME) + _WB_ITEM_IDS)
        }
        stone_order = {item_id: index for index, (item_id, _name) in enumerate(EQUIPMENT_EXP_ITEMS)}
        report_order = {token: index for index, token in enumerate(_REPORT_ORDER)}
        weapon_order = {
            item_id: index
            for index, item_id in enumerate(
                [
                    f"Equipment_Icon_WeaponExpGrowth{part_key}_{tier}"
                    for part_key, _label in WEAPON_PART_ITEMS
                    for tier in range(3, -1, -1)
                ]
            )
        }
        tech_order = {
            item_id: index
            for index, item_id in enumerate(
                [
                    f"Item_Icon_SkillBook_{school}_{tier}"
                    for school in _SCHOOL_SEQUENCE
                    for tier in ("0", "1", "2", "3")
                ]
                + ["Item_Icon_SkillBook_Ultimate_Piece"]
            )
        }
        bd_order = {
            item_id: index
            for index, item_id in enumerate(
                [
                    f"Item_Icon_Material_ExSkill_{school}_{tier}"
                    for school in _SCHOOL_SEQUENCE
                    for tier in ("0", "1", "2", "3")
                ]
            )
        }

        def equipment_sort_key(entry: tuple[str, dict]) -> tuple[int, str]:
            item_id = str(entry[1].get("item_id") or "")
            try:
                tier_number = int(item_id.rsplit("_Tier", 1)[-1])
            except ValueError:
                tier_number = -1
            return (-tier_number, _inventory_display_label(entry[0], entry[1]).lower())

        def ordered_sort_key(order_map: dict[str, int], entry: tuple[str, dict]) -> tuple[int, str]:
            item_id = str(entry[1].get("item_id") or "")
            return (order_map.get(item_id, 9999), _inventory_display_label(entry[0], entry[1]).lower())

        for series in EQUIPMENT_SERIES:
            entries = sorted(equipment_groups[series.icon_key], key=equipment_sort_key)
            self._set_inventory_list_items(
                self._inventory_equipment_lists[series.icon_key],
                self._inventory_equipment_summaries[series.icon_key],
                entries,
            )

        ordered_items = {
            "ooparts": sorted(item_groups["ooparts"], key=lambda entry: ordered_sort_key(opart_order, entry)),
            "wb": sorted(item_groups["wb"], key=lambda entry: ordered_sort_key(wb_order, entry)),
            "stones": sorted(item_groups["stones"], key=lambda entry: ordered_sort_key(stone_order, entry)),
            "reports": sorted(
                item_groups["reports"],
                key=lambda entry: (
                    report_order.get(
                        _report_icon_for_entry(
                            str(entry[1].get("item_id") or "") or None,
                            _inventory_display_label(entry[0], entry[1]),
                        )
                        or "",
                        9999,
                    ),
                    _inventory_display_label(entry[0], entry[1]).lower(),
                ),
            ),
            "weapon_parts": sorted(item_groups["weapon_parts"], key=lambda entry: ordered_sort_key(weapon_order, entry)),
            "tech_notes": sorted(item_groups["tech_notes"], key=lambda entry: ordered_sort_key(tech_order, entry)),
            "bd": sorted(item_groups["bd"], key=lambda entry: ordered_sort_key(bd_order, entry)),
            "other": sorted(item_groups["other"], key=lambda entry: _inventory_display_label(entry[0], entry[1]).lower()),
        }

        for category, entries in ordered_items.items():
            self._set_inventory_list_items(
                self._inventory_item_lists[category],
                self._inventory_item_summaries[category],
                entries,
            )

    def _build_stats_tab(self, root: QWidget) -> None:
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(12, self._ui_scale))

        header = QFrame()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
        )
        title = QLabel("Collection Statistics")
        title.setObjectName("title")
        subtitle = QLabel("Use ring summaries to compare ownership, roles, schools, and combat composition at a glance.")
        subtitle.setObjectName("count")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        self._stats_summary_line = QLabel("")
        self._stats_summary_line.setObjectName("filterSummary")
        layout.addWidget(self._stats_summary_line)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(scale_px(12, self._ui_scale))

        self._stats_summary_host = QWidget()
        self._stats_summary_cards = QGridLayout(self._stats_summary_host)
        self._stats_summary_cards.setContentsMargins(0, 0, 0, 0)
        self._stats_summary_cards.setHorizontalSpacing(scale_px(12, self._ui_scale))
        self._stats_summary_cards.setVerticalSpacing(scale_px(12, self._ui_scale))
        host_layout.addWidget(self._stats_summary_host)

        cards_wrap = QWidget()
        self._stats_cards_layout = QGridLayout(cards_wrap)
        self._stats_cards_layout.setContentsMargins(0, 0, 0, 0)
        self._stats_cards_layout.setHorizontalSpacing(scale_px(12, self._ui_scale))
        self._stats_cards_layout.setVerticalSpacing(scale_px(12, self._ui_scale))
        host_layout.addWidget(cards_wrap)
        host_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

    def _build_plan_tab(self, root: QWidget) -> None:
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(12, self._ui_scale))

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
        )
        header_layout.setSpacing(scale_px(10, self._ui_scale))

        title = QLabel("Plan Workspace")
        title.setObjectName("title")
        header_layout.addWidget(title)

        summary = QLabel("Search only when needed, then manage planned students as cards like the Students tab.")
        summary.setObjectName("count")
        header_layout.addWidget(summary, 1)
        layout.addWidget(header)

        quick_add_panel = QFrame()
        quick_add_panel.setObjectName("panel")
        quick_add_layout = QVBoxLayout(quick_add_panel)
        quick_add_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(12, self._ui_scale),
        )
        quick_add_layout.setSpacing(scale_px(8, self._ui_scale))

        quick_add_header = QHBoxLayout()
        quick_add_header.setContentsMargins(0, 0, 0, 0)
        quick_add_header.setSpacing(scale_px(10, self._ui_scale))
        title_add = QLabel("Quick Add")
        title_add.setObjectName("sectionTitle")
        quick_add_header.addWidget(title_add)
        quick_add_note = QLabel("Search by student name, id, or tag only when needed.")
        quick_add_note.setObjectName("count")
        quick_add_note.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        quick_add_header.addWidget(quick_add_note, 1)
        quick_add_layout.addLayout(quick_add_header)

        quick_add_row = QHBoxLayout()
        quick_add_row.setContentsMargins(0, 0, 0, 0)
        quick_add_row.setSpacing(scale_px(8, self._ui_scale))
        self._plan_search = QLineEdit()
        self._plan_search.setPlaceholderText("Type student name, id, or tag")
        self._plan_search.textChanged.connect(self._refresh_plan_lists)
        quick_add_row.addWidget(self._plan_search, 1)
        self._plan_add_button = ParallelogramButton("Add", style=self._card_button_style)
        self._plan_add_button.clicked.connect(self._add_selected_student_to_plan)
        quick_add_row.addWidget(self._plan_add_button, 0, Qt.AlignVCenter)
        quick_add_layout.addLayout(quick_add_row)

        self._plan_all_list = QListWidget()
        self._plan_all_list.currentItemChanged.connect(self._on_plan_all_item_changed)
        self._plan_all_list.setMaximumHeight(scale_px(132, self._ui_scale))
        self._plan_all_list.setVisible(False)
        quick_add_layout.addWidget(self._plan_all_list)

        self._plan_search_state = QLabel("Type a student name, id, or tag to search.")
        self._plan_search_state.setObjectName("filterSummary")
        quick_add_layout.addWidget(self._plan_search_state)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        plan_panel = QFrame()
        plan_panel.setObjectName("panel")
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale))
        plan_layout.setSpacing(scale_px(10, self._ui_scale))

        plan_header = QHBoxLayout()
        plan_header.setContentsMargins(0, 0, 0, 0)
        plan_header.setSpacing(scale_px(10, self._ui_scale))
        title_plan = QLabel("Planned Students")
        title_plan.setObjectName("sectionTitle")
        plan_header.addWidget(title_plan)
        self._plan_count_label = QLabel("")
        self._plan_count_label.setObjectName("count")
        plan_header.addWidget(self._plan_count_label, 1, Qt.AlignRight)
        plan_layout.addLayout(plan_header)

        self._plan_empty_label = QLabel("No students in plan yet. Search above to add your first student.")
        self._plan_empty_label.setObjectName("filterSummary")
        self._plan_empty_label.setWordWrap(True)
        plan_layout.addWidget(self._plan_empty_label)

        self._plan_grid = ParallelogramCardGrid(self._student_card_asset, self._ui_scale)
        self._plan_grid.setObjectName("studentGrid")
        self._plan_grid.current_changed.connect(self._on_plan_card_changed)
        self._plan_grid.layout_changed.connect(lambda *_: self._refresh_card_layout())
        plan_layout.addWidget(self._plan_grid, 1)

        plan_buttons = QHBoxLayout()
        self._plan_remove_button = QPushButton("Remove")
        self._plan_remove_button.clicked.connect(self._remove_selected_plan_student)
        plan_buttons.addWidget(self._plan_remove_button)
        self._plan_open_button = QPushButton("Open In Viewer")
        self._plan_open_button.clicked.connect(self._focus_selected_plan_student_in_viewer)
        plan_buttons.addWidget(self._plan_open_button)
        plan_buttons.addStretch(1)
        plan_layout.addLayout(plan_buttons)

        splitter.addWidget(plan_panel)

        editor_panel = QFrame()
        editor_panel.setObjectName("panel")
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(scale_px(16, self._ui_scale), scale_px(16, self._ui_scale), scale_px(16, self._ui_scale), scale_px(16, self._ui_scale))
        editor_layout.setSpacing(scale_px(10, self._ui_scale))

        self._plan_name = QLabel("Select a student")
        self._plan_name.setObjectName("detailName")
        editor_layout.addWidget(self._plan_name)

        self._plan_current = QLabel("")
        self._plan_current.setObjectName("detailSub")
        editor_layout.addWidget(self._plan_current)

        controls_wrap = QWidget()
        controls_layout = QHBoxLayout(controls_wrap)
        controls_layout.setContentsMargins(scale_px(10, self._ui_scale), scale_px(6, self._ui_scale), scale_px(10, self._ui_scale), scale_px(10, self._ui_scale))
        controls_layout.setSpacing(scale_px(18, self._ui_scale))

        left_column = QVBoxLayout()
        left_column.setContentsMargins(scale_px(2, self._ui_scale), 0, scale_px(2, self._ui_scale), 0)
        left_column.setSpacing(scale_px(16, self._ui_scale))
        right_column = QVBoxLayout()
        right_column.setContentsMargins(scale_px(2, self._ui_scale), 0, scale_px(2, self._ui_scale), 0)
        right_column.setSpacing(scale_px(16, self._ui_scale))
        controls_layout.addLayout(left_column, 8)
        controls_layout.addLayout(right_column, 5)

        progression_panel = QFrame()
        progression_panel.setObjectName("planSectionPanel")
        progression_layout = QVBoxLayout(progression_panel)
        progression_layout.setContentsMargins(scale_px(18, self._ui_scale), scale_px(16, self._ui_scale), scale_px(18, self._ui_scale), scale_px(16, self._ui_scale))
        progression_layout.setSpacing(scale_px(12, self._ui_scale))
        progression_title = QLabel("Growth Target")
        progression_title.setObjectName("sectionTitle")
        progression_layout.addWidget(progression_title)
        progression_row = QFrame()
        progression_row.setObjectName("planBand")
        progression_row_layout = QHBoxLayout(progression_row)
        progression_row_layout.setContentsMargins(scale_px(14, self._ui_scale), scale_px(10, self._ui_scale), scale_px(14, self._ui_scale), scale_px(10, self._ui_scale))
        progression_row_layout.setSpacing(scale_px(12, self._ui_scale))
        progression_label = QLabel("Star / Weapon Star")
        progression_label.setObjectName("detailSectionTitle")
        progression_label.setMinimumWidth(scale_px(118, self._ui_scale))
        progression_row_layout.addWidget(progression_label, 0, Qt.AlignTop)
        star_selector = PlanSegmentSelector(9, color_break=5, ui_scale=self._ui_scale)
        star_selector.valueChanged.connect(lambda value: self._on_plan_segment_changed("star_weapon", value))
        self._plan_segment_inputs["star_weapon"] = star_selector
        progression_row_layout.addWidget(star_selector, 1)
        progression_layout.addWidget(progression_row)
        left_column.addWidget(progression_panel)

        skill_panel = QFrame()
        skill_panel.setObjectName("planSectionPanel")
        skill_layout = QVBoxLayout(skill_panel)
        skill_layout.setContentsMargins(scale_px(18, self._ui_scale), scale_px(18, self._ui_scale), scale_px(18, self._ui_scale), scale_px(18, self._ui_scale))
        skill_layout.setSpacing(scale_px(12, self._ui_scale))
        skill_title = QLabel("Skills")
        skill_title.setObjectName("sectionTitle")
        skill_layout.addWidget(skill_title)
        for field_name, label, count in (
            ("target_ex_skill", "EX", MAX_TARGET_EX_SKILL),
            ("target_skill1", "Normal", MAX_TARGET_SKILL),
            ("target_skill2", "Passive", MAX_TARGET_SKILL),
            ("target_skill3", "Sub", MAX_TARGET_SKILL),
        ):
            row = QFrame()
            row.setObjectName("planBand")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(scale_px(14, self._ui_scale), scale_px(10, self._ui_scale), scale_px(14, self._ui_scale), scale_px(10, self._ui_scale))
            row_layout.setSpacing(scale_px(12, self._ui_scale))
            row_title = QLabel(label)
            row_title.setObjectName("detailSectionTitle")
            row_title.setMinimumWidth(scale_px(64, self._ui_scale))
            row_layout.addWidget(row_title)
            selector = PlanSegmentSelector(count, active_fill=ACCENT_STRONG, active_border=ACCENT, ui_scale=self._ui_scale)
            selector.valueChanged.connect(lambda value, name=field_name: self._on_plan_segment_changed(name, value))
            self._plan_segment_inputs[field_name] = selector
            row_layout.addWidget(selector, 1)
            skill_layout.addWidget(row)
        left_column.addWidget(skill_panel, 0)

        equipment_panel = QFrame()
        equipment_panel.setObjectName("planSectionPanel")
        equipment_layout = QVBoxLayout(equipment_panel)
        equipment_layout.setContentsMargins(scale_px(18, self._ui_scale), scale_px(16, self._ui_scale), scale_px(18, self._ui_scale), scale_px(16, self._ui_scale))
        equipment_layout.setSpacing(scale_px(12, self._ui_scale))
        equipment_title = QLabel("Equipment Tier")
        equipment_title.setObjectName("sectionTitle")
        equipment_layout.addWidget(equipment_title)

        equipment_body = QWidget()
        equipment_body.setObjectName("planTransparent")
        equipment_body_layout = QHBoxLayout(equipment_body)
        equipment_body_layout.setContentsMargins(0, 0, 0, 0)
        equipment_body_layout.setSpacing(scale_px(10, self._ui_scale))
        equipment_main = QVBoxLayout()
        equipment_main.setContentsMargins(0, 0, 0, 0)
        equipment_main.setSpacing(scale_px(10, self._ui_scale))
        equipment_body_layout.addLayout(equipment_main, 9)

        self._plan_unique_item_panel = QFrame()
        self._plan_unique_item_panel.setObjectName("planBand")
        unique_layout = QVBoxLayout(self._plan_unique_item_panel)
        unique_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(8, self._ui_scale), scale_px(12, self._ui_scale), scale_px(8, self._ui_scale))
        unique_layout.setSpacing(scale_px(8, self._ui_scale))
        unique_title = QLabel("Unique Item")
        unique_title.setObjectName("detailSectionTitle")
        unique_layout.addWidget(unique_title)
        self._plan_unique_item_selector = PlanSegmentSelector(2, active_fill=PALETTE_SOFT, active_border="#ffffff", inactive_fill=_mix_hex(SURFACE_ALT, BG, 0.14), ui_scale=self._ui_scale)
        self._plan_unique_item_selector.valueChanged.connect(lambda value: self._on_plan_segment_changed("target_equip4_tier", value))
        self._plan_segment_inputs["target_equip4_tier"] = self._plan_unique_item_selector
        unique_layout.addWidget(self._plan_unique_item_selector)
        equipment_body_layout.addWidget(self._plan_unique_item_panel, 3)
        equipment_layout.addWidget(equipment_body)

        for field_name, slot_index in (
            ("target_equip1_tier", 1),
            ("target_equip2_tier", 2),
            ("target_equip3_tier", 3),
        ):
            row = QFrame()
            row.setObjectName("planBand")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(8, self._ui_scale), scale_px(12, self._ui_scale), scale_px(8, self._ui_scale))
            row_layout.setSpacing(scale_px(10, self._ui_scale))
            row_title = QLabel(f"Equip {slot_index}")
            row_title.setObjectName("detailSectionTitle")
            row_title.setMinimumWidth(scale_px(70, self._ui_scale))
            self._plan_equipment_labels[field_name] = row_title
            row_layout.addWidget(row_title)
            selector = PlanSegmentSelector(MAX_TARGET_EQUIP_TIER, active_fill=PALETTE_SOFT, active_border="#ffffff", inactive_fill=_mix_hex(SURFACE_ALT, BG, 0.14), ui_scale=self._ui_scale)
            selector.valueChanged.connect(lambda value, name=field_name: self._on_plan_segment_changed(name, value))
            self._plan_segment_inputs[field_name] = selector
            row_layout.addWidget(selector, 1)
            equipment_main.addWidget(row)
        left_column.addWidget(equipment_panel, 0)

        level_panel = QFrame()
        level_panel.setObjectName("planSectionPanel")
        level_layout = QVBoxLayout(level_panel)
        level_layout.setContentsMargins(scale_px(18, self._ui_scale), scale_px(16, self._ui_scale), scale_px(18, self._ui_scale), scale_px(16, self._ui_scale))
        level_layout.setSpacing(scale_px(10, self._ui_scale))
        level_title = QLabel("Level Targets")
        level_title.setObjectName("sectionTitle")
        level_layout.addWidget(level_title)
        for field_name, label, maximum in (
            ("target_level", "Student", 90),
            ("target_weapon_level", "Weapon", MAX_TARGET_WEAPON_LEVEL),
            ("target_equip1_level", "Equip 1", MAX_TARGET_EQUIP_LEVEL),
            ("target_equip2_level", "Equip 2", MAX_TARGET_EQUIP_LEVEL),
            ("target_equip3_level", "Equip 3", MAX_TARGET_EQUIP_LEVEL),
        ):
            row = QFrame()
            row.setObjectName("planBand")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(8, self._ui_scale), scale_px(12, self._ui_scale), scale_px(8, self._ui_scale))
            row_layout.setSpacing(scale_px(8, self._ui_scale))
            row_title = QLabel(label)
            row_title.setObjectName("detailSectionTitle")
            row_title.setMinimumWidth(scale_px(62, self._ui_scale))
            self._plan_level_row_labels[field_name] = row_title
            row_layout.addWidget(row_title)
            selector = PlanStepper(maximum, ui_scale=self._ui_scale)
            selector.valueChanged.connect(lambda value, name=field_name: self._on_plan_digit_changed(name, value))
            self._plan_level_inputs[field_name] = selector
            self._plan_level_rows[field_name] = row
            row_layout.addWidget(selector, 1)
            level_layout.addWidget(row)

        stat_label_row = QLabel("Bond Stats")
        stat_label_row.setObjectName("detailSectionTitle")
        stat_label_row.setStyleSheet(f"color: {PALETTE_SOFT};")
        level_layout.addWidget(stat_label_row)
        self._plan_stat_caption = stat_label_row

        for field_name, label in (
            ("target_stat_hp", "HP"),
            ("target_stat_atk", "ATK"),
            ("target_stat_heal", "HEAL"),
        ):
            row = QFrame()
            row.setObjectName("planBand")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(8, self._ui_scale), scale_px(12, self._ui_scale), scale_px(8, self._ui_scale))
            row_layout.setSpacing(scale_px(8, self._ui_scale))
            row_title = QLabel(label)
            row_title.setObjectName("detailSectionTitle")
            row_title.setMinimumWidth(scale_px(62, self._ui_scale))
            row_layout.addWidget(row_title)
            selector = PlanStepper(25, ui_scale=self._ui_scale)
            selector.valueChanged.connect(lambda value, name=field_name: self._on_plan_digit_changed(name, value))
            self._plan_level_inputs[field_name] = selector
            self._plan_stat_rows[field_name] = row
            row_layout.addWidget(selector, 1)
            level_layout.addWidget(row)
        level_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        right_column.addWidget(level_panel, 0)

        self._plan_student_summary = QLabel("Need materials preview will come later.")
        self._plan_total_summary = QLabel("")
        self._plan_student_summary.setVisible(False)
        self._plan_total_summary.setVisible(False)
        editor_layout.addWidget(controls_wrap, 0)
        editor_layout.addWidget(quick_add_panel, 0)
        editor_layout.addStretch(1)
        splitter.addWidget(editor_panel)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)

    def _plan_goal_map(self) -> dict[str, StudentGoal]:
        return self._plan.goal_map()

    def _save_plan(self) -> None:
        save_plan(self._plan_path, self._plan)

    def _get_or_create_goal(self, student_id: str) -> StudentGoal:
        for goal in self._plan.goals:
            if goal.student_id == student_id:
                return goal
        goal = StudentGoal(student_id=student_id)
        self._plan.goals.append(goal)
        return goal

    def _build_student_card(self, record) -> StudentCardWidget:
        divider_primary, divider_secondary = _student_divider_colors(record)
        card = StudentCardWidget(
            card_asset=self._student_card_asset,
            student_id=record.student_id,
            title=record.title,
            owned=record.owned,
            divider_left=QColor(divider_primary),
            divider_right=QColor(divider_secondary),
        )
        card.setToolTip(record.student_id)
        return card

    def _current_plan_grid_student_id(self) -> str | None:
        if not hasattr(self, "_plan_grid"):
            return None
        return self._plan_grid.current_card_id()

    def _set_plan_search_selection(self, student_id: str | None) -> None:
        if not hasattr(self, "_plan_all_list"):
            return
        previous = self._plan_all_list.blockSignals(True)
        try:
            self._plan_all_list.clearSelection()
            self._plan_all_list.setCurrentRow(-1)
            if not student_id:
                return
            for index in range(self._plan_all_list.count()):
                item = self._plan_all_list.item(index)
                if item.data(Qt.UserRole) == student_id:
                    self._plan_all_list.setCurrentItem(item)
                    break
        finally:
            self._plan_all_list.blockSignals(previous)

    def _set_plan_grid_selection(self, student_id: str | None) -> None:
        if not hasattr(self, "_plan_grid"):
            return
        target_id = student_id if student_id in self._plan_card_by_id else None
        previous = self._plan_grid.blockSignals(True)
        try:
            self._plan_grid.set_current_card(target_id)
        finally:
            self._plan_grid.blockSignals(previous)

    def _has_any_card_target(self, student_id: str) -> bool:
        return student_id in self._item_by_id or student_id in self._plan_card_by_id

    def _update_plan_actions(self) -> None:
        search_selected = self._plan_current_all_student_id()
        planned_selected = self._current_plan_grid_student_id()
        if hasattr(self, "_plan_add_button"):
            self._plan_add_button.setEnabled(bool(search_selected))
        if hasattr(self, "_plan_remove_button"):
            self._plan_remove_button.setEnabled(bool(planned_selected))
        if hasattr(self, "_plan_open_button"):
            self._plan_open_button.setEnabled(bool(planned_selected))

    @staticmethod
    def _record_has_weapon_system(record: StudentRecord) -> bool:
        return (record.weapon_state or "") != "no_weapon_system"

    @staticmethod
    def _plan_allows_weapon_targets(record: StudentRecord) -> bool:
        # In the planner, allow future weapon goals even before the weapon
        # system is unlocked on the current record.
        return True

    @staticmethod
    def _weapon_level_cap_for_star(weapon_star: int) -> int:
        return {
            1: 30,
            2: 40,
            3: 50,
            4: 60,
        }.get(max(0, int(weapon_star)), 0)

    @staticmethod
    def _record_base_star(record: StudentRecord) -> int:
        try:
            rarity = int(record.rarity or 1)
        except (TypeError, ValueError):
            rarity = 1
        return max(1, min(5, rarity))

    @staticmethod
    def _record_current_star(record: StudentRecord) -> int:
        return max(StudentViewerWindow._record_base_star(record), int(record.star or 0))

    @staticmethod
    def _record_current_skill(raw_value: int | None) -> int:
        return max(1, int(raw_value or 0))

    @staticmethod
    def _record_weapon_level(record: StudentRecord) -> int:
        if (record.weapon_state or "") in ("weapon_equipped", "weapon_unlocked_not_equipped"):
            return max(1, int(record.weapon_level or 0) or 1)
        return 0

    @staticmethod
    def _record_star_weapon_total(record: StudentRecord) -> int:
        weapon_star = max(0, int(record.weapon_star or 0))
        if (record.weapon_state or "") == "no_weapon_system":
            weapon_star = 0
        if weapon_star > 0:
            return 5 + weapon_star
        return StudentViewerWindow._record_current_star(record)

    def _current_or_target_weapon_star(self, record: StudentRecord, goal: StudentGoal | None = None) -> int:
        current_weapon_star = max(0, int(record.weapon_star or 0))
        if goal is None:
            return current_weapon_star
        return max(current_weapon_star, int(getattr(goal, "target_weapon_star", 0) or 0))

    def _current_or_target_star(self, record: StudentRecord, goal: StudentGoal | None = None) -> int:
        current_star = self._record_current_star(record)
        if goal is None:
            return current_star
        return max(current_star, int(getattr(goal, "target_star", 0) or 0))

    @staticmethod
    def _current_equipment_level(current_tier: int, raw_level: int | None) -> int:
        if raw_level and raw_level > 0:
            return min(int(raw_level), EQUIPMENT_TIER_MAX_LEVEL.get(max(current_tier, 0), MAX_TARGET_EQUIP_LEVEL))
        if current_tier <= 0:
            return 0
        return 1

    @staticmethod
    def _minimum_equipment_tier_for_level(level: int) -> int:
        normalized = max(0, int(level))
        for tier, max_level in sorted(EQUIPMENT_TIER_MAX_LEVEL.items()):
            if normalized <= max_level:
                return tier
        return MAX_TARGET_EQUIP_TIER

    @staticmethod
    def _equipment_level_cap_for_tier(tier: int) -> int:
        return EQUIPMENT_TIER_MAX_LEVEL.get(max(0, int(tier)), MAX_TARGET_EQUIP_LEVEL)

    @staticmethod
    def _goal_value(goal: StudentGoal | None, field_name: str, current_value: int) -> int:
        if goal is None:
            return current_value
        raw_value = getattr(goal, field_name, None)
        if raw_value is None:
            return current_value
        return max(current_value, int(raw_value))

    def _sync_plan_goal(self, goal: StudentGoal, record: StudentRecord) -> None:
        current_star = self._record_current_star(record)
        current_weapon_star = max(0, int(record.weapon_star or 0))
        current_weapon_level = self._record_weapon_level(record)
        allows_weapon_targets = self._plan_allows_weapon_targets(record)

        target_star = max(current_star, int(goal.target_star or 0))
        target_weapon_star = max(current_weapon_star, int(goal.target_weapon_star or 0))
        target_weapon_level = max(current_weapon_level, int(goal.target_weapon_level or 0))

        if not allows_weapon_targets:
            target_weapon_star = current_weapon_star
            target_weapon_level = current_weapon_level
        if target_weapon_star > 0 or target_weapon_level > 0:
            target_star = max(target_star, 5)
        if int(getattr(goal, "target_equip4_tier", 0) or 0) > 0:
            target_star = max(target_star, 3)
        target_weapon_level = min(target_weapon_level, self._weapon_level_cap_for_star(target_weapon_star))

        goal.target_star = target_star if target_star > current_star else None
        goal.target_weapon_star = target_weapon_star if allows_weapon_targets and target_weapon_star > current_weapon_star else None
        goal.target_weapon_level = target_weapon_level if allows_weapon_targets and target_weapon_level > current_weapon_level else None

        for slot_index in range(1, 4):
            tier_field = f"target_equip{slot_index}_tier"
            level_field = f"target_equip{slot_index}_level"
            current_tier = _parse_tier_number(getattr(record, f"equip{slot_index}", None)) or 0
            current_level = self._current_equipment_level(current_tier, getattr(record, f"equip{slot_index}_level", None))
            raw_target_tier = getattr(goal, tier_field)
            target_level = max(current_level, int(getattr(goal, level_field) or 0))
            target_tier = max(current_tier, int(raw_target_tier or 0))
            if target_level > 0:
                if raw_target_tier is not None and target_tier > 0:
                    target_level = min(target_level, self._equipment_level_cap_for_tier(target_tier))
                else:
                    target_tier = max(target_tier, self._minimum_equipment_tier_for_level(target_level))
                target_level = min(target_level, EQUIPMENT_TIER_MAX_LEVEL.get(target_tier, MAX_TARGET_EQUIP_LEVEL))
            setattr(goal, level_field, target_level if target_level > current_level else None)
            setattr(goal, tier_field, target_tier if target_tier > current_tier else None)

        if self._record_supports_unique_item(record) and hasattr(goal, "target_equip4_tier"):
            current_unique_tier = _parse_tier_number(record.equip4) or 0
            target_unique_tier = max(current_unique_tier, int(getattr(goal, "target_equip4_tier") or 0))
            if target_star < 3:
                target_unique_tier = current_unique_tier
            goal.target_equip4_tier = target_unique_tier if target_unique_tier > current_unique_tier else None

    @staticmethod
    def _record_has_unique_item(record: StudentRecord) -> bool:
        return bool((record.equip4 or "").strip())

    @staticmethod
    def _record_supports_unique_item(record: StudentRecord) -> bool:
        if StudentViewerWindow._record_has_unique_item(record):
            return True
        return bool(student_meta.favorite_item_enabled(record.student_id))

    @staticmethod
    def _equipment_slot_labels(record: StudentRecord) -> list[str]:
        labels = list(student_meta.equipment_slots(record.student_id) or [])
        fallback = ["Equip 1", "Equip 2", "Equip 3"]
        normalized: list[str] = []
        for index in range(3):
            try:
                label = str(labels[index] or fallback[index]).strip()
            except Exception:
                label = fallback[index]
            normalized.append(label.title())
        return normalized

    def _plan_supports_field(self, goal: StudentGoal | None, field_name: str) -> bool:
        if goal is None:
            return False
        return hasattr(goal, field_name)

    def _refresh_plan_editor_visibility(self, record: StudentRecord, goal: StudentGoal | None) -> None:
        labels = self._equipment_slot_labels(record)
        for idx, field_name in enumerate(("target_equip1_tier", "target_equip2_tier", "target_equip3_tier")):
            label_widget = self._plan_equipment_labels.get(field_name)
            if label_widget is not None:
                label_widget.setText(labels[idx])
        for idx, field_name in enumerate(("target_equip1_level", "target_equip2_level", "target_equip3_level"), start=1):
            label_widget = self._plan_level_row_labels.get(field_name)
            if label_widget is not None:
                label_widget.setText(labels[idx - 1])

        target_weapon_star = self._goal_value(goal, "target_weapon_star", max(0, int(record.weapon_star or 0)))
        target_weapon_level = self._goal_value(goal, "target_weapon_level", self._record_weapon_level(record))
        show_weapon_level = self._plan_allows_weapon_targets(record) and (target_weapon_star > 0 or target_weapon_level > 0)
        weapon_row = self._plan_level_rows.get("target_weapon_level")
        if weapon_row is not None:
            weapon_row.setVisible(show_weapon_level)

        show_stats = self._goal_value(goal, "target_level", max(0, int(record.level or 0))) >= 90
        self._plan_stat_caption.setVisible(show_stats)
        for row in self._plan_stat_rows.values():
            row.setVisible(show_stats)

        has_unique_item = self._record_supports_unique_item(record)
        self._plan_unique_item_panel.setVisible(has_unique_item)
        if has_unique_item:
            selector = self._plan_unique_item_selector
            selector.setEnabled(self._plan_supports_field(goal, "target_equip4_tier") and self._current_or_target_star(record, goal) >= 3)

    def _refresh_plan_editor_controls(self, record: StudentRecord, goal: StudentGoal | None) -> None:
        current_total = self._record_star_weapon_total(record)
        current_star = self._record_current_star(record)
        current_weapon_star = max(0, int(record.weapon_star or 0))
        target_star = self._goal_value(goal, "target_star", current_star)
        target_weapon_star = self._goal_value(goal, "target_weapon_star", current_weapon_star)
        target_total = target_star if target_weapon_star <= 0 else 5 + target_weapon_star
        self._plan_segment_inputs["star_weapon"].setState(
            minimum_value=current_total,
            value=target_total,
            enabled_count=9 if self._plan_allows_weapon_targets(record) else 5,
        )

        for field_name, current_value in (
            ("target_ex_skill", self._record_current_skill(record.ex_skill)),
            ("target_skill1", self._record_current_skill(record.skill1)),
            ("target_skill2", self._record_current_skill(record.skill2)),
            ("target_skill3", self._record_current_skill(record.skill3)),
        ):
            self._plan_segment_inputs[field_name].setState(
                minimum_value=current_value,
                value=self._goal_value(goal, field_name, current_value),
            )

        for slot_index in range(1, 4):
            tier_field = f"target_equip{slot_index}_tier"
            level_field = f"target_equip{slot_index}_level"
            current_tier = _parse_tier_number(getattr(record, f"equip{slot_index}", None)) or 0
            current_level = self._current_equipment_level(current_tier, getattr(record, f"equip{slot_index}_level", None))
            target_tier = self._goal_value(goal, tier_field, current_tier)
            self._plan_segment_inputs[tier_field].setState(
                minimum_value=current_tier,
                value=target_tier,
            )
            self._plan_level_inputs[level_field].setMaximumValue(self._equipment_level_cap_for_tier(target_tier))
            self._plan_level_inputs[level_field].setState(
                minimum_value=current_level,
                value=self._goal_value(goal, level_field, current_level),
            )

        current_level = max(0, int(record.level or 0))
        current_weapon_level = self._record_weapon_level(record)
        self._plan_level_inputs["target_level"].setState(
            minimum_value=current_level,
            value=self._goal_value(goal, "target_level", current_level),
        )
        weapon_level_selector = self._plan_level_inputs["target_weapon_level"]
        target_weapon_star = self._current_or_target_weapon_star(record, goal)
        weapon_level_selector.setMaximumValue(self._weapon_level_cap_for_star(target_weapon_star))
        weapon_level_selector.setEnabled(self._plan_allows_weapon_targets(record))
        weapon_level_selector.setState(
            minimum_value=current_weapon_level,
            value=self._goal_value(goal, "target_weapon_level", current_weapon_level),
        )

        for field_name, current_value in (
            ("target_stat_hp", max(0, int(record.stat_hp or 0))),
            ("target_stat_atk", max(0, int(record.stat_atk or 0))),
            ("target_stat_heal", max(0, int(record.stat_heal or 0))),
        ):
            selector = self._plan_level_inputs.get(field_name)
            if selector is None:
                continue
            selector.setEnabled(self._plan_supports_field(goal, field_name))
            selector.setState(
                minimum_value=current_value,
                value=self._goal_value(goal, field_name, current_value),
            )

        if self._record_supports_unique_item(record):
            current_unique_tier = _parse_tier_number(record.equip4) or 0
            self._plan_unique_item_selector.setState(
                minimum_value=current_unique_tier,
                value=self._goal_value(goal, "target_equip4_tier", current_unique_tier),
                enabled_count=2 if self._current_or_target_star(record, goal) >= 3 else 0,
            )

        self._refresh_plan_editor_visibility(record, goal)

    def _on_plan_segment_changed(self, field_name: str, value: int) -> None:
        if self._plan_editor_guard:
            return
        student_id = self._selected_plan_student_id or self._plan_current_all_student_id()
        if not student_id:
            return
        record = self._records_by_id.get(student_id)
        if record is None:
            return
        goal = self._get_or_create_goal(student_id)

        if field_name == "star_weapon":
            target_star = min(5, value)
            target_weapon_star = max(0, value - 5)
            goal.target_star = target_star if target_star > self._record_current_star(record) else None
            goal.target_weapon_star = target_weapon_star if target_weapon_star > max(0, int(record.weapon_star or 0)) else None
        else:
            current_value = 0
            if field_name == "target_ex_skill":
                current_value = self._record_current_skill(record.ex_skill)
            elif field_name == "target_skill1":
                current_value = self._record_current_skill(record.skill1)
            elif field_name == "target_skill2":
                current_value = self._record_current_skill(record.skill2)
            elif field_name == "target_skill3":
                current_value = self._record_current_skill(record.skill3)
            elif field_name.startswith("target_equip"):
                slot_index = int(field_name[len("target_equip")])
                current_value = _parse_tier_number(getattr(record, f"equip{slot_index}", None)) or 0
            if self._plan_supports_field(goal, field_name):
                setattr(goal, field_name, value if value > current_value else None)

        self._sync_plan_goal(goal, record)
        self._save_plan()
        self._selected_plan_student_id = student_id
        self._load_plan_student(student_id)
        self._refresh_plan_lists()
        self._set_plan_grid_selection(student_id)
        self._refresh_plan_totals()

    def _on_plan_digit_changed(self, field_name: str, value: int) -> None:
        if self._plan_editor_guard:
            return
        student_id = self._selected_plan_student_id or self._plan_current_all_student_id()
        if not student_id:
            return
        record = self._records_by_id.get(student_id)
        if record is None:
            return
        goal = self._get_or_create_goal(student_id)

        if field_name == "target_level":
            current_value = max(0, int(record.level or 0))
        elif field_name == "target_weapon_level":
            current_value = self._record_weapon_level(record)
        elif field_name == "target_stat_hp":
            current_value = max(0, int(record.stat_hp or 0))
        elif field_name == "target_stat_atk":
            current_value = max(0, int(record.stat_atk or 0))
        elif field_name == "target_stat_heal":
            current_value = max(0, int(record.stat_heal or 0))
        else:
            slot_index = int(field_name[len("target_equip")])
            current_tier = _parse_tier_number(getattr(record, f"equip{slot_index}", None)) or 0
            current_value = self._current_equipment_level(current_tier, getattr(record, f"equip{slot_index}_level", None))
        if self._plan_supports_field(goal, field_name):
            setattr(goal, field_name, value if value > current_value else None)

        self._sync_plan_goal(goal, record)
        self._save_plan()
        self._selected_plan_student_id = student_id
        self._load_plan_student(student_id)
        self._refresh_plan_lists()
        self._set_plan_grid_selection(student_id)
        self._refresh_plan_totals()

    def _refresh_plan_lists(self) -> None:
        if not hasattr(self, "_plan_all_list"):
            return
        query = self._plan_search.text().strip().casefold()
        current_all = self._plan_current_all_student_id()
        current_plan = self._current_plan_grid_student_id() or self._selected_plan_student_id
        goal_map = self._plan_goal_map()

        self._plan_all_list.clear()
        match_count = 0
        if query:
            for record in sorted(self._all_students, key=lambda item: item.title.lower()):
                if query not in student_meta.search_blob(record.student_id, record.title):
                    continue
                status = "Planned" if record.student_id in goal_map else ("Owned" if record.owned else "Unowned")
                item = QListWidgetItem(f"{record.title}\n{status}")
                item.setData(Qt.UserRole, record.student_id)
                if record.student_id in goal_map:
                    item.setForeground(QColor("#84d0ff"))
                self._plan_all_list.addItem(item)
                match_count += 1

        self._plan_all_list.setVisible(bool(query))
        if not query:
            self._plan_search_state.setText("Type a student name, id, or tag to search.")
        elif match_count:
            self._plan_search_state.setText(f"{match_count} students found. Select one and add it to the plan.")
        else:
            self._plan_search_state.setText("No students matched that search.")

        self._plan_grid.clear_cards()
        self._plan_card_by_id.clear()
        planned_cards: list[StudentCardWidget] = []
        for goal in sorted(self._plan.goals, key=lambda entry: self._records_by_id.get(entry.student_id).title.lower() if entry.student_id in self._records_by_id else entry.student_id):
            record = self._records_by_id.get(goal.student_id)
            if record is None:
                continue
            card = self._build_student_card(record)
            planned_cards.append(card)
            self._plan_card_by_id[record.student_id] = card

        if planned_cards:
            self._plan_grid.add_cards(planned_cards)
            for student_id in self._plan_card_by_id:
                self._enqueue_thumb(student_id)

        self._plan_count_label.setText(f"{len(planned_cards)} students")
        self._plan_empty_label.setVisible(not planned_cards)
        self._plan_grid.setVisible(bool(planned_cards))

        self._set_plan_search_selection(current_all)
        self._set_plan_grid_selection(current_plan)
        focused_id = current_plan if current_plan in self._plan_card_by_id else self._plan_current_all_student_id()
        if focused_id:
            self._selected_plan_student_id = focused_id if focused_id in goal_map else None
            self._load_plan_student(focused_id)
        else:
            self._selected_plan_student_id = None
            self._clear_plan_editor()
        self._update_plan_actions()

    def _plan_current_all_student_id(self) -> str | None:
        item = self._plan_all_list.currentItem() if hasattr(self, "_plan_all_list") else None
        return item.data(Qt.UserRole) if item else None

    def _on_plan_all_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self._update_plan_actions()
            return
        student_id = str(current.data(Qt.UserRole))
        self._selected_plan_student_id = student_id if student_id in self._plan_goal_map() else None
        self._set_plan_grid_selection(student_id if student_id in self._plan_goal_map() else None)
        self._load_plan_student(student_id)
        self._update_plan_actions()

    def _on_plan_card_changed(self, current: str | None, _previous: str | None) -> None:
        if current is None:
            self._selected_plan_student_id = None
            self._update_plan_actions()
            return
        self._selected_plan_student_id = current
        self._set_plan_search_selection(current)
        self._load_plan_student(current)
        self._update_plan_actions()

    def _add_selected_student_to_plan(self) -> None:
        student_id = self._plan_current_all_student_id() or self._selected_plan_student_id
        if not student_id:
            return
        self._get_or_create_goal(student_id)
        self._selected_plan_student_id = student_id
        self._save_plan()
        self._refresh_plan_lists()
        self._set_plan_grid_selection(student_id)
        self._update_plan_student_summary(student_id)
        self._refresh_plan_totals()
        self._update_plan_actions()

    def _remove_selected_plan_student(self) -> None:
        student_id = self._current_plan_grid_student_id() or self._selected_plan_student_id
        if not student_id:
            return
        self._plan.goals = [goal for goal in self._plan.goals if goal.student_id != student_id]
        self._selected_plan_student_id = None
        self._save_plan()
        self._refresh_plan_lists()
        self._refresh_plan_totals()
        self._update_plan_actions()

    def _focus_selected_plan_student_in_viewer(self) -> None:
        if not self._selected_plan_student_id:
            return
        if self._selected_plan_student_id in self._item_by_id:
            self._student_grid.set_current_card(self._selected_plan_student_id)

    def _load_plan_student(self, student_id: str) -> None:
        record = self._records_by_id.get(student_id)
        if record is None:
            self._clear_plan_editor()
            return
        goal = self._plan_goal_map().get(student_id)
        self._plan_editor_guard = True
        try:
            self._plan_name.setText(record.title)
            self._plan_current.setText("Owned" if record.owned else "Unowned")
            for selector in self._plan_segment_inputs.values():
                selector.setEnabled(True)
            for selector in self._plan_level_inputs.values():
                selector.setEnabled(True)
            self._refresh_plan_editor_controls(record, goal)
        finally:
            self._plan_editor_guard = False
        self._update_plan_student_summary(student_id)

    def _clear_plan_editor(self) -> None:
        self._plan_editor_guard = True
        try:
            self._plan_name.setText("Select a student")
            self._plan_current.setText("")
            for selector in self._plan_segment_inputs.values():
                selector.setEnabled(False)
                selector.setState(minimum_value=0, value=0, enabled_count=selector._count)
            for selector in self._plan_level_inputs.values():
                selector.setEnabled(False)
                selector.setState(minimum_value=0, value=0)
        finally:
            self._plan_editor_guard = False
        if hasattr(self, "_plan_unique_item_panel"):
            self._plan_unique_item_panel.setVisible(False)
        if hasattr(self, "_plan_stat_caption"):
            self._plan_stat_caption.setVisible(False)
        for row in getattr(self, "_plan_stat_rows", {}).values():
            row.setVisible(False)
        self._plan_student_summary.setText("No student selected")
        self._update_plan_actions()

    def _update_plan_student_summary(self, student_id: str) -> None:
        record = self._records_by_id.get(student_id)
        goal = self._plan_goal_map().get(student_id)
        if record is None or goal is None:
            self._plan_student_summary.setText("Add this student to the plan to calculate costs.")
            return
        summary = calculate_goal_cost(record, goal)
        self._plan_student_summary.setText(self._format_cost_summary(summary))

    def _add_current_student_to_plan(self) -> None:
        student_id = self._current_student_id()
        if not student_id:
            return
        self._get_or_create_goal(student_id)
        self._selected_plan_student_id = student_id
        self._save_plan()
        self._refresh_plan_lists()
        self._set_plan_grid_selection(student_id)
        self._refresh_plan_totals()
        self._update_plan_actions()

    def _refresh_plan_totals(self) -> None:
        if not hasattr(self, "_plan_total_summary"):
            return
        total = calculate_plan_totals(self._records_by_id, self._plan)
        self._plan_total_summary.setText(
            f"{len(self._plan.goals)} students in plan\n{self._format_cost_summary(total)}"
        )
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _refresh_stats_tab(self) -> None:
        if self._stats_cards_layout is None or self._stats_summary_host is None:
            return

        while self._stats_summary_cards.count():
            item = self._stats_summary_cards.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        while self._stats_cards_layout.count():
            item = self._stats_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        total = len(self._filtered_students)
        owned = sum(1 for record in self._filtered_students if record.owned)
        planned = sum(1 for record in self._filtered_students if record.student_id in self._plan_goal_map())
        avg_level = round(sum((record.level or 0) for record in self._filtered_students if record.owned) / max(1, owned), 1) if owned else 0
        avg_star = round(sum(record.star for record in self._filtered_students if record.owned) / max(1, owned), 1) if owned else 0

        summary_cards = (
            ("Visible Students", str(total), "Current filtered collection"),
            ("Owned Students", str(owned), "Owned among visible students"),
            ("Planned Students", str(planned), "Already added to planner"),
            ("Average Level", f"{avg_level}", "Owned students only"),
            ("Average Star", f"{avg_star}", "Owned students only"),
        )
        for index, (label, value, sub) in enumerate(summary_cards):
            card = QFrame()
            card.setObjectName("summaryCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale))
            text_label = QLabel(label)
            text_label.setObjectName("metricLabel")
            value_label = QLabel(value)
            value_label.setObjectName("metricValue")
            sub_label = QLabel(sub)
            sub_label.setObjectName("kpiValueSub")
            card_layout.addWidget(text_label)
            card_layout.addWidget(value_label)
            card_layout.addWidget(sub_label)
            self._stats_summary_cards.addWidget(card, 0, index)

        self._stats_summary_line.setText(f"Statistics reflect the {len(self._filtered_students)} students currently visible in the Students tab.")

        chart_specs = (
            ("Ownership", "owned"),
            ("School Distribution", "school"),
            ("Combat Class", "combat_class"),
            ("Attack Type", "attack_type"),
            ("Defense Type", "defense_type"),
            ("Role Distribution", "role"),
        )
        for index, (title, field_name) in enumerate(chart_specs):
            rows = build_distribution(self._filtered_students, field_name)
            card = QFrame()
            card.setObjectName("statPanel")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(scale_px(16, self._ui_scale), scale_px(16, self._ui_scale), scale_px(16, self._ui_scale), scale_px(16, self._ui_scale))
            card_layout.setSpacing(scale_px(10, self._ui_scale))
            title_label = QLabel(title)
            title_label.setObjectName("sectionTitle")
            card_layout.addWidget(title_label)
            if rows:
                top = rows[0]
                top_wrap = QHBoxLayout()
                donut = DonutWidget(top.percent, top.color, f"{top.percent:.0f}%", self._ui_scale)
                top_wrap.addWidget(donut, 0, Qt.AlignLeft | Qt.AlignVCenter)
                top_text = QVBoxLayout()
                main_label = QLabel(top.label)
                main_label.setObjectName("metricValue")
                count_label = QLabel(f"{top.count} students")
                count_label.setObjectName("detailSub")
                top_text.addWidget(main_label)
                top_text.addWidget(count_label)
                top_wrap.addLayout(top_text, 1)
                card_layout.addLayout(top_wrap)
                for row in rows[:4]:
                    row_label = QLabel(f"{row.label}  ·  {row.count}  ·  {row.percent:.1f}%")
                    row_label.setObjectName("detailSub")
                    card_layout.addWidget(row_label)
            else:
                empty = QLabel("No data available for this distribution.")
                empty.setObjectName("detailSub")
                card_layout.addWidget(empty)
            self._stats_cards_layout.addWidget(card, index // 2, index % 2)

    def _format_cost_summary(self, summary: PlanCostSummary) -> str:
        lines = [
            f"Credits: {summary.credits:,}",
            f"EXP: {summary.level_exp:,}",
        ]
        if summary.level_exp_items:
            lines.append("Level reports:")
            for key, value in sorted(summary.level_exp_items.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.equipment_exp:
            lines.append(f"Equipment EXP: {summary.equipment_exp:,}")
        if summary.equipment_exp_items:
            lines.append("Equipment exp items:")
            for key, value in sorted(summary.equipment_exp_items.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.weapon_exp:
            lines.append(f"Weapon EXP: {summary.weapon_exp:,}")
        if summary.weapon_exp_items:
            lines.append("Weapon exp items:")
            for key, value in sorted(summary.weapon_exp_items.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.star_materials:
            lines.append("Star materials:")
            for key, value in sorted(summary.star_materials.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.equipment_materials:
            lines.append("Equipment materials:")
            for key, value in sorted(summary.equipment_materials.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.skill_books:
            lines.append("Skill books:")
            for key, value in sorted(summary.skill_books.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.ex_ooparts:
            lines.append("EX ooparts:")
            for key, value in sorted(summary.ex_ooparts.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.skill_ooparts:
            lines.append("Skill ooparts:")
            for key, value in sorted(summary.skill_ooparts.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.stat_materials:
            lines.append("Stat materials:")
            for key, value in sorted(summary.stat_materials.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.stat_levels:
            lines.append("Stat targets:")
            for key, value in sorted(summary.stat_levels.items()):
                lines.append(f"- {key}: +{value}")
        if summary.warnings:
            lines.append("Notes:")
            for warning in dict.fromkeys(summary.warnings):
                lines.append(f"- {warning}")
        return "\n".join(lines)

    def _reload_data(self) -> None:
        self._all_students = load_students()
        self._inventory_snapshot = load_inventory_snapshot()
        self._plan = load_plan(self._plan_path)
        self._storage_mtimes = self._snapshot_storage_mtimes()
        self._records_by_id = {record.student_id: record for record in self._all_students}
        self._filter_options = build_filter_options(self._all_students)
        self._unowned_icon_cache.clear()
        self._apply_filters()
        self._refresh_plan_lists()
        self._refresh_plan_totals()
        self._refresh_stats_tab()
        self._refresh_inventory_tab()

    def _apply_filters(self) -> None:
        query = self._search.text().strip().casefold()
        sort_mode = self._sort_mode.currentData()

        items = [
            record
            for record in self._all_students
            if matches_student_filters(
                record,
                self._selected_filters,
                query,
                hide_jp_only=self._hide_jp_only.isChecked(),
            )
            and (self._show_unowned.isChecked() or record.owned)
        ]

        if sort_mode == "star_desc":
            items.sort(key=lambda record: (-record.star, -(record.level or 0), record.title.lower()))
        elif sort_mode == "star_asc":
            items.sort(key=lambda record: (record.star, record.level or 0, record.title.lower()))
        elif sort_mode == "level_desc":
            items.sort(key=lambda record: (-(record.level or 0), -record.star, record.title.lower()))
        else:
            items.sort(key=lambda record: record.title.lower())

        self._filtered_students = items
        self._filter_summary.setText(
            summarize_filters(
                self._selected_filters,
                self._filter_options,
                hide_jp_only=self._hide_jp_only.isChecked(),
            )
        )
        active_count = active_filter_count(self._selected_filters) + int(self._hide_jp_only.isChecked())
        self._filter_button.setText(f"Filters ({active_count})" if active_count else "Filters")
        self._rebuild_list()
        self._refresh_stats_tab()
        self._sync_resource_controls_from_students()
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _open_filter_dialog(self) -> None:
        dialog = FilterDialog(self, self._filter_options, self._selected_filters, self._ui_scale)
        if dialog.exec() == QDialog.Accepted:
            self._selected_filters = dialog.selected_filters()
            self._apply_filters()

    def _rebuild_list(self) -> None:
        selected_id = self._current_student_id()
        self._student_grid.clear_cards()
        self._item_by_id.clear()
        self._clear_thumb_requests()
        cards: list[StudentCardWidget] = []

        for record in self._filtered_students:
            card = self._build_student_card(record)
            cards.append(card)
            self._item_by_id[record.student_id] = card

        if cards:
            self._student_grid.add_cards(cards)

        for record in self._filtered_students:
            self._enqueue_thumb(record.student_id)

        owned_count = sum(1 for record in self._all_students if record.owned)
        self._count_label.setText(f"{len(self._filtered_students)} shown / {len(self._all_students)} total ({owned_count} owned)")

        if self._filtered_students:
            restore_id = selected_id if selected_id in self._item_by_id else self._filtered_students[0].student_id
            self._student_grid.set_current_card(restore_id)
        else:
            self._student_grid.set_current_card(None)
            self._clear_detail()

    def _clear_thumb_requests(self) -> None:
        self._thumb_pump.stop()
        self._thumb_loading.clear()
        self._pending_thumb_requests.clear()
        self._pending_thumb_lookup.clear()

    def _enqueue_thumb(self, student_id: str) -> None:
        request = (student_id, self._thumb_width, self._thumb_height)
        if request in self._thumb_loading or request in self._pending_thumb_lookup:
            return
        self._pending_thumb_requests.append(request)
        self._pending_thumb_lookup.add(request)
        if not self._thumb_pump.isActive():
            self._thumb_pump.start()

    def _drain_thumb_queue(self) -> None:
        started = 0
        while self._pending_thumb_requests and started < self._thumb_batch_size:
            student_id, width, height = self._pending_thumb_requests.pop(0)
            request = (student_id, width, height)
            self._pending_thumb_lookup.discard(request)
            if not self._has_any_card_target(student_id):
                continue
            self._queue_thumb(student_id, width, height)
            started += 1
        if not self._pending_thumb_requests:
            self._thumb_pump.stop()

    def _queue_thumb(self, student_id: str, width: int, height: int) -> None:
        request = (student_id, width, height)
        if request in self._thumb_loading:
            return

        self._thumb_loading.add(request)
        task = ThumbTask(student_id, width, height)
        task.signals.loaded.connect(self._apply_thumb)
        self._pool.start(task)

    def _apply_thumb(self, student_id: str, path: str, width: int, height: int) -> None:
        self._thumb_loading.discard((student_id, width, height))
        if not path:
            return
        if width != self._thumb_width or height != self._thumb_height:
            return

        pixmap = QPixmap(path)
        if not pixmap.isNull():
            if student_id in self._item_by_id:
                self._student_grid.set_card_pixmap(student_id, pixmap)
            if student_id in self._plan_card_by_id:
                self._plan_grid.set_card_pixmap(student_id, pixmap)

    def _on_student_card_changed(self, current: str | None, _previous: str | None) -> None:
        if not current:
            self._clear_detail()
            return

        record = next((entry for entry in self._filtered_students if entry.student_id == current), None)
        if record is None:
            self._clear_detail()
            return

        self._populate_detail(record)

    def _on_student_grid_layout_changed(self, _width: int, _height: int) -> None:
        self._refresh_card_layout()

    def _populate_detail(self, record: StudentRecord) -> None:
        attack_color = _attack_color(record.attack_type)
        defense_color = _defense_accent_color(record.defense_type)
        self._name.setText(record.title)
        self._subtitle.clear()
        self._detail_badges.clear()
        self._subtitle.setVisible(False)
        self._detail_badges.setVisible(False)
        self._detail_plan_button.setText("Open In Plan" if record.student_id in self._plan_goal_map() else "Add To Plan")
        self._detail_attack_bar.setColors(_mix_hex(attack_color, SURFACE_ALT, 0.12), attack_color)
        self._detail_defense_bar.setColors(_mix_hex(defense_color, SURFACE_ALT, 0.12), defense_color)
        has_weapon_progress = record.owned and record.star >= 5 and (record.weapon_state or "") != "no_weapon_system"
        self._detail_progress_strip.setProgress(record.star if record.owned else 0, record.weapon_star or 0, has_weapon_progress)
        self._detail_attack_chip.setVisible(False)
        self._detail_defense_chip.setVisible(False)
        self._detail_level_value.setStyleSheet(f"color: {INK};")
        self._detail_weapon_value.setStyleSheet(f"color: {INK};")

        school_logo = _school_logo_path(record.school)
        if school_logo is not None:
            school_pixmap = QPixmap(str(school_logo))
            if not school_pixmap.isNull():
                self._detail_school_icon.setPixmap(_tinted_pixmap(school_pixmap, "#ffffff", self._detail_school_icon.size()))
            else:
                self._detail_school_icon.setPixmap(QPixmap())
        else:
            self._detail_school_icon.setPixmap(QPixmap())

        self._detail_level_value.setText(str(record.level or "-") if record.owned else "-")
        self._detail_position_value.setText(_position_label(record.position))
        self._detail_class_value.setText((record.combat_class or "-").title())
        has_weapon = record.owned and record.weapon_level is not None and (record.weapon_state or "") != "no_weapon_system"
        self._detail_weapon_card.setVisible(has_weapon)
        self._detail_weapon_value.setText(f"Lv.{record.weapon_level}" if has_weapon else "-")
        self._detail_weapon_sub.clear()

        self._detail_skill_labels["ex"].setText(str(record.ex_skill or "-") if record.owned else "-")
        self._detail_skill_labels["s1"].setText(str(record.skill1 or "-") if record.owned else "-")
        self._detail_skill_labels["s2"].setText(str(record.skill2 or "-") if record.owned else "-")
        self._detail_skill_labels["s3"].setText(str(record.skill3 or "-") if record.owned else "-")

        for index, slot in enumerate(("equip1", "equip2", "equip3"), start=1):
            tier = getattr(record, slot)
            tier_num = _parse_tier_number(tier)
            caption_text = student_meta.equipment_slots(record.student_id)[index - 1] or slot.upper()
            value_text = str(tier_num) if record.owned and tier_num is not None else "-"
            icon_path = _equipment_icon_path(record.student_id, index, tier) if record.owned else None
            icon_pixmap = QPixmap()
            if icon_path is not None:
                loaded = QPixmap(str(icon_path))
                if not loaded.isNull():
                    icon_pixmap = loaded
            self._detail_equip_cards[slot].setData(
                icon=icon_pixmap,
                value=value_text,
                caption=caption_text.upper(),
            )

        self._detail_stats_line.setText(
            f"HP {record.stat_hp or 0:,}   |   ATK {record.stat_atk or 0:,}   |   HEAL {record.stat_heal or 0:,}"
            if record.owned
            else "No progression data available"
        )

        hero_path = portrait_path(record.student_id)
        hero_size = self._hero.card_size()
        hero_source = None
        if hero_size.width() > 0 and hero_size.height() > 0:
            hero_source = ensure_thumbnail(record.student_id, hero_size.width(), hero_size.height())
        if hero_source is None:
            hero_source = hero_path

        if hero_source and hero_source.exists():
            pixmap = QPixmap(str(hero_source))
            if not pixmap.isNull():
                self._large_pixmap = pixmap
                self._hero.setPixmap(self._large_pixmap, owned=record.owned)
                return

        self._large_pixmap = None
        if record.owned:
            self._hero.clear()
        else:
            self._hero.setPixmap(self._unowned_icon(record.student_id).pixmap(self._hero.size()), owned=False)

    def _clear_detail(self) -> None:
        self._name.setText("Select a student")
        self._subtitle.clear()
        self._detail_badges.clear()
        self._subtitle.setVisible(False)
        self._detail_badges.setVisible(False)
        self._detail_attack_chip.setVisible(False)
        self._detail_defense_chip.setVisible(False)
        self._detail_school_icon.setPixmap(QPixmap())
        self._detail_plan_button.setText("Add To Plan")
        self._detail_progress_strip.setProgress(0, 0, False)
        self._detail_level_value.setText("-")
        self._detail_position_value.setText("-")
        self._detail_class_value.setText("-")
        self._detail_weapon_card.setVisible(False)
        self._detail_weapon_value.setText("-")
        self._detail_weapon_sub.clear()
        for label in self._detail_skill_labels.values():
            label.setText("-")
        for card in self._detail_equip_cards.values():
            card.clearData()
        self._detail_stats_line.setText("-")
        self._hero.clear()

    def _current_student_id(self) -> str | None:
        if not hasattr(self, "_student_grid"):
            return None
        return self._student_grid.current_card_id()

    def _unowned_icon(self, student_id: str) -> QIcon:
        cached = self._unowned_icon_cache.get(student_id)
        if cached is None:
            cached = make_unowned_icon(student_id, self._thumb_width, self._thumb_height)
            self._unowned_icon_cache[student_id] = cached
        return cached

    @staticmethod
    def _equip_text(tier: str | None, level: int | None) -> str:
        if tier and level is not None:
            return f"{tier} / Lv.{level}"
        if tier:
            return tier
        return "-"


def main() -> int:
    app = QApplication(sys.argv)
    ui_font_family = _load_ui_font_family()
    if ui_font_family:
        app.setFont(QFont(ui_font_family))
    window = StudentViewerWindow(get_qt_ui_scale(app, base_width=1680, base_height=1080))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
