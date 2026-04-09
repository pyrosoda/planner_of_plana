"""
Startup profile selection dialog.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from core.config import normalize_profile_name


class ProfileDialog(tk.Toplevel):
    def __init__(self, master, profiles: list[str], last_profile: str | None = None):
        super().__init__(master)
        self.title("프로필 선택")
        self.resizable(False, False)
        self.configure(bg="#101722")
        self.result: str | None = None
        self._profiles = sorted(profiles, key=str.casefold)

        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        width = 420
        height = 360
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{width}x{height}+{(sw-width)//2}+{(sh-height)//2}")

        self._build(last_profile)
        self.bind("<Return>", lambda _e: self._confirm_selection())
        self.bind("<Escape>", lambda _e: self._cancel())

    def _build(self, last_profile: str | None) -> None:
        wrap = tk.Frame(self, bg="#101722", padx=18, pady=18)
        wrap.pack(fill="both", expand=True)

        tk.Label(
            wrap,
            text="사용자 프로필",
            bg="#101722",
            fg="#e4f1ff",
            font=("Malgun Gothic", 15, "bold"),
        ).pack(anchor="w")

        tk.Label(
            wrap,
            text="기존 닉네임을 선택하거나 새 닉네임을 입력해 주세요.",
            bg="#101722",
            fg="#8aa4bf",
            font=("Malgun Gothic", 9),
        ).pack(anchor="w", pady=(6, 14))

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
            font=("Malgun Gothic", 10),
            height=10,
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
        entry_frame.pack(fill="x", pady=(14, 10))
        tk.Label(
            entry_frame,
            text="새 닉네임",
            bg="#101722",
            fg="#8aa4bf",
            font=("Malgun Gothic", 9),
        ).pack(anchor="w")
        self._entry = tk.Entry(
            entry_frame,
            bg="#162130",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=("Malgun Gothic", 11),
        )
        self._entry.pack(fill="x", pady=(6, 0), ipady=6)

        button_row = tk.Frame(wrap, bg="#101722")
        button_row.pack(fill="x", pady=(8, 0))

        tk.Button(
            button_row,
            text="선택",
            command=self._confirm_selection,
            bg="#2d8cff",
            fg="#ffffff",
            relief="flat",
            padx=18,
            pady=8,
        ).pack(side="right")

        tk.Button(
            button_row,
            text="취소",
            command=self._cancel,
            bg="#233244",
            fg="#d2dfed",
            relief="flat",
            padx=18,
            pady=8,
        ).pack(side="right", padx=(0, 8))

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
