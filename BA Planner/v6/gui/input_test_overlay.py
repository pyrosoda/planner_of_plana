"""
Temporary overlay for comparing click strategies and collecting click points.
"""

from __future__ import annotations

import ctypes
import json
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

from core.capture import find_target_hwnd, get_window_rect
from core.config import BASE_DIR
from core.input import DEBUG_CLICK_METHODS, debug_click_screen, get_cursor_pos
from core.logger import LOG_APP, get_logger
from gui.ui_scale import get_ui_scale, scale_font, scale_px

BG = "#0d1b2a"
CARD = "#152435"
TEXT = "#e8f4fd"
SUB = "#7ab3d4"
BLUE = "#1a6fad"
LBLUE = "#4aa8e0"
RED = "#FF4D4D"
YELLOW = "#f5c842"
GREEN = "#3dbf7a"
FONT = "Malgun Gothic"

PANEL_W = 430
PANEL_H = 620
POINT_CAPTURE_FILE = BASE_DIR / "debug" / "captured_click_points.json"
DEFAULT_CAPTURE_NAME = "skill_close_button"
PRESET_CAPTURE_NAMES = (
    "skill_close_button",
    "weapon_close_button",
    "equipment_close_button",
    "level_close_button",
    "stat_close_button",
)

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
_log = get_logger(LOG_APP)


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
        self._pending_action = "click"
        self._target_mode = "cursor"
        self._ui_scale = get_ui_scale(self, base_width=1600, base_height=1080)
        self._overlay_mode = tk.StringVar(value="none")
        self._click_method = tk.StringVar(value="activate_pag")
        self._capture_name = tk.StringVar(value=DEFAULT_CAPTURE_NAME)
        self._status_text = tk.StringVar(value="Ready")
        self._countdown_text = tk.StringVar(value="No pending action")

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
            text="Input Test",
            bg=BLUE,
            fg=TEXT,
            font=scale_font((FONT, 12, "bold"), self._ui_scale),
        ).pack(side="left", padx=scale_px(10, self._ui_scale), pady=scale_px(6, self._ui_scale))
        tk.Button(
            header,
            text="Close",
            bg=BLUE,
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=self.hide,
        ).pack(side="right", padx=scale_px(6, self._ui_scale), pady=scale_px(4, self._ui_scale))

        body = tk.Frame(card, bg=CARD)
        body.pack(fill="both", expand=True, padx=scale_px(12, self._ui_scale), pady=scale_px(10, self._ui_scale))

        self._draw_overlay_mode_section(body)
        self._draw_click_method_section(body)
        self._draw_click_action_section(body)
        self._draw_capture_section(body)

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

    def _draw_overlay_mode_section(self, body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Overlay Mode",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x")
        for value, label in [
            ("none", "Panel only"),
            ("dim_blocking", "Dim backdrop - blocking"),
            ("dim_passthrough", "Dim backdrop - click-through"),
            ("clear_passthrough", "Clear backdrop - click-through"),
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

    def _draw_click_method_section(self, body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Click Method",
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

    def _draw_click_action_section(self, body: tk.Frame) -> None:
        action_row = tk.Frame(body, bg=CARD)
        action_row.pack(fill="x", pady=(scale_px(12, self._ui_scale), 0))
        tk.Button(
            action_row,
            text="Click current cursor in 2s",
            bg=LBLUE,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._arm_click("cursor"),
        ).pack(fill="x")
        tk.Button(
            action_row,
            text="Click game center now",
            bg=GREEN,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._arm_click("center"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))

    def _draw_capture_section(self, body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Capture Point Name",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(14, self._ui_scale), 0))
        tk.Entry(
            body,
            textvariable=self._capture_name,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0), ipady=scale_px(5, self._ui_scale))

        preset_row = tk.Frame(body, bg=CARD)
        preset_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        for name in PRESET_CAPTURE_NAMES:
            tk.Button(
                preset_row,
                text=name.replace("_button", ""),
                bg="#24384d",
                fg=TEXT,
                relief="flat",
                cursor="hand2",
                font=scale_font((FONT, 8), self._ui_scale),
                command=lambda value=name: self._capture_name.set(value),
            ).pack(side="left", padx=(0, scale_px(4, self._ui_scale)))

        capture_row = tk.Frame(body, bg=CARD)
        capture_row.pack(fill="x", pady=(scale_px(8, self._ui_scale), 0))
        tk.Button(
            capture_row,
            text="Record cursor in 2s",
            bg=YELLOW,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._arm_capture(delay=2.0),
        ).pack(fill="x")
        tk.Button(
            capture_row,
            text="Record cursor now",
            bg=GREEN,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._arm_capture(delay=0.0),
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
            if self._pending_action == "capture":
                self._countdown_text.set("Recording point...")
            else:
                self._countdown_text.set("Running click...")
            self.after(0, self._fire_pending_action)
            return
        if self._pending_action == "capture":
            name = self._capture_name.get().strip() or DEFAULT_CAPTURE_NAME
            self._countdown_text.set(f"{remaining:.1f}s -> record '{name}'")
        else:
            self._countdown_text.set(f"{remaining:.1f}s -> click {self._target_mode}")
        self._countdown_job = self.after(100, self._tick_countdown)

    def _cancel_countdown(self) -> None:
        if self._countdown_job is not None:
            self.after_cancel(self._countdown_job)
            self._countdown_job = None
        self._countdown_text.set("No pending action")

    def _arm_click(self, target_mode: str) -> None:
        if find_target_hwnd() is None:
            self._status_text.set("No target game window selected.")
            return
        self._cancel_countdown()
        self._pending_action = "click"
        self._target_mode = target_mode
        self._countdown_deadline = time.monotonic() + (0.25 if target_mode == "center" else 2.0)
        self._tick_countdown()

    def _arm_capture(self, delay: float) -> None:
        if find_target_hwnd() is None:
            self._status_text.set("No target game window selected.")
            return
        if not self._capture_name.get().strip():
            self._status_text.set("Enter a capture point name first.")
            return
        self._cancel_countdown()
        self._pending_action = "capture"
        self._countdown_deadline = time.monotonic() + max(0.0, delay)
        if delay <= 0:
            self._fire_pending_action()
            return
        self._tick_countdown()

    def _fire_pending_action(self) -> None:
        if self._pending_action == "capture":
            self._record_capture_point()
            return
        self._fire_click()

    def _fire_click(self) -> None:
        hwnd = find_target_hwnd()
        if hwnd is None:
            self._status_text.set("Target game window was not found.")
            self._countdown_text.set("No pending action")
            return

        if self._target_mode == "center":
            pos = self._game_center()
        else:
            pos = get_cursor_pos()

        if pos is None:
            self._status_text.set("Failed to read the target position.")
            self._countdown_text.set("No pending action")
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
        self._countdown_text.set("No pending action")

    def _record_capture_point(self) -> None:
        pos = get_cursor_pos()
        rect = get_window_rect()
        name = self._capture_name.get().strip() or DEFAULT_CAPTURE_NAME

        if pos is None:
            self._status_text.set("Failed to read current cursor position.")
            self._countdown_text.set("No pending action")
            return
        if rect is None:
            self._status_text.set("Failed to read target window bounds.")
            self._countdown_text.set("No pending action")
            return

        sx, sy = pos
        left, top, width, height = rect
        width = max(width, 1)
        height = max(height, 1)
        cx = sx - left
        cy = sy - top
        ratio_x = round(cx / width, 6)
        ratio_y = round(cy / height, 6)

        payload = self._load_capture_points()
        payload[name] = {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "screen": {"x": sx, "y": sy},
            "client": {"x": cx, "y": cy},
            "ratio": {"x": ratio_x, "y": ratio_y},
            "window": {
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            },
        }
        self._write_capture_points(payload)
        _log.info(
            "[coord_capture] name=%s screen=(%d,%d) client=(%d,%d) ratio=(%.6f,%.6f) file=%s",
            name,
            sx,
            sy,
            cx,
            cy,
            ratio_x,
            ratio_y,
            POINT_CAPTURE_FILE,
        )
        self._status_text.set(
            f"saved {name}: screen=({sx},{sy}) client=({cx},{cy}) ratio=({ratio_x:.6f},{ratio_y:.6f})"
        )
        self._countdown_text.set(f"Saved -> {POINT_CAPTURE_FILE.name}")

    def _load_capture_points(self) -> dict:
        try:
            if POINT_CAPTURE_FILE.exists():
                raw = json.loads(POINT_CAPTURE_FILE.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
        except Exception as exc:
            _log.warning("[coord_capture] failed to read %s: %s", POINT_CAPTURE_FILE, exc)
        return {}

    def _write_capture_points(self, payload: dict) -> None:
        path = Path(POINT_CAPTURE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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
