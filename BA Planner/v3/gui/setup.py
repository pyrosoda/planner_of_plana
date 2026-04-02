"""
gui/setup.py
설정 위자드: 닉네임 입력 + 영역 드래그 + 버튼 좌표 클릭 설정
"""
import tkinter as tk
from tkinter import ttk
from typing import Callable

from core.config import save_config, load_config

# ── 색상 ──────────────────────────────────────────────────
BG       = "#0d1b2a"
CARD     = "#152435"
BLUE     = "#1a6fad"
LBLUE    = "#4aa8e0"
YELLOW   = "#f5c842"
GREEN    = "#3dbf7a"
ORANGE   = "#e8894a"
PURPLE   = "#c97bec"
TEXT     = "#e8f4fd"
SUBTEXT  = "#7ab3d4"
FONT     = "Malgun Gothic"

# ── 설정 단계 정의 ─────────────────────────────────────────
# type: "region"  → 드래그로 영역 지정
#       "point"   → 클릭으로 좌표 지정
#       "text"    → 텍스트 입력
SETUP_STEPS = [
    {
        "key":         "nickname",
        "type":        "text",
        "label":       "플레이어 닉네임",
        "description": "블루아카이브 로비 좌측 상단에 표시되는\n닉네임을 입력해주세요",
        "color":       YELLOW,
    },
    {
        "key":         "nickname_region",
        "type":        "region",
        "label":       "닉네임 감지 영역",
        "description": "좌측 상단 Lv.xx 닉네임이 표시된\n영역에 틀을 맞춰주세요",
        "hint_ratio":  (0.00, 0.00, 0.22, 0.10),
        "color":       YELLOW,
    },
    {
        "key":         "resources",
        "type":        "region",
        "label":       "상단 재화 바",
        "description": "청휘석·크레딧이 표시된\n상단 영역을 틀에 맞춰주세요",
        "hint_ratio":  (0.55, 0.00, 0.90, 0.07),
        "color":       YELLOW,
    },
    {
        "key":         "menu_button",
        "type":        "point",
        "label":       "메뉴(⋮) 버튼",
        "description": "우측 상단 메뉴 버튼을\n클릭해주세요",
        "color":       LBLUE,
    },
    {
        "key":         "menu_item_button",
        "type":        "point",
        "label":       "메뉴 내 아이템 버튼",
        "description": "메뉴를 열어놓은 상태에서\n아이템 버튼을 클릭해주세요",
        "color":       ORANGE,
    },
    {
        "key":         "menu_equipment_button",
        "type":        "point",
        "label":       "메뉴 내 장비 버튼",
        "description": "메뉴를 열어놓은 상태에서\n장비 버튼을 클릭해주세요",
        "color":       PURPLE,
    },
    {
        "key":         "item_grid",
        "type":        "region",
        "label":       "아이템 그리드",
        "description": "아이템 화면의 슬롯 격자 전체를\n틀에 맞춰주세요",
        "hint_ratio":  (0.53, 0.20, 0.99, 0.98),
        "grid":        (5, 4),
        "color":       LBLUE,
    },
    {
        "key":         "item_detail",
        "type":        "region",
        "label":       "아이템 상세 패널",
        "description": "아이템 선택 시 나타나는\n이름·수량 패널에 틀을 맞춰주세요",
        "hint_ratio":  (0.02, 0.75, 0.50, 0.90),
        "color":       ORANGE,
    },
    {
        "key":         "equipment_grid",
        "type":        "region",
        "label":       "장비 그리드",
        "description": "장비 화면의 슬롯 격자 전체를\n틀에 맞춰주세요",
        "hint_ratio":  (0.53, 0.20, 0.99, 0.98),
        "grid":        (5, 4),
        "color":       PURPLE,
    },
    {
        "key":         "equipment_detail",
        "type":        "region",
        "label":       "장비 상세 패널",
        "description": "장비 선택 시 나타나는\n이름·수량 패널에 틀을 맞춰주세요",
        "hint_ratio":  (0.02, 0.75, 0.50, 0.90),
        "color":       PURPLE,
    },
]

HANDLE_SIZE = 10
MIN_SIZE    = 50


class TextStep(tk.Toplevel):
    """닉네임 등 텍스트 입력 단계"""
    def __init__(self, master, step: dict,
                 step_num: int, total: int,
                 on_confirm: Callable, on_cancel: Callable,
                 existing_value: str = ""):
        super().__init__(master)
        self.on_confirm = on_confirm
        self.on_cancel  = on_cancel

        self.title("")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 420, 240
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        color = step["color"]

        # 상단 컬러 바
        tk.Frame(self, bg=color, height=4).pack(fill="x")

        # STEP 배지
        badge_f = tk.Frame(self, bg=BG)
        badge_f.pack(pady=(16, 0))
        tk.Label(badge_f, text=f"  STEP {step_num}/{total}  ",
                 bg=color, fg=BG,
                 font=(FONT, 11, "bold")).pack()

        tk.Label(self, text=step["label"],
                 bg=BG, fg=TEXT,
                 font=(FONT, 15, "bold")).pack(pady=(10, 4))

        tk.Label(self, text=step["description"],
                 bg=BG, fg=SUBTEXT,
                 font=(FONT, 10), justify="center").pack()

        self._var = tk.StringVar(value=existing_value)
        entry = tk.Entry(self, textvariable=self._var,
                         bg=CARD, fg=TEXT, insertbackground=TEXT,
                         font=(FONT, 13), relief="flat",
                         width=24, justify="center")
        entry.pack(pady=12)
        entry.focus_set()

        btn_f = tk.Frame(self, bg=BG)
        btn_f.pack()
        tk.Button(btn_f, text="✅  확인",
                  bg=color, fg=BG,
                  font=(FONT, 11, "bold"),
                  relief="flat", padx=14, pady=6,
                  cursor="hand2",
                  command=self._confirm).pack(side="left", padx=6)
        tk.Button(btn_f, text="❌  취소",
                  bg=CARD, fg=SUBTEXT,
                  font=(FONT, 10), relief="flat",
                  padx=10, pady=6, cursor="hand2",
                  command=self._cancel).pack(side="left")

        self.bind("<Return>", lambda e: self._confirm())
        self.bind("<Escape>", lambda e: self._cancel())

    def _confirm(self):
        val = self._var.get().strip()
        if not val:
            return
        self.destroy()
        self.on_confirm(val)

    def _cancel(self):
        self.destroy()
        self.on_cancel()


class PointStep(tk.Toplevel):
    """클릭 좌표 설정 단계 — 전체화면 오버레이에서 클릭"""
    def __init__(self, master, step: dict,
                 step_num: int, total: int,
                 on_confirm: Callable, on_cancel: Callable):
        super().__init__(master)
        self.on_confirm = on_confirm
        self.on_cancel  = on_cancel

        self.overrideredirect(True)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")
        self.attributes("-alpha", 0.55)
        self.attributes("-topmost", True)
        self.configure(bg="#000000")
        self.focus_force()

        color = step["color"]

        canvas = tk.Canvas(self, bg="#000000", highlightthickness=0,
                           cursor="crosshair")
        canvas.place(relx=0, rely=0, relwidth=1, relheight=1)

        # 배경 어둡게
        canvas.create_rectangle(0, 0, sw, sh,
                                 fill="#000000", stipple="gray25", outline="")

        # 중앙 안내 패널
        pw, ph = 460, 120
        px = (sw - pw) // 2
        py = (sh - ph) // 2

        canvas.create_rectangle(px-2, py-2, px+pw+2, py+ph+2,
                                 fill=color, outline="")
        canvas.create_rectangle(px, py, px+pw, py+ph,
                                 fill=BG, outline="")

        canvas.create_text(sw//2, py+28,
                           text=f"STEP {step_num}/{total}  —  {step['label']}",
                           fill=TEXT, font=(FONT, 14, "bold"), anchor="center")
        canvas.create_text(sw//2, py+62,
                           text=step["description"].replace("\\n", "\n"),
                           fill=SUBTEXT, font=(FONT, 10),
                           anchor="center", justify="center")
        canvas.create_text(sw//2, py+98,
                           text="❌ Esc 취소",
                           fill=SUBTEXT, font=(FONT, 9), anchor="center")

        self._sw = sw
        self._sh = sh
        canvas.bind("<ButtonPress-1>", self._on_click)
        self.bind("<Escape>", lambda e: self._cancel())

    def _on_click(self, e):
        rx = e.x / self._sw
        ry = e.y / self._sh
        self.destroy()
        self.on_confirm({"rx": rx, "ry": ry})

    def _cancel(self):
        self.destroy()
        self.on_cancel()


class RegionStep(tk.Toplevel):
    """드래그로 영역 지정 단계"""
    def __init__(self, master, step: dict,
                 step_num: int, total: int,
                 on_confirm: Callable, on_cancel: Callable):
        super().__init__(master)
        self.on_confirm = on_confirm
        self.on_cancel  = on_cancel
        self._step      = step

        self.overrideredirect(True)
        self._sw = self.winfo_screenwidth()
        self._sh = self.winfo_screenheight()
        self.geometry(f"{self._sw}x{self._sh}+0+0")
        self.attributes("-alpha", 0.85)
        self.attributes("-topmost", True)
        self.configure(bg="#000000")
        self.focus_force()

        self.canvas = tk.Canvas(self, bg="#000000",
                                highlightthickness=0, cursor="crosshair")
        self.canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.canvas.create_rectangle(0, 0, self._sw, self._sh,
                                     fill="#000000", stipple="gray25", outline="")

        color = step["color"]
        self._color = color

        # 중앙 안내 패널
        self._draw_info(step, step_num, total, color)

        # 초기 프레임
        hr = step.get("hint_ratio", (0.1, 0.1, 0.9, 0.9))
        self.fx1 = int(self._sw * hr[0])
        self.fy1 = int(self._sh * hr[1])
        self.fx2 = int(self._sw * hr[2])
        self.fy2 = int(self._sh * hr[3])
        self._drag_mode = None
        self._drag_ox = self._drag_oy = 0
        self._redraw()

        self.canvas.bind("<ButtonPress-1>",   self._press)
        self.canvas.bind("<B1-Motion>",       self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Return>", lambda e: self._confirm())
        self.bind("<Escape>", lambda e: self._cancel())

    def _draw_info(self, step, step_num, total, color):
        pw, ph = 460, 110
        px = (self._sw - pw) // 2
        py = 20

        self.canvas.create_rectangle(px-2, py-2, px+pw+2, py+ph+2,
                                     fill=color, outline="", tags="info")
        self.canvas.create_rectangle(px, py, px+pw, py+ph,
                                     fill=BG, outline="", tags="info")
        self.canvas.create_rectangle(px+14, py+12, px+110, py+34,
                                     fill=color, outline="", tags="info")
        self.canvas.create_text(px+62, py+23,
                                text=f"STEP {step_num}/{total}",
                                fill=BG, font=(FONT, 10, "bold"),
                                anchor="center", tags="info")
        self.canvas.create_text(self._sw//2, py+54,
                                text=f"[ {step['label']} ] 영역 설정",
                                fill=TEXT, font=(FONT, 15, "bold"),
                                anchor="center", tags="info")
        self.canvas.create_text(self._sw//2, py+84,
                                text=step["description"].replace("\\n", "  ·  "),
                                fill=SUBTEXT, font=(FONT, 10),
                                anchor="center", tags="info")
        self.canvas.create_text(self._sw//2, self._sh-20,
                                text="Enter / 확인 버튼으로 확정    Esc 취소",
                                fill=SUBTEXT, font=(FONT, 9), anchor="center")

    def _redraw(self):
        self.canvas.delete("frame")
        color = self._color
        x1, y1, x2, y2 = self.fx1, self.fy1, self.fx2, self.fy2

        # 내부 반투명
        self.canvas.create_rectangle(x1, y1, x2, y2,
                                     fill="#1a6fad", stipple="gray12",
                                     outline="", tags="frame")
        # 테두리
        self.canvas.create_rectangle(x1, y1, x2, y2,
                                     fill="", outline=color,
                                     width=2, tags="frame")

        # 그리드
        grid = self._step.get("grid")
        if grid:
            cols, rows = grid
            cw = (x2-x1)/cols; rh = (y2-y1)/rows
            for c in range(1, cols):
                lx = x1+int(c*cw)
                self.canvas.create_line(lx, y1, lx, y2,
                                        fill=color, width=1, dash=(4,4), tags="frame")
            for r in range(1, rows):
                ly = y1+int(r*rh)
                self.canvas.create_line(x1, ly, x2, ly,
                                        fill=color, width=1, dash=(4,4), tags="frame")

        # 핸들
        hs = HANDLE_SIZE
        for hx, hy in [(x1,y1),(x2,y1),(x1,y2),(x2,y2)]:
            self.canvas.create_rectangle(hx-hs, hy-hs, hx+hs, hy+hs,
                                         fill=YELLOW, outline=BG,
                                         width=2, tags="frame")

        # 이동 핸들
        mx, my = (x1+x2)//2, (y1+y2)//2
        self.canvas.create_oval(mx-14, my-14, mx+14, my+14,
                                fill=color, outline=BG, width=2, tags="frame")
        self.canvas.create_text(mx, my, text="✥", fill="white",
                                font=("Arial", 12, "bold"), tags="frame")

        # 크기 표시
        self.canvas.create_text(x1+6, y1+6,
                                text=f"{x2-x1}×{y2-y1}",
                                fill=color, font=(FONT, 9),
                                anchor="nw", tags="frame")

        # 확인 버튼
        bw, bh = 200, 44
        bx = (x1+x2)//2
        by = y2+18
        if by+bh > self._sh-30:
            by = y1-bh-10
        self.canvas.create_rectangle(bx-bw//2, by, bx+bw//2, by+bh,
                                     fill=GREEN, outline="", tags="frame")
        self.canvas.create_text(bx, by+bh//2,
                                text="✅  이 영역으로 확정",
                                fill="white", font=(FONT, 11, "bold"),
                                tags="frame")
        self._btn = (bx-bw//2, by, bx+bw//2, by+bh)

    def _hit_handle(self, x, y):
        hs = HANDLE_SIZE+4
        for name, (hx, hy) in [("nw",(self.fx1,self.fy1)),("ne",(self.fx2,self.fy1)),
                                 ("sw",(self.fx1,self.fy2)),("se",(self.fx2,self.fy2))]:
            if abs(x-hx)<=hs and abs(y-hy)<=hs:
                return name
        return None

    def _press(self, e):
        bx1,by1,bx2,by2 = self._btn
        if bx1<=e.x<=bx2 and by1<=e.y<=by2:
            self._confirm(); return
        h = self._hit_handle(e.x, e.y)
        if h:
            self._drag_mode = ("resize", h)
        elif self.fx1<e.x<self.fx2 and self.fy1<e.y<self.fy2:
            self._drag_mode = ("move",)
        else:
            self._drag_mode = None
        self._drag_ox, self._drag_oy = e.x, e.y

    def _drag(self, e):
        if not self._drag_mode: return
        dx = e.x-self._drag_ox; dy = e.y-self._drag_oy
        self._drag_ox, self._drag_oy = e.x, e.y
        if self._drag_mode[0] == "move":
            self.fx1+=dx; self.fy1+=dy; self.fx2+=dx; self.fy2+=dy
            self.fx1=max(0,self.fx1); self.fy1=max(0,self.fy1)
            self.fx2=min(self._sw,self.fx2); self.fy2=min(self._sh,self.fy2)
        else:
            h = self._drag_mode[1]
            if "w" in h: self.fx1+=dx
            if "e" in h: self.fx2+=dx
            if "n" in h: self.fy1+=dy
            if "s" in h: self.fy2+=dy
            if self.fx2-self.fx1<MIN_SIZE: self.fx2=self.fx1+MIN_SIZE
            if self.fy2-self.fy1<MIN_SIZE: self.fy2=self.fy1+MIN_SIZE
        self._redraw()

    def _release(self, e):
        self._drag_mode = None

    def _confirm(self):
        result = {
            "x1": self.fx1/self._sw, "y1": self.fy1/self._sh,
            "x2": self.fx2/self._sw, "y2": self.fy2/self._sh,
        }
        self.destroy()
        self.on_confirm(result)

    def _cancel(self):
        self.destroy()
        self.on_cancel()


class BetweenScreen(tk.Toplevel):
    """단계 사이 안내 창 — 게임 화면 이동 후 준비됐으면 진행"""
    def __init__(self, master, step: dict,
                 step_num: int, total: int,
                 on_proceed: Callable, on_cancel: Callable):
        super().__init__(master)
        self.on_proceed = on_proceed
        self.on_cancel  = on_cancel

        self.title("")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = 460, 210
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        color = step["color"]
        tk.Frame(self, bg=color, height=4).pack(fill="x")

        bf = tk.Frame(self, bg=BG)
        bf.pack(pady=(14, 0))
        tk.Label(bf, text=f"  STEP {step_num}/{total}  ",
                 bg=color, fg=BG, font=(FONT, 10, "bold")).pack()

        tk.Label(self, text=f"다음: [ {step['label']} ]",
                 bg=BG, fg=TEXT, font=(FONT, 14, "bold")).pack(pady=(8, 4))
        tk.Label(self, text=step["description"],
                 bg=BG, fg=SUBTEXT, font=(FONT, 10), justify="center").pack()
        tk.Label(self,
                 text="게임 화면을 해당 화면으로 이동한 뒤\n아래 버튼을 눌러주세요",
                 bg=BG, fg=SUBTEXT, font=(FONT, 9), justify="center").pack(pady=(6,0))

        btnf = tk.Frame(self, bg=BG)
        btnf.pack(pady=12)
        tk.Button(btnf, text="✅  준비됐어요",
                  bg=color, fg=BG,
                  font=(FONT, 11, "bold"),
                  relief="flat", padx=14, pady=7,
                  cursor="hand2", command=self._proceed).pack(side="left", padx=6)
        tk.Button(btnf, text="❌  취소",
                  bg=CARD, fg=SUBTEXT,
                  font=(FONT, 10), relief="flat",
                  padx=10, pady=7, cursor="hand2",
                  command=self._cancel).pack(side="left")

    def _proceed(self):
        self.destroy()
        self.on_proceed()

    def _cancel(self):
        self.destroy()
        self.on_cancel()


class SetupWizard:
    """전체 설정 위자드 - 단계별 순서 관리 + 즉시 저장"""

    def __init__(self, master,
                 on_complete: Callable[[dict], None],
                 on_cancel: Callable):
        self.master      = master
        self.on_complete = on_complete
        self.on_cancel   = on_cancel
        self.results     = load_config()  # 기존 설정 로드
        self._steps      = SETUP_STEPS
        self._idx        = 0

    def start(self):
        self._next()

    def _next(self):
        if self._idx >= len(self._steps):
            self.on_complete(self.results)
            return

        step = self._steps[self._idx]
        total = len(self._steps)
        step_num = self._idx + 1

        # 첫 단계 제외, region/point 단계 전에 사이 안내창
        if self._idx > 0 and step["type"] in ("region", "point"):
            BetweenScreen(self.master, step, step_num, total,
                          on_proceed=lambda: self._open_step(step, step_num, total),
                          on_cancel=self.on_cancel)
        else:
            self._open_step(step, step_num, total)

    def _open_step(self, step, step_num, total):
        t = step["type"]
        if t == "text":
            existing = self.results.get(step["key"], "")
            TextStep(self.master, step, step_num, total,
                     on_confirm=self._confirm,
                     on_cancel=self.on_cancel,
                     existing_value=existing)
        elif t == "point":
            PointStep(self.master, step, step_num, total,
                      on_confirm=self._confirm,
                      on_cancel=self.on_cancel)
        elif t == "region":
            RegionStep(self.master, step, step_num, total,
                       on_confirm=self._confirm,
                       on_cancel=self.on_cancel)

    def _confirm(self, value):
        key = self._steps[self._idx]["key"]
        self.results[key] = value
        save_config(self.results)   # 즉시 저장
        self._idx += 1
        self.master.after(200, self._next)
