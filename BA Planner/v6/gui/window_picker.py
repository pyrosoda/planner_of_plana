"""
Window selection dialog.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.capture import get_all_windows, get_target_info, set_target_window
from gui.ui_scale import get_ui_scale, scale_font, scale_px

BG = "#0d1b2a"
CARD = "#152435"
CARD2 = "#1a2e40"
BLUE = "#1a6fad"
LBLUE = "#4aa8e0"
GREEN = "#3dbf7a"
TEXT = "#e8f4fd"
SUB = "#7ab3d4"
FONT = "Malgun Gothic"

BA_KEYWORDS = ["blue archive", "bluearchive"]


class WindowPicker(tk.Toplevel):
    def __init__(
        self,
        master,
        on_select: Callable[[int, str], None],
        on_cancel: Callable,
    ):
        super().__init__(master)
        self.on_select = on_select
        self.on_cancel = on_cancel
        self._windows: list[dict] = []
        self._selected_idx: int | None = None

        self.title("Window Select")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self._ui_scale = get_ui_scale(self, base_width=640, base_height=560)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = scale_px(560, self._ui_scale)
        h = scale_px(500, self._ui_scale)
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._build_ui()
        self._refresh()

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.grab_set()
        self.focus_force()

    def _build_ui(self) -> None:
        wrap = tk.Frame(
            self,
            bg=BG,
            padx=scale_px(16, self._ui_scale),
            pady=scale_px(16, self._ui_scale),
        )
        wrap.pack(fill="both", expand=True)

        header = tk.Frame(wrap, bg=BLUE, height=scale_px(48, self._ui_scale))
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="Select the Blue Archive window",
            bg=BLUE,
            fg=TEXT,
            font=scale_font((FONT, 13, "bold"), self._ui_scale),
        ).pack(expand=True)

        tk.Label(
            wrap,
            text="Pick a running window from the list below. The highlighted items are likely Blue Archive.",
            bg=BG,
            fg=SUB,
            justify="left",
            wraplength=scale_px(500, self._ui_scale),
            font=scale_font((FONT, 9), self._ui_scale),
        ).pack(anchor="w", pady=(scale_px(10, self._ui_scale), scale_px(10, self._ui_scale)))

        self._cur_var = tk.StringVar(value="Current: none")
        current_frame = tk.Frame(wrap, bg=CARD, height=scale_px(38, self._ui_scale))
        current_frame.pack(fill="x", pady=(0, scale_px(10, self._ui_scale)))
        current_frame.pack_propagate(False)
        tk.Label(
            current_frame,
            textvariable=self._cur_var,
            bg=CARD,
            fg=GREEN,
            anchor="w",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
        ).pack(fill="both", padx=scale_px(10, self._ui_scale))

        list_shell = tk.Frame(wrap, bg=CARD)
        list_shell.pack(fill="both", expand=True)

        list_header = tk.Frame(list_shell, bg=CARD2, height=scale_px(28, self._ui_scale))
        list_header.pack(fill="x")
        list_header.pack_propagate(False)
        tk.Label(
            list_header,
            text="Window title",
            bg=CARD2,
            fg=LBLUE,
            anchor="w",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
        ).pack(side="left", fill="x", expand=True, padx=scale_px(8, self._ui_scale))
        tk.Label(
            list_header,
            text="Size",
            bg=CARD2,
            fg=LBLUE,
            width=12,
            anchor="w",
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
        ).pack(side="right", padx=scale_px(8, self._ui_scale))

        list_frame = tk.Frame(list_shell, bg=CARD)
        list_frame.pack(fill="both", expand=True)

        scroll = tk.Scrollbar(list_frame)
        scroll.pack(side="right", fill="y")

        self._listbox = tk.Listbox(
            list_frame,
            bg=CARD,
            fg=TEXT,
            selectbackground=BLUE,
            selectforeground=TEXT,
            activestyle="none",
            relief="flat",
            exportselection=False,
            yscrollcommand=scroll.set,
            font=scale_font((FONT, 9), self._ui_scale),
            height=10,
        )
        self._listbox.pack(side="left", fill="both", expand=True)
        scroll.config(command=self._listbox.yview)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)
        self._listbox.bind("<Double-Button-1>", lambda _e: self._confirm())

        btn_row = tk.Frame(wrap, bg=BG)
        btn_row.pack(fill="x", pady=(scale_px(12, self._ui_scale), 0))

        tk.Button(
            btn_row,
            text="Refresh",
            bg=CARD,
            fg=SUB,
            relief="flat",
            cursor="hand2",
            padx=scale_px(12, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
            font=scale_font((FONT, 9), self._ui_scale),
            command=self._refresh,
        ).pack(side="left")

        tk.Button(
            btn_row,
            text="Cancel",
            bg=CARD,
            fg=SUB,
            relief="flat",
            cursor="hand2",
            padx=scale_px(12, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
            font=scale_font((FONT, 10), self._ui_scale),
            command=self._cancel,
        ).pack(side="right")

        self._confirm_btn = tk.Button(
            btn_row,
            text="Use selected window",
            bg=GREEN,
            fg=BG,
            relief="flat",
            cursor="hand2",
            state="disabled",
            padx=scale_px(12, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
            command=self._confirm,
        )
        self._confirm_btn.pack(side="right", padx=(0, scale_px(8, self._ui_scale)))

    def _refresh(self) -> None:
        self._windows = get_all_windows()
        self._selected_idx = None
        self._confirm_btn.configure(state="disabled")
        self._listbox.delete(0, "end")

        for index, win in enumerate(self._windows):
            title = win["title"]
            size = win["size"]
            is_ba = any(keyword in title.lower() for keyword in BA_KEYWORDS)
            label = f"{title[:48]:48s}  {size}"
            self._listbox.insert("end", label)
            if is_ba:
                self._listbox.itemconfig(index, fg=GREEN)

        hwnd, title = get_target_info()
        self._cur_var.set(f"Current: {title}" if hwnd and title else "Current: none")

    def _on_select(self, _event=None) -> None:
        selection = self._listbox.curselection()
        if not selection:
            self._selected_idx = None
            self._confirm_btn.configure(state="disabled")
            return

        self._selected_idx = selection[0]
        title = self._windows[self._selected_idx]["title"]
        self._cur_var.set(f"Selected: {title}")
        self._confirm_btn.configure(state="normal")

    def _confirm(self) -> None:
        if self._selected_idx is None:
            return

        win = self._windows[self._selected_idx]
        set_target_window(win["hwnd"], win["title"])
        try:
            self.destroy()
        finally:
            self.on_select(win["hwnd"], win["title"])

    def _cancel(self) -> None:
        try:
            self.destroy()
        finally:
            self.on_cancel()
