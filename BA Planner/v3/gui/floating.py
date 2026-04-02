"""
gui/floating.py
블루아카이브 창 위에 붙어 따라다니는 원형 플로팅 오버레이.
로비일 때만 표시. 클릭하면 스캔 메뉴 확장.
"""
import tkinter as tk
import threading
import time
from typing import Callable

from core.capture import get_window_rect

# ── 색상 ──────────────────────────────────────────────────
BG      = "#0d1b2a"
CARD    = "#152435"
BLUE    = "#1a6fad"
LBLUE   = "#4aa8e0"
YELLOW  = "#f5c842"
GREEN   = "#3dbf7a"
ORANGE  = "#e8894a"
PURPLE  = "#c97bec"
TEXT    = "#e8f4fd"
SUBTEXT = "#7ab3d4"
RED     = "#e85a5a"
FONT    = "Malgun Gothic"

# 오버레이 위치: 창 좌측 중앙 (비율)
FLOAT_RX = 0.015
FLOAT_RY = 0.45

CIRCLE_R  = 30   # 기본 원 반지름
EXPAND_W  = 220  # 확장 시 너비
EXPAND_H  = 260  # 확장 시 높이


class FloatingOverlay(tk.Toplevel):
    """
    항상 블루아카이브 창 위에 붙어있는 원형 오버레이.
    - 로비 감지 시 표시 / 아닐 때 숨김
    - 클릭 시 스캔 메뉴 펼침
    - 스캔 결과(재화) 실시간 업데이트
    """

    def __init__(self, master,
                 on_scan_items:     Callable,
                 on_scan_equipment: Callable,
                 on_scan_students:  Callable,
                 on_open_settings:  Callable):
        super().__init__(master)

        self._on_scan_items     = on_scan_items
        self._on_scan_equipment = on_scan_equipment
        self._on_scan_students  = on_scan_students
        self._on_settings       = on_open_settings

        self._expanded   = False
        self._scanning   = False
        self._visible    = False
        self._resources  = {"청휘석": None, "크레딧": None}
        self._log_lines  = []

        self._build_window()
        self._start_position_tracker()

    # ── 윈도우 기본 설정 ──────────────────────────────────
    def _build_window(self):
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(bg=BG)
        self.withdraw()  # 처음엔 숨김

        self._draw_collapsed()

    # ── 접힌 상태 ─────────────────────────────────────────
    def _draw_collapsed(self):
        for w in self.winfo_children():
            w.destroy()

        d = CIRCLE_R * 2
        self.geometry(f"{d}x{d}")

        canvas = tk.Canvas(self, width=d, height=d,
                           bg=BG, highlightthickness=0)
        canvas.pack()

        # 원 배경
        canvas.create_oval(2, 2, d-2, d-2,
                           fill=BLUE, outline=LBLUE, width=2)
        # BA 텍스트
        canvas.create_text(d//2, d//2, text="BA",
                           fill=TEXT, font=(FONT, 12, "bold"))

        # 스캔 중이면 애니메이션 점
        if self._scanning:
            canvas.create_oval(d-12, 2, d-2, 12,
                               fill=YELLOW, outline="")

        canvas.bind("<Button-1>", lambda e: self._toggle())
        self._canvas = canvas

    # ── 펼쳐진 상태 ───────────────────────────────────────
    def _draw_expanded(self):
        for w in self.winfo_children():
            w.destroy()

        self.geometry(f"{EXPAND_W}x{EXPAND_H}")

        # 메인 프레임
        frame = tk.Frame(self, bg=BG,
                         highlightbackground=LBLUE,
                         highlightthickness=2)
        frame.pack(fill="both", expand=True)

        # ── 헤더 ──
        hdr = tk.Frame(frame, bg=BLUE)
        hdr.pack(fill="x")

        tk.Label(hdr, text="🎓 BA Analyzer",
                 bg=BLUE, fg=TEXT,
                 font=(FONT, 11, "bold")).pack(side="left", padx=10, pady=6)

        tk.Button(hdr, text="✕",
                  bg=BLUE, fg=TEXT,
                  font=("Arial", 10), relief="flat",
                  cursor="hand2",
                  command=self._toggle).pack(side="right", padx=6)

        # ── 재화 표시 ──
        res_frame = tk.Frame(frame, bg=CARD)
        res_frame.pack(fill="x", padx=6, pady=(6, 0))

        pyrox = self._resources.get("청휘석") or "-"
        credit = self._resources.get("크레딧") or "-"

        tk.Label(res_frame, text=f"💎 {pyrox}",
                 bg=CARD, fg=YELLOW,
                 font=(FONT, 10, "bold")).pack(side="left", padx=8, pady=4)
        tk.Label(res_frame, text=f"💰 {credit}",
                 bg=CARD, fg=TEXT,
                 font=(FONT, 10, "bold")).pack(side="left", padx=8)

        # ── 스캔 버튼들 ──
        btn_cfg = [
            ("📦  아이템 스캔",  LBLUE,  self._on_scan_items),
            ("🔧  장비 스캔",    PURPLE, self._on_scan_equipment),
            ("👩  학생 스캔",    GREEN,  self._on_scan_students),
        ]

        for label, color, cmd in btn_cfg:
            state = "disabled" if self._scanning else "normal"
            tk.Button(frame, text=label,
                      bg=color if not self._scanning else CARD,
                      fg=BG if not self._scanning else SUBTEXT,
                      font=(FONT, 10, "bold"),
                      relief="flat", pady=5,
                      cursor="hand2" if not self._scanning else "arrow",
                      state=state,
                      command=cmd).pack(fill="x", padx=6, pady=2)

        # ── 로그 ──
        log_frame = tk.Frame(frame, bg=CARD, height=50)
        log_frame.pack(fill="x", padx=6, pady=(4, 0))
        log_frame.pack_propagate(False)

        log_text = "\n".join(self._log_lines[-2:]) if self._log_lines else "대기 중..."
        tk.Label(log_frame, text=log_text,
                 bg=CARD, fg=SUBTEXT,
                 font=(FONT, 8), justify="left",
                 anchor="nw", wraplength=200).pack(padx=6, pady=4, fill="both")

        # ── 설정 버튼 ──
        tk.Button(frame, text="⚙️  설정",
                  bg=CARD, fg=SUBTEXT,
                  font=(FONT, 9), relief="flat",
                  cursor="hand2",
                  command=self._on_settings).pack(fill="x", padx=6, pady=(2, 6))

        # 드래그 이동
        frame.bind("<ButtonPress-1>",   self._drag_start)
        frame.bind("<B1-Motion>",       self._drag_move)
        hdr.bind("<ButtonPress-1>",     self._drag_start)
        hdr.bind("<B1-Motion>",         self._drag_move)

    def _toggle(self):
        self._expanded = not self._expanded
        if self._expanded:
            self._draw_expanded()
        else:
            self._draw_collapsed()
        self._reposition()

    # ── 위치 관리 ─────────────────────────────────────────
    def _reposition(self):
        rect = get_window_rect()
        if rect is None:
            return
        l, t, w, h = rect

        if self._expanded:
            ox = int(l + w * FLOAT_RX)
            oy = int(t + h * FLOAT_RY) - EXPAND_H // 2
        else:
            ox = int(l + w * FLOAT_RX)
            oy = int(t + h * FLOAT_RY) - CIRCLE_R

        # 화면 밖 이탈 방지
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        target_w = EXPAND_W if self._expanded else CIRCLE_R * 2
        target_h = EXPAND_H if self._expanded else CIRCLE_R * 2
        ox = max(0, min(ox, sw - target_w))
        oy = max(0, min(oy, sh - target_h))

        self.geometry(f"+{ox}+{oy}")

    def _start_position_tracker(self):
        """창 위치 추적 스레드"""
        def loop():
            while True:
                try:
                    if self._visible:
                        self.after(0, self._reposition)
                except Exception:
                    pass
                time.sleep(0.5)

        threading.Thread(target=loop, daemon=True).start()

    # ── 드래그 ────────────────────────────────────────────
    def _drag_start(self, e):
        self._drag_x = e.x_root - self.winfo_x()
        self._drag_y = e.y_root - self.winfo_y()

    def _drag_move(self, e):
        x = e.x_root - self._drag_x
        y = e.y_root - self._drag_y
        self.geometry(f"+{x}+{y}")

    # ── 표시/숨김 ─────────────────────────────────────────
    def show(self):
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._reposition()

    def hide(self):
        if self._visible:
            self._visible = False
            self.withdraw()

    # ── 외부에서 호출 ─────────────────────────────────────
    def set_scanning(self, scanning: bool):
        self._scanning = scanning
        if self._expanded:
            self.after(0, self._draw_expanded)
        else:
            self.after(0, self._draw_collapsed)

    def update_resources(self, resources: dict):
        self._resources = resources
        if self._expanded:
            self.after(0, self._draw_expanded)

    def add_log(self, msg: str):
        self._log_lines.append(msg)
        if len(self._log_lines) > 20:
            self._log_lines = self._log_lines[-20:]
        if self._expanded:
            self.after(0, self._draw_expanded)
