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

import core.student_meta as student_meta
from core.config import get_storage_paths
from core.planning import StudentGoal, load_plan, save_plan
from core.planning_calc import PlanCostSummary, calculate_goal_cost, calculate_plan_totals
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
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

BASE_DIR = Path(__file__).resolve().parent.parent
PORTRAIT_DIR = BASE_DIR / "templates" / "students_portraits"

from gui.student_filters import (
    FILTER_FIELD_LABELS,
    FILTER_FIELD_ORDER,
    active_filter_count,
    build_filter_options,
    matches_student_filters,
    summarize_filters,
)
from gui.student_stats import StatsDialog


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


def thumb_cache_path(student_id: str, size: int) -> Path:
    return BASE_DIR / "cache" / "student_thumbs" / f"{size}x{size}" / f"{student_id}.png"


def ensure_thumbnail(student_id: str, size: int = 128) -> Path | None:
    if not HAS_PIL:
        return portrait_path(student_id)

    source = portrait_path(student_id)
    if source is None:
        return None

    target = thumb_cache_path(student_id, size)
    if target.exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as img:
            prepared = img.convert("RGBA")
            prepared.thumbnail((size, size), Image.LANCZOS)

            canvas = Image.new("RGBA", (size, size), (16, 22, 30, 255))
            offset = ((size - prepared.width) // 2, (size - prepared.height) // 2)
            canvas.alpha_composite(prepared, offset)
            canvas.convert("RGB").save(target, format="PNG")
        return target
    except Exception:
        return source


def make_placeholder_icon(size: int = 128) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#1a2430"))
    return QIcon(pixmap)


def make_unowned_icon(student_id: str, size: int = 128) -> QIcon:
    source = portrait_path(student_id)
    if source and source.exists():
        pixmap = QPixmap(str(source))
        if not pixmap.isNull():
            return QIcon(_make_dimmed_pixmap(pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation), size))
    return QIcon(_make_dimmed_pixmap(QPixmap(size, size), size, fill="#1a2430"))


def _make_dimmed_pixmap(pixmap: QPixmap, size: int, fill: str | None = None) -> QPixmap:
    canvas = QPixmap(size, size)
    canvas.fill(QColor(fill or "#101a24"))
    painter = QPainter(canvas)
    x = max(0, (size - pixmap.width()) // 2)
    y = max(0, (size - pixmap.height()) // 2)
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
    def __init__(self, student_id: str, size: int):
        super().__init__()
        self.student_id = student_id
        self.size = size
        self.signals = ThumbSignals()

    def run(self) -> None:
        path = ensure_thumbnail(self.student_id, self.size)
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
        self._thumb_size = scale_px(156, ui_scale)
        self._grid_width = scale_px(212, ui_scale)
        self._grid_height = scale_px(244, ui_scale)
        self.setWindowTitle("BA Student Viewer")
        self.resize(scale_px(1560, ui_scale), scale_px(980, ui_scale))

        self._pool = QThreadPool.globalInstance()
        self._all_students = load_students()
        self._records_by_id = {record.student_id: record for record in self._all_students}
        self._filtered_students = list(self._all_students)
        self._item_by_id: dict[str, QListWidgetItem] = {}
        self._thumb_loading: set[str] = set()
        self._placeholder_icon = make_placeholder_icon(self._thumb_size)
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

        self._build_ui()
        self._apply_filters()
        self._refresh_plan_lists()
        self._refresh_plan_totals()

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
        outer_layout.addWidget(tabs, 1)

        viewer_tab = QWidget()
        tabs.addTab(viewer_tab, "Viewer")

        layout = QVBoxLayout(viewer_tab)
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

        title = QLabel("BA Student Viewer")
        title.setObjectName("title")
        header_layout.addWidget(title)

        self._count_label = QLabel("")
        self._count_label.setObjectName("count")
        header_layout.addWidget(self._count_label)
        header_layout.addStretch(1)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search name or id")
        self._search.textChanged.connect(self._apply_filters)
        header_layout.addWidget(self._search, 2)

        self._show_unowned = QCheckBox("Show unowned")
        self._show_unowned.setChecked(True)
        self._show_unowned.stateChanged.connect(self._apply_filters)
        header_layout.addWidget(self._show_unowned)

        self._filter_button = QPushButton("Filters")
        self._filter_button.clicked.connect(self._open_filter_dialog)
        header_layout.addWidget(self._filter_button)

        self._stats_button = QPushButton("Stats")
        self._stats_button.clicked.connect(self._open_stats_dialog)
        header_layout.addWidget(self._stats_button)

        self._sort_mode = QComboBox()
        self._sort_mode.addItem("Star desc", "star_desc")
        self._sort_mode.addItem("Star asc", "star_asc")
        self._sort_mode.addItem("Level desc", "level_desc")
        self._sort_mode.addItem("Name asc", "name_asc")
        self._sort_mode.currentIndexChanged.connect(self._apply_filters)
        header_layout.addWidget(self._sort_mode)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_data)
        header_layout.addWidget(refresh_button)

        layout.addWidget(header)

        self._filter_summary = QLabel("No filters applied")
        self._filter_summary.setWordWrap(True)
        self._filter_summary.setObjectName("filterSummary")
        layout.addWidget(self._filter_summary)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setSpacing(scale_px(12, self._ui_scale))
        self._list.setIconSize(QSize(self._thumb_size, self._thumb_size))
        self._list.setGridSize(QSize(self._grid_width, self._grid_height))
        self._list.setUniformItemSizes(True)
        self._list.currentItemChanged.connect(self._on_item_changed)
        splitter.addWidget(self._list)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
            scale_px(18, self._ui_scale),
        )
        detail_layout.setSpacing(scale_px(12, self._ui_scale))

        self._hero = QLabel()
        self._hero.setMinimumSize(scale_px(420, self._ui_scale), scale_px(420, self._ui_scale))
        self._hero.setAlignment(Qt.AlignCenter)
        self._hero.setObjectName("hero")
        detail_layout.addWidget(self._hero)

        self._name = QLabel("Select a student")
        self._name.setObjectName("detailName")
        detail_layout.addWidget(self._name)

        self._subtitle = QLabel("")
        self._subtitle.setObjectName("detailSub")
        detail_layout.addWidget(self._subtitle)

        stats = QFrame()
        stats_layout = QGridLayout(stats)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setHorizontalSpacing(scale_px(12, self._ui_scale))
        stats_layout.setVerticalSpacing(scale_px(8, self._ui_scale))
        self._stat_labels: dict[str, QLabel] = {}
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

        equips = QFrame()
        equip_form = QFormLayout(equips)
        equip_form.setContentsMargins(0, 0, 0, 0)
        equip_form.setHorizontalSpacing(scale_px(14, self._ui_scale))
        equip_form.setVerticalSpacing(scale_px(8, self._ui_scale))
        self._equip_labels: dict[str, QLabel] = {}
        for slot in ("equip1", "equip2", "equip3", "equip4"):
            value = QLabel("-")
            value.setWordWrap(True)
            equip_form.addRow(slot.upper(), value)
            self._equip_labels[slot] = value
        detail_layout.addWidget(equips)
        detail_layout.addStretch(1)

        splitter.addWidget(detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        plan_tab = QWidget()
        tabs.addTab(plan_tab, "Plan")
        self._build_plan_tab(plan_tab)

        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{ background: #0b1118; color: #d8e7f3; }}
            QFrame#header {{ background: #101a24; border: 1px solid #1b2a38; border-radius: {scale_px(12, self._ui_scale)}px; }}
            QLabel#title {{ font-size: {scale_px(22, self._ui_scale)}px; font-weight: 700; color: #73c0ff; }}
            QLabel#count {{ color: #7b95aa; }}
            QLabel#filterSummary {{ color: #7b95aa; padding-left: {scale_px(4, self._ui_scale)}px; }}
            QLineEdit, QComboBox, QPushButton {{
                background: #16212d;
                border: 1px solid #243648;
                border-radius: {scale_px(9, self._ui_scale)}px;
                padding: {scale_px(8, self._ui_scale)}px {scale_px(10, self._ui_scale)}px;
                min-height: {scale_px(22, self._ui_scale)}px;
            }}
            QListWidget {{
                background: #0e1620;
                border: 1px solid #1b2a38;
                border-radius: {scale_px(12, self._ui_scale)}px;
                padding: {scale_px(10, self._ui_scale)}px;
            }}
            QListWidget::item {{
                background: #121c27;
                border: 1px solid #223241;
                border-radius: {scale_px(12, self._ui_scale)}px;
                padding: {scale_px(10, self._ui_scale)}px;
            }}
            QListWidget::item:selected {{
                background: #173047;
                border: 1px solid #5ab3ff;
            }}
            QLabel#hero {{
                background: #101a24;
                border: 1px solid #1b2a38;
                border-radius: {scale_px(16, self._ui_scale)}px;
            }}
            QLabel#detailName {{ font-size: {scale_px(28, self._ui_scale)}px; font-weight: 700; }}
            QLabel#detailSub {{ color: #7b95aa; }}
            QLabel#statValue {{ color: #84d0ff; font-weight: 600; }}
            """
        )

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

        title = QLabel("Growth Planner")
        title.setObjectName("title")
        header_layout.addWidget(title)

        summary = QLabel("Choose any student, including unowned, and set target growth values.")
        summary.setObjectName("count")
        header_layout.addWidget(summary, 1)

        self._plan_search = QLineEdit()
        self._plan_search.setPlaceholderText("Search students for plan")
        self._plan_search.textChanged.connect(self._refresh_plan_lists)
        header_layout.addWidget(self._plan_search, 2)
        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        all_panel = QWidget()
        all_layout = QVBoxLayout(all_panel)
        all_layout.setContentsMargins(0, 0, 0, 0)
        all_layout.setSpacing(scale_px(10, self._ui_scale))
        all_layout.addWidget(QLabel("All students"))
        self._plan_all_list = QListWidget()
        self._plan_all_list.currentItemChanged.connect(self._on_plan_all_item_changed)
        all_layout.addWidget(self._plan_all_list, 1)
        add_button = QPushButton("Add To Plan")
        add_button.clicked.connect(self._add_selected_student_to_plan)
        all_layout.addWidget(add_button)
        splitter.addWidget(all_panel)

        plan_panel = QWidget()
        plan_layout = QVBoxLayout(plan_panel)
        plan_layout.setContentsMargins(0, 0, 0, 0)
        plan_layout.setSpacing(scale_px(10, self._ui_scale))
        plan_layout.addWidget(QLabel("Planned students"))
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

        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(scale_px(10, self._ui_scale))

        self._plan_name = QLabel("Select a student")
        self._plan_name.setObjectName("detailName")
        editor_layout.addWidget(self._plan_name)

        self._plan_current = QLabel("")
        self._plan_current.setObjectName("detailSub")
        editor_layout.addWidget(self._plan_current)

        form_frame = QFrame()
        form = QFormLayout(form_frame)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(scale_px(14, self._ui_scale))
        form.setVerticalSpacing(scale_px(8, self._ui_scale))
        for field_name, label, minimum, maximum in (
            ("target_level", "Target Level", 0, 100),
            ("target_star", "Target Star", 0, 8),
            ("target_ex_skill", "Target EX", 0, 5),
            ("target_skill1", "Target Skill 1", 0, 10),
            ("target_skill2", "Target Skill 2", 0, 10),
            ("target_skill3", "Target Skill 3", 0, 10),
            ("target_weapon_level", "Target Weapon Lv", 0, 90),
            ("target_weapon_star", "Target Weapon Star", 0, 4),
            ("target_equip1_tier", "Target Equip 1", 0, 10),
            ("target_equip2_tier", "Target Equip 2", 0, 10),
            ("target_equip3_tier", "Target Equip 3", 0, 10),
            ("target_bound_level", "Target Bound", 0, 50),
        ):
            spin = QSpinBox()
            spin.setRange(minimum, maximum)
            spin.setSpecialValueText("-")
            spin.valueChanged.connect(self._on_plan_editor_changed)
            self._plan_inputs[field_name] = spin
            form.addRow(label, spin)
        editor_layout.addWidget(form_frame)

        self._plan_student_summary = QLabel("No student selected")
        self._plan_student_summary.setWordWrap(True)
        self._plan_student_summary.setObjectName("filterSummary")
        editor_layout.addWidget(self._plan_student_summary)

        totals_frame = QFrame()
        totals_layout = QVBoxLayout(totals_frame)
        totals_layout.setContentsMargins(0, 0, 0, 0)
        totals_layout.setSpacing(scale_px(8, self._ui_scale))
        totals_layout.addWidget(QLabel("Plan totals"))
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
        item = self._item_by_id.get(self._selected_plan_student_id)
        if item is not None:
            self._list.setCurrentItem(item)

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
                f"{record.student_id}  |  Current Lv.{record.level or 0}  Star {record.star}  EX {record.ex_skill or 0}  Skills {record.skill1 or 0}/{record.skill2 or 0}/{record.skill3 or 0}"
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

    def _refresh_plan_totals(self) -> None:
        if not hasattr(self, "_plan_total_summary"):
            return
        total = calculate_plan_totals(self._records_by_id, self._plan)
        self._plan_total_summary.setText(
            f"{len(self._plan.goals)} students in plan\n{self._format_cost_summary(total)}"
        )

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

    def _open_filter_dialog(self) -> None:
        dialog = FilterDialog(self, self._filter_options, self._selected_filters, self._ui_scale)
        if dialog.exec() == QDialog.Accepted:
            self._selected_filters = dialog.selected_filters()
            self._apply_filters()

    def _open_stats_dialog(self) -> None:
        dialog = StatsDialog(self, self._filtered_students, self._ui_scale)
        dialog.exec()

    def _rebuild_list(self) -> None:
        selected_id = self._current_student_id()
        self._list.clear()
        self._item_by_id.clear()
        self._thumb_loading.clear()

        for record in self._filtered_students:
            subtitle = f"Lv.{record.level or '-'}  {'*' * record.star}" if record.owned else "Not owned"
            icon = self._placeholder_icon if record.owned else self._unowned_icon(record.student_id)
            item = QListWidgetItem(icon, f"{record.title}\n{subtitle}")
            item.setData(Qt.UserRole, record.student_id)
            item.setToolTip(record.student_id)
            if not record.owned:
                item.setForeground(QColor("#7b95aa"))
            self._list.addItem(item)
            self._item_by_id[record.student_id] = item
            if record.owned:
                self._queue_thumb(record.student_id)

        owned_count = sum(1 for record in self._all_students if record.owned)
        self._count_label.setText(f"{len(self._filtered_students)} shown / {len(self._all_students)} total ({owned_count} owned)")

        if self._filtered_students:
            restore = self._item_by_id.get(selected_id or "")
            self._list.setCurrentItem(restore or self._list.item(0))
        else:
            self._clear_detail()

    def _queue_thumb(self, student_id: str) -> None:
        if student_id in self._thumb_loading:
            return

        self._thumb_loading.add(student_id)
        task = ThumbTask(student_id, self._thumb_size)
        task.signals.loaded.connect(self._apply_thumb)
        self._pool.start(task)

    def _apply_thumb(self, student_id: str, path: str) -> None:
        self._thumb_loading.discard(student_id)
        item = self._item_by_id.get(student_id)
        if item is None or not path:
            return

        icon = QIcon(path)
        if not icon.isNull():
            item.setIcon(icon)

    def _on_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self._clear_detail()
            return

        student_id = current.data(Qt.UserRole)
        record = next((entry for entry in self._filtered_students if entry.student_id == student_id), None)
        if record is None:
            self._clear_detail()
            return

        self._populate_detail(record)

    def _populate_detail(self, record: StudentRecord) -> None:
        self._name.setText(record.title)
        self._subtitle.setText(f"{record.student_id}  |  {'Owned' if record.owned else 'Not owned'}")
        self._stat_labels["level"].setText(str(record.level or "-") if record.owned else "")
        self._stat_labels["star"].setText(str(record.star or "-") if record.owned else "")
        self._stat_labels["weapon"].setText(record.weapon_state or "-" if record.owned else "")
        self._stat_labels["weapon_level"].setText(str(record.weapon_level or "-") if record.owned else "")
        self._stat_labels["ex"].setText(str(record.ex_skill or "-") if record.owned else "")
        self._stat_labels["s1"].setText(str(record.skill1 or "-") if record.owned else "")
        self._stat_labels["s2"].setText(str(record.skill2 or "-") if record.owned else "")
        self._stat_labels["s3"].setText(str(record.skill3 or "-") if record.owned else "")

        self._equip_labels["equip1"].setText(self._equip_text(record.equip1, record.equip1_level) if record.owned else "")
        self._equip_labels["equip2"].setText(self._equip_text(record.equip2, record.equip2_level) if record.owned else "")
        self._equip_labels["equip3"].setText(self._equip_text(record.equip3, record.equip3_level) if record.owned else "")
        self._equip_labels["equip4"].setText((record.equip4 or "-") if record.owned else "")

        hero_path = portrait_path(record.student_id)
        if hero_path and hero_path.exists():
            pixmap = QPixmap(str(hero_path))
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self._hero.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self._large_pixmap = _make_dimmed_pixmap(scaled, max(self._hero.width(), self._hero.height())) if not record.owned else scaled
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
        for label in self._stat_labels.values():
            label.setText("-")
        for label in self._equip_labels.values():
            label.setText("-")
        self._hero.setPixmap(QPixmap())
        self._hero.setText("No selection")

    def _current_student_id(self) -> str | None:
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _unowned_icon(self, student_id: str) -> QIcon:
        cached = self._unowned_icon_cache.get(student_id)
        if cached is None:
            cached = make_unowned_icon(student_id, self._thumb_size)
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
    window = StudentViewerWindow(get_qt_ui_scale(app, base_width=1680, base_height=1080))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
