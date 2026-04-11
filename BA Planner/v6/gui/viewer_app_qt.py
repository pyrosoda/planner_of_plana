"""
Standalone Qt-based student viewer process.
"""

from __future__ import annotations

import json
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
from core.planning import MAX_TARGET_STAR, StudentGoal, load_plan, save_plan
from core.planning_calc import PlanCostSummary, calculate_goal_cost, calculate_plan_totals
from PySide6.QtCore import QObject, QRect, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QImage, QPainter, QPixmap
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
)

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

PORTRAIT_DIR = BASE_DIR / "templates" / "students_portraits"
UI_FONT_PATH = BASE_DIR / "gui" / "font" / "경기천년제목_Medium.ttf"
POLI_BG_DIR = BASE_DIR / "templates" / "icons" / "temp"
CARD_BUTTON_ASSET = POLI_BG_DIR / "square.png"
MAIN_UI_PALETTE_PATH = BASE_DIR / "gui" / "main_ui_color_palete.txt"
THUMB_STYLE_VERSION = "v4-parallelogram-card"

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


def _attack_color(attack_type: str | None) -> str:
    mapping = {
        "Explosive": "#731c25",
        "Piercing": "#c3b37b",
        "Mystic": "#a5c7da",
        "Sonic": "#ae78b4",
    }
    return mapping.get((attack_type or "").strip(), "#5c6ea8")


def _defense_accent_color(defense_type: str | None) -> str:
    mapping = {
        "Light": _attack_color("Explosive"),
        "Heavy": _attack_color("Piercing"),
        "Special": _attack_color("Mystic"),
        "Elastic": _attack_color("Sonic"),
        "Composite": "#458e8e",
    }
    return mapping.get((defense_type or "").strip(), BORDER)


def _student_divider_colors(record: "StudentRecord") -> tuple[str, str]:
    primary = _attack_color(record.attack_type)
    secondary = _defense_accent_color(record.defense_type)
    if secondary.lower() == primary.lower():
        secondary = _school_accent_color(record.school)
    if secondary.lower() == primary.lower():
        secondary = "#f4f6fb"
    return primary, secondary


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


def _row_to_record(row: dict, owned: bool) -> StudentRecord:
    student_id = row.get("student_id") or ""
    return StudentRecord(
        student_id=student_id,
        display_name=row.get("display_name") or student_meta.field(student_id, "display_name") or student_id or "",
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

    if portrait.width == width and portrait.height == height:
        return portrait
    return portrait.resize((width, height), Image.LANCZOS)


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
    loaded = Signal(str, str)


class ThumbTask(QRunnable):
    def __init__(self, student_id: str, width: int, height: int):
        super().__init__()
        self.student_id = student_id
        self.width = width
        self.height = height
        self.signals = ThumbSignals()

    def run(self) -> None:
        path = ensure_thumbnail(self.student_id, self.width, self.height)
        self.signals.loaded.emit(self.student_id, str(path) if path else "")


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


class StudentViewerWindow(QMainWindow):
    def __init__(self, ui_scale: float):
        super().__init__()
        self._ui_scale = ui_scale
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
        self._thumb_loading: set[str] = set()
        self._placeholder_icon = make_placeholder_icon(self._thumb_width, self._thumb_height)
        self._unowned_icon_cache: dict[str, QIcon] = {}
        self._large_pixmap: QPixmap | None = None
        self._selected_filters: dict[str, set[str]] = {key: set() for key in FILTER_FIELD_ORDER}
        self._filter_options = build_filter_options(self._all_students)
        self._plan_path = get_storage_paths().current_dir / "growth_plan.json"
        self._plan = load_plan(self._plan_path)
        self._plan_editor_guard = False
        self._selected_plan_student_id: str | None = None
        self._plan_inputs: dict[str, QSpinBox] = {}
        self._plan_item_by_id: dict[str, QListWidgetItem] = {}
        self._stats_cards_layout: QGridLayout | None = None
        self._stats_summary_host: QWidget | None = None
        self._card_layout_guard = False

        self._build_ui()
        self._apply_filters()
        self._refresh_plan_lists()
        self._refresh_plan_totals()
        self._refresh_stats_tab()

    def _build_ui(self) -> None:
        root = QWidget(self)
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

        stats_tab = QWidget()
        tabs.addTab(stats_tab, "Statistics")
        self._build_stats_tab(stats_tab)

        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background: {BG}; color: {INK}; }}
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
            QLabel#sectionTitle {{ font-size: {scale_px(16, self._ui_scale)}px; font-weight: 700; color: {INK}; }}
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
        self._search.setPlaceholderText("Search by student name or id")
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
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
        )
        detail_layout.setSpacing(scale_px(12, self._ui_scale))

        hero_wrap = QFrame()
        hero_wrap.setObjectName("heroWrap")
        hero_layout = QVBoxLayout(hero_wrap)
        hero_layout.setContentsMargins(
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
            scale_px(16, self._ui_scale),
        )
        self._hero = QLabel()
        self._hero.setMinimumSize(scale_px(286, self._ui_scale), scale_px(250, self._ui_scale))
        self._hero.setAlignment(Qt.AlignCenter)
        self._hero.setObjectName("hero")
        hero_layout.addWidget(self._hero)
        detail_layout.addWidget(hero_wrap)

        self._name = QLabel("Select a student")
        self._name.setObjectName("detailName")
        detail_layout.addWidget(self._name)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("detailSub")
        detail_layout.addWidget(self._subtitle)

        self._detail_badges = QLabel("")
        self._detail_badges.setObjectName("badge")
        self._detail_badges.setWordWrap(True)
        detail_layout.addWidget(self._detail_badges)

        self._detail_plan_button = ParallelogramButton("Add To Plan", style=self._card_button_style)
        self._detail_plan_button.clicked.connect(self._add_current_student_to_plan)
        detail_action_row = QHBoxLayout()
        detail_action_row.setContentsMargins(0, 0, 0, 0)
        detail_action_row.addWidget(self._detail_plan_button, 0, Qt.AlignLeft)
        detail_action_row.addStretch(1)
        detail_layout.addLayout(detail_action_row)

        quick_grid = QGridLayout()
        quick_grid.setHorizontalSpacing(scale_px(10, self._ui_scale))
        quick_grid.setVerticalSpacing(scale_px(10, self._ui_scale))
        self._quick_metric_labels: dict[str, QLabel] = {}
        for index, (key, label) in enumerate(
            (
                ("level", "Level"),
                ("star", "Star"),
                ("weapon_level", "Weapon Lv"),
                ("ex", "EX Skill"),
                ("hp", "HP"),
                ("atk", "ATK"),
            )
        ):
            card = QFrame()
            card.setObjectName("summaryCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(scale_px(12, self._ui_scale), scale_px(12, self._ui_scale), scale_px(12, self._ui_scale), scale_px(12, self._ui_scale))
            card_layout.setSpacing(scale_px(4, self._ui_scale))
            title_label = QLabel(label)
            title_label.setObjectName("metricLabel")
            value_label = QLabel("-")
            value_label.setObjectName("metricValue")
            card_layout.addWidget(title_label)
            card_layout.addWidget(value_label)
            self._quick_metric_labels[key] = value_label
            quick_grid.addWidget(card, index // 3, index % 3)
        detail_layout.addLayout(quick_grid)

        stats = QGroupBox("Current Progression")
        stats_layout = QGridLayout(stats)
        stats_layout.setHorizontalSpacing(scale_px(12, self._ui_scale))
        stats_layout.setVerticalSpacing(scale_px(8, self._ui_scale))
        self._stat_labels = {}
        stat_rows = [
            ("Level", "level"),
            ("Star", "star"),
            ("Weapon", "weapon"),
            ("Weapon Lv", "weapon_level"),
            ("EX", "ex"),
            ("Skill 1", "s1"),
            ("Skill 2", "s2"),
            ("Skill 3", "s3"),
        ]
        for row, (label, key) in enumerate(stat_rows):
            stats_layout.addWidget(QLabel(label), row, 0)
            value = QLabel("-")
            value.setObjectName("statValue")
            stats_layout.addWidget(value, row, 1)
            self._stat_labels[key] = value
        detail_layout.addWidget(stats)

        equips = QGroupBox("Equipment & Stats")
        equip_form = QFormLayout(equips)
        equip_form.setHorizontalSpacing(scale_px(14, self._ui_scale))
        equip_form.setVerticalSpacing(scale_px(8, self._ui_scale))
        self._equip_labels = {}
        for slot in ("equip1", "equip2", "equip3", "equip4"):
            value = QLabel("-")
            value.setWordWrap(True)
            equip_form.addRow(slot.upper(), value)
            self._equip_labels[slot] = value
        self._detail_stats_line = QLabel("-")
        self._detail_stats_line.setObjectName("detailSub")
        equip_form.addRow("Stats", self._detail_stats_line)
        detail_layout.addWidget(equips)
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

    def eventFilter(self, watched, event) -> bool:
        return super().eventFilter(watched, event)

    def _refresh_card_layout(self) -> None:
        if self._card_layout_guard or not hasattr(self, "_student_grid"):
            return
        size = self._student_grid.current_card_size()
        thumb_width = size.width()
        thumb_height = size.height()
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
            self._thumb_loading.clear()
            for student_id in self._item_by_id:
                self._queue_thumb(student_id)
        finally:
            self._card_layout_guard = False

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

        summary = QLabel("Add students, define target growth, and review required resources in one place.")
        summary.setObjectName("count")
        header_layout.addWidget(summary, 1)

        self._plan_search = QLineEdit()
        self._plan_search.setPlaceholderText("Search students for plan")
        self._plan_search.textChanged.connect(self._refresh_plan_lists)
        header_layout.addWidget(self._plan_search, 2)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        all_panel = QFrame()
        all_panel.setObjectName("panel")
        all_layout = QVBoxLayout(all_panel)
        all_layout.setContentsMargins(scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale))
        all_layout.setSpacing(scale_px(10, self._ui_scale))
        title_all = QLabel("Student Library")
        title_all.setObjectName("sectionTitle")
        all_layout.addWidget(title_all)
        self._plan_all_list = QListWidget()
        self._plan_all_list.currentItemChanged.connect(self._on_plan_all_item_changed)
        all_layout.addWidget(self._plan_all_list, 1)
        add_button = ParallelogramButton("Add To Plan", style=self._card_button_style)
        add_button.clicked.connect(self._add_selected_student_to_plan)
        add_button_row = QHBoxLayout()
        add_button_row.setContentsMargins(0, 0, 0, 0)
        add_button_row.addWidget(add_button, 0, Qt.AlignLeft)
        add_button_row.addStretch(1)
        all_layout.addLayout(add_button_row)
        splitter.addWidget(all_panel)

        plan_panel = QFrame()
        plan_panel.setObjectName("panel")
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale), scale_px(14, self._ui_scale))
        plan_layout.setSpacing(scale_px(10, self._ui_scale))
        title_plan = QLabel("Planned Students")
        title_plan.setObjectName("sectionTitle")
        plan_layout.addWidget(title_plan)
        self._plan_list = QListWidget()
        self._plan_list.currentItemChanged.connect(self._on_plan_item_changed)
        plan_layout.addWidget(self._plan_list, 1)
        plan_buttons = QHBoxLayout()
        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_selected_plan_student)
        plan_buttons.addWidget(remove_button)
        open_button = QPushButton("Open In Viewer")
        open_button.clicked.connect(self._focus_selected_plan_student_in_viewer)
        plan_buttons.addWidget(open_button)
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

        form_wrap = QWidget()
        form_wrap_layout = QGridLayout(form_wrap)
        form_wrap_layout.setContentsMargins(0, 0, 0, 0)
        form_wrap_layout.setHorizontalSpacing(scale_px(12, self._ui_scale))
        form_wrap_layout.setVerticalSpacing(scale_px(12, self._ui_scale))

        sections = (
            (
                "Progression",
                (
                    ("target_level", "Target Level", 0, 100),
                    ("target_star", "Target Star", 0, MAX_TARGET_STAR),
                    ("target_ex_skill", "Target EX", 0, 5),
                    ("target_weapon_level", "Target Weapon Lv", 0, 90),
                    ("target_weapon_star", "Target Weapon Star", 0, 4),
                ),
            ),
            (
                "Skills",
                (
                    ("target_skill1", "Target Skill 1", 0, 10),
                    ("target_skill2", "Target Skill 2", 0, 10),
                    ("target_skill3", "Target Skill 3", 0, 10),
                ),
            ),
            (
                "Equipment",
                (
                    ("target_equip1_tier", "Target Equip 1", 0, 10),
                    ("target_equip2_tier", "Target Equip 2", 0, 10),
                    ("target_equip3_tier", "Target Equip 3", 0, 10),
                ),
            ),
            (
                "Stats",
                (
                    ("target_stat_hp", "Target Stat HP", 0, 25),
                    ("target_stat_atk", "Target Stat ATK", 0, 25),
                    ("target_stat_heal", "Target Stat HEAL", 0, 25),
                ),
            ),
        )
        for index, (section_title, fields) in enumerate(sections):
            box = QGroupBox(section_title)
            form = QFormLayout(box)
            form.setHorizontalSpacing(scale_px(14, self._ui_scale))
            form.setVerticalSpacing(scale_px(8, self._ui_scale))
            for field_name, label, minimum, maximum in fields:
                spin = QSpinBox()
                spin.setRange(minimum, maximum)
                spin.setSpecialValueText("-")
                spin.valueChanged.connect(self._on_plan_editor_changed)
                self._plan_inputs[field_name] = spin
                form.addRow(label, spin)
            form_wrap_layout.addWidget(box, index // 2, index % 2)
        editor_layout.addWidget(form_wrap)

        student_result_box = QGroupBox("Selected Student Resource Summary")
        student_result_layout = QVBoxLayout(student_result_box)
        self._plan_student_summary = QLabel("No student selected")
        self._plan_student_summary.setWordWrap(True)
        self._plan_student_summary.setObjectName("filterSummary")
        student_result_layout.addWidget(self._plan_student_summary)
        editor_layout.addWidget(student_result_box)

        totals_frame = QGroupBox("Total Resources")
        totals_layout = QVBoxLayout(totals_frame)
        totals_layout.setSpacing(scale_px(8, self._ui_scale))
        self._plan_total_summary = QLabel("")
        self._plan_total_summary.setWordWrap(True)
        totals_layout.addWidget(self._plan_total_summary)
        editor_layout.addWidget(totals_frame)
        editor_layout.addStretch(1)
        splitter.addWidget(editor_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 2)
        splitter.setStretchFactor(2, 3)

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

    def _refresh_plan_lists(self) -> None:
        if not hasattr(self, "_plan_all_list"):
            return
        query = self._plan_search.text().strip().lower()
        current_all = self._plan_current_all_student_id()
        current_plan = self._selected_plan_student_id
        goal_map = self._plan_goal_map()

        self._plan_all_list.clear()
        for record in sorted(self._all_students, key=lambda item: item.title.lower()):
            if query and query not in record.title.lower() and query not in record.student_id.lower():
                continue
            status = "Planned" if record.student_id in goal_map else ("Owned" if record.owned else "Unowned")
            item = QListWidgetItem(f"{record.title}\n{status}")
            item.setData(Qt.UserRole, record.student_id)
            if record.student_id in goal_map:
                item.setForeground(QColor("#84d0ff"))
            self._plan_all_list.addItem(item)

        self._plan_list.clear()
        self._plan_item_by_id.clear()
        for goal in sorted(self._plan.goals, key=lambda entry: self._records_by_id.get(entry.student_id).title.lower() if entry.student_id in self._records_by_id else entry.student_id):
            record = self._records_by_id.get(goal.student_id)
            if record is None:
                continue
            item = QListWidgetItem(record.title)
            item.setData(Qt.UserRole, record.student_id)
            self._plan_list.addItem(item)
            self._plan_item_by_id[record.student_id] = item

        self._restore_selection(self._plan_all_list, current_all)
        self._restore_selection(self._plan_list, current_plan)

    @staticmethod
    def _restore_selection(widget: QListWidget, student_id: str | None) -> None:
        if not student_id:
            return
        for index in range(widget.count()):
            item = widget.item(index)
            if item.data(Qt.UserRole) == student_id:
                widget.setCurrentItem(item)
                break

    def _plan_current_all_student_id(self) -> str | None:
        item = self._plan_all_list.currentItem() if hasattr(self, "_plan_all_list") else None
        return item.data(Qt.UserRole) if item else None

    def _on_plan_all_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            student_id = str(current.data(Qt.UserRole))
            self._selected_plan_student_id = student_id if student_id in self._plan_goal_map() else None
            self._load_plan_student(student_id)

    def _on_plan_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is not None:
            self._selected_plan_student_id = str(current.data(Qt.UserRole))
            self._load_plan_student(self._selected_plan_student_id)

    def _add_selected_student_to_plan(self) -> None:
        student_id = self._plan_current_all_student_id()
        if not student_id:
            return
        self._get_or_create_goal(student_id)
        self._selected_plan_student_id = student_id
        self._save_plan()
        self._refresh_plan_lists()
        self._restore_selection(self._plan_list, student_id)
        self._update_plan_student_summary(student_id)
        self._refresh_plan_totals()

    def _remove_selected_plan_student(self) -> None:
        student_id = self._selected_plan_student_id
        if not student_id:
            item = self._plan_list.currentItem()
            student_id = str(item.data(Qt.UserRole)) if item else None
        if not student_id:
            return
        self._plan.goals = [goal for goal in self._plan.goals if goal.student_id != student_id]
        self._selected_plan_student_id = None
        self._save_plan()
        self._refresh_plan_lists()
        self._clear_plan_editor()
        self._refresh_plan_totals()

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
            self._plan_current.setText(
                f"{record.student_id}  |  Current Lv.{record.level or 0}  Star {record.star}  EX {record.ex_skill or 0}  Skills {record.skill1 or 0}/{record.skill2 or 0}/{record.skill3 or 0}  Stats {record.stat_hp or 0}/{record.stat_atk or 0}/{record.stat_heal or 0}"
            )
            for field_name, spin in self._plan_inputs.items():
                value = getattr(goal, field_name, None) if goal else None
                spin.setValue(int(value) if value else 0)
        finally:
            self._plan_editor_guard = False
        self._update_plan_student_summary(student_id)

    def _clear_plan_editor(self) -> None:
        self._plan_editor_guard = True
        try:
            self._plan_name.setText("Select a student")
            self._plan_current.setText("")
            for spin in self._plan_inputs.values():
                spin.setValue(0)
        finally:
            self._plan_editor_guard = False
        self._plan_student_summary.setText("No student selected")

    def _on_plan_editor_changed(self) -> None:
        if self._plan_editor_guard:
            return
        student_id = self._selected_plan_student_id or self._plan_current_all_student_id()
        if not student_id:
            return
        goal = self._get_or_create_goal(student_id)
        for field_name, spin in self._plan_inputs.items():
            setattr(goal, field_name, int(spin.value()) or None)
        self._selected_plan_student_id = student_id
        self._save_plan()
        self._refresh_plan_lists()
        self._update_plan_student_summary(student_id)
        self._refresh_plan_totals()

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
        self._refresh_plan_totals()

    def _refresh_plan_totals(self) -> None:
        if not hasattr(self, "_plan_total_summary"):
            return
        total = calculate_plan_totals(self._records_by_id, self._plan)
        self._plan_total_summary.setText(
            f"{len(self._plan.goals)} students in plan\n{self._format_cost_summary(total)}"
        )

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
        if summary.ex_ooparts:
            lines.append("EX ooparts:")
            for key, value in sorted(summary.ex_ooparts.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"- {key}: {value}")
        if summary.skill_ooparts:
            lines.append("Skill ooparts:")
            for key, value in sorted(summary.skill_ooparts.items(), key=lambda item: (-item[1], item[0])):
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
        self._records_by_id = {record.student_id: record for record in self._all_students}
        self._filter_options = build_filter_options(self._all_students)
        self._unowned_icon_cache.clear()
        self._apply_filters()
        self._refresh_plan_lists()
        self._refresh_plan_totals()
        self._refresh_stats_tab()

    def _apply_filters(self) -> None:
        query = self._search.text().strip().lower()
        sort_mode = self._sort_mode.currentData()

        items = [
            record
            for record in self._all_students
            if matches_student_filters(record, self._selected_filters, query)
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
        self._filter_summary.setText(summarize_filters(self._selected_filters, self._filter_options))
        active_count = active_filter_count(self._selected_filters)
        self._filter_button.setText(f"Filters ({active_count})" if active_count else "Filters")
        self._rebuild_list()
        self._refresh_stats_tab()

    def _open_filter_dialog(self) -> None:
        dialog = FilterDialog(self, self._filter_options, self._selected_filters, self._ui_scale)
        if dialog.exec() == QDialog.Accepted:
            self._selected_filters = dialog.selected_filters()
            self._apply_filters()

    def _rebuild_list(self) -> None:
        selected_id = self._current_student_id()
        self._student_grid.clear_cards()
        self._item_by_id.clear()
        self._thumb_loading.clear()

        for record in self._filtered_students:
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
            self._student_grid.add_card(card)
            self._item_by_id[record.student_id] = card
            self._queue_thumb(record.student_id)

        owned_count = sum(1 for record in self._all_students if record.owned)
        self._count_label.setText(f"{len(self._filtered_students)} shown / {len(self._all_students)} total ({owned_count} owned)")

        if self._filtered_students:
            restore_id = selected_id if selected_id in self._item_by_id else self._filtered_students[0].student_id
            self._student_grid.set_current_card(restore_id)
        else:
            self._student_grid.set_current_card(None)
            self._clear_detail()

    def _queue_thumb(self, student_id: str) -> None:
        if student_id in self._thumb_loading:
            return

        self._thumb_loading.add(student_id)
        task = ThumbTask(student_id, self._thumb_width, self._thumb_height)
        task.signals.loaded.connect(self._apply_thumb)
        self._pool.start(task)

    def _apply_thumb(self, student_id: str, path: str) -> None:
        self._thumb_loading.discard(student_id)
        card = self._item_by_id.get(student_id)
        if card is None or not path:
            return

        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self._student_grid.set_card_pixmap(student_id, pixmap)

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
        self._name.setText(record.title)
        self._subtitle.setText(f"{record.student_id}  |  {'Owned' if record.owned else 'Not owned'}")
        badges = [record.school or "Unknown", record.combat_class or "-", record.attack_type or "-", f"Star {record.star or 0}"]
        self._detail_badges.setText("   ".join(badges))
        self._detail_plan_button.setText("Open In Plan" if record.student_id in self._plan_goal_map() else "Add To Plan")
        self._stat_labels["level"].setText(str(record.level or "-") if record.owned else "")
        self._stat_labels["star"].setText(str(record.star or "-") if record.owned else "")
        self._stat_labels["weapon"].setText(record.weapon_state or "-" if record.owned else "")
        self._stat_labels["weapon_level"].setText(str(record.weapon_level or "-") if record.owned else "")
        self._stat_labels["ex"].setText(str(record.ex_skill or "-") if record.owned else "")
        self._stat_labels["s1"].setText(str(record.skill1 or "-") if record.owned else "")
        self._stat_labels["s2"].setText(str(record.skill2 or "-") if record.owned else "")
        self._stat_labels["s3"].setText(str(record.skill3 or "-") if record.owned else "")
        self._quick_metric_labels["level"].setText(str(record.level or "-") if record.owned else "-")
        self._quick_metric_labels["star"].setText(str(record.star or "-") if record.owned else "-")
        self._quick_metric_labels["weapon_level"].setText(str(record.weapon_level or "-") if record.owned else "-")
        self._quick_metric_labels["ex"].setText(str(record.ex_skill or "-") if record.owned else "-")
        self._quick_metric_labels["hp"].setText(f"{record.stat_hp or 0:,}" if record.owned else "-")
        self._quick_metric_labels["atk"].setText(f"{record.stat_atk or 0:,}" if record.owned else "-")

        self._equip_labels["equip1"].setText(self._equip_text(record.equip1, record.equip1_level) if record.owned else "")
        self._equip_labels["equip2"].setText(self._equip_text(record.equip2, record.equip2_level) if record.owned else "")
        self._equip_labels["equip3"].setText(self._equip_text(record.equip3, record.equip3_level) if record.owned else "")
        self._equip_labels["equip4"].setText((record.equip4 or "-") if record.owned else "")
        self._detail_stats_line.setText(
            f"HP {record.stat_hp or 0:,}   |   ATK {record.stat_atk or 0:,}   |   HEAL {record.stat_heal or 0:,}"
            if record.owned
            else "No progression data available"
        )

        hero_path = portrait_path(record.student_id)
        if hero_path and hero_path.exists():
            pixmap = QPixmap(str(hero_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self._hero.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self._large_pixmap = (
                    _make_dimmed_pixmap(scaled, self._hero.width(), self._hero.height())
                    if not record.owned
                    else scaled
                )
                self._hero.setPixmap(self._large_pixmap)
                self._hero.setText("")
                return

        self._large_pixmap = None
        if record.owned:
            self._hero.setPixmap(QPixmap())
            self._hero.setText("No portrait")
        else:
            self._hero.setPixmap(self._unowned_icon(record.student_id).pixmap(self._hero.size()))
            self._hero.setText("")

    def _clear_detail(self) -> None:
        self._name.setText("Select a student")
        self._subtitle.setText("")
        self._detail_badges.setText("")
        self._detail_plan_button.setText("Add To Plan")
        for label in self._stat_labels.values():
            label.setText("-")
        for label in self._quick_metric_labels.values():
            label.setText("-")
        for label in self._equip_labels.values():
            label.setText("-")
        self._detail_stats_line.setText("-")
        self._hero.setPixmap(QPixmap())
        self._hero.setText("No selection")

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
