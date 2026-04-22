from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox

import core.student_meta as student_meta
from core.student_order import ordered_student_ids
from gui.ui_scale import get_ui_scale, scale_font, scale_px


@dataclass(slots=True)
class FastScanConfigResult:
    saved: bool
    student_ids: list[str]


class FastScanConfigDialog(tk.Toplevel):
    def __init__(
        self,
        master,
        *,
        initial_selected_ids: list[str],
        saved_student_count: int,
    ) -> None:
        super().__init__(master)
        self.title("빠른 스캔 목록 설정")
        self.configure(bg="#101722")
        self.result = FastScanConfigResult(saved=False, student_ids=[])
        self._ui_scale = get_ui_scale(self, base_width=860, base_height=840)
        self._saved_student_count = saved_student_count
        self._search = tk.StringVar(value="")
        self._selected: dict[str, tk.BooleanVar] = {
            student_id: tk.BooleanVar(value=student_id in set(initial_selected_ids))
            for student_id in student_meta.all_ids()
        }
        self._rows: list[tuple[str, tk.Frame]] = []
        self._count_label: tk.Label | None = None

        if master is not None:
            try:
                if bool(master.winfo_viewable()):
                    self.transient(master)
            except Exception:
                pass

        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()
        self._show_dialog()

    def _show_dialog(self) -> None:
        self.update_idletasks()
        width = scale_px(820, self._ui_scale)
        height = scale_px(780, self._ui_scale)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{width}x{height}+{(sw-width)//2}+{(sh-height)//2}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(250, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _build(self) -> None:
        wrap = tk.Frame(self, bg="#101722", padx=scale_px(18, self._ui_scale), pady=scale_px(18, self._ui_scale))
        wrap.pack(fill="both", expand=True)

        tk.Label(
            wrap,
            text="빠른 스캔 기준 목록 편집",
            bg="#101722",
            fg="#e4f1ff",
            font=scale_font(("Malgun Gothic", 15, "bold"), self._ui_scale),
        ).pack(anchor="w")

        base_text = (
            "학생별로 토글해서 빠른 스캔 기준 목록을 저장합니다.\n"
            "저장 데이터가 있으면 그 수보다 적게 저장할 수 없고, 더 많으면 추가 학생이 생겼는지 다시 확인합니다."
        )
        tk.Label(
            wrap,
            text=base_text,
            bg="#101722",
            fg="#8aa4bf",
            justify="left",
            wraplength=scale_px(760, self._ui_scale),
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(anchor="w", pady=(scale_px(6, self._ui_scale), scale_px(12, self._ui_scale)))

        head = tk.Frame(wrap, bg="#162130", padx=scale_px(12, self._ui_scale), pady=scale_px(10, self._ui_scale))
        head.pack(fill="x")
        self._count_label = tk.Label(
            head,
            text="",
            bg="#162130",
            fg="#d6e6f5",
            anchor="w",
            font=scale_font(("Malgun Gothic", 10, "bold"), self._ui_scale),
        )
        self._count_label.pack(side="left")
        tk.Label(
            head,
            text=f"저장 데이터 학생 수: {self._saved_student_count}명",
            bg="#162130",
            fg="#8aa4bf",
            anchor="e",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(side="right")

        search_wrap = tk.Frame(wrap, bg="#101722")
        search_wrap.pack(fill="x", pady=(scale_px(12, self._ui_scale), scale_px(8, self._ui_scale)))
        tk.Label(
            search_wrap,
            text="검색",
            bg="#101722",
            fg="#8aa4bf",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(side="left")
        entry = tk.Entry(
            search_wrap,
            textvariable=self._search,
            bg="#162130",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
        )
        entry.pack(side="left", fill="x", expand=True, padx=(scale_px(8, self._ui_scale), 0), ipady=scale_px(6, self._ui_scale))
        self._search.trace_add("write", lambda *_args: self._apply_filter())

        canvas_wrap = tk.Frame(wrap, bg="#101722")
        canvas_wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_wrap, bg="#162130", highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)

        inner = tk.Frame(canvas, bg="#162130")
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(inner_window, width=event.width),
        )

        for student_id in ordered_student_ids(student_meta.all_ids()):
            row = tk.Frame(inner, bg="#162130")
            row.pack(fill="x", padx=scale_px(8, self._ui_scale), pady=(0, scale_px(2, self._ui_scale)))
            check = tk.Checkbutton(
                row,
                text=student_meta.display_name(student_id),
                variable=self._selected[student_id],
                bg="#162130",
                fg="#e4f1ff",
                activebackground="#162130",
                activeforeground="#e4f1ff",
                selectcolor="#203043",
                command=self._refresh_count,
                anchor="w",
                justify="left",
                font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            )
            check.pack(fill="x")
            self._rows.append((student_id, row))

        actions = tk.Frame(wrap, bg="#101722")
        actions.pack(fill="x", pady=(scale_px(10, self._ui_scale), 0))
        tk.Button(
            actions,
            text="전체 선택",
            command=self._select_all,
            bg="#233244",
            fg="#d2dfed",
            relief="flat",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
            padx=scale_px(14, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
        ).pack(side="left")
        tk.Button(
            actions,
            text="모두 해제",
            command=self._clear_all,
            bg="#233244",
            fg="#d2dfed",
            relief="flat",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
            padx=scale_px(14, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
        ).pack(side="left", padx=(scale_px(8, self._ui_scale), 0))
        tk.Button(
            actions,
            text="초기 선택 복원",
            command=self._restore_saved_like_default,
            bg="#233244",
            fg="#d2dfed",
            relief="flat",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
            padx=scale_px(14, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
        ).pack(side="left", padx=(scale_px(8, self._ui_scale), 0))

        buttons = tk.Frame(wrap, bg="#101722")
        buttons.pack(fill="x", pady=(scale_px(16, self._ui_scale), 0))
        tk.Button(
            buttons,
            text="취소",
            command=self._cancel,
            bg="#233244",
            fg="#d2dfed",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            padx=scale_px(16, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        ).pack(side="right")
        tk.Button(
            buttons,
            text="저장",
            command=self._save,
            bg="#25a55f",
            fg="#ffffff",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10, "bold"), self._ui_scale),
            padx=scale_px(16, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        ).pack(side="right", padx=(0, scale_px(8, self._ui_scale)))

        self._default_selected_ids = self._selected_ids()
        self._refresh_count()
        self._apply_filter()

    def _selected_ids(self) -> list[str]:
        return [student_id for student_id, value in self._selected.items() if value.get()]

    def _refresh_count(self) -> None:
        if self._count_label is None:
            return
        selected_count = len(self._selected_ids())
        self._count_label.configure(text=f"선택 학생 수: {selected_count}명")

    def _apply_filter(self) -> None:
        query = self._search.get().strip().casefold()
        for student_id, row in self._rows:
            visible = not query or query in student_meta.search_blob(student_id)
            if visible:
                row.pack(fill="x", padx=scale_px(8, self._ui_scale), pady=(0, scale_px(2, self._ui_scale)))
            else:
                row.pack_forget()

    def _clear_all(self) -> None:
        for value in self._selected.values():
            value.set(False)
        self._refresh_count()

    def _select_all(self) -> None:
        for value in self._selected.values():
            value.set(True)
        self._refresh_count()

    def _restore_saved_like_default(self) -> None:
        selected = set(self._default_selected_ids)
        for student_id, value in self._selected.items():
            value.set(student_id in selected)
        self._refresh_count()

    def _save(self) -> None:
        selected_ids = ordered_student_ids(self._selected_ids())
        selected_count = len(selected_ids)
        if selected_count <= 0:
            messagebox.showwarning("빠른 스캔 목록", "최소 한 명 이상 선택해 주세요.", parent=self)
            return

        if self._saved_student_count > 0 and selected_count < self._saved_student_count:
            messagebox.showwarning(
                "빠른 스캔 목록",
                (
                    "저장 데이터 학생 수보다 적은 목록은 저장할 수 없습니다.\n\n"
                    f"저장 데이터: {self._saved_student_count}명\n"
                    f"선택 목록: {selected_count}명"
                ),
                parent=self,
            )
            return

        if self._saved_student_count > 0 and selected_count > self._saved_student_count:
            confirmed = messagebox.askyesno(
                "빠른 스캔 목록",
                (
                    "저장 데이터보다 많은 학생이 선택되었습니다.\n"
                    "추가 학생 데이터가 실제로 생긴 것이 맞나요?\n\n"
                    f"저장 데이터: {self._saved_student_count}명\n"
                    f"선택 목록: {selected_count}명"
                ),
                parent=self,
            )
            if not confirmed:
                return

        self.result = FastScanConfigResult(saved=True, student_ids=selected_ids)
        self.destroy()

    def _cancel(self) -> None:
        self.result = FastScanConfigResult(saved=False, student_ids=[])
        self.destroy()


def edit_fast_scan_config(
    master,
    *,
    initial_selected_ids: list[str],
    saved_student_count: int,
) -> FastScanConfigResult:
    dialog = FastScanConfigDialog(
        master,
        initial_selected_ids=initial_selected_ids,
        saved_student_count=saved_student_count,
    )
    master.wait_window(dialog)
    return dialog.result
