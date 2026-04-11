"""
Scaled Tk student viewer used as a fallback when the Qt viewer is unavailable.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import tkinter as tk
import hashlib
from pathlib import Path
from typing import Optional

from core.config import get_storage_paths
from gui.student_filters import (
    FILTER_FIELD_LABELS,
    FILTER_FIELD_ORDER,
    active_filter_count,
    build_filter_options,
    enrich_student_row,
    matches_student_filters,
    summarize_filters,
)
from gui.ui_scale import get_ui_scale, scale_font, scale_px

try:
    from PIL import Image, ImageOps, ImageTk

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates" / "students_portraits"
POLI_BG_DIR = BASE_DIR / "templates" / "icons" / "temp"
POLI_BG_TEXTURES = sorted(POLI_BG_DIR.glob("UITex_BGPoliLight_*.png"))

C = {
    "bg": "#080c14",
    "surface": "#0e1520",
    "card": "#111927",
    "card_h": "#16202e",
    "border": "#1a2e40",
    "accent": "#4aa8e0",
    "accent2": "#6ec6ff",
    "gold": "#f0c040",
    "text": "#d6eaf8",
    "sub": "#5c8aaa",
    "dim": "#2a3d52",
    "star5": "#f0c040",
    "star4": "#b388ff",
    "star3": "#4aa8e0",
    "star2": "#3dbf7a",
    "star1": "#e85a5a",
    "t1": "#90c090",
    "t2": "#4aa8e0",
    "t3": "#b388ff",
    "t4": "#f0c040",
    "t5": "#f07060",
    "t6": "#f0a040",
    "t7": "#64dccc",
    "t8": "#ffa0c8",
    "t9": "#ffdc64",
    "t10": "#f0f0ff",
}

SEARCH_PLACEHOLDER = "이름 또는 ID 검색"
FILTER_DEBOUNCE_MS = 180
VISIBLE_ROW_BUFFER = 2

_img_cache: dict[str, Optional[ImageTk.PhotoImage]] = {}


def load_students() -> list[dict]:
    paths = get_storage_paths()
    db_path = paths.db_path
    current_json = paths.current_students_json

    if db_path.exists():
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM students ORDER BY student_id").fetchall()
            conn.close()
            if rows:
                return [enrich_student_row(dict(row)) for row in rows]
        except Exception as exc:
            print(f"[Viewer] DB load failed: {exc}")

    if current_json.exists():
        try:
            data = json.loads(current_json.read_text(encoding="utf-8"))
            return [enrich_student_row(value) for value in data.values()]
        except Exception as exc:
            print(f"[Viewer] JSON load failed: {exc}")

    return []


def star_color(n: int) -> str:
    return C.get(f"star{n}", C["dim"])


def school_color(school: Optional[str]) -> str:
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
    return mapping.get((school or "").strip(), C["accent"])


def attack_color(attack_type: Optional[str]) -> str:
    mapping = {
        "Explosive": "#731c25",
        "Piercing": "#c3b37b",
        "Mystic": "#a5c7da",
        "Sonic": "#ae78b4",
    }
    return mapping.get((attack_type or "").strip(), C["accent"])


def defense_color(defense_type: Optional[str]) -> str:
    mapping = {
        "Light": attack_color("Explosive"),
        "Heavy": attack_color("Piercing"),
        "Special": attack_color("Mystic"),
        "Elastic": attack_color("Sonic"),
        "Composite": "#458e8e",
    }
    return mapping.get((defense_type or "").strip(), C["sub"])


def student_divider_colors(student: dict) -> tuple[str, str]:
    primary = attack_color(student.get("attack_type"))
    secondary = defense_color(student.get("defense_type"))
    if secondary.lower() == primary.lower():
        secondary = school_color(student.get("school"))
    if secondary.lower() == primary.lower():
        secondary = C["text"]
    return primary, secondary


def tier_color(tier: Optional[str]) -> str:
    if not tier or tier in ("empty", "null", "unknown"):
        return C["dim"]
    if tier in ("level_locked", "love_locked"):
        return C["sub"]
    clean = tier.replace("T", "").replace("t", "")
    return C.get(f"t{clean}", C["dim"])


def tier_label(tier: Optional[str]) -> str:
    if not tier:
        return "?"
    if tier == "empty":
        return "비어 있음"
    if tier == "level_locked":
        return "레벨 잠금"
    if tier == "love_locked":
        return "호감도 잠금"
    if tier == "null":
        return "없음"
    return tier


def weapon_text(student: dict) -> str:
    state = student.get("weapon_state")
    if state == "weapon_equipped":
        star = student.get("weapon_star") or "?"
        level = student.get("weapon_level") or "?"
        return f"전무 {star} / Lv.{level}"
    if state == "weapon_unlocked_not_equipped":
        return "전무 해금"
    if state == "no_weapon_system":
        return "전무 없음"
    return "-"


def _stable_texture_path(student_id: str) -> Optional[Path]:
    if not POLI_BG_TEXTURES:
        return None
    digest = hashlib.blake2b(student_id.encode("utf-8"), digest_size=2).digest()
    index = int.from_bytes(digest, "big") % len(POLI_BG_TEXTURES)
    return POLI_BG_TEXTURES[index]


def _load_photo(student_id: str, size: tuple[int, int]) -> Optional[ImageTk.PhotoImage]:
    if not HAS_PIL:
        return None

    key = f"{student_id}_{size[0]}x{size[1]}"
    if key in _img_cache:
        return _img_cache[key]

    path = next(
        (candidate for candidate in (TEMPLATE_DIR / f"{student_id}.png", TEMPLATE_DIR / f"{student_id}.jpg") if candidate.exists()),
        None,
    )
    if path is None:
        _img_cache[key] = None
        return None

    try:
        with Image.open(path) as raw:
            portrait = raw.convert("RGBA")

        alpha = portrait.getchannel("A")
        bbox = alpha.getbbox()
        if bbox:
            portrait = portrait.crop(bbox)

        texture_path = _stable_texture_path(student_id)
        if texture_path is not None:
            background = Image.new("RGBA", size, (14, 21, 32, 255))
            with Image.open(texture_path) as tex:
                texture = ImageOps.fit(tex.convert("RGBA"), size, Image.LANCZOS, centering=(0.5, 0.5))
                texture.putalpha(32)
                background.alpha_composite(texture)
        else:
            background = Image.new("RGBA", size, (14, 21, 32, 255))

        background.alpha_composite(Image.new("RGBA", size, (8, 12, 18, 112)))

        if portrait.width > 0 and portrait.height > 0:
            scale = (size[1] * 0.98) / portrait.height
            portrait = portrait.resize(
                (
                    max(1, int(round(portrait.width * scale))),
                    max(1, int(round(portrait.height * scale))),
                ),
                Image.LANCZOS,
            )
            layer = Image.new("RGBA", size, (0, 0, 0, 0))
            offset = (
                (size[0] - portrait.width) // 2,
                (size[1] - portrait.height) // 2,
            )
            layer.paste(portrait, offset, portrait)
            background.alpha_composite(layer)

        bg = background.convert("RGB")
        photo = ImageTk.PhotoImage(bg)
        _img_cache[key] = photo
        return photo
    except Exception as exc:
        print(f"[Viewer] image load failed ({student_id}): {exc}")
        _img_cache[key] = None
        return None


class StudentModal(tk.Toplevel):
    def __init__(self, master, student: dict, ui_scale: float):
        super().__init__(master)
        self.s = student
        self._ui_scale = ui_scale
        self._font_body = scale_font(("Malgun Gothic", 10), ui_scale)

        sid = student.get("student_id", "")
        name = student.get("display_name") or sid

        self.title(f"{name} - 상세 정보")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.attributes("-topmost", True)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        width = scale_px(560, ui_scale)
        height = scale_px(760, ui_scale)
        self.geometry(f"{width}x{height}+{(sw-width)//2}+{(sh-height)//2}")

        self._build(width)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.focus_force()

    def _section(self, parent, title: str) -> None:
        tk.Label(
            parent,
            text=title.upper(),
            bg=C["card"],
            fg=C["sub"],
            font=scale_font(("Malgun Gothic", 8, "bold"), self._ui_scale),
        ).pack(anchor="w", padx=scale_px(18, self._ui_scale), pady=(0, scale_px(4, self._ui_scale)))

    def _build(self, width: int) -> None:
        sid = self.s.get("student_id", "")
        name = self.s.get("display_name") or sid
        photo_h = int(width * 9 / 16)

        photo_frame = tk.Frame(self, bg=C["surface"], width=width, height=photo_h)
        photo_frame.pack(fill="x")
        photo_frame.pack_propagate(False)

        photo_canvas = tk.Canvas(photo_frame, width=width, height=photo_h, bg=C["surface"], highlightthickness=0)
        photo_canvas.pack(fill="both", expand=True)

        photo = _load_photo(sid, (width, photo_h))
        if photo:
            photo_canvas.create_image(0, 0, image=photo, anchor="nw")
            photo_canvas._photo = photo
        else:
            photo_canvas.create_text(
                width // 2,
                photo_h // 2,
                text="NO IMAGE",
                font=scale_font(("Consolas", 22, "bold"), self._ui_scale),
                fill=C["dim"],
            )

        star_n = self.s.get("student_star") or 0
        level = self.s.get("level")
        badge_x1 = scale_px(12, self._ui_scale)
        badge_y1 = photo_h - scale_px(36, self._ui_scale)
        badge_x2 = scale_px(106, self._ui_scale)
        badge_y2 = photo_h - scale_px(8, self._ui_scale)
        photo_canvas.create_rectangle(badge_x1, badge_y1, badge_x2, badge_y2, fill="#0a0f1a", outline=C["border"])
        photo_canvas.create_text(
            (badge_x1 + badge_x2) // 2,
            (badge_y1 + badge_y2) // 2,
            text=f"Lv.{level or '?'}",
            font=scale_font(("Consolas", 12, "bold"), self._ui_scale),
            fill=C["accent2"],
        )
        photo_canvas.create_text(
            width - scale_px(12, self._ui_scale),
            photo_h - scale_px(20, self._ui_scale),
            text="★" * star_n,
            font=scale_font(("Malgun Gothic", 13), self._ui_scale),
            fill=C["gold"],
            anchor="e",
        )

        body = tk.Frame(self, bg=C["card"])
        body.pack(fill="both", expand=True)

        name_row = tk.Frame(body, bg=C["card"])
        name_row.pack(fill="x", padx=scale_px(18, self._ui_scale), pady=(scale_px(14, self._ui_scale), 0))
        tk.Label(
            name_row,
            text=name,
            bg=C["card"],
            fg=C["text"],
            font=scale_font(("Malgun Gothic", 17, "bold"), self._ui_scale),
        ).pack(side="left")
        tk.Label(
            name_row,
            text=f"  {sid}",
            bg=C["card"],
            fg=C["dim"],
            font=scale_font(("Consolas", 9), self._ui_scale),
        ).pack(side="left", pady=(scale_px(5, self._ui_scale), 0))
        tk.Button(
            name_row,
            text="닫기",
            bg=C["surface"],
            fg=C["sub"],
            font=self._font_body,
            relief="flat",
            cursor="hand2",
            padx=scale_px(12, self._ui_scale),
            pady=scale_px(4, self._ui_scale),
            command=self.destroy,
        ).pack(side="right")

        tk.Frame(body, bg=star_color(star_n), height=scale_px(2, self._ui_scale)).pack(
            fill="x",
            padx=scale_px(18, self._ui_scale),
            pady=(scale_px(6, self._ui_scale), scale_px(10, self._ui_scale)),
        )

        self._section(body, "스킬")
        skill_f = tk.Frame(body, bg=C["card"])
        skill_f.pack(fill="x", padx=scale_px(18, self._ui_scale), pady=(0, scale_px(10, self._ui_scale)))
        for label, value in [
            ("EX", self.s.get("ex_skill")),
            ("S1", self.s.get("skill1")),
            ("S2", self.s.get("skill2")),
            ("S3", self.s.get("skill3")),
        ]:
            cell = tk.Frame(skill_f, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
            cell.pack(side="left", padx=scale_px(4, self._ui_scale), pady=scale_px(2, self._ui_scale), expand=True, fill="x")
            tk.Label(cell, text=label, bg=C["surface"], fg=C["sub"], font=scale_font(("Consolas", 9), self._ui_scale)).pack(
                pady=(scale_px(6, self._ui_scale), 0)
            )
            tk.Label(
                cell,
                text=str(value) if value is not None else "?",
                bg=C["surface"],
                fg=C["accent2"] if value is not None else C["dim"],
                font=scale_font(("Consolas", 18, "bold"), self._ui_scale),
            ).pack(pady=(0, scale_px(6, self._ui_scale)))

        self._section(body, "전용 무기")
        weapon_f = tk.Frame(body, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        weapon_f.pack(fill="x", padx=scale_px(18, self._ui_scale), pady=(0, scale_px(10, self._ui_scale)))
        inner = tk.Frame(weapon_f, bg=C["surface"])
        inner.pack(fill="x", padx=scale_px(12, self._ui_scale), pady=scale_px(10, self._ui_scale))
        state = self.s.get("weapon_state")
        if state == "weapon_equipped":
            title = "전무 장착"
            detail = weapon_text(self.s)
            color = C["gold"]
        elif state == "weapon_unlocked_not_equipped":
            title = "전무 해금"
            detail = "해금되었지만 장착되지 않음"
            color = C["accent"]
        else:
            title = "전무 정보 없음"
            detail = ""
            color = C["dim"]
        tk.Label(
            inner,
            text=title,
            bg=C["surface"],
            fg=color,
            font=scale_font(("Malgun Gothic", 11, "bold"), self._ui_scale),
        ).pack(anchor="w")
        if detail:
            tk.Label(
                inner,
                text=detail,
                bg=C["surface"],
                fg=C["text"],
                font=scale_font(("Consolas", 11, "bold"), self._ui_scale),
            ).pack(anchor="w", pady=(scale_px(2, self._ui_scale), 0))

        self._section(body, "장비")
        equip_f = tk.Frame(body, bg=C["card"])
        equip_f.pack(fill="x", padx=scale_px(18, self._ui_scale), pady=(0, scale_px(12, self._ui_scale)))
        for idx in range(1, 5):
            tier = self.s.get(f"equip{idx}")
            level = self.s.get(f"equip{idx}_level")
            color = tier_color(tier)
            cell = tk.Frame(equip_f, bg=C["surface"], highlightbackground=color, highlightthickness=1)
            cell.pack(side="left", padx=scale_px(4, self._ui_scale), expand=True, fill="x")
            tk.Label(
                cell,
                text=f"SLOT {idx}",
                bg=C["surface"],
                fg=C["sub"],
                font=scale_font(("Consolas", 8), self._ui_scale),
            ).pack(pady=(scale_px(6, self._ui_scale), 0))
            tk.Label(
                cell,
                text=tier_label(tier),
                bg=C["surface"],
                fg=color,
                font=scale_font(("Consolas", 13, "bold"), self._ui_scale),
            ).pack()
            tk.Label(
                cell,
                text=f"Lv.{level}" if level is not None else "",
                bg=C["surface"],
                fg=C["sub"],
                font=scale_font(("Consolas", 8), self._ui_scale),
            ).pack(pady=(0, scale_px(6, self._ui_scale)))


class StudentViewer(tk.Toplevel):
    def __init__(self, master=None):
        if master is None:
            self._owned_root = tk.Tk()
            self._owned_root.withdraw()
            super().__init__(self._owned_root)
        else:
            super().__init__(master)

        self._ui_scale = get_ui_scale(self, base_width=1500, base_height=1080)
        self._font_body = scale_font(("Malgun Gothic", 10), self._ui_scale)
        self._font_small = scale_font(("Malgun Gothic", 8), self._ui_scale)
        self._font_title = scale_font(("Malgun Gothic", 15, "bold"), self._ui_scale)
        self._card_w = scale_px(176, self._ui_scale)
        self._card_h = scale_px(286, self._ui_scale)
        self._photo_h = scale_px(146, self._ui_scale)
        self._grid_pad = scale_px(12, self._ui_scale)
        self._min_cols = 3 if self._ui_scale >= 1.35 else 4

        self.title("BA Student Viewer")
        self.configure(bg=C["bg"])
        self.geometry(f"{scale_px(1320, self._ui_scale)}x{scale_px(860, self._ui_scale)}")
        self.minsize(scale_px(940, self._ui_scale), scale_px(620, self._ui_scale))

        self._all_students: list[dict] = []
        self._filtered: list[dict] = []
        self._card_pool: list[tk.Canvas] = []
        self._modal: Optional[StudentModal] = None
        self._filter_after: Optional[str] = None
        self._resize_after: Optional[str] = None

        self._sort_mode = tk.StringVar(value="star_desc")
        self._search_var = tk.StringVar(value="")
        self._selected_filters: dict[str, set[str]] = {key: set() for key in FILTER_FIELD_ORDER}
        self._filter_options: dict[str, list] = {}

        self._build_ui()
        self._search_var.trace_add("write", self._on_filter_change)
        self.bind("<Configure>", self._on_resize)
        self.after(100, self._load_data_async)

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        header.pack(fill="x", padx=scale_px(12, self._ui_scale), pady=(scale_px(12, self._ui_scale), scale_px(6, self._ui_scale)))

        top_row = tk.Frame(header, bg=C["surface"])
        top_row.pack(fill="x", padx=scale_px(14, self._ui_scale), pady=(scale_px(12, self._ui_scale), scale_px(8, self._ui_scale)))

        tk.Label(
            top_row,
            text="BA Student Viewer",
            bg=C["surface"],
            fg=C["accent2"],
            font=self._font_title,
        ).pack(side="left")

        self._stat_frame = tk.Frame(top_row, bg=C["surface"])
        self._stat_frame.pack(side="left", padx=scale_px(10, self._ui_scale))
        self._stat_labels: dict[str, tk.Label] = {}
        for key, text in [("total", "전체"), ("lv90", "Lv.90"), ("star5", "5성"), ("weapon", "전무")]:
            lbl = tk.Label(
                self._stat_frame,
                text=text,
                bg=C["surface"],
                fg=C["sub"],
                font=self._font_small,
                padx=scale_px(10, self._ui_scale),
                pady=scale_px(4, self._ui_scale),
                highlightbackground=C["border"],
                highlightthickness=1,
            )
            lbl.pack(side="left", padx=scale_px(3, self._ui_scale))
            self._stat_labels[key] = lbl

        filter_row = tk.Frame(header, bg=C["surface"])
        filter_row.pack(fill="x", padx=scale_px(14, self._ui_scale), pady=(0, scale_px(12, self._ui_scale)))

        self._search_entry = tk.Entry(
            filter_row,
            textvariable=self._search_var,
            bg=C["card"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            font=self._font_body,
            highlightbackground=C["border"],
            highlightthickness=1,
            width=22,
        )
        self._search_entry.pack(side="left", padx=(0, scale_px(8, self._ui_scale)), ipady=scale_px(6, self._ui_scale))
        self._search_entry.insert(0, SEARCH_PLACEHOLDER)
        self._search_entry.bind("<FocusIn>", self._clear_search_placeholder)

        sort_menu = tk.OptionMenu(
            filter_row,
            self._sort_mode,
            "star_desc",
            "star_asc",
            "level_desc",
            "name_asc",
            command=lambda _value: self._apply_filter(),
        )
        sort_menu.config(
            bg=C["card"],
            fg=C["text"],
            relief="flat",
            font=self._font_small,
            highlightthickness=0,
            activebackground=C["border"],
            padx=scale_px(6, self._ui_scale),
            pady=scale_px(4, self._ui_scale),
        )
        sort_menu["menu"].config(bg=C["card"], fg=C["text"], font=self._font_small)
        sort_menu.pack(side="left", padx=(0, scale_px(8, self._ui_scale)))

        star_f = tk.Frame(filter_row, bg=C["surface"])
        star_f.pack(side="left", padx=(0, scale_px(8, self._ui_scale)))
        self._star_btns: list[tuple[str, tk.Button]] = []
        for label, value in [("전체", "all"), ("5성", "5"), ("4성", "4"), ("3성", "3"), ("2성", "2")]:
            btn = tk.Button(
                star_f,
                text=label,
                bg=C["accent"] if value == "all" else C["card"],
                fg="#fff" if value == "all" else C["sub"],
                relief="flat",
                font=self._font_small,
                cursor="hand2",
                padx=scale_px(8, self._ui_scale),
                pady=scale_px(4, self._ui_scale),
                command=lambda v=value: self._set_star_filter(v),
            )
            btn.pack(side="left", padx=scale_px(2, self._ui_scale))
            self._star_btns.append((value, btn))

        weapon_f = tk.Frame(filter_row, bg=C["surface"])
        weapon_f.pack(side="left", padx=(0, scale_px(8, self._ui_scale)))
        self._weapon_btns: list[tuple[str, tk.Button]] = []
        for label, value in [("전무 전체", "all"), ("장착", "weapon_equipped"), ("없음", "no_weapon_system")]:
            btn = tk.Button(
                weapon_f,
                text=label,
                bg=C["accent"] if value == "all" else C["card"],
                fg="#fff" if value == "all" else C["sub"],
                relief="flat",
                font=self._font_small,
                cursor="hand2",
                padx=scale_px(8, self._ui_scale),
                pady=scale_px(4, self._ui_scale),
                command=lambda v=value: self._set_weapon_filter(v),
            )
            btn.pack(side="left", padx=scale_px(2, self._ui_scale))
            self._weapon_btns.append((value, btn))

        tk.Button(
            filter_row,
            text="새로고침",
            bg=C["card"],
            fg=C["sub"],
            relief="flat",
            font=self._font_small,
            cursor="hand2",
            padx=scale_px(10, self._ui_scale),
            pady=scale_px(4, self._ui_scale),
            command=self._load_data_async,
        ).pack(side="right")

        self._count_bar = tk.Label(self, text="", bg=C["bg"], fg=C["sub"], font=self._font_small, anchor="w")
        self._count_bar.pack(fill="x", padx=scale_px(18, self._ui_scale), pady=(scale_px(2, self._ui_scale), scale_px(6, self._ui_scale)))

        self._canvas_frame = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        self._scrollbar = tk.Scrollbar(self, orient="vertical", command=self._on_scrollbar, width=scale_px(14, self._ui_scale))
        self._canvas_frame.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y", padx=(0, scale_px(10, self._ui_scale)), pady=(0, scale_px(10, self._ui_scale)))
        self._canvas_frame.pack(side="left", fill="both", expand=True, padx=(scale_px(12, self._ui_scale), 0), pady=(0, scale_px(10, self._ui_scale)))

        self._grid_inner = tk.Frame(self._canvas_frame, bg=C["bg"])
        self._canvas_window = self._canvas_frame.create_window(0, 0, anchor="nw", window=self._grid_inner)

        self._grid_inner.bind("<Configure>", self._on_inner_configure)
        self._canvas_frame.bind("<Configure>", self._on_canvas_resize)
        self._canvas_frame.bind("<MouseWheel>", self._on_mousewheel)

    def _clear_search_placeholder(self, _event) -> None:
        if self._search_entry.get() == SEARCH_PLACEHOLDER:
            self._search_entry.delete(0, "end")

    def _load_data_async(self) -> None:
        self._count_bar.config(text="  학생 데이터를 불러오는 중...")

        def task():
            students = load_students()
            self.after(0, lambda: self._on_data_loaded(students))

        threading.Thread(target=task, daemon=True).start()

    def _on_data_loaded(self, students: list[dict]) -> None:
        self._all_students = students
        self._update_stats()
        self._apply_filter()

    def _update_stats(self) -> None:
        total = len(self._all_students)
        lv90 = sum(1 for s in self._all_students if (s.get("level") or 0) >= 90)
        star5 = sum(1 for s in self._all_students if (s.get("student_star") or 0) >= 5)
        weapon = sum(1 for s in self._all_students if s.get("weapon_state") == "weapon_equipped")

        self._stat_labels["total"].config(text=f"전체 {total}")
        self._stat_labels["lv90"].config(text=f"Lv.90 {lv90}")
        self._stat_labels["star5"].config(text=f"5성 {star5}")
        self._stat_labels["weapon"].config(text=f"전무 {weapon}")

    def _set_star_filter(self, value: str) -> None:
        self._filter_star.set(value)
        for current, btn in self._star_btns:
            btn.config(bg=C["accent"] if current == value else C["card"], fg="#fff" if current == value else C["sub"])
        self._apply_filter()

    def _set_weapon_filter(self, value: str) -> None:
        self._filter_weapon.set(value)
        for current, btn in self._weapon_btns:
            btn.config(bg=C["accent"] if current == value else C["card"], fg="#fff" if current == value else C["sub"])
        self._apply_filter()

    def _on_filter_change(self, *_args) -> None:
        if self._filter_after:
            self.after_cancel(self._filter_after)
        self._filter_after = self.after(FILTER_DEBOUNCE_MS, self._apply_filter)

    def _apply_filter(self) -> None:
        self._filter_after = None
        star = self._filter_star.get()
        weapon = self._filter_weapon.get()
        query = self._search_var.get().strip()
        if query == SEARCH_PLACEHOLDER:
            query = ""

        arr = list(self._all_students)
        if star != "all":
            arr = [s for s in arr if str(s.get("student_star") or "") == star]
        if weapon != "all":
            arr = [s for s in arr if s.get("weapon_state") == weapon]
        if query:
            q = query.lower()
            arr = [s for s in arr if q in (s.get("display_name") or "").lower() or q in (s.get("student_id") or "").lower()]

        mode = self._sort_mode.get()
        if mode == "star_desc":
            arr.sort(key=lambda s: (-(s.get("student_star") or 0), -(s.get("level") or 0), (s.get("display_name") or "")))
        elif mode == "star_asc":
            arr.sort(key=lambda s: ((s.get("student_star") or 0), (s.get("level") or 0), (s.get("display_name") or "")))
        elif mode == "level_desc":
            arr.sort(key=lambda s: (-(s.get("level") or 0), -(s.get("student_star") or 0)))
        elif mode == "name_asc":
            arr.sort(key=lambda s: (s.get("display_name") or "", s.get("student_id") or ""))

        self._filtered = arr
        self._count_bar.config(text=f"  {len(arr)}명 표시 중 / 전체 {len(self._all_students)}명")
        self._canvas_frame.yview_moveto(0)
        self._refresh_virtual_grid(reset_pool=False)

    def _init_card_canvas(self, canvas: tk.Canvas) -> None:
        photo_h = self._photo_h
        items: dict[str, object] = {}

        border_w = max(1, scale_px(1, self._ui_scale))
        items["bg"] = canvas.create_rectangle(0, 0, self._card_w, self._card_h, fill=C["card"], outline="")
        items["top_line"] = canvas.create_rectangle(0, 0, self._card_w, scale_px(4, self._ui_scale), fill=C["dim"], outline="")
        items["border"] = canvas.create_rectangle(0, 0, self._card_w - 1, self._card_h - 1, outline=C["border"], fill="", width=border_w)
        canvas.create_rectangle(0, scale_px(4, self._ui_scale), self._card_w, scale_px(4, self._ui_scale) + photo_h, fill=C["surface"], outline="")
        divider_y = scale_px(4, self._ui_scale) + photo_h
        divider_h = scale_px(4, self._ui_scale)
        items["divider_left"] = canvas.create_rectangle(
            0,
            divider_y,
            self._card_w // 2,
            divider_y + divider_h,
            fill=C["accent"],
            outline="",
        )
        items["divider_right"] = canvas.create_rectangle(
            self._card_w // 2,
            divider_y,
            self._card_w,
            divider_y + divider_h,
            fill=C["accent2"],
            outline="",
        )

        items["photo"] = canvas.create_image(self._card_w // 2, scale_px(4, self._ui_scale) + photo_h // 2, anchor="center", state="hidden")
        items["placeholder"] = canvas.create_text(
            self._card_w // 2,
            scale_px(4, self._ui_scale) + photo_h // 2,
            text="NO\nIMAGE",
            font=scale_font(("Consolas", 16, "bold"), self._ui_scale),
            fill=C["dim"],
            justify="center",
            state="hidden",
        )
        items["placeholder_sid"] = canvas.create_text(
            self._card_w // 2,
            scale_px(4, self._ui_scale) + photo_h // 2 + scale_px(34, self._ui_scale),
            text="",
            font=self._font_small,
            fill=C["dim"],
            state="hidden",
        )
        canvas.create_rectangle(
            scale_px(6, self._ui_scale),
            scale_px(4, self._ui_scale) + photo_h - scale_px(22, self._ui_scale),
            scale_px(58, self._ui_scale),
            scale_px(4, self._ui_scale) + photo_h - scale_px(4, self._ui_scale),
            fill="#0a0f1a",
            outline=C["border"],
        )
        items["level_text"] = canvas.create_text(
            scale_px(32, self._ui_scale),
            scale_px(4, self._ui_scale) + photo_h - scale_px(13, self._ui_scale),
            text="Lv.?",
            font=scale_font(("Consolas", 8, "bold"), self._ui_scale),
            fill=C["accent2"],
        )
        items["weapon_bg"] = canvas.create_rectangle(
            self._card_w - scale_px(48, self._ui_scale),
            scale_px(8, self._ui_scale),
            self._card_w - scale_px(6, self._ui_scale),
            scale_px(28, self._ui_scale),
            fill="#0a0f1a",
            outline=C["gold"],
            state="hidden",
        )
        items["weapon_text"] = canvas.create_text(
            self._card_w - scale_px(27, self._ui_scale),
            scale_px(18, self._ui_scale),
            text="",
            font=scale_font(("Malgun Gothic", 7, "bold"), self._ui_scale),
            fill=C["gold"],
            state="hidden",
        )

        y = scale_px(4, self._ui_scale) + photo_h + scale_px(8, self._ui_scale)
        items["name"] = canvas.create_text(
            self._card_w // 2,
            y,
            text="",
            font=scale_font(("Malgun Gothic", 9, "bold"), self._ui_scale),
            fill=C["text"],
            width=self._card_w - scale_px(14, self._ui_scale),
            anchor="n",
        )
        y += scale_px(24, self._ui_scale)

        chip_gap = scale_px(4, self._ui_scale)
        chip_w = (self._card_w - scale_px(10, self._ui_scale) - chip_gap * 3) // 4
        x = scale_px(5, self._ui_scale)
        skills = []
        for _ in range(4):
            rect = canvas.create_rectangle(x, y, x + chip_w, y + scale_px(18, self._ui_scale), fill=C["surface"], outline=C["dim"])
            text = canvas.create_text(
                x + chip_w // 2,
                y + scale_px(9, self._ui_scale),
                text="",
                font=scale_font(("Consolas", 7, "bold"), self._ui_scale),
                fill=C["accent2"],
            )
            skills.append((rect, text))
            x += chip_w + chip_gap
        items["skills"] = skills
        y += scale_px(24, self._ui_scale)

        eq_w = chip_w
        x = scale_px(5, self._ui_scale)
        equips = []
        for _ in range(4):
            rect = canvas.create_rectangle(x, y, x + eq_w, y + scale_px(24, self._ui_scale), fill=C["surface"], outline=C["dim"], width=border_w)
            tier = canvas.create_text(
                x + eq_w // 2,
                y + scale_px(8, self._ui_scale),
                text="",
                font=scale_font(("Consolas", 7), self._ui_scale),
                fill=C["dim"],
            )
            lvl = canvas.create_text(
                x + eq_w // 2,
                y + scale_px(18, self._ui_scale),
                text="",
                font=scale_font(("Consolas", 6), self._ui_scale),
                fill=C["sub"],
            )
            equips.append((rect, tier, lvl))
            x += eq_w + chip_gap
        items["equips"] = equips

        canvas._items = items
        canvas._hover = False
        canvas._data_idx = None
        canvas._student_data = None
        canvas.photo_ref = None

    def _update_card_canvas(self, canvas: tk.Canvas, student: dict) -> None:
        items = canvas._items
        sid = student.get("student_id", "")
        star_n = student.get("student_star") or 0

        canvas._student_data = student
        self._set_card_hover(canvas, False)
        canvas.itemconfig(items["top_line"], fill=star_color(star_n))
        divider_primary, divider_secondary = student_divider_colors(student)
        canvas.itemconfig(items["divider_left"], fill=divider_primary)
        canvas.itemconfig(items["divider_right"], fill=divider_secondary)
        canvas.itemconfig(items["name"], text=student.get("display_name") or sid)

        level = student.get("level")
        canvas.itemconfig(items["level_text"], text=f"Lv.{level}" if level else "Lv.?")

        photo = _load_photo(sid, (self._card_w, self._photo_h))
        if photo:
            canvas.itemconfig(items["photo"], image=photo, state="normal")
            canvas.itemconfig(items["placeholder"], state="hidden")
            canvas.itemconfig(items["placeholder_sid"], state="hidden")
            canvas.photo_ref = photo
        else:
            canvas.itemconfig(items["photo"], image="", state="hidden")
            canvas.itemconfig(items["placeholder"], state="normal")
            canvas.itemconfig(items["placeholder_sid"], text=sid[:16], state="normal")
            canvas.photo_ref = None

        weapon_state = student.get("weapon_state")
        if weapon_state == "weapon_equipped":
            wstar = student.get("weapon_star") or "?"
            canvas.itemconfig(items["weapon_bg"], outline=C["gold"], state="normal")
            canvas.itemconfig(items["weapon_text"], text=f"전{wstar}", fill=C["gold"], state="normal")
        elif weapon_state == "weapon_unlocked_not_equipped":
            canvas.itemconfig(items["weapon_bg"], outline=C["accent"], state="normal")
            canvas.itemconfig(items["weapon_text"], text="해금", fill=C["accent"], state="normal")
        else:
            canvas.itemconfig(items["weapon_bg"], state="hidden")
            canvas.itemconfig(items["weapon_text"], state="hidden")

        skills = [
            ("EX", student.get("ex_skill")),
            ("S1", student.get("skill1")),
            ("S2", student.get("skill2")),
            ("S3", student.get("skill3")),
        ]
        for (rect, text_id), (label, value) in zip(items["skills"], skills):
            canvas.itemconfig(rect, outline=C["dim"])
            canvas.itemconfig(text_id, text=f"{label} {value if value is not None else '?'}")

        equips = [
            (student.get("equip1"), student.get("equip1_level")),
            (student.get("equip2"), student.get("equip2_level")),
            (student.get("equip3"), student.get("equip3_level")),
            (student.get("equip4"), None),
        ]
        for (rect, tier_text, level_text), (tier, value) in zip(items["equips"], equips):
            color = tier_color(tier)
            canvas.itemconfig(rect, outline=color if color != C["dim"] else C["dim"])
            canvas.itemconfig(tier_text, text=tier_label(tier), fill=color)
            canvas.itemconfig(level_text, text=f"L{value}" if value is not None else "")

    def _set_card_hover(self, canvas: tk.Canvas, hover: bool) -> None:
        if getattr(canvas, "_hover", False) == hover:
            return
        canvas._hover = hover
        canvas.itemconfig(canvas._items["bg"], fill=C["card_h"] if hover else C["card"])
        canvas.itemconfig(canvas._items["border"], outline=C["accent"] if hover else C["border"])

    def _ensure_card_pool(self, needed: int) -> None:
        while len(self._card_pool) < needed:
            canvas = tk.Canvas(
                self._grid_inner,
                width=self._card_w,
                height=self._card_h,
                bg=C["card"],
                highlightthickness=0,
                cursor="hand2",
            )
            self._init_card_canvas(canvas)
            canvas.bind("<Enter>", self._on_card_enter)
            canvas.bind("<Leave>", self._on_card_leave)
            canvas.bind("<Button-1>", self._on_card_click)
            canvas.bind("<MouseWheel>", self._on_mousewheel)
            self._card_pool.append(canvas)

    def _compute_cols(self) -> int:
        width = max(self._canvas_frame.winfo_width(), self._card_w + self._grid_pad * 2)
        return max(self._min_cols, (width - self._grid_pad) // (self._card_w + self._grid_pad))

    def _refresh_virtual_grid(self, reset_pool: bool = False) -> None:
        if reset_pool:
            for canvas in self._card_pool:
                canvas._data_idx = None

        cols = self._compute_cols()
        total = len(self._filtered)
        row_height = self._card_h + self._grid_pad
        rows = max(1, math.ceil(total / cols)) if total else 1
        width = cols * (self._card_w + self._grid_pad) + self._grid_pad
        height = rows * row_height + self._grid_pad

        self._grid_inner.configure(width=width, height=height)
        self._canvas_frame.itemconfig(self._canvas_window, width=max(self._canvas_frame.winfo_width(), width))
        self._canvas_frame.configure(scrollregion=(0, 0, width, height))

        top = max(0, self._canvas_frame.canvasy(0))
        bottom = top + max(1, self._canvas_frame.winfo_height())
        start_row = max(0, int(top // row_height) - VISIBLE_ROW_BUFFER)
        end_row = min(rows, int(bottom // row_height) + VISIBLE_ROW_BUFFER + 1)

        visible_indices = []
        for row in range(start_row, end_row):
            base = row * cols
            for col in range(cols):
                idx = base + col
                if idx >= total:
                    break
                visible_indices.append(idx)

        self._ensure_card_pool(max(1, len(visible_indices)))

        for slot, idx in enumerate(visible_indices):
            canvas = self._card_pool[slot]
            row = idx // cols
            col = idx % cols
            x = self._grid_pad // 2 + col * (self._card_w + self._grid_pad)
            y = self._grid_pad // 2 + row * row_height
            canvas.place(x=x, y=y, width=self._card_w, height=self._card_h)
            if canvas._data_idx != idx:
                self._update_card_canvas(canvas, self._filtered[idx])
                canvas._data_idx = idx

        for slot in range(len(visible_indices), len(self._card_pool)):
            canvas = self._card_pool[slot]
            canvas.place_forget()
            canvas._data_idx = None
            canvas._student_data = None
            self._set_card_hover(canvas, False)

    def _open_modal(self, student: dict) -> None:
        if self._modal and self._modal.winfo_exists():
            self._modal.destroy()
        self._modal = StudentModal(self, student, self._ui_scale)

    def _on_card_enter(self, event) -> None:
        widget = event.widget
        if getattr(widget, "_student_data", None) is not None:
            self._set_card_hover(widget, True)

    def _on_card_leave(self, event) -> None:
        self._set_card_hover(event.widget, False)

    def _on_card_click(self, event) -> None:
        student = getattr(event.widget, "_student_data", None)
        if student is not None:
            self._open_modal(student)

    def _on_scrollbar(self, *args) -> None:
        self._canvas_frame.yview(*args)
        self._refresh_virtual_grid()

    def _on_mousewheel(self, event) -> str:
        delta = -1 * (event.delta // 120)
        if delta:
            self._canvas_frame.yview_scroll(delta, "units")
            self._refresh_virtual_grid()
        return "break"

    def _on_inner_configure(self, _event) -> None:
        self._canvas_frame.configure(scrollregion=self._canvas_frame.bbox("all"))

    def _on_canvas_resize(self, event) -> None:
        self._canvas_frame.itemconfig(self._canvas_window, width=event.width)
        self._refresh_virtual_grid(reset_pool=True)

    def _on_resize(self, _event) -> None:
        if self._resize_after:
            self.after_cancel(self._resize_after)
        self._resize_after = self.after(120, lambda: self._refresh_virtual_grid(reset_pool=True))

    def run(self) -> None:
        if hasattr(self, "_owned_root"):
            self._owned_root.mainloop()
        else:
            self.mainloop()


def open_viewer(master=None) -> StudentViewer:
    return StudentViewer(master)


if __name__ == "__main__":
    viewer = StudentViewer()
    viewer.run()
