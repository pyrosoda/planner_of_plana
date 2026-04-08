"""
Optimized student viewer for large datasets.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageTk

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

BASE_DIR = Path(__file__).parent.parent
TEMPLATE_DIR = BASE_DIR / "templates" / "students_portraits"
CURRENT_JSON = BASE_DIR / "data" / "current" / "students.json"
DB_PATH = BASE_DIR / "ba_planner.db"

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

FONT_BODY = ("Malgun Gothic", 9)
FONT_SMALL = ("Malgun Gothic", 8)

CARD_W = 160
CARD_H = 260
PHOTO_SIZE = 130
GRID_PAD = 10
COLS_MIN = 4
FILTER_DEBOUNCE_MS = 180
VISIBLE_ROW_BUFFER = 2
SEARCH_PLACEHOLDER = "이름 검색..."

_img_cache: dict[str, Optional[ImageTk.PhotoImage]] = {}


def load_students() -> list[dict]:
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM students ORDER BY student_id").fetchall()
            conn.close()
            if rows:
                return [dict(r) for r in rows]
        except Exception as exc:
            print(f"[Viewer] DB load failed: {exc}")

    if CURRENT_JSON.exists():
        try:
            data = json.loads(CURRENT_JSON.read_text(encoding="utf-8"))
            return list(data.values())
        except Exception as exc:
            print(f"[Viewer] JSON load failed: {exc}")

    return []


def _load_photo(student_id: str, size: tuple[int, int]) -> Optional[ImageTk.PhotoImage]:
    if not HAS_PIL:
        return None
    key = f"{student_id}_{size[0]}x{size[1]}"
    if key in _img_cache:
        return _img_cache[key]

    path = next(
        (p for p in (TEMPLATE_DIR / f"{student_id}.png", TEMPLATE_DIR / f"{student_id}.jpg") if p.exists()),
        None,
    )
    if path is None:
        _img_cache[key] = None
        return None

    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail(size, Image.LANCZOS)

        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        canvas.paste(img, offset)

        bg = Image.new("RGB", size, C["surface"])
        bg.paste(canvas, mask=canvas.split()[3])
        photo = ImageTk.PhotoImage(bg)
        _img_cache[key] = photo
        return photo
    except Exception as exc:
        print(f"[Viewer] image load failed ({student_id}): {exc}")
        _img_cache[key] = None
        return None


def _load_photo_large(student_id: str, w: int, h: int) -> Optional[ImageTk.PhotoImage]:
    if not HAS_PIL:
        return None
    key = f"{student_id}_modal_{w}x{h}"
    if key in _img_cache:
        return _img_cache[key]

    path = next(
        (p for p in (TEMPLATE_DIR / f"{student_id}.png", TEMPLATE_DIR / f"{student_id}.jpg") if p.exists()),
        None,
    )
    if path is None:
        _img_cache[key] = None
        return None

    try:
        img = Image.open(path).convert("RGB")
        ratio = w / h
        iw, ih = img.size
        if iw / ih > ratio:
            new_w = int(ih * ratio)
            img = img.crop(((iw - new_w) // 2, 0, (iw + new_w) // 2, ih))
        else:
            new_h = int(iw / ratio)
            img = img.crop((0, 0, iw, new_h))
        img = img.resize((w, h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        _img_cache[key] = photo
        return photo
    except Exception:
        _img_cache[key] = None
        return None


def star_color(n: int) -> str:
    return C.get(f"star{n}", C["dim"])


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
        return "빈칸"
    if tier == "level_locked":
        return "Lv잠금"
    if tier == "love_locked":
        return "애정잠금"
    if tier == "null":
        return "없음"
    return tier


def _init_card_canvas(canvas: tk.Canvas) -> None:
    photo_h = PHOTO_SIZE
    items: dict[str, object] = {}

    items["bg"] = canvas.create_rectangle(0, 0, CARD_W, CARD_H, fill=C["card"], outline="")
    items["top_line"] = canvas.create_rectangle(0, 0, CARD_W, 3, fill=C["dim"], outline="")
    items["border"] = canvas.create_rectangle(0, 0, CARD_W - 1, CARD_H - 1, outline=C["border"], fill="", width=1)
    canvas.create_rectangle(0, 3, CARD_W, 3 + photo_h, fill=C["surface"], outline="")

    items["photo"] = canvas.create_image(CARD_W // 2, 3 + photo_h // 2, anchor="center", state="hidden")
    items["placeholder"] = canvas.create_text(
        CARD_W // 2, 3 + photo_h // 2, text="🎓", font=("Segoe UI Emoji", 24), fill=C["dim"], state="hidden"
    )
    items["placeholder_sid"] = canvas.create_text(
        CARD_W // 2, 3 + photo_h // 2 + 28, text="", font=FONT_SMALL, fill=C["dim"], state="hidden"
    )
    canvas.create_rectangle(4, 3 + photo_h - 18, 42, 3 + photo_h - 3, fill="#0a0f1a", outline=C["border"])
    items["level_text"] = canvas.create_text(
        23, 3 + photo_h - 10, text="Lv.?", font=("Consolas", 7, "bold"), fill=C["accent2"]
    )
    items["weapon_bg"] = canvas.create_rectangle(
        CARD_W - 40, 6, CARD_W - 3, 20, fill="#0a0f1a", outline=C["gold"], state="hidden"
    )
    items["weapon_text"] = canvas.create_text(
        CARD_W - 21, 13, text="", font=("Malgun Gothic", 6, "bold"), fill=C["gold"], state="hidden"
    )

    y = 3 + photo_h + 6
    items["name"] = canvas.create_text(
        CARD_W // 2, y, text="", font=("Malgun Gothic", 8, "bold"), fill=C["text"], width=CARD_W - 8, anchor="n"
    )
    y += 18
    items["stars"] = canvas.create_text(CARD_W // 2, y, text="", font=("Malgun Gothic", 7), fill=C["gold"], anchor="n")
    y += 14

    chip_w = (CARD_W - 8 - 9) // 4
    x = 4
    skills = []
    for _ in range(4):
        rect = canvas.create_rectangle(x, y, x + chip_w, y + 13, fill=C["surface"], outline=C["dim"])
        text = canvas.create_text(x + chip_w // 2, y + 6, text="", font=("Consolas", 6, "bold"), fill=C["accent2"])
        skills.append((rect, text))
        x += chip_w + 3
    items["skills"] = skills
    y += 17

    eq_w = (CARD_W - 8 - 9) // 4
    x = 4
    equips = []
    for _ in range(4):
        rect = canvas.create_rectangle(x, y, x + eq_w, y + 18, fill=C["surface"], outline=C["dim"], width=1)
        tier = canvas.create_text(x + eq_w // 2, y + 6, text="", font=("Consolas", 6), fill=C["dim"])
        lvl = canvas.create_text(x + eq_w // 2, y + 13, text="", font=("Consolas", 5), fill=C["sub"])
        equips.append((rect, tier, lvl))
        x += eq_w + 3
    items["equips"] = equips

    canvas._items = items
    canvas._hover = False
    canvas._data_idx = None
    canvas._student_data = None
    canvas.photo_ref = None


def _set_card_hover(canvas: tk.Canvas, hover: bool) -> None:
    if getattr(canvas, "_hover", False) == hover:
        return
    canvas._hover = hover
    canvas.itemconfig(canvas._items["bg"], fill=C["card_h"] if hover else C["card"])
    canvas.itemconfig(canvas._items["border"], outline=C["accent"] if hover else C["border"])


def _update_card_canvas(canvas: tk.Canvas, student: dict) -> None:
    items = canvas._items
    sid = student.get("student_id", "")
    star_n = student.get("student_star") or 0

    canvas._student_data = student
    _set_card_hover(canvas, False)
    canvas.itemconfig(items["top_line"], fill=star_color(star_n))
    canvas.itemconfig(items["name"], text=student.get("display_name") or sid)
    canvas.itemconfig(items["stars"], text="★" * star_n + "☆" * (5 - star_n))

    level = student.get("level")
    canvas.itemconfig(items["level_text"], text=f"Lv.{level}" if level else "Lv.?")

    photo = _load_photo(sid, (CARD_W, PHOTO_SIZE))
    if photo:
        canvas.itemconfig(items["photo"], image=photo, state="normal")
        canvas.itemconfig(items["placeholder"], state="hidden")
        canvas.itemconfig(items["placeholder_sid"], state="hidden")
        canvas.photo_ref = photo
    else:
        canvas.itemconfig(items["photo"], image="", state="hidden")
        canvas.itemconfig(items["placeholder"], state="normal")
        canvas.itemconfig(items["placeholder_sid"], text=sid[:14], state="normal")
        canvas.photo_ref = None

    weapon_state = student.get("weapon_state")
    if weapon_state == "weapon_equipped":
        wstar = student.get("weapon_star") or "?"
        canvas.itemconfig(items["weapon_bg"], outline=C["gold"], state="normal")
        canvas.itemconfig(items["weapon_text"], text=f"⚔{wstar}★", fill=C["gold"], state="normal")
    elif weapon_state == "weapon_unlocked_not_equipped":
        canvas.itemconfig(items["weapon_bg"], outline=C["accent"], state="normal")
        canvas.itemconfig(items["weapon_text"], text="🔓", fill=C["accent"], state="normal")
    else:
        canvas.itemconfig(items["weapon_bg"], state="hidden")
        canvas.itemconfig(items["weapon_text"], state="hidden")

    skills = [
        ("EX", student.get("ex_skill")),
        ("S1", student.get("skill1")),
        ("S2", student.get("skill2")),
        ("S3", student.get("skill3")),
    ]
    for (rect, text), (label, value) in zip(items["skills"], skills):
        canvas.itemconfig(rect, outline=C["dim"])
        canvas.itemconfig(text, text=f"{label} {value if value is not None else '?'}")

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


class StudentModal(tk.Toplevel):
    def __init__(self, master, student: dict):
        super().__init__(master)
        self.s = student

        sid = student.get("student_id", "")
        name = student.get("display_name") or sid

        self.title(f"{name} - 상세 정보")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.attributes("-topmost", True)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 480, 620
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._build(w)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.focus_force()

    def _section(self, parent, title: str) -> None:
        tk.Label(
            parent,
            text=title.upper(),
            bg=C["card"],
            fg=C["sub"],
            font=("Malgun Gothic", 7, "bold"),
        ).pack(anchor="w", padx=14, pady=(0, 2))

    def _build(self, width: int) -> None:
        sid = self.s.get("student_id", "")
        name = self.s.get("display_name") or sid
        photo_h = int(width * 9 / 16)

        photo_frame = tk.Frame(self, bg=C["surface"], width=width, height=photo_h)
        photo_frame.pack(fill="x")
        photo_frame.pack_propagate(False)

        photo_canvas = tk.Canvas(photo_frame, width=width, height=photo_h, bg=C["surface"], highlightthickness=0)
        photo_canvas.pack()

        photo = _load_photo_large(sid, width, photo_h)
        if photo:
            photo_canvas.create_image(0, 0, image=photo, anchor="nw")
            photo_canvas._photo = photo
        else:
            photo_canvas.create_text(width // 2, photo_h // 2, text="🎓", font=("Segoe UI Emoji", 48), fill=C["dim"])

        star_n = self.s.get("student_star") or 0
        level = self.s.get("level")
        photo_canvas.create_rectangle(8, photo_h - 26, 80, photo_h - 4, fill="#0a0f1a", outline=C["border"])
        photo_canvas.create_text(44, photo_h - 15, text=f"Lv.{level or '?'}", font=("Consolas", 11, "bold"), fill=C["accent2"])
        photo_canvas.create_text(width - 8, photo_h - 14, text="★" * star_n, font=("Malgun Gothic", 12), fill=C["gold"], anchor="e")

        body = tk.Frame(self, bg=C["card"])
        body.pack(fill="both", expand=True)

        name_row = tk.Frame(body, bg=C["card"])
        name_row.pack(fill="x", padx=14, pady=(12, 0))
        tk.Label(name_row, text=name, bg=C["card"], fg=C["text"], font=("Malgun Gothic", 16, "bold")).pack(side="left")
        tk.Label(name_row, text=f"   {sid}", bg=C["card"], fg=C["dim"], font=("Consolas", 8)).pack(side="left", pady=(4, 0))
        tk.Button(
            name_row,
            text="X",
            bg=C["surface"],
            fg=C["sub"],
            font=("Arial", 10),
            relief="flat",
            cursor="hand2",
            command=self.destroy,
        ).pack(side="right")

        tk.Frame(body, bg=star_color(star_n), height=2).pack(fill="x", padx=14, pady=(4, 8))

        self._section(body, "스킬")
        skill_f = tk.Frame(body, bg=C["card"])
        skill_f.pack(fill="x", padx=14, pady=(0, 8))
        for label, value in [
            ("EX", self.s.get("ex_skill")),
            ("S1", self.s.get("skill1")),
            ("S2", self.s.get("skill2")),
            ("S3", self.s.get("skill3")),
        ]:
            cell = tk.Frame(skill_f, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
            cell.pack(side="left", padx=3, pady=2, expand=True, fill="x")
            tk.Label(cell, text=label, bg=C["surface"], fg=C["sub"], font=("Consolas", 8)).pack()
            tk.Label(
                cell,
                text=str(value) if value is not None else "?",
                bg=C["surface"],
                fg=C["accent2"] if value is not None else C["dim"],
                font=("Consolas", 18, "bold"),
            ).pack()

        self._section(body, "무기")
        weapon_f = tk.Frame(body, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        weapon_f.pack(fill="x", padx=14, pady=(0, 8))
        state = self.s.get("weapon_state")
        if state == "weapon_equipped":
            title = "무기 장착"
            detail = f"{self.s.get('weapon_star') or '?'}★  Lv.{self.s.get('weapon_level') or '?'}"
            color = C["gold"]
            icon = "⚔"
        elif state == "weapon_unlocked_not_equipped":
            title = "무기 미장착"
            detail = ""
            color = C["accent"]
            icon = "🔓"
        else:
            title = "무기 시스템 없음"
            detail = ""
            color = C["dim"]
            icon = "?"
        inner = tk.Frame(weapon_f, bg=C["surface"])
        inner.pack(fill="x", padx=10, pady=8)
        tk.Label(inner, text=icon, bg=C["surface"], font=("Segoe UI Emoji", 22)).pack(side="left", padx=(0, 10))
        info = tk.Frame(inner, bg=C["surface"])
        info.pack(side="left")
        tk.Label(info, text=title, bg=C["surface"], fg=color, font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        if detail:
            tk.Label(info, text=detail, bg=C["surface"], fg=C["text"], font=("Consolas", 11, "bold")).pack(anchor="w")

        self._section(body, "장비")
        equip_f = tk.Frame(body, bg=C["card"])
        equip_f.pack(fill="x", padx=14, pady=(0, 8))
        for idx in range(1, 5):
            tier = self.s.get(f"equip{idx}")
            level = self.s.get(f"equip{idx}_level")
            color = tier_color(tier)
            cell = tk.Frame(equip_f, bg=C["surface"], highlightbackground=color, highlightthickness=1)
            cell.pack(side="left", padx=3, expand=True, fill="x")
            tk.Label(cell, text=f"SLOT {idx}", bg=C["surface"], fg=C["sub"], font=("Consolas", 7)).pack(pady=(4, 0))
            tk.Label(cell, text=tier_label(tier), bg=C["surface"], fg=color, font=("Consolas", 13, "bold")).pack()
            tk.Label(cell, text=f"Lv.{level}" if level is not None else "", bg=C["surface"], fg=C["sub"], font=("Consolas", 8)).pack(pady=(0, 4))


class StudentViewer(tk.Toplevel):
    def __init__(self, master=None):
        if master is None:
            self._root = tk.Tk()
            self._root.withdraw()
            super().__init__(self._root)
        else:
            super().__init__(master)

        self.title("BA Student Viewer")
        self.configure(bg=C["bg"])
        self.geometry("1100x720")
        self.minsize(640, 480)

        self._all_students: list[dict] = []
        self._filtered: list[dict] = []
        self._card_pool: list[tk.Canvas] = []
        self._modal: Optional[StudentModal] = None
        self._filter_after: Optional[str] = None
        self._resize_after: Optional[str] = None

        self._filter_star = tk.StringVar(value="all")
        self._filter_weapon = tk.StringVar(value="all")
        self._sort_mode = tk.StringVar(value="star_desc")
        self._search_var = tk.StringVar(value="")

        self._build_ui()
        self._search_var.trace_add("write", self._on_filter_change)
        self.bind("<Configure>", self._on_resize)
        self.after(100, self._load_data_async)

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=C["surface"], highlightbackground=C["border"], highlightthickness=1)
        header.pack(fill="x")

        tk.Label(
            header,
            text="BA  Student  Viewer",
            bg=C["surface"],
            fg=C["accent2"],
            font=("Malgun Gothic", 14, "bold"),
        ).pack(side="left", padx=14, pady=10)

        self._stat_frame = tk.Frame(header, bg=C["surface"])
        self._stat_frame.pack(side="left", padx=6)
        self._stat_labels: dict[str, tk.Label] = {}
        for key, text in [("total", "총 인원"), ("lv90", "Lv.90"), ("star5", "5성"), ("weapon", "무기")]:
            lbl = tk.Label(
                self._stat_frame,
                text=text,
                bg=C["surface"],
                fg=C["sub"],
                font=("Malgun Gothic", 8),
                relief="flat",
                padx=8,
                pady=3,
                highlightbackground=C["border"],
                highlightthickness=1,
            )
            lbl.pack(side="left", padx=3)
            self._stat_labels[key] = lbl

        filters = tk.Frame(header, bg=C["surface"])
        filters.pack(side="right", padx=10, pady=6)

        self._search_entry = tk.Entry(
            filters,
            textvariable=self._search_var,
            bg=C["card"],
            fg=C["text"],
            insertbackground=C["text"],
            relief="flat",
            font=FONT_BODY,
            highlightbackground=C["border"],
            highlightthickness=1,
            width=16,
        )
        self._search_entry.pack(side="left", padx=4, ipady=4)
        self._search_entry.insert(0, SEARCH_PLACEHOLDER)
        self._search_entry.bind(
            "<FocusIn>",
            lambda _e: self._search_entry.delete(0, "end") if self._search_entry.get() == SEARCH_PLACEHOLDER else None,
        )

        sort_menu = tk.OptionMenu(
            filters,
            self._sort_mode,
            "star_desc",
            "star_asc",
            "level_desc",
            "name_asc",
            command=lambda _value: self._apply_filter(),
        )
        sort_menu.config(bg=C["card"], fg=C["text"], relief="flat", font=FONT_SMALL, highlightthickness=0, activebackground=C["border"])
        sort_menu["menu"].config(bg=C["card"], fg=C["text"])
        sort_menu.pack(side="left", padx=4)

        star_f = tk.Frame(filters, bg=C["surface"])
        star_f.pack(side="left", padx=4)
        self._star_btns: list[tuple[str, tk.Button]] = []
        for label, value in [("전체", "all"), ("5성", "5"), ("4성", "4"), ("3성", "3"), ("2성", "2")]:
            btn = tk.Button(
                star_f,
                text=label,
                bg=C["accent"] if value == "all" else C["card"],
                fg="#fff" if value == "all" else C["sub"],
                relief="flat",
                font=FONT_SMALL,
                cursor="hand2",
                padx=6,
                pady=3,
                command=lambda v=value: self._set_star_filter(v),
            )
            btn.pack(side="left", padx=1)
            self._star_btns.append((value, btn))

        weapon_f = tk.Frame(filters, bg=C["surface"])
        weapon_f.pack(side="left", padx=4)
        self._weapon_btns: list[tuple[str, tk.Button]] = []
        for label, value in [("무기 전체", "all"), ("장착", "weapon_equipped"), ("없음", "no_weapon_system")]:
            btn = tk.Button(
                weapon_f,
                text=label,
                bg=C["accent"] if value == "all" else C["card"],
                fg="#fff" if value == "all" else C["sub"],
                relief="flat",
                font=FONT_SMALL,
                cursor="hand2",
                padx=6,
                pady=3,
                command=lambda v=value: self._set_weapon_filter(v),
            )
            btn.pack(side="left", padx=1)
            self._weapon_btns.append((value, btn))

        tk.Button(filters, text="새로고침", bg=C["card"], fg=C["sub"], relief="flat", font=FONT_SMALL, cursor="hand2", command=self._load_data_async).pack(side="left", padx=4, pady=2)

        self._count_bar = tk.Label(self, text="", bg=C["bg"], fg=C["sub"], font=FONT_SMALL, anchor="w")
        self._count_bar.pack(fill="x", padx=14, pady=(6, 2))

        self._canvas_frame = tk.Canvas(self, bg=C["bg"], highlightthickness=0)
        self._scrollbar = tk.Scrollbar(self, orient="vertical", command=self._on_scrollbar)
        self._canvas_frame.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas_frame.pack(side="left", fill="both", expand=True)

        self._grid_inner = tk.Frame(self._canvas_frame, bg=C["bg"])
        self._canvas_window = self._canvas_frame.create_window(0, 0, anchor="nw", window=self._grid_inner)

        self._grid_inner.bind("<Configure>", self._on_inner_configure)
        self._canvas_frame.bind("<Configure>", self._on_canvas_resize)
        self._canvas_frame.bind("<MouseWheel>", self._on_mousewheel)

    def _load_data_async(self) -> None:
        self._count_bar.config(text="  데이터 로드 중...")

        def task():
            students = load_students()
            self.after(0, lambda: self._on_data_loaded(students))

        threading.Thread(target=task, daemon=True).start()

    def _on_data_loaded(self, students: list[dict]) -> None:
        self._all_students = students
        self._update_stats()
        self._apply_filter()
        print(f"[Viewer] 학생 {len(students)}명 로드 완료")

    def _update_stats(self) -> None:
        total = len(self._all_students)
        lv90 = sum(1 for s in self._all_students if (s.get("level") or 0) >= 90)
        star5 = sum(1 for s in self._all_students if (s.get("student_star") or 0) >= 5)
        weapon = sum(1 for s in self._all_students if s.get("weapon_state") == "weapon_equipped")

        self._stat_labels["total"].config(text=f"총 {total}명")
        self._stat_labels["lv90"].config(text=f"Lv.90 {lv90}")
        self._stat_labels["star5"].config(text=f"5성 {star5}")
        self._stat_labels["weapon"].config(text=f"무기 {weapon}")

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
            arr = [
                s
                for s in arr
                if q in (s.get("display_name") or "").lower() or q in (s.get("student_id") or "").lower()
            ]

        mode = self._sort_mode.get()
        if mode == "star_desc":
            arr.sort(key=lambda s: (-(s.get("student_star") or 0), -(s.get("level") or 0)))
        elif mode == "star_asc":
            arr.sort(key=lambda s: ((s.get("student_star") or 0), (s.get("level") or 0)))
        elif mode == "level_desc":
            arr.sort(key=lambda s: -(s.get("level") or 0))
        elif mode == "name_asc":
            arr.sort(key=lambda s: (s.get("display_name") or ""))

        self._filtered = arr
        self._count_bar.config(text=f"  {len(arr)}명 표시 중 / 전체 {len(self._all_students)}명")
        self._canvas_frame.yview_moveto(0)
        self._refresh_virtual_grid(reset_pool=False)

    def _ensure_card_pool(self, needed: int) -> None:
        while len(self._card_pool) < needed:
            canvas = tk.Canvas(self._grid_inner, width=CARD_W, height=CARD_H, bg=C["card"], highlightthickness=0, cursor="hand2")
            _init_card_canvas(canvas)
            canvas.bind("<Enter>", self._on_card_enter)
            canvas.bind("<Leave>", self._on_card_leave)
            canvas.bind("<Button-1>", self._on_card_click)
            canvas.bind("<MouseWheel>", self._on_mousewheel)
            self._card_pool.append(canvas)

    def _compute_cols(self) -> int:
        width = max(self._canvas_frame.winfo_width(), CARD_W + GRID_PAD * 2)
        return max(COLS_MIN, (width - GRID_PAD) // (CARD_W + GRID_PAD))

    def _refresh_virtual_grid(self, reset_pool: bool = False) -> None:
        if reset_pool:
            for canvas in self._card_pool:
                canvas._data_idx = None

        cols = self._compute_cols()
        total = len(self._filtered)
        row_height = CARD_H + GRID_PAD
        rows = max(1, math.ceil(total / cols)) if total else 1
        width = cols * (CARD_W + GRID_PAD) + GRID_PAD
        height = rows * row_height + GRID_PAD

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
            x = GRID_PAD // 2 + col * (CARD_W + GRID_PAD)
            y = GRID_PAD // 2 + row * row_height
            canvas.place(x=x, y=y, width=CARD_W, height=CARD_H)
            if canvas._data_idx != idx:
                _update_card_canvas(canvas, self._filtered[idx])
                canvas._data_idx = idx

        for slot in range(len(visible_indices), len(self._card_pool)):
            canvas = self._card_pool[slot]
            canvas.place_forget()
            canvas._data_idx = None
            canvas._student_data = None
            _set_card_hover(canvas, False)

    def _open_modal(self, student: dict) -> None:
        if self._modal and self._modal.winfo_exists():
            self._modal.destroy()
        self._modal = StudentModal(self, student)

    def _on_card_enter(self, event) -> None:
        widget = event.widget
        if getattr(widget, "_student_data", None) is not None:
            _set_card_hover(widget, True)

    def _on_card_leave(self, event) -> None:
        _set_card_hover(event.widget, False)

    def _on_card_click(self, event) -> None:
        student = getattr(event.widget, "_student_data", None)
        if student is not None:
            self._open_modal(student)

    def _on_scrollbar(self, *args) -> None:
        self._canvas_frame.yview(*args)
        self._refresh_virtual_grid()

    def _on_canvas_scroll(self, first, last) -> None:
        self._scrollbar.set(first, last)

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
        if hasattr(self, "_root"):
            self._root.mainloop()
        else:
            self.mainloop()


def open_viewer(master=None) -> StudentViewer:
    return StudentViewer(master)


if __name__ == "__main__":
    viewer = StudentViewer()
    viewer.run()
