"""
gui/student_viewer.py — BA Student Viewer (tkinter 자체 창)

DB(data/current/students.json 또는 SQLite)에서 학생 데이터를 로드하고
templates/students/ 폴더에서 이미지를 가져와 그리드로 표시.

실행:
  python gui/student_viewer.py
  (또는 main.py에서 뷰어 버튼으로 호출)
"""

import json
import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Optional

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFilter, ImageEnhance
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ── 경로 ──────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent.parent
TEMPLATE_DIR  = BASE_DIR / "templates" / "students_portraits"
CURRENT_JSON  = BASE_DIR / "data" / "current" / "students.json"
DB_PATH       = BASE_DIR / "ba_planner.db"

# ── 색상 팔레트 (HTML 뷰어와 동일) ───────────────────────
C = {
    "bg":       "#080c14",
    "surface":  "#0e1520",
    "card":     "#111927",
    "card_h":   "#16202e",
    "border":   "#1a2e40",
    "accent":   "#4aa8e0",
    "accent2":  "#6ec6ff",
    "gold":     "#f0c040",
    "gold2":    "#ffd966",
    "green":    "#3dbf7a",
    "red":      "#e85a5a",
    "purple":   "#b388ff",
    "text":     "#d6eaf8",
    "sub":      "#5c8aaa",
    "dim":      "#2a3d52",
    "star_on":  "#f0c040",
    "star_off": "#2a3d52",
    # 성작별 상단 컬러라인
    "star5":    "#f0c040",
    "star4":    "#b388ff",
    "star3":    "#4aa8e0",
    "star2":    "#3dbf7a",
    "star1":    "#e85a5a",
    # 장비 티어별
    "t1": "#90c090", "t2": "#4aa8e0", "t3": "#b388ff",
    "t4": "#f0c040", "t5": "#f07060", "t6": "#f0a040",
    "t7": "#64dccc", "t8": "#ffa0c8", "t9": "#ffdc64", "t10": "#f0f0ff",
}

FONT_TITLE = ("Malgun Gothic", 13, "bold")
FONT_BODY  = ("Malgun Gothic", 9)
FONT_SMALL = ("Malgun Gothic", 8)
FONT_MONO  = ("Consolas", 9)

CARD_W = 160
CARD_H = 260
PHOTO_SIZE = 130
GRID_PAD = 10
COLS_MIN = 4


# ── 데이터 로드 ───────────────────────────────────────────
def load_students() -> list[dict]:
    """DB → JSON 순으로 시도해 학생 목록 반환."""
    # 1) SQLite
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM students ORDER BY student_id"
            ).fetchall()
            conn.close()
            if rows:
                return [dict(r) for r in rows]
        except Exception as e:
            print(f"[Viewer] DB 로드 실패: {e}")

    # 2) JSON fallback
    if CURRENT_JSON.exists():
        try:
            data = json.loads(CURRENT_JSON.read_text(encoding="utf-8"))
            return list(data.values())
        except Exception as e:
            print(f"[Viewer] JSON 로드 실패: {e}")

    return []


# ── 이미지 로드 ───────────────────────────────────────────
_img_cache: dict[str, Optional[ImageTk.PhotoImage]] = {}


def _load_photo(student_id: str, size: tuple) -> Optional[ImageTk.PhotoImage]:
    """templates/students/{student_id}.png 로드 + 리사이즈."""
    if not HAS_PIL:
        return None

    key = f"{student_id}_{size[0]}x{size[1]}"
    if key in _img_cache:
        return _img_cache[key]

    # 파일 탐색
    candidates = [
        TEMPLATE_DIR / f"{student_id}.png",
        TEMPLATE_DIR / f"{student_id}.jpg",
    ]
    path = next((p for p in candidates if p.exists()), None)

    if path is None:
        _img_cache[key] = None
        return None

    try:
        img = Image.open(path).convert("RGBA")
        img.thumbnail(size, Image.LANCZOS)

        # 정방형 캔버스에 중앙 배치
        canvas = Image.new("RGBA", size, (0, 0, 0, 0))
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        canvas.paste(img, offset)

        # RGB 변환
        bg = Image.new("RGB", size, C["surface"])
        bg.paste(canvas, mask=canvas.split()[3])

        photo = ImageTk.PhotoImage(bg)
        _img_cache[key] = photo
        return photo
    except Exception as e:
        print(f"[Viewer] 이미지 로드 실패 ({student_id}): {e}")
        _img_cache[key] = None
        return None


def _load_photo_large(student_id: str, w: int, h: int) -> Optional[ImageTk.PhotoImage]:
    """모달용 16:9 비율 큰 이미지."""
    if not HAS_PIL:
        return None
    key = f"{student_id}_modal_{w}x{h}"
    if key in _img_cache:
        return _img_cache[key]

    candidates = [
        TEMPLATE_DIR / f"{student_id}.png",
        TEMPLATE_DIR / f"{student_id}.jpg",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        _img_cache[key] = None
        return None

    try:
        img = Image.open(path).convert("RGB")
        # 크롭: 상단 기준
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
    except Exception as e:
        _img_cache[key] = None
        return None


# ── 유틸 ──────────────────────────────────────────────────
def star_color(n: int) -> str:
    return C.get(f"star{n}", C["dim"])


def tier_color(t: Optional[str]) -> str:
    if not t or t in ("empty", "null", "unknown"):
        return C["dim"]
    if t in ("level_locked", "love_locked"):
        return C["sub"]
    m = t.replace("T", "").replace("t", "")
    return C.get(f"t{m}", C["dim"])


def tier_label(t: Optional[str]) -> str:
    if not t:                    return "—"
    if t == "empty":             return "빈칸"
    if t == "level_locked":      return "Lv잠금"
    if t == "love_locked":       return "♡잠금"
    if t == "null":              return "없음"
    return t


def weapon_label(ws: Optional[str]) -> str:
    if ws == "weapon_equipped":            return "⚔ 장착"
    if ws == "weapon_unlocked_not_equipped": return "🔓 미장착"
    return "—"


# ── 카드 캔버스 렌더 ──────────────────────────────────────
def draw_card_on_canvas(canvas: tk.Canvas, s: dict, w: int, h: int, hover: bool):
    """단일 카드를 canvas 위에 직접 그리는 함수."""
    canvas.delete("all")
    bg = C["card_h"] if hover else C["card"]
    star_n = s.get("student_star") or 0

    # 배경
    canvas.create_rectangle(0, 0, w, h, fill=bg, outline="")

    # 성작 컬러라인 (상단 3px)
    line_color = star_color(star_n)
    canvas.create_rectangle(0, 0, w, 3, fill=line_color, outline="")

    # 테두리
    border_col = C["border"] if not hover else C["accent"]
    canvas.create_rectangle(0, 0, w-1, h-1,
                             outline=border_col, fill="", width=1)

    photo_h = PHOTO_SIZE
    sid = s.get("student_id", "")

    # 사진 영역 배경
    canvas.create_rectangle(0, 3, w, 3 + photo_h,
                             fill=C["surface"], outline="")

    # 이미지
    photo = _load_photo(sid, (w, photo_h))
    if photo:
        canvas.create_image(w // 2, 3 + photo_h // 2, image=photo, anchor="center")
        canvas.photo_ref = photo  # GC 방지
    else:
        canvas.create_text(w // 2, 3 + photo_h // 2,
                           text="🎓", font=("Segoe UI Emoji", 24), fill=C["dim"])
        canvas.create_text(w // 2, 3 + photo_h // 2 + 28,
                           text=sid[:14], font=FONT_SMALL, fill=C["dim"])

    # 레벨 뱃지 (사진 좌하단)
    lv = s.get("level")
    lv_txt = f"Lv.{lv}" if lv else "Lv.?"
    canvas.create_rectangle(4, 3 + photo_h - 18, 4 + 38, 3 + photo_h - 3,
                             fill="#0a0f1a",
                             outline=C["border"])
    canvas.create_text(23, 3 + photo_h - 10,
                       text=lv_txt, font=("Consolas", 7, "bold"),
                       fill=C["accent2"])

    # 무기 뱃지 (사진 우상단)
    ws = s.get("weapon_state")
    if ws == "weapon_equipped":
        wstar = s.get("weapon_star") or "?"
        wlbl = f"⚔{wstar}★"
        canvas.create_rectangle(w - 40, 6, w - 3, 20,
                                 fill="#0a0f1a", outline=C["gold"])
        canvas.create_text(w - 21, 13, text=wlbl,
                           font=("Malgun Gothic", 6, "bold"), fill=C["gold"])
    elif ws == "weapon_unlocked_not_equipped":
        canvas.create_rectangle(w - 26, 6, w - 3, 20,
                                 fill="#0a0f1a", outline=C["accent"])
        canvas.create_text(w - 14, 13, text="🔓",
                           font=("Segoe UI Emoji", 7), fill=C["accent"])

    # ── 카드 바디 ─────────────────────────────────────────
    y = 3 + photo_h + 6

    # 이름
    name = s.get("display_name") or sid
    canvas.create_text(w // 2, y,
                       text=name, font=("Malgun Gothic", 8, "bold"),
                       fill=C["text"], width=w - 8, anchor="n")
    y += 18

    # 별
    star_txt = "★" * star_n + "☆" * (5 - star_n)
    canvas.create_text(w // 2, y,
                       text=star_txt, font=("Malgun Gothic", 7),
                       fill=C["gold"], anchor="n")
    y += 14

    # 스킬
    skills = [
        ("EX", s.get("ex_skill")),
        ("S1", s.get("skill1")),
        ("S2", s.get("skill2")),
    ]
    if s.get("skill3") is not None:
        skills.append(("S3", s.get("skill3")))

    chip_w = (w - 8 - (len(skills) - 1) * 3) // len(skills)
    cx = 4
    for lbl, val in skills:
        canvas.create_rectangle(cx, y, cx + chip_w, y + 13,
                                 fill=C["surface"], outline=C["dim"])
        canvas.create_text(cx + chip_w // 2, y + 6,
                           text=f"{lbl} {val if val is not None else '?'}",
                           font=("Consolas", 6, "bold"), fill=C["accent2"])
        cx += chip_w + 3
    y += 17

    # 장비
    equips = [
        (s.get("equip1"), s.get("equip1_level")),
        (s.get("equip2"), s.get("equip2_level")),
        (s.get("equip3"), s.get("equip3_level")),
        (s.get("equip4"), None),
    ]
    eq_w = (w - 8 - 9) // 4
    ex = 4
    for t, lv in equips:
        col = tier_color(t)
        canvas.create_rectangle(ex, y, ex + eq_w, y + 18,
                                 fill=C["surface"], outline=col if col != C["dim"] else C["dim"],
                                 width=1)
        canvas.create_text(ex + eq_w // 2, y + 6,
                           text=tier_label(t), font=("Consolas", 6), fill=col)
        if lv is not None:
            canvas.create_text(ex + eq_w // 2, y + 13,
                               text=f"L{lv}", font=("Consolas", 5), fill=C["sub"])
        ex += eq_w + 3


# ── 모달 창 ───────────────────────────────────────────────
class StudentModal(tk.Toplevel):
    def __init__(self, master, s: dict):
        super().__init__(master)
        self.s = s
        sid = s.get("student_id", "")
        name = s.get("display_name") or sid

        self.title(f"{name} — 상세 정보")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.attributes("-topmost", True)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 480, 620
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._build(w)

        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()
        self.focus_force()

    def _build(self, W: int):
        sid = self.s.get("student_id", "")
        name = self.s.get("display_name") or sid

        # ── 사진 영역 (16:9)
        ph = int(W * 9 / 16)
        photo_frame = tk.Frame(self, bg=C["surface"], width=W, height=ph)
        photo_frame.pack(fill="x")
        photo_frame.pack_propagate(False)

        photo_canvas = tk.Canvas(photo_frame, width=W, height=ph,
                                  bg=C["surface"], highlightthickness=0)
        photo_canvas.pack()

        photo = _load_photo_large(sid, W, ph)
        if photo:
            photo_canvas.create_image(0, 0, image=photo, anchor="nw")
            photo_canvas._photo = photo
        else:
            photo_canvas.create_text(W // 2, ph // 2, text="🎓",
                                     font=("Segoe UI Emoji", 48), fill=C["dim"])

        # 오버레이: 레벨 + 성작
        lv = self.s.get("level")
        star_n = self.s.get("student_star") or 0
        photo_canvas.create_rectangle(8, ph - 26, 80, ph - 4,
                                       fill="#0a0f1a", outline=C["border"])
        photo_canvas.create_text(44, ph - 15,
                                  text=f"Lv.{lv or '?'}",
                                  font=("Consolas", 11, "bold"), fill=C["accent2"])
        star_txt = "★" * star_n
        photo_canvas.create_text(W - 8, ph - 14,
                                  text=star_txt, font=("Malgun Gothic", 12),
                                  fill=C["gold"], anchor="e")

        # ── 바디
        body = tk.Frame(self, bg=C["card"])
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # 이름 행
        name_row = tk.Frame(body, bg=C["card"])
        name_row.pack(fill="x", padx=14, pady=(12, 0))

        star_line_color = star_color(star_n)
        tk.Label(name_row, text=name,
                 bg=C["card"], fg=C["text"],
                 font=("Malgun Gothic", 16, "bold")).pack(side="left")
        tk.Label(name_row, text=f"   {sid}",
                 bg=C["card"], fg=C["dim"],
                 font=("Consolas", 8)).pack(side="left", pady=(4, 0))
        tk.Button(name_row, text="✕",
                  bg=C["surface"], fg=C["sub"],
                  font=("Arial", 10), relief="flat", cursor="hand2",
                  command=self.destroy).pack(side="right")

        # 컬러라인
        tk.Frame(body, bg=star_line_color, height=2).pack(fill="x", padx=14, pady=(4, 8))

        # ── 스킬 섹션
        self._section(body, "스킬 레벨")
        skill_f = tk.Frame(body, bg=C["card"])
        skill_f.pack(fill="x", padx=14, pady=(0, 8))

        skills = [
            ("EX", self.s.get("ex_skill")),
            ("S1", self.s.get("skill1")),
            ("S2", self.s.get("skill2")),
            ("S3", self.s.get("skill3")),
        ]
        for lbl, val in skills:
            cell = tk.Frame(skill_f, bg=C["surface"],
                            highlightbackground=C["border"],
                            highlightthickness=1)
            cell.pack(side="left", padx=3, pady=2, expand=True, fill="x")
            tk.Label(cell, text=lbl, bg=C["surface"], fg=C["sub"],
                     font=("Consolas", 8)).pack()
            display = str(val) if val is not None else "—"
            col = C["accent2"] if val is not None else C["dim"]
            tk.Label(cell, text=display, bg=C["surface"], fg=col,
                     font=("Consolas", 18, "bold")).pack()

        # ── 무기 섹션
        self._section(body, "무기")
        ws = self.s.get("weapon_state")
        weapon_f = tk.Frame(body, bg=C["surface"],
                             highlightbackground=C["border"],
                             highlightthickness=1)
        weapon_f.pack(fill="x", padx=14, pady=(0, 8))

        if ws == "weapon_equipped":
            icon, state_col, state_lbl = "⚔️", C["gold"], "무기 장착"
            wstar = self.s.get("weapon_star") or "?"
            wlv   = self.s.get("weapon_level") or "?"
            detail = f"{wstar}★  Lv.{wlv}"
        elif ws == "weapon_unlocked_not_equipped":
            icon, state_col, state_lbl = "🔓", C["accent"], "미장착"
            detail = ""
        else:
            icon, state_col, state_lbl = "🗡️", C["dim"], "무기 시스템 없음"
            detail = ""

        w_inner = tk.Frame(weapon_f, bg=C["surface"])
        w_inner.pack(fill="x", padx=10, pady=8)
        tk.Label(w_inner, text=icon, bg=C["surface"],
                 font=("Segoe UI Emoji", 22)).pack(side="left", padx=(0, 10))
        w_info = tk.Frame(w_inner, bg=C["surface"])
        w_info.pack(side="left")
        tk.Label(w_info, text=state_lbl, bg=C["surface"], fg=state_col,
                 font=("Malgun Gothic", 10, "bold")).pack(anchor="w")
        if detail:
            tk.Label(w_info, text=detail, bg=C["surface"], fg=C["text"],
                     font=("Consolas", 11, "bold")).pack(anchor="w")

        # ── 장비 섹션
        self._section(body, "장비 슬롯")
        equip_f = tk.Frame(body, bg=C["card"])
        equip_f.pack(fill="x", padx=14, pady=(0, 8))

        for i in range(1, 5):
            t  = self.s.get(f"equip{i}")
            lv = self.s.get(f"equip{i}_level")
            col = tier_color(t)
            cell = tk.Frame(equip_f, bg=C["surface"],
                             highlightbackground=col,
                             highlightthickness=1)
            cell.pack(side="left", padx=3, expand=True, fill="x")
            tk.Label(cell, text=f"SLOT {i}", bg=C["surface"], fg=C["sub"],
                     font=("Consolas", 7)).pack(pady=(4, 0))
            tk.Label(cell, text=tier_label(t), bg=C["surface"], fg=col,
                     font=("Consolas", 13, "bold")).pack()
            if lv is not None:
                tk.Label(cell, text=f"Lv.{lv}", bg=C["surface"], fg=C["sub"],
                         font=("Consolas", 8)).pack(pady=(0, 4))
            else:
                tk.Label(cell, text="", bg=C["surface"], height=1).pack()

    def _section(self, parent, title: str):
        tk.Label(parent, text=title.upper(),
                 bg=C["card"], fg=C["sub"],
                 font=("Malgun Gothic", 7, "bold")).pack(
                     anchor="w", padx=14, pady=(0, 2))


# ── 메인 뷰어 창 ──────────────────────────────────────────
class StudentViewer(tk.Toplevel):
    """
    BA Student Viewer — 자체 tkinter 창.

    사용:
        viewer = StudentViewer(master)
    """

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
        self._filtered:     list[dict] = []
        self._card_widgets: list[tk.Canvas] = []
        self._modal: Optional[StudentModal] = None

        self._filter_star   = tk.StringVar(value="all")
        self._filter_weapon = tk.StringVar(value="all")
        self._sort_mode     = tk.StringVar(value="star_desc")
        self._search_var    = tk.StringVar(value="")

        self._build_ui()
        # _build_ui() 완료 후 trace 등록 (_count_bar 등 위젯 생성 보장)
        self._search_var.trace_add("write", self._on_filter_change)
        self.bind("<Configure>", self._on_resize)
        self.after(100, self._load_data_async)

    # ── UI 구성 ───────────────────────────────────────────
    def _build_ui(self):
        # 헤더
        self._header = tk.Frame(self, bg=C["surface"],
                                 highlightbackground=C["border"],
                                 highlightthickness=1)
        self._header.pack(fill="x", padx=0, pady=0)

        # 제목
        tk.Label(self._header,
                 text="BA  Student  Viewer",
                 bg=C["surface"], fg=C["accent2"],
                 font=("Malgun Gothic", 14, "bold")).pack(side="left", padx=14, pady=10)

        # 통계 레이블들
        self._stat_frame = tk.Frame(self._header, bg=C["surface"])
        self._stat_frame.pack(side="left", padx=6)
        self._stat_labels: dict[str, tk.Label] = {}
        for key, txt in [("total", "총 —명"), ("lv90", "Lv.90 —"),
                          ("star5", "5★ —"), ("weapon", "무기 —")]:
            lbl = tk.Label(self._stat_frame, text=txt,
                           bg=C["surface"], fg=C["sub"],
                           font=("Malgun Gothic", 8),
                           relief="flat", padx=8, pady=3,
                           highlightbackground=C["border"],
                           highlightthickness=1)
            lbl.pack(side="left", padx=3)
            self._stat_labels[key] = lbl

        # 필터 영역 (오른쪽)
        filter_frame = tk.Frame(self._header, bg=C["surface"])
        filter_frame.pack(side="right", padx=10, pady=6)

        # 검색
        search_entry = tk.Entry(filter_frame,
                                textvariable=self._search_var,
                                bg=C["card"], fg=C["text"],
                                insertbackground=C["text"],
                                relief="flat", font=FONT_BODY,
                                highlightbackground=C["border"],
                                highlightthickness=1, width=16)
        search_entry.pack(side="left", padx=4, ipady=4)
        search_entry.insert(0, "이름 검색...")
        search_entry.bind("<FocusIn>", lambda e: (
            search_entry.delete(0, "end") if search_entry.get() == "이름 검색..." else None
        ))

        # 정렬
        sort_opts = [("성작↓", "star_desc"), ("성작↑", "star_asc"),
                     ("레벨↓", "level_desc"), ("이름순", "name_asc")]
        sort_m = tk.OptionMenu(filter_frame, self._sort_mode,
                                *[v for _, v in sort_opts],
                                command=lambda _: self._on_filter_change())
        self._sort_mode.set("star_desc")
        sort_m.config(bg=C["card"], fg=C["text"], relief="flat",
                       font=FONT_SMALL, highlightthickness=0,
                       activebackground=C["border"])
        sort_m["menu"].config(bg=C["card"], fg=C["text"])
        sort_m.pack(side="left", padx=4)

        # 성작 필터 버튼
        star_f = tk.Frame(filter_frame, bg=C["surface"])
        star_f.pack(side="left", padx=4)
        self._star_btns: list[tk.Button] = []
        for lbl, val in [("전체", "all"), ("⭐5", "5"), ("⭐4", "4"),
                          ("⭐3", "3"), ("⭐2", "2")]:
            btn = tk.Button(star_f, text=lbl,
                             bg=C["accent"] if val == "all" else C["card"],
                             fg="#fff" if val == "all" else C["sub"],
                             relief="flat", font=FONT_SMALL, cursor="hand2",
                             padx=6, pady=3,
                             command=lambda v=val: self._set_star_filter(v))
            btn.pack(side="left", padx=1)
            self._star_btns.append((val, btn))

        # 무기 필터
        weapon_f = tk.Frame(filter_frame, bg=C["surface"])
        weapon_f.pack(side="left", padx=4)
        self._weapon_btns = []
        for lbl, val in [("무기 전체", "all"), ("장착", "weapon_equipped"), ("없음", "no_weapon_system")]:
            btn = tk.Button(weapon_f, text=lbl,
                             bg=C["accent"] if val == "all" else C["card"],
                             fg="#fff" if val == "all" else C["sub"],
                             relief="flat", font=FONT_SMALL, cursor="hand2",
                             padx=6, pady=3,
                             command=lambda v=val: self._set_weapon_filter(v))
            btn.pack(side="left", padx=1)
            self._weapon_btns.append((val, btn))

        # 새로고침
        tk.Button(filter_frame, text="🔄",
                  bg=C["card"], fg=C["sub"],
                  relief="flat", font=FONT_SMALL, cursor="hand2",
                  command=self._load_data_async).pack(side="left", padx=4, pady=2)

        # 카운트 바
        self._count_bar = tk.Label(self, text="",
                                    bg=C["bg"], fg=C["sub"],
                                    font=FONT_SMALL, anchor="w")
        self._count_bar.pack(fill="x", padx=14, pady=(6, 2))

        # 스크롤 그리드 영역
        self._canvas_frame = tk.Canvas(self, bg=C["bg"],
                                        highlightthickness=0)
        self._scrollbar = tk.Scrollbar(self, orient="vertical",
                                        command=self._canvas_frame.yview)
        self._canvas_frame.configure(yscrollcommand=self._scrollbar.set)
        self._scrollbar.pack(side="right", fill="y")
        self._canvas_frame.pack(side="left", fill="both", expand=True)

        self._grid_inner = tk.Frame(self._canvas_frame, bg=C["bg"])
        self._canvas_window = self._canvas_frame.create_window(
            0, 0, anchor="nw", window=self._grid_inner
        )
        self._grid_inner.bind("<Configure>", self._on_inner_configure)
        self._canvas_frame.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas_frame.bind("<Configure>", self._on_canvas_resize)

    # ── 데이터 로드 ───────────────────────────────────────
    def _load_data_async(self):
        self._count_bar.config(text="📡 데이터 로딩 중...")

        def task():
            students = load_students()
            self.after(0, lambda: self._on_data_loaded(students))

        threading.Thread(target=task, daemon=True).start()

    def _on_data_loaded(self, students: list[dict]):
        self._all_students = students
        self._update_stats()
        self._apply_filter()
        print(f"[Viewer] 학생 {len(students)}명 로드 완료")

    # ── 통계 업데이트 ─────────────────────────────────────
    def _update_stats(self):
        s = self._all_students
        total  = len(s)
        lv90   = sum(1 for x in s if (x.get("level") or 0) >= 90)
        star5  = sum(1 for x in s if (x.get("student_star") or 0) >= 5)
        weapon = sum(1 for x in s if x.get("weapon_state") == "weapon_equipped")

        self._stat_labels["total"].config(text=f"총 {total}명")
        self._stat_labels["lv90"].config(text=f"Lv.90 {lv90}")
        self._stat_labels["star5"].config(text=f"5★ {star5}")
        self._stat_labels["weapon"].config(text=f"무기장착 {weapon}")

    # ── 필터/정렬 ─────────────────────────────────────────
    def _set_star_filter(self, val: str):
        self._filter_star.set(val)
        for v, btn in self._star_btns:
            btn.config(bg=C["accent"] if v == val else C["card"],
                        fg="#fff" if v == val else C["sub"])
        self._apply_filter()

    def _set_weapon_filter(self, val: str):
        self._filter_weapon.set(val)
        for v, btn in self._weapon_btns:
            btn.config(bg=C["accent"] if v == val else C["card"],
                        fg="#fff" if v == val else C["sub"])
        self._apply_filter()

    def _on_filter_change(self, *_):
        self._apply_filter()

    def _apply_filter(self):
        star   = self._filter_star.get()
        weapon = self._filter_weapon.get()
        q      = self._search_var.get().strip()
        if q == "이름 검색...":
            q = ""

        arr = list(self._all_students)

        if star != "all":
            arr = [s for s in arr if str(s.get("student_star") or "") == star]
        if weapon != "all":
            arr = [s for s in arr if s.get("weapon_state") == weapon]
        if q:
            ql = q.lower()
            arr = [s for s in arr
                   if ql in (s.get("display_name") or "").lower()
                   or ql in (s.get("student_id") or "").lower()]

        mode = self._sort_mode.get()
        if mode == "star_desc":
            arr.sort(key=lambda s: (-(s.get("student_star") or 0),
                                     -(s.get("level") or 0)))
        elif mode == "star_asc":
            arr.sort(key=lambda s: ((s.get("student_star") or 0),
                                     (s.get("level") or 0)))
        elif mode == "level_desc":
            arr.sort(key=lambda s: -(s.get("level") or 0))
        elif mode == "name_asc":
            arr.sort(key=lambda s: (s.get("display_name") or ""))

        self._filtered = arr
        total = len(self._all_students)
        self._count_bar.config(
            text=f"  {len(arr)}명 표시 중 / 전체 {total}명"
        )
        self._render_grid()

    # ── 그리드 렌더 ───────────────────────────────────────
    def _render_grid(self):
        # 기존 카드 제거
        for w in self._grid_inner.winfo_children():
            w.destroy()
        self._card_widgets.clear()

        cw = self._canvas_frame.winfo_width()
        cols = max(COLS_MIN, (cw - GRID_PAD) // (CARD_W + GRID_PAD))

        for i, s in enumerate(self._filtered):
            row = i // cols
            col = i % cols

            c = tk.Canvas(self._grid_inner,
                           width=CARD_W, height=CARD_H,
                           bg=C["card"], highlightthickness=0,
                           cursor="hand2")
            c.grid(row=row, column=col,
                    padx=GRID_PAD // 2, pady=GRID_PAD // 2)

            # 초기 렌더
            draw_card_on_canvas(c, s, CARD_W, CARD_H, hover=False)
            self._card_widgets.append(c)

            # 호버 효과
            def _enter(event, cv=c, st=s):
                draw_card_on_canvas(cv, st, CARD_W, CARD_H, hover=True)

            def _leave(event, cv=c, st=s):
                draw_card_on_canvas(cv, st, CARD_W, CARD_H, hover=False)

            def _click(event, st=s):
                self._open_modal(st)

            c.bind("<Enter>", _enter)
            c.bind("<Leave>", _leave)
            c.bind("<Button-1>", _click)
            c.bind("<MouseWheel>", self._on_mousewheel)

        # 스크롤 영역 업데이트
        self._grid_inner.update_idletasks()
        self._canvas_frame.configure(
            scrollregion=self._canvas_frame.bbox("all")
        )

    # ── 모달 ──────────────────────────────────────────────
    def _open_modal(self, s: dict):
        if self._modal and self._modal.winfo_exists():
            self._modal.destroy()
        self._modal = StudentModal(self, s)

    # ── 스크롤 / 리사이즈 ─────────────────────────────────
    def _on_mousewheel(self, e):
        self._canvas_frame.yview_scroll(-1 * (e.delta // 120), "units")

    def _on_inner_configure(self, e):
        self._canvas_frame.configure(
            scrollregion=self._canvas_frame.bbox("all")
        )

    def _on_canvas_resize(self, e):
        self._canvas_frame.itemconfig(self._canvas_window, width=e.width)

    def _on_resize(self, e):
        # 창 크기 변경 시 그리드 재렌더 (컬럼 수 재계산)
        if hasattr(self, "_resize_after"):
            self.after_cancel(self._resize_after)
        self._resize_after = self.after(200, self._render_grid)

    # ── 독립 실행용 ───────────────────────────────────────
    def run(self):
        """단독 실행 시 mainloop."""
        if hasattr(self, "_root"):
            self._root.mainloop()
        else:
            self.mainloop()


# ── 진입점 ────────────────────────────────────────────────
def open_viewer(master=None) -> StudentViewer:
    """main.py 등 외부에서 호출하는 팩토리 함수."""
    viewer = StudentViewer(master)
    return viewer


if __name__ == "__main__":
    viewer = StudentViewer()
    viewer.run()