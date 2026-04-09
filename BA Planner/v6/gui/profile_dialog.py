"""
Startup profile selection dialog.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from core.config import normalize_profile_name
from gui.ui_scale import get_ui_scale, scale_font, scale_px


class ProfileDialog(tk.Toplevel):
    def __init__(self, master, profiles: list[str], last_profile: str | None = None):
        super().__init__(master)
        self.title("프로필 선택")
        self.resizable(False, False)
        self.configure(bg="#101722")
        self.result: str | None = None
        self._profiles = sorted(profiles, key=str.casefold)
        self._ui_scale = get_ui_scale(self, base_width=520, base_height=420)

        if master is not None and str(master.state()) != "withdrawn":
            self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        width = scale_px(420, self._ui_scale)
        height = scale_px(360, self._ui_scale)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{width}x{height}+{(sw-width)//2}+{(sh-height)//2}")

        self._build(last_profile)
        self.bind("<Return>", lambda _e: self._confirm_selection())
        self.bind("<Escape>", lambda _e: self._cancel())
        self._show_dialog()

    def _show_dialog(self) -> None:
        self.update_idletasks()
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(250, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _build(self, last_profile: str | None) -> None:
        wrap = tk.Frame(self, bg="#101722", padx=scale_px(18, self._ui_scale), pady=scale_px(18, self._ui_scale))
        wrap.pack(fill="both", expand=True)

        tk.Label(
            wrap,
            text="사용자 프로필",
            bg="#101722",
            fg="#e4f1ff",
            font=scale_font(("Malgun Gothic", 15, "bold"), self._ui_scale),
        ).pack(anchor="w")

        tk.Label(
            wrap,
            text="기존 닉네임을 선택하거나 새 닉네임을 입력해 주세요.",
            bg="#101722",
            fg="#8aa4bf",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(anchor="w", pady=(scale_px(6, self._ui_scale), scale_px(14, self._ui_scale)))

        list_frame = tk.Frame(wrap, bg="#101722")
        list_frame.pack(fill="both", expand=True)

        self._listbox = tk.Listbox(
            list_frame,
            bg="#162130",
            fg="#e4f1ff",
            selectbackground="#2d8cff",
            selectforeground="#ffffff",
            activestyle="none",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            height=max(8, scale_px(10, self._ui_scale)),
        )
        self._listbox.pack(side="left", fill="both", expand=True)
        self._listbox.bind("<Double-Button-1>", lambda _e: self._confirm_selection())
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        scroll = tk.Scrollbar(list_frame, command=self._listbox.yview)
        scroll.pack(side="right", fill="y")
        self._listbox.configure(yscrollcommand=scroll.set)

        for profile in self._profiles:
            self._listbox.insert("end", profile)

        entry_frame = tk.Frame(wrap, bg="#101722")
        entry_frame.pack(fill="x", pady=(scale_px(14, self._ui_scale), scale_px(10, self._ui_scale)))
        tk.Label(
            entry_frame,
            text="새 닉네임",
            bg="#101722",
            fg="#8aa4bf",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(anchor="w")
        self._entry = tk.Entry(
            entry_frame,
            bg="#162130",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=scale_font(("Malgun Gothic", 11), self._ui_scale),
        )
        self._entry.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0), ipady=scale_px(6, self._ui_scale))

        button_row = tk.Frame(wrap, bg="#101722")
        button_row.pack(fill="x", pady=(scale_px(8, self._ui_scale), 0))

        tk.Button(
            button_row,
            text="선택",
            command=self._confirm_selection,
            bg="#2d8cff",
            fg="#ffffff",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10, "bold"), self._ui_scale),
            padx=scale_px(18, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        ).pack(side="right")

        tk.Button(
            button_row,
            text="취소",
            command=self._cancel,
            bg="#233244",
            fg="#d2dfed",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            padx=scale_px(18, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        ).pack(side="right", padx=(0, scale_px(8, self._ui_scale)))

        if last_profile:
            lowered = [item.casefold() for item in self._profiles]
            if last_profile.casefold() in lowered:
                idx = lowered.index(last_profile.casefold())
                self._listbox.selection_set(idx)
                self._listbox.see(idx)
                self._entry.insert(0, self._profiles[idx])
        elif self._profiles:
            self._listbox.selection_set(0)
            self._entry.insert(0, self._profiles[0])

        self._entry.focus_set()

    def _on_select(self, _event=None) -> None:
        selection = self._listbox.curselection()
        if not selection:
            return
        name = self._listbox.get(selection[0])
        self._entry.delete(0, "end")
        self._entry.insert(0, name)

    def _confirm_selection(self) -> None:
        name = normalize_profile_name(self._entry.get())
        if not name:
            messagebox.showwarning("프로필 선택", "닉네임을 입력해 주세요.", parent=self)
            return
        self.result = name
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def choose_profile(master, profiles: list[str], last_profile: str | None = None) -> str | None:
    dialog = ProfileDialog(master, profiles, last_profile=last_profile)
    master.wait_window(dialog)
    return dialog.result
