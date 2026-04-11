"""
Temporary overlay for comparing click strategies and overlay hit-testing.
"""

from __future__ import annotations

import ctypes
import threading
import time
import tkinter as tk

from core.capture import find_target_hwnd, get_window_rect
from core.input import DEBUG_CLICK_METHODS, debug_click_screen, get_cursor_pos
from gui.ui_scale import get_ui_scale, scale_font, scale_px

BG = "#0d1b2a"
CARD = "#152435"
TEXT = "#e8f4fd"
SUB = "#7ab3d4"
BLUE = "#1a6fad"
LBLUE = "#4aa8e0"
RED = "#FF4D4D"
FONT = "Malgun Gothic"

PANEL_W = 430
PANEL_H = 430

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


class InputTestOverlay(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self._backdrop = tk.Toplevel(master)
        self._visible = False
        self._stop_event = threading.Event()
        self._countdown_job: str | None = None
        self._countdown_deadline = 0.0
        self._target_mode = "cursor"
        self._ui_scale = get_ui_scale(self, base_width=1600, base_height=1080)
        self._overlay_mode = tk.StringVar(value="none")
        self._click_method = tk.StringVar(value="activate_pag")
        self._status_text = tk.StringVar(value="대기 중")
        self._countdown_text = tk.StringVar(value="클릭 예약 없음")

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.96)
        self.configure(bg=BG)
        self.withdraw()

        self._backdrop.overrideredirect(True)
        self._backdrop.attributes("-topmost", True)
        self._backdrop.withdraw()

        self._draw()
        self._start_tracker()

    def _draw(self) -> None:
        for widget in self.winfo_children():
            widget.destroy()

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True)
        card = tk.Frame(outer, bg=CARD, highlightbackground=LBLUE, highlightthickness=2)
        card.pack(fill="both", expand=True)

        header = tk.Frame(card, bg=BLUE)
        header.pack(fill="x")
        tk.Label(
            header,
            text="입력 테스트",
            bg=BLUE,
            fg=TEXT,
            font=scale_font((FONT, 12, "bold"), self._ui_scale),
        ).pack(side="left", padx=scale_px(10, self._ui_scale), pady=scale_px(6, self._ui_scale))
        tk.Button(
            header,
            text="닫기",
            bg=BLUE,
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=self.hide,
        ).pack(side="right", padx=scale_px(6, self._ui_scale), pady=scale_px(4, self._ui_scale))

        body = tk.Frame(card, bg=CARD)
        body.pack(fill="both", expand=True, padx=scale_px(12, self._ui_scale), pady=scale_px(10, self._ui_scale))

        tk.Label(
            body,
            text="오버레이 모드",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x")
        for value, label in [
            ("none", "패널만"),
            ("dim_blocking", "어두운 배경 - 클릭 막음"),
            ("dim_passthrough", "어두운 배경 - 클릭 통과"),
            ("clear_passthrough", "투명 배경 - 클릭 통과"),
        ]:
            tk.Radiobutton(
                body,
                text=label,
                value=value,
                variable=self._overlay_mode,
                command=self._apply_backdrop_mode,
                bg=CARD,
                fg=TEXT,
                selectcolor=BG,
                activebackground=CARD,
                activeforeground=TEXT,
                anchor="w",
                font=scale_font((FONT, 9), self._ui_scale),
            ).pack(fill="x")

        tk.Label(
            body,
            text="클릭 방식",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(10, self._ui_scale), 0))

        methods_frame = tk.Frame(body, bg=CARD)
        methods_frame.pack(fill="x", pady=(scale_px(4, self._ui_scale), 0))
        for idx, (value, label) in enumerate(DEBUG_CLICK_METHODS):
            tk.Radiobutton(
                methods_frame,
                text=label,
                value=value,
                variable=self._click_method,
                bg=CARD,
                fg=TEXT,
                selectcolor=BG,
                activebackground=CARD,
                activeforeground=TEXT,
                anchor="w",
                font=scale_font((FONT, 8), self._ui_scale),
            ).grid(row=idx // 2, column=idx % 2, sticky="w", padx=(0, scale_px(8, self._ui_scale)))

        action_row = tk.Frame(body, bg=CARD)
        action_row.pack(fill="x", pady=(scale_px(12, self._ui_scale), 0))
        tk.Button(
            action_row,
            text="2초 후 현재 커서 클릭",
            bg=LBLUE,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._arm_click("cursor"),
        ).pack(fill="x")
        tk.Button(
            action_row,
            text="즉시 게임 중앙 클릭",
            bg="#79d392",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._arm_click("center"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))

        tk.Label(
            body,
            textvariable=self._countdown_text,
            bg=CARD,
            fg=TEXT,
            justify="left",
            anchor="w",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(12, self._ui_scale), 0))
        tk.Label(
            body,
            textvariable=self._status_text,
            bg=CARD,
            fg=SUB,
            justify="left",
            anchor="w",
            wraplength=scale_px(PANEL_W - 48, self._ui_scale),
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))

    def is_visible(self) -> bool:
        return self._visible

    def _game_center(self) -> tuple[int, int] | None:
        rect = get_window_rect()
        if rect is None:
            return None
        left, top, width, height = rect
        return left + width // 2, top + height // 2

    def _position_windows(self) -> None:
        rect = get_window_rect()
        panel_w = scale_px(PANEL_W, self._ui_scale)
        panel_h = scale_px(PANEL_H, self._ui_scale)
        if rect is None:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            ox = max(0, (sw - panel_w) // 2)
            oy = max(0, (sh - panel_h) // 2)
            self.geometry(f"{panel_w}x{panel_h}+{ox}+{oy}")
            self._backdrop.withdraw()
            return

        left, top, width, height = rect
        ox = left + max(0, (width - panel_w) // 2)
        oy = top + max(0, (height - panel_h) // 2)
        self.geometry(f"{panel_w}x{panel_h}+{ox}+{oy}")
        self._backdrop.geometry(f"{max(width, 1)}x{max(height, 1)}+{left}+{top}")
        self._apply_backdrop_mode()

    def _apply_backdrop_mode(self) -> None:
        if not self._visible:
            self._backdrop.withdraw()
            return

        rect = get_window_rect()
        mode = self._overlay_mode.get()
        if rect is None or mode == "none":
            self._backdrop.withdraw()
            return

        if mode == "dim_blocking":
            alpha = 0.20
            clickthrough = False
            bg = "#08131d"
        elif mode == "dim_passthrough":
            alpha = 0.20
            clickthrough = True
            bg = "#08131d"
        else:
            alpha = 0.01
            clickthrough = True
            bg = "#08131d"

        self._backdrop.configure(bg=bg)
        self._backdrop.attributes("-alpha", alpha)
        self._backdrop.deiconify()
        self._backdrop.update_idletasks()
        _set_clickthrough(self._backdrop, clickthrough)
        self._backdrop.lift()
        self.lift()

    def _tick_countdown(self) -> None:
        remaining = self._countdown_deadline - time.monotonic()
        if remaining <= 0:
            self._countdown_job = None
            self._countdown_text.set("클릭 실행 중...")
            self.after(0, self._fire_click)
            return
        self._countdown_text.set(f"{remaining:.1f}초 후 {self._target_mode} 위치 클릭")
        self._countdown_job = self.after(100, self._tick_countdown)

    def _cancel_countdown(self) -> None:
        if self._countdown_job is not None:
            self.after_cancel(self._countdown_job)
            self._countdown_job = None
        self._countdown_text.set("클릭 예약 없음")

    def _arm_click(self, target_mode: str) -> None:
        if find_target_hwnd() is None:
            self._status_text.set("대상 게임 창이 없습니다. 창을 먼저 다시 선택해 주세요.")
            return
        self._cancel_countdown()
        self._target_mode = target_mode
        if target_mode == "center":
            self._countdown_deadline = time.monotonic() + 0.25
        else:
            self._countdown_deadline = time.monotonic() + 2.0
        self._tick_countdown()

    def _fire_click(self) -> None:
        hwnd = find_target_hwnd()
        if hwnd is None:
            self._status_text.set("대상 게임 창을 찾지 못했습니다.")
            self._countdown_text.set("클릭 예약 없음")
            return

        if self._target_mode == "center":
            pos = self._game_center()
        else:
            pos = get_cursor_pos()

        if pos is None:
            self._status_text.set("타깃 좌표를 가져오지 못했습니다.")
            self._countdown_text.set("클릭 예약 없음")
            return

        method = self._click_method.get()
        sx, sy = pos
        ok = debug_click_screen(
            hwnd,
            sx,
            sy,
            method=method,
            label=f"input_test:{self._target_mode}:{method}",
        )
        self._status_text.set(
            f"method={method} target={self._target_mode} screen=({sx},{sy}) ok={ok}"
        )
        self._countdown_text.set("클릭 예약 없음")

    def _start_tracker(self) -> None:
        def loop() -> None:
            while not self._stop_event.is_set():
                if self._visible:
                    try:
                        self.after(0, self._position_windows)
                    except Exception:
                        pass
                self._stop_event.wait(0.4)

        threading.Thread(target=loop, name="InputTestOverlayTracker", daemon=True).start()

    def show(self) -> None:
        if not self._visible:
            self._visible = True
            self._position_windows()
            self.deiconify()
            self.update_idletasks()
            self.lift()
            self._apply_backdrop_mode()

    def hide(self) -> None:
        if self._visible:
            self._visible = False
            self._cancel_countdown()
            self._backdrop.withdraw()
            self.withdraw()

    def destroy(self) -> None:
        self._stop_event.set()
        self._cancel_countdown()
        try:
            self._backdrop.destroy()
        except tk.TclError:
            pass
        super().destroy()
