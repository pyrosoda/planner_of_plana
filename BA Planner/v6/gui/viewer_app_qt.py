"""
Standalone Qt-based student viewer process.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "ba_planner.db"
CURRENT_JSON = BASE_DIR / "data" / "current" / "students.json"
PORTRAIT_DIR = BASE_DIR / "templates" / "students_portraits"
THUMB_CACHE_DIR = BASE_DIR / "cache" / "student_thumbs" / "128x128"


@dataclass(slots=True)
class StudentRecord:
    student_id: str
    display_name: str
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

    @property
    def title(self) -> str:
        return self.display_name or self.student_id


def load_students() -> list[StudentRecord]:
    records: list[StudentRecord] = []

    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM students ORDER BY student_id").fetchall()
            conn.close()
            for row in rows:
                records.append(_row_to_record(dict(row)))
            if records:
                return records
        except Exception:
            pass

    if CURRENT_JSON.exists():
        try:
            payload = json.loads(CURRENT_JSON.read_text(encoding="utf-8"))
            for value in payload.values():
                records.append(_row_to_record(value))
        except Exception:
            pass

    return records


def _row_to_record(row: dict) -> StudentRecord:
    return StudentRecord(
        student_id=row.get("student_id") or "",
        display_name=row.get("display_name") or row.get("student_id") or "",
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
    )


def portrait_path(student_id: str) -> Path | None:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = PORTRAIT_DIR / f"{student_id}{ext}"
        if path.exists():
            return path
    return None


def thumb_cache_path(student_id: str) -> Path:
    return THUMB_CACHE_DIR / f"{student_id}.png"


def ensure_thumbnail(student_id: str, size: int = 128) -> Path | None:
    if not HAS_PIL:
        return portrait_path(student_id)

    source = portrait_path(student_id)
    if source is None:
        return None

    target = thumb_cache_path(student_id)
    if target.exists():
        return target

    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
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


class ThumbSignals(QObject):
    loaded = Signal(str, str)


class ThumbTask(QRunnable):
    def __init__(self, student_id: str):
        super().__init__()
        self.student_id = student_id
        self.signals = ThumbSignals()

    def run(self) -> None:
        path = ensure_thumbnail(self.student_id)
        self.signals.loaded.emit(self.student_id, str(path) if path else "")


class StudentViewerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BA Student Viewer")
        self.resize(1320, 820)

        self._pool = QThreadPool.globalInstance()
        self._all_students = load_students()
        self._filtered_students = list(self._all_students)
        self._item_by_id: dict[str, QListWidgetItem] = {}
        self._thumb_loading: set[str] = set()
        self._placeholder_icon = make_placeholder_icon()
        self._large_pixmap: QPixmap | None = None

        self._build_ui()
        self._apply_filters()

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 12, 12, 12)
        header_layout.setSpacing(8)

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

        self._star_filter = QComboBox()
        self._star_filter.addItem("All stars", "all")
        self._star_filter.addItem("5 star", 5)
        self._star_filter.addItem("4 star", 4)
        self._star_filter.addItem("3 star", 3)
        self._star_filter.currentIndexChanged.connect(self._apply_filters)
        header_layout.addWidget(self._star_filter)

        self._weapon_filter = QComboBox()
        self._weapon_filter.addItem("All weapons", "all")
        self._weapon_filter.addItem("Equipped", "weapon_equipped")
        self._weapon_filter.addItem("Unlocked", "weapon_unlocked_not_equipped")
        self._weapon_filter.addItem("None", "no_weapon_system")
        self._weapon_filter.currentIndexChanged.connect(self._apply_filters)
        header_layout.addWidget(self._weapon_filter)

        self._sort_mode = QComboBox()
        self._sort_mode.addItem("Star desc", "star_desc")
        self._sort_mode.addItem("Level desc", "level_desc")
        self._sort_mode.addItem("Name asc", "name_asc")
        self._sort_mode.currentIndexChanged.connect(self._apply_filters)
        header_layout.addWidget(self._sort_mode)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._reload_data)
        header_layout.addWidget(refresh_button)

        layout.addWidget(header)

        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.IconMode)
        self._list.setResizeMode(QListWidget.Adjust)
        self._list.setMovement(QListWidget.Static)
        self._list.setSpacing(10)
        self._list.setIconSize(QSize(128, 128))
        self._list.setGridSize(QSize(170, 190))
        self._list.setUniformItemSizes(True)
        self._list.currentItemChanged.connect(self._on_item_changed)
        splitter.addWidget(self._list)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(14, 14, 14, 14)
        detail_layout.setSpacing(10)

        self._hero = QLabel()
        self._hero.setMinimumSize(320, 320)
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
        stats_layout.setHorizontalSpacing(10)
        stats_layout.setVerticalSpacing(6)
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

        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #0b1118; color: #d8e7f3; }
            QFrame#header { background: #101a24; border: 1px solid #1b2a38; border-radius: 10px; }
            QLabel#title { font-size: 20px; font-weight: 700; color: #73c0ff; }
            QLabel#count { color: #7b95aa; }
            QLineEdit, QComboBox, QPushButton {
                background: #16212d;
                border: 1px solid #243648;
                border-radius: 8px;
                padding: 6px 8px;
            }
            QListWidget {
                background: #0e1620;
                border: 1px solid #1b2a38;
                border-radius: 10px;
                padding: 8px;
            }
            QListWidget::item {
                background: #121c27;
                border: 1px solid #223241;
                border-radius: 10px;
                padding: 8px;
            }
            QListWidget::item:selected {
                background: #173047;
                border: 1px solid #5ab3ff;
            }
            QLabel#hero {
                background: #101a24;
                border: 1px solid #1b2a38;
                border-radius: 14px;
            }
            QLabel#detailName { font-size: 24px; font-weight: 700; }
            QLabel#detailSub { color: #7b95aa; }
            QLabel#statValue { color: #84d0ff; font-weight: 600; }
            """
        )

    def _reload_data(self) -> None:
        self._all_students = load_students()
        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self._search.text().strip().lower()
        star_filter = self._star_filter.currentData()
        weapon_filter = self._weapon_filter.currentData()
        sort_mode = self._sort_mode.currentData()

        items = list(self._all_students)
        if star_filter != "all":
            items = [record for record in items if record.star == int(star_filter)]
        if weapon_filter != "all":
            items = [record for record in items if (record.weapon_state or "") == weapon_filter]
        if query:
            items = [
                record
                for record in items
                if query in record.title.lower() or query in record.student_id.lower()
            ]

        if sort_mode == "star_desc":
            items.sort(key=lambda record: (-record.star, -(record.level or 0), record.title.lower()))
        elif sort_mode == "level_desc":
            items.sort(key=lambda record: (-(record.level or 0), -record.star, record.title.lower()))
        else:
            items.sort(key=lambda record: record.title.lower())

        self._filtered_students = items
        self._rebuild_list()

    def _rebuild_list(self) -> None:
        selected_id = self._current_student_id()
        self._list.clear()
        self._item_by_id.clear()
        self._thumb_loading.clear()

        for record in self._filtered_students:
            item = QListWidgetItem(self._placeholder_icon, f"{record.title}\nLv.{record.level or '-'}  {'*' * record.star}")
            item.setData(Qt.UserRole, record.student_id)
            item.setToolTip(record.student_id)
            self._list.addItem(item)
            self._item_by_id[record.student_id] = item
            self._queue_thumb(record.student_id)

        self._count_label.setText(f"{len(self._filtered_students)} shown / {len(self._all_students)} total")

        if self._filtered_students:
            restore = self._item_by_id.get(selected_id or "")
            self._list.setCurrentItem(restore or self._list.item(0))
        else:
            self._clear_detail()

    def _queue_thumb(self, student_id: str) -> None:
        if student_id in self._thumb_loading:
            return

        self._thumb_loading.add(student_id)
        task = ThumbTask(student_id)
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
        self._subtitle.setText(record.student_id)
        self._stat_labels["level"].setText(str(record.level or "-"))
        self._stat_labels["star"].setText(str(record.star or "-"))
        self._stat_labels["weapon"].setText(record.weapon_state or "-")
        self._stat_labels["weapon_level"].setText(str(record.weapon_level or "-"))
        self._stat_labels["ex"].setText(str(record.ex_skill or "-"))
        self._stat_labels["s1"].setText(str(record.skill1 or "-"))
        self._stat_labels["s2"].setText(str(record.skill2 or "-"))
        self._stat_labels["s3"].setText(str(record.skill3 or "-"))

        self._equip_labels["equip1"].setText(self._equip_text(record.equip1, record.equip1_level))
        self._equip_labels["equip2"].setText(self._equip_text(record.equip2, record.equip2_level))
        self._equip_labels["equip3"].setText(self._equip_text(record.equip3, record.equip3_level))
        self._equip_labels["equip4"].setText(record.equip4 or "-")

        hero_path = portrait_path(record.student_id)
        if hero_path and hero_path.exists():
            pixmap = QPixmap(str(hero_path))
            if not pixmap.isNull():
                self._large_pixmap = pixmap.scaled(
                    self._hero.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
                self._hero.setPixmap(self._large_pixmap)
                return

        self._large_pixmap = None
        self._hero.setPixmap(QPixmap())
        self._hero.setText("No portrait")

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

    @staticmethod
    def _equip_text(tier: str | None, level: int | None) -> str:
        if tier and level is not None:
            return f"{tier} / Lv.{level}"
        if tier:
            return tier
        return "-"


def main() -> int:
    app = QApplication(sys.argv)
    window = StudentViewerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
