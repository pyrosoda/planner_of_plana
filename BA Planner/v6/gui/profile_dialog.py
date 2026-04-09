"""
Startup profile selection dialog.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from core.config import delete_profile, normalize_profile_name
from gui.ui_scale import get_ui_scale, scale_font, scale_px


class ProfileDialog(tk.Toplevel):
    def __init__(self, master, profiles: list[str], last_profile: str | None = None):
        super().__init__(master)
        self.title("Profile Select")
        self.resizable(False, False)
        self.configure(bg="#101722")
        self.result: str | None = None
        self._profiles = sorted(profiles, key=str.casefold)
        self._ui_scale = get_ui_scale(self, base_width=560, base_height=520)

        if master is not None:
            try:
                if bool(master.winfo_viewable()):
                    self.transient(master)
            except Exception:
                pass

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        width = scale_px(500, self._ui_scale)
        height = scale_px(470, self._ui_scale)
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
        wrap = tk.Frame(
            self,
            bg="#101722",
            padx=scale_px(18, self._ui_scale),
            pady=scale_px(18, self._ui_scale),
        )
        wrap.pack(fill="both", expand=True)

        tk.Label(
            wrap,
            text="Choose a profile",
            bg="#101722",
            fg="#e4f1ff",
            font=scale_font(("Malgun Gothic", 15, "bold"), self._ui_scale),
        ).pack(anchor="w")

        tk.Label(
            wrap,
            text="Select an existing profile, or type a new name below to create one.",
            bg="#101722",
            fg="#8aa4bf",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
            justify="left",
            wraplength=scale_px(430, self._ui_scale),
        ).pack(anchor="w", pady=(scale_px(6, self._ui_scale), scale_px(12, self._ui_scale)))

        list_container = tk.Frame(wrap, bg="#101722")
        list_container.pack(fill="x")

        tk.Label(
            list_container,
            text="Existing profiles",
            bg="#101722",
            fg="#8aa4bf",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(anchor="w")

        list_frame = tk.Frame(list_container, bg="#101722")
        list_frame.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))

        self._listbox = tk.Listbox(
            list_frame,
            bg="#162130",
            fg="#e4f1ff",
            selectbackground="#2d8cff",
            selectforeground="#ffffff",
            activestyle="none",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            height=6,
            exportselection=False,
        )
        self._listbox.pack(side="left", fill="x", expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)
        self._listbox.bind("<Double-Button-1>", lambda _e: self._confirm_selection())

        scroll = tk.Scrollbar(list_frame, command=self._listbox.yview)
        scroll.pack(side="right", fill="y")
        self._listbox.configure(yscrollcommand=scroll.set)

        entry_frame = tk.Frame(wrap, bg="#101722")
        entry_frame.pack(fill="x", pady=(scale_px(16, self._ui_scale), 0))

        tk.Label(
            entry_frame,
            text="New profile name",
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
        self._entry.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0), ipady=scale_px(8, self._ui_scale))

        tk.Label(
            entry_frame,
            text="Typing a new name and pressing OK will create that profile.",
            bg="#101722",
            fg="#6f8aa5",
            font=scale_font(("Malgun Gothic", 8), self._ui_scale),
            justify="left",
            wraplength=scale_px(430, self._ui_scale),
        ).pack(anchor="w", pady=(scale_px(6, self._ui_scale), 0))

        button_row = tk.Frame(wrap, bg="#101722")
        button_row.pack(fill="x", pady=(scale_px(18, self._ui_scale), 0))

        self._delete_btn = tk.Button(
            button_row,
            text="Delete",
            command=self._delete_selected,
            bg="#80333b",
            fg="#ffffff",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            padx=scale_px(18, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        )
        self._delete_btn.pack(side="left")

        tk.Button(
            button_row,
            text="OK",
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
            text="Cancel",
            command=self._cancel,
            bg="#233244",
            fg="#d2dfed",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            padx=scale_px(18, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        ).pack(side="right", padx=(0, scale_px(8, self._ui_scale)))

        self._populate_profiles(last_profile)

        self._entry.focus_set()
        self._entry.selection_range(0, "end")

    def _populate_profiles(self, preferred_name: str | None = None) -> None:
        self._listbox.configure(state="normal")
        self._listbox.delete(0, "end")

        if self._profiles:
            for profile in self._profiles:
                self._listbox.insert("end", profile)
            self._delete_btn_state("normal")

            selected_name = None
            if preferred_name:
                lowered = [item.casefold() for item in self._profiles]
                if preferred_name.casefold() in lowered:
                    idx = lowered.index(preferred_name.casefold())
                    selected_name = self._profiles[idx]
                    self._listbox.selection_set(idx)
                    self._listbox.see(idx)
            if selected_name is None:
                self._listbox.selection_set(0)
                selected_name = self._profiles[0]

            self._entry.delete(0, "end")
            self._entry.insert(0, selected_name)
        else:
            self._listbox.insert("end", "No profiles yet. Enter a new name below.")
            self._listbox.configure(state="disabled")
            self._delete_btn_state("disabled")
            self._entry.delete(0, "end")
            self._entry.insert(0, "Default Profile")

    def _delete_btn_state(self, state: str) -> None:
        if hasattr(self, "_delete_btn"):
            self._delete_btn.configure(state=state)

    def _on_select(self, _event=None) -> None:
        selection = self._listbox.curselection()
        if not selection or not self._profiles:
            return
        name = self._listbox.get(selection[0])
        self._entry.delete(0, "end")
        self._entry.insert(0, name)

    def _delete_selected(self) -> None:
        selection = self._listbox.curselection()
        if not selection or not self._profiles:
            return

        name = self._listbox.get(selection[0])
        confirmed = messagebox.askyesno(
            "Delete Profile",
            f"Delete profile '{name}'?\n\nThis will remove its saved data and cannot be undone.",
            parent=self,
        )
        if not confirmed:
            return

        try:
            deleted = delete_profile(name)
        except Exception as exc:
            messagebox.showerror(
                "Delete Profile",
                f"Failed to delete profile '{name}'.\n\n{exc}",
                parent=self,
            )
            return

        if not deleted:
            messagebox.showwarning(
                "Delete Profile",
                f"Profile '{name}' was not found.",
                parent=self,
            )
            return

        self._profiles = [profile for profile in self._profiles if profile.casefold() != name.casefold()]
        preferred_name = self._profiles[0] if self._profiles else None
        self._populate_profiles(preferred_name)
        self._entry.focus_set()
        self._entry.selection_range(0, "end")

    def _confirm_selection(self) -> None:
        name = normalize_profile_name(self._entry.get())
        if not name:
            messagebox.showwarning("Profile Select", "Please enter a profile name.", parent=self)
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
