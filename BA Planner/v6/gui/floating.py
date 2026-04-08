"""
Floating overlay tied to the selected Blue Archive window.
"""

import threading
import time
import tkinter as tk
from typing import Callable

from core.capture import get_window_rect
from core.states import AppState

BG = "#0d1b2a"
CARD = "#152435"
BLUE = "#1a6fad"
LBLUE = "#4aa8e0"
YELLOW = "#f5c842"
GREEN = "#3dbf7a"
ORANGE = "#e8894a"
PURPLE = "#c97bec"
RED = "#FF4D4D"
TEXT = "#e8f4fd"
SUB = "#7ab3d4"
FONT = "Malgun Gothic"

FLOAT_RX = 0.018
FLOAT_RY = 0.45
CIRCLE_D = 60
EXPAND_W = 230
EXPAND_H = 300


class FloatingOverlay(tk.Toplevel):
    def __init__(
        self,
        master,
        on_scan_items: Callable,
        on_scan_equipment: Callable,
        on_scan_students: Callable,
        on_scan_all: Callable,
        on_stop: Callable,
        on_settings: Callable,
        on_view_students=None,
    ):
        super().__init__(master)

        self._cbs = {
            "items": on_scan_items,
            "equipment": on_scan_equipment,
            "students": on_scan_students,
            "all": on_scan_all,
            "stop": on_stop,
            "settings": on_settings,
            "recover": on_settings,
            "view_students": on_view_students or (lambda: None),
        }
        self._expanded = False
        self._scanning = False
        self._visible = False
        self._resources = {}
        self._log_lines: list[str] = []
        self._drag_x = self._drag_y = 0
        self._app_state = AppState.INIT

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(bg=BG)
        self.withdraw()

        self._draw()
        self._start_tracker()

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

        canvas = tk.Canvas(self, width=d, height=d, bg=BG, highlightthickness=0)
        canvas.pack()
        fill = RED if self._app_state == AppState.ERROR else BLUE
        canvas.create_oval(2, 2, d - 2, d - 2, fill=fill, outline=LBLUE, width=2)
        if self._scanning or self._app_state == AppState.STOPPING:
            canvas.create_oval(d - 14, 2, d - 2, 14, fill=YELLOW, outline="")
        canvas.create_text(
            d // 2,
            d // 2,
            text="BA",
            fill=TEXT,
            font=(FONT, 14, "bold"),
        )
        canvas.bind("<Button-1>", lambda _e: self._toggle())

    def _draw_expanded(self):
        self.geometry(f"{EXPAND_W}x{EXPAND_H}")

        frame = tk.Frame(
            self,
            bg=BG,
            highlightbackground=LBLUE,
            highlightthickness=2,
        )
        frame.pack(fill="both", expand=True)

        hdr = tk.Frame(frame, bg=BLUE)
        hdr.pack(fill="x")
        tk.Label(
            hdr,
            text="BA Analyzer",
            bg=BLUE,
            fg=TEXT,
            font=(FONT, 11, "bold"),
        ).pack(side="left", padx=10, pady=6)
        tk.Button(
            hdr,
            text="x",
            bg=BLUE,
            fg=TEXT,
            font=("Arial", 10),
            relief="flat",
            cursor="hand2",
            command=self._toggle,
        ).pack(side="right", padx=6)
        hdr.bind("<ButtonPress-1>", self._drag_start)
        hdr.bind("<B1-Motion>", self._drag_move)

        self._draw_status(frame)
        self._draw_resources(frame)
        self._draw_actions(frame)
        self._draw_log(frame)
        self._draw_footer(frame)

    def _draw_status(self, parent):
        labels = {
            AppState.INIT: "초기화 중",
            AppState.IDLE: "대상 창 선택 필요",
            AppState.WATCHING: "로비 감시 중",
            AppState.SCANNING: "스캔 실행 중",
            AppState.PAUSED: "일시정지",
            AppState.ERROR: "오류 상태",
            AppState.STOPPING: "정리 중",
        }
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=6, pady=(6, 2))
        tk.Label(
            row,
            text=f"상태: {labels.get(self._app_state, self._app_state.name)}",
            bg=CARD,
            fg=TEXT,
            font=(FONT, 9, "bold"),
        ).pack(anchor="w", padx=8, pady=4)

    def _draw_resources(self, parent):
        res = tk.Frame(parent, bg=CARD)
        res.pack(fill="x", padx=6, pady=(0, 2))
        pyrox = self._resources.get("청휘석") or "-"
        credit = self._resources.get("크레딧") or "-"
        tk.Label(
            res,
            text=f"청휘석 {pyrox}",
            bg=CARD,
            fg=YELLOW,
            font=(FONT, 10, "bold"),
        ).pack(side="left", padx=8, pady=4)
        tk.Label(
            res,
            text=f"크레딧 {credit}",
            bg=CARD,
            fg=TEXT,
            font=(FONT, 10, "bold"),
        ).pack(side="left", padx=4)

    def _draw_actions(self, parent):
        if self._app_state in (AppState.SCANNING, AppState.STOPPING) or self._scanning:
            self._action_button(parent, "스캔 중지", RED, TEXT, "stop")
            return

        if self._app_state == AppState.ERROR:
            self._action_button(parent, "복구 / 창 다시 선택", ORANGE, BG, "recover")
            self._action_button(parent, "학생 뷰어", YELLOW, BG, "view_students")
            return

        if self._app_state == AppState.IDLE:
            self._action_button(parent, "창 선택", ORANGE, BG, "settings")
            return

        if self._app_state == AppState.WATCHING:
            buttons = [
                ("아이템 스캔", LBLUE, "items"),
                ("장비 스캔", PURPLE, "equipment"),
                ("학생 스캔", GREEN, "students"),
                ("전체 스캔", ORANGE, "all"),
                ("학생 뷰어", YELLOW, "view_students"),
            ]
            for text, color, key in buttons:
                self._action_button(parent, text, color, BG, key)
            return

        self._action_button(parent, "창 선택", ORANGE, BG, "settings")

    def _action_button(self, parent, text: str, bg: str, fg: str, key: str):
        tk.Button(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            font=(FONT, 10, "bold"),
            relief="flat",
            pady=5,
            cursor="hand2",
            command=self._cbs[key],
        ).pack(fill="x", padx=6, pady=2)

    def _draw_log(self, parent):
        log_f = tk.Frame(parent, bg=CARD, height=56)
        log_f.pack(fill="x", padx=6, pady=(4, 0))
        log_f.pack_propagate(False)
        log_txt = "\n".join(self._log_lines[-3:]) if self._log_lines else "대기 중..."
        tk.Label(
            log_f,
            text=log_txt,
            bg=CARD,
            fg=SUB,
            font=(FONT, 8),
            justify="left",
            anchor="nw",
            wraplength=210,
        ).pack(padx=6, pady=4, fill="both")

    def _draw_footer(self, parent):
        tk.Button(
            parent,
            text="설정",
            bg=CARD,
            fg=SUB,
            font=(FONT, 9),
            relief="flat",
            cursor="hand2",
            command=self._cbs["settings"],
        ).pack(fill="x", padx=6, pady=(2, 6))

    def _reposition(self):
        rect = get_window_rect()
        if rect is None:
            return

        left, top, width, height = rect
        if self._expanded:
            ox = int(left + width * FLOAT_RX)
            oy = int(top + height * FLOAT_RY) - EXPAND_H // 2
            tw, th = EXPAND_W, EXPAND_H
        else:
            ox = int(left + width * FLOAT_RX)
            oy = int(top + height * FLOAT_RY) - CIRCLE_D // 2
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

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    def show(self):
        if not self._visible:
            self._visible = True
            self.deiconify()
            self._reposition()

    def hide(self):
        if self._visible:
            self._visible = False
            self.withdraw()

    def set_scanning(self, value: bool):
        self._scanning = value
        self.after(0, self._draw)

    def set_app_state(self, state: AppState):
        self._app_state = state
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
