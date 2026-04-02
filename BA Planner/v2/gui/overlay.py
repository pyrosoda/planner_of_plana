"""
overlay.py
게임 화면 위에 반투명 오버레이를 띄우고,
와이어프레임 틀을 드래그/리사이즈해서 UI 영역을 지정하는 모듈
"""

import tkinter as tk
from tkinter import font as tkfont
from dataclasses import dataclass
from typing import Callable

# ── 색상 ──────────────────────────────────────────────────
OVERLAY_BG      = "#000000"   # 오버레이 배경 (투명도로 조절)
FRAME_COLOR     = "#4aa8e0"   # 와이어프레임 테두리
FRAME_FILL      = "#1a6fad"   # 와이어프레임 내부
HANDLE_COLOR    = "#f5c842"   # 리사이즈 핸들
TEXT_BG         = "#0d1b2a"
TEXT_FG         = "#e8f4fd"
CONFIRM_COLOR   = "#3dbf7a"
GRID_LINE_COLOR = "#4aa8e033"

HANDLE_SIZE = 10
MIN_SIZE    = 60


@dataclass
class RegionResult:
    """영역 선택 결과 (비율 좌표)"""
    x1: float
    y1: float
    x2: float
    y2: float
    screen_w: int
    screen_h: int

    def to_dict(self):
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}

    def pixel_rect(self, w, h):
        return (int(w * self.x1), int(h * self.y1),
                int(w * self.x2), int(h * self.y2))


REGION_CONFIGS = {
    "resources": {
        "label":       "상단 재화 바",
        "description": "청휘석 · 크레딧이 표시된\n상단 영역을 틀에 맞춰주세요",
        "grid":        None,
        "hint_ratio":  (0.55, 0.00, 0.90, 0.07),
        "color":       "#f5c842",
    },
    "item_grid": {
        "label":       "아이템 그리드",
        "description": "아이템 화면의 슬롯 격자 전체를\n틀에 맞춰주세요",
        "grid":        (5, 4),
        "hint_ratio":  (0.53, 0.20, 0.99, 0.98),
        "color":       "#4aa8e0",
    },
    "item_detail": {
        "label":       "아이템 상세 패널",
        "description": "아이템 선택 시 나타나는\n이름·수량 패널에 틀을 맞춰주세요",
        "grid":        None,
        "hint_ratio":  (0.02, 0.75, 0.50, 0.90),
        "color":       "#e8894a",
    },
    "equipment_grid": {
        "label":       "장비 그리드",
        "description": "장비 화면의 슬롯 격자 전체를\n틀에 맞춰주세요",
        "grid":        (5, 4),
        "hint_ratio":  (0.53, 0.20, 0.99, 0.98),
        "color":       "#c97bec",
    },
    "equipment_detail": {
        "label":       "장비 상세 패널",
        "description": "장비 선택 시 나타나는\n이름·수량 패널에 틀을 맞춰주세요",
        "grid":        None,
        "hint_ratio":  (0.02, 0.75, 0.50, 0.90),
        "color":       "#b06be0",
    },
    "student_basic": {
        "label":       "학생 기본 정보",
        "description": "이름 · 인연 수치 · 레벨이 표시된\n왼쪽 하단 영역에 틀을 맞춰주세요",
        "grid":        None,
        "hint_ratio":  (0.02, 0.76, 0.35, 0.90),
        "color":       "#3dbf7a",
    },
    "student_stats": {
        "label":       "학생 능력치/스킬/장비",
        "description": "능력치 · 스킬 레벨 · 무기 레벨 · 장비 레벨이\n표시된 오른쪽 패널에 틀을 맞춰주세요",
        "grid":        None,
        "hint_ratio":  (0.52, 0.13, 0.99, 0.98),
        "color":       "#5bc2e7",
    },
}


class RegionOverlay(tk.Toplevel):
    """
    단일 영역 선택 오버레이.
    전체화면 반투명 창 위에 드래그 가능한 와이어프레임 틀을 표시.
    """

    def __init__(self, master, region_key: str,
                 on_confirm: Callable[[RegionResult], None],
                 on_cancel: Callable[[], None]):
        super().__init__(master)
        self.region_key = region_key
        self.config_data = REGION_CONFIGS[region_key]
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel

        self._setup_window()
        self._draw_ui()
        self._init_frame()
        self._bind_events()

    # ── 윈도우 설정 ────────────────────────────────────────
    def _setup_window(self):
        # sw/sh 먼저 계산
        self.sw = self.winfo_screenwidth()
        self.sh = self.winfo_screenheight()
        # Windows: overrideredirect + fullscreen 충돌 방지
        # geometry로 직접 전체화면 크기 지정
        self.overrideredirect(True)
        self.geometry(f"{self.sw}x{self.sh}+0+0")
        self.attributes("-alpha", 0.85)
        self.attributes("-topmost", True)
        self.configure(bg=OVERLAY_BG)
        self.lift()
        self.focus_force()

    def _draw_ui(self):
        self.canvas = tk.Canvas(
            self, bg=OVERLAY_BG, highlightthickness=0,
            cursor="crosshair"
        )
        self.canvas.place(relx=0, rely=0, relwidth=1, relheight=1)

        # 어두운 배경 오버레이
        self.canvas.create_rectangle(
            0, 0, self.sw, self.sh,
            fill="#000000", stipple="gray25", outline=""
        )

        cfg = self.config_data
        color = cfg["color"]

        # 단계 표시
        keys = list(REGION_CONFIGS.keys())
        step = keys.index(self.region_key) + 1
        total = len(keys)

        # ── 중앙 플로팅 안내 패널 ──
        pw, ph = 480, 110
        px = (self.sw - pw) // 2
        py = (self.sh - ph) // 2

        # 패널 배경 (둥근 사각형 효과)
        self.canvas.create_rectangle(
            px - 2, py - 2, px + pw + 2, py + ph + 2,
            fill=color, outline="", tags="info_panel"
        )
        self.canvas.create_rectangle(
            px, py, px + pw, py + ph,
            fill="#0d1b2a", outline="", tags="info_panel"
        )

        # STEP 배지
        self.canvas.create_rectangle(
            px + 16, py + 14, px + 110, py + 38,
            fill=color, outline="", tags="info_panel"
        )
        self.canvas.create_text(
            px + 63, py + 26,
            text=f"STEP  {step} / {total}",
            fill="#0d1b2a",
            font=("Malgun Gothic", 11, "bold"),
            anchor="center", tags="info_panel"
        )

        # 제목
        self.canvas.create_text(
            px + pw // 2, py + 56,
            text=f"[ {cfg['label']} ] 영역 설정",
            fill="#e8f4fd",
            font=("Malgun Gothic", 16, "bold"),
            anchor="center", tags="info_panel"
        )

        # 설명
        self.canvas.create_text(
            px + pw // 2, py + 88,
            text=cfg["description"].replace("\n", "  ·  "),
            fill="#7ab3d4",
            font=("Malgun Gothic", 10),
            anchor="center", tags="info_panel"
        )

        # 하단 단축키 힌트 (화면 하단 고정)
        self.canvas.create_text(
            self.sw // 2, self.sh - 24,
            text="✅ Enter 또는 확인 버튼으로 확정    ❌ Esc로 취소",
            fill="#7ab3d4",
            font=("Malgun Gothic", 10),
            anchor="center"
        )

    def _init_frame(self):
        """초기 와이어프레임 위치 (hint_ratio 기반)"""
        x1r, y1r, x2r, y2r = self.config_data["hint_ratio"]
        self.fx1 = int(self.sw * x1r)
        self.fy1 = int(self.sh * y1r)
        self.fx2 = int(self.sw * x2r)
        self.fy2 = int(self.sh * y2r)
        self._ensure_min_size()
        self._redraw_frame()

    # ── 프레임 드로잉 ──────────────────────────────────────
    def _redraw_frame(self):
        self.canvas.delete("frame")
        color = self.config_data["color"]
        x1, y1, x2, y2 = self.fx1, self.fy1, self.fx2, self.fy2

        # 내부 반투명 채우기
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            fill=FRAME_FILL, stipple="gray12",
            outline="", tags="frame"
        )

        # 테두리
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            fill="", outline=color,
            width=2, tags="frame"
        )

        # 그리드 표시 (아이템 그리드만)
        grid = self.config_data.get("grid")
        if grid:
            cols, rows = grid
            cw = (x2 - x1) / cols
            rh = (y2 - y1) / rows
            for c in range(1, cols):
                lx = x1 + int(c * cw)
                self.canvas.create_line(
                    lx, y1, lx, y2,
                    fill=color, width=1,
                    dash=(4, 4), tags="frame"
                )
            for r in range(1, rows):
                ly = y1 + int(r * rh)
                self.canvas.create_line(
                    x1, ly, x2, ly,
                    fill=color, width=1,
                    dash=(4, 4), tags="frame"
                )
            # 슬롯 번호
            for r in range(rows):
                for c in range(cols):
                    cx = x1 + int((c + 0.5) * cw)
                    cy = y1 + int((r + 0.5) * rh)
                    self.canvas.create_text(
                        cx, cy,
                        text=f"{r * cols + c + 1}",
                        fill=color,
                        font=("Malgun Gothic", 9),
                        tags="frame"
                    )

        # 모서리 핸들 (리사이즈)
        hs = HANDLE_SIZE
        for hx, hy in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
            self.canvas.create_rectangle(
                hx - hs, hy - hs, hx + hs, hy + hs,
                fill=HANDLE_COLOR, outline="#0d1b2a",
                width=2, tags="frame"
            )

        # 중앙 이동 핸들
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        self.canvas.create_oval(
            mx - 14, my - 14, mx + 14, my + 14,
            fill=color, outline="#0d1b2a",
            width=2, tags="frame"
        )
        self.canvas.create_text(
            mx, my, text="✥",
            fill="white",
            font=("Arial", 12, "bold"),
            tags="frame"
        )

        # 크기 표시
        pw = x2 - x1
        ph = y2 - y1
        self.canvas.create_text(
            x1 + 6, y1 + 6,
            text=f"{pw}×{ph}",
            fill=color,
            font=("Malgun Gothic", 9),
            anchor="nw", tags="frame"
        )

        # 확인 버튼
        btn_w, btn_h = 200, 44
        bx = (x1 + x2) // 2
        by = y2 + 20
        if by + btn_h > self.sh - 50:
            by = y1 - btn_h - 10

        self.canvas.create_rectangle(
            bx - btn_w // 2, by,
            bx + btn_w // 2, by + btn_h,
            fill=CONFIRM_COLOR, outline="",
            tags="frame"
        )
        self.canvas.create_text(
            bx, by + btn_h // 2,
            text="✅  이 영역으로 확정",
            fill="white",
            font=("Malgun Gothic", 11, "bold"),
            tags="frame"
        )
        self._confirm_btn_rect = (
            bx - btn_w // 2, by,
            bx + btn_w // 2, by + btn_h
        )

    # ── 이벤트 바인딩 ──────────────────────────────────────
    def _bind_events(self):
        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda e: self._confirm())
        self.bind("<Escape>", lambda e: self._cancel())

        self._drag_mode = None
        self._drag_ox = 0
        self._drag_oy = 0

    def _hit_handle(self, x, y):
        hs = HANDLE_SIZE + 4
        corners = {
            "nw": (self.fx1, self.fy1),
            "ne": (self.fx2, self.fy1),
            "sw": (self.fx1, self.fy2),
            "se": (self.fx2, self.fy2),
        }
        for name, (hx, hy) in corners.items():
            if abs(x - hx) <= hs and abs(y - hy) <= hs:
                return name
        return None

    def _hit_center(self, x, y):
        mx = (self.fx1 + self.fx2) // 2
        my = (self.fy1 + self.fy2) // 2
        return abs(x - mx) <= 20 and abs(y - my) <= 20

    def _hit_interior(self, x, y):
        return self.fx1 < x < self.fx2 and self.fy1 < y < self.fy2

    def _hit_confirm_btn(self, x, y):
        if not hasattr(self, "_confirm_btn_rect"):
            return False
        bx1, by1, bx2, by2 = self._confirm_btn_rect
        return bx1 <= x <= bx2 and by1 <= y <= by2

    def _on_press(self, e):
        if self._hit_confirm_btn(e.x, e.y):
            self._confirm()
            return

        handle = self._hit_handle(e.x, e.y)
        if handle:
            self._drag_mode = ("resize", handle)
        elif self._hit_center(e.x, e.y) or self._hit_interior(e.x, e.y):
            self._drag_mode = ("move",)
        else:
            self._drag_mode = None

        self._drag_ox = e.x
        self._drag_oy = e.y

    def _on_drag(self, e):
        if not self._drag_mode:
            return
        dx = e.x - self._drag_ox
        dy = e.y - self._drag_oy
        self._drag_ox = e.x
        self._drag_oy = e.y

        mode = self._drag_mode[0]
        if mode == "move":
            self.fx1 += dx; self.fy1 += dy
            self.fx2 += dx; self.fy2 += dy
            # 화면 밖 이탈 방지 (상단 제한 없음)
            if self.fx1 < 0:   self.fx2 -= self.fx1;   self.fx1 = 0
            if self.fy1 < 0:   self.fy2 -= self.fy1;   self.fy1 = 0
            if self.fx2 > self.sw: self.fx1 -= self.fx2-self.sw; self.fx2 = self.sw
            if self.fy2 > self.sh: self.fy1 -= self.fy2-self.sh; self.fy2 = self.sh

        elif mode == "resize":
            handle = self._drag_mode[1]
            if "w" in handle: self.fx1 += dx
            if "e" in handle: self.fx2 += dx
            if "n" in handle: self.fy1 += dy
            if "s" in handle: self.fy2 += dy
            self._ensure_min_size()

        self._redraw_frame()

    def _on_release(self, e):
        self._drag_mode = None

    def _ensure_min_size(self):
        if self.fx2 - self.fx1 < MIN_SIZE:
            self.fx2 = self.fx1 + MIN_SIZE
        if self.fy2 - self.fy1 < MIN_SIZE:
            self.fy2 = self.fy1 + MIN_SIZE

    # ── 확정/취소 ──────────────────────────────────────────
    def _confirm(self):
        result = RegionResult(
            x1=self.fx1 / self.sw,
            y1=self.fy1 / self.sh,
            x2=self.fx2 / self.sw,
            y2=self.fy2 / self.sh,
            screen_w=self.sw,
            screen_h=self.sh,
        )
        self.destroy()
        self.on_confirm(result)

    def _cancel(self):
        self.destroy()
        self.on_cancel()


class SetupWizard:
    """
    4개 영역을 순서대로 설정하는 위자드.
    각 단계 완료 시 즉시 config.json에 저장.
    단계 사이에 사용자가 게임 화면을 이동할 수 있도록
    "다음 단계로" 중간 안내 창을 표시.
    """

    def __init__(self, master,
                 on_complete: Callable[[dict], None],
                 on_cancel: Callable[[], None]):
        self.master = master
        self.on_complete = on_complete
        self.on_cancel = on_cancel
        self.results = {}
        self._keys = list(REGION_CONFIGS.keys())
        self._idx = 0

    def start(self):
        self._next()

    def _next(self):
        if self._idx >= len(self._keys):
            self.on_complete(self.results)
            return

        key = self._keys[self._idx]
        # 두 번째 단계부터는 중간 안내 창 표시
        if self._idx > 0:
            self._show_between_screen(key)
        else:
            self._open_overlay(key)

    def _show_between_screen(self, key: str):
        """
        단계 사이 안내 창:
        사용자가 게임 화면을 원하는 곳으로 이동한 뒤
        '준비됐어요' 버튼을 눌러 다음 오버레이 진입
        """
        cfg = REGION_CONFIGS[key]
        keys = self._keys
        step = keys.index(key) + 1
        total = len(keys)

        win = tk.Toplevel(self.master)
        win.title("")
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.95)
        win.configure(bg="#0d1b2a")

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        ww, wh = 460, 220
        wx = (sw - ww) // 2
        wy = (sh - wh) // 2
        win.geometry(f"{ww}x{wh}+{wx}+{wy}")

        color = cfg["color"]

        # 상단 컬러 바
        top_bar = tk.Frame(win, bg=color, height=4)
        top_bar.pack(fill="x")

        # STEP 배지
        badge_frame = tk.Frame(win, bg="#0d1b2a")
        badge_frame.pack(pady=(16, 0))
        tk.Label(badge_frame,
                 text=f"  STEP {step} / {total}  ",
                 bg=color, fg="#0d1b2a",
                 font=("Malgun Gothic", 11, "bold")).pack()

        # 다음 영역 안내
        tk.Label(win,
                 text=f"다음: [ {cfg['label']} ]",
                 bg="#0d1b2a", fg="#e8f4fd",
                 font=("Malgun Gothic", 15, "bold")).pack(pady=(10, 4))

        tk.Label(win,
                 text=cfg["description"].replace("\\n", "\n"),
                 bg="#0d1b2a", fg="#7ab3d4",
                 font=("Malgun Gothic", 10),
                 justify="center").pack()

        tk.Label(win,
                 text="게임 화면을 해당 화면으로 이동한 뒤 아래 버튼을 눌러줘",
                 bg="#0d1b2a", fg="#7ab3d4",
                 font=("Malgun Gothic", 9)).pack(pady=(8, 0))

        def proceed():
            win.destroy()
            self.master.after(150, lambda: self._open_overlay(key))

        def cancel():
            win.destroy()
            self.on_cancel()

        btn_frame = tk.Frame(win, bg="#0d1b2a")
        btn_frame.pack(pady=12)

        tk.Button(btn_frame,
                  text="✅  준비됐어요, 영역 설정 시작",
                  bg=color, fg="#0d1b2a",
                  font=("Malgun Gothic", 11, "bold"),
                  relief="flat", padx=16, pady=8,
                  cursor="hand2",
                  command=proceed).pack(side="left", padx=6)

        tk.Button(btn_frame,
                  text="❌  취소",
                  bg="#1a2e40", fg="#7ab3d4",
                  font=("Malgun Gothic", 10),
                  relief="flat", padx=10, pady=8,
                  cursor="hand2",
                  command=cancel).pack(side="left")

    def _open_overlay(self, key: str):
        RegionOverlay(
            self.master, key,
            on_confirm=self._on_confirm,
            on_cancel=self._on_cancel,
        )

    def _on_confirm(self, result: RegionResult):
        from core.config import save_config as _save
        key = self._keys[self._idx]
        self.results[key] = result
        # 즉시 저장 (단계별)
        _save(self.results)
        self._idx += 1
        self.master.after(200, self._next)

    def _on_cancel(self):
        self.on_cancel()