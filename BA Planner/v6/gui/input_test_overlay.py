"""
Temporary overlay for comparing click strategies and collecting click points.
"""

from __future__ import annotations

import json
import re
import threading
import time
import tkinter as tk
import ctypes
from datetime import datetime
from pathlib import Path

from core.capture import capture_window_background, find_target_hwnd, get_window_rect
from core.config import BASE_DIR
from core.input import (
    DEBUG_CLICK_METHODS,
    debug_click_client,
    debug_click_screen,
    drag_scroll,
    get_cursor_pos,
    ratio_to_client,
    scroll,
    scroll_raw_delta,
)
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
REGION_CAPTURE_DIR = BASE_DIR / "debug" / "region_captures"
INVENTORY_DETAIL_TEMPLATE_DIR = BASE_DIR / "templates" / "inventory_detail"
DEFAULT_CAPTURE_NAME = "skill_close_button"
DEFAULT_REGION_CAPTURE_NAME = "debug_region"
PRESET_CAPTURE_NAMES = (
    "skill_close_button",
    "weapon_close_button",
    "equipment_close_button",
    "level_close_button",
    "stat_close_button",
)
REGION_TEMPLATE_PROFILE_OPTIONS = (
    ("tech_notes", "Tech Notes"),
    ("tactical_bd", "Tactical BD"),
    ("activity_reports", "Reports"),
    ("ooparts", "OOParts"),
)

_log = get_logger(LOG_APP)

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


def _sanitize_capture_name(name: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", (name or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._")
    return cleaned or fallback


def _parallelogram_from_three_points(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if len(points) != 3:
        raise ValueError("exactly three points are required")
    bottom_left, raw_bottom_right, top_left = [(float(x), float(y)) for x, y in points]
    bottom_right = (raw_bottom_right[0], bottom_left[1])
    top_right = (
        bottom_right[0] + (top_left[0] - bottom_left[0]),
        bottom_right[1] + (top_left[1] - bottom_left[1]),
    )
    return [top_left, top_right, bottom_right, bottom_left]


def _rectangle_from_two_points(
    points: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    if len(points) != 2:
        raise ValueError("exactly two points are required")
    p1, p2 = [(float(x), float(y)) for x, y in points]
    left = min(p1[0], p2[0])
    right = max(p1[0], p2[0])
    top = min(p1[1], p2[1])
    bottom = max(p1[1], p2[1])
    return [(left, top), (right, top), (right, bottom), (left, bottom)]


def _region_capture_payload(
    *,
    target_rect: tuple[int, int, int, int],
    ordered_screen: list[tuple[float, float]],
    capture_name: str,
) -> dict:
    left, top, width, height = target_rect
    ordered_client = [(sx - left, sy - top) for sx, sy in ordered_screen]
    return {
        "name": capture_name,
        "window_rect": {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
        },
        "points_screen": [{"x": int(round(x)), "y": int(round(y))} for x, y in ordered_screen],
        "points_client": [{"x": int(round(x)), "y": int(round(y))} for x, y in ordered_client],
        "points_ratio": [
            {"x": round(x / max(width, 1), 6), "y": round(y / max(height, 1), 6)}
            for x, y in ordered_client
        ],
    }


def _warp_region_image(image, payload: dict):
    import cv2
    import numpy as np
    from PIL import Image

    points_client = [(float(p["x"]), float(p["y"])) for p in payload["points_client"]]
    top_left, top_right, bottom_right, bottom_left = points_client
    top_width = ((top_right[0] - top_left[0]) ** 2 + (top_right[1] - top_left[1]) ** 2) ** 0.5
    bottom_width = ((bottom_right[0] - bottom_left[0]) ** 2 + (bottom_right[1] - bottom_left[1]) ** 2) ** 0.5
    left_height = ((bottom_left[0] - top_left[0]) ** 2 + (bottom_left[1] - top_left[1]) ** 2) ** 0.5
    right_height = ((bottom_right[0] - top_right[0]) ** 2 + (bottom_right[1] - top_right[1]) ** 2) ** 0.5
    dst_w = max(1, int(round(max(top_width, bottom_width))))
    dst_h = max(1, int(round(max(left_height, right_height))))

    src = np.array(points_client, dtype=np.float32)
    dst = np.array(
        [(0.0, 0.0), (dst_w - 1.0, 0.0), (dst_w - 1.0, dst_h - 1.0), (0.0, dst_h - 1.0)],
        dtype=np.float32,
    )
    image_np = np.array(image.convert("RGB"))
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(image_np, matrix, (dst_w, dst_h))
    return Image.fromarray(warped), {"width": dst_w, "height": dst_h}


def _next_region_capture_paths(base_name: str) -> tuple[Path, Path]:
    REGION_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    for idx in range(1, 1000):
        suffix = f"_{idx:03d}"
        png_path = REGION_CAPTURE_DIR / f"{base_name}{suffix}.png"
        json_path = REGION_CAPTURE_DIR / f"{base_name}{suffix}.json"
        if not png_path.exists() and not json_path.exists():
            return png_path, json_path
    raise RuntimeError("too many captures for the same region name")


def _save_region_capture(image, payload: dict) -> tuple[Path, Path]:
    warped, output_size = _warp_region_image(image, payload)
    base_name = _sanitize_capture_name(str(payload.get("name") or DEFAULT_REGION_CAPTURE_NAME), DEFAULT_REGION_CAPTURE_NAME)
    png_path, json_path = _next_region_capture_paths(base_name)
    warped.save(png_path)
    out_payload = dict(payload)
    out_payload["captured_at"] = datetime.now().isoformat(timespec="seconds")
    out_payload["output_size"] = output_size
    out_payload["image_path"] = str(png_path)
    json_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return png_path, json_path


def _save_region_definition(payload: dict) -> Path:
    REGION_CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    base_name = _sanitize_capture_name(str(payload.get("name") or DEFAULT_REGION_CAPTURE_NAME), DEFAULT_REGION_CAPTURE_NAME)
    json_path = REGION_CAPTURE_DIR / f"{base_name}.region.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


class RegionCaptureOverlay(tk.Toplevel):
    def __init__(self, master, *, ui_scale: float, on_complete):
        super().__init__(master)
        self._ui_scale = ui_scale
        self._on_complete = on_complete
        self._target_rect: tuple[int, int, int, int] | None = None
        self._capture_name = DEFAULT_REGION_CAPTURE_NAME
        self._points: list[tuple[int, int]] = []
        self._active_quad: list[tuple[float, float]] | None = None
        self._selection_mode = False
        self._capture_shape = "parallelogram"
        self.withdraw()
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.22)
        self.configure(bg="#000000")
        self._canvas = tk.Canvas(self, bg="#000000", highlightthickness=0, bd=0, relief="flat")
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Button-1>", self._on_left_click)
        self._canvas.bind("<Button-3>", self._on_right_click)
        self.bind("<Escape>", lambda _e: self.cancel("cancelled"))
        self.bind("<BackSpace>", lambda _e: self._undo_last_point())
        self.bind("<Delete>", lambda _e: self._undo_last_point())
        self.bind("<FocusOut>", self._on_focus_out)

    def begin(
        self,
        *,
        target_rect: tuple[int, int, int, int],
        capture_name: str,
        capture_shape: str = "parallelogram",
    ) -> None:
        self._target_rect = target_rect
        self._capture_name = _sanitize_capture_name(capture_name, DEFAULT_REGION_CAPTURE_NAME)
        self._points = []
        self._active_quad = None
        self._selection_mode = True
        self._capture_shape = capture_shape if capture_shape in {"parallelogram", "rectangle"} else "parallelogram"
        screen_w = max(self.winfo_screenwidth(), 1)
        screen_h = max(self.winfo_screenheight(), 1)
        self.geometry(f"{screen_w}x{screen_h}+0+0")
        self.deiconify()
        self.lift()
        self.focus_force()
        _set_clickthrough(self, False)
        self._redraw()

    def cancel(self, reason: str) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.withdraw()
        self._points = []
        self._selection_mode = False
        self._on_complete(False, f"region capture {reason}", None)

    def show_active_region(
        self,
        *,
        target_rect: tuple[int, int, int, int],
        quad_screen: list[tuple[float, float]],
        capture_name: str,
        raise_window: bool = False,
    ) -> None:
        self._target_rect = target_rect
        self._capture_name = _sanitize_capture_name(capture_name, DEFAULT_REGION_CAPTURE_NAME)
        self._points = []
        self._active_quad = quad_screen
        self._selection_mode = False
        screen_w = max(self.winfo_screenwidth(), 1)
        screen_h = max(self.winfo_screenheight(), 1)
        self.geometry(f"{screen_w}x{screen_h}+0+0")
        if str(self.state()) == "withdrawn":
            self.deiconify()
        if raise_window:
            self.lift()
        _set_clickthrough(self, True)
        self._redraw()

    def clear_active_region(self) -> None:
        self._active_quad = None
        self._selection_mode = False
        self._points = []
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.withdraw()

    def suspend(self) -> None:
        self._selection_mode = False
        self._points = []
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.withdraw()

    def _undo_last_point(self) -> None:
        if self._selection_mode and self._points:
            self._points.pop()
            self._redraw()

    def _on_focus_out(self, _event=None) -> None:
        if not self.winfo_exists():
            return
        if self._selection_mode:
            try:
                self.after(10, self._bring_to_front)
            except tk.TclError:
                pass

    def _bring_to_front(self) -> None:
        if not self.winfo_exists():
            return
        try:
            self.attributes("-topmost", True)
            self.lift()
            if self._selection_mode:
                self.focus_force()
        except tk.TclError:
            pass

    def _on_right_click(self, _event) -> None:
        self._undo_last_point()

    def _on_left_click(self, event) -> None:
        if not self._selection_mode or self._target_rect is None:
            return
        left, top, width, height = self._target_rect
        sx = int(event.x_root)
        sy = int(event.y_root)
        if not (left <= sx <= left + width and top <= sy <= top + height):
            return
        max_points = 3 if self._capture_shape == "parallelogram" else 2
        if len(self._points) >= max_points:
            return
        if self._capture_shape == "parallelogram" and len(self._points) == 1:
            sy = self._points[0][1]
        self._points.append((sx, sy))
        if len(self._points) == max_points:
            self._save_capture()
            return
        self._redraw()

    def _redraw(self) -> None:
        self._canvas.delete("all")
        if self._target_rect is None:
            return
        left, top, width, height = self._target_rect
        right = left + width
        bottom = top + height
        self._canvas.create_rectangle(left, top, right, bottom, outline="#4aa8e0", width=2)
        if self._selection_mode:
            if self._capture_shape == "rectangle":
                helper_text = "Set rectangle: click top-left -> bottom-right. Right click or Backspace to undo. Esc to cancel."
            else:
                helper_text = "Set region: click 3 points in order (bottom-left -> bottom-right width only -> top-left). Right click or Backspace to undo. Esc to cancel."
            self._canvas.create_text(
                left + 12,
                max(20, top - 18),
                text=helper_text,
                anchor="w",
                fill="#f5f8ff",
                font=scale_font((FONT, 10, "bold"), self._ui_scale),
            )
            for idx, (sx, sy) in enumerate(self._points, start=1):
                self._canvas.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, fill="#f5c842", outline="#f5c842")
                self._canvas.create_text(
                    sx + 12,
                    sy - 10,
                    text=str(idx),
                    anchor="w",
                    fill="#f5f8ff",
                    font=scale_font((FONT, 10, "bold"), self._ui_scale),
                )
            if len(self._points) >= 2:
                self._canvas.create_line(*[coord for point in self._points for coord in point], fill="#f5c842", width=2)
            if self._capture_shape == "parallelogram" and len(self._points) == 3:
                self._active_quad = _parallelogram_from_three_points(self._points)
            elif self._capture_shape == "rectangle" and len(self._points) == 2:
                self._active_quad = _rectangle_from_two_points(self._points)
        elif self._active_quad:
            self._canvas.create_text(
                left + 12,
                max(20, top - 18),
                text=f"Active region: {self._capture_name}",
                anchor="w",
                fill="#f5f8ff",
                font=scale_font((FONT, 10, "bold"), self._ui_scale),
            )
        if self._active_quad:
            top_left, top_right, bottom_right, bottom_left = self._active_quad
            self._canvas.create_line(
                top_left[0], top_left[1], top_right[0], top_right[1],
                bottom_right[0], bottom_right[1], bottom_left[0], bottom_left[1],
                top_left[0], top_left[1],
                fill="#8ecae6",
                width=2,
            )

    def _save_capture(self) -> None:
        expected_points = 3 if self._capture_shape == "parallelogram" else 2
        if self._target_rect is None or len(self._points) != expected_points:
            self.cancel("failed")
            return

        if self._capture_shape == "rectangle":
            ordered_screen = _rectangle_from_two_points(self._points)
        else:
            ordered_screen = _parallelogram_from_three_points(self._points)
        payload = _region_capture_payload(
            target_rect=self._target_rect,
            ordered_screen=ordered_screen,
            capture_name=self._capture_name,
        )
        payload["shape"] = self._capture_shape
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self._points = []
        self._selection_mode = False
        self._active_quad = None
        _set_clickthrough(self, False)
        self.withdraw()
        self._on_complete(True, f"region set: {self._capture_name}", payload)


class InputTestOverlay(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self._visible = False
        self._stop_event = threading.Event()
        self._countdown_job: str | None = None
        self._countdown_deadline = 0.0
        self._pending_action = "click"
        self._target_mode = "cursor"
        self._ui_scale = get_ui_scale(self, base_width=1600, base_height=1080)
        self._click_method = tk.StringVar(value="activate_pag")
        self._coord_mode = tk.StringVar(value="client")
        self._coord_x = tk.StringVar(value="")
        self._coord_y = tk.StringVar(value="")
        self._capture_name = tk.StringVar(value=DEFAULT_CAPTURE_NAME)
        self._region_capture_name = tk.StringVar(value=DEFAULT_REGION_CAPTURE_NAME)
        self._region_template_profile = tk.StringVar(value="tech_notes")
        self._status_text = tk.StringVar(value="Ready")
        self._countdown_text = tk.StringVar(value="No pending action")
        self._scroll_amount = tk.StringVar(value="-360")
        self._scroll_delta = tk.StringVar(value="-30")
        self._drag_delta_y = tk.StringVar(value="-160")
        self._drag_duration = tk.StringVar(value="0.14")
        self._drag_coord_mode = tk.StringVar(value="client")
        self._drag_coord_x = tk.StringVar(value="")
        self._drag_coord_y = tk.StringVar(value="")
        self._scroll_canvas: tk.Canvas | None = None
        self._scroll_body: tk.Frame | None = None
        self._active_region_payload: dict | None = None
        self._region_capture_overlay: RegionCaptureOverlay | None = None
        self._region_capture_restore_input = False
        self._region_capture_restore_floating = False
        self.title("Input Test")
        self.overrideredirect(False)
        self.attributes("-topmost", False)
        self.attributes("-alpha", 1.0)
        self.resizable(False, True)
        self.configure(bg=BG)
        self.withdraw()

        self._draw()
        self._start_tracker()

    def _draw(self) -> None:
        for widget in self.winfo_children():
            if isinstance(widget, tk.Toplevel):
                continue
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

        body_wrap = tk.Frame(card, bg=CARD)
        body_wrap.pack(fill="both", expand=True, padx=scale_px(12, self._ui_scale), pady=scale_px(10, self._ui_scale))

        canvas = tk.Canvas(
            body_wrap,
            bg=CARD,
            highlightthickness=0,
            bd=0,
            relief="flat",
        )
        scrollbar = tk.Scrollbar(body_wrap, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=CARD)
        body.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(body_window, width=e.width),
        )
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._scroll_canvas = canvas
        self._scroll_body = body

        self._draw_click_method_section(body)
        self._draw_click_action_section(body)
        self._draw_exact_coord_section(body)
        self._draw_capture_section(body)
        self._draw_region_capture_section(body)
        self._draw_scroll_test_section(body)

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

    def _ensure_region_capture_overlay(self) -> None:
        overlay = getattr(self, "_region_capture_overlay", None)
        try:
            alive = bool(overlay and overlay.winfo_exists())
        except Exception:
            alive = False
        if alive:
            return
        self._region_capture_overlay = RegionCaptureOverlay(
            self,
            ui_scale=self._ui_scale,
            on_complete=self._on_region_capture_complete,
        )

    def _on_mousewheel(self, event) -> str | None:
        if not self._visible or self._scroll_canvas is None:
            return None
        try:
            self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            return None
        return "break"

    def _draw_click_method_section(self, body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Click Method",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x")

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

    def _draw_exact_coord_section(self, body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Exact Coordinate Click",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(14, self._ui_scale), 0))

        mode_row = tk.Frame(body, bg=CARD)
        mode_row.pack(fill="x", pady=(scale_px(4, self._ui_scale), 0))
        for value, label in [("client", "Client"), ("screen", "Screen"), ("ratio", "Ratio")]:
            tk.Radiobutton(
                mode_row,
                text=label,
                value=value,
                variable=self._coord_mode,
                bg=CARD,
                fg=TEXT,
                selectcolor=BG,
                activebackground=CARD,
                activeforeground=TEXT,
                anchor="w",
                font=scale_font((FONT, 8), self._ui_scale),
            ).pack(side="left", padx=(0, scale_px(10, self._ui_scale)))

        entry_row = tk.Frame(body, bg=CARD)
        entry_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Entry(
            entry_row,
            textvariable=self._coord_x,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=10,
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(side="left", fill="x", expand=True, ipady=scale_px(5, self._ui_scale))
        tk.Entry(
            entry_row,
            textvariable=self._coord_y,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=10,
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(side="left", fill="x", expand=True, padx=(scale_px(6, self._ui_scale), 0), ipady=scale_px(5, self._ui_scale))

        helper_row = tk.Frame(body, bg=CARD)
        helper_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            helper_row,
            text="Load cursor",
            bg="#24384d",
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 8), self._ui_scale),
            command=self._fill_exact_from_cursor,
        ).pack(side="left", fill="x", expand=True)
        tk.Button(
            helper_row,
            text="Load center",
            bg="#24384d",
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 8), self._ui_scale),
            command=self._fill_exact_from_center,
        ).pack(side="left", fill="x", expand=True, padx=(scale_px(6, self._ui_scale), 0))

        fire_row = tk.Frame(body, bg=CARD)
        fire_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            fire_row,
            text="Click exact now",
            bg=GREEN,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._arm_click("exact", delay=0.0),
        ).pack(fill="x")
        tk.Button(
            fire_row,
            text="Click exact in 2s",
            bg=LBLUE,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._arm_click("exact", delay=2.0),
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

    def _draw_region_capture_section(self, body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Region Capture",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(14, self._ui_scale), 0))
        tk.Entry(
            body,
            textvariable=self._region_capture_name,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0), ipady=scale_px(5, self._ui_scale))
        profile_row = tk.Frame(body, bg=CARD)
        profile_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.OptionMenu(
            profile_row,
            self._region_template_profile,
            *[value for value, _label in REGION_TEMPLATE_PROFILE_OPTIONS],
        ).pack(side="left", fill="x", expand=True)
        tk.Button(
            profile_row,
            text="Load profile region",
            bg="#24384d",
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 8, "bold"), self._ui_scale),
            command=self._load_profile_region_template,
        ).pack(side="left", padx=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Start region capture",
            bg="#8ecae6",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._start_region_capture("parallelogram"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Start rectangle capture",
            bg="#bde0fe",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._start_region_capture("rectangle"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Capture active region now",
            bg="#ffb703",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=self._capture_active_region,
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Clear active region",
            bg="#24384d",
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 8, "bold"), self._ui_scale),
            command=self._clear_active_region,
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Label(
            body,
            text="Set the region once, then keep using Capture active region now. Parallelogram mode uses bottom-left -> bottom-right -> top-left. Rectangle mode uses top-left -> bottom-right.",
            bg=CARD,
            fg=SUB,
            anchor="w",
            justify="left",
            wraplength=scale_px(PANEL_W - 48, self._ui_scale),
            font=scale_font((FONT, 8), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))

    def _draw_scroll_test_section(self, body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Scroll Test",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(14, self._ui_scale), 0))

        amount_row = tk.Frame(body, bg=CARD)
        amount_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Label(
            amount_row,
            text="Amount",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 8, "bold"), self._ui_scale),
        ).pack(side="left")
        tk.Entry(
            amount_row,
            textvariable=self._scroll_amount,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=10,
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(side="right", fill="x", expand=True, ipady=scale_px(5, self._ui_scale))

        delta_row = tk.Frame(body, bg=CARD)
        delta_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Label(
            delta_row,
            text="Raw Delta",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 8, "bold"), self._ui_scale),
        ).pack(side="left")
        tk.Entry(
            delta_row,
            textvariable=self._scroll_delta,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=10,
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(side="right", fill="x", expand=True, ipady=scale_px(5, self._ui_scale))

        tk.Button(
            body,
            text="Scroll at current cursor",
            bg=YELLOW,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._fire_scroll("cursor"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Scroll at game center",
            bg=GREEN,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._fire_scroll("center"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Scroll at exact coords",
            bg=LBLUE,
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._fire_scroll("exact"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Physical raw delta at current cursor",
            bg="#d6922b",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._fire_raw_scroll("cursor"),
        ).pack(fill="x", pady=(scale_px(10, self._ui_scale), 0))
        tk.Button(
            body,
            text="Physical raw delta at exact coords",
            bg="#c77dff",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._fire_raw_scroll("exact"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Label(
            body,
            text="Amount uses normal wheel notches. Physical Raw Delta tries a real wheel delta first, then falls back to WM_MOUSEWHEEL, so you can test finer values like -30, -60, or -90.",
            bg=CARD,
            fg=SUB,
            anchor="w",
            justify="left",
            wraplength=scale_px(PANEL_W - 48, self._ui_scale),
            font=scale_font((FONT, 8), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))

        tk.Label(
            body,
            text="Drag Test",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(14, self._ui_scale), 0))

        drag_delta_row = tk.Frame(body, bg=CARD)
        drag_delta_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Label(
            drag_delta_row,
            text="Drag dY(px)",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 8, "bold"), self._ui_scale),
        ).pack(side="left")
        tk.Entry(
            drag_delta_row,
            textvariable=self._drag_delta_y,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=10,
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(side="right", fill="x", expand=True, ipady=scale_px(5, self._ui_scale))

        drag_duration_row = tk.Frame(body, bg=CARD)
        drag_duration_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Label(
            drag_duration_row,
            text="Duration(s)",
            bg=CARD,
            fg=TEXT,
            anchor="w",
            font=scale_font((FONT, 8, "bold"), self._ui_scale),
        ).pack(side="left")
        tk.Entry(
            drag_duration_row,
            textvariable=self._drag_duration,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=10,
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(side="right", fill="x", expand=True, ipady=scale_px(5, self._ui_scale))

        drag_mode_row = tk.Frame(body, bg=CARD)
        drag_mode_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        for value, label in [("client", "Drag Client"), ("screen", "Drag Screen"), ("ratio", "Drag Ratio")]:
            tk.Radiobutton(
                drag_mode_row,
                text=label,
                value=value,
                variable=self._drag_coord_mode,
                bg=CARD,
                fg=TEXT,
                selectcolor=BG,
                activebackground=CARD,
                activeforeground=TEXT,
                anchor="w",
                font=scale_font((FONT, 8), self._ui_scale),
            ).pack(side="left", padx=(0, scale_px(8, self._ui_scale)))

        drag_coord_row = tk.Frame(body, bg=CARD)
        drag_coord_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Entry(
            drag_coord_row,
            textvariable=self._drag_coord_x,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=10,
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(side="left", fill="x", expand=True, ipady=scale_px(5, self._ui_scale))
        tk.Entry(
            drag_coord_row,
            textvariable=self._drag_coord_y,
            bg=BG,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            width=10,
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(side="left", fill="x", expand=True, padx=(scale_px(6, self._ui_scale), 0), ipady=scale_px(5, self._ui_scale))

        drag_helper_row = tk.Frame(body, bg=CARD)
        drag_helper_row.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            drag_helper_row,
            text="Load drag cursor",
            bg="#24384d",
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 8), self._ui_scale),
            command=self._fill_drag_exact_from_cursor,
        ).pack(side="left", fill="x", expand=True)
        tk.Button(
            drag_helper_row,
            text="Load drag center",
            bg="#24384d",
            fg=TEXT,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 8), self._ui_scale),
            command=self._fill_drag_exact_from_center,
        ).pack(side="left", fill="x", expand=True, padx=(scale_px(6, self._ui_scale), 0))

        tk.Button(
            body,
            text="Drag at current cursor",
            bg="#ffb703",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._fire_drag_scroll("cursor"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Drag at exact coords",
            bg="#8ecae6",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._fire_drag_scroll("exact"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Button(
            body,
            text="Drag at game center",
            bg="#90be6d",
            fg=BG,
            relief="flat",
            cursor="hand2",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            command=lambda: self._fire_drag_scroll("center"),
        ).pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))
        tk.Label(
            body,
            text="Use a negative dY to drag upward. This is the calibration tool for finding the smallest reliable drag distance.",
            bg=CARD,
            fg=SUB,
            anchor="w",
            justify="left",
            wraplength=scale_px(PANEL_W - 48, self._ui_scale),
            font=scale_font((FONT, 8), self._ui_scale),
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
        margin = scale_px(16, self._ui_scale)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        if rect is None:
            ox = max(0, (sw - panel_w) // 2)
            oy = max(0, (sh - panel_h) // 2)
            self.geometry(f"{panel_w}x{panel_h}+{ox}+{oy}")
            return

        left, top, width, height = rect
        right_x = left + width + margin
        left_x = left - panel_w - margin
        if right_x + panel_w <= sw:
            ox = right_x
        elif left_x >= 0:
            ox = left_x
        else:
            ox = min(max(0, left + max(0, (width - panel_w) // 2)), max(0, sw - panel_w))

        oy = min(max(0, top + margin), max(0, sh - panel_h))
        self.geometry(f"{panel_w}x{panel_h}+{ox}+{oy}")

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

    def _arm_click(self, target_mode: str, delay: float | None = None) -> None:
        if find_target_hwnd() is None:
            self._status_text.set("No target game window selected.")
            return
        self._cancel_countdown()
        self._pending_action = "click"
        self._target_mode = target_mode
        if delay is None:
            delay = 0.25 if target_mode == "center" else 2.0
        self._countdown_deadline = time.monotonic() + max(0.0, delay)
        if delay <= 0:
            self._fire_pending_action()
            return
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

    def _fire_scroll(self, target_mode: str) -> None:
        target = self._resolve_scroll_target(target_mode)
        if target is None:
            return
        hwnd, rect, rx, ry = target
        try:
            amount = int(float(self._scroll_amount.get().strip()))
        except ValueError:
            self._status_text.set("Enter a valid scroll amount first.")
            return

        ok = scroll(hwnd, rect, rx, ry, amount)
        cx, cy = ratio_to_client(rect, rx, ry)
        self._status_text.set(
            f"scroll target={target_mode} amount={amount} "
            f"ratio=({rx:.6f},{ry:.6f}) client=({cx},{cy}) ok={ok}"
        )

    def _resolve_scroll_target(self, target_mode: str) -> tuple[int, tuple[int, int, int, int], float, float] | None:
        hwnd = find_target_hwnd()
        rect = get_window_rect()
        if hwnd is None or rect is None:
            self._status_text.set("Target game window was not found.")
            return None

        width = max(rect[2], 1)
        height = max(rect[3], 1)
        try:
            if target_mode == "center":
                rx = 0.5
                ry = 0.5
            elif target_mode == "exact":
                mode = self._coord_mode.get()
                if mode == "screen":
                    sx = int(float(self._coord_x.get().strip()))
                    sy = int(float(self._coord_y.get().strip()))
                    rx = (sx - rect[0]) / width
                    ry = (sy - rect[1]) / height
                elif mode == "ratio":
                    rx = float(self._coord_x.get().strip())
                    ry = float(self._coord_y.get().strip())
                else:
                    cx = int(float(self._coord_x.get().strip()))
                    cy = int(float(self._coord_y.get().strip()))
                    rx = cx / width
                    ry = cy / height
            else:
                pos = get_cursor_pos()
                if pos is None:
                    self._status_text.set("Failed to read current cursor position.")
                    return None
                rx = (pos[0] - rect[0]) / width
                ry = (pos[1] - rect[1]) / height
        except ValueError:
            self._status_text.set("Enter valid exact coordinates first.")
            return None
        return hwnd, rect, rx, ry

    def _resolve_drag_target(self, target_mode: str) -> tuple[int, tuple[int, int, int, int], float, float] | None:
        hwnd = find_target_hwnd()
        rect = get_window_rect()
        if hwnd is None or rect is None:
            self._status_text.set("Target game window was not found.")
            return None

        width = max(rect[2], 1)
        height = max(rect[3], 1)
        try:
            if target_mode == "center":
                rx = 0.5
                ry = 0.5
            elif target_mode == "exact":
                mode = self._drag_coord_mode.get()
                if mode == "screen":
                    sx = int(float(self._drag_coord_x.get().strip()))
                    sy = int(float(self._drag_coord_y.get().strip()))
                    rx = (sx - rect[0]) / width
                    ry = (sy - rect[1]) / height
                elif mode == "ratio":
                    rx = float(self._drag_coord_x.get().strip())
                    ry = float(self._drag_coord_y.get().strip())
                else:
                    cx = int(float(self._drag_coord_x.get().strip()))
                    cy = int(float(self._drag_coord_y.get().strip()))
                    rx = cx / width
                    ry = cy / height
            else:
                pos = get_cursor_pos()
                if pos is None:
                    self._status_text.set("Failed to read current cursor position.")
                    return None
                rx = (pos[0] - rect[0]) / width
                ry = (pos[1] - rect[1]) / height
        except ValueError:
            self._status_text.set("Enter valid drag coordinates first.")
            return None
        return hwnd, rect, rx, ry

    def _fire_raw_scroll(self, target_mode: str) -> None:
        target = self._resolve_scroll_target(target_mode)
        if target is None:
            return
        hwnd, rect, rx, ry = target
        try:
            wheel_delta = int(float(self._scroll_delta.get().strip()))
        except ValueError:
            self._status_text.set("Enter a valid raw delta first.")
            return
        ok = scroll_raw_delta(hwnd, rect, rx, ry, wheel_delta)
        cx, cy = ratio_to_client(rect, rx, ry)
        self._status_text.set(
            f"raw-scroll target={target_mode} delta={wheel_delta} "
            f"ratio=({rx:.6f},{ry:.6f}) client=({cx},{cy}) ok={ok}"
        )

    def _fire_drag_scroll(self, target_mode: str) -> None:
        target = self._resolve_drag_target(target_mode)
        if target is None:
            return
        hwnd, rect, rx, ry = target
        try:
            delta_y = float(self._drag_delta_y.get().strip())
            duration = float(self._drag_duration.get().strip())
        except ValueError:
            self._status_text.set("Enter valid drag delta and duration first.")
            return

        height = max(rect[3], 1)
        end_ry = ry + (delta_y / height)
        start_ry = max(0.02, min(0.98, ry))
        end_ry = max(0.02, min(0.98, end_ry))
        ok = drag_scroll(
            hwnd,
            rect,
            rx,
            start_ry,
            end_ry,
            delay=0.35,
            duration=max(0.01, duration),
        )
        start_cx, start_cy = ratio_to_client(rect, rx, start_ry)
        end_cx, end_cy = ratio_to_client(rect, rx, end_ry)
        self._status_text.set(
            f"drag target={target_mode} dY={delta_y:.1f}px duration={duration:.2f}s "
            f"start=({start_cx},{start_cy}) end=({end_cx},{end_cy}) "
            f"ratio=({rx:.6f},{start_ry:.6f})->({rx:.6f},{end_ry:.6f}) ok={ok}"
        )

    def _start_region_capture(self, capture_shape: str = "parallelogram") -> None:
        self._ensure_region_capture_overlay()
        hwnd = find_target_hwnd()
        rect = get_window_rect()
        if hwnd is None or rect is None:
            self._status_text.set("Target game window was not found.")
            return
        capture_name = _sanitize_capture_name(
            self._region_capture_name.get(),
            DEFAULT_REGION_CAPTURE_NAME,
        )
        self._region_capture_name.set(capture_name)
        self._active_region_payload = None
        self._region_capture_restore_input = self._visible
        if self._visible:
            self._visible = False
            self.withdraw()
        floating = getattr(self.master, "_overlay", None)
        restore_floating = False
        try:
            restore_floating = bool(floating and getattr(floating, "_visible", False))
        except Exception:
            restore_floating = False
        self._region_capture_restore_floating = restore_floating
        if restore_floating:
            try:
                floating.hide()
            except Exception:
                pass
        if capture_shape == "rectangle":
            self._status_text.set(
                "Rectangle capture started. Click top-left, then bottom-right inside the game window."
            )
        else:
            self._status_text.set(
                "Region capture started. Click bottom-left, bottom-right, then top-left inside the game window."
            )
        self._region_capture_overlay.begin(
            target_rect=rect,
            capture_name=capture_name,
            capture_shape=capture_shape,
        )

    def _capture_active_region(self) -> None:
        self._ensure_region_capture_overlay()
        payload = self._active_region_payload
        hwnd = find_target_hwnd()
        if payload is None:
            self._status_text.set("No active region. Set a region first.")
            return
        if hwnd is None:
            self._status_text.set("Target game window was not found.")
            return
        image = capture_window_background(hwnd, retry=1, normalize=False)
        if image is None:
            self._status_text.set("Failed to capture the target window.")
            return
        current_rect = get_window_rect()
        if current_rect is None:
            self._status_text.set("Target game window bounds are unavailable.")
            return
        capture_name = _sanitize_capture_name(
            self._region_capture_name.get(),
            DEFAULT_REGION_CAPTURE_NAME,
        )
        payload = dict(payload)
        payload["name"] = capture_name
        payload["window_rect"] = {
            "left": current_rect[0],
            "top": current_rect[1],
            "width": current_rect[2],
            "height": current_rect[3],
        }
        ratio_points = payload.get("points_ratio") or []
        payload["points_screen"] = [
            {
                "x": int(round(current_rect[0] + current_rect[2] * float(point["x"]))),
                "y": int(round(current_rect[1] + current_rect[3] * float(point["y"]))),
            }
            for point in ratio_points
        ]
        payload["points_client"] = [
            {
                "x": int(round(current_rect[2] * float(point["x"]))),
                "y": int(round(current_rect[3] * float(point["y"]))),
            }
            for point in ratio_points
        ]
        png_path, json_path = _save_region_capture(image, payload)
        self._region_capture_name.set(capture_name)
        self._status_text.set(f"saved {capture_name} -> {png_path.name}, {json_path.name}")
        self._countdown_text.set("Saved region capture")

    def _load_profile_region_template(self) -> None:
        profile_id = self._region_template_profile.get().strip()
        if not profile_id:
            self._status_text.set("Select a profile first.")
            return
        base = INVENTORY_DETAIL_TEMPLATE_DIR / profile_id
        if not base.exists():
            self._status_text.set(f"Template folder not found: {profile_id}")
            return

        payload = None
        for json_path in sorted(base.glob("*.json")):
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            if payload:
                break
        if not payload:
            self._status_text.set(f"No region json found for {profile_id}.")
            return

        self._active_region_payload = {
            "name": _sanitize_capture_name(
                self._region_capture_name.get(),
                DEFAULT_REGION_CAPTURE_NAME,
            ),
            "window_rect": payload.get("window_rect", {}),
            "points_screen": payload.get("points_screen", []),
            "points_client": payload.get("points_client", []),
            "points_ratio": payload.get("points_ratio", []),
            "shape": payload.get("shape", "rectangle"),
        }
        self._status_text.set(f"Loaded active region from {profile_id}.")
        self._countdown_text.set("Active region ready")

    def _clear_active_region(self) -> None:
        self._active_region_payload = None
        overlay = self._region_capture_overlay
        if overlay and overlay.winfo_exists():
            overlay.clear_active_region()
        self._status_text.set("Cleared active region.")

    def _refresh_active_region_overlay(self) -> None:
        return

    def _on_region_capture_complete(self, ok: bool, message: str, payload: dict | None = None) -> None:
        self._region_capture_restore_floating = False
        if self._region_capture_restore_input:
            self._visible = True
            self.deiconify()
            self.update_idletasks()
            self.lift()
            self._position_windows()
        self._region_capture_restore_input = False
        self._status_text.set(message)
        if ok:
            self._active_region_payload = payload
            if payload is not None:
                definition_path = _save_region_definition(payload)
                overlay = self._region_capture_overlay
                if overlay and overlay.winfo_exists():
                    overlay.suspend()
                self._status_text.set(f"{message} ({definition_path.name})")
            self._countdown_text.set("Active region ready")

    def _fill_drag_exact_from_cursor(self) -> None:
        pos = get_cursor_pos()
        rect = get_window_rect()
        if pos is None or rect is None:
            self._status_text.set("Failed to read cursor or game window.")
            return
        self._set_drag_inputs_from_screen(pos[0], pos[1], rect)

    def _fill_drag_exact_from_center(self) -> None:
        pos = self._game_center()
        rect = get_window_rect()
        if pos is None or rect is None:
            self._status_text.set("Failed to read game center.")
            return
        self._set_drag_inputs_from_screen(pos[0], pos[1], rect)

    def _set_drag_inputs_from_screen(
        self,
        sx: int,
        sy: int,
        rect: tuple[int, int, int, int],
    ) -> None:
        left, top, width, height = rect
        width = max(width, 1)
        height = max(height, 1)
        cx = sx - left
        cy = sy - top
        mode = self._drag_coord_mode.get()
        if mode == "screen":
            self._drag_coord_x.set(str(sx))
            self._drag_coord_y.set(str(sy))
        elif mode == "ratio":
            self._drag_coord_x.set(f"{cx / width:.6f}")
            self._drag_coord_y.set(f"{cy / height:.6f}")
        else:
            self._drag_coord_x.set(str(cx))
            self._drag_coord_y.set(str(cy))
        self._status_text.set(
            f"Loaded drag {mode} coords from screen=({sx},{sy}) client=({cx},{cy})"
        )

    def _fire_click(self) -> None:
        hwnd = find_target_hwnd()
        if hwnd is None:
            self._status_text.set("Target game window was not found.")
            self._countdown_text.set("No pending action")
            return

        if self._target_mode == "center":
            pos = self._game_center()
        elif self._target_mode == "exact":
            self._fire_exact_click(hwnd)
            self._countdown_text.set("No pending action")
            return
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

    def _fill_exact_from_cursor(self) -> None:
        pos = get_cursor_pos()
        rect = get_window_rect()
        if pos is None or rect is None:
            self._status_text.set("Failed to read cursor or game window.")
            return
        self._set_exact_inputs_from_screen(pos[0], pos[1], rect)

    def _fill_exact_from_center(self) -> None:
        pos = self._game_center()
        rect = get_window_rect()
        if pos is None or rect is None:
            self._status_text.set("Failed to read game center.")
            return
        self._set_exact_inputs_from_screen(pos[0], pos[1], rect)

    def _set_exact_inputs_from_screen(
        self,
        sx: int,
        sy: int,
        rect: tuple[int, int, int, int],
    ) -> None:
        left, top, width, height = rect
        width = max(width, 1)
        height = max(height, 1)
        cx = sx - left
        cy = sy - top
        mode = self._coord_mode.get()
        if mode == "screen":
            self._coord_x.set(str(sx))
            self._coord_y.set(str(sy))
        elif mode == "ratio":
            self._coord_x.set(f"{cx / width:.6f}")
            self._coord_y.set(f"{cy / height:.6f}")
        else:
            self._coord_x.set(str(cx))
            self._coord_y.set(str(cy))
        self._status_text.set(
            f"Loaded {mode} coords from screen=({sx},{sy}) client=({cx},{cy})"
        )

    def _fire_exact_click(self, hwnd: int) -> None:
        method = self._click_method.get()
        mode = self._coord_mode.get()
        rect = get_window_rect()
        try:
            if mode == "screen":
                sx = int(float(self._coord_x.get().strip()))
                sy = int(float(self._coord_y.get().strip()))
                ok = debug_click_screen(
                    hwnd,
                    sx,
                    sy,
                    method=method,
                    label=f"input_test:screen:{method}",
                )
                self._status_text.set(
                    f"method={method} target=screen screen=({sx},{sy}) ok={ok}"
                )
                return

            if rect is None:
                self._status_text.set("Target game window bounds are unavailable.")
                return

            if mode == "ratio":
                rx = float(self._coord_x.get().strip())
                ry = float(self._coord_y.get().strip())
                cx, cy = ratio_to_client(rect, rx, ry)
                ok = debug_click_client(
                    hwnd,
                    cx,
                    cy,
                    method=method,
                    label=f"input_test:ratio:{method}",
                )
                self._status_text.set(
                    f"method={method} target=ratio ratio=({rx:.6f},{ry:.6f}) client=({cx},{cy}) ok={ok}"
                )
                return

            cx = int(float(self._coord_x.get().strip()))
            cy = int(float(self._coord_y.get().strip()))
            ok = debug_click_client(
                hwnd,
                cx,
                cy,
                method=method,
                label=f"input_test:client:{method}",
            )
            self._status_text.set(
                f"method={method} target=client client=({cx},{cy}) ok={ok}"
            )
        except ValueError:
            self._status_text.set("Enter valid exact coordinates first.")

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

    def hide(self) -> None:
        if self._visible:
            self._visible = False
            self._cancel_countdown()
            try:
                overlay = self._region_capture_overlay
                if overlay and overlay.winfo_exists():
                    if getattr(overlay, "_selection_mode", False):
                        overlay.cancel("hidden")
                    else:
                        overlay.suspend()
            except Exception:
                pass
            self.withdraw()

    def destroy(self) -> None:
        self._stop_event.set()
        self._cancel_countdown()
        try:
            self._region_capture_overlay.destroy()
        except Exception:
            pass
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        super().destroy()
