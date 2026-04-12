"""
Floating overlay tied to the selected Blue Archive window.
"""

import ctypes
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Callable

from core.capture import get_window_rect
from core.states import AppState
from gui.ui_scale import get_ui_scale, scale_font, scale_px

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
EXPAND_H = 380
SCAN_CARD_W = 360
SCAN_CARD_H = 150

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

_u32 = ctypes.windll.user32
_get_window_long_ptr = getattr(_u32, "GetWindowLongPtrW", _u32.GetWindowLongW)
_set_window_long_ptr = getattr(_u32, "SetWindowLongPtrW", _u32.SetWindowLongW)


def _set_clickthrough(window: tk.Toplevel, enabled: bool) -> None:
    try:
        hwnd = window.winfo_id()
        exstyle = _get_window_long_ptr(hwnd, GWL_EXSTYLE)
        if enabled:
            exstyle |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            exstyle &= ~WS_EX_TRANSPARENT
            exstyle |= WS_EX_LAYERED
        _set_window_long_ptr(hwnd, GWL_EXSTYLE, exstyle)
        _u32.SetWindowPos(
            hwnd,
            0,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
    except Exception:
        pass


class FloatingOverlay(tk.Toplevel):
    def __init__(
        self,
        master,
        on_scan_items: Callable,
        on_scan_equipment: Callable,
        on_scan_students: Callable,
        on_scan_current_student: Callable,
        on_scan_all: Callable,
        on_stop: Callable,
        on_input_test: Callable,
        on_settings: Callable,
        on_view_students=None,
    ):
        super().__init__(master)
        self._scan_backdrop = tk.Toplevel(master)

        self._cbs = {
            "items": on_scan_items,
            "equipment": on_scan_equipment,
            "students": on_scan_students,
            "current_student": on_scan_current_student,
            "all": on_scan_all,
            "stop": on_stop,
            "input_test": on_input_test,
            "settings": on_settings,
            "recover": on_settings,
            "view_students": on_view_students or (lambda: None),
        }
        self._expanded = False
        self._visible = False
        self._resources = {}
        self._log_lines: list[str] = []
        self._drag_x = self._drag_y = 0
        self._app_state = AppState.INIT
        self._in_lobby = True
        self._stop_event = threading.Event()
        self._status_label: tk.Label | None = None
        self._pyrox_label: tk.Label | None = None
        self._credit_label: tk.Label | None = None
        self._log_label: tk.Label | None = None
        self._actions_frame: tk.Frame | None = None
        self._scan_title_label: tk.Label | None = None
        self._scan_message_label: tk.Label | None = None
        self._scan_progress_label: tk.Label | None = None
        self._scan_progress: ttk.Progressbar | None = None
        self._scan_progress_current: int | None = None
        self._scan_progress_total: int | None = None
        self._scan_progress_note = ""
        self._ui_scale = get_ui_scale(self, base_width=1600, base_height=1080)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.93)
        self.configure(bg=BG)
        self.withdraw()

        self._scan_backdrop.overrideredirect(True)
        self._scan_backdrop.attributes("-topmost", True)
        self._scan_backdrop.attributes("-alpha", 0.22)
        self._scan_backdrop.configure(bg="#08131d")
        self._scan_backdrop.withdraw()
        self._init_progress_style()

        self._draw()
        self._start_tracker()

    def _init_progress_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Scan.Horizontal.TProgressbar",
            troughcolor="#10202d",
            bordercolor="#10202d",
            background=LBLUE,
            lightcolor=LBLUE,
            darkcolor=BLUE,
            thickness=scale_px(12, self._ui_scale),
        )

    def _draw(self):
        for w in self.winfo_children():
            w.destroy()
        self._status_label = None
        self._pyrox_label = None
        self._credit_label = None
        self._log_label = None
        self._actions_frame = None
        self._scan_title_label = None
        self._scan_message_label = None
        self._scan_progress_label = None

        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            self._draw_scan_overlay()
        elif self._expanded:
            self._draw_expanded()
        else:
            self._draw_collapsed()

    def _draw_scan_overlay(self):
        self.geometry(
            f"{scale_px(SCAN_CARD_W, self._ui_scale)}x"
            f"{scale_px(SCAN_CARD_H, self._ui_scale)}"
        )

        root = tk.Frame(self, bg="#08131d")
        root.pack(fill="both", expand=True)

        card = tk.Frame(
            root,
            bg=CARD,
            highlightbackground=LBLUE,
            highlightthickness=2,
        )
        card.pack(fill="both", expand=True)

        self._scan_title_label = tk.Label(
            card,
            text="학생 스캔 진행 중",
            bg=CARD,
            fg=TEXT,
            font=scale_font((FONT, 14, "bold"), self._ui_scale),
        )
        self._scan_title_label.pack(pady=(scale_px(18, self._ui_scale), scale_px(10, self._ui_scale)))

        self._scan_progress = ttk.Progressbar(
            card,
            mode="indeterminate",
            style="Scan.Horizontal.TProgressbar",
        )
        self._scan_progress.pack(fill="x", padx=scale_px(24, self._ui_scale))

        self._scan_progress_label = tk.Label(
            card,
            text="진행률 계산 중...",
            bg=CARD,
            fg=TEXT,
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
        )
        self._scan_progress_label.pack(pady=(scale_px(8, self._ui_scale), 0))

        self._scan_message_label = tk.Label(
            card,
            text="스캔을 준비하고 있습니다...",
            bg=CARD,
            fg=SUB,
            font=scale_font((FONT, 10), self._ui_scale),
            justify="center",
            wraplength=scale_px(SCAN_CARD_W - 48, self._ui_scale),
        )
        self._scan_message_label.pack(
            padx=scale_px(24, self._ui_scale),
            pady=(scale_px(12, self._ui_scale), scale_px(12, self._ui_scale)),
        )

        tk.Button(
            card,
            text="중지",
            bg=RED,
            fg=TEXT,
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
            relief="flat",
            cursor="hand2",
            command=self._cbs["stop"],
        ).pack(ipadx=scale_px(18, self._ui_scale), ipady=scale_px(3, self._ui_scale))

        self._refresh_dynamic_content()

    def _draw_collapsed(self):
        d = scale_px(CIRCLE_D, self._ui_scale)
        self.geometry(f"{d}x{d}")

        canvas = tk.Canvas(self, width=d, height=d, bg=BG, highlightthickness=0)
        canvas.pack()
        fill = RED if self._app_state == AppState.ERROR else BLUE
        canvas.create_oval(2, 2, d - 2, d - 2, fill=fill, outline=LBLUE, width=2)
        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            canvas.create_oval(d - 14, 2, d - 2, 14, fill=YELLOW, outline="")
        canvas.create_text(
            d // 2,
            d // 2,
            text="BA",
            fill=TEXT,
            font=scale_font((FONT, 14, "bold"), self._ui_scale),
        )
        canvas.bind("<Button-1>", lambda _e: self._toggle())

    def _draw_expanded(self):
        self.geometry(f"{scale_px(EXPAND_W, self._ui_scale)}x{scale_px(EXPAND_H, self._ui_scale)}")

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
            font=scale_font((FONT, 11, "bold"), self._ui_scale),
        ).pack(side="left", padx=scale_px(10, self._ui_scale), pady=scale_px(6, self._ui_scale))
        tk.Button(
            hdr,
            text="x",
            bg=BLUE,
            fg=TEXT,
            font=scale_font(("Arial", 10), self._ui_scale),
            relief="flat",
            cursor="hand2",
            command=self._toggle,
        ).pack(side="right", padx=scale_px(6, self._ui_scale))
        hdr.bind("<ButtonPress-1>", self._drag_start)
        hdr.bind("<B1-Motion>", self._drag_move)

        self._draw_status(frame)
        self._draw_resources(frame)
        self._draw_actions(frame)
        self._draw_log(frame)
        self._draw_footer(frame)
        self._refresh_dynamic_content()

    def _draw_status(self, parent):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=scale_px(6, self._ui_scale), pady=(scale_px(6, self._ui_scale), scale_px(2, self._ui_scale)))
        self._status_label = tk.Label(
            row,
            text="",
            bg=CARD,
            fg=TEXT,
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
        )
        self._status_label.pack(anchor="w", padx=scale_px(8, self._ui_scale), pady=scale_px(4, self._ui_scale))

    def _draw_resources(self, parent):
        res = tk.Frame(parent, bg=CARD)
        res.pack(fill="x", padx=scale_px(6, self._ui_scale), pady=(0, scale_px(2, self._ui_scale)))
        self._pyrox_label = tk.Label(
            res,
            text="",
            bg=CARD,
            fg=YELLOW,
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        )
        self._pyrox_label.pack(side="left", padx=scale_px(8, self._ui_scale), pady=scale_px(4, self._ui_scale))
        self._credit_label = tk.Label(
            res,
            text="",
            bg=CARD,
            fg=TEXT,
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        )
        self._credit_label.pack(side="left", padx=scale_px(4, self._ui_scale))

    def _draw_actions(self, parent):
        self._actions_frame = tk.Frame(parent, bg=BG)
        self._actions_frame.pack(fill="x")
        self._rebuild_actions()

    def _action_button(self, parent, text: str, bg: str, fg: str, key: str):
        tk.Button(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
            relief="flat",
            pady=scale_px(5, self._ui_scale),
            cursor="hand2",
            command=self._cbs[key],
        ).pack(fill="x", padx=scale_px(6, self._ui_scale), pady=scale_px(2, self._ui_scale))

    def _draw_log(self, parent):
        log_f = tk.Frame(parent, bg=CARD, height=scale_px(56, self._ui_scale))
        log_f.pack(fill="x", padx=scale_px(6, self._ui_scale), pady=(scale_px(4, self._ui_scale), 0))
        log_f.pack_propagate(False)
        self._log_label = tk.Label(
            log_f,
            text="",
            bg=CARD,
            fg=SUB,
            font=scale_font((FONT, 8), self._ui_scale),
            justify="left",
            anchor="nw",
            wraplength=scale_px(210, self._ui_scale),
        )
        self._log_label.pack(padx=scale_px(6, self._ui_scale), pady=scale_px(4, self._ui_scale), fill="both")

    def _state_text(self) -> str:
        labels = {
            AppState.INIT: "초기화 중",
            AppState.IDLE: "대상 창 선택 필요",
            AppState.WATCHING: "로비 감시 중",
            AppState.SCANNING: "스캔 실행 중",
            AppState.PAUSED: "일시 정지",
            AppState.ERROR: "오류 상태",
            AppState.STOPPING: "정리 중",
        }
        return f"상태: {labels.get(self._app_state, self._app_state.name)}"

    def _action_specs(self) -> list[tuple[str, str, str, str]]:
        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            return [("스캔 중지", RED, TEXT, "stop")]
        if self._app_state == AppState.ERROR:
            return [
                ("복구 / 창 다시 선택", ORANGE, BG, "recover"),
                ("입력 테스트", LBLUE, BG, "input_test"),
                ("학생 뷰어", YELLOW, BG, "view_students"),
            ]
        if self._app_state == AppState.IDLE:
            return [("창 선택", ORANGE, BG, "settings")]
        if self._app_state == AppState.WATCHING:
            if not self._in_lobby:
                return [
                    ("현재 학생 스캔", GREEN, BG, "current_student"),
                    ("입력 테스트", LBLUE, BG, "input_test"),
                    ("학생 뷰어", YELLOW, BG, "view_students"),
                    ("창 선택", ORANGE, BG, "settings"),
                ]
            return [
                ("아이템 스캔", LBLUE, BG, "items"),
                ("장비 스캔", PURPLE, BG, "equipment"),
                ("학생 스캔", GREEN, BG, "students"),
                ("현재 학생 스캔", BLUE, TEXT, "current_student"),
                ("전체 스캔", ORANGE, BG, "all"),
                ("입력 테스트", PURPLE, TEXT, "input_test"),
                ("학생 뷰어", YELLOW, BG, "view_students"),
            ]
        return [("창 선택", ORANGE, BG, "settings")]

    def _rebuild_actions(self) -> None:
        if self._actions_frame is None:
            return
        for w in self._actions_frame.winfo_children():
            w.destroy()
        for text, color, fg, key in self._action_specs():
            self._action_button(self._actions_frame, text, color, fg, key)

    def _refresh_dynamic_content(self) -> None:
        if self._status_label is not None:
            self._status_label.config(text=self._state_text())
        if self._pyrox_label is not None:
            self._pyrox_label.config(text=f"청휘석 {self._resources.get('청휘석') or '-'}")
        if self._credit_label is not None:
            self._credit_label.config(text=f"크레딧 {self._resources.get('크레딧') or '-'}")
        if self._log_label is not None:
            self._log_label.config(text="\n".join(self._log_lines[-3:]) if self._log_lines else "대기 중...")
        if self._scan_title_label is not None:
            self._scan_title_label.config(
                text="스캔 정리 중" if self._app_state == AppState.STOPPING else "학생 스캔 진행 중"
            )
        if self._scan_progress is not None:
            known_total = (
                self._scan_progress_current is not None
                and self._scan_progress_total is not None
                and self._scan_progress_total > 0
            )
            if known_total:
                current = min(self._scan_progress_current, self._scan_progress_total)
                self._scan_progress.stop()
                self._scan_progress.configure(
                    mode="determinate",
                    maximum=self._scan_progress_total,
                    value=current,
                )
            else:
                self._scan_progress.configure(mode="indeterminate")
                self._scan_progress.start(10)
        if self._scan_progress_label is not None:
            if (
                self._scan_progress_current is not None
                and self._scan_progress_total is not None
                and self._scan_progress_total > 0
            ):
                current = min(self._scan_progress_current, self._scan_progress_total)
                pct = round((current / self._scan_progress_total) * 100)
                prefix = f"{self._scan_progress_note}  " if self._scan_progress_note else ""
                self._scan_progress_label.config(
                    text=f"{prefix}{current} / {self._scan_progress_total} ({pct}%)"
                )
            else:
                self._scan_progress_label.config(
                    text=self._scan_progress_note or "진행률 계산 중..."
                )
        if self._scan_message_label is not None:
            self._scan_message_label.config(
                text=self._log_lines[-1] if self._log_lines else "스캔을 준비하고 있습니다..."
            )

    def set_scan_progress(
        self,
        current: int | None = None,
        total: int | None = None,
        note: str = "",
    ) -> None:
        self._scan_progress_current = current
        self._scan_progress_total = total
        self._scan_progress_note = note
        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            self.after(0, self._refresh_dynamic_content)

    def reset_scan_progress(self) -> None:
        self._scan_progress_current = None
        self._scan_progress_total = None
        self._scan_progress_note = ""
        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            self.after(0, self._refresh_dynamic_content)

    def _draw_footer(self, parent):
        tk.Button(
            parent,
            text="설정",
            bg=CARD,
            fg=SUB,
            font=scale_font((FONT, 9), self._ui_scale),
            relief="flat",
            cursor="hand2",
            command=self._cbs["settings"],
        ).pack(fill="x", padx=scale_px(6, self._ui_scale), pady=(scale_px(2, self._ui_scale), scale_px(6, self._ui_scale)))

    def _position_scan_windows(self) -> bool:
        rect = get_window_rect()
        if rect is None:
            return False

        left, top, width, height = rect
        self._scan_backdrop.geometry(
            f"{max(width, 1)}x{max(height, 1)}+{left}+{top}"
        )

        tw = scale_px(SCAN_CARD_W, self._ui_scale)
        th = scale_px(SCAN_CARD_H, self._ui_scale)
        ox = left + max(0, (width - tw) // 2)
        oy = top + max(0, (height - th) // 2)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        ox = max(0, min(ox, sw - tw))
        oy = max(0, min(oy, sh - th))
        self.geometry(f"{tw}x{th}+{ox}+{oy}")
        return True

    def _reposition(self):
        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            if not self._position_scan_windows():
                return
            _set_clickthrough(self._scan_backdrop, True)
            self._scan_backdrop.lift()
            self.lift()
            return

        rect = get_window_rect()
        if rect is None:
            return

        left, top, width, height = rect
        if self._expanded:
            ox = int(left + width * FLOAT_RX)
            scaled_expand_h = scale_px(EXPAND_H, self._ui_scale)
            oy = int(top + height * FLOAT_RY) - scaled_expand_h // 2
            tw, th = scale_px(EXPAND_W, self._ui_scale), scaled_expand_h
        else:
            ox = int(left + width * FLOAT_RX)
            scaled_circle_d = scale_px(CIRCLE_D, self._ui_scale)
            oy = int(top + height * FLOAT_RY) - scaled_circle_d // 2
            tw, th = scaled_circle_d, scaled_circle_d

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        ox = max(0, min(ox, sw - tw))
        oy = max(0, min(oy, sh - th))
        self.geometry(f"{tw}x{th}+{ox}+{oy}")

    def _show_scan_backdrop(self) -> None:
        if not self._visible or self._app_state not in (AppState.SCANNING, AppState.STOPPING):
            self._scan_backdrop.withdraw()
            return
        self._position_scan_windows()
        self._scan_backdrop.deiconify()
        self._scan_backdrop.update_idletasks()
        _set_clickthrough(self._scan_backdrop, True)
        self._scan_backdrop.lift()

    def _hide_scan_backdrop(self) -> None:
        self._scan_backdrop.withdraw()

    def _start_tracker(self):
        def loop():
            while not self._stop_event.is_set():
                try:
                    if self._visible:
                        self.after(0, self._sync_visibility)
                except Exception:
                    pass
                self._stop_event.wait(0.5)

        threading.Thread(target=loop, daemon=True).start()

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    def _sync_visibility(self) -> None:
        if not self._visible:
            self._hide_scan_backdrop()
            self.withdraw()
            return
        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            self._show_scan_backdrop()
            self._position_scan_windows()
        self.deiconify()
        self.update_idletasks()
        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            self.lift()
        self._reposition()

    def show(self):
        self._visible = True
        self._sync_visibility()

    def hide(self):
        if self._visible:
            self._visible = False
            self._hide_scan_backdrop()
            self.withdraw()

    def set_app_state(self, state: AppState):
        prev = self._app_state
        self._app_state = state
        if prev in (AppState.SCANNING, AppState.STOPPING) and self._scan_progress is not None:
            self._scan_progress.stop()
        if not self._expanded and state not in (AppState.SCANNING, AppState.STOPPING):
            self.after(0, self._draw)
            return
        self.after(0, self._refresh_dynamic_content)
        if prev != state:
            self.after(0, self._rebuild_actions)
        if prev != state and (
            prev in (AppState.SCANNING, AppState.STOPPING)
            or state in (AppState.SCANNING, AppState.STOPPING)
        ):
            self.after(0, self._draw)
            self.after(0, self._reposition)
        if self._visible and state in (AppState.SCANNING, AppState.STOPPING):
            self.after(0, self._show_scan_backdrop)
            self.after(0, self.show)
        else:
            self.after(0, self._hide_scan_backdrop)

    def set_lobby_state(self, in_lobby: bool) -> None:
        prev = self._in_lobby
        self._in_lobby = in_lobby
        if self._app_state == AppState.WATCHING and prev != in_lobby:
            self.after(0, self._rebuild_actions)

    def update_resources(self, res: dict):
        self._resources = res
        if self._expanded:
            self.after(0, self._refresh_dynamic_content)

    def add_log(self, msg: str):
        self._log_lines.append(msg)
        if len(self._log_lines) > 30:
            self._log_lines = self._log_lines[-30:]
        if self._expanded or self._app_state in (AppState.SCANNING, AppState.STOPPING):
            self.after(0, self._refresh_dynamic_content)

    def _toggle(self):
        if self._app_state in (AppState.SCANNING, AppState.STOPPING):
            return
        self._expanded = not self._expanded
        self._draw()
        self._reposition()

    def destroy(self):
        self._stop_event.set()
        if self._scan_progress is not None:
            self._scan_progress.stop()
        self._scan_backdrop.destroy()
        super().destroy()
