"""
gui/floating.py — 원형 플로팅 오버레이
로비 감지 시 표시. 클릭하면 스캔 메뉴 펼침.
"""
import tkinter as tk
import threading
import time
from typing import Callable

from core.capture import get_window_rect

BG    = "#0d1b2a"
CARD  = "#152435"
BLUE  = "#1a6fad"
LBLUE = "#4aa8e0"
YELLOW= "#f5c842"
GREEN = "#3dbf7a"
ORANGE= "#e8894a"
PURPLE= "#c97bec"
RED = "#FF4D4D"
TEXT  = "#e8f4fd"
SUB   = "#7ab3d4"
FONT  = "Malgun Gothic"

FLOAT_RX  = 0.018
FLOAT_RY  = 0.45
CIRCLE_D  = 60
EXPAND_W  = 230
EXPAND_H  = 280


class FloatingOverlay(tk.Toplevel):
    def __init__(self, master,
                 on_scan_items:     Callable,
                 on_scan_equipment: Callable,
                 on_scan_students:  Callable,
                 on_scan_all:       Callable,
                 on_stop:           Callable,
                 on_settings:       Callable,
                 on_view_students=None):
        super().__init__(master)

        self._cbs = {
            "items":     on_scan_items,
            "equipment": on_scan_equipment,
            "students":  on_scan_students,
            "all":       on_scan_all,
            "stop":      on_stop,
            "settings":  on_settings,
            "view_students": on_view_students or (lambda: None),
        }
        self._expanded   = False
        self._scanning   = False
        self._visible    = False
        self._resources  = {}
        self._log_lines: list[str] = []
        self._drag_x = self._drag_y = 0

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(bg=BG)
        self.withdraw()

        self._draw()
        self._start_tracker()

    # ── 드로잉 ────────────────────────────────────────────
    def _draw(self):
        for w in self.winfo_children():
            w.destroy()

        if self._expanded:
            self._draw_expanded()
        else:
            self._draw_collapsed()

    def _draw_collapsed(self):
        d = CIRCLE_D
        self.geometry(f"{d}x{d}")

        c = tk.Canvas(self, width=d, height=d,
                      bg=BG, highlightthickness=0)
        c.pack()

        c.create_oval(2, 2, d-2, d-2,
                      fill=BLUE, outline=LBLUE, width=2)
        if self._scanning:
            c.create_oval(d-14, 2, d-2, 14, fill=YELLOW, outline="")
        c.create_text(d//2, d//2, text="BA",
                      fill=TEXT, font=(FONT, 14, "bold"))
        c.bind("<Button-1>", lambda e: self._toggle())

    def _draw_expanded(self):
        self.geometry(f"{EXPAND_W}x{EXPAND_H}")

        frame = tk.Frame(self, bg=BG,
                         highlightbackground=LBLUE,
                         highlightthickness=2)
        frame.pack(fill="both", expand=True)

        # 헤더
        hdr = tk.Frame(frame, bg=BLUE)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🎓 BA Analyzer",
                 bg=BLUE, fg=TEXT,
                 font=(FONT, 11, "bold")).pack(side="left", padx=10, pady=6)
        tk.Button(hdr, text="✕", bg=BLUE, fg=TEXT,
                  font=("Arial", 10), relief="flat", cursor="hand2",
                  command=self._toggle).pack(side="right", padx=6)
        hdr.bind("<ButtonPress-1>", self._drag_start)
        hdr.bind("<B1-Motion>",     self._drag_move)

        # 재화
        res = tk.Frame(frame, bg=CARD)
        res.pack(fill="x", padx=6, pady=(6,2))
        pyrox  = self._resources.get("청휘석") or "-"
        credit = self._resources.get("크레딧") or "-"
        tk.Label(res, text=f"💎 {pyrox}",
                 bg=CARD, fg=YELLOW,
                 font=(FONT, 10, "bold")).pack(side="left", padx=8, pady=4)
        tk.Label(res, text=f"💰 {credit}",
                 bg=CARD, fg=TEXT,
                 font=(FONT, 10, "bold")).pack(side="left", padx=4)

        # 스캔 중이면 정지 버튼, 아니면 스캔 버튼들
        if self._scanning:
            tk.Button(frame, text="⏹  스캔 중지",
                      bg=RED, fg=TEXT,
                      font=(FONT, 11, "bold"),
                      relief="flat", pady=10,
                      cursor="hand2",
                      command=self._cbs["stop"]
                      ).pack(fill="x", padx=6, pady=4)
        else:
            btns = [
                ("📦  아이템 스캔",    LBLUE,  "items"),
                ("🔧  장비 스캔",      PURPLE, "equipment"),
                ("👩  학생 스캔",      GREEN,  "students"),
                ("🔄  전체 스캔",      ORANGE, "all"),
                ("📋  학생 뷰어",      YELLOW, "view_students"),
            ]
            for label, color, key in btns:
                tk.Button(frame, text=label,
                          bg=color, fg=BG,
                          font=(FONT, 10, "bold"),
                          relief="flat", pady=5,
                          cursor="hand2",
                          command=self._cbs[key]
                          ).pack(fill="x", padx=6, pady=2)

        # 로그
        log_f = tk.Frame(frame, bg=CARD, height=46)
        log_f.pack(fill="x", padx=6, pady=(4,0))
        log_f.pack_propagate(False)
        log_txt = "\n".join(self._log_lines[-2:]) if self._log_lines else "대기 중..."
        tk.Label(log_f, text=log_txt,
                 bg=CARD, fg=SUB,
                 font=(FONT, 8), justify="left",
                 anchor="nw", wraplength=210).pack(padx=6, pady=4, fill="both")

        # 설정
        tk.Button(frame, text="⚙️  설정",
                  bg=CARD, fg=SUB,
                  font=(FONT, 9), relief="flat",
                  cursor="hand2",
                  command=self._cbs["settings"]
                  ).pack(fill="x", padx=6, pady=(2,6))

    # ── 위치 추적 ─────────────────────────────────────────
    def _reposition(self):
        rect = get_window_rect()
        if rect is None:
            return
        l, t, w, h = rect
        if self._expanded:
            ox = int(l + w * FLOAT_RX)
            oy = int(t + h * FLOAT_RY) - EXPAND_H // 2
            tw, th = EXPAND_W, EXPAND_H
        else:
            ox = int(l + w * FLOAT_RX)
            oy = int(t + h * FLOAT_RY) - CIRCLE_D // 2
            tw, th = CIRCLE_D, CIRCLE_D

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        ox = max(0, min(ox, sw - tw))
        oy = max(0, min(oy, sh - th))
        self.geometry(f"+{ox}+{oy}")

    def _start_tracker(self):
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
        self.geometry(f"+{e.x_root - self._drag_x}+{e.y_root - self._drag_y}")

    # ── 공개 API ──────────────────────────────────────────
    def show(self):
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._reposition()

    def hide(self):
        if self._visible:
            self._visible = False
            self.withdraw()

    def set_scanning(self, v: bool):
        self._scanning = v
        self.after(0, self._draw)

    def update_resources(self, res: dict):
        self._resources = res
        if self._expanded:
            self.after(0, self._draw)

    def add_log(self, msg: str):
        self._log_lines.append(msg)
        if len(self._log_lines) > 30:
            self._log_lines = self._log_lines[-30:]
        if self._expanded:
            self.after(0, self._draw)

    def _toggle(self):
        self._expanded = not self._expanded
        self._draw()
        self._reposition()