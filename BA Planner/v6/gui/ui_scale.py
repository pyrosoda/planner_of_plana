from __future__ import annotations

import os
import tkinter as tk


def get_ui_scale(
    root: tk.Misc,
    *,
    base_width: int | None = None,
    base_height: int = 1080,
    min_scale: float = 0.8,
    max_scale: float = 1.8,
) -> float:
    """Compute a stable UI scale from screen size.

    Allows manual override via BA_UI_SCALE env (float).
    When a base width is supplied, the scale fits within both axes.
    """
    raw = os.getenv("BA_UI_SCALE")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass

    try:
        screen_h = max(1, int(root.winfo_screenheight()))
    except Exception:
        screen_h = base_height

    scale = screen_h / float(base_height)
    if base_width:
        try:
            screen_w = max(1, int(root.winfo_screenwidth()))
        except Exception:
            screen_w = base_width
        scale = min(scale, screen_w / float(base_width))
    return max(min_scale, min(max_scale, scale))


def scale_px(value: int | float, scale: float) -> int:
    return max(1, int(round(float(value) * scale)))


def scale_font(font: tuple, scale: float) -> tuple:
    if len(font) < 2:
        return font
    family, size, *rest = font
    try:
        size_i = int(size)
    except Exception:
        return font
    return (family, max(1, int(round(size_i * scale))), *rest)
