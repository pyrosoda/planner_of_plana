"""
Standalone Qt-based student viewer process.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import sqlite3
import sys
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field, fields
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import core.student_meta as student_meta
from core.config import get_storage_paths
from core.db import init_db
from core.equipment_items import EQUIPMENT_EXP_ITEMS, EQUIPMENT_ITEM_ID_TO_NAME, EQUIPMENT_SERIES, WEAPON_PART_ITEMS
from core.inventory_profiles import inventory_item_display_name
from core.oparts import OPART_DEFINITIONS, OPART_ITEM_ID_TO_NAME, OPART_LEGACY_WB_ITEM_IDS, OPART_ORDERED_ITEM_IDS, OPART_WB_ITEMS
from core.planning import (
    MAX_TARGET_EQUIP_LEVEL,
    MAX_TARGET_EQUIP_TIER,
    MAX_TARGET_EQUIP4_TIER,
    MAX_TARGET_EX_SKILL,
    MAX_TARGET_LEVEL,
    MAX_TARGET_SKILL,
    MAX_TARGET_STAR,
    MAX_TARGET_STAT,
    MAX_TARGET_WEAPON_LEVEL,
    MAX_TARGET_WEAPON_STAR,
    StudentGoal,
    load_plan,
    save_plan,
)
from core.planning_calc import PlanCostSummary, calculate_goal_cost
from core.tactical_challenge import (
    TACTICAL_STRIKER_SLOTS,
    TACTICAL_SUPPORT_SLOTS,
    TacticalDeck,
    TacticalJokboEntry,
    TacticalMatch,
    clear_tactical_import_template,
    deck_label,
    deck_template,
    delete_tactical_match,
    ensure_tactical_import_template,
    get_tactical_match,
    latest_tactical_match_for_opponent,
    load_tactical_challenge,
    opponent_report_from_storage,
    parse_deck_template,
    query_tactical_matches,
    read_tactical_import_rows,
    tactical_import_readme_path,
    write_tactical_import_rows,
    save_tactical_metadata,
    save_tactical_challenge,
    search_jokbo_from_storage,
    tactical_match_count,
    tactical_match_summary,
    upsert_tactical_jokbo,
    upsert_tactical_jokbo_entries,
    upsert_tactical_match,
    upsert_tactical_matches,
)
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
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QScrollArea,
    QSizePolicy,
)

_PLAN_GOAL_CACHE_FIELDS = tuple(field.name for field in fields(StudentGoal))

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

PORTRAIT_DIR = BASE_DIR / "templates" / "students_portraits"
UI_FONT_PATH = BASE_DIR / "gui" / "font" / "경기천년제목_Medium.ttf"
POLI_BG_DIR = BASE_DIR / "templates" / "icons" / "temp"
STUDENT_ELEPH_DIR = BASE_DIR / "templates" / "students_elephs"
SCHOOL_LOGO_DIR = BASE_DIR / "templates" / "icons" / "school_logo"
EQUIPMENT_ICON_DIR = BASE_DIR / "templates" / "icons" / "equipment"
OPART_ICON_DIR = BASE_DIR / "templates" / "icons" / "ooparts"
SKILL_BOOK_ICON_DIR = BASE_DIR / "templates" / "icons" / "skill_book"
SKILL_DB_ICON_DIR = BASE_DIR / "templates" / "icons" / "skill_db"
INVENTORY_DETAIL_DIR = BASE_DIR / "templates" / "inventory_detail"
CARD_BUTTON_ASSET = POLI_BG_DIR / "square.png"
ITEM_ICON_DEFAULT_BACKGROUND = POLI_BG_DIR / "square.png"
ITEM_ICON_BACKGROUND_BLUE = POLI_BG_DIR / "square_blue.png"
ITEM_ICON_BACKGROUND_YELLOW = POLI_BG_DIR / "square_yellow.png"
ITEM_ICON_BACKGROUND_PURPLE = POLI_BG_DIR / "square_purple.png"
ITEM_ICON_BACKGROUND_BY_TIER_INDEX: dict[int, Path] = {
    1: ITEM_ICON_BACKGROUND_BLUE,
    2: ITEM_ICON_BACKGROUND_YELLOW,
    3: ITEM_ICON_BACKGROUND_PURPLE,
}
MAIN_UI_PALETTE_PATH = BASE_DIR / "gui" / "main_ui_color_palete.txt"
THUMB_STYLE_VERSION = "v5-parallelogram-card-fit"
DETAIL_SLANT = 0.22
SEARCH_DEBOUNCE_MS = 180

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
_WB_ITEM_IDS = tuple(item_id for item_id, _name in OPART_WB_ITEMS) + OPART_LEGACY_WB_ITEM_IDS
_LEGACY_WB_ID_TO_ITEM_ID = {name: item_id for item_id, name in OPART_WB_ITEMS}
_OPART_NAME_TO_ITEM_ID = {
    name: item_id
    for item_id, name in OPART_ITEM_ID_TO_NAME.items()
    if item_id.startswith("Item_Icon_")
}
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
_OPART_EN_TO_ICON_KEY = {
    definition.family_en.casefold(): definition.icon_key
    for definition in OPART_DEFINITIONS
}
_PLAN_RESOURCE_CATEGORY_ORDER = {
    "credits": 0,
    "level_exp": 10,
    "equipment_exp": 20,
    "weapon_exp": 30,
    "skill_bd": 40,
    "skill_notes": 50,
    "secret_notes": 60,
    "ex_ooparts": 70,
    "skill_ooparts": 80,
    "stat_materials": 85,
    "favorite_item_materials": 86,
    "equipment_slot_1": 90,
    "equipment_slot_2": 100,
    "equipment_slot_3": 110,
    "equipment_materials": 120,
    "star_materials": 130,
}
_EQUIPMENT_NAME_TO_ITEM_ID = {
    name: item_id
    for item_id, name in EQUIPMENT_ITEM_ID_TO_NAME.items()
}

from gui.student_filters import (
    FILTER_FIELD_LABELS,
    FILTER_FIELD_ORDER,
    active_filter_count,
    build_filter_options,
    format_filter_value,
    get_student_value,
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
from gui.student_stats import DonutWidget, SunburstNode, SunburstWidget, build_distribution


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


def _live_line_edit_text(widget: QLineEdit | None) -> str:
    if isinstance(widget, LiveSearchLineEdit):
        return widget.liveText()
    return widget.text() if widget is not None else ""


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


def _item_icon_tier_index(item_id: str | None) -> int | None:
    text = str(item_id or "")
    match = re.search(r"_(\d+)$", text)
    if match:
        return int(match.group(1))
    return None


def _uses_tiered_item_background(item_id: str | None) -> bool:
    text = str(item_id or "")
    if text in _OPART_ITEM_IDS:
        return True
    return (
        text.startswith("Item_Icon_ExpItem_")
        or text.startswith("report_")
        or text.startswith("Item_Icon_SkillBook_")
        or text.startswith("Item_Icon_Material_ExSkill_")
        or text.startswith("Equipment_Icon_Exp_")
        or text.startswith("Equipment_Icon_WeaponExpGrowth")
    )


def _uses_yellow_item_background(item_id: str | None) -> bool:
    text = str(item_id or "")
    return (
        text == "Item_Icon_Favor_Selection"
        or text.startswith("Item_Icon_Favor_")
        or text in _WORKBOOK_ID_TO_NAME
        or text in _WB_ITEM_IDS
        or text.startswith("Item_Icon_WorkBook_")
    )


def _item_icon_background_path(item_id: str | None = None) -> Path | None:
    if _uses_yellow_item_background(item_id) and ITEM_ICON_BACKGROUND_YELLOW.exists():
        return ITEM_ICON_BACKGROUND_YELLOW
    if _uses_tiered_item_background(item_id):
        tier_index = _item_icon_tier_index(item_id)
        if tier_index is not None:
            tier_path = ITEM_ICON_BACKGROUND_BY_TIER_INDEX.get(tier_index)
            if tier_path is not None and tier_path.exists():
                return tier_path
    return ITEM_ICON_DEFAULT_BACKGROUND if ITEM_ICON_DEFAULT_BACKGROUND.exists() else None


def _draw_centered_pixmap(painter: QPainter, pixmap: QPixmap, bounds: QRect) -> None:
    if pixmap.isNull() or not bounds.isValid():
        return
    scaled = pixmap.scaled(bounds.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    x = bounds.x() + (bounds.width() - scaled.width()) // 2
    y = bounds.y() + (bounds.height() - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)


def _item_icon_pixmap(
    *,
    size: QSize,
    item_id: str | None = None,
    icon_path: Path | None = None,
    icon: QPixmap | None = None,
) -> QPixmap:
    if not size.isValid() or size.width() <= 0 or size.height() <= 0:
        return QPixmap()

    source = QPixmap(icon) if icon is not None else QPixmap()
    if source.isNull() and icon_path is not None and icon_path.exists():
        source = QPixmap(str(icon_path))
    if source.isNull():
        return QPixmap()

    background_path = _item_icon_background_path(item_id)
    if background_path is None:
        return source.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    background = QPixmap(str(background_path))
    if background.isNull():
        return source.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    canvas = QPixmap(size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    _draw_centered_pixmap(painter, background, canvas.rect())
    _draw_centered_pixmap(painter, source, canvas.rect())
    painter.end()
    return canvas


def _item_icon(icon_path: Path | None, *, size: QSize, item_id: str | None = None) -> QIcon:
    pixmap = _item_icon_pixmap(size=size, item_id=item_id, icon_path=icon_path)
    return QIcon(pixmap) if not pixmap.isNull() else QIcon()


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
        next_minimum = max(0, min(self._count, minimum_value))
        next_enabled_count = max(0, min(self._count, enabled_count if enabled_count is not None else self._count))
        next_value = max(next_minimum, min(next_enabled_count, value))
        if (
            next_minimum == self._minimum_value
            and next_enabled_count == self._enabled_count
            and next_value == self._value
        ):
            return
        self._minimum_value = next_minimum
        self._enabled_count = next_enabled_count
        self._value = next_value
        self._refresh_cells()

    def value(self) -> int:
        return self._value

    def setEnabled(self, enabled: bool) -> None:
        if enabled == self.isEnabled():
            return
        super().setEnabled(enabled)
        self._refresh_cells()

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

class LiveSearchLineEdit(QLineEdit):
    liveTextChanged = Signal(str)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._preedit_text = ""
        self.textChanged.connect(self._emit_live_text)

    def liveText(self) -> str:
        if not self._preedit_text:
            return self.text()
        cursor = self.cursorPosition()
        base_text = self.text()
        return f"{base_text[:cursor]}{self._preedit_text}{base_text[cursor:]}"

    def inputMethodEvent(self, event) -> None:
        super().inputMethodEvent(event)
        self._preedit_text = event.preeditString() or ""
        self._emit_live_text()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if self._preedit_text:
            self._preedit_text = ""
            self._emit_live_text()

    def _emit_live_text(self, *_args) -> None:
        self.liveTextChanged.emit(self.liveText())


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
        layout.setSpacing(scale_px(6, self._ui_scale))

        self._input = QLineEdit("0")
        self._input.setObjectName("planValueInput")
        self._input.setAlignment(Qt.AlignCenter)
        self._input.setValidator(QIntValidator(0, self._max_value, self))
        self._input.setMinimumHeight(scale_px(34, self._ui_scale))
        self._input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._input.textEdited.connect(self._on_text_edited)
        self._input.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self._input, 1)

        self._minus_button = QPushButton("-")
        self._minus_button.setObjectName("planStepButton")
        self._minus_button.setMinimumHeight(scale_px(34, self._ui_scale))
        self._minus_button.setFixedWidth(scale_px(34, self._ui_scale))
        self._minus_button.clicked.connect(lambda: self._step_by(-1))
        layout.addWidget(self._minus_button)

        self._plus_button = QPushButton("+")
        self._plus_button.setObjectName("planStepButton")
        self._plus_button.setMinimumHeight(scale_px(34, self._ui_scale))
        self._plus_button.setFixedWidth(scale_px(34, self._ui_scale))
        self._plus_button.clicked.connect(lambda: self._step_by(1))
        layout.addWidget(self._plus_button)

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
        next_minimum = max(0, min(self._max_value, minimum_value))
        next_value = max(next_minimum, min(self._max_value, value))
        if next_minimum == self._minimum_value and next_value == self._value:
            return
        self._minimum_value = next_minimum
        self._value = next_value
        self._refresh()

    def value(self) -> int:
        return self._value

    def setMaximumValue(self, maximum_value: int) -> None:
        next_max_value = max(0, int(maximum_value))
        if next_max_value == self._max_value:
            return
        self._max_value = next_max_value
        self._input.setValidator(QIntValidator(0, self._max_value, self))
        self._minimum_value = min(self._minimum_value, self._max_value)
        self._value = min(self._value, self._max_value)
        self._refresh()

    def setEnabled(self, enabled: bool) -> None:
        if enabled == self.isEnabled():
            return
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

    def _step_by(self, delta: int) -> None:
        if not self.isEnabled():
            return
        self._commit_value(self._value + int(delta), emit_signal=True)

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
        self._minus_button.setEnabled(enabled and self._value > self._minimum_value)
        self._plus_button.setEnabled(enabled and self._value < self._max_value)
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
    if item_id:
        item_id = _LEGACY_WB_ID_TO_ITEM_ID.get(item_id, item_id)
    elif name:
        item_id = _OPART_NAME_TO_ITEM_ID.get(name)

    student_id = _student_id_from_eleph_item_id(item_id)
    if student_id:
        path = STUDENT_ELEPH_DIR / f"{item_id}.png"
        if path.exists():
            return path

    report_icon = _report_icon_for_entry(item_id, name)
    if report_icon:
        path = POLI_BG_DIR / f"{report_icon}.png"
        if path.exists():
            return path

    if item_id:
        if item_id == "Item_Icon_Favor_Selection":
            path = POLI_BG_DIR / f"{item_id}.png"
            if path.exists():
                return path
        if item_id in _WORKBOOK_ID_TO_NAME:
            path = POLI_BG_DIR / f"{item_id}.png"
            if path.exists():
                return path
        if item_id.startswith("Item_Icon_SkillBook_"):
            path = SKILL_BOOK_ICON_DIR / f"{item_id}.png"
            if path.exists():
                return path
            path = INVENTORY_DETAIL_DIR / "tech_notes" / f"{item_id}.png"
            if path.exists():
                return path
        if item_id.startswith("Item_Icon_Material_ExSkill_"):
            path = SKILL_DB_ICON_DIR / f"{item_id}.png"
            if path.exists():
                return path
            path = INVENTORY_DETAIL_DIR / "tactical_bd" / f"{item_id}.png"
            if path.exists():
                return path
        if item_id in _OPART_ITEM_IDS or item_id in _WB_ITEM_IDS:
            path = OPART_ICON_DIR / f"{item_id}.png"
            if path.exists():
                return path
        if item_id.startswith("Equipment_Icon_") and "_Tier" in item_id:
            path = EQUIPMENT_ICON_DIR / f"{item_id}.png"
            if path.exists():
                return path
            path = INVENTORY_DETAIL_DIR / "equipment" / f"{item_id}.png"
            if path.exists():
                return path
        if item_id.startswith("Equipment_Icon_Exp_") or item_id.startswith("Equipment_Icon_WeaponExpGrowth"):
            path = EQUIPMENT_ICON_DIR / f"{item_id}.png"
            if path.exists():
                return path

    if name:
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
        student_id = _student_id_from_eleph_item_id(item_id_text)
        if student_id:
            return f"{student_meta.display_name(student_id)}의 엘레프"
        report_icon = _REPORT_ID_TO_ICON.get(item_id_text)
        if report_icon:
            return _REPORT_ICON_TO_NAME.get(report_icon, item_id_text)
        workbook_name = _WORKBOOK_ID_TO_NAME.get(item_id_text)
        if workbook_name:
            return workbook_name
    display_name = inventory_item_display_name(str(item_id)) if item_id else None
    return str(display_name or payload.get("name") or item_key)


def _plan_resource_split_tier(key: str) -> tuple[str, int | None]:
    base, separator, tier_text = key.rpartition(" T")
    if not separator:
        return key.strip(), None
    try:
        return base.strip(), int(tier_text)
    except ValueError:
        return key.strip(), None


def _student_id_from_eleph_item_id(item_id: str | None) -> str | None:
    prefix = "Item_Icon_SecretStone_"
    if item_id and item_id.startswith(prefix):
        return item_id[len(prefix):]
    return None


def _tier_from_item_id_or_name(item_id: str | None, name: str | None) -> int:
    text = f"{item_id or ''} {name or ''}"
    for pattern in (r"_Tier(\d+)", r" T(\d+)", r"_(\d+)(?:\s|$)"):
        match = re.search(pattern, text)
        if match:
            try:
                number = int(match.group(1))
            except ValueError:
                continue
            if pattern.startswith(r"_Tier"):
                return number
            return number + 1 if item_id and item_id.endswith(f"_{number}") else number
    return 0


def _equipment_series_key_from_item(item_id: str | None, name: str | None) -> str | None:
    text = item_id or ""
    match = re.match(r"Equipment_Icon_([^_]+)_Tier\d+", text)
    if match:
        return match.group(1)
    item_name = name or ""
    for series in EQUIPMENT_SERIES:
        if item_name in series.tier_names:
            return series.icon_key
    return None


def _plan_resource_item_id(key: str, category: str) -> str | None:
    base, tier = _plan_resource_split_tier(key)
    if category == "credits":
        return "Currency_Icon_Gold"
    if category == "star_materials" and key.startswith("Item_Icon_SecretStone_"):
        return key
    if tier is None:
        if category == "equipment_materials" and base in _EQUIPMENT_NAME_TO_ITEM_ID:
            return _EQUIPMENT_NAME_TO_ITEM_ID[base]
        return key if key.startswith(("Item_Icon_", "Equipment_Icon_")) else None

    zero_tier = max(0, tier - 1)
    if category == "level_exp":
        return f"Item_Icon_ExpItem_{zero_tier}"
    if category == "equipment_exp":
        return f"Equipment_Icon_Exp_{zero_tier}"
    if category == "weapon_exp":
        return f"Equipment_Icon_WeaponExpGrowthA_{zero_tier}"
    if category == "skill_books":
        school, _, resource_kind = base.partition(" ")
        if school in _SCHOOL_SEQUENCE and resource_kind == "BD":
            return f"Item_Icon_Material_ExSkill_{school}_{zero_tier}"
        if school in _SCHOOL_SEQUENCE and resource_kind == "Note":
            if tier == 5:
                return "Item_Icon_SkillBook_Ultimate_Piece"
            return f"Item_Icon_SkillBook_{school}_{zero_tier}"
    if category == "equipment_materials" and base in EQUIPMENT_ITEM_ID_TO_NAME:
        return base
    if category == "equipment_materials" and base in _EQUIPMENT_NAME_TO_ITEM_ID:
        return _EQUIPMENT_NAME_TO_ITEM_ID[base]
    if category == "equipment_materials" and base in {series.icon_key for series in EQUIPMENT_SERIES}:
        return f"Equipment_Icon_{base}_Tier{tier}"
    if category in {"ex_ooparts", "skill_ooparts", "stat_materials"}:
        if base == "Item_Icon_WorkBook_PotentialMaxHP":
            return base
        icon_key = _OPART_EN_TO_ICON_KEY.get(base.casefold())
        if icon_key:
            return f"Item_Icon_Material_{icon_key}_{zero_tier}"
    if category == "favorite_item_materials":
        if base == "Item_Icon_Favor_Selection":
            return base
        icon_key = _OPART_EN_TO_ICON_KEY.get(base.casefold())
        if icon_key:
            return f"Item_Icon_Material_{icon_key}_{zero_tier}"
    return key if key.startswith(("Item_Icon_", "Equipment_Icon_")) else None


def _plan_resource_icon_path(item_id: str | None, name: str) -> Path | None:
    if item_id == "Currency_Icon_Gold":
        path = POLI_BG_DIR / "Currency_Icon_Gold.png"
        return path if path.exists() else None
    student_id = _student_id_from_eleph_item_id(item_id)
    if student_id:
        path = STUDENT_ELEPH_DIR / f"{item_id}.png"
        return path if path.exists() else None
    if item_id == "Item_Icon_Favor_Selection":
        path = POLI_BG_DIR / "Item_Icon_Favor_Selection.png"
        return path if path.exists() else None
    return _inventory_icon_path(item_id, name)


def _plan_resource_display_name(item_id: str | None, fallback: str) -> str:
    if item_id == "Currency_Icon_Gold":
        return "크레딧"
    student_id = _student_id_from_eleph_item_id(item_id)
    if student_id:
        return f"{student_meta.display_name(student_id)}의 엘레프"
    if item_id == "Item_Icon_Favor_Selection":
        return "Favorite Gift Selection"
    display_name = inventory_item_display_name(item_id) if item_id else None
    return str(display_name or fallback)


def _inventory_quantity_index(inventory: dict[str, dict]) -> dict[str, int]:
    index: dict[str, int] = {}
    for item_key, payload in inventory.items():
        quantity = _inventory_quantity_value(payload.get("quantity"))
        if quantity is None:
            continue
        candidates = {str(item_key)}
        item_id = payload.get("item_id")
        if item_id:
            candidates.add(str(item_id))
        name = payload.get("name")
        if name:
            candidates.add(str(name))
        for candidate in candidates:
            index[candidate] = max(index.get(candidate, 0), quantity)
    return index


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
        self.setWindowTitle("학생 필터")
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

        intro = QLabel("각 항목에서 하나 이상의 값을 선택하세요. 선택한 항목은 모두 만족하는 학생만 표시됩니다.")
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
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("적용")
        buttons.button(QDialogButtonBox.StandardButton.Reset).setText("초기화")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
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


class InventoryListItem(QFrame):
    def __init__(self, *, ui_scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_scale = ui_scale
        self.setObjectName("planBand")

        layout = QGridLayout(self)
        layout.setContentsMargins(
            scale_px(12, self._ui_scale),
            scale_px(8, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(8, self._ui_scale),
        )
        layout.setHorizontalSpacing(scale_px(10, self._ui_scale))
        layout.setVerticalSpacing(scale_px(1, self._ui_scale))

        self._icon = QLabel()
        self._icon.setFixedSize(scale_px(40, self._ui_scale), scale_px(40, self._ui_scale))
        self._icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon, 0, 0, 2, 1, Qt.AlignVCenter)

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
        layout.addLayout(text_wrap, 0, 1, 2, 1)

        self._owned = self._build_value_label()
        self._plan_need = self._build_value_label()
        self._plan_short = self._build_value_label()
        self._pool_remain = self._build_value_label()
        self._status = QLabel("-")
        self._status.setObjectName("inventoryStatus")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setMinimumWidth(scale_px(104, self._ui_scale))

        for column, widget in enumerate(
            (self._owned, self._plan_need, self._plan_short, self._pool_remain, self._status),
            start=2,
        ):
            layout.addWidget(widget, 0, column, 2, 1, Qt.AlignVCenter)

        layout.setColumnStretch(1, 1)
        for column in range(2, 6):
            layout.setColumnMinimumWidth(column, scale_px(74, self._ui_scale))

    def _build_value_label(self) -> QLabel:
        label = QLabel("-")
        label.setObjectName("inventoryValue")
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        label.setMinimumWidth(scale_px(70, self._ui_scale))
        return label

    def setData(
        self,
        *,
        icon_path: Path | None,
        item_id: str | None = None,
        name: str,
        quantity: str,
        meta: str = "",
        shortage: bool = False,
        plan_need: str = "-",
        plan_short: str = "-",
        pool_remain: str = "-",
        status: str = "",
    ) -> None:
        self._name.setText(name)
        self._owned.setText(quantity)
        self._plan_need.setText(plan_need)
        self._plan_short.setText(plan_short)
        self._pool_remain.setText(pool_remain)
        self._status.setText(status or ("Plan Shortage" if shortage else "Sufficient"))
        self._meta.setText(meta)
        warning_style = "color: #ff6b6b;" if shortage else ""
        self._name.setStyleSheet(warning_style)
        self._owned.setStyleSheet(warning_style)
        self._plan_short.setStyleSheet(warning_style)
        self._meta.setStyleSheet(warning_style if shortage else "")
        self._status.setProperty("status", self._status.text().replace(" ", "_").lower())
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

        if icon_path is not None and icon_path.exists():
            pixmap = _item_icon_pixmap(size=self._icon.size(), item_id=item_id, icon_path=icon_path)
            if not pixmap.isNull():
                self._icon.setPixmap(pixmap)
                return
        self._icon.setPixmap(QPixmap())


class InventoryPressureRow(QFrame):
    def __init__(self, *, ui_scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_scale = ui_scale
        self.setObjectName("planBand")
        self.setFixedHeight(scale_px(58, self._ui_scale))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            scale_px(9, self._ui_scale),
            scale_px(7, self._ui_scale),
            scale_px(9, self._ui_scale),
            scale_px(7, self._ui_scale),
        )
        layout.setSpacing(scale_px(8, self._ui_scale))

        self._icon = QLabel()
        self._icon.setFixedSize(scale_px(34, self._ui_scale), scale_px(34, self._ui_scale))
        self._icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon, 0, Qt.AlignVCenter)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(scale_px(1, self._ui_scale))
        self._name = QLabel("-")
        self._name.setObjectName("sectionTitle")
        self._name.setWordWrap(False)
        text_wrap.addWidget(self._name)
        self._meta = QLabel("-")
        self._meta.setObjectName("detailMiniSub")
        self._meta.setWordWrap(False)
        text_wrap.addWidget(self._meta)
        layout.addLayout(text_wrap, 1)

        self._amount = QLabel("-")
        self._amount.setObjectName("inventoryPressureAmount")
        self._amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self._amount, 0, Qt.AlignVCenter)

    def setData(
        self,
        *,
        icon_path: Path | None,
        item_id: str,
        name: str,
        amount: int,
        meta: str,
        pool: bool,
    ) -> None:
        self._name.setText(name)
        self._meta.setText(meta)
        self._amount.setText(f"{amount:,}")
        self._amount.setStyleSheet("color: #ff8a00;" if pool else "color: #ff4d6d;")
        if icon_path is not None and icon_path.exists():
            pixmap = _item_icon_pixmap(size=self._icon.size(), item_id=item_id, icon_path=icon_path)
            if not pixmap.isNull():
                self._icon.setPixmap(pixmap)
                return
        self._icon.setPixmap(QPixmap())


@dataclass(slots=True)
class PlanResourceRequirement:
    key: str
    name: str
    required: int
    owned: int
    icon_path: Path | None
    category: str
    icon: QPixmap | None = None


@dataclass(slots=True)
class InventoryOpartStudentImpact:
    student_id: str
    title: str
    ex_required: int = 0
    skill_required: int = 0

    @property
    def total_required(self) -> int:
        return self.ex_required + self.skill_required


@dataclass(slots=True)
class InventoryOpartPlanUsage:
    item_id: str
    name: str
    required: int = 0
    owned: int = 0
    ex_required: int = 0
    skill_required: int = 0
    impacts: list[InventoryOpartStudentImpact] = field(default_factory=list)
    pool_required: int = 0
    pool_ex_required: int = 0
    pool_skill_required: int = 0
    pool_impacts: list[InventoryOpartStudentImpact] = field(default_factory=list)

    @property
    def shortage(self) -> int:
        return max(0, self.required - self.owned)

    @property
    def pool_shortage(self) -> int:
        return max(0, self.pool_required - self.owned)


class InventoryOpartFamilyRow(QFrame):
    selected = Signal(str)

    def __init__(
        self,
        *,
        family_name: str,
        tier_items: list[tuple[int, str, str, int, str, Path | None]],
        selected_item_id: str | None,
        ui_scale: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ui_scale = ui_scale
        self._buttons: dict[str, QPushButton] = {}
        self.setObjectName("planBand")

        layout = QGridLayout(self)
        layout.setContentsMargins(
            scale_px(8, self._ui_scale),
            scale_px(8, self._ui_scale),
            scale_px(8, self._ui_scale),
            scale_px(8, self._ui_scale),
        )
        layout.setHorizontalSpacing(scale_px(8, self._ui_scale))
        layout.setVerticalSpacing(0)

        icon_size = QSize(scale_px(34, self._ui_scale), scale_px(34, self._ui_scale))
        for column, (tier, item_id, name, owned, status, icon_path) in enumerate(tier_items):
            button = QPushButton(f"T{tier}  {owned:,}\n{status}")
            button.setObjectName("planQuickButton")
            button.setToolTip(f"{family_name} T{tier}\n{name}\n{owned:,} - {status}")
            button.setMinimumHeight(scale_px(74, self._ui_scale))
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if icon_path is not None and icon_path.exists():
                icon = _item_icon(icon_path, size=icon_size, item_id=item_id)
                if not icon.isNull():
                    button.setIcon(icon)
                    button.setIconSize(icon_size)
            button.clicked.connect(lambda _checked=False, value=item_id: self.selected.emit(value))
            self._buttons[item_id] = button
            layout.addWidget(button, 0, column)
            layout.setColumnStretch(column, 1)

        self.setSelectedItem(selected_item_id)

    def setSelectedItem(self, item_id: str | None) -> None:
        for button_item_id, button in self._buttons.items():
            button.setProperty("selectedOpart", button_item_id == item_id)
            if button_item_id == item_id:
                button.setStyleSheet("border: 2px solid #f266b3;")
            else:
                button.setStyleSheet("")


class PlanResourceChip(QFrame):
    def __init__(self, *, ui_scale: float, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui_scale = ui_scale
        self.setObjectName("planBand")
        self.setFixedHeight(scale_px(50, self._ui_scale))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            scale_px(9, self._ui_scale),
            scale_px(6, self._ui_scale),
            scale_px(9, self._ui_scale),
            scale_px(6, self._ui_scale),
        )
        layout.setSpacing(scale_px(8, self._ui_scale))

        self._icon = QLabel()
        self._icon.setFixedSize(scale_px(34, self._ui_scale), scale_px(34, self._ui_scale))
        self._icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon, 0, Qt.AlignVCenter)

        text_wrap = QVBoxLayout()
        text_wrap.setContentsMargins(0, 0, 0, 0)
        text_wrap.setSpacing(scale_px(1, self._ui_scale))
        self._name = QLabel("-")
        self._name.setObjectName("detailMiniSub")
        self._name.setWordWrap(False)
        text_wrap.addWidget(self._name)
        self._quantity = QLabel("-")
        self._quantity.setObjectName("detailMiniValue")
        self._quantity.setWordWrap(False)
        text_wrap.addWidget(self._quantity)
        layout.addLayout(text_wrap, 1)

    @staticmethod
    def _compact_amount(value: int) -> str:
        if value >= 1_000_000:
            text = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".")
            return f"{text}M"
        return f"{value:,}"

    def setData(self, requirement: PlanResourceRequirement) -> None:
        self._name.setText(requirement.name)
        self._name.setToolTip(requirement.name)
        self._quantity.setText(f"{self._compact_amount(requirement.required)} / {self._compact_amount(requirement.owned)}")
        self._quantity.setToolTip(f"{requirement.required:,} / {requirement.owned:,}")
        shortage = requirement.required > requirement.owned
        self._name.setStyleSheet(f"color: #ff6b6b;" if shortage else "")
        self._quantity.setStyleSheet(f"color: #ff6b6b;" if shortage else "")

        if requirement.icon is not None and not requirement.icon.isNull():
            pixmap = _item_icon_pixmap(size=self._icon.size(), item_id=requirement.key, icon=requirement.icon)
            self._icon.setPixmap(pixmap)
            return

        if requirement.icon_path is not None and requirement.icon_path.exists():
            pixmap = _item_icon_pixmap(size=self._icon.size(), item_id=requirement.key, icon_path=requirement.icon_path)
            if not pixmap.isNull():
                self._icon.setPixmap(pixmap)
                return
        self._icon.setPixmap(QPixmap())


class TacticalDeckSlot(QWidget):
    def __init__(
        self,
        *,
        card_asset: ParallelogramCardAsset,
        ui_scale: float,
        preferred_width: int,
        preferred_height: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._card_asset = card_asset
        self._ui_scale = ui_scale
        self._preferred_size = QSize(preferred_width, preferred_height)
        self._pixmap = QPixmap()
        self._text = ""
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(scale_px(24, self._ui_scale))
        self.setFixedHeight(preferred_height)

    def setData(self, *, name: str, pixmap: QPixmap) -> None:
        self._text = name
        self._pixmap = pixmap
        self.setToolTip(name)
        self.update()

    def sizeHint(self) -> QSize:
        return self._preferred_size

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        available_width = max(1, self.width())
        available_height = max(1, self.height())
        target_ratio = max(0.01, float(self._card_asset.aspect_ratio))
        if available_width / available_height > target_ratio:
            card_height = available_height
            card_width = max(1, int(round(card_height * target_ratio)))
        else:
            card_width = available_width
            card_height = max(1, int(round(card_width / target_ratio)))
        card_size = QSize(card_width, card_height)
        card_x = (available_width - card_width) // 2
        card_y = (available_height - card_height) // 2
        card_image = QImage(card_size, QImage.Format_ARGB32_Premultiplied)
        card_image.fill(Qt.transparent)
        card_painter = QPainter(card_image)
        card_painter.setRenderHint(QPainter.Antialiasing, True)
        card_painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        card_painter.drawImage(0, 0, self._card_asset.background(card_size, hovered=False, selected=False))
        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(card_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            card_painter.drawPixmap((card_size.width() - scaled.width()) // 2, (card_size.height() - scaled.height()) // 2, scaled)
        card_painter.drawImage(0, 0, self._card_asset.outline(card_size))
        card_painter.end()

        painter.drawImage(card_x, card_y, self._card_asset.apply_alpha_mask(card_image))
        if self._text and self._pixmap.isNull():
            painter.setPen(QColor(MUTED))
            painter.drawText(self.rect(), Qt.AlignCenter, "*" if self._text.strip() == "*" else "?")
        painter.end()


class TacticalDeckEditor(QWidget):
    def __init__(self, title: str, *, card_asset: ParallelogramCardAsset, ui_scale: float, icon_provider, deck_parser=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card_asset = card_asset
        self._ui_scale = ui_scale
        self._icon_provider = icon_provider
        self._deck_parser = deck_parser or parse_deck_template
        self._slot_width = scale_px(74, self._ui_scale)
        self._slot_height = max(scale_px(58, self._ui_scale), int(round(self._slot_width / self._card_asset.aspect_ratio)))
        self._icons: list[TacticalDeckSlot] = []
        self._deck = TacticalDeck()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(7, self._ui_scale))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_label = QLabel(title)
        title_label.setObjectName("detailSectionTitle")
        header.addWidget(title_label)
        header.addStretch(1)
        layout.addLayout(header)

        icon_row = QHBoxLayout()
        icon_row.setContentsMargins(0, 0, 0, 0)
        icon_row.setSpacing(scale_px(5, self._ui_scale))
        for index in range(TACTICAL_STRIKER_SLOTS + TACTICAL_SUPPORT_SLOTS):
            if index == TACTICAL_STRIKER_SLOTS:
                divider = QLabel("|")
                divider.setObjectName("sectionTitle")
                divider.setAlignment(Qt.AlignCenter)
                icon_row.addWidget(divider)
            label = TacticalDeckSlot(
                card_asset=self._card_asset,
                ui_scale=self._ui_scale,
                preferred_width=self._slot_width,
                preferred_height=self._slot_height,
            )
            self._icons.append(label)
            icon_row.addWidget(label, 1)
        layout.addLayout(icon_row)

        self._template_input = QLineEdit()
        self._template_input.setPlaceholderText("student1,student2,student3,student4|support1,support2")
        self._template_input.returnPressed.connect(self.importTemplate)
        layout.addWidget(self._template_input)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.addStretch(1)
        copy_button = QPushButton("Copy")
        import_button = QPushButton("Import")
        button_width = max(
            scale_px(68, self._ui_scale),
            QFontMetrics(import_button.font()).horizontalAdvance("Import") + scale_px(28, self._ui_scale),
        )
        copy_button.setFixedWidth(button_width)
        import_button.setFixedWidth(button_width)
        copy_button.clicked.connect(self.copyTemplate)
        import_button.clicked.connect(self.importTemplate)
        action_row.addWidget(copy_button)
        action_row.addWidget(import_button)
        layout.addLayout(action_row)
        self._syncIcons()

    def deck(self) -> TacticalDeck:
        text = self._template_input.text().strip()
        if text and text != deck_template(self._deck):
            return self._deck_parser(text)
        return self._deck

    def templateText(self) -> str:
        return self._template_input.text().strip()

    def setDeck(self, deck: TacticalDeck) -> None:
        self._deck = deck
        self._template_input.setText(deck_template(self._deck))
        self._syncIcons()

    def clearDeck(self) -> None:
        self.setDeck(TacticalDeck())
        self._template_input.clear()

    def copyTemplate(self) -> None:
        self._deck = self.deck()
        self._syncIcons()
        text = deck_template(self._deck)
        self._template_input.setText(text)
        QApplication.clipboard().setText(text)

    def importTemplate(self) -> None:
        text = self._template_input.text().strip() or QApplication.clipboard().text().strip()
        if text:
            self.setDeck(self._deck_parser(text))

    def _syncIcons(self) -> None:
        deck = self._deck
        names = deck.strikers[:TACTICAL_STRIKER_SLOTS]
        names += [""] * max(0, TACTICAL_STRIKER_SLOTS - len(names))
        names += deck.supports[:TACTICAL_SUPPORT_SLOTS]
        for index, label in enumerate(self._icons):
            name = names[index] if index < len(names) else ""
            pixmap = self._icon_provider(name, max(self._slot_width, self._slot_height)) if name else QPixmap()
            label.setData(name=name, pixmap=pixmap if pixmap is not None else QPixmap())


class TacticalDeckPreview(QWidget):
    def __init__(
        self,
        *,
        card_asset: ParallelogramCardAsset,
        ui_scale: float,
        icon_provider,
        compact: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._card_asset = card_asset
        self._ui_scale = ui_scale
        self._icon_provider = icon_provider
        self._compact = compact
        self._slot_width = scale_px(38 if compact else 58, self._ui_scale)
        self._slot_height = max(scale_px(30 if compact else 44, self._ui_scale), int(round(self._slot_width / self._card_asset.aspect_ratio)))
        self._icons: list[TacticalDeckSlot] = []
        self.setSizePolicy(QSizePolicy.Fixed if compact else QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(4, self._ui_scale))
        divider_count = 0
        for index in range(TACTICAL_STRIKER_SLOTS + TACTICAL_SUPPORT_SLOTS):
            if index == TACTICAL_STRIKER_SLOTS:
                divider = QLabel("|")
                divider.setObjectName("detailSub")
                layout.addWidget(divider)
                divider_count += 1
            label = TacticalDeckSlot(
                card_asset=self._card_asset,
                ui_scale=self._ui_scale,
                preferred_width=self._slot_width,
                preferred_height=self._slot_height,
            )
            self._icons.append(label)
            layout.addWidget(label, 1)
        if compact:
            item_count = TACTICAL_STRIKER_SLOTS + TACTICAL_SUPPORT_SLOTS + divider_count
            total_width = self._slot_width * (TACTICAL_STRIKER_SLOTS + TACTICAL_SUPPORT_SLOTS) + layout.spacing() * max(0, item_count - 1) + scale_px(8, self._ui_scale)
            self.setFixedWidth(total_width)

    def setDeck(self, deck: TacticalDeck) -> None:
        names = deck.strikers[:TACTICAL_STRIKER_SLOTS]
        names += [""] * max(0, TACTICAL_STRIKER_SLOTS - len(names))
        names += deck.supports[:TACTICAL_SUPPORT_SLOTS]
        for index, label in enumerate(self._icons):
            name = names[index] if index < len(names) else ""
            pixmap = self._icon_provider(name, max(self._slot_width, self._slot_height)) if name else QPixmap()
            label.setData(name=name, pixmap=pixmap if pixmap is not None else QPixmap())




class StudentViewerWindow(QMainWindow):
    def __init__(self, ui_scale: float):
        super().__init__()
        self._ui_scale = ui_scale
        self._startup_window_applied = False
        self._applying_work_area = False
        self._detail_panel: QFrame | None = None
        self._detail_scroll: QScrollArea | None = None
        self._hero_wrap: QFrame | None = None
        self._busy_overlay: QFrame | None = None
        self._busy_label: QLabel | None = None
        self._busy_cursor_active = False
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
        self._tactical_student_lookup_index: dict[str, list[str]] | None = None
        self._filtered_students = list(self._all_students)
        self._item_by_id: dict[str, StudentCardWidget] = {}
        self._plan_card_by_id: dict[str, StudentCardWidget] = {}
        self._resource_scope_card_by_id: dict[str, StudentCardWidget] = {}
        self._resource_search_card_by_id: dict[str, StudentCardWidget] = {}
        self._thumb_loading: set[tuple[str, int, int]] = set()
        self._pending_thumb_requests: list[tuple[str, int, int]] = []
        self._pending_thumb_lookup: set[tuple[str, int, int]] = set()
        self._thumb_batch_size = 16
        self._thumb_max_in_flight = 48
        self._thumb_pixmap_cache: OrderedDict[tuple[str, int, int], QPixmap] = OrderedDict()
        self._thumb_pixmap_cache_limit = 640
        self._placeholder_icon = make_placeholder_icon(self._thumb_width, self._thumb_height)
        self._unowned_icon_cache: dict[str, QIcon] = {}
        self._large_pixmap: QPixmap | None = None
        self._selected_filters: dict[str, set[str]] = {key: set() for key in FILTER_FIELD_ORDER}
        self._filter_options = build_filter_options(self._all_students)
        self._plan_path = get_storage_paths().current_dir / "growth_plan.json"
        self._plan = load_plan(self._plan_path)
        self._tactical_path = get_storage_paths().current_dir / "tactical_challenge.db"
        self._tactical_data = load_tactical_challenge(self._tactical_path, load_matches=False)
        self._plan_editor_guard = False
        self._selected_plan_student_id: str | None = None
        self._plan_segment_inputs: dict[str, PlanSegmentSelector] = {}
        self._plan_level_inputs: dict[str, PlanStepper] = {}
        self._plan_level_rows: dict[str, QWidget] = {}
        self._plan_level_row_labels: dict[str, QLabel] = {}
        self._plan_equipment_labels: dict[str, QLabel] = {}
        self._plan_stat_rows: dict[str, QWidget] = {}
        self._plan_ability_release_expanded = False
        self._resource_selected_ids: set[str] = set()
        self._resource_search_pending_ids: set[str] = set()
        self._resource_current_student_id: str | None = None
        self._resource_include_unplanned_level = True
        self._resource_include_unplanned_equipment = True
        self._resource_include_unplanned_skills = True
        self._resource_syncing_controls = False
        self._main_tabs: QTabWidget | None = None
        self._resource_tab: QWidget | None = None
        self._resources_dirty = False
        self._inventory_snapshot = load_inventory_snapshot()
        self._inventory_quantity_index_cache = _inventory_quantity_index(self._inventory_snapshot or {})
        self._plan_goal_map_cache: dict[str, StudentGoal] | None = None
        self._plan_cost_cache: dict[tuple[str, tuple[object, ...]], PlanCostSummary] = {}
        self._plan_resource_icon_path_cache: dict[tuple[str | None, str], Path | None] = {}
        self._plan_resource_pixmap_cache: dict[Path, QPixmap] = {}
        storage_paths = get_storage_paths()
        self._storage_watch_paths = (
            storage_paths.current_students_json,
            storage_paths.current_inventory_json,
            self._plan_path,
            self._tactical_path,
        )
        self._storage_mtimes = self._snapshot_storage_mtimes()
        self._stats_cards_layout: QGridLayout | None = None
        self._stats_summary_host: QWidget | None = None
        self._stats_sunburst: SunburstWidget | None = None
        self._stats_sunburst_mode: QComboBox | None = None
        self._stats_sunburst_detail: QLabel | None = None
        self._tactical_selected_match_id: str | None = None
        self._tactical_match_page_size = 100
        self._tactical_match_loaded_count = self._tactical_match_page_size
        self._tactical_match_query = ""
        self._card_layout_guard = False
        self._thumb_pump = QTimer(self)
        self._thumb_pump.setSingleShot(False)
        self._thumb_pump.setInterval(0)
        self._thumb_pump.timeout.connect(self._drain_thumb_queue)
        self._filter_refresh_timer = QTimer(self)
        self._filter_refresh_timer.setSingleShot(True)
        self._filter_refresh_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._filter_refresh_timer.timeout.connect(self._apply_filters)
        self._plan_search_timer = QTimer(self)
        self._plan_search_timer.setSingleShot(True)
        self._plan_search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._plan_search_timer.timeout.connect(self._refresh_plan_lists)
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
        self._refresh_tactical_tab()
        self._resources_dirty = False

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
        self._main_tabs = tabs
        tabs.setObjectName("mainTabs")
        outer_layout.addWidget(tabs, 1)

        students_tab = QWidget()
        tabs.addTab(students_tab, "Students")
        self._build_students_tab(students_tab)

        plan_tab = QWidget()
        tabs.addTab(plan_tab, "Plans")
        self._build_plan_tab(plan_tab)

        resource_tab = QWidget()
        self._resource_tab = resource_tab
        tabs.addTab(resource_tab, "Requirements")
        self._build_resource_tab(resource_tab)

        inventory_tab = QWidget()
        tabs.addTab(inventory_tab, "Inventory")
        self._build_inventory_tab(inventory_tab)

        tactical_tab = QWidget()
        tabs.addTab(tactical_tab, "Tactical Challenge")
        self._build_tactical_tab(tactical_tab)

        stats_tab = QWidget()
        tabs.addTab(stats_tab, "Statistics")
        self._build_stats_tab(stats_tab)

        tabs.currentChanged.connect(self._on_main_tab_changed)

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
            QLineEdit, QComboBox, QPushButton, QPlainTextEdit {{
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
            QComboBox, QLineEdit, QPlainTextEdit {{
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
            QLabel#inventoryValue {{
                font-size: {scale_px(13, self._ui_scale)}px;
                font-weight: 800;
                color: {INK};
            }}
            QLabel#inventoryPressureAmount {{
                font-size: {scale_px(13, self._ui_scale)}px;
                font-weight: 900;
            }}
            QLabel#inventoryStatus {{
                border-radius: {scale_px(8, self._ui_scale)}px;
                padding: {scale_px(4, self._ui_scale)}px {scale_px(7, self._ui_scale)}px;
                font-size: {scale_px(11, self._ui_scale)}px;
                font-weight: 800;
                background: {_mix_hex(SURFACE_ALT, '#ffffff', 0.08)};
                color: {MUTED};
            }}
            QLabel#inventoryStatus[status="sufficient"] {{
                background: #e8f8f1;
                color: #00a86b;
            }}
            QLabel#inventoryStatus[status="plan_shortage"] {{
                background: #ffe3e5;
                color: #ff304f;
            }}
            QLabel#inventoryStatus[status="long-term_pressure"] {{
                background: #fff2c2;
                color: #d97900;
            }}
            QLabel#inventoryStatus[status="unused"] {{
                background: #eef0f5;
                color: #8b93a7;
            }}
            QLabel#inventoryStatus[status="high-tier_bottleneck"] {{
                background: #ffe3e5;
                color: #d7193f;
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
            QPushButton#planStepButton {{
                background: {_mix_hex(SURFACE_ALT, ACCENT, 0.18)};
                color: {INK};
                border: 1px solid {_mix_hex(BORDER, ACCENT, 0.22)};
                border-radius: {scale_px(11, self._ui_scale)}px;
                padding: {scale_px(4, self._ui_scale)}px;
                font-size: {scale_px(15, self._ui_scale)}px;
                font-weight: 900;
                min-width: {scale_px(28, self._ui_scale)}px;
            }}
            QPushButton#planStepButton:hover {{
                background: {_mix_hex(SURFACE_ALT, ACCENT, 0.28)};
            }}
            QPushButton#planStepButton:disabled {{
                color: {MUTED};
                background: {_mix_hex(SURFACE_ALT, BG, 0.14)};
                border-color: {_mix_hex(BORDER, SURFACE_ALT, 0.36)};
            }}
            QPushButton#planDisclosureButton {{
                background: {_mix_hex(SURFACE_ALT, BG, 0.06)};
                color: {PALETTE_SOFT};
                border: 1px solid {_mix_hex(BORDER, SURFACE_ALT, 0.28)};
                border-radius: {scale_px(11, self._ui_scale)}px;
                padding: {scale_px(7, self._ui_scale)}px {scale_px(10, self._ui_scale)}px;
                font-size: {scale_px(11, self._ui_scale)}px;
                font-weight: 800;
                text-align: left;
            }}
            QPushButton#planDisclosureButton:hover {{
                background: {_mix_hex(SURFACE_ALT, ACCENT, 0.12)};
                color: {INK};
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
        self._build_busy_overlay(root)

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

        self._search = LiveSearchLineEdit()
        self._search.setPlaceholderText("Search by student name, id, or tag")
        self._search.liveTextChanged.connect(self._schedule_filter_refresh)
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
        self._filter_button = ParallelogramButton("필터", style=self._card_button_style)
        self._filter_button.clicked.connect(self._open_filter_dialog)
        toolbar_buttons.addButton(self._filter_button)

        refresh_button = ParallelogramButton("Refresh", style=self._card_button_style)
        refresh_button.clicked.connect(self._reload_data)
        toolbar_buttons.addButton(refresh_button)
        toolbar_layout.addWidget(toolbar_buttons, 0, Qt.AlignVCenter)
        layout.addWidget(toolbar)

        self._filter_summary = QLabel("적용된 필터 없음")
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
        self._sync_busy_overlay_geometry()

    def _build_busy_overlay(self, parent: QWidget) -> None:
        overlay = QFrame(parent)
        overlay.setObjectName("busyOverlay")
        overlay.setAttribute(Qt.WA_StyledBackground, True)
        overlay.hide()
        overlay.setGeometry(parent.rect())
        overlay.setStyleSheet(
            f"""
            QFrame#busyOverlay {{
                background: rgba(0, 0, 0, 132);
            }}
            QFrame#busyCard {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: {scale_px(10, self._ui_scale)}px;
            }}
            QProgressBar {{
                background: {SURFACE_ALT};
                border: 1px solid {BORDER};
                border-radius: {scale_px(5, self._ui_scale)}px;
                min-height: {scale_px(10, self._ui_scale)}px;
                max-height: {scale_px(10, self._ui_scale)}px;
            }}
            QProgressBar::chunk {{
                background: {ACCENT_STRONG};
                border-radius: {scale_px(5, self._ui_scale)}px;
            }}
            """
        )

        layout = QVBoxLayout(overlay)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)

        card = QFrame(overlay)
        card.setObjectName("busyCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            scale_px(24, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(24, self._ui_scale),
            scale_px(18, self._ui_scale),
        )
        card_layout.setSpacing(scale_px(12, self._ui_scale))

        label = QLabel("저장 중...", card)
        label.setObjectName("sectionTitle")
        label.setAlignment(Qt.AlignCenter)
        progress = QProgressBar(card)
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedWidth(scale_px(220, self._ui_scale))

        card_layout.addWidget(label)
        card_layout.addWidget(progress, 0, Qt.AlignHCenter)
        layout.addWidget(card)

        self._busy_overlay = overlay
        self._busy_label = label

    def _sync_busy_overlay_geometry(self) -> None:
        if self._busy_overlay is None:
            return
        parent = self._busy_overlay.parentWidget()
        if parent is None:
            return
        self._busy_overlay.setGeometry(parent.rect())

    def _show_busy_overlay(self, text: str = "저장 중...") -> None:
        if self._busy_overlay is None:
            return
        if self._busy_label is not None:
            self._busy_label.setText(text)
        self._sync_busy_overlay_geometry()
        self._busy_overlay.raise_()
        self._busy_overlay.show()
        if not self._busy_cursor_active:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._busy_cursor_active = True
        QApplication.processEvents()

    def _hide_busy_overlay(self) -> None:
        if self._busy_overlay is not None:
            self._busy_overlay.hide()
        if self._busy_cursor_active:
            QApplication.restoreOverrideCursor()
            self._busy_cursor_active = False
        QApplication.processEvents()

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
        if hasattr(self, "_resource_scope_grid"):
            sizes.append(self._resource_scope_grid.current_card_size())
        if hasattr(self, "_resource_search_grid"):
            sizes.append(self._resource_search_grid.current_card_size())
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
            for student_id in sorted(
                set(self._item_by_id)
                | set(self._plan_card_by_id)
                | set(getattr(self, "_resource_scope_card_by_id", {}))
                | set(getattr(self, "_resource_search_card_by_id", {}))
            ):
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
        title = QLabel("Requirement Scope")
        title.setObjectName("title")
        title_wrap.addWidget(title)
        subtitle = QLabel("Build a student scope, check who is already planned, and inspect the combined growth requirements.")
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

        self._resource_search = LiveSearchLineEdit()
        self._resource_search.setPlaceholderText("Search by student name, id, or tag; filters narrow groups")
        self._resource_search.textChanged.connect(self._on_resource_search_changed)
        self._resource_search.liveTextChanged.connect(self._schedule_filter_refresh)
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
        self._resource_filter_button = ParallelogramButton("필터", style=self._card_button_style)
        self._resource_filter_button.clicked.connect(self._open_filter_dialog)
        resource_toolbar_buttons.addButton(self._resource_filter_button)
        resource_refresh_button = ParallelogramButton("Refresh", style=self._card_button_style)
        resource_refresh_button.clicked.connect(self._reload_data)
        resource_toolbar_buttons.addButton(resource_refresh_button)
        toolbar_layout.addWidget(resource_toolbar_buttons, 0, Qt.AlignVCenter)

        self._resource_filter_summary = QLabel("적용된 필터 없음")
        self._resource_filter_summary.setWordWrap(True)
        self._resource_filter_summary.setObjectName("filterSummary")

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

        self._resource_left_tabs = QTabBar()
        self._resource_left_tabs.setObjectName("planEditorTabs")
        self._resource_left_tabs.setExpanding(False)
        self._resource_left_tabs.setUsesScrollButtons(False)
        self._resource_left_tabs.addTab("Scope")
        self._resource_left_tabs.addTab("Search")
        left_layout.addWidget(self._resource_left_tabs, 0, Qt.AlignLeft)

        self._resource_left_stack = QStackedWidget()
        left_layout.addWidget(self._resource_left_stack, 1)
        self._resource_left_tabs.currentChanged.connect(self._resource_left_stack.setCurrentIndex)

        scope_tab = QWidget()
        scope_layout = QVBoxLayout(scope_tab)
        scope_layout.setContentsMargins(0, 0, 0, 0)
        scope_layout.setSpacing(scale_px(10, self._ui_scale))

        scope_header = QHBoxLayout()
        scope_header.setContentsMargins(0, 0, 0, 0)
        scope_header.setSpacing(scale_px(8, self._ui_scale))
        left_title = QLabel("Scope Students")
        left_title.setObjectName("sectionTitle")
        scope_header.addWidget(left_title)
        self._resource_scope_count = QLabel("")
        self._resource_scope_count.setObjectName("count")
        scope_header.addWidget(self._resource_scope_count, 1, Qt.AlignRight)
        scope_layout.addLayout(scope_header)

        self._resource_list_summary = QLabel("")
        self._resource_list_summary.setObjectName("detailSub")
        self._resource_list_summary.setWordWrap(True)
        scope_layout.addWidget(self._resource_list_summary)

        unplanned_options = QFrame()
        unplanned_options.setObjectName("planSectionPanel")
        unplanned_layout = QVBoxLayout(unplanned_options)
        unplanned_layout.setContentsMargins(
            scale_px(12, self._ui_scale),
            scale_px(10, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(10, self._ui_scale),
        )
        unplanned_layout.setSpacing(scale_px(8, self._ui_scale))
        unplanned_title = QLabel("Not Planned Calculation")
        unplanned_title.setObjectName("detailSectionTitle")
        unplanned_layout.addWidget(unplanned_title)
        unplanned_row = QHBoxLayout()
        unplanned_row.setSpacing(scale_px(10, self._ui_scale))
        self._resource_unplanned_level = QCheckBox("Level")
        self._resource_unplanned_level.setChecked(True)
        self._resource_unplanned_level.stateChanged.connect(self._on_resource_unplanned_options_changed)
        unplanned_row.addWidget(self._resource_unplanned_level)
        self._resource_unplanned_equipment = QCheckBox("Equipment")
        self._resource_unplanned_equipment.setChecked(True)
        self._resource_unplanned_equipment.stateChanged.connect(self._on_resource_unplanned_options_changed)
        unplanned_row.addWidget(self._resource_unplanned_equipment)
        self._resource_unplanned_skills = QCheckBox("Skills")
        self._resource_unplanned_skills.setChecked(True)
        self._resource_unplanned_skills.stateChanged.connect(self._on_resource_unplanned_options_changed)
        unplanned_row.addWidget(self._resource_unplanned_skills)
        unplanned_row.addStretch(1)
        unplanned_layout.addLayout(unplanned_row)
        scope_layout.addWidget(unplanned_options, 0)

        self._resource_scope_grid = ParallelogramCardGrid(self._student_card_asset, self._ui_scale)
        self._resource_scope_grid.setObjectName("studentGrid")
        self._resource_scope_grid.current_changed.connect(self._on_resource_scope_card_changed)
        self._resource_scope_grid.layout_changed.connect(lambda *_: self._refresh_card_layout())
        scope_layout.addWidget(self._resource_scope_grid, 1)

        scope_buttons = QHBoxLayout()
        scope_buttons.setSpacing(scale_px(8, self._ui_scale))
        for label, handler in (
            ("Remove selected", self._resource_remove_scope_selected),
            ("Clear", self._resource_clear_checked),
        ):
            button = QPushButton(label)
            button.setObjectName("planQuickButton")
            button.clicked.connect(handler)
            if label == "Remove selected":
                self._resource_remove_scope_button = button
            scope_buttons.addWidget(button)
        scope_buttons.addStretch(1)
        scope_layout.addLayout(scope_buttons)
        self._resource_left_stack.addWidget(scope_tab)

        search_tab = QWidget()
        search_layout = QVBoxLayout(search_tab)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(scale_px(10, self._ui_scale))
        search_layout.addWidget(toolbar, 0)
        search_layout.addWidget(self._resource_filter_summary, 0)

        result_title = QLabel("Search Results")
        result_title.setObjectName("sectionTitle")
        search_layout.addWidget(result_title)
        self._resource_search_summary = QLabel("")
        self._resource_search_summary.setObjectName("detailSub")
        self._resource_search_summary.setWordWrap(True)
        search_layout.addWidget(self._resource_search_summary)

        self._resource_search_grid = ParallelogramCardGrid(self._student_card_asset, self._ui_scale, multi_select=True)
        self._resource_search_grid.setObjectName("studentGrid")
        self._resource_search_grid.selection_changed.connect(self._on_resource_search_selection_changed)
        self._resource_search_grid.layout_changed.connect(lambda *_: self._refresh_card_layout())
        search_layout.addWidget(self._resource_search_grid, 1)

        search_buttons = QHBoxLayout()
        search_buttons.setSpacing(scale_px(8, self._ui_scale))
        self._resource_add_selected_button = QPushButton("Add selected")
        self._resource_add_selected_button.setObjectName("planQuickButton")
        self._resource_add_selected_button.clicked.connect(self._resource_add_pending_to_scope)
        search_buttons.addWidget(self._resource_add_selected_button)
        for label, handler in (
            ("Add results", self._resource_check_visible),
            ("Add planned", self._resource_check_visible_planned),
            ("Clear selection", self._resource_clear_search_selection),
        ):
            button = QPushButton(label)
            button.setObjectName("planQuickButton")
            button.clicked.connect(handler)
            search_buttons.addWidget(button)
        search_buttons.addStretch(1)
        search_layout.addLayout(search_buttons)
        self._resource_left_stack.addWidget(search_tab)

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
        aggregate_title = QLabel("Combined Requirements")
        aggregate_title.setObjectName("sectionTitle")
        aggregate_options_layout.addWidget(aggregate_title)

        self._resource_aggregate_summary = QLabel("Add students to scope to combine growth costs.")
        self._resource_aggregate_summary.setObjectName("detailSub")
        self._resource_aggregate_summary.setWordWrap(True)
        aggregate_options_layout.addWidget(self._resource_aggregate_summary)
        right_layout.addWidget(aggregate_options, 0)

        self._resource_requirement_empty = QLabel("Add students to scope to preview required resources.")
        self._resource_requirement_empty.setObjectName("filterSummary")
        self._resource_requirement_empty.setWordWrap(True)
        self._resource_requirement_empty.setMinimumHeight(scale_px(22, self._ui_scale))
        right_layout.addWidget(self._resource_requirement_empty)

        self._resource_requirement_scroll = QScrollArea()
        self._resource_requirement_scroll.setFrameShape(QFrame.NoFrame)
        self._resource_requirement_scroll.setWidgetResizable(True)
        self._resource_requirement_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._resource_requirement_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._resource_requirement_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._resource_requirement_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")

        self._resource_requirement_grid_host = QWidget()
        self._resource_requirement_grid_host.setObjectName("planTransparent")
        self._resource_requirement_grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._resource_requirement_grid = QGridLayout(self._resource_requirement_grid_host)
        self._resource_requirement_grid.setContentsMargins(
            scale_px(6, self._ui_scale),
            scale_px(6, self._ui_scale),
            scale_px(6, self._ui_scale),
            scale_px(6, self._ui_scale),
        )
        self._resource_requirement_grid.setHorizontalSpacing(scale_px(8, self._ui_scale))
        self._resource_requirement_grid.setVerticalSpacing(scale_px(8, self._ui_scale))
        self._resource_requirement_grid.setAlignment(Qt.AlignTop)
        for column in range(3):
            self._resource_requirement_grid.setColumnStretch(column, 1)
        self._resource_requirement_scroll.setWidget(self._resource_requirement_grid_host)
        right_layout.addWidget(self._resource_requirement_scroll, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([scale_px(720, self._ui_scale), scale_px(720, self._ui_scale)])
        layout.addWidget(splitter, 1)

        self._sync_resource_controls_from_students()
        self._refresh_resource_students_list()
        self._refresh_resource_view()
        self._resources_dirty = False

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

        title = QLabel("Material Pressure Analysis")
        title.setObjectName("title")
        header_layout.addWidget(title)

        subtitle = QLabel("Inventory analysis - shortage tracking - growth planning optimization")
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
        self._inventory_oopart_plan_usage: dict[str, InventoryOpartPlanUsage] = {}
        self._inventory_oopart_selected_id: str | None = None
        self._inventory_requirement_index: dict[str, PlanResourceRequirement] = {}
        self._inventory_pool_requirement_index: dict[str, PlanResourceRequirement] = {}

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

            column_header = QLabel("MATERIAL                                      OWNED      PLAN NEED    PLAN SHORT   POOL REMAIN   STATUS")
            column_header.setObjectName("detailMiniSub")
            tab_layout.addWidget(column_header)

            item_list = QListWidget()
            item_list.currentItemChanged.connect(self._on_inventory_item_changed)
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

            column_header = QLabel("MATERIAL                                      OWNED      PLAN NEED    PLAN SHORT   POOL REMAIN   STATUS")
            column_header.setObjectName("detailMiniSub")
            tab_layout.addWidget(column_header)

            item_list = QListWidget()
            item_list.currentItemChanged.connect(self._on_inventory_item_changed)
            if key == "ooparts":
                item_list.currentItemChanged.connect(self._on_inventory_oopart_changed)
            tab_layout.addWidget(item_list, 1)
            self._inventory_item_tabs.addTab(tab, label)
            self._inventory_item_lists[key] = item_list
            self._inventory_item_summaries[key] = summary

        item_layout.addWidget(self._inventory_item_tabs, 1)
        self._inventory_root_tabs.addTab(item_root, "Items")

        inventory_splitter = QSplitter(Qt.Horizontal)
        inventory_splitter.setChildrenCollapsible(False)

        overview_panel = QFrame()
        overview_panel.setObjectName("planSectionPanel")
        overview_panel.setMinimumWidth(scale_px(300, self._ui_scale))
        overview_layout = QVBoxLayout(overview_panel)
        overview_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        overview_layout.setSpacing(scale_px(10, self._ui_scale))

        insight_title = QLabel("Material Pressure")
        insight_title.setObjectName("sectionTitle")
        overview_layout.addWidget(insight_title)

        self._inventory_insight_summary = QLabel("Scan inventory and select Ooparts to inspect plan pressure.")
        self._inventory_insight_summary.setObjectName("detailSub")
        self._inventory_insight_summary.setWordWrap(True)
        overview_layout.addWidget(self._inventory_insight_summary)

        plan_priority_panel = QFrame()
        plan_priority_panel.setObjectName("planBand")
        plan_priority_panel.setMinimumHeight(scale_px(150, self._ui_scale))
        plan_priority_layout = QVBoxLayout(plan_priority_panel)
        plan_priority_layout.setContentsMargins(
            scale_px(10, self._ui_scale),
            scale_px(8, self._ui_scale),
            scale_px(10, self._ui_scale),
            scale_px(8, self._ui_scale),
        )
        plan_priority_layout.setSpacing(scale_px(6, self._ui_scale))
        plan_priority_title = QLabel("Plan Shortage TOP")
        plan_priority_title.setObjectName("detailSectionTitle")
        plan_priority_layout.addWidget(plan_priority_title)
        self._inventory_plan_priority_list = QListWidget()
        self._configure_inventory_priority_cards(self._inventory_plan_priority_list)
        self._inventory_plan_priority_list.currentItemChanged.connect(self._on_inventory_priority_changed)
        plan_priority_layout.addWidget(self._inventory_plan_priority_list, 1)
        overview_layout.addWidget(plan_priority_panel, 1)

        pool_pressure_panel = QFrame()
        pool_pressure_panel.setObjectName("planBand")
        pool_pressure_panel.setMinimumHeight(scale_px(150, self._ui_scale))
        pool_pressure_layout = QVBoxLayout(pool_pressure_panel)
        pool_pressure_layout.setContentsMargins(
            scale_px(10, self._ui_scale),
            scale_px(8, self._ui_scale),
            scale_px(10, self._ui_scale),
            scale_px(8, self._ui_scale),
        )
        pool_pressure_layout.setSpacing(scale_px(6, self._ui_scale))
        pool_pressure_title = QLabel("Full Pool Pressure TOP")
        pool_pressure_title.setObjectName("detailSectionTitle")
        pool_pressure_layout.addWidget(pool_pressure_title)
        self._inventory_pool_pressure_list = QListWidget()
        self._configure_inventory_priority_cards(self._inventory_pool_pressure_list)
        self._inventory_pool_pressure_list.currentItemChanged.connect(self._on_inventory_priority_changed)
        pool_pressure_layout.addWidget(self._inventory_pool_pressure_list, 1)
        overview_layout.addWidget(pool_pressure_panel, 1)

        bottleneck_panel = QFrame()
        bottleneck_panel.setObjectName("planBand")
        bottleneck_layout = QVBoxLayout(bottleneck_panel)
        bottleneck_layout.setContentsMargins(
            scale_px(10, self._ui_scale),
            scale_px(8, self._ui_scale),
            scale_px(10, self._ui_scale),
            scale_px(8, self._ui_scale),
        )
        bottleneck_layout.setSpacing(scale_px(6, self._ui_scale))
        bottleneck_title = QLabel("Common Bottleneck Summary")
        bottleneck_title.setObjectName("detailSectionTitle")
        bottleneck_layout.addWidget(bottleneck_title)
        self._inventory_bottleneck_summary = QLabel("-")
        self._inventory_bottleneck_summary.setObjectName("detailSub")
        self._inventory_bottleneck_summary.setWordWrap(True)
        bottleneck_layout.addWidget(self._inventory_bottleneck_summary)
        overview_layout.addWidget(bottleneck_panel, 0)

        school_panel = QFrame()
        school_panel.setObjectName("planBand")
        school_layout = QVBoxLayout(school_panel)
        school_layout.setContentsMargins(
            scale_px(10, self._ui_scale),
            scale_px(8, self._ui_scale),
            scale_px(10, self._ui_scale),
            scale_px(8, self._ui_scale),
        )
        school_layout.setSpacing(scale_px(6, self._ui_scale))
        school_title = QLabel("School / Category Shortage")
        school_title.setObjectName("detailSectionTitle")
        school_layout.addWidget(school_title)
        self._inventory_school_summary = QLabel("-")
        self._inventory_school_summary.setObjectName("detailSub")
        self._inventory_school_summary.setWordWrap(True)
        school_layout.addWidget(self._inventory_school_summary)
        overview_layout.addWidget(school_panel, 0)
        overview_layout.addStretch(3)

        detail_panel = QFrame()
        detail_panel.setObjectName("planSectionPanel")
        detail_panel.setMinimumWidth(scale_px(320, self._ui_scale))
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        detail_layout.setSpacing(scale_px(10, self._ui_scale))

        self._inventory_oopart_detail_title = QLabel("Select an oopart")
        self._inventory_oopart_detail_title.setObjectName("sectionTitle")
        detail_layout.addWidget(self._inventory_oopart_detail_title)

        self._inventory_oopart_detail_table = QGridLayout()
        self._inventory_oopart_detail_table.setContentsMargins(0, 0, 0, 0)
        self._inventory_oopart_detail_table.setHorizontalSpacing(scale_px(8, self._ui_scale))
        self._inventory_oopart_detail_table.setVerticalSpacing(scale_px(6, self._ui_scale))
        self._inventory_oopart_metric_labels: dict[str, QLabel] = {}
        for row, (key, label) in enumerate(
            (
                ("owned", "Owned"),
                ("required", "Plan Need"),
                ("shortage", "Plan Short"),
                ("coverage", "Plan Coverage"),
                ("pool_required", "Full Pool Need"),
                ("pool_shortage", "Pool Left"),
                ("pool_coverage", "Full Coverage"),
                ("ex_required", "EX Demand"),
                ("skill_required", "Normal Skill"),
                ("affected", "Affected Students"),
            )
        ):
            name_label = QLabel(label)
            name_label.setObjectName("detailMiniSub")
            value_label = QLabel("-")
            value_label.setObjectName("detailMiniValue")
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._inventory_oopart_metric_labels[key] = value_label
            self._inventory_oopart_detail_table.addWidget(name_label, row, 0)
            self._inventory_oopart_detail_table.addWidget(value_label, row, 1)
        detail_layout.addLayout(self._inventory_oopart_detail_table)

        self._inventory_oopart_detail_summary = QLabel("Pick an item in Items > Ooparts to see planned use and affected students.")
        self._inventory_oopart_detail_summary.setObjectName("detailSub")
        self._inventory_oopart_detail_summary.setWordWrap(True)
        detail_layout.addWidget(self._inventory_oopart_detail_summary)

        self._inventory_oopart_impact_list = QListWidget()
        self._inventory_oopart_impact_list.setMinimumHeight(scale_px(160, self._ui_scale))
        detail_layout.addWidget(self._inventory_oopart_impact_list, 1)

        inventory_splitter.addWidget(overview_panel)
        inventory_splitter.addWidget(self._inventory_root_tabs)
        inventory_splitter.addWidget(detail_panel)
        inventory_splitter.setStretchFactor(0, 1)
        inventory_splitter.setStretchFactor(1, 2)
        inventory_splitter.setStretchFactor(2, 1)
        inventory_splitter.setSizes([
            scale_px(360, self._ui_scale),
            scale_px(720, self._ui_scale),
            scale_px(420, self._ui_scale),
        ])
        layout.addWidget(inventory_splitter, 1)
        self._refresh_inventory_tab()

    def _sync_resource_controls_from_students(self) -> None:
        if not hasattr(self, "_resource_search"):
            return
        self._resource_syncing_controls = True
        try:
            if self._resource_search.text() != self._search.text():
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
        total_materials = sum(summary.star_materials.values()) + sum(summary.equipment_materials.values()) + sum(summary.skill_books.values()) + sum(summary.ex_ooparts.values()) + sum(summary.skill_ooparts.values()) + sum(summary.favorite_item_materials.values()) + sum(summary.stat_materials.values())
        return f"크레딧 {summary.credits:,} · EXP {summary.level_exp:,} · Items {total_materials:,}"

    def _resource_focus_label(
        self,
        record: StudentRecord,
        summary: PlanCostSummary | None,
        goal_map: dict[str, StudentGoal] | None = None,
    ) -> str:
        goal_map = self._plan_goal_map() if goal_map is None else goal_map
        status = []
        status.append("Planned" if record.student_id in goal_map else "Not planned")
        status.append("Owned" if record.owned else "Unowned")
        if summary is None:
            return " · ".join(status)
        buckets = [
            ("skill", sum(summary.skill_books.values()) + sum(summary.ex_ooparts.values()) + sum(summary.skill_ooparts.values())),
            ("equipment", sum(summary.equipment_materials.values())),
            ("star", sum(summary.star_materials.values())),
            ("favorite", sum(summary.favorite_item_materials.values())),
            ("stat", sum(summary.stat_materials.values())),
        ]
        label, amount = max(buckets, key=lambda item: item[1])
        if amount > 0:
            status.append(f"{label.title()}-heavy")
        return " · ".join(status)

    def _resource_goal_for_student(
        self,
        student_id: str,
        goal_map: dict[str, StudentGoal] | None = None,
    ) -> StudentGoal | None:
        goal_map = self._plan_goal_map() if goal_map is None else goal_map
        return goal_map.get(student_id)

    def _resource_summary_for_student(
        self,
        student_id: str,
        goal_map: dict[str, StudentGoal] | None = None,
    ) -> PlanCostSummary | None:
        record = self._records_by_id.get(student_id)
        goal = self._resource_goal_for_student(student_id, goal_map)
        if record is None or goal is None:
            return None
        return self._cached_goal_cost(student_id, record=record, goal=goal)

    def _resource_unplanned_goal_for_student(self, student_id: str) -> StudentGoal | None:
        if not (
            self._resource_include_unplanned_level
            or self._resource_include_unplanned_equipment
            or self._resource_include_unplanned_skills
        ):
            return None
        record = self._records_by_id.get(student_id)
        if record is None:
            return None
        goal = StudentGoal(student_id=student_id)
        if self._resource_include_unplanned_level:
            goal.target_level = MAX_TARGET_LEVEL
        if self._resource_include_unplanned_equipment:
            goal.target_equip1_tier = MAX_TARGET_EQUIP_TIER
            goal.target_equip2_tier = MAX_TARGET_EQUIP_TIER
            goal.target_equip3_tier = MAX_TARGET_EQUIP_TIER
            goal.target_equip1_level = MAX_TARGET_EQUIP_LEVEL
            goal.target_equip2_level = MAX_TARGET_EQUIP_LEVEL
            goal.target_equip3_level = MAX_TARGET_EQUIP_LEVEL
            if self._record_supports_unique_item(record):
                goal.target_equip4_tier = MAX_TARGET_EQUIP4_TIER
        if self._resource_include_unplanned_skills:
            goal.target_ex_skill = MAX_TARGET_EX_SKILL
            goal.target_skill1 = MAX_TARGET_SKILL
            goal.target_skill2 = MAX_TARGET_SKILL
            goal.target_skill3 = MAX_TARGET_SKILL
        return goal

    def _resource_current_student(self) -> str | None:
        if hasattr(self, "_resource_scope_grid"):
            return self._resource_scope_grid.current_card_id()
        return None

    def _refresh_resource_students_list(self) -> None:
        if not hasattr(self, "_resource_scope_grid"):
            return
        current_id = self._resource_current_student_id or self._resource_current_student()
        old_scope_cards = dict(self._resource_scope_card_by_id)
        old_search_cards = dict(self._resource_search_card_by_id)

        goal_map = self._plan_goal_map()
        visible_ids = {record.student_id for record in self._filtered_students}
        self._resource_search_pending_ids &= visible_ids
        selected_records = [
            self._records_by_id[student_id]
            for student_id in self._resource_selected_ids
            if student_id in self._records_by_id
        ]
        selected_records.sort(key=lambda record: record.title.lower())
        planned_count = sum(1 for record in selected_records if record.student_id in goal_map)

        scope_cards: list[StudentCardWidget] = []
        next_scope_by_id: dict[str, StudentCardWidget] = {}
        for record in selected_records:
            card = old_scope_cards.get(record.student_id)
            if card is None:
                card = self._build_student_card(record)
            else:
                self._apply_student_card_record(card, record)
            scope_cards.append(card)
            next_scope_by_id[record.student_id] = card

        self._resource_scope_card_by_id = next_scope_by_id
        self._resource_scope_grid.set_cards(scope_cards)

        if scope_cards:
            restore_id = current_id if current_id in self._resource_scope_card_by_id else selected_records[0].student_id
            self._resource_scope_grid.set_current_card(restore_id)
            self._resource_current_student_id = restore_id
        else:
            self._resource_scope_grid.set_current_card(None)
            self._resource_current_student_id = None

        visible_planned = sum(1 for record in self._filtered_students if record.student_id in goal_map)
        search_cards: list[StudentCardWidget] = []
        next_search_by_id: dict[str, StudentCardWidget] = {}
        for record in self._filtered_students:
            card = old_search_cards.get(record.student_id)
            if card is None:
                card = self._build_student_card(record)
            else:
                self._apply_student_card_record(card, record)
            if record.student_id in self._resource_selected_ids:
                card.setToolTip(f"{record.student_id}\nAlready in scope")
            else:
                card.setToolTip(record.student_id)
            search_cards.append(card)
            next_search_by_id[record.student_id] = card

        self._resource_search_card_by_id = next_search_by_id
        self._resource_search_grid.set_cards(search_cards)
        self._resource_search_grid.set_selected_card_ids(set(self._resource_search_pending_ids))

        if hasattr(self, "_resource_scope_count"):
            self._resource_scope_count.setText(f"{len(selected_records)} students")
        self._resource_list_summary.setText(
            f"{len(selected_records)} in scope - {planned_count} planned - {len(selected_records) - planned_count} not planned"
        )
        if hasattr(self, "_resource_search_summary"):
            visible_selected = len(self._resource_selected_ids & {record.student_id for record in self._filtered_students})
            pending_count = len(self._resource_search_pending_ids)
            self._resource_search_summary.setText(
                f"{len(self._filtered_students)} matches - {visible_planned} planned - {visible_selected} already in scope - {pending_count} selected"
            )
        self._update_resource_scope_actions()
        self._update_resource_search_actions()
        for record in selected_records:
            self._enqueue_thumb(record.student_id)
        for record in self._filtered_students:
            self._enqueue_thumb(record.student_id)

    def _on_resource_scope_card_changed(self, current: str | None, _previous: str | None) -> None:
        self._resource_current_student_id = current
        self._update_resource_scope_actions()

    def _on_resource_search_selection_changed(self, selected_ids: object) -> None:
        if isinstance(selected_ids, set):
            self._resource_search_pending_ids = {str(student_id) for student_id in selected_ids}
        else:
            self._resource_search_pending_ids = set()
        self._refresh_resource_search_summary()
        self._update_resource_search_actions()

    def _refresh_resource_search_summary(self) -> None:
        if not hasattr(self, "_resource_search_summary"):
            return
        goal_map = self._plan_goal_map()
        visible_planned = sum(1 for record in self._filtered_students if record.student_id in goal_map)
        visible_selected = len(self._resource_selected_ids & {record.student_id for record in self._filtered_students})
        self._resource_search_summary.setText(
            f"{len(self._filtered_students)} matches - {visible_planned} planned - {visible_selected} already in scope - {len(self._resource_search_pending_ids)} selected"
        )

    def _update_resource_scope_actions(self) -> None:
        if hasattr(self, "_resource_remove_scope_button"):
            self._resource_remove_scope_button.setEnabled(bool(self._resource_current_student()))

    def _update_resource_search_actions(self) -> None:
        if hasattr(self, "_resource_add_selected_button"):
            self._resource_add_selected_button.setEnabled(bool(self._resource_search_pending_ids))

    def _on_resource_unplanned_options_changed(self, _state: int) -> None:
        self._resource_include_unplanned_level = self._resource_unplanned_level.isChecked()
        self._resource_include_unplanned_equipment = self._resource_unplanned_equipment.isChecked()
        self._resource_include_unplanned_skills = self._resource_unplanned_skills.isChecked()
        self._refresh_resource_view()

    def _resource_add_pending_to_scope(self) -> None:
        if not self._resource_search_pending_ids:
            return
        self._resource_selected_ids.update(self._resource_search_pending_ids)
        self._resource_search_pending_ids.clear()
        if hasattr(self, "_resource_left_tabs"):
            self._resource_left_tabs.setCurrentIndex(0)
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _resource_remove_scope_selected(self) -> None:
        student_id = self._resource_current_student()
        if not student_id:
            return
        self._resource_selected_ids.discard(student_id)
        self._resource_search_pending_ids.discard(student_id)
        self._resource_current_student_id = None
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _resource_clear_search_selection(self) -> None:
        self._resource_search_pending_ids.clear()
        if hasattr(self, "_resource_search_grid"):
            self._resource_search_grid.set_selected_card_ids(set())
        self._refresh_resource_search_summary()
        self._update_resource_search_actions()

    def _resource_check_visible(self) -> None:
        self._resource_selected_ids.update(record.student_id for record in self._filtered_students)
        self._resource_search_pending_ids.clear()
        if hasattr(self, "_resource_left_tabs"):
            self._resource_left_tabs.setCurrentIndex(0)
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _resource_check_visible_planned(self) -> None:
        goal_map = self._plan_goal_map()
        self._resource_selected_ids.update(record.student_id for record in self._filtered_students if record.student_id in goal_map)
        self._resource_search_pending_ids.clear()
        if hasattr(self, "_resource_left_tabs"):
            self._resource_left_tabs.setCurrentIndex(0)
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _resource_clear_checked(self) -> None:
        self._resource_selected_ids.clear()
        self._resource_search_pending_ids.clear()
        self._resource_current_student_id = None
        self._refresh_resource_students_list()
        self._refresh_resource_view()

    def _resource_total_for_ids(
        self,
        student_ids: list[str] | tuple[str, ...] | set[str],
        goal_map: dict[str, StudentGoal] | None = None,
    ) -> tuple[PlanCostSummary, int, int]:
        goal_map = self._plan_goal_map() if goal_map is None else goal_map
        ordered_ids = [student_id for student_id in student_ids if student_id in self._records_by_id]
        total = PlanCostSummary()
        contributing_count = 0
        for student_id in ordered_ids:
            record = self._records_by_id[student_id]
            if student_id in goal_map:
                summary = self._cached_goal_cost(student_id, record=record, goal=goal_map[student_id])
            else:
                unplanned_goal = self._resource_unplanned_goal_for_student(student_id)
                summary = calculate_goal_cost(record, unplanned_goal) if unplanned_goal is not None else None
            if summary is None:
                continue
            total.merge(summary)
            contributing_count += 1
        return total, len(ordered_ids), contributing_count

    def _set_output_from_summary(self, target: QListWidget, summary: PlanCostSummary | None) -> None:
        target.clear()
        if summary is None:
            target.addItem("No planner target is available for this selection yet.")
            return

        sections: list[tuple[str, list[tuple[str, int]]]] = []
        if summary.credits:
            sections.append(("크레딧", [("크레딧", summary.credits)]))
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
        for heading, mapping in (("Star materials", summary.star_materials), ("Equipment materials", summary.equipment_materials), ("Skill books", summary.skill_books), ("EX ooparts", summary.ex_ooparts), ("Skill ooparts", summary.skill_ooparts), ("Favorite item materials", summary.favorite_item_materials), ("Stat materials", summary.stat_materials)):
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

    def _clear_requirement_grid(self, grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate_requirement_grid(
        self,
        grid: QGridLayout,
        entries: list[PlanResourceRequirement],
        *,
        columns: int = 3,
    ) -> None:
        for index, requirement in enumerate(entries):
            chip = PlanResourceChip(ui_scale=self._ui_scale)
            chip.setData(requirement)
            grid.addWidget(chip, index // columns, index % columns)

    def _refresh_resource_view(self) -> None:
        if not hasattr(self, "_resource_requirement_grid"):
            return
        self._refresh_resource_aggregate_view()

    def _is_resource_tab_current(self) -> bool:
        return (
            self._main_tabs is not None
            and self._resource_tab is not None
            and self._main_tabs.currentWidget() is self._resource_tab
        )

    def _refresh_resources_if_visible(self) -> None:
        if self._is_resource_tab_current():
            self._refresh_resource_students_list()
            self._refresh_resource_view()
            self._resources_dirty = False
        else:
            self._resources_dirty = True

    def _on_main_tab_changed(self, _index: int) -> None:
        if self._resources_dirty and self._is_resource_tab_current():
            self._refresh_resource_students_list()
            self._refresh_resource_view()
            self._resources_dirty = False

    def _refresh_resource_aggregate_view(self) -> None:
        goal_map = self._plan_goal_map()
        student_ids = sorted(
            self._resource_selected_ids,
            key=lambda student_id: self._records_by_id[student_id].title.lower() if student_id in self._records_by_id else student_id,
        )
        summary, selected_count, contributing_count = self._resource_total_for_ids(student_ids, goal_map)
        planned_count = sum(1 for student_id in student_ids if student_id in goal_map)
        unplanned_count = max(0, selected_count - planned_count)
        unplanned_included = max(0, contributing_count - planned_count)
        self._resource_aggregate_summary.setText(
            f"Combining {selected_count} scoped students. {planned_count} planned and {unplanned_included}/{unplanned_count} not planned students contribute to the current total."
        )
        self._resource_requirement_grid_host.setUpdatesEnabled(False)
        try:
            self._clear_requirement_grid(self._resource_requirement_grid)
            self._resource_requirement_scroll.setVisible(True)
            if contributing_count == 0:
                self._resource_requirement_empty.setText("No scoped students currently contribute required resources.")
                self._resource_requirement_empty.setVisible(True)
                return
            entries = self._plan_requirement_entries(summary)
            self._resource_requirement_empty.setText("" if entries else "The current scope does not require additional resources.")
            self._resource_requirement_empty.setVisible(True)
            if not entries:
                return
            shortages = sum(1 for entry in entries if entry.required > entry.owned)
            self._resource_aggregate_summary.setText(
                f"{len(entries)} items - {shortages} short - {planned_count} planned and {unplanned_included}/{unplanned_count} not planned students contributing."
            )
            self._populate_requirement_grid(self._resource_requirement_grid, entries)
        finally:
            self._resource_requirement_grid_host.setUpdatesEnabled(True)

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

    def _inventory_plan_requirement_index(self) -> dict[str, PlanResourceRequirement]:
        goal_map = self._plan_goal_map()
        total, _selected_count, _contributing_count = self._resource_total_for_ids(
            [goal.student_id for goal in self._plan.goals],
            goal_map,
        )
        entries = self._plan_requirement_entries(total)
        return {entry.key: entry for entry in entries}

    def _inventory_full_pool_goal_for_student(self, record: StudentRecord) -> StudentGoal:
        goal = StudentGoal(student_id=record.student_id)
        goal.target_level = MAX_TARGET_LEVEL
        goal.target_star = MAX_TARGET_STAR
        goal.target_ex_skill = MAX_TARGET_EX_SKILL
        goal.target_skill1 = MAX_TARGET_SKILL
        goal.target_skill2 = MAX_TARGET_SKILL
        goal.target_skill3 = MAX_TARGET_SKILL
        goal.target_equip1_tier = MAX_TARGET_EQUIP_TIER
        goal.target_equip2_tier = MAX_TARGET_EQUIP_TIER
        goal.target_equip3_tier = MAX_TARGET_EQUIP_TIER
        goal.target_equip1_level = MAX_TARGET_EQUIP_LEVEL
        goal.target_equip2_level = MAX_TARGET_EQUIP_LEVEL
        goal.target_equip3_level = MAX_TARGET_EQUIP_LEVEL
        if self._plan_allows_weapon_targets(record):
            goal.target_weapon_star = MAX_TARGET_WEAPON_STAR
            goal.target_weapon_level = MAX_TARGET_WEAPON_LEVEL
        if self._record_supports_unique_item(record):
            goal.target_equip4_tier = MAX_TARGET_EQUIP4_TIER
        goal.target_stat_hp = MAX_TARGET_STAT
        goal.target_stat_atk = MAX_TARGET_STAT
        goal.target_stat_heal = MAX_TARGET_STAT
        return goal

    def _inventory_full_pool_requirement_index(self) -> dict[str, PlanResourceRequirement]:
        total = PlanCostSummary()
        for record in self._all_students:
            goal = self._inventory_full_pool_goal_for_student(record)
            summary = self._cached_goal_cost(record.student_id, record=record, goal=goal)
            if summary is not None:
                total.merge(summary)
        entries = self._plan_requirement_entries(total)
        return {entry.key: entry for entry in entries}

    def _inventory_requirement_for_entry(
        self,
        item_id: str,
        name: str,
        requirement_index: dict[str, PlanResourceRequirement] | None = None,
    ) -> PlanResourceRequirement | None:
        requirement_index = requirement_index if requirement_index is not None else getattr(self, "_inventory_requirement_index", {})
        if item_id in requirement_index:
            return requirement_index[item_id]
        folded_name = name.casefold()
        for entry in requirement_index.values():
            if entry.name.casefold() == folded_name:
                return entry
        return None

    def _inventory_status_for_values(self, *, owned: int, required: int, pool_left: int = 0, tier: int = 0) -> str:
        if required > owned:
            return "High-tier Bottleneck" if tier >= 8 else "Plan Shortage"
        if pool_left > 0:
            return "Long-term Pressure"
        if required <= 0 and pool_left <= 0:
            return "Unused"
        return "Sufficient"

    @staticmethod
    def _inventory_bottleneck_bucket(category: str) -> str:
        if category in {"credits", "level_exp"}:
            return "Level"
        if category in {"equipment_exp", "equipment_materials"}:
            return "Equipment"
        if category == "weapon_exp":
            return "Weapon"
        if category in {"skill_books", "ex_ooparts", "skill_ooparts"}:
            return "Skill"
        if category == "stat_materials":
            return "Ability"
        return "Other"

    @staticmethod
    def _inventory_is_common_requirement_category(category: str) -> bool:
        return category in {
            "credits",
            "level_exp",
            "equipment_exp",
            "weapon_exp",
            "skill_books",
            "stat_materials",
            "equipment_materials",
        }

    def _inventory_common_bottleneck_text(self) -> str:
        buckets: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for entry in self._inventory_requirement_index.values():
            if not self._inventory_is_common_requirement_category(entry.category):
                continue
            required = max(0, entry.required)
            shortage = max(0, entry.required - entry.owned)
            if required <= 0:
                continue
            bucket = self._inventory_bottleneck_bucket(entry.category)
            buckets[bucket][0] += shortage
            buckets[bucket][1] += required
        rows = []
        for bucket, (shortage, required) in buckets.items():
            if required <= 0:
                continue
            ratio = int((shortage / required) * 100) if shortage > 0 else 0
            rows.append((ratio, shortage, bucket))
        rows.sort(key=lambda item: (-item[0], -item[1], item[2]))
        if not rows:
            return "No current common-material bottleneck in the plan."
        return "\n".join(f"{bucket}: {ratio}% short ({shortage:,})" for ratio, shortage, bucket in rows[:5])

    def _inventory_school_shortage_text(self) -> str:
        school_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"BD": 0, "TN": 0})
        wb_totals: dict[str, int] = defaultdict(int)
        for entry in self._inventory_requirement_index.values():
            shortage = max(0, entry.required - entry.owned)
            if shortage <= 0:
                continue
            item_id = entry.key
            match = re.match(r"Item_Icon_Material_ExSkill_([^_]+)_", item_id)
            if match:
                school_totals[match.group(1)]["BD"] += shortage
                continue
            match = re.match(r"Item_Icon_SkillBook_([^_]+)_", item_id)
            if match and "Ultimate" not in item_id:
                school_totals[match.group(1)]["TN"] += shortage
                continue
            if item_id in _WORKBOOK_ID_TO_NAME:
                wb_totals[_WORKBOOK_ID_TO_NAME[item_id].replace(" WB", "")] += shortage
        school_rows = [
            (values["BD"] + values["TN"], school, values)
            for school, values in school_totals.items()
            if values["BD"] or values["TN"]
        ]
        school_rows.sort(key=lambda item: (-item[0], item[1]))
        lines = [f"{school}: BD {values['BD']:,} - TN {values['TN']:,}" for _total, school, values in school_rows[:4]]
        if wb_totals:
            wb_text = ", ".join(f"{name} {amount:,}" for name, amount in sorted(wb_totals.items()))
            lines.append(f"WB: {wb_text}")
        return "\n".join(lines) if lines else "No BD, tech note, or WB shortage in the current plan."

    def _inventory_build_oopart_plan_usage(self) -> dict[str, InventoryOpartPlanUsage]:
        usage_by_item: dict[str, InventoryOpartPlanUsage] = {}
        impact_by_item: dict[str, dict[str, InventoryOpartStudentImpact]] = {}
        pool_impact_by_item: dict[str, dict[str, InventoryOpartStudentImpact]] = {}

        def add_summary(
            *,
            record: StudentRecord,
            summary: PlanCostSummary,
            target_usage_by_item: dict[str, InventoryOpartPlanUsage],
            target_impact_by_item: dict[str, dict[str, InventoryOpartStudentImpact]],
            pool: bool,
        ) -> None:
            for category, values, impact_field in (
                ("ex_ooparts", summary.ex_ooparts, "ex_required"),
                ("skill_ooparts", summary.skill_ooparts, "skill_required"),
            ):
                for key, raw_required in values.items():
                    required = int(raw_required or 0)
                    if required <= 0:
                        continue
                    item_id = _plan_resource_item_id(key, category)
                    if not item_id or item_id not in _OPART_ITEM_IDS:
                        continue
                    name = _plan_resource_display_name(item_id, key)
                    usage = target_usage_by_item.get(item_id)
                    if usage is None:
                        usage = InventoryOpartPlanUsage(item_id=item_id, name=name)
                        target_usage_by_item[item_id] = usage
                    if pool:
                        usage.pool_required += required
                        if impact_field == "ex_required":
                            usage.pool_ex_required += required
                        else:
                            usage.pool_skill_required += required
                    else:
                        usage.required += required
                        if impact_field == "ex_required":
                            usage.ex_required += required
                        else:
                            usage.skill_required += required

                    impacts = target_impact_by_item.setdefault(item_id, {})
                    impact = impacts.get(record.student_id)
                    if impact is None:
                        impact = InventoryOpartStudentImpact(student_id=record.student_id, title=record.title)
                        impacts[record.student_id] = impact
                    if impact_field == "ex_required":
                        impact.ex_required += required
                    else:
                        impact.skill_required += required

        goal_map = self._plan_goal_map()

        for student_id, goal in goal_map.items():
            record = self._records_by_id.get(student_id)
            if record is None:
                continue
            summary = self._cached_goal_cost(student_id, record=record, goal=goal)
            if summary is None:
                continue
            add_summary(
                record=record,
                summary=summary,
                target_usage_by_item=usage_by_item,
                target_impact_by_item=impact_by_item,
                pool=False,
            )

        for record in self._all_students:
            goal = StudentGoal(student_id=record.student_id)
            goal.target_ex_skill = MAX_TARGET_EX_SKILL
            goal.target_skill1 = MAX_TARGET_SKILL
            goal.target_skill2 = MAX_TARGET_SKILL
            goal.target_skill3 = MAX_TARGET_SKILL
            summary = self._cached_goal_cost(record.student_id, record=record, goal=goal)
            if summary is None:
                continue
            add_summary(
                record=record,
                summary=summary,
                target_usage_by_item=usage_by_item,
                target_impact_by_item=pool_impact_by_item,
                pool=True,
            )

        for item_id, usage in usage_by_item.items():
            usage.owned = self._inventory_quantity_index_cache.get(item_id, 0)
            usage.impacts = sorted(
                impact_by_item.get(item_id, {}).values(),
                key=lambda impact: (-impact.total_required, impact.title.lower(), impact.student_id),
            )
            usage.pool_impacts = sorted(
                pool_impact_by_item.get(item_id, {}).values(),
                key=lambda impact: (-impact.total_required, impact.title.lower(), impact.student_id),
            )
        return usage_by_item

    @staticmethod
    def _inventory_coverage(owned: int, required: int) -> str:
        if required <= 0:
            return "-"
        return f"{min(100, int((owned / required) * 100))}%"

    def _inventory_oopart_status(self, usage: InventoryOpartPlanUsage | None) -> str:
        if usage is None or (usage.required <= 0 and usage.pool_required <= 0):
            return "Unused"
        if usage.shortage > 0:
            return "Plan Shortage"
        if usage.pool_shortage > 0:
            return "Long-term Pressure"
        return "Sufficient"

    def _clear_inventory_oopart_metrics(self) -> None:
        for label in getattr(self, "_inventory_oopart_metric_labels", {}).values():
            label.setText("-")

    def _set_inventory_metric(self, key: str, value: str) -> None:
        label = getattr(self, "_inventory_oopart_metric_labels", {}).get(key)
        if label is not None:
            label.setText(value)

    def _inventory_student_consumers(self, item_id: str, name: str) -> list[tuple[str, int]]:
        consumers: list[tuple[str, int]] = []
        goal_map = self._plan_goal_map()
        for student_id, goal in goal_map.items():
            record = self._records_by_id.get(student_id)
            if record is None:
                continue
            summary = self._cached_goal_cost(student_id, record=record, goal=goal)
            if summary is None:
                continue
            for entry in self._plan_requirement_entries(summary, record=record):
                if entry.key == item_id or entry.name.casefold() == name.casefold():
                    consumers.append((record.title, entry.required))
                    break
        consumers.sort(key=lambda item: (-item[1], item[0].casefold()))
        return consumers

    @staticmethod
    def _inventory_exp_yield(category: str, item_id: str, name: str) -> tuple[str, int] | None:
        tier = _tier_from_item_id_or_name(item_id, name)
        if tier <= 0:
            return None
        index = max(0, min(3, tier - 1))
        if category == "level_exp":
            return "Level EXP", (50, 500, 2_000, 10_000)[index]
        if category == "equipment_exp":
            return "Equipment EXP", (90, 360, 1_440, 5_760)[index]
        if category == "weapon_exp":
            return "Weapon EXP", (10, 50, 200, 1_000)[index]
        return None

    def _on_inventory_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None or not hasattr(self, "_inventory_oopart_detail_title"):
            return
        category = str(current.data(Qt.UserRole + 6) or "")
        if category == "ooparts":
            return

        item_id = str(current.data(Qt.UserRole) or "")
        name = str(current.data(Qt.UserRole + 1) or item_id or "Inventory item")
        owned = int(current.data(Qt.UserRole + 2) or 0)
        required = int(current.data(Qt.UserRole + 3) or 0)
        shortage = int(current.data(Qt.UserRole + 4) or 0)
        status = str(current.data(Qt.UserRole + 5) or self._inventory_status_for_values(owned=owned, required=required))
        pool_required = int(current.data(Qt.UserRole + 7) or 0)
        pool_left = int(current.data(Qt.UserRole + 8) or 0)

        self._inventory_oopart_detail_title.setText(name)
        self._inventory_oopart_impact_list.clear()
        self._set_inventory_metric("owned", f"{owned:,}")
        self._set_inventory_metric("required", f"{required:,}" if required > 0 else "-")
        self._set_inventory_metric("shortage", f"{shortage:,}" if shortage > 0 else "-")
        self._set_inventory_metric("coverage", self._inventory_coverage(owned, required))
        self._set_inventory_metric("pool_required", f"{pool_required:,}" if pool_required > 0 else "-")
        self._set_inventory_metric("pool_shortage", f"{pool_left:,}" if pool_left > 0 else "-")
        self._set_inventory_metric("pool_coverage", self._inventory_coverage(owned, pool_required))
        self._set_inventory_metric("ex_required", "-")
        self._set_inventory_metric("skill_required", "-")

        consumers = self._inventory_student_consumers(item_id, name) if required > 0 else []
        self._set_inventory_metric("affected", f"{len(consumers):,}" if consumers else "-")
        category_text = category.replace("_", " ").title() if category else "Inventory"
        self._inventory_oopart_detail_summary.setText(
            f"Status: {status}. {category_text} material compared against current plan and full-pool demand."
        )
        if pool_required > 0:
            self._inventory_oopart_impact_list.addItem(
                f"Full pool demand: need {pool_required:,}, left {pool_left:,}, coverage {self._inventory_coverage(owned, pool_required)}"
            )
        exp_yield = self._inventory_exp_yield(category, item_id, name)
        if exp_yield is not None and owned > 0:
            label, value = exp_yield
            self._inventory_oopart_impact_list.addItem(f"Converted value: {owned * value:,} {label}")
        if consumers:
            for title, amount in consumers[:12]:
                self._inventory_oopart_impact_list.addItem(f"{title} - needs {amount:,}")
        else:
            self._inventory_oopart_impact_list.addItem("No current planned student consumes this item.")

    def _on_inventory_oopart_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        item_id = str(current.data(Qt.UserRole) or "") if current is not None else ""
        self._inventory_oopart_selected_id = item_id or None
        if current is not None:
            target = self._inventory_item_lists.get("ooparts") if hasattr(self, "_inventory_item_lists") else None
            widget = target.itemWidget(current) if target is not None else None
            if isinstance(widget, InventoryOpartFamilyRow):
                widget.setSelectedItem(item_id)
        self._update_inventory_oopart_detail(current)

    def _on_inventory_oopart_cell_selected(self, item_id: str, list_item: QListWidgetItem, widget: InventoryOpartFamilyRow) -> None:
        list_item.setData(Qt.UserRole, item_id)
        list_item.setData(Qt.UserRole + 1, _plan_resource_display_name(item_id, item_id))
        list_item.setData(Qt.UserRole + 2, self._inventory_quantity_index_cache.get(item_id, 0))
        usage = self._inventory_oopart_plan_usage.get(item_id) if hasattr(self, "_inventory_oopart_plan_usage") else None
        list_item.setData(Qt.UserRole + 3, usage.required if usage else 0)
        list_item.setData(Qt.UserRole + 4, usage.shortage if usage else 0)
        list_item.setData(Qt.UserRole + 5, self._inventory_oopart_status(usage))
        list_item.setData(Qt.UserRole + 6, "ooparts")
        widget.setSelectedItem(item_id)
        target = self._inventory_item_lists.get("ooparts") if hasattr(self, "_inventory_item_lists") else None
        if target is not None:
            target.setCurrentItem(list_item)
        self._inventory_oopart_selected_id = item_id
        self._update_inventory_oopart_detail(list_item)

    def _on_inventory_priority_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        item_id = str(current.data(Qt.UserRole) or "") if current is not None else ""
        if item_id:
            category = str(current.data(Qt.UserRole + 6) or "")
            if category == "ooparts" or item_id in _OPART_ITEM_IDS:
                self._select_inventory_oopart(item_id)
            else:
                self._select_inventory_item(item_id)

    def _select_inventory_item(self, item_id: str) -> None:
        if not item_id:
            return
        for list_map, root_index in (
            (getattr(self, "_inventory_equipment_lists", {}), 0),
            (getattr(self, "_inventory_item_lists", {}), 1),
        ):
            for category_index, (_category, target) in enumerate(list_map.items()):
                for index in range(target.count()):
                    item = target.item(index)
                    if str(item.data(Qt.UserRole) or "") == item_id:
                        self._inventory_root_tabs.setCurrentIndex(root_index)
                        if root_index == 0 and hasattr(self, "_inventory_equipment_tabs"):
                            self._inventory_equipment_tabs.setCurrentIndex(category_index)
                        elif root_index == 1 and hasattr(self, "_inventory_item_tabs"):
                            self._inventory_item_tabs.setCurrentIndex(category_index)
                        target.setCurrentItem(item)
                        target.scrollToItem(item)
                        return

    def _select_inventory_oopart(self, item_id: str) -> None:
        if not hasattr(self, "_inventory_item_lists"):
            return
        target = self._inventory_item_lists.get("ooparts")
        if target is None:
            return
        family_prefix = "_".join(item_id.rsplit("_", 1)[:-1])
        for index in range(target.count()):
            item = target.item(index)
            current_id = str(item.data(Qt.UserRole) or "")
            current_prefix = "_".join(current_id.rsplit("_", 1)[:-1])
            if current_id == item_id or (family_prefix and current_prefix == family_prefix):
                item.setData(Qt.UserRole, item_id)
                item.setData(Qt.UserRole + 1, _plan_resource_display_name(item_id, item_id))
                item.setData(Qt.UserRole + 2, self._inventory_quantity_index_cache.get(item_id, 0))
                usage = self._inventory_oopart_plan_usage.get(item_id) if hasattr(self, "_inventory_oopart_plan_usage") else None
                item.setData(Qt.UserRole + 3, usage.required if usage else 0)
                item.setData(Qt.UserRole + 4, usage.shortage if usage else 0)
                item.setData(Qt.UserRole + 5, self._inventory_oopart_status(usage))
                item.setData(Qt.UserRole + 6, "ooparts")
                widget = target.itemWidget(item)
                if isinstance(widget, InventoryOpartFamilyRow):
                    widget.setSelectedItem(item_id)
                self._inventory_root_tabs.setCurrentIndex(1)
                self._inventory_item_tabs.setCurrentIndex(0)
                target.setCurrentItem(item)
                target.scrollToItem(item)
                return

    def _configure_inventory_priority_cards(self, target: QListWidget) -> None:
        target.setViewMode(QListView.ListMode)
        target.setResizeMode(QListView.Adjust)
        target.setMovement(QListView.Static)
        target.setFlow(QListView.TopToBottom)
        target.setWrapping(False)
        target.setWordWrap(True)
        target.setSpacing(scale_px(6, self._ui_scale))
        target.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        target.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def _add_inventory_usage_list_item(self, target: QListWidget, usage: InventoryOpartPlanUsage, *, pool: bool) -> None:
        if pool:
            amount = usage.pool_shortage
            meta = f"{usage.owned:,} / {usage.pool_required:,} - pool left"
            tooltip = f"{usage.name}\nFull pool left {usage.pool_shortage:,} / need {usage.pool_required:,}"
        else:
            amount = usage.shortage
            meta = f"{usage.owned:,} / {usage.required:,} - {len(usage.impacts)} planned"
            tooltip = f"{usage.name}\nPlan short {usage.shortage:,} / need {usage.required:,}"
        item = QListWidgetItem("")
        item.setSizeHint(QSize(scale_px(220, self._ui_scale), scale_px(64, self._ui_scale)))
        item.setData(Qt.UserRole, usage.item_id)
        target.addItem(item)

        row = InventoryPressureRow(ui_scale=self._ui_scale)
        icon_path = _inventory_icon_path(usage.item_id, usage.name)
        row.setData(
            icon_path=icon_path,
            item_id=usage.item_id,
            name=usage.name,
            amount=amount,
            meta=meta,
            pool=pool,
        )
        target.setItemWidget(item, row)
        item.setToolTip(tooltip)
        item.setData(Qt.UserRole + 6, "ooparts")

    def _add_inventory_requirement_list_item(self, target: QListWidget, entry: PlanResourceRequirement, *, pool: bool) -> None:
        shortage = max(0, entry.required - entry.owned)
        if shortage <= 0:
            return
        item = QListWidgetItem("")
        item.setSizeHint(QSize(scale_px(220, self._ui_scale), scale_px(64, self._ui_scale)))
        item.setData(Qt.UserRole, entry.key)
        item.setData(Qt.UserRole + 1, entry.name)
        item.setData(Qt.UserRole + 2, entry.owned)
        item.setData(Qt.UserRole + 3, entry.required)
        item.setData(Qt.UserRole + 4, shortage)
        item.setData(Qt.UserRole + 6, entry.category)
        target.addItem(item)

        row = InventoryPressureRow(ui_scale=self._ui_scale)
        row.setData(
            icon_path=entry.icon_path,
            item_id=entry.key,
            name=entry.name,
            amount=shortage,
            meta=f"{entry.owned:,} / {entry.required:,} - {'pool left' if pool else 'plan short'}",
            pool=pool,
        )
        target.setItemWidget(item, row)
        item.setToolTip(f"{entry.name}\nShort {shortage:,} / need {entry.required:,}")

    def _refresh_inventory_insight_panel(self) -> None:
        if not hasattr(self, "_inventory_insight_summary"):
            return
        self._inventory_plan_priority_list.clear()
        self._inventory_pool_pressure_list.clear()
        if hasattr(self, "_inventory_bottleneck_summary"):
            self._inventory_bottleneck_summary.setText(self._inventory_common_bottleneck_text())
        if hasattr(self, "_inventory_school_summary"):
            self._inventory_school_summary.setText(self._inventory_school_shortage_text())

        usages = list(self._inventory_oopart_plan_usage.values())
        plan_requirement_top = [
            entry
            for entry in sorted(
                self._inventory_requirement_index.values(),
                key=lambda entry: (-(entry.required - entry.owned), entry.name.lower()),
            )
            if self._inventory_is_common_requirement_category(entry.category) and entry.required > entry.owned
        ][:5]
        pool_requirement_top = [
            entry
            for entry in sorted(
                self._inventory_pool_requirement_index.values(),
                key=lambda entry: (-(entry.required - entry.owned), entry.name.lower()),
            )
            if self._inventory_is_common_requirement_category(entry.category) and entry.required > entry.owned
        ][:5]

        if not usages and not plan_requirement_top and not pool_requirement_top:
            self._inventory_insight_summary.setText("No planned or full-pool Ooparts demand is available yet.")
            self._update_inventory_oopart_detail(None)
            return

        planned_count = sum(1 for usage in usages if usage.required > 0)
        plan_shortage_items = sum(1 for usage in usages if usage.shortage > 0)
        plan_shortage_total = sum(usage.shortage for usage in usages)
        pool_count = sum(1 for usage in usages if usage.pool_required > 0)
        pool_shortage_items = sum(1 for usage in usages if usage.pool_shortage > 0)
        pool_shortage_total = sum(usage.pool_shortage for usage in usages)
        self._inventory_insight_summary.setText(
            f"Plan demand uses {planned_count} Ooparts; {plan_shortage_items} are short by {plan_shortage_total:,}. "
            f"Full pool demand uses {pool_count}; {pool_shortage_items} remain short by {pool_shortage_total:,}. "
            f"Common plan bottlenecks: {len(plan_requirement_top)}."
        )

        plan_top = [usage for usage in sorted(usages, key=lambda usage: (-usage.shortage, usage.name.lower())) if usage.shortage > 0][:8]
        pool_top = [usage for usage in sorted(usages, key=lambda usage: (-usage.pool_shortage, usage.name.lower())) if usage.pool_shortage > 0][:8]
        if plan_top or plan_requirement_top:
            for usage in plan_top:
                self._add_inventory_usage_list_item(self._inventory_plan_priority_list, usage, pool=False)
            for entry in plan_requirement_top:
                self._add_inventory_requirement_list_item(self._inventory_plan_priority_list, entry, pool=False)
        else:
            self._inventory_plan_priority_list.addItem("No current plan shortages.")
        if pool_top or pool_requirement_top:
            for usage in pool_top:
                self._add_inventory_usage_list_item(self._inventory_pool_pressure_list, usage, pool=True)
            for entry in pool_requirement_top:
                self._add_inventory_requirement_list_item(self._inventory_pool_pressure_list, entry, pool=True)
        else:
            self._inventory_pool_pressure_list.addItem("No remaining full-pool shortages.")

    def _update_inventory_oopart_detail(self, current: QListWidgetItem | None) -> None:
        if not hasattr(self, "_inventory_oopart_detail_title"):
            return
        self._inventory_oopart_impact_list.clear()
        if current is None:
            self._inventory_oopart_detail_title.setText("Select an oopart")
            self._inventory_oopart_detail_summary.setText("Pick an item above to see planned use and affected students.")
            self._clear_inventory_oopart_metrics()
            return

        item_id = str(current.data(Qt.UserRole) or "")
        name = str(current.data(Qt.UserRole + 1) or item_id or "Oopart")
        owned = int(current.data(Qt.UserRole + 2) or 0)
        usage = self._inventory_oopart_plan_usage.get(item_id)
        self._inventory_oopart_detail_title.setText(name)
        if usage is None:
            usage = InventoryOpartPlanUsage(item_id=item_id, name=name, owned=owned)
        else:
            usage.owned = owned

        self._set_inventory_metric("owned", f"{owned:,}")
        self._set_inventory_metric("required", f"{usage.required:,}" if usage.required > 0 else "-")
        self._set_inventory_metric("shortage", f"{usage.shortage:,}" if usage.shortage > 0 else "-")
        self._set_inventory_metric("coverage", self._inventory_coverage(owned, usage.required))
        self._set_inventory_metric("pool_required", f"{usage.pool_required:,}" if usage.pool_required > 0 else "-")
        self._set_inventory_metric("pool_shortage", f"{usage.pool_shortage:,}" if usage.pool_shortage > 0 else "-")
        self._set_inventory_metric("pool_coverage", self._inventory_coverage(owned, usage.pool_required))
        self._set_inventory_metric("ex_required", f"{usage.ex_required:,}" if usage.ex_required > 0 else "-")
        self._set_inventory_metric("skill_required", f"{usage.skill_required:,}" if usage.skill_required > 0 else "-")
        self._set_inventory_metric("affected", f"{len(usage.impacts):,} / {len(usage.pool_impacts):,}")

        status = self._inventory_oopart_status(usage)
        planned_ids = set(self._plan_goal_map())
        planned_pool_count = sum(1 for impact in usage.pool_impacts if impact.student_id in planned_ids)
        self._inventory_oopart_detail_summary.setText(
            f"Status: {status}. Full pool affected students: {len(usage.pool_impacts)} "
            f"({planned_pool_count} currently planned)."
        )
        if not usage.pool_impacts:
            self._inventory_oopart_impact_list.addItem("No full-pool student demand.")
            return

        for impact in usage.pool_impacts:
            is_planned = impact.student_id in planned_ids
            prefix = "[Plan] " if is_planned else ""
            item = QListWidgetItem(
                f"{prefix}{impact.title} ({impact.student_id}) - "
                f"EX {impact.ex_required:,} / Skill {impact.skill_required:,} / Total {impact.total_required:,}"
            )
            if is_planned:
                item.setBackground(QColor("#3a2238"))
                item.setForeground(QColor("#ffe1f0"))
            self._inventory_oopart_impact_list.addItem(item)

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

    def _set_inventory_oopart_family_items(
        self,
        target: QListWidget,
        summary: QLabel,
        oopart_usage: dict[str, InventoryOpartPlanUsage],
    ) -> None:
        target.clear()
        if not self._inventory_oopart_selected_id and OPART_DEFINITIONS:
            self._inventory_oopart_selected_id = f"Item_Icon_Material_{OPART_DEFINITIONS[0].icon_key}_3"

        usages = list(oopart_usage.values())
        plan_shortage_items = sum(1 for usage in usages if usage.shortage > 0)
        plan_shortage_total = sum(usage.shortage for usage in usages)
        pool_shortage_items = sum(1 for usage in usages if usage.pool_shortage > 0)
        pool_shortage_total = sum(usage.pool_shortage for usage in usages)
        summary.setText(
            f"{len(OPART_DEFINITIONS)} families - plan short {plan_shortage_items} ({plan_shortage_total:,}) - "
            f"full pool short {pool_shortage_items} ({pool_shortage_total:,})"
        )

        restore_item: QListWidgetItem | None = None
        for definition in OPART_DEFINITIONS:
            tier_items: list[tuple[int, str, str, int, str, Path | None]] = []
            row_selected_id = self._inventory_oopart_selected_id
            family_ids = [f"Item_Icon_Material_{definition.icon_key}_{index}" for index in range(4)]
            if row_selected_id not in family_ids:
                row_selected_id = family_ids[-1]
            for tier_index in range(3, -1, -1):
                item_id = f"Item_Icon_Material_{definition.icon_key}_{tier_index}"
                name = _plan_resource_display_name(item_id, item_id)
                usage = oopart_usage.get(item_id)
                owned = self._inventory_quantity_index_cache.get(item_id, 0)
                status = self._inventory_oopart_status(usage)
                tier_items.append((tier_index + 1, item_id, name, owned, status, _inventory_icon_path(item_id, name)))

            widget = InventoryOpartFamilyRow(
                family_name=definition.family_en,
                tier_items=tier_items,
                selected_item_id=self._inventory_oopart_selected_id if self._inventory_oopart_selected_id in family_ids else None,
                ui_scale=self._ui_scale,
            )
            item = QListWidgetItem()
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setSizeHint(QSize(scale_px(320, self._ui_scale), scale_px(98, self._ui_scale)))
            item.setData(Qt.UserRole, row_selected_id)
            item.setData(Qt.UserRole + 1, _plan_resource_display_name(row_selected_id, row_selected_id))
            item.setData(Qt.UserRole + 2, self._inventory_quantity_index_cache.get(row_selected_id, 0))
            selected_usage = oopart_usage.get(row_selected_id)
            item.setData(Qt.UserRole + 3, selected_usage.required if selected_usage else 0)
            item.setData(Qt.UserRole + 4, selected_usage.shortage if selected_usage else 0)
            item.setData(Qt.UserRole + 5, self._inventory_oopart_status(selected_usage))
            item.setData(Qt.UserRole + 6, "ooparts")
            target.addItem(item)
            target.setItemWidget(item, widget)
            widget.selected.connect(lambda value, list_item=item, row_widget=widget: self._on_inventory_oopart_cell_selected(value, list_item, row_widget))
            if self._inventory_oopart_selected_id in family_ids:
                restore_item = item

        if restore_item is None and target.count() > 0:
            restore_item = target.item(0)
            self._inventory_oopart_selected_id = str(restore_item.data(Qt.UserRole) or "")
        target.setCurrentItem(restore_item)
        self._update_inventory_oopart_detail(restore_item)

    def _set_inventory_list_items(
        self,
        target: QListWidget,
        summary: QLabel,
        entries: list[tuple[str, dict]],
        *,
        category: str = "",
        oopart_usage: dict[str, InventoryOpartPlanUsage] | None = None,
    ) -> None:
        if category == "ooparts":
            self._set_inventory_oopart_family_items(target, summary, oopart_usage or {})
            return

        target.clear()
        requirement_index = getattr(self, "_inventory_requirement_index", {})
        pool_requirement_index = getattr(self, "_inventory_pool_requirement_index", {})
        if not entries:
            summary.setText("No scanned items in this category yet.")
            target.addItem("Run an item or equipment scan to populate this category.")
            if category == "ooparts":
                self._inventory_oopart_selected_id = None
                self._update_inventory_oopart_detail(None)
            return

        total_quantity = sum(
            quantity
            for _item_key, payload in entries
            if (quantity := _inventory_quantity_value(payload.get("quantity"))) is not None
        )
        summary.setText(f"{len(entries)} items 쨌 total quantity {total_quantity:,}")

        if category == "ooparts" and oopart_usage:
            shortage_items = sum(1 for usage in oopart_usage.values() if usage.shortage > 0)
            total_shortage = sum(usage.shortage for usage in oopart_usage.values())
            pool_shortage_items = sum(1 for usage in oopart_usage.values() if usage.pool_shortage > 0)
            pool_total_shortage = sum(usage.pool_shortage for usage in oopart_usage.values())
            plan_top = sorted(oopart_usage.values(), key=lambda usage: (-usage.shortage, usage.name.lower()))[:3]
            pool_top = sorted(oopart_usage.values(), key=lambda usage: (-usage.pool_shortage, usage.name.lower()))[:3]
            plan_top_text = ", ".join(f"{usage.name} {usage.shortage:,}" for usage in plan_top if usage.shortage > 0) or "none"
            pool_top_text = ", ".join(f"{usage.name} {usage.pool_shortage:,}" for usage in pool_top if usage.pool_shortage > 0) or "none"
            summary.setText(
                f"{len(entries)} items - total quantity {total_quantity:,} - "
                f"plan short {shortage_items} ({total_shortage:,}) - "
                f"full pool short {pool_shortage_items} ({pool_total_shortage:,})\n"
                f"Plan priority: {plan_top_text}\n"
                f"Full pool pressure: {pool_top_text}"
            )

        restore_item: QListWidgetItem | None = None
        for item_key, payload in entries:
            item_id = payload.get("item_id")
            item_id_text = str(item_id) if item_id else str(item_key)
            name = _inventory_display_label(item_key, payload)
            quantity_value = _inventory_quantity_value(payload.get("quantity"))
            owned = quantity_value if quantity_value is not None else 0
            requirement = self._inventory_requirement_for_entry(item_id_text, name, requirement_index)
            required = requirement.required if requirement is not None else 0
            plan_short = max(0, required - owned)
            pool_requirement = self._inventory_requirement_for_entry(item_id_text, name, pool_requirement_index)
            pool_required = pool_requirement.required if pool_requirement is not None else 0
            pool_left = max(0, pool_required - owned)
            usage = oopart_usage.get(item_id_text) if oopart_usage else None
            shortage = bool(usage and (usage.shortage > 0 or usage.pool_shortage > 0))
            if usage and usage.required > 0:
                quantity = f"{owned:,} / {usage.required:,}"
                meta = (
                    f"Plan need {usage.required:,} - Plan short {usage.shortage:,} - "
                    f"Full pool need {usage.pool_required:,} - Pool left {usage.pool_shortage:,} - "
                    f"EX {usage.ex_required:,} / Skill {usage.skill_required:,} - {len(usage.impacts)} planned"
                )
            elif usage and usage.pool_required > 0:
                quantity = f"{owned:,} / 0"
                meta = (
                    f"No plan demand - Full pool need {usage.pool_required:,} - "
                    f"Pool left {usage.pool_shortage:,} - EX {usage.pool_ex_required:,} / Skill {usage.pool_skill_required:,}"
                )
            else:
                quantity = f"{quantity_value:,}" if quantity_value is not None else str(payload.get("quantity") or "?")
                tier = _tier_from_item_id_or_name(item_id_text, name)
                meta_parts = []
                if category:
                    meta_parts.append(category.replace("_", " ").title())
                if tier:
                    meta_parts.append(f"T{tier}")
                meta = " - ".join(meta_parts)
            if not usage:
                tier = _tier_from_item_id_or_name(item_id_text, name)
                status = self._inventory_status_for_values(owned=owned, required=required, pool_left=pool_left, tier=tier)
                shortage = plan_short > 0
                plan_need_text = f"{required:,}" if required > 0 else "-"
                plan_short_text = f"-{plan_short:,}" if plan_short > 0 else "-"
                pool_remain_text = f"{pool_left:,}" if pool_left > 0 else "-"
            else:
                status = self._inventory_oopart_status(usage)
                plan_need_text = f"{usage.required:,}" if usage.required > 0 else "-"
                plan_short_text = f"-{usage.shortage:,}" if usage.shortage > 0 else "-"
                pool_remain_text = f"{usage.pool_shortage:,}" if usage.pool_shortage > 0 else "-"
            widget = InventoryListItem(ui_scale=self._ui_scale)
            widget.setData(
                icon_path=_inventory_icon_path(str(item_id) if item_id else None, name),
                item_id=item_id_text or None,
                name=name,
                quantity=quantity,
                meta=meta,
                shortage=shortage,
                plan_need=plan_need_text,
                plan_short=plan_short_text,
                pool_remain=pool_remain_text,
                status=status,
            )
            item = QListWidgetItem()
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            item.setSizeHint(QSize(scale_px(640, self._ui_scale), scale_px(64, self._ui_scale)))
            item.setData(Qt.UserRole, item_id_text)
            item.setData(Qt.UserRole + 1, name)
            item.setData(Qt.UserRole + 2, owned)
            item.setData(Qt.UserRole + 3, required if not usage else usage.required)
            item.setData(Qt.UserRole + 4, plan_short if not usage else usage.shortage)
            item.setData(Qt.UserRole + 5, status)
            item.setData(Qt.UserRole + 6, category)
            item.setData(Qt.UserRole + 7, pool_required if not usage else usage.pool_required)
            item.setData(Qt.UserRole + 8, pool_left if not usage else usage.pool_shortage)
            target.addItem(item)
            target.setItemWidget(item, widget)
            if category == "ooparts" and item_id_text == self._inventory_oopart_selected_id:
                restore_item = item

        if category == "ooparts":
            if restore_item is None and target.count() > 0:
                restore_item = target.item(0)
            target.setCurrentItem(restore_item)
            self._update_inventory_oopart_detail(restore_item)

    def _refresh_inventory_tab(self) -> None:
        if not hasattr(self, "_inventory_root_tabs"):
            return

        inventory = self._inventory_snapshot or {}
        self._inventory_requirement_index = self._inventory_plan_requirement_index()
        self._inventory_pool_requirement_index = self._inventory_full_pool_requirement_index()
        if not inventory:
            self._inventory_summary.setText("No scanned inventory is available yet. Run an item or equipment scan to populate this tab.")
            self._inventory_oopart_plan_usage = self._inventory_build_oopart_plan_usage()
            for key, widget in self._inventory_equipment_lists.items():
                self._set_inventory_list_items(widget, self._inventory_equipment_summaries[key], [])
            for key, widget in self._inventory_item_lists.items():
                if key == "ooparts" and self._inventory_oopart_plan_usage:
                    entries = [
                        (
                            item_id,
                            {
                                "item_id": item_id,
                                "name": usage.name,
                                "quantity": 0,
                                "planned_only": True,
                            },
                        )
                        for item_id, usage in self._inventory_oopart_plan_usage.items()
                    ]
                    entries.sort(key=lambda entry: _OPART_ITEM_IDS.index(entry[0]) if entry[0] in _OPART_ITEM_IDS else 9999)
                    self._set_inventory_list_items(
                        widget,
                        self._inventory_item_summaries[key],
                        entries,
                        category=key,
                        oopart_usage=self._inventory_oopart_plan_usage,
                    )
                else:
                    self._set_inventory_list_items(widget, self._inventory_item_summaries[key], [], category=key)
            self._refresh_inventory_insight_panel()
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

        self._inventory_oopart_plan_usage = self._inventory_build_oopart_plan_usage()
        self._refresh_inventory_insight_panel()

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

        scanned_oopart_ids = {
            str(payload.get("item_id") or item_key)
            for item_key, payload in item_groups["ooparts"]
        }
        for item_id, usage in self._inventory_oopart_plan_usage.items():
            if item_id in scanned_oopart_ids:
                continue
            item_groups["ooparts"].append(
                (
                    item_id,
                    {
                        "item_id": item_id,
                        "name": usage.name,
                        "quantity": usage.owned,
                        "planned_only": True,
                    },
                )
            )

        known_requirement_ids = {
            str(payload.get("item_id") or item_key)
            for item_key, payload in inventory.items()
        }
        known_requirement_ids.update(str(payload.get("item_id") or item_key) for item_key, payload in item_groups["ooparts"])
        requirement_entries: dict[str, PlanResourceRequirement] = {}
        requirement_entries.update(self._inventory_pool_requirement_index)
        requirement_entries.update(self._inventory_requirement_index)
        for item_id, entry in requirement_entries.items():
            if not self._inventory_is_common_requirement_category(entry.category):
                continue
            if item_id in known_requirement_ids or item_id in _OPART_ITEM_IDS:
                continue
            payload = {
                "item_id": item_id,
                "name": entry.name,
                "quantity": 0,
                "planned_only": True,
            }
            if item_id.startswith("Equipment_Icon_") and "_Tier" in item_id:
                series_key = item_id.removeprefix("Equipment_Icon_").split("_Tier", 1)[0]
                if series_key in equipment_groups:
                    equipment_groups[series_key].append((item_id, payload))
                    known_requirement_ids.add(item_id)
                    continue
            item_groups[self._inventory_classify_item(item_id, payload)].append((item_id, payload))
            known_requirement_ids.add(item_id)

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
                category=category,
                oopart_usage=self._inventory_oopart_plan_usage if category == "ooparts" else None,
            )

    def _build_tactical_tab(self, root: QWidget) -> None:
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(scale_px(12, self._ui_scale))

        header = QFrame()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(
            scale_px(18, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(16, self._ui_scale),
        )
        title = QLabel("Tactical Challenge")
        title.setObjectName("title")
        subtitle = QLabel("전술대항전 전적, 상대 방어덱, 공격 족보를 한 곳에서 기록하고 찾아봅니다.")
        subtitle.setObjectName("count")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        input_panel = QFrame()
        input_panel.setObjectName("panel")
        input_scroll = QScrollArea()
        input_scroll.setWidgetResizable(True)
        input_scroll.setFrameShape(QFrame.NoFrame)
        input_scroll.setWidget(input_panel)
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        input_layout.setSpacing(scale_px(10, self._ui_scale))

        match_title = QLabel("오늘 전적 입력")
        match_title.setObjectName("sectionTitle")
        input_layout.addWidget(match_title)
        date_row = QHBoxLayout()
        date_row.setContentsMargins(0, 0, 0, 0)
        self._tactical_date = QLineEdit(date.today().isoformat())
        self._tactical_season = QLineEdit(self._tactical_data.season or "")
        self._tactical_season.setPlaceholderText("시즌")
        self._tactical_season.editingFinished.connect(self._save_tactical_season)
        date_row.addWidget(QLabel("날짜"))
        date_row.addWidget(self._tactical_date, 1)
        date_row.addWidget(QLabel("시즌"))
        date_row.addWidget(self._tactical_season, 1)
        input_layout.addLayout(date_row)

        self._tactical_match_panels: list[dict] = []
        panel_widget, panel = self._build_tactical_match_input_panel(1)
        self._tactical_match_panels.append(panel)
        input_layout.addWidget(panel_widget)

        abbrev_panel = self._build_tactical_abbreviation_panel()
        input_layout.addWidget(abbrev_panel)

        self._tactical_status = QLabel("")
        self._tactical_status.setObjectName("filterSummary")
        self._tactical_status.setWordWrap(True)
        self._tactical_status.setMaximumHeight(scale_px(48, self._ui_scale))
        self._tactical_status.hide()
        input_layout.addStretch(1)
        splitter.addWidget(input_scroll)

        history_panel = QFrame()
        history_panel.setObjectName("panel")
        history_layout = QVBoxLayout(history_panel)
        history_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        history_layout.setSpacing(scale_px(10, self._ui_scale))
        history_header = QHBoxLayout()
        history_title = QLabel("전적 기록")
        history_title.setObjectName("sectionTitle")
        self._tactical_match_summary = QLabel("")
        self._tactical_match_summary.setObjectName("filterSummary")
        history_header.addWidget(history_title)
        history_header.addWidget(self._tactical_match_summary, 1, Qt.AlignRight)
        history_layout.addLayout(history_header)
        self._tactical_match_search = QLineEdit()
        self._tactical_match_search.setPlaceholderText("상대 이름, 학생, 메모 검색")
        self._tactical_match_search.textChanged.connect(lambda *_: self._reset_tactical_match_list())
        history_layout.addWidget(self._tactical_match_search)
        self._tactical_match_list = QListWidget()
        self._tactical_match_list.currentItemChanged.connect(self._on_tactical_match_selected)
        history_layout.addWidget(self._tactical_match_list, 1)
        self._tactical_match_load_more_button = QPushButton("더 보기")
        self._tactical_match_load_more_button.clicked.connect(self._load_more_tactical_matches)
        history_layout.addWidget(self._tactical_match_load_more_button)
        match_action_row = QHBoxLayout()
        match_action_row.setContentsMargins(0, 0, 0, 0)
        self._tactical_match_copy_attack_button = QPushButton("ATK Copy")
        self._tactical_match_copy_attack_button.clicked.connect(self._copy_selected_tactical_match_attack)
        self._tactical_match_copy_defense_button = QPushButton("DEF Copy")
        self._tactical_match_copy_defense_button.clicked.connect(self._copy_selected_tactical_match_defense)
        self._tactical_match_delete_button = QPushButton("[삭제]")
        self._tactical_match_delete_button.clicked.connect(self._delete_selected_tactical_match)
        self._tactical_match_import_button = QPushButton("Excel Import")
        self._tactical_match_import_button.clicked.connect(self._import_tactical_spreadsheet)
        import_template_path = self._ensure_tactical_import_template()
        self._tactical_match_import_button.setToolTip(
            f"템플릿: {import_template_path}\n설명서: {tactical_import_readme_path(import_template_path)}"
        )
        match_action_row.addStretch(1)
        match_action_row.addWidget(self._tactical_match_import_button)
        match_action_row.addWidget(self._tactical_match_copy_attack_button)
        match_action_row.addWidget(self._tactical_match_copy_defense_button)
        match_action_row.addWidget(self._tactical_match_delete_button)
        history_layout.addLayout(match_action_row)
        splitter.addWidget(history_panel)

        insight_panel = QFrame()
        insight_panel.setObjectName("panel")
        insight_layout = QVBoxLayout(insight_panel)
        insight_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(14, self._ui_scale),
        )
        insight_tabs = QTabWidget()
        insight_layout.addWidget(insight_tabs, 1)

        opponent_tab = QWidget()
        opponent_layout = QVBoxLayout(opponent_tab)
        opponent_layout.setContentsMargins(0, 0, 0, 0)
        opponent_layout.setSpacing(scale_px(10, self._ui_scale))
        opponent_search_row = QHBoxLayout()
        self._tactical_opponent_search = QLineEdit()
        self._tactical_opponent_search.setPlaceholderText("상대 이름 검색")
        self._tactical_opponent_search.returnPressed.connect(self._refresh_tactical_opponent_report)
        opponent_search_button = QPushButton("검색")
        opponent_search_button.clicked.connect(self._refresh_tactical_opponent_report)
        opponent_search_row.addWidget(self._tactical_opponent_search, 1)
        opponent_search_row.addWidget(opponent_search_button)
        opponent_layout.addLayout(opponent_search_row)
        self._tactical_opponent_summary = QLabel("")
        self._tactical_opponent_summary.setObjectName("detailSub")
        self._tactical_opponent_summary.setWordWrap(True)
        opponent_layout.addWidget(self._tactical_opponent_summary)
        self._tactical_opponent_top_list = QListWidget()
        opponent_layout.addWidget(self._tactical_opponent_top_list, 1)
        insight_tabs.addTab(opponent_tab, "상대")

        jokbo_tab = QWidget()
        jokbo_layout = QVBoxLayout(jokbo_tab)
        jokbo_layout.setContentsMargins(0, 0, 0, 0)
        jokbo_layout.setSpacing(scale_px(10, self._ui_scale))
        search_group, self._tactical_jokbo_search_inputs = self._build_tactical_deck_editor("방어덱 검색")
        jokbo_layout.addWidget(search_group)
        search_buttons = QHBoxLayout()
        search_jokbo_button = QPushButton("족보 검색")
        search_jokbo_button.clicked.connect(self._refresh_tactical_jokbo_results)
        copy_search_button = QPushButton("전적 방어덱 복사")
        copy_search_button.clicked.connect(self._copy_selected_tactical_defense_to_search)
        search_buttons.addWidget(search_jokbo_button)
        search_buttons.addWidget(copy_search_button)
        jokbo_layout.addLayout(search_buttons)
        self._tactical_jokbo_results = QListWidget()
        jokbo_layout.addWidget(self._tactical_jokbo_results, 1)
        jokbo_action_row = QHBoxLayout()
        jokbo_action_row.setContentsMargins(0, 0, 0, 0)
        self._tactical_jokbo_copy_defense_button = QPushButton("DEF Copy")
        self._tactical_jokbo_copy_defense_button.clicked.connect(self._copy_selected_tactical_jokbo_defense)
        self._tactical_jokbo_copy_attack_button = QPushButton("ATK Copy")
        self._tactical_jokbo_copy_attack_button.clicked.connect(self._copy_selected_tactical_jokbo_attack)
        jokbo_action_row.addStretch(1)
        jokbo_action_row.addWidget(self._tactical_jokbo_copy_attack_button)
        jokbo_action_row.addWidget(self._tactical_jokbo_copy_defense_button)
        jokbo_layout.addLayout(jokbo_action_row)
        insight_tabs.addTab(jokbo_tab, "족보")
        splitter.addWidget(insight_panel)
        splitter.setSizes([scale_px(420, self._ui_scale), scale_px(520, self._ui_scale), scale_px(470, self._ui_scale)])

    def _build_tactical_match_input_panel(self, index: int) -> tuple[QFrame, dict]:
        panel_widget = QFrame()
        panel_widget.setObjectName("planBand")
        layout = QVBoxLayout(panel_widget)
        layout.setContentsMargins(scale_px(10, self._ui_scale), scale_px(10, self._ui_scale), scale_px(10, self._ui_scale), scale_px(10, self._ui_scale))
        layout.setSpacing(scale_px(8, self._ui_scale))

        header = QHBoxLayout()
        title = QLabel("대전 기록")
        title.setObjectName("sectionTitle")
        opponent = QLineEdit()
        opponent.setPlaceholderText("상대 이름")
        win_button = QPushButton("승")
        loss_button = QPushButton("패")
        win_button.setCheckable(True)
        loss_button.setCheckable(True)
        save_button = QPushButton("Save")
        clear_button = QPushButton("Clear")
        action_width = scale_px(72, self._ui_scale)
        for button in (win_button, loss_button, save_button, clear_button):
            button.setFixedWidth(action_width)
        header.addWidget(title)
        header.addWidget(opponent, 1)
        header.addWidget(win_button)
        header.addWidget(loss_button)
        header.addWidget(save_button)
        header.addWidget(clear_button)
        layout.addLayout(header)

        recent_row = QHBoxLayout()
        recent_row.setContentsMargins(0, 0, 0, 0)
        recent_attack_button = QPushButton("최근 공격")
        recent_defense_button = QPushButton("최근 방어")
        recent_button_width = action_width * 2 + scale_px(6, self._ui_scale)
        recent_attack_button.setFixedWidth(recent_button_width)
        recent_defense_button.setFixedWidth(recent_button_width)
        recent_attack_button.setToolTip("상대 이름으로 최근 공격 기록의 공덱/방덱을 가져옵니다.")
        recent_defense_button.setToolTip("상대 이름으로 최근 방어 기록의 공덱/방덱을 가져옵니다.")
        recent_row.addStretch(1)
        recent_row.addWidget(recent_attack_button)
        recent_row.addWidget(recent_defense_button)
        layout.addLayout(recent_row)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        attack_mode_button = QPushButton("공격 기록")
        defense_mode_button = QPushButton("방어 기록")
        jokbo_mode_button = QPushButton("족보")
        attack_mode_button.setCheckable(True)
        defense_mode_button.setCheckable(True)
        jokbo_mode_button.setCheckable(True)
        mode_hint = QLabel("공격 기록: 내 공격덱 vs 상대 방어덱 / 방어 기록: 상대 공격덱 vs 내 방어덱 / 족보: 방어덱과 공격덱 페어")
        mode_hint.setObjectName("detailSub")
        mode_hint.setWordWrap(True)
        mode_row.addWidget(attack_mode_button)
        mode_row.addWidget(defense_mode_button)
        mode_row.addWidget(jokbo_mode_button)
        mode_row.addWidget(mode_hint, 1)
        layout.addLayout(mode_row)

        attack_widget, attack_editor = self._build_tactical_deck_editor("공격덱")
        defense_widget, defense_editor = self._build_tactical_deck_editor("방어덱")
        layout.addWidget(attack_widget)
        layout.addWidget(defense_widget)

        notes = QPlainTextEdit()
        notes.setPlaceholderText("메모")
        notes.setMaximumHeight(scale_px(58, self._ui_scale))
        layout.addWidget(notes)
        status = QLabel("")
        status.setObjectName("filterSummary")
        status.setWordWrap(True)
        status.setMaximumHeight(scale_px(48, self._ui_scale))
        status.hide()
        layout.addWidget(status)

        panel = {
            "title": title,
            "opponent": opponent,
            "result": "win",
            "win_button": win_button,
            "loss_button": loss_button,
            "mode": "attack",
            "attack_mode_button": attack_mode_button,
            "defense_mode_button": defense_mode_button,
            "jokbo_mode_button": jokbo_mode_button,
            "attack": attack_editor,
            "defense": defense_editor,
            "notes": notes,
            "status": status,
        }
        win_button.clicked.connect(lambda *_args, target=panel: self._set_tactical_panel_result(target, "win"))
        loss_button.clicked.connect(lambda *_args, target=panel: self._set_tactical_panel_result(target, "loss"))
        attack_mode_button.clicked.connect(lambda *_args, target=panel: self._set_tactical_panel_mode(target, "attack"))
        defense_mode_button.clicked.connect(lambda *_args, target=panel: self._set_tactical_panel_mode(target, "defense"))
        jokbo_mode_button.clicked.connect(lambda *_args, target=panel: self._set_tactical_panel_mode(target, "jokbo"))
        save_button.clicked.connect(lambda *_args, target=panel: self._save_tactical_match_panel(target))
        clear_button.clicked.connect(lambda *_args, target=panel: self._clear_tactical_match_panel(target))
        recent_attack_button.clicked.connect(lambda *_args, target=panel: self._load_recent_tactical_match_panel(target, "attack"))
        recent_defense_button.clicked.connect(lambda *_args, target=panel: self._load_recent_tactical_match_panel(target, "defense"))
        self._set_tactical_panel_result(panel, "win")
        self._set_tactical_panel_mode(panel, "attack")
        return panel_widget, panel

    def _build_tactical_abbreviation_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("planBand")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(scale_px(10, self._ui_scale), scale_px(10, self._ui_scale), scale_px(10, self._ui_scale), scale_px(10, self._ui_scale))
        layout.setSpacing(scale_px(7, self._ui_scale))

        header = QHBoxLayout()
        title = QLabel("줄임말 설정")
        title.setObjectName("sectionTitle")
        add_striker_button = QPushButton("스트 추가")
        add_striker_button.clicked.connect(lambda *_: self._add_tactical_abbreviation_row("", "", "striker"))
        add_special_button = QPushButton("스페셜 추가")
        add_special_button.clicked.connect(lambda *_: self._add_tactical_abbreviation_row("", "", "special"))
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(add_striker_button)
        header.addWidget(add_special_button)
        layout.addLayout(header)

        hint = QLabel("스트라이커와 스페셜 줄임말은 별도 사전입니다. 같은 글자도 슬롯에 따라 따로 해석됩니다.")
        hint.setObjectName("detailSub")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._tactical_abbrev_rows: list[tuple[QLineEdit, QLineEdit, QWidget]] = []
        self._tactical_special_abbrev_rows: list[tuple[QLineEdit, QLineEdit, QWidget]] = []
        striker_label = QLabel("스트라이커")
        striker_label.setObjectName("detailSectionTitle")
        layout.addWidget(striker_label)
        self._tactical_abbrev_rows_layout = QVBoxLayout()
        self._tactical_abbrev_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._tactical_abbrev_rows_layout.setSpacing(scale_px(5, self._ui_scale))
        layout.addLayout(self._tactical_abbrev_rows_layout)

        for key, value in sorted((self._tactical_data.abbreviations or {}).items()):
            self._add_tactical_abbreviation_row(key, value, "striker")
        if not self._tactical_abbrev_rows:
            self._add_tactical_abbreviation_row("", "", "striker")

        special_label = QLabel("스페셜")
        special_label.setObjectName("detailSectionTitle")
        layout.addWidget(special_label)
        self._tactical_special_abbrev_rows_layout = QVBoxLayout()
        self._tactical_special_abbrev_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._tactical_special_abbrev_rows_layout.setSpacing(scale_px(5, self._ui_scale))
        layout.addLayout(self._tactical_special_abbrev_rows_layout)

        for key, value in sorted((self._tactical_data.special_abbreviations or {}).items()):
            self._add_tactical_abbreviation_row(key, value, "special")
        if not self._tactical_special_abbrev_rows:
            self._add_tactical_abbreviation_row("", "", "special")
        return panel

    def _add_tactical_abbreviation_row(self, key: str, value: str, role: str = "striker") -> None:
        rows_layout_name = "_tactical_special_abbrev_rows_layout" if role == "special" else "_tactical_abbrev_rows_layout"
        rows_name = "_tactical_special_abbrev_rows" if role == "special" else "_tactical_abbrev_rows"
        rows_layout = getattr(self, rows_layout_name, None)
        rows = getattr(self, rows_name, None)
        if rows_layout is None or rows is None:
            return
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(scale_px(5, self._ui_scale))
        key_input = QLineEdit(key)
        key_input.setMaxLength(1)
        key_input.setPlaceholderText("글자")
        key_input.setFixedWidth(scale_px(48, self._ui_scale))
        student_input = QLineEdit(value)
        student_input.setPlaceholderText("스페셜 학생" if role == "special" else "스트라이커 학생")
        remove_button = QPushButton("[삭제]")
        row_layout.addWidget(key_input)
        row_layout.addWidget(student_input, 1)
        row_layout.addWidget(remove_button)
        rows_layout.addWidget(row)
        rows.append((key_input, student_input, row))
        key_input.editingFinished.connect(self._save_tactical_abbreviations)
        student_input.editingFinished.connect(self._save_tactical_abbreviations)
        remove_button.clicked.connect(lambda *_args, target=row, target_role=role: self._remove_tactical_abbreviation_row(target, target_role))

    def _remove_tactical_abbreviation_row(self, row: QWidget, role: str = "striker") -> None:
        rows_name = "_tactical_special_abbrev_rows" if role == "special" else "_tactical_abbrev_rows"
        rows = getattr(self, rows_name, [])
        setattr(self, rows_name, [entry for entry in rows if entry[2] is not row])
        row.setParent(None)
        row.deleteLater()
        self._save_tactical_abbreviations()

    def _set_tactical_panel_mode(self, panel: dict, mode: str) -> None:
        panel["mode"] = mode if mode in {"attack", "defense", "jokbo"} else "attack"
        if "title" in panel:
            panel["title"].setText("족보 모드" if panel["mode"] == "jokbo" else "대전 기록")
        panel["attack_mode_button"].setChecked(panel["mode"] == "attack")
        panel["defense_mode_button"].setChecked(panel["mode"] == "defense")
        panel["jokbo_mode_button"].setChecked(panel["mode"] == "jokbo")
        selected_style = f"background: {ACCENT_STRONG}; color: #ffffff; border: 2px solid #ffffff; font-weight: 900;"
        idle_style = f"background: {SURFACE_ALT}; color: {INK}; border: 1px solid {BORDER}; font-weight: 700;"
        panel["attack_mode_button"].setStyleSheet(selected_style if panel["mode"] == "attack" else idle_style)
        panel["defense_mode_button"].setStyleSheet(selected_style if panel["mode"] == "defense" else idle_style)
        panel["jokbo_mode_button"].setStyleSheet(selected_style if panel["mode"] == "jokbo" else idle_style)
        opponent_input = panel.get("opponent")
        if opponent_input is not None:
            is_jokbo = panel["mode"] == "jokbo"
            opponent_input.setEnabled(not is_jokbo)
            opponent_input.setPlaceholderText("족보 모드에서는 상대 이름 미사용" if is_jokbo else "상대 이름")

    def _set_tactical_panel_result(self, panel: dict, result: str) -> None:
        panel["result"] = "loss" if result == "loss" else "win"
        panel["win_button"].setChecked(panel["result"] == "win")
        panel["loss_button"].setChecked(panel["result"] == "loss")
        panel["win_button"].setText("승")
        panel["loss_button"].setText("패")
        selected_style = f"background: {ACCENT_STRONG}; color: #ffffff; border: 2px solid #ffffff; font-weight: 900;"
        idle_style = f"background: {SURFACE_ALT}; color: {INK}; border: 1px solid {BORDER}; font-weight: 700;"
        panel["win_button"].setStyleSheet(selected_style if panel["result"] == "win" else idle_style)
        panel["loss_button"].setStyleSheet(selected_style if panel["result"] == "loss" else idle_style)

    def _tactical_import_key(self, value: object) -> str:
        return re.sub(r"[\s_\-./()]+", "", str(value or "").strip().casefold())

    def _tactical_import_template_path(self) -> Path:
        return get_storage_paths().current_dir / "tactical_challenge_import_template.xlsx"

    def _ensure_tactical_import_template(self) -> Path:
        path = self._tactical_import_template_path()
        ensure_tactical_import_template(path)
        return path

    def _tactical_import_value(self, row: dict[str, str], *aliases: str) -> str:
        for alias in aliases:
            value = row.get(self._tactical_import_key(alias), "")
            if str(value or "").strip():
                return str(value).strip()
        return ""

    def _tactical_import_deck_value(
        self,
        row: dict[str, str],
        single_aliases: tuple[str, ...],
        slot_aliases: tuple[str, ...],
    ) -> str:
        single_value = self._tactical_import_value(row, *single_aliases)
        if single_value:
            return single_value

        def _slot(index: int) -> str:
            aliases: list[str] = []
            for alias in slot_aliases:
                aliases.extend(
                    [
                        f"{alias}{index}",
                        f"{alias}S{index}",
                        f"{alias}스트{index}",
                        f"{alias}스트라이커{index}",
                    ]
                )
            return self._tactical_import_value(row, *aliases)

        def _support(index: int) -> str:
            aliases: list[str] = []
            for alias in slot_aliases:
                aliases.extend(
                    [
                        f"{alias}SP{index}",
                        f"{alias}Special{index}",
                        f"{alias}스페셜{index}",
                        f"{alias}서포터{index}",
                        f"{alias}지원{index}",
                    ]
                )
            return self._tactical_import_value(row, *aliases)

        strikers = [_slot(index) for index in range(1, TACTICAL_STRIKER_SLOTS + 1)]
        supports = [_support(index) for index in range(1, TACTICAL_SUPPORT_SLOTS + 1)]
        if not any(strikers) and not any(supports):
            return ""
        return f"{','.join(strikers)}|{','.join(supports)}"

    def _normalize_tactical_import_date(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if re.fullmatch(r"\d{8}", text):
            return date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
        if re.fullmatch(r"\d+(\.0+)?", text):
            serial = int(float(text))
            if 20000 <= serial <= 80000:
                return (date(1899, 12, 30) + timedelta(days=serial)).isoformat()
        normalized = re.sub(r"[./]", "-", text)
        return date.fromisoformat(normalized[:10]).isoformat()

    def _normalize_tactical_import_result(self, value: str) -> str:
        key = self._tactical_import_key(value)
        if key in {"승", "win", "w", "1", "true", "o"}:
            return "win"
        if key in {"패", "loss", "lose", "l", "0", "false", "x"}:
            return "loss"
        return ""

    def _normalize_tactical_import_mode(self, value: str) -> str:
        key = self._tactical_import_key(value)
        if "족보" in key or "jokbo" in key:
            return "jokbo"
        if "방어" in key or "defense" in key or key == "def":
            return "defense"
        return "attack"

    def _canonical_import_deck(self, row_number: int, deck_text: str, label: str, errors: list[str]) -> TacticalDeck:
        deck = self._parse_tactical_deck_template(deck_text)
        canonical, error = self._canonical_tactical_deck_or_error(deck, label)
        if error:
            errors.append(f"{row_number}행: {error}")
        return canonical

    def _failed_tactical_import_row(self, raw_row: dict[str, str], error: str) -> dict[str, str]:
        failed = {str(key): str(value or "").strip() for key, value in raw_row.items()}
        failed["오류"] = error
        return failed

    def _build_tactical_import_entries(self, rows: list[dict[str, str]]) -> tuple[list[TacticalMatch], list[TacticalJokboEntry], list[str], list[dict[str, str]]]:
        matches: list[TacticalMatch] = []
        jokbo_entries: list[TacticalJokboEntry] = []
        errors: list[str] = []
        failed_rows: list[dict[str, str]] = []
        now = datetime.now().isoformat(timespec="seconds")

        for index, raw_row in enumerate(rows, start=2):
            row = {self._tactical_import_key(key): str(value or "").strip() for key, value in raw_row.items()}

            def reject(message: str) -> None:
                errors.append(message)
                failed_rows.append(self._failed_tactical_import_row(raw_row, message))

            mode = self._normalize_tactical_import_mode(
                self._tactical_import_value(row, "mode", "type", "구분", "종류", "기록종류", "기록")
            )
            generic_attack = self._tactical_import_deck_value(
                row,
                ("attack", "atk", "공격덱", "공덱"),
                ("attack", "atk", "공격", "공"),
            )
            generic_defense = self._tactical_import_deck_value(
                row,
                ("defense", "def", "방어덱", "방덱"),
                ("defense", "def", "방어", "방"),
            )
            notes = self._tactical_import_value(row, "notes", "note", "memo", "메모", "비고")
            source = self._tactical_import_value(row, "source", "출처", "데이터출처", "source_type") or "내 기록"
            row_id = self._tactical_import_value(row, "id", "match_id", "고유값")

            if mode == "jokbo":
                defense_text = self._tactical_import_deck_value(
                    row,
                    ("jokbo_defense", "족보방어덱", "방어덱", "방덱"),
                    ("jokbo_defense", "jokbodef", "족보방어", "방어", "방"),
                ) or generic_defense
                attack_text = self._tactical_import_deck_value(
                    row,
                    ("jokbo_attack", "족보공격덱", "공격덱", "공덱"),
                    ("jokbo_attack", "jokboatk", "족보공격", "공격", "공"),
                ) or generic_attack
                if not defense_text or not attack_text:
                    reject(f"{index}행: 족보는 공격덱과 방어덱이 모두 필요합니다.")
                    continue
                jokbo_errors_before = len(errors)
                defense = self._canonical_import_deck(index, defense_text, "족보 방어덱", errors)
                attack = self._canonical_import_deck(index, attack_text, "족보 공격덱", errors)
                if len(errors) != jokbo_errors_before:
                    failed_rows.append(self._failed_tactical_import_row(raw_row, "\n".join(errors[jokbo_errors_before:])))
                    continue
                jokbo_entries.append(
                    TacticalJokboEntry(
                        id=row_id or f"import-jokbo-{datetime.now().strftime('%Y%m%d%H%M%S')}-{index}-{uuid4().hex[:6]}",
                        defense=defense,
                        attack=attack,
                        notes=notes,
                        updated_at=now,
                    )
                )
                continue

            date_text = self._tactical_import_value(row, "date", "날짜", "일자")
            opponent = self._tactical_import_value(row, "opponent", "상대", "상대이름", "name", "이름")
            result_text = self._tactical_import_value(row, "result", "승패", "결과", "winloss")
            result = self._normalize_tactical_import_result(result_text) if result_text else "loss"
            if not opponent and source != "내 기록":
                opponent = "미상"
            if not opponent:
                reject(f"{index}행: 상대 이름이 필요합니다.")
                continue
            if result_text and not result:
                reject(f"{index}행: 승패는 승/패 또는 win/loss로 입력해 주세요.")
                continue
            if date_text:
                try:
                    match_date = self._normalize_tactical_import_date(date_text)
                except Exception:
                    reject(f"{index}행: 날짜 '{date_text}'를 인식할 수 없습니다.")
                    continue
            else:
                match_date = ""

            my_attack_text = self._tactical_import_deck_value(
                row,
                ("my_attack", "my atk", "내공격덱", "내공덱"),
                ("my_attack", "myatk", "내공격", "내공"),
            )
            opponent_defense_text = self._tactical_import_deck_value(
                row,
                ("opponent_defense", "op def", "상대방어덱", "상대방덱"),
                ("opponent_defense", "opdef", "상대방어", "상대방"),
            )
            my_defense_text = self._tactical_import_deck_value(
                row,
                ("my_defense", "my def", "내방어덱", "내방덱"),
                ("my_defense", "mydef", "내방어", "내방"),
            )
            opponent_attack_text = self._tactical_import_deck_value(
                row,
                ("opponent_attack", "op atk", "상대공격덱", "상대공덱"),
                ("opponent_attack", "opatk", "상대공격", "상대공"),
            )
            if mode == "defense":
                my_defense_text = my_defense_text or generic_defense
                opponent_attack_text = opponent_attack_text or generic_attack
            else:
                my_attack_text = my_attack_text or generic_attack
                opponent_defense_text = opponent_defense_text or generic_defense

            if not any((my_attack_text, opponent_defense_text, my_defense_text, opponent_attack_text)):
                reject(f"{index}행: 덱 정보가 필요합니다.")
                continue

            match_errors_before = len(errors)
            my_attack = self._canonical_import_deck(index, my_attack_text, "내 공격덱", errors) if my_attack_text else TacticalDeck()
            opponent_defense = self._canonical_import_deck(index, opponent_defense_text, "상대 방어덱", errors) if opponent_defense_text else TacticalDeck()
            my_defense = self._canonical_import_deck(index, my_defense_text, "내 방어덱", errors) if my_defense_text else TacticalDeck()
            opponent_attack = self._canonical_import_deck(index, opponent_attack_text, "상대 공격덱", errors) if opponent_attack_text else TacticalDeck()
            if len(errors) != match_errors_before:
                failed_rows.append(self._failed_tactical_import_row(raw_row, "\n".join(errors[match_errors_before:])))
                continue

            matches.append(
                TacticalMatch(
                    id=row_id or f"import-tc-{datetime.now().strftime('%Y%m%d%H%M%S')}-{index}-{uuid4().hex[:6]}",
                    date=match_date,
                    season=self._tactical_import_value(row, "season", "시즌") or self._tactical_data.season,
                    opponent=opponent,
                    result=result,
                    my_attack=my_attack,
                    opponent_defense=opponent_defense,
                    my_defense=my_defense,
                    opponent_attack=opponent_attack,
                    source=source,
                    notes=notes,
                    created_at=now,
                )
            )

        return matches, jokbo_entries, errors, failed_rows

    def _import_tactical_spreadsheet(self) -> None:
        template_path = self._ensure_tactical_import_template()
        self._show_busy_overlay("가져오는 중...")
        try:
            rows = read_tactical_import_rows(template_path)
            if not rows:
                self._set_tactical_status(f"템플릿에 가져올 행이 없습니다.\n{template_path}", error=True)
                return
            matches, jokbo_entries, errors, failed_rows = self._build_tactical_import_entries(rows)
            if not matches and not jokbo_entries and errors:
                write_tactical_import_rows(template_path, failed_rows)
                preview = "\n".join(errors[:12])
                suffix = f"\n...외 {len(errors) - 12}개 오류" if len(errors) > 12 else ""
                self._set_tactical_status(
                    "가져올 수 있는 행이 없습니다. 문제가 있는 행만 템플릿에 남겼습니다.\n" + preview + suffix,
                    error=True,
                )
                return
            upsert_tactical_matches(self._tactical_path, matches)
            upsert_tactical_jokbo_entries(self._tactical_path, jokbo_entries)
            self._storage_mtimes = self._snapshot_storage_mtimes()
            self._tactical_match_loaded_count = max(self._tactical_match_loaded_count, self._tactical_match_page_size)
            self._refresh_tactical_match_list()
            self._refresh_tactical_jokbo_results()
            if failed_rows:
                write_tactical_import_rows(template_path, failed_rows)
                preview = "\n".join(errors[:8])
                suffix = f"\n...외 {len(errors) - 8}개 오류" if len(errors) > 8 else ""
                self._set_tactical_status(
                    f"정상 행은 가져왔습니다. 전적 {len(matches)}개, 족보 {len(jokbo_entries)}개\n"
                    f"문제가 있는 행 {len(failed_rows)}개는 템플릿에 남겼습니다. 확인이 필요합니다.\n"
                    f"{preview}{suffix}",
                    error=True,
                )
            else:
                clear_tactical_import_template(template_path)
                self._set_tactical_status(
                    f"템플릿 데이터를 가져왔습니다. 전적 {len(matches)}개, 족보 {len(jokbo_entries)}개\n"
                    f"템플릿을 비웠습니다: {template_path}"
                )
        except Exception as exc:
            self._set_tactical_status(f"가져오기 실패: {exc}", error=True)
        finally:
            self._hide_busy_overlay()

    def _save_tactical_match_panel(self, panel: dict) -> None:
        if not self._save_tactical_abbreviations():
            return
        season = self._tactical_season.text().strip()
        if self._tactical_data.season != season:
            self._tactical_data.season = season
            self._save_tactical_metadata()
        now = datetime.now().isoformat(timespec="seconds")
        attack_deck = self._deck_from_tactical_inputs(panel["attack"])
        defense_deck = self._deck_from_tactical_inputs(panel["defense"])
        attack_deck, attack_error = self._canonical_tactical_deck_or_error(attack_deck, "공격덱")
        defense_deck, defense_error = self._canonical_tactical_deck_or_error(defense_deck, "방어덱")
        if attack_error or defense_error:
            self._set_tactical_status("\n".join(error for error in (attack_error, defense_error) if error), error=True, panel=panel)
            return
        self._set_tactical_deck_inputs(panel["attack"], attack_deck)
        self._set_tactical_deck_inputs(panel["defense"], defense_deck)
        if panel.get("mode") == "jokbo":
            if not any(defense_deck.strikers) and not any(defense_deck.supports):
                self._set_tactical_status("족보의 방어덱을 입력해 주세요.", error=True, panel=panel)
                return
            if not any(attack_deck.strikers) and not any(attack_deck.supports):
                self._set_tactical_status("족보의 공격덱을 입력해 주세요.", error=True, panel=panel)
                return
            entry = TacticalJokboEntry(
                id=f"jokbo-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
                defense=defense_deck,
                attack=attack_deck,
                wins=0,
                losses=0,
                notes=panel["notes"].toPlainText().strip(),
                updated_at=now,
            )
            self._show_busy_overlay()
            try:
                self._tactical_data.jokbo.append(entry)
                upsert_tactical_jokbo(self._tactical_path, entry)
                self._storage_mtimes = self._snapshot_storage_mtimes()
                if hasattr(self, "_tactical_jokbo_search_inputs"):
                    self._set_tactical_deck_inputs(self._tactical_jokbo_search_inputs, defense_deck)
                self._refresh_tactical_jokbo_results()
            finally:
                self._hide_busy_overlay()
            self._set_tactical_status("족보를 저장했습니다.", panel=panel)
            return

        opponent = panel["opponent"].text().strip()
        if not opponent:
            self._set_tactical_status("상대 이름을 입력해 주세요.", error=True, panel=panel)
            return
        is_defense_record = panel.get("mode") == "defense"
        match = TacticalMatch(
            id=f"tc-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}",
            date=self._tactical_date.text().strip(),
            season=season,
            opponent=opponent,
            result=str(panel["result"]),
            my_attack=TacticalDeck() if is_defense_record else attack_deck,
            opponent_defense=TacticalDeck() if is_defense_record else defense_deck,
            my_defense=defense_deck if is_defense_record else TacticalDeck(),
            opponent_attack=attack_deck if is_defense_record else TacticalDeck(),
            source="내 기록",
            notes=panel["notes"].toPlainText().strip(),
            created_at=now,
        )
        self._tactical_selected_match_id = match.id
        self._show_busy_overlay()
        try:
            upsert_tactical_match(self._tactical_path, match)
            self._storage_mtimes = self._snapshot_storage_mtimes()
            self._tactical_match_loaded_count = max(self._tactical_match_loaded_count, self._tactical_match_page_size)
            self._refresh_tactical_match_list()
        finally:
            self._hide_busy_overlay()
        self._set_tactical_status(f"{self._tactical_date_label(match)} {opponent} 전적을 저장했습니다.", panel=panel)

    def _clear_tactical_match_panel(self, panel: dict) -> None:
        panel["opponent"].clear()
        panel["notes"].clear()
        self._set_tactical_status("", panel=panel)
        self._set_tactical_panel_result(panel, "win")
        self._set_tactical_panel_mode(panel, "attack")
        self._clear_tactical_deck_inputs(panel["attack"])
        self._clear_tactical_deck_inputs(panel["defense"])

    def _load_recent_tactical_match_panel(self, panel: dict, mode: str) -> None:
        opponent = panel["opponent"].text().strip()
        if not opponent:
            self._set_tactical_status("상대 이름을 입력해 주세요.", error=True, panel=panel)
            return
        mode = "defense" if mode == "defense" else "attack"
        self._show_busy_overlay("불러오는 중...")
        try:
            match = latest_tactical_match_for_opponent(self._tactical_path, opponent, mode)
        finally:
            self._hide_busy_overlay()
        if match is None:
            label = "방어" if mode == "defense" else "공격"
            self._set_tactical_status(f"{opponent}의 최근 {label} 기록을 찾지 못했습니다.", error=True, panel=panel)
            return
        self._set_tactical_panel_mode(panel, mode)
        self._set_tactical_panel_result(panel, match.result)
        if mode == "defense":
            self._set_tactical_deck_inputs(panel["attack"], match.opponent_attack)
            self._set_tactical_deck_inputs(panel["defense"], match.my_defense)
        else:
            self._set_tactical_deck_inputs(panel["attack"], match.my_attack)
            self._set_tactical_deck_inputs(panel["defense"], match.opponent_defense)
        label = "방어" if mode == "defense" else "공격"
        self._set_tactical_status(f"{self._tactical_date_label(match)} {opponent} 최근 {label} 기록을 가져왔습니다.", panel=panel)

    def _save_tactical_season(self) -> None:
        if self._tactical_data.season == self._tactical_season.text().strip():
            return
        self._tactical_data.season = self._tactical_season.text().strip()
        self._save_tactical_metadata()

    def _save_tactical_abbreviations(self) -> bool:
        if not hasattr(self, "_tactical_abbrev_rows"):
            return True
        errors: list[str] = []

        def _collect(rows: list[tuple[QLineEdit, QLineEdit, QWidget]], expected_class: str, label: str) -> dict[str, str]:
            mapping: dict[str, str] = {}
            for key_input, student_input, _row in rows:
                key = key_input.text().strip()
                value = student_input.text().strip()
                if not key and not value:
                    continue
                if not key or not value:
                    errors.append(f"{label} 줄임말: 글자와 학생을 모두 입력해 주세요.")
                    continue
                if len(key) != 1:
                    errors.append(f"{label} 줄임말: '{key}'는 한 글자만 사용할 수 있습니다.")
                    continue
                if key in mapping:
                    errors.append(f"{label} 줄임말: '{key}'가 중복 등록되어 있습니다.")
                    continue
                matches = self._tactical_student_ids_for_name(value)
                if not matches:
                    errors.append(f"{label} 줄임말: '{value}' 학생을 인식할 수 없습니다.")
                    continue
                if len(matches) > 1:
                    names = ", ".join(self._tactical_student_display_name(student_id) for student_id in matches[:6])
                    suffix = "..." if len(matches) > 6 else ""
                    errors.append(f"{label} 줄임말: '{value}' 중복 태그입니다. ({names}{suffix})")
                    continue
                student_id = matches[0]
                if student_meta.combat_class(student_id) != expected_class:
                    errors.append(f"{label} 줄임말: '{self._tactical_student_display_name(student_id)}'는 {label} 학생이 아닙니다.")
                    continue
                mapping[key] = self._tactical_student_display_name(student_id)
                student_input.setText(mapping[key])
            return mapping

        striker_mapping = _collect(self._tactical_abbrev_rows, "striker", "스트라이커")
        special_mapping = _collect(getattr(self, "_tactical_special_abbrev_rows", []), "special", "스페셜")
        if errors:
            self._set_tactical_status("\n".join(errors), error=True)
            return False
        if (
            striker_mapping == self._tactical_data.abbreviations
            and special_mapping == self._tactical_data.special_abbreviations
        ):
            return True
        self._tactical_data.abbreviations = striker_mapping
        self._tactical_data.special_abbreviations = special_mapping
        self._save_tactical_metadata()
        return True

    def _compact_tactical_message(self, text: str, *, max_lines: int = 2, max_chars: int = 150) -> str:
        full_text = str(text or "").strip()
        if not full_text:
            return ""
        lines = [line.strip() for line in full_text.splitlines() if line.strip()]
        if len(lines) > max_lines:
            visible = lines[:max_lines]
            visible.append(f"...외 {len(lines) - max_lines}개")
            return "\n".join(visible)
        compact = "\n".join(lines) if lines else full_text
        if len(compact) > max_chars:
            return compact[: max(0, max_chars - 3)].rstrip() + "..."
        return compact

    def _set_tactical_status(self, text: str, *, error: bool = False, panel: dict | None = None) -> None:
        target = panel.get("status") if panel is not None else None
        if target is None and getattr(self, "_tactical_match_panels", None):
            target = self._tactical_match_panels[0].get("status")
        if target is None and hasattr(self, "_tactical_status"):
            target = self._tactical_status
        if target is None:
            return
        full_text = str(text or "").strip()
        compact_text = self._compact_tactical_message(full_text)
        target.setStyleSheet("color: #ff6b6b; font-weight: 800;" if error else "")
        target.setText(compact_text)
        target.setToolTip(full_text if full_text and full_text != compact_text else "")
        target.setVisible(bool(full_text))

    def _tactical_lookup_key(self, value: object) -> str:
        cleaned = " ".join(str(value or "").strip().split())
        cleaned = re.sub(r"\s*([()])\s*", r"\1", cleaned)
        return cleaned.casefold()

    def _tactical_abbreviation_map(self, role: str = "striker") -> dict[str, str]:
        rows_name = "_tactical_special_abbrev_rows" if role == "special" else "_tactical_abbrev_rows"
        data = self._tactical_data.special_abbreviations if role == "special" else self._tactical_data.abbreviations
        if hasattr(self, rows_name):
            mapping: dict[str, str] = {}
            for key_input, student_input, _row in getattr(self, rows_name):
                key = key_input.text().strip()
                value = student_input.text().strip()
                if len(key) == 1 and value:
                    mapping[key] = value
            return mapping
        return dict(data or {})

    def _parse_tactical_deck_template(self, value: str) -> TacticalDeck:
        raw = str(value or "").strip()
        if not raw:
            return TacticalDeck()
        striker_abbreviations = self._tactical_abbreviation_map("striker")
        special_abbreviations = self._tactical_abbreviation_map("special")
        if "|" in raw:
            striker_raw, support_raw = raw.split("|", 1)
        else:
            striker_raw, support_raw = raw, ""

        compact_striker = "".join(striker_raw.split())
        compact_support = "".join(support_raw.split())
        has_striker_separator = any(separator in striker_raw for separator in ",/;")
        has_support_separator = any(separator in support_raw for separator in ",/;")
        exact_striker = self._tactical_student_ids_for_name(compact_striker)
        exact_support = self._tactical_student_ids_for_name(compact_support)
        compact_strikers = (
            compact_striker
            and not exact_striker
            and not has_striker_separator
            and 1 < len(compact_striker) <= TACTICAL_STRIKER_SLOTS
            and all(char in striker_abbreviations for char in compact_striker)
        )
        compact_supports = (
            compact_support
            and not exact_support
            and not has_support_separator
            and 1 < len(compact_support) <= TACTICAL_SUPPORT_SLOTS
            and all(char in special_abbreviations for char in compact_support)
        )
        deck = parse_deck_template(raw)
        deck.strikers = (
            [striker_abbreviations[char] for char in compact_striker]
            if compact_strikers
            else [striker_abbreviations.get(name, name) if len(name) == 1 else name for name in deck.strikers]
        )
        deck.supports = (
            [special_abbreviations[char] for char in compact_support]
            if compact_supports
            else [special_abbreviations.get(name, name) if len(name) == 1 else name for name in deck.supports]
        )
        return deck

    def _tactical_student_ids_for_name(self, name: str) -> list[str]:
        needle = self._tactical_lookup_key(name)
        if not needle:
            return []
        index = self._tactical_student_lookup_index_map()
        return list(index.get(needle, []))

    def _tactical_student_lookup_index_map(self) -> dict[str, list[str]]:
        cached = getattr(self, "_tactical_student_lookup_index", None)
        if cached is not None:
            return cached
        index: dict[str, set[str]] = defaultdict(set)

        for student_id in student_meta.all_ids():
            record = self._records_by_id.get(student_id)
            terms: list[object] = [
                student_id,
                student_id.replace("_", " "),
                student_meta.display_name(student_id),
                record.title if record is not None else "",
                record.display_name if record is not None else "",
            ]
            terms.extend(student_meta.search_tags(student_id))
            terms.extend(student_meta.kr_search_tags(student_id))
            for term in terms:
                key = self._tactical_lookup_key(term)
                if key:
                    index[key].add(student_id)
        built = {
            key: sorted(values, key=lambda student_id: student_meta.display_name(student_id).casefold())
            for key, values in index.items()
        }
        self._tactical_student_lookup_index = built
        return built

    def _tactical_student_display_name(self, student_id: str) -> str:
        record = self._records_by_id.get(student_id)
        return record.title if record is not None else student_meta.display_name(student_id)

    def _canonical_tactical_deck_or_error(self, deck: TacticalDeck, label: str) -> tuple[TacticalDeck, str]:
        errors: list[str] = []

        def _is_empty_token(value: str) -> bool:
            key = self._tactical_import_key(value)
            return key in {"", "-", "?", "unknown", "none", "null", "na", "n/a", "알수없음", "미상"}

        def _resolve_slots(values: list[str], prefix: str, expected_class: str, expected_label: str) -> list[str]:
            resolved: list[str] = []
            for index, raw_name in enumerate(values, start=1):
                raw_name = str(raw_name or "").strip()
                if _is_empty_token(raw_name):
                    resolved.append("")
                    continue
                matches = self._tactical_student_ids_for_name(raw_name)
                if not matches:
                    errors.append(f"{label} {prefix}{index}: '{raw_name}' 학생을 인식할 수 없어 저장할 수 없습니다.")
                    resolved.append(raw_name)
                elif len(matches) > 1:
                    names = ", ".join(self._tactical_student_display_name(student_id) for student_id in matches[:6])
                    suffix = "..." if len(matches) > 6 else ""
                    errors.append(f"{label} {prefix}{index}: '{raw_name}' 중복 태그입니다. ({names}{suffix})")
                    resolved.append(raw_name)
                else:
                    student_id = matches[0]
                    if student_meta.combat_class(student_id) != expected_class:
                        errors.append(f"{label} {prefix}{index}: '{self._tactical_student_display_name(student_id)}'는 {expected_label} 자리에 배치할 수 없습니다.")
                    resolved.append(self._tactical_student_display_name(student_id))
            return resolved

        canonical = TacticalDeck(
            strikers=_resolve_slots(deck.strikers[:TACTICAL_STRIKER_SLOTS], "S", "striker", "스트라이커"),
            supports=_resolve_slots(deck.supports[:TACTICAL_SUPPORT_SLOTS], "SP", "special", "스페셜"),
        )
        return canonical, "\n".join(errors)

    def _canonical_tactical_search_deck_or_error(self, deck: TacticalDeck, label: str) -> tuple[TacticalDeck, str]:
        errors: list[str] = []

        def _resolve_slots(values: list[str], prefix: str, expected_class: str, expected_label: str) -> list[str]:
            resolved: list[str] = []
            for index, raw_name in enumerate(values, start=1):
                raw_name = str(raw_name or "").strip()
                if not raw_name:
                    resolved.append("")
                    continue
                if raw_name == "*":
                    resolved.append("*")
                    continue
                matches = self._tactical_student_ids_for_name(raw_name)
                if not matches:
                    errors.append(f"{label} {prefix}{index}: '{raw_name}' 학생을 인식할 수 없습니다.")
                    resolved.append(raw_name)
                elif len(matches) > 1:
                    names = ", ".join(self._tactical_student_display_name(student_id) for student_id in matches[:6])
                    suffix = "..." if len(matches) > 6 else ""
                    errors.append(f"{label} {prefix}{index}: '{raw_name}' 중복 태그입니다. ({names}{suffix})")
                    resolved.append(raw_name)
                else:
                    student_id = matches[0]
                    if student_meta.combat_class(student_id) != expected_class:
                        errors.append(f"{label} {prefix}{index}: '{self._tactical_student_display_name(student_id)}'는 {expected_label} 자리에 배치할 수 없습니다.")
                    resolved.append(self._tactical_student_display_name(student_id))
            return resolved

        canonical = TacticalDeck(
            strikers=_resolve_slots(deck.strikers[:TACTICAL_STRIKER_SLOTS], "S", "striker", "스트라이커"),
            supports=_resolve_slots(deck.supports[:TACTICAL_SUPPORT_SLOTS], "SP", "special", "스페셜"),
        )
        return canonical, "\n".join(errors)

    def _tactical_student_id_for_name(self, name: str) -> str | None:
        matches = self._tactical_student_ids_for_name(name)
        return matches[0] if len(matches) == 1 else None

    def _tactical_portrait_pixmap(self, name: str, size: int) -> QPixmap:
        student_id = self._tactical_student_id_for_name(name)
        if not student_id:
            return QPixmap()
        source = ensure_thumbnail(student_id, size, size)
        if source is None or not source.exists():
            return QPixmap()
        pixmap = QPixmap(str(source))
        return pixmap if not pixmap.isNull() else QPixmap()

    def _build_tactical_deck_editor(self, title: str) -> tuple[QWidget, TacticalDeckEditor]:
        editor = TacticalDeckEditor(
            title,
            card_asset=self._student_card_asset,
            ui_scale=self._ui_scale,
            icon_provider=self._tactical_portrait_pixmap,
            deck_parser=self._parse_tactical_deck_template,
        )
        return editor, editor

    def _deck_from_tactical_inputs(self, inputs) -> TacticalDeck:
        if isinstance(inputs, TacticalDeckEditor):
            return inputs.deck()
        return TacticalDeck(
            strikers=[edit.text().strip() for edit in inputs.get("strikers", []) if edit.text().strip()],
            supports=[edit.text().strip() for edit in inputs.get("supports", []) if edit.text().strip()],
        )

    def _set_tactical_deck_inputs(self, inputs, deck: TacticalDeck) -> None:
        if isinstance(inputs, TacticalDeckEditor):
            inputs.setDeck(deck)
            return
        for edits, values in ((inputs.get("strikers", []), deck.strikers), (inputs.get("supports", []), deck.supports)):
            for index, edit in enumerate(edits):
                edit.setText(values[index] if index < len(values) else "")

    def _clear_tactical_deck_inputs(self, inputs) -> None:
        if isinstance(inputs, TacticalDeckEditor):
            inputs.clearDeck()
            return
        for edit in inputs.get("strikers", []) + inputs.get("supports", []):
            edit.clear()

    def _save_tactical_data(self) -> None:
        self._show_busy_overlay()
        try:
            save_tactical_challenge(self._tactical_path, self._tactical_data, sync_matches=False)
            self._storage_mtimes = self._snapshot_storage_mtimes()
        finally:
            self._hide_busy_overlay()

    def _save_tactical_metadata(self) -> None:
        self._show_busy_overlay()
        try:
            save_tactical_metadata(
                self._tactical_path,
                season=self._tactical_data.season,
                abbreviations=self._tactical_data.abbreviations,
                special_abbreviations=self._tactical_data.special_abbreviations,
            )
            self._storage_mtimes = self._snapshot_storage_mtimes()
        finally:
            self._hide_busy_overlay()

    def _save_tactical_match(self) -> None:
        if self._tactical_match_panels:
            self._save_tactical_match_panel(self._tactical_match_panels[0])

    def _save_tactical_jokbo(self) -> None:
        if not self._tactical_match_panels:
            return
        panel = self._tactical_match_panels[0]
        self._set_tactical_panel_mode(panel, "jokbo")
        self._save_tactical_match_panel(panel)

    def _clear_tactical_match_form(self) -> None:
        for panel in self._tactical_match_panels:
            self._clear_tactical_match_panel(panel)

    def _copy_tactical_match_defense_to_jokbo(self) -> None:
        deck = TacticalDeck()
        for panel in self._tactical_match_panels:
            candidate = self._deck_from_tactical_inputs(panel["defense"])
            if candidate.strikers or candidate.supports:
                deck = candidate
                break
        if self._tactical_match_panels:
            self._set_tactical_deck_inputs(self._tactical_match_panels[0]["defense"], deck)
        self._set_tactical_deck_inputs(self._tactical_jokbo_search_inputs, deck)

    def _selected_tactical_match(self) -> TacticalMatch | None:
        selected_id = self._tactical_selected_match_id
        if not selected_id and hasattr(self, "_tactical_match_list"):
            item = self._tactical_match_list.currentItem()
            selected_id = str(item.data(Qt.UserRole) or "") if item is not None else ""
        if not selected_id:
            return None
        return get_tactical_match(self._tactical_path, selected_id)

    def _tactical_date_label(self, match: TacticalMatch) -> str:
        return match.date or "날짜 없음"

    def _copy_selected_tactical_defense_to_search(self) -> None:
        match = self._selected_tactical_match()
        if match is None:
            return
        deck = match.opponent_defense if (match.opponent_defense.strikers or match.opponent_defense.supports) else match.my_defense
        self._set_tactical_deck_inputs(self._tactical_jokbo_search_inputs, deck)
        self._refresh_tactical_jokbo_results()

    def _refresh_tactical_tab(self) -> None:
        if not hasattr(self, "_tactical_match_list"):
            return
        if hasattr(self, "_tactical_season") and not self._tactical_season.hasFocus():
            previous = self._tactical_season.blockSignals(True)
            try:
                self._tactical_season.setText(self._tactical_data.season or "")
            finally:
                self._tactical_season.blockSignals(previous)
        self._refresh_tactical_match_list()
        self._refresh_tactical_opponent_report()
        self._refresh_tactical_jokbo_results()

    def _reset_tactical_match_list(self) -> None:
        self._tactical_match_loaded_count = self._tactical_match_page_size
        self._refresh_tactical_match_list()

    def _load_more_tactical_matches(self) -> None:
        self._show_busy_overlay("불러오는 중...")
        try:
            self._tactical_match_loaded_count += self._tactical_match_page_size
            self._refresh_tactical_match_list()
        finally:
            self._hide_busy_overlay()

    def _refresh_tactical_match_list(self) -> None:
        query = self._tactical_match_search.text() if hasattr(self, "_tactical_match_search") else ""
        if query != self._tactical_match_query:
            self._tactical_match_query = query
            self._tactical_match_loaded_count = self._tactical_match_page_size
        total_filtered = tactical_match_count(self._tactical_path, query)
        matches = query_tactical_matches(self._tactical_path, query, limit=self._tactical_match_loaded_count)
        current_id = self._tactical_selected_match_id
        self._tactical_match_list.blockSignals(True)
        self._tactical_match_list.clear()
        for match in matches:
            result_text = "승" if match.result == "win" else "패"
            season_text = f" · {match.season}" if match.season else ""
            source_text = f" · {match.source}" if match.source and match.source != "내 기록" else ""
            item = QListWidgetItem()
            item.setData(Qt.UserRole, match.id)
            item.setToolTip(self._tactical_match_tooltip(match))
            self._tactical_match_list.addItem(item)
            row = QFrame()
            row.setObjectName("planBand")
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(scale_px(8, self._ui_scale), scale_px(7, self._ui_scale), scale_px(8, self._ui_scale), scale_px(7, self._ui_scale))
            top_row = QHBoxLayout()
            text = QLabel(f"{self._tactical_date_label(match)}{season_text}{source_text}  [{result_text}] {match.opponent}")
            text.setWordWrap(True)
            text.setObjectName("sectionTitle")
            top_row.addWidget(text, 1)
            row_layout.addLayout(top_row)
            deck_row = QHBoxLayout()
            deck_row.setContentsMargins(0, 0, 0, 0)
            deck_row.setSpacing(scale_px(6, self._ui_scale))
            attack_deck = match.my_attack if (match.my_attack.strikers or match.my_attack.supports) else match.opponent_attack
            defense_deck = match.opponent_defense if (match.opponent_defense.strikers or match.opponent_defense.supports) else match.my_defense
            attack_label = "ATK" if (match.my_attack.strikers or match.my_attack.supports) else "OP ATK"
            defense_label = "DEF" if (match.opponent_defense.strikers or match.opponent_defense.supports) else "MY DEF"
            attack_preview = TacticalDeckPreview(card_asset=self._student_card_asset, ui_scale=self._ui_scale, icon_provider=self._tactical_portrait_pixmap, compact=True)
            attack_preview.setDeck(attack_deck)
            defense_preview = TacticalDeckPreview(card_asset=self._student_card_asset, ui_scale=self._ui_scale, icon_provider=self._tactical_portrait_pixmap, compact=True)
            defense_preview.setDeck(defense_deck)
            deck_row.addWidget(QLabel(attack_label))
            deck_row.addWidget(attack_preview)
            deck_row.addStretch(1)
            deck_row.addWidget(QLabel(defense_label))
            deck_row.addWidget(defense_preview)
            row_layout.addLayout(deck_row)
            hint = row.sizeHint()
            hint.setHeight(hint.height() + scale_px(8, self._ui_scale))
            item.setSizeHint(hint)
            self._tactical_match_list.setItemWidget(item, row)
            if current_id and match.id == current_id:
                self._tactical_match_list.setCurrentItem(item)
        self._tactical_match_list.blockSignals(False)
        summary = tactical_match_summary(self._tactical_path, self._tactical_date.text().strip())
        self._tactical_match_summary.setText(
            f"오늘 {summary['today']}/5 · 전체 {summary['wins']}승 {summary['losses']}패 · 표시 {len(matches)}/{total_filtered}"
        )
        if hasattr(self, "_tactical_match_load_more_button"):
            self._tactical_match_load_more_button.setVisible(len(matches) < total_filtered)
        self._set_tactical_match_detail(self._selected_tactical_match())

    def _delete_tactical_match(self, match_id: str) -> None:
        self._show_busy_overlay("삭제 중...")
        try:
            if not delete_tactical_match(self._tactical_path, match_id):
                return
            if self._tactical_selected_match_id == match_id:
                self._tactical_selected_match_id = None
            self._storage_mtimes = self._snapshot_storage_mtimes()
            self._refresh_tactical_match_list()
        finally:
            self._hide_busy_overlay()
        self._set_tactical_status("전적을 삭제했습니다.")

    def _selected_tactical_match_decks(self) -> tuple[TacticalDeck, TacticalDeck] | None:
        match = self._selected_tactical_match()
        if match is None:
            return None
        attack_deck = match.my_attack if (match.my_attack.strikers or match.my_attack.supports) else match.opponent_attack
        defense_deck = match.opponent_defense if (match.opponent_defense.strikers or match.opponent_defense.supports) else match.my_defense
        return attack_deck, defense_deck

    def _copy_selected_tactical_match_attack(self) -> None:
        decks = self._selected_tactical_match_decks()
        if decks is not None:
            self._copy_tactical_deck_template(decks[0])

    def _copy_selected_tactical_match_defense(self) -> None:
        decks = self._selected_tactical_match_decks()
        if decks is not None:
            self._copy_tactical_deck_template(decks[1])

    def _delete_selected_tactical_match(self) -> None:
        match = self._selected_tactical_match()
        if match is not None:
            self._delete_tactical_match(match.id)

    def _tactical_match_tooltip(self, match: TacticalMatch) -> str:
        lines = [
            f"{self._tactical_date_label(match)} {match.season} {match.opponent}".strip(),
            f"출처: {match.source or '내 기록'}",
            f"내 공격덱: {deck_label(match.my_attack)}",
            f"상대 방어덱: {deck_label(match.opponent_defense)}",
        ]
        if deck_label(match.my_defense, empty=""):
            lines.append(f"내 방어덱: {deck_label(match.my_defense)}")
        if deck_label(match.opponent_attack, empty=""):
            lines.append(f"상대 공격덱: {deck_label(match.opponent_attack)}")
        if match.notes:
            lines.append(match.notes)
        return "\n".join(lines)

    def _on_tactical_match_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._tactical_selected_match_id = str(current.data(Qt.UserRole) or "") if current is not None else None
        match = self._selected_tactical_match()
        if match is not None:
            self._tactical_opponent_search.setText(match.opponent)
            deck = match.opponent_defense if (match.opponent_defense.strikers or match.opponent_defense.supports) else match.my_defense
            self._set_tactical_deck_inputs(self._tactical_jokbo_search_inputs, deck)
        self._set_tactical_match_detail(match)
        self._refresh_tactical_opponent_report()
        self._refresh_tactical_jokbo_results()

    def _set_tactical_match_detail(self, match: TacticalMatch | None) -> None:
        if not hasattr(self, "_tactical_match_detail"):
            return
        if match is None:
            self._tactical_match_detail.setText("선택한 전적의 상세 정보가 여기에 표시됩니다.")
            return
        result_text = "승리" if match.result == "win" else "패배"
        lines = [
            f"{self._tactical_date_label(match)} · {match.season or '-'} · {match.source or '내 기록'} · {match.opponent} · {result_text}",
            f"내 공격덱: {deck_label(match.my_attack)}",
            f"상대 방어덱: {deck_label(match.opponent_defense)}",
        ]
        if deck_label(match.my_defense, empty=""):
            lines.append(f"내 방어덱: {deck_label(match.my_defense)}")
        if deck_label(match.opponent_attack, empty=""):
            lines.append(f"상대 공격덱: {deck_label(match.opponent_attack)}")
        if match.notes:
            lines.append(f"메모: {match.notes}")
        self._tactical_match_detail.setText("\n".join(lines))

    def _refresh_tactical_opponent_report(self) -> None:
        if not hasattr(self, "_tactical_opponent_summary"):
            return
        opponent = self._tactical_opponent_search.text().strip()
        if not opponent:
            match = self._selected_tactical_match()
            opponent = match.opponent if match is not None else ""
        if not opponent:
            self._tactical_opponent_summary.setText("상대를 검색하거나 전적을 선택하면 상대전적과 최근 방어덱이 표시됩니다.")
            self._tactical_opponent_top_list.clear()
            return
        report = opponent_report_from_storage(self._tactical_path, opponent)
        total = len(report["matches"])
        self._tactical_opponent_top_list.clear()
        if total == 0:
            self._tactical_opponent_summary.setText(f"{opponent}: 기록이 없습니다.")
            return
        self._tactical_opponent_summary.setText(
            f"{opponent}: {report['wins']}승 {report['losses']}패 ({report['win_rate']:.1f}%)"
        )
        if deck_label(report["recent_defense"], empty=""):
            self._add_tactical_opponent_deck_row(
                title="최근 방어덱",
                defense=report["recent_defense"],
                attack=report["recent_attack"],
            )
        for index, entry in enumerate(report["top_defenses"], start=1):
            self._add_tactical_opponent_deck_row(
                title=f"TOP {index} · {entry['count']}회 · {entry['wins']}승 {entry['losses']}패 ({entry['win_rate']:.1f}%)",
                defense=entry["deck"],
                attack=entry["attack"],
            )
        if not report["top_defenses"]:
            self._tactical_opponent_top_list.addItem("방어덱 정보가 있는 전적이 없습니다.")

    def _add_tactical_opponent_deck_row(self, *, title: str, defense: TacticalDeck, attack: TacticalDeck) -> None:
        item = QListWidgetItem()
        item.setToolTip(f"공격: {deck_label(attack)}\n방어: {deck_label(defense)}")
        row = QFrame()
        row.setObjectName("planBand")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(scale_px(8, self._ui_scale), scale_px(7, self._ui_scale), scale_px(8, self._ui_scale), scale_px(7, self._ui_scale))
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        label.setWordWrap(True)
        layout.addWidget(label)
        deck_row = QHBoxLayout()
        deck_row.setContentsMargins(0, 0, 0, 0)
        deck_row.setSpacing(scale_px(6, self._ui_scale))
        attack_preview = TacticalDeckPreview(card_asset=self._student_card_asset, ui_scale=self._ui_scale, icon_provider=self._tactical_portrait_pixmap, compact=True)
        attack_preview.setDeck(attack)
        defense_preview = TacticalDeckPreview(card_asset=self._student_card_asset, ui_scale=self._ui_scale, icon_provider=self._tactical_portrait_pixmap, compact=True)
        defense_preview.setDeck(defense)
        deck_row.addWidget(QLabel("ATK"))
        deck_row.addWidget(attack_preview)
        deck_row.addStretch(1)
        deck_row.addWidget(QLabel("DEF"))
        deck_row.addWidget(defense_preview)
        layout.addLayout(deck_row)
        self._tactical_opponent_top_list.addItem(item)
        hint = row.sizeHint()
        hint.setHeight(hint.height() + scale_px(8, self._ui_scale))
        item.setSizeHint(hint)
        self._tactical_opponent_top_list.setItemWidget(item, row)

    def _refresh_tactical_jokbo_results(self) -> None:
        if not hasattr(self, "_tactical_jokbo_results"):
            return
        defense = self._deck_from_tactical_inputs(self._tactical_jokbo_search_inputs)
        if not any(defense.strikers) and not any(defense.supports):
            self._tactical_jokbo_results.clear()
            self._tactical_jokbo_results.addItem("방어덱을 입력하거나 전적을 선택하면 족보를 검색합니다.")
            return
        defense, error = self._canonical_tactical_search_deck_or_error(defense, "족보 검색 방어덱")
        if error:
            self._tactical_jokbo_results.clear()
            item = QListWidgetItem(self._compact_tactical_message(error, max_lines=2, max_chars=130))
            item.setToolTip(error)
            self._tactical_jokbo_results.addItem(item)
            self._set_tactical_status(error, error=True)
            return
        self._set_tactical_deck_inputs(self._tactical_jokbo_search_inputs, defense)
        results = search_jokbo_from_storage(self._tactical_path, self._tactical_data, defense)
        self._tactical_jokbo_results.clear()
        for result in results["manual"]:
            entry = result["entry"]
            self._add_tactical_jokbo_result_row(
                title=f"족보 · {result['wins']}승 {result['losses']}패 ({result['win_rate']:.1f}%)",
                defense=entry.defense,
                attack=entry.attack,
                note=entry.notes or "-",
            )
        for result in results["observed"]:
            self._add_tactical_jokbo_result_row(
                title=f"전적 기반 · {result['wins']}승 {result['losses']}패 ({result['win_rate']:.1f}%)",
                defense=result["defense"],
                attack=result["attack"],
                note="",
            )
        if self._tactical_jokbo_results.count() == 0:
            self._tactical_jokbo_results.addItem("일치하는 족보나 전적 기반 공격덱이 없습니다.")

    def _add_tactical_jokbo_result_row(self, *, title: str, defense: TacticalDeck, attack: TacticalDeck, note: str) -> None:
        item = QListWidgetItem()
        item.setData(Qt.UserRole, deck_template(defense))
        item.setData(Qt.UserRole + 1, deck_template(attack))
        row = QFrame()
        row.setObjectName("planBand")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(scale_px(8, self._ui_scale), scale_px(7, self._ui_scale), scale_px(8, self._ui_scale), scale_px(7, self._ui_scale))
        label = QLabel(title)
        label.setObjectName("sectionTitle")
        if note:
            label.setToolTip(note)
        layout.addWidget(label)
        decks = QHBoxLayout()
        decks.setContentsMargins(0, 0, 0, 0)
        decks.setSpacing(scale_px(6, self._ui_scale))
        defense_preview = TacticalDeckPreview(card_asset=self._student_card_asset, ui_scale=self._ui_scale, icon_provider=self._tactical_portrait_pixmap, compact=True)
        defense_preview.setDeck(defense)
        attack_preview = TacticalDeckPreview(card_asset=self._student_card_asset, ui_scale=self._ui_scale, icon_provider=self._tactical_portrait_pixmap, compact=True)
        attack_preview.setDeck(attack)
        decks.addWidget(QLabel("ATK"))
        decks.addWidget(attack_preview)
        decks.addStretch(1)
        decks.addWidget(QLabel("DEF"))
        decks.addWidget(defense_preview)
        layout.addLayout(decks)
        self._tactical_jokbo_results.addItem(item)
        hint = row.sizeHint()
        hint.setHeight(hint.height() + scale_px(8, self._ui_scale))
        item.setSizeHint(hint)
        self._tactical_jokbo_results.setItemWidget(item, row)

    def _selected_tactical_jokbo_decks(self) -> tuple[TacticalDeck, TacticalDeck] | None:
        if not hasattr(self, "_tactical_jokbo_results"):
            return None
        item = self._tactical_jokbo_results.currentItem()
        if item is None:
            return None
        defense_text = str(item.data(Qt.UserRole) or "")
        attack_text = str(item.data(Qt.UserRole + 1) or "")
        if not defense_text and not attack_text:
            return None
        return parse_deck_template(defense_text), parse_deck_template(attack_text)

    def _copy_selected_tactical_jokbo_defense(self) -> None:
        decks = self._selected_tactical_jokbo_decks()
        if decks is not None:
            self._copy_tactical_deck_template(decks[0])

    def _copy_selected_tactical_jokbo_attack(self) -> None:
        decks = self._selected_tactical_jokbo_decks()
        if decks is not None:
            self._copy_tactical_deck_template(decks[1])

    def _copy_tactical_deck_template(self, deck: TacticalDeck) -> None:
        QApplication.clipboard().setText(deck_template(deck))
        if hasattr(self, "_tactical_status"):
            self._set_tactical_status("덱 템플릿을 복사했습니다.")

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

        sunburst_panel = QFrame()
        sunburst_panel.setObjectName("statPanel")
        sunburst_layout = QVBoxLayout(sunburst_panel)
        sunburst_layout.setContentsMargins(
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
        )
        sunburst_layout.setSpacing(scale_px(12, self._ui_scale))

        sunburst_header = QHBoxLayout()
        sunburst_header.setContentsMargins(0, 0, 0, 0)
        sunburst_header.setSpacing(scale_px(10, self._ui_scale))
        sunburst_title = QLabel("Sunburst Overview")
        sunburst_title.setObjectName("sectionTitle")
        sunburst_header.addWidget(sunburst_title)
        self._stats_sunburst_mode = QComboBox()
        self._stats_sunburst_mode.addItem("School > Role > Attack", "collection_school_role_attack")
        self._stats_sunburst_mode.addItem("Class > Role > Position", "collection_class_role_position")
        self._stats_sunburst_mode.addItem("Plan Required Resources", "plan_required")
        self._stats_sunburst_mode.addItem("Plan Shortages", "plan_shortage")
        self._stats_sunburst_mode.currentIndexChanged.connect(lambda *_: self._refresh_stats_tab())
        sunburst_header.addWidget(self._stats_sunburst_mode, 0, Qt.AlignRight)
        sunburst_layout.addLayout(sunburst_header)

        sunburst_body = QHBoxLayout()
        sunburst_body.setContentsMargins(0, 0, 0, 0)
        sunburst_body.setSpacing(scale_px(12, self._ui_scale))
        self._stats_sunburst = SunburstWidget(self._ui_scale)
        sunburst_body.addWidget(self._stats_sunburst, 3)
        detail_panel = QFrame()
        detail_panel.setObjectName("planBand")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(12, self._ui_scale),
        )
        detail_layout.setSpacing(scale_px(8, self._ui_scale))
        detail_title = QLabel("Top Branches")
        detail_title.setObjectName("detailSectionTitle")
        detail_layout.addWidget(detail_title)
        self._stats_sunburst_detail = QLabel("")
        self._stats_sunburst_detail.setObjectName("detailSub")
        self._stats_sunburst_detail.setWordWrap(True)
        detail_layout.addWidget(self._stats_sunburst_detail)
        detail_layout.addStretch(1)
        sunburst_body.addWidget(detail_panel, 2)
        sunburst_layout.addLayout(sunburst_body, 1)
        layout.addWidget(sunburst_panel, 2)

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
        self._plan_search = LiveSearchLineEdit()
        self._plan_search.setPlaceholderText("Type student name, id, or tag")
        self._plan_search.liveTextChanged.connect(self._schedule_plan_search_refresh)
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

        self._plan_empty_label = QLabel("No students in plan yet. Use Quick Add below the grid to add your first student.")
        self._plan_empty_label.setObjectName("filterSummary")
        self._plan_empty_label.setWordWrap(True)
        plan_layout.addWidget(self._plan_empty_label)

        self._plan_grid = ParallelogramCardGrid(self._student_card_asset, self._ui_scale)
        self._plan_grid.setObjectName("studentGrid")
        self._plan_grid.current_changed.connect(self._on_plan_card_changed)
        self._plan_grid.layout_changed.connect(lambda *_: self._refresh_card_layout())
        plan_layout.addWidget(self._plan_grid, 1)

        plan_layout.addWidget(quick_add_panel, 0)

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
        editor_outer_layout = QVBoxLayout(editor_panel)
        editor_outer_layout.setContentsMargins(0, 0, 0, 0)
        editor_outer_layout.setSpacing(0)

        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.NoFrame)
        editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor_scroll.setObjectName("planEditorScroll")
        editor_outer_layout.addWidget(editor_scroll, 1)

        editor_content = QWidget()
        editor_content.setObjectName("planTransparent")
        editor_layout = QVBoxLayout(editor_content)
        editor_layout.setContentsMargins(scale_px(16, self._ui_scale), scale_px(16, self._ui_scale), scale_px(16, self._ui_scale), scale_px(16, self._ui_scale))
        editor_layout.setSpacing(scale_px(10, self._ui_scale))
        editor_scroll.setWidget(editor_content)

        editor_header = QWidget()
        editor_header.setObjectName("planTransparent")
        editor_header_layout = QHBoxLayout(editor_header)
        editor_header_layout.setContentsMargins(0, 0, 0, 0)
        editor_header_layout.setSpacing(scale_px(10, self._ui_scale))
        name_col = QVBoxLayout()
        name_col.setContentsMargins(0, 0, 0, 0)
        name_col.setSpacing(scale_px(2, self._ui_scale))
        self._plan_name = QLabel("Select a student")
        self._plan_name.setObjectName("detailName")
        name_col.addWidget(self._plan_name)
        self._plan_current = QLabel("")
        self._plan_current.setObjectName("detailSub")
        name_col.addWidget(self._plan_current)
        editor_header_layout.addLayout(name_col, 1)

        plan_editor_tabs = QTabBar()
        plan_editor_tabs.setObjectName("planEditorTabs")
        plan_editor_tabs.setExpanding(False)
        plan_editor_tabs.setUsesScrollButtons(False)
        plan_editor_tabs.addTab("Edit")
        plan_editor_tabs.addTab("Resources")
        editor_header_layout.addWidget(plan_editor_tabs, 0, Qt.AlignRight | Qt.AlignVCenter)
        editor_layout.addWidget(editor_header)

        plan_editor_stack = QStackedWidget()
        plan_editor_stack.setObjectName("planEditorStack")
        plan_editor_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        plan_editor_tabs.currentChanged.connect(plan_editor_stack.setCurrentIndex)
        edit_tab = QWidget()
        edit_tab.setObjectName("planTransparent")
        edit_tab_layout = QVBoxLayout(edit_tab)
        edit_tab_layout.setContentsMargins(0, 0, 0, 0)
        edit_tab_layout.setSpacing(0)
        resources_tab = QWidget()
        resources_tab.setObjectName("planTransparent")
        resources_tab_layout = QVBoxLayout(resources_tab)
        resources_tab_layout.setContentsMargins(0, 0, 0, 0)
        resources_tab_layout.setSpacing(0)

        controls_wrap = QWidget()
        controls_layout = QVBoxLayout(controls_wrap)
        controls_layout.setContentsMargins(scale_px(10, self._ui_scale), scale_px(6, self._ui_scale), scale_px(10, self._ui_scale), scale_px(10, self._ui_scale))
        controls_layout.setSpacing(scale_px(16, self._ui_scale))

        def add_plan_level_row(
            parent_layout: QVBoxLayout,
            field_name: str,
            label: str,
            maximum: int,
            *,
            label_width: int = 62,
        ) -> QFrame:
            row = QFrame()
            row.setObjectName("planBand")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(8, self._ui_scale), scale_px(12, self._ui_scale), scale_px(8, self._ui_scale))
            row_layout.setSpacing(scale_px(8, self._ui_scale))
            row_title = QLabel(label)
            row_title.setObjectName("detailSectionTitle")
            row_title.setMinimumWidth(scale_px(label_width, self._ui_scale))
            self._plan_level_row_labels[field_name] = row_title
            row_layout.addWidget(row_title)
            selector = PlanStepper(maximum, ui_scale=self._ui_scale)
            selector.valueChanged.connect(lambda value, name=field_name: self._on_plan_digit_changed(name, value))
            self._plan_level_inputs[field_name] = selector
            self._plan_level_rows[field_name] = row
            row_layout.addWidget(selector, 1)
            parent_layout.addWidget(row)
            return row

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

        add_plan_level_row(progression_layout, "target_level", "Student", 90, label_width=118)
        add_plan_level_row(progression_layout, "target_weapon_level", "Weapon", MAX_TARGET_WEAPON_LEVEL, label_width=118)

        stat_toggle = QPushButton()
        stat_toggle.setObjectName("planDisclosureButton")
        stat_toggle.clicked.connect(self._toggle_ability_release_targets)
        progression_layout.addWidget(stat_toggle)
        self._plan_stat_caption = stat_toggle
        self._update_ability_release_toggle_text()

        for field_name, label in (
            ("target_stat_hp", "HP"),
            ("target_stat_atk", "ATK"),
            ("target_stat_heal", "HEAL"),
        ):
            row = add_plan_level_row(progression_layout, field_name, label, 25, label_width=118)
            self._plan_stat_rows[field_name] = row

        controls_layout.addWidget(progression_panel)

        requirement_panel = QFrame()
        requirement_panel.setObjectName("planSectionPanel")
        requirement_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        requirement_layout = QVBoxLayout(requirement_panel)
        requirement_layout.setContentsMargins(
            scale_px(14, self._ui_scale),
            scale_px(12, self._ui_scale),
            scale_px(14, self._ui_scale),
            scale_px(12, self._ui_scale),
        )
        requirement_layout.setSpacing(scale_px(8, self._ui_scale))
        requirement_header = QHBoxLayout()
        requirement_header.setContentsMargins(0, 0, 0, 0)
        requirement_header.setSpacing(scale_px(10, self._ui_scale))
        requirement_title = QLabel("Required Resources")
        requirement_title.setObjectName("sectionTitle")
        requirement_header.addWidget(requirement_title)
        self._plan_requirement_summary = QLabel("Selected student - Needed / Inventory")
        self._plan_requirement_summary.setObjectName("count")
        self._plan_requirement_summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        requirement_header.addWidget(self._plan_requirement_summary, 1)
        requirement_layout.addLayout(requirement_header)

        self._plan_requirement_empty = QLabel("Select a planned student and set targets to preview required resources.")
        self._plan_requirement_empty.setObjectName("filterSummary")
        self._plan_requirement_empty.setWordWrap(True)
        self._plan_requirement_empty.setMinimumHeight(scale_px(22, self._ui_scale))
        requirement_layout.addWidget(self._plan_requirement_empty)

        self._plan_requirement_scroll = QScrollArea()
        self._plan_requirement_scroll.setFrameShape(QFrame.NoFrame)
        self._plan_requirement_scroll.setWidgetResizable(True)
        self._plan_requirement_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._plan_requirement_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._plan_requirement_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._plan_requirement_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QScrollArea > QWidget > QWidget { background: transparent; }")

        self._plan_requirement_grid_host = QWidget()
        self._plan_requirement_grid_host.setObjectName("planTransparent")
        self._plan_requirement_grid_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._plan_requirement_grid = QGridLayout(self._plan_requirement_grid_host)
        self._plan_requirement_grid.setContentsMargins(
            scale_px(6, self._ui_scale),
            scale_px(6, self._ui_scale),
            scale_px(6, self._ui_scale),
            scale_px(6, self._ui_scale),
        )
        self._plan_requirement_grid.setHorizontalSpacing(scale_px(8, self._ui_scale))
        self._plan_requirement_grid.setVerticalSpacing(scale_px(8, self._ui_scale))
        self._plan_requirement_grid.setAlignment(Qt.AlignTop)
        for column in range(3):
            self._plan_requirement_grid.setColumnStretch(column, 1)
        self._plan_requirement_scroll.setWidget(self._plan_requirement_grid_host)
        requirement_layout.addWidget(self._plan_requirement_scroll, 1)

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
        controls_layout.addWidget(skill_panel, 0)

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
            control_stack = QVBoxLayout()
            control_stack.setContentsMargins(0, 0, 0, 0)
            control_stack.setSpacing(scale_px(8, self._ui_scale))
            selector = PlanSegmentSelector(MAX_TARGET_EQUIP_TIER, active_fill=PALETTE_SOFT, active_border="#ffffff", inactive_fill=_mix_hex(SURFACE_ALT, BG, 0.14), ui_scale=self._ui_scale)
            selector.valueChanged.connect(lambda value, name=field_name: self._on_plan_segment_changed(name, value))
            self._plan_segment_inputs[field_name] = selector
            control_stack.addWidget(selector)

            level_field_name = f"target_equip{slot_index}_level"
            level_row = QWidget()
            level_row.setObjectName("planTransparent")
            level_layout = QHBoxLayout(level_row)
            level_layout.setContentsMargins(0, 0, 0, 0)
            level_layout.setSpacing(scale_px(8, self._ui_scale))
            level_title = QLabel("Level")
            level_title.setObjectName("detailSectionTitle")
            level_title.setMinimumWidth(scale_px(54, self._ui_scale))
            self._plan_level_row_labels[level_field_name] = row_title
            level_layout.addWidget(level_title)
            level_selector = PlanStepper(MAX_TARGET_EQUIP_LEVEL, ui_scale=self._ui_scale)
            level_selector.valueChanged.connect(lambda value, name=level_field_name: self._on_plan_digit_changed(name, value))
            self._plan_level_inputs[level_field_name] = level_selector
            self._plan_level_rows[level_field_name] = level_row
            level_layout.addWidget(level_selector, 1)
            control_stack.addWidget(level_row)

            row_layout.addLayout(control_stack, 1)
            equipment_main.addWidget(row)
        controls_layout.addWidget(equipment_panel, 0)

        self._plan_student_summary = QLabel("Need materials preview will come later.")
        self._plan_total_summary = QLabel("")
        self._plan_student_summary.setVisible(False)
        self._plan_total_summary.setVisible(False)
        edit_tab_layout.addWidget(controls_wrap, 0)
        edit_tab_layout.addStretch(1)
        resources_tab_layout.addWidget(requirement_panel, 1)
        plan_editor_stack.addWidget(edit_tab)
        plan_editor_stack.addWidget(resources_tab)
        plan_editor_tabs.setCurrentIndex(0)
        editor_layout.addWidget(plan_editor_stack, 1)
        splitter.addWidget(editor_panel)

        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 3)

    def _plan_goal_map(self) -> dict[str, StudentGoal]:
        if self._plan_goal_map_cache is None:
            self._plan_goal_map_cache = self._plan.goal_map()
        return self._plan_goal_map_cache

    def _invalidate_plan_caches(self, student_id: str | None = None) -> None:
        self._plan_goal_map_cache = None
        if student_id is None:
            self._plan_cost_cache.clear()
            return
        for cache_key in [cache_key for cache_key in self._plan_cost_cache if cache_key[0] == student_id]:
            del self._plan_cost_cache[cache_key]

    def _goal_cache_signature(self, goal: StudentGoal) -> tuple[object, ...]:
        return tuple(getattr(goal, field_name, None) for field_name in _PLAN_GOAL_CACHE_FIELDS)

    def _cached_goal_cost(
        self,
        student_id: str,
        *,
        record: StudentRecord | None = None,
        goal: StudentGoal | None = None,
        goal_map: dict[str, StudentGoal] | None = None,
    ) -> PlanCostSummary | None:
        record = record or self._records_by_id.get(student_id)
        if goal is None:
            goal_map = self._plan_goal_map() if goal_map is None else goal_map
            goal = goal_map.get(student_id)
        if record is None or goal is None:
            return None
        cache_key = (student_id, self._goal_cache_signature(goal))
        summary = self._plan_cost_cache.get(cache_key)
        if summary is None:
            summary = calculate_goal_cost(record, goal)
            self._plan_cost_cache[cache_key] = summary
        return summary

    def _cached_plan_resource_icon_path(self, item_id: str | None, name: str) -> Path | None:
        cache_key = (item_id, name)
        if cache_key not in self._plan_resource_icon_path_cache:
            self._plan_resource_icon_path_cache[cache_key] = _plan_resource_icon_path(item_id, name)
        return self._plan_resource_icon_path_cache[cache_key]

    def _cached_plan_resource_pixmap(self, icon_path: Path | None) -> QPixmap | None:
        if icon_path is None:
            return None
        pixmap = self._plan_resource_pixmap_cache.get(icon_path)
        if pixmap is None:
            pixmap = QPixmap(str(icon_path)) if icon_path.exists() else QPixmap()
            self._plan_resource_pixmap_cache[icon_path] = pixmap
        return pixmap if not pixmap.isNull() else None

    def _save_plan(self) -> None:
        save_plan(self._plan_path, self._plan)
        try:
            self._storage_mtimes[self._plan_path] = self._plan_path.stat().st_mtime_ns
        except OSError:
            self._storage_mtimes[self._plan_path] = None

    def _get_or_create_goal(self, student_id: str) -> StudentGoal:
        for goal in self._plan.goals:
            if goal.student_id == student_id:
                return goal
        goal = StudentGoal(student_id=student_id)
        self._plan.goals.append(goal)
        self._invalidate_plan_caches(student_id)
        return goal

    def _apply_student_card_record(self, card: StudentCardWidget, record: StudentRecord) -> None:
        divider_primary, divider_secondary = _student_divider_colors(record)
        card.setData(
            title=record.title,
            owned=record.owned,
            divider_left=QColor(divider_primary),
            divider_right=QColor(divider_secondary),
        )
        card.setToolTip(record.student_id)

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
        self._apply_cached_thumb_to_card(card)
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
        return (
            student_id in self._item_by_id
            or student_id in self._plan_card_by_id
            or student_id in self._resource_scope_card_by_id
            or student_id in self._resource_search_card_by_id
        )

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

        self._refresh_ability_release_visibility(record, goal)

        has_unique_item = self._record_supports_unique_item(record)
        self._plan_unique_item_panel.setVisible(has_unique_item)
        if has_unique_item:
            selector = self._plan_unique_item_selector
            selector.setEnabled(self._plan_supports_field(goal, "target_equip4_tier"))

    @staticmethod
    def _set_widget_visible(widget: QWidget | None, visible: bool) -> None:
        if widget is not None and widget.isVisible() != visible:
            widget.setVisible(visible)

    def _update_ability_release_toggle_text(self) -> None:
        marker = "-" if self._plan_ability_release_expanded else "+"
        self._plan_stat_caption.setText(f"Ability Release {marker}")

    def _ability_release_available(self, record: StudentRecord, goal: StudentGoal | None) -> bool:
        current_level = max(0, int(record.level or 0))
        return self._goal_value(goal, "target_level", current_level) >= 90

    def _refresh_ability_release_visibility(self, record: StudentRecord, goal: StudentGoal | None) -> None:
        available = self._ability_release_available(record, goal)
        self._set_widget_visible(self._plan_stat_caption, available)
        for row in self._plan_stat_rows.values():
            self._set_widget_visible(row, available and self._plan_ability_release_expanded)
        self._update_ability_release_toggle_text()

    def _toggle_ability_release_targets(self) -> None:
        self._plan_ability_release_expanded = not self._plan_ability_release_expanded
        student_id = self._selected_plan_student_id or self._plan_current_all_student_id()
        record = self._records_by_id.get(student_id) if student_id else None
        goal = self._plan_goal_map().get(student_id) if student_id else None
        if record is not None:
            self._refresh_ability_release_visibility(record, goal)
        else:
            self._update_ability_release_toggle_text()

    def _refresh_weapon_level_controls(self, record: StudentRecord, goal: StudentGoal | None) -> None:
        current_weapon_level = self._record_weapon_level(record)
        target_weapon_star = self._current_or_target_weapon_star(record, goal)
        target_weapon_level = self._goal_value(goal, "target_weapon_level", current_weapon_level)
        show_weapon_level = self._plan_allows_weapon_targets(record) and (target_weapon_star > 0 or target_weapon_level > 0)
        self._set_widget_visible(self._plan_level_rows.get("target_weapon_level"), show_weapon_level)
        weapon_level_selector = self._plan_level_inputs["target_weapon_level"]
        weapon_level_selector.setMaximumValue(self._weapon_level_cap_for_star(target_weapon_star))
        weapon_level_selector.setEnabled(self._plan_allows_weapon_targets(record))
        weapon_level_selector.setState(
            minimum_value=current_weapon_level,
            value=target_weapon_level,
        )

    def _refresh_star_weapon_controls(self, record: StudentRecord, goal: StudentGoal | None) -> None:
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
        self._refresh_weapon_level_controls(record, goal)

    def _refresh_single_equipment_controls(self, record: StudentRecord, goal: StudentGoal | None, slot_index: int) -> None:
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

    def _refresh_single_digit_control(self, record: StudentRecord, goal: StudentGoal | None, field_name: str) -> None:
        if field_name == "target_level":
            current_value = max(0, int(record.level or 0))
        elif field_name == "target_weapon_level":
            self._refresh_star_weapon_controls(record, goal)
            return
        elif field_name == "target_stat_hp":
            current_value = max(0, int(record.stat_hp or 0))
        elif field_name == "target_stat_atk":
            current_value = max(0, int(record.stat_atk or 0))
        elif field_name == "target_stat_heal":
            current_value = max(0, int(record.stat_heal or 0))
        else:
            return
        selector = self._plan_level_inputs.get(field_name)
        if selector is None:
            return
        selector.setEnabled(self._plan_supports_field(goal, field_name))
        selector.setState(
            minimum_value=current_value,
            value=self._goal_value(goal, field_name, current_value),
        )
        if field_name == "target_level":
            self._refresh_ability_release_visibility(record, goal)

    def _refresh_single_segment_control(self, record: StudentRecord, goal: StudentGoal | None, field_name: str) -> None:
        if field_name == "star_weapon":
            self._refresh_star_weapon_controls(record, goal)
            return
        if field_name.startswith("target_equip") and field_name.endswith("_tier"):
            self._refresh_single_equipment_controls(record, goal, int(field_name[len("target_equip")]))
            return
        if field_name == "target_equip4_tier":
            if self._record_supports_unique_item(record):
                current_unique_tier = _parse_tier_number(record.equip4) or 0
                self._plan_unique_item_selector.setState(
                    minimum_value=current_unique_tier,
                    value=self._goal_value(goal, "target_equip4_tier", current_unique_tier),
                    enabled_count=2,
                )
            return
        current_value = 0
        if field_name == "target_ex_skill":
            current_value = self._record_current_skill(record.ex_skill)
        elif field_name == "target_skill1":
            current_value = self._record_current_skill(record.skill1)
        elif field_name == "target_skill2":
            current_value = self._record_current_skill(record.skill2)
        elif field_name == "target_skill3":
            current_value = self._record_current_skill(record.skill3)
        selector = self._plan_segment_inputs.get(field_name)
        if selector is not None:
            selector.setState(
                minimum_value=current_value,
                value=self._goal_value(goal, field_name, current_value),
            )

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
                enabled_count=2,
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
        was_planned = student_id in self._plan_goal_map()
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
        self._invalidate_plan_caches(student_id)
        self._save_plan()
        self._selected_plan_student_id = student_id
        self._refresh_after_plan_goal_change(student_id, rebuild_lists=not was_planned, changed_field=field_name)

    def _on_plan_digit_changed(self, field_name: str, value: int) -> None:
        if self._plan_editor_guard:
            return
        student_id = self._selected_plan_student_id or self._plan_current_all_student_id()
        if not student_id:
            return
        record = self._records_by_id.get(student_id)
        if record is None:
            return
        was_planned = student_id in self._plan_goal_map()
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
        self._invalidate_plan_caches(student_id)
        self._save_plan()
        self._selected_plan_student_id = student_id
        self._refresh_after_plan_goal_change(student_id, rebuild_lists=not was_planned, changed_field=field_name)

    def _refresh_after_plan_goal_change(self, student_id: str, *, rebuild_lists: bool, changed_field: str | None = None) -> None:
        if rebuild_lists:
            self._refresh_plan_lists()
            self._set_plan_grid_selection(student_id)
        else:
            self._refresh_plan_editor_after_goal_change(student_id, changed_field)
            if self._current_plan_grid_student_id() != student_id:
                self._set_plan_grid_selection(student_id)
            self._update_plan_actions()
        self._refresh_plan_totals()

    def _refresh_plan_editor_after_goal_change(self, student_id: str, changed_field: str | None = None) -> None:
        record = self._records_by_id.get(student_id)
        goal = self._plan_goal_map().get(student_id)
        if record is None:
            self._clear_plan_editor()
            return
        self._plan_editor_guard = True
        try:
            if changed_field is None:
                self._refresh_plan_editor_controls(record, goal)
            elif changed_field in self._plan_segment_inputs:
                self._refresh_single_segment_control(record, goal, changed_field)
            elif changed_field in self._plan_level_inputs:
                if changed_field.startswith("target_equip") and changed_field.endswith("_level"):
                    self._refresh_single_equipment_controls(record, goal, int(changed_field[len("target_equip")]))
                else:
                    self._refresh_single_digit_control(record, goal, changed_field)
        finally:
            self._plan_editor_guard = False
        self._update_plan_student_summary(student_id)
        self._refresh_selected_plan_requirements(student_id)

    def _refresh_plan_lists(self) -> None:
        if not hasattr(self, "_plan_all_list"):
            return
        query = _live_line_edit_text(self._plan_search).strip().casefold()
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

        planned_goals = sorted(
            self._plan.goals,
            key=lambda entry: self._records_by_id.get(entry.student_id).title.lower() if entry.student_id in self._records_by_id else entry.student_id,
        )
        planned_ids = tuple(goal.student_id for goal in planned_goals if goal.student_id in self._records_by_id)
        current_ids = tuple(self._plan_card_by_id)
        if planned_ids != current_ids:
            self._plan_grid.clear_cards()
            self._plan_card_by_id.clear()
            planned_cards: list[StudentCardWidget] = []
            for goal in planned_goals:
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
        else:
            planned_cards = list(self._plan_card_by_id.values())

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
        self._invalidate_plan_caches(student_id)
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
            self._plan_ability_release_expanded = False
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
        self._refresh_selected_plan_requirements(student_id)

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
            self._update_ability_release_toggle_text()
        for row in getattr(self, "_plan_stat_rows", {}).values():
            row.setVisible(False)
        self._plan_student_summary.setText("No student selected")
        self._refresh_plan_requirements(None)
        self._update_plan_actions()

    def _update_plan_student_summary(self, student_id: str) -> None:
        record = self._records_by_id.get(student_id)
        goal = self._plan_goal_map().get(student_id)
        if record is None or goal is None:
            self._plan_student_summary.setText("Add this student to the plan to calculate costs.")
            return
        summary = self._cached_goal_cost(student_id, record=record, goal=goal)
        if summary is None:
            self._plan_student_summary.setText("Add this student to the plan to calculate costs.")
            return
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
        goal_map = self._plan_goal_map()
        total, _selected_count, _contributing_count = self._resource_total_for_ids(
            [goal.student_id for goal in self._plan.goals],
            goal_map,
        )
        self._plan_total_summary.setText(
            f"{len(self._plan.goals)} students in plan\n{self._format_cost_summary(total)}"
        )
        self._refresh_resources_if_visible()
        self._refresh_inventory_tab()

    def _refresh_selected_plan_requirements(self, student_id: str | None = None) -> None:
        selected_id = student_id or self._selected_plan_student_id or self._current_plan_grid_student_id()
        if not selected_id:
            self._refresh_plan_requirements(None)
            return
        record = self._records_by_id.get(selected_id)
        goal = self._plan_goal_map().get(selected_id)
        if record is None or goal is None:
            self._refresh_plan_requirements(None)
            return
        self._refresh_plan_requirements(self._cached_goal_cost(selected_id, record=record, goal=goal), record=record)

    def _plan_requirement_sort_key(
        self,
        entry: PlanResourceRequirement,
        *,
        equipment_slot_order: dict[str, int],
    ) -> tuple[int, int, str]:
        category = entry.category
        item_id = entry.key
        if category == "skill_books":
            if item_id == "Item_Icon_SkillBook_Ultimate_Piece":
                category = "secret_notes"
            elif item_id.startswith("Item_Icon_Material_ExSkill_"):
                category = "skill_bd"
            elif item_id.startswith("Item_Icon_SkillBook_"):
                category = "skill_notes"
        elif category == "equipment_materials":
            series_key = _equipment_series_key_from_item(item_id, entry.name)
            slot_index = equipment_slot_order.get(series_key or "")
            if slot_index in (1, 2, 3):
                category = f"equipment_slot_{slot_index}"
        tier = _tier_from_item_id_or_name(item_id, entry.name)
        return (
            _PLAN_RESOURCE_CATEGORY_ORDER.get(category, 999),
            -tier,
            entry.name.lower(),
        )

    def _plan_requirement_entries(self, summary: PlanCostSummary, *, record: StudentRecord | None = None) -> list[PlanResourceRequirement]:
        inventory_index = self._inventory_quantity_index_cache
        merged: dict[tuple[str, str], PlanResourceRequirement] = {}
        equipment_slot_order: dict[str, int] = {}
        if record is not None:
            for index, slot_key in enumerate(student_meta.equipment_slots(record.student_id) or (), start=1):
                if slot_key:
                    equipment_slot_order[str(slot_key)] = index

        def add_entry(category: str, key: str, required: int) -> None:
            if required <= 0:
                return
            item_id = _plan_resource_item_id(key, category)
            name = _plan_resource_display_name(item_id, key)
            owned = inventory_index.get(item_id or "", inventory_index.get(key, 0))
            icon_path = self._cached_plan_resource_icon_path(item_id, name)
            icon = self._cached_plan_resource_pixmap(icon_path)
            merge_key = (category, item_id or key)
            current = merged.get(merge_key)
            if current is None:
                merged[merge_key] = PlanResourceRequirement(
                    key=item_id or key,
                    name=name,
                    required=required,
                    owned=owned,
                    icon_path=icon_path,
                    category=category,
                    icon=icon,
                )
            else:
                current.required += required

        add_entry("credits", "Currency_Icon_Gold", summary.credits)
        for category, values in (
            ("level_exp", summary.level_exp_items),
            ("equipment_exp", summary.equipment_exp_items),
            ("weapon_exp", summary.weapon_exp_items),
            ("skill_books", summary.skill_books),
            ("ex_ooparts", summary.ex_ooparts),
            ("skill_ooparts", summary.skill_ooparts),
            ("favorite_item_materials", summary.favorite_item_materials),
            ("stat_materials", summary.stat_materials),
            ("equipment_materials", summary.equipment_materials),
            ("star_materials", summary.star_materials),
        ):
            for key, required in values.items():
                add_entry(category, key, required)

        return sorted(
            merged.values(),
            key=lambda entry: self._plan_requirement_sort_key(entry, equipment_slot_order=equipment_slot_order),
        )

    def _refresh_plan_requirements(self, summary: PlanCostSummary | None, *, record: StudentRecord | None = None) -> None:
        if not hasattr(self, "_plan_requirement_grid"):
            return

        self._plan_requirement_grid_host.setUpdatesEnabled(False)
        try:
            while self._plan_requirement_grid.count():
                item = self._plan_requirement_grid.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()

            if summary is None:
                self._plan_requirement_empty.setText("Select a planned student and set targets to preview required resources.")
                self._plan_requirement_empty.setVisible(True)
                self._plan_requirement_scroll.setVisible(True)
                self._plan_requirement_summary.setText("Selected student - Needed / Inventory")
                return

            entries = self._plan_requirement_entries(summary, record=record)
            self._plan_requirement_empty.setText("" if entries else "This student's current targets do not require additional resources.")
            self._plan_requirement_empty.setVisible(True)
            self._plan_requirement_scroll.setVisible(True)
            if not entries:
                self._plan_requirement_summary.setText("Selected student - Needed / Inventory")
                return

            shortages = sum(1 for entry in entries if entry.required > entry.owned)
            self._plan_requirement_summary.setText(
                f"{len(entries)} items - {shortages} short - Needed / Inventory"
            )
            columns = 3
            for index, requirement in enumerate(entries):
                chip = PlanResourceChip(ui_scale=self._ui_scale)
                chip.setData(requirement)
                self._plan_requirement_grid.addWidget(chip, index // columns, index % columns)
        finally:
            self._plan_requirement_grid_host.setUpdatesEnabled(True)

    def _stats_value_label(self, record: StudentRecord, field_name: str) -> str:
        if field_name == "owned":
            return "Owned" if record.owned else "Unowned"
        value = get_student_value(record, field_name)
        return format_filter_value(field_name, value) if value else "(Missing)"

    def _sunburst_tree_from_paths(self, title: str, paths: list[tuple[tuple[str, ...], float]]) -> SunburstNode:
        tree: dict[str, dict] = {}

        for raw_path, raw_value in paths:
            value = float(raw_value or 0)
            if value <= 0:
                continue
            cursor = tree
            for part in raw_path:
                label = str(part or "(Missing)")
                cursor = cursor.setdefault(label, {})
            cursor["_value"] = float(cursor.get("_value", 0.0)) + value

        def build(label: str, branch: dict) -> SunburstNode:
            children = [
                build(child_label, child_branch)
                for child_label, child_branch in branch.items()
                if child_label != "_value"
            ]
            children.sort(key=lambda child: (-child.total(), child.label.casefold()))
            return SunburstNode(label=label, value=float(branch.get("_value", 0.0)), children=children)

        root = build(title, tree)
        return root

    def _collection_sunburst_root(self, mode: str) -> SunburstNode:
        if mode == "collection_class_role_position":
            fields = ("combat_class", "role", "position")
            title = "Visible Students"
        else:
            fields = ("school", "role", "attack_type")
            title = "Visible Students"
        paths = [
            (tuple(self._stats_value_label(record, field_name) for field_name in fields), 1.0)
            for record in self._filtered_students
        ]
        return self._sunburst_tree_from_paths(title, paths)

    def _skill_book_sunburst_path(self, item_id: str, name: str) -> tuple[str, ...]:
        if "SkillBook_Ultimate" in item_id or "Ultimate" in item_id:
            return ("Skills", "Secret Notes", name)
        match = re.match(r"Item_Icon_Material_ExSkill_([^_]+)_(\d+)", item_id)
        if match:
            return ("Skills", "Tactical BD", match.group(1), f"T{int(match.group(2)) + 1}")
        match = re.match(r"Item_Icon_SkillBook_([^_]+)_(\d+)", item_id)
        if match:
            return ("Skills", "Tech Notes", match.group(1), f"T{int(match.group(2)) + 1}")
        base, tier = _plan_resource_split_tier(name)
        school, _, kind = base.partition(" ")
        if school and kind:
            return ("Skills", kind, school, f"T{tier}" if tier else name)
        return ("Skills", "Other", name)

    def _oopart_sunburst_path(self, group: str, item_id: str, name: str) -> tuple[str, ...]:
        tier = _tier_from_item_id_or_name(item_id, name)
        family = name
        if tier:
            family = re.sub(r"\s+T\d+$", "", name).strip() or name
        return ("Ooparts", group, family, f"T{tier}" if tier else name)

    def _equipment_sunburst_path(self, item_id: str, name: str) -> tuple[str, ...]:
        tier = _tier_from_item_id_or_name(item_id, name)
        series_key = _equipment_series_key_from_item(item_id, name)
        series = series_key or re.sub(r"\s+T\d+$", "", name).strip() or name
        return ("Equipment", "Blueprints", series, f"T{tier}" if tier else name)

    def _resource_sunburst_root(self, *, shortage_only: bool) -> SunburstNode:
        goal_map = self._plan_goal_map()
        student_ids = [record.student_id for record in self._filtered_students if record.student_id in goal_map]
        summary, _selected_count, contributing_count = self._resource_total_for_ids(student_ids, goal_map)
        entries = self._plan_requirement_entries(summary)
        paths: list[tuple[tuple[str, ...], float]] = []

        for entry in entries:
            value = max(0, entry.required - entry.owned) if shortage_only else entry.required
            if value <= 0:
                continue
            item_id = entry.key
            if entry.category == "credits":
                path = ("Currency", entry.name)
            elif entry.category == "level_exp":
                path = ("Level", "Activity Reports", entry.name)
            elif entry.category == "equipment_exp":
                path = ("Equipment", "EXP", entry.name)
            elif entry.category == "weapon_exp":
                path = ("Weapon", "EXP", entry.name)
            elif entry.category == "skill_books":
                path = self._skill_book_sunburst_path(item_id, entry.name)
            elif entry.category == "ex_ooparts":
                path = self._oopart_sunburst_path("EX Skills", item_id, entry.name)
            elif entry.category == "skill_ooparts":
                path = self._oopart_sunburst_path("Basic Skills", item_id, entry.name)
            elif entry.category == "stat_materials":
                path = ("Ability Release", entry.name)
            elif entry.category == "favorite_item_materials":
                path = ("Favorite Item", entry.name)
            elif entry.category == "equipment_materials":
                path = self._equipment_sunburst_path(item_id, entry.name)
            elif entry.category == "star_materials":
                path = ("Stars / Weapon", "Eleph", entry.name)
            else:
                path = ("Other", entry.category, entry.name)
            paths.append((path, value))

        title = "Plan Shortage" if shortage_only else "Plan Required"
        root = self._sunburst_tree_from_paths(title, paths)
        if contributing_count == 0:
            return SunburstNode(label=title)
        return root

    def _stats_sunburst_root(self) -> SunburstNode:
        mode = self._stats_sunburst_mode.currentData() if self._stats_sunburst_mode is not None else None
        if mode == "plan_required":
            return self._resource_sunburst_root(shortage_only=False)
        if mode == "plan_shortage":
            return self._resource_sunburst_root(shortage_only=True)
        return self._collection_sunburst_root(str(mode or "collection_school_role_attack"))

    def _refresh_stats_sunburst(self) -> None:
        if self._stats_sunburst is None or self._stats_sunburst_detail is None:
            return
        root = self._stats_sunburst_root()
        self._stats_sunburst.setRoot(root)
        if not root.children:
            self._stats_sunburst_detail.setText("No matching data for the current mode and filters.")
            return
        total = root.total()
        lines = [f"Total: {total:,.0f}"]
        for child in sorted(root.children, key=lambda node: (-node.total(), node.label.casefold()))[:8]:
            percent = (child.total() / total * 100.0) if total else 0.0
            lines.append(f"{child.label}: {child.total():,.0f} ({percent:.1f}%)")
        self._stats_sunburst_detail.setText("\n".join(lines))

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
        goal_map = self._plan_goal_map()
        planned = sum(1 for record in self._filtered_students if record.student_id in goal_map)
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
        self._refresh_stats_sunburst()

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
            f"크레딧: {summary.credits:,}",
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
        if summary.favorite_item_materials:
            lines.append("Favorite item materials:")
            for key, value in sorted(summary.favorite_item_materials.items(), key=lambda item: (-item[1], item[0])):
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
        self._inventory_quantity_index_cache = _inventory_quantity_index(self._inventory_snapshot or {})
        self._plan = load_plan(self._plan_path)
        self._tactical_data = load_tactical_challenge(self._tactical_path, load_matches=False)
        self._invalidate_plan_caches()
        self._storage_mtimes = self._snapshot_storage_mtimes()
        self._records_by_id = {record.student_id: record for record in self._all_students}
        self._tactical_student_lookup_index = None
        self._filter_options = build_filter_options(self._all_students)
        self._unowned_icon_cache.clear()
        self._apply_filters()
        self._refresh_plan_lists()
        self._refresh_plan_totals()
        self._refresh_stats_tab()
        self._refresh_inventory_tab()
        self._refresh_tactical_tab()

    def _schedule_filter_refresh(self, *_args) -> None:
        self._filter_refresh_timer.start()

    def _schedule_plan_search_refresh(self, *_args) -> None:
        self._plan_search_timer.start()

    def _apply_filters(self) -> None:
        active_search = self._resource_search if hasattr(self, "_resource_search") and self._resource_search.hasFocus() else self._search
        query = _live_line_edit_text(active_search).strip().casefold()
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
        self._filter_button.setText(f"필터 ({active_count})" if active_count else "필터")
        self._rebuild_list()
        self._refresh_stats_tab()
        self._sync_resource_controls_from_students()
        self._refresh_resources_if_visible()

    def _open_filter_dialog(self) -> None:
        dialog = FilterDialog(self, self._filter_options, self._selected_filters, self._ui_scale)
        if dialog.exec() == QDialog.Accepted:
            self._selected_filters = dialog.selected_filters()
            self._apply_filters()

    def _rebuild_list(self) -> None:
        selected_id = self._current_student_id()
        old_cards = dict(self._item_by_id)
        cards: list[StudentCardWidget] = []
        next_by_id: dict[str, StudentCardWidget] = {}

        for record in self._filtered_students:
            card = old_cards.get(record.student_id)
            if card is None:
                card = self._build_student_card(record)
            else:
                self._apply_student_card_record(card, record)
            cards.append(card)
            next_by_id[record.student_id] = card

        self._item_by_id = next_by_id
        self._student_grid.set_cards(cards)

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

    def _remember_thumb_pixmap(self, student_id: str, width: int, height: int, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        key = (student_id, width, height)
        self._thumb_pixmap_cache[key] = pixmap
        self._thumb_pixmap_cache.move_to_end(key)
        while len(self._thumb_pixmap_cache) > self._thumb_pixmap_cache_limit:
            self._thumb_pixmap_cache.popitem(last=False)

    def _cached_thumb_pixmap(self, student_id: str, width: int, height: int, path: str | None = None) -> QPixmap | None:
        key = (student_id, width, height)
        cached = self._thumb_pixmap_cache.get(key)
        if cached is not None:
            self._thumb_pixmap_cache.move_to_end(key)
            return cached
        if not path:
            return None
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None
        self._remember_thumb_pixmap(student_id, width, height, pixmap)
        return pixmap

    def _apply_cached_thumb_to_card(self, card: StudentCardWidget) -> None:
        pixmap = self._cached_thumb_pixmap(card.student_id, self._thumb_width, self._thumb_height)
        if pixmap is not None:
            card.setPixmap(pixmap)

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

    def _visible_thumb_student_ids(self) -> set[str]:
        visible: set[str] = set()
        for attr in ("_student_grid", "_plan_grid", "_resource_scope_grid", "_resource_search_grid"):
            grid = getattr(self, attr, None)
            if grid is not None and grid.isVisible():
                visible.update(grid.visible_card_ids())
        return visible

    def _pop_next_thumb_request(self) -> tuple[str, int, int]:
        visible_ids = self._visible_thumb_student_ids()
        if visible_ids:
            for index, request in enumerate(self._pending_thumb_requests):
                if request[0] in visible_ids:
                    return self._pending_thumb_requests.pop(index)
        return self._pending_thumb_requests.pop(0)

    def _drain_thumb_queue(self) -> None:
        started = 0
        while (
            self._pending_thumb_requests
            and started < self._thumb_batch_size
            and len(self._thumb_loading) < self._thumb_max_in_flight
        ):
            student_id, width, height = self._pop_next_thumb_request()
            request = (student_id, width, height)
            self._pending_thumb_lookup.discard(request)
            if not self._has_any_card_target(student_id):
                continue
            self._queue_thumb(student_id, width, height)
            started += 1
        if not self._pending_thumb_requests or len(self._thumb_loading) >= self._thumb_max_in_flight:
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
        if self._pending_thumb_requests and not self._thumb_pump.isActive():
            self._thumb_pump.start()
        if not path:
            return
        if width != self._thumb_width or height != self._thumb_height:
            return

        pixmap = self._cached_thumb_pixmap(student_id, width, height, path)
        if pixmap is not None and not pixmap.isNull():
            if student_id in self._item_by_id:
                self._student_grid.set_card_pixmap(student_id, pixmap)
            if student_id in self._plan_card_by_id:
                self._plan_grid.set_card_pixmap(student_id, pixmap)
            if student_id in self._resource_scope_card_by_id:
                self._resource_scope_grid.set_card_pixmap(student_id, pixmap)
            if student_id in self._resource_search_card_by_id:
                self._resource_search_grid.set_card_pixmap(student_id, pixmap)

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

