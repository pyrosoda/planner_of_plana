from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tkinter as tk

from gui.ui_scale import get_ui_scale, scale_font, scale_px

try:
    from PIL import Image, ImageOps, ImageTk

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


BASE_DIR = Path(__file__).resolve().parent.parent
PORTRAIT_DIR = BASE_DIR / "templates" / "students_portraits"
POLI_BG_DIR = BASE_DIR / "templates" / "icons" / "temp"
POLI_BG_TEXTURES = sorted(POLI_BG_DIR.glob("UITex_BGPoliLight_*.png"))
GRID_COLUMNS = 6
_PHOTO_CACHE: dict[str, object | None] = {}


@dataclass(slots=True)
class FastScanDialogResult:
    action: str


def _portrait_path(student_id: str) -> Path | None:
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        path = PORTRAIT_DIR / f"{student_id}{ext}"
        if path.exists():
            return path
    return None


def _load_card_photo(student_id: str, size: tuple[int, int]) -> object | None:
    if not HAS_PIL:
        return None

    width, height = size
    key = f"{student_id}:{width}x{height}"
    cached = _PHOTO_CACHE.get(key)
    if key in _PHOTO_CACHE:
        return cached

    path = _portrait_path(student_id)
    if path is None:
        _PHOTO_CACHE[key] = None
        return None

    try:
        background = Image.new("RGBA", size, (17, 25, 39, 255))
        if POLI_BG_TEXTURES:
            texture_index = sum(student_id.encode("utf-8")) % len(POLI_BG_TEXTURES)
            with Image.open(POLI_BG_TEXTURES[texture_index]) as tex:
                texture = ImageOps.fit(tex.convert("RGBA"), size, Image.LANCZOS, centering=(0.5, 0.5))
                texture.putalpha(40)
                background.alpha_composite(texture)
        background.alpha_composite(Image.new("RGBA", size, (8, 12, 18, 84)))

        with Image.open(path) as raw:
            portrait = raw.convert("RGBA")
        alpha = portrait.getchannel("A")
        bbox = alpha.getbbox()
        if bbox:
            portrait = portrait.crop(bbox)
        if portrait.width > 0 and portrait.height > 0:
            scale = min((width * 0.98) / portrait.width, (height * 0.98) / portrait.height)
            portrait = portrait.resize(
                (
                    max(1, int(round(portrait.width * scale))),
                    max(1, int(round(portrait.height * scale))),
                ),
                Image.LANCZOS,
            )
            offset = ((width - portrait.width) // 2, height - portrait.height)
            background.alpha_composite(portrait, offset)

        photo = ImageTk.PhotoImage(background.convert("RGB"))
        _PHOTO_CACHE[key] = photo
        return photo
    except Exception:
        _PHOTO_CACHE[key] = None
        return None


class FastScanDialog(tk.Toplevel):
    def __init__(
        self,
        master,
        *,
        ordered_students: list[tuple[str, str]],
        has_rollback: bool,
        mode_label: str,
        roster_source_label: str,
        saved_student_count: int,
    ) -> None:
        super().__init__(master)
        self.title("학생 스캔 모드")
        self.configure(bg="#101722")
        self.result = FastScanDialogResult(action="cancel")
        self._ordered_students = ordered_students
        self._has_rollback = has_rollback
        self._mode_label = mode_label
        self._roster_source_label = roster_source_label
        self._saved_student_count = saved_student_count
        self._ui_scale = get_ui_scale(self, base_width=820, base_height=760)
        self._same_order = tk.BooleanVar(value=False)
        self._same_owned = tk.BooleanVar(value=False)

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
        width = scale_px(780, self._ui_scale)
        height = scale_px(720, self._ui_scale)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{width}x{height}+{(sw-width)//2}+{(sh-height)//2}")
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(250, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _build(self) -> None:
        wrap = tk.Frame(
            self,
            bg="#101722",
            padx=scale_px(18, self._ui_scale),
            pady=scale_px(18, self._ui_scale),
        )
        wrap.pack(fill="both", expand=True)

        tk.Label(
            wrap,
            text="빠른 학생 스캔",
            bg="#101722",
            fg="#e4f1ff",
            font=scale_font(("Malgun Gothic", 15, "bold"), self._ui_scale),
        ).pack(anchor="w")

        tk.Label(
            wrap,
            text=(
                "빠른 모드는 학생 텍스처 인식을 건너뛰고 기준 목록의 이름순 순서대로 스캔합니다.\n"
                "인게임 학생 목록도 이름순 정렬이어야 하며, 아래 목록이 현재 보유 학생과 같아야 합니다."
            ),
            bg="#101722",
            fg="#8aa4bf",
            justify="left",
            wraplength=scale_px(660, self._ui_scale),
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(anchor="w", pady=(scale_px(6, self._ui_scale), scale_px(12, self._ui_scale)))

        info = tk.Frame(wrap, bg="#162130", padx=scale_px(12, self._ui_scale), pady=scale_px(10, self._ui_scale))
        info.pack(fill="x")

        tk.Label(
            info,
            text=f"대상: {self._mode_label}",
            bg="#162130",
            fg="#d6e6f5",
            anchor="w",
            font=scale_font(("Malgun Gothic", 10, "bold"), self._ui_scale),
        ).pack(fill="x")
        tk.Label(
            info,
            text=f"기준 목록 출처: {self._roster_source_label}",
            bg="#162130",
            fg="#8aa4bf",
            anchor="w",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(4, self._ui_scale), 0))
        tk.Label(
            info,
            text=(
                f"기준 목록 학생 수: {len(self._ordered_students)}명"
                f" | 저장 데이터 학생 수: {self._saved_student_count}명"
            ),
            bg="#162130",
            fg="#8aa4bf",
            anchor="w",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(fill="x", pady=(scale_px(4, self._ui_scale), 0))

        list_frame = tk.Frame(wrap, bg="#101722")
        list_frame.pack(fill="both", expand=True, pady=(scale_px(14, self._ui_scale), scale_px(10, self._ui_scale)))

        tk.Label(
            list_frame,
            text=f"이름순 기준 목록 ({GRID_COLUMNS}칸 고정)",
            bg="#101722",
            fg="#8aa4bf",
            anchor="w",
            font=scale_font(("Malgun Gothic", 9), self._ui_scale),
        ).pack(anchor="w")

        self._build_roster_grid(list_frame)

        check_wrap = tk.Frame(wrap, bg="#101722")
        check_wrap.pack(fill="x")

        self._check_order = tk.Checkbutton(
            check_wrap,
            text="인게임 학생 목록을 이름순 정렬로 맞췄습니다.",
            variable=self._same_order,
            bg="#101722",
            fg="#e4f1ff",
            activebackground="#101722",
            activeforeground="#e4f1ff",
            selectcolor="#162130",
            command=self._refresh_state,
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            anchor="w",
            justify="left",
        )
        self._check_order.pack(fill="x")

        self._check_owned = tk.Checkbutton(
            check_wrap,
            text="아래 목록이 현재 보유 학생과 동일하다는 것을 확인했습니다.",
            variable=self._same_owned,
            bg="#101722",
            fg="#e4f1ff",
            activebackground="#101722",
            activeforeground="#e4f1ff",
            selectcolor="#162130",
            command=self._refresh_state,
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            anchor="w",
            justify="left",
        )
        self._check_owned.pack(fill="x", pady=(scale_px(6, self._ui_scale), 0))

        foot = tk.Label(
            wrap,
            text=(
                "빠른 모드에서는 학생 식별을 건너뛰므로 순서가 어긋나면 잘못된 학생에 값이 저장될 수 있습니다.\n"
                "이상할 때는 롤백 버튼으로 마지막 빠른 스캔 전 상태를 복원할 수 있습니다."
            ),
            bg="#101722",
            fg="#f1c27d",
            justify="left",
            wraplength=scale_px(660, self._ui_scale),
            font=scale_font(("Malgun Gothic", 8), self._ui_scale),
        )
        foot.pack(anchor="w", pady=(scale_px(10, self._ui_scale), 0))

        buttons = tk.Frame(wrap, bg="#101722")
        buttons.pack(fill="x", pady=(scale_px(16, self._ui_scale), 0))

        if self._has_rollback:
            tk.Button(
                buttons,
                text="마지막 빠른 스캔 롤백",
                command=self._rollback,
                bg="#80333b",
                fg="#ffffff",
                relief="flat",
                font=scale_font(("Malgun Gothic", 10), self._ui_scale),
                padx=scale_px(14, self._ui_scale),
                pady=scale_px(8, self._ui_scale),
            ).pack(side="left")

        tk.Button(
            buttons,
            text="목록 편집",
            command=self._edit,
            bg="#7a5cff",
            fg="#ffffff",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            padx=scale_px(16, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        ).pack(side="left", padx=(scale_px(8, self._ui_scale), 0))

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

        self._normal_button = tk.Button(
            buttons,
            text="일반 스캔",
            command=self._normal,
            bg="#2d8cff",
            fg="#ffffff",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            padx=scale_px(16, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        )
        self._normal_button.pack(side="right", padx=(0, scale_px(8, self._ui_scale)))

        self._fast_button = tk.Button(
            buttons,
            text="빠른 스캔",
            command=self._fast,
            bg="#25a55f",
            fg="#ffffff",
            relief="flat",
            font=scale_font(("Malgun Gothic", 10, "bold"), self._ui_scale),
            padx=scale_px(16, self._ui_scale),
            pady=scale_px(8, self._ui_scale),
        )
        self._fast_button.pack(side="right", padx=(0, scale_px(8, self._ui_scale)))
        self._refresh_state()

    def _build_roster_grid(self, parent: tk.Widget) -> None:
        body = tk.Frame(parent, bg="#101722")
        body.pack(fill="both", expand=True, pady=(scale_px(6, self._ui_scale), 0))

        canvas = tk.Canvas(body, bg="#162130", highlightthickness=0)
        scrollbar = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)

        inner = tk.Frame(canvas, bg="#162130")
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")
        card_width = scale_px(102, self._ui_scale)
        card_height = scale_px(138, self._ui_scale)
        gap = scale_px(8, self._ui_scale)
        pad = scale_px(10, self._ui_scale)
        grid_width = pad * 2 + GRID_COLUMNS * card_width + (GRID_COLUMNS - 1) * gap

        def sync_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def center_grid(event) -> None:
            x = max(0, (event.width - grid_width) // 2)
            canvas.coords(inner_window, x, 0)
            canvas.itemconfigure(inner_window, width=grid_width)

        def on_mousewheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        inner.bind("<Configure>", sync_scroll_region)
        canvas.bind("<Configure>", center_grid)
        canvas.bind("<MouseWheel>", on_mousewheel)
        inner.bind("<MouseWheel>", on_mousewheel)

        if not self._ordered_students:
            empty = tk.Label(
                inner,
                text="저장된 기준 목록이 없습니다.\n먼저 목록 편집을 눌러 설정해 주세요.",
                bg="#162130",
                fg="#8aa4bf",
                justify="center",
                font=scale_font(("Malgun Gothic", 10), self._ui_scale),
            )
            empty.grid(row=0, column=0, columnspan=GRID_COLUMNS, sticky="nsew", padx=pad, pady=scale_px(28, self._ui_scale))
            empty.bind("<MouseWheel>", on_mousewheel)
            return

        for index, (student_id, name) in enumerate(self._ordered_students, start=1):
            row = (index - 1) // GRID_COLUMNS
            col = (index - 1) % GRID_COLUMNS
            card = self._build_student_card(inner, index, student_id, name, card_width, card_height)
            card.bind("<MouseWheel>", on_mousewheel)
            card.grid(
                row=row,
                column=col,
                padx=(pad if col == 0 else gap, 0),
                pady=(pad if row == 0 else gap, 0),
                sticky="nw",
            )

        for col in range(GRID_COLUMNS):
            inner.grid_columnconfigure(col, minsize=card_width)

    def _build_student_card(self, parent: tk.Widget, index: int, student_id: str, name: str, width: int, height: int) -> tk.Canvas:
        image_height = max(scale_px(86, self._ui_scale), height - scale_px(38, self._ui_scale))
        canvas = tk.Canvas(
            parent,
            width=width,
            height=height,
            bg="#111927",
            highlightthickness=1,
            highlightbackground="#22364a",
            highlightcolor="#4aa8e0",
        )
        photo = _load_card_photo(student_id, (width, image_height))
        if photo is not None:
            canvas.create_image(0, 0, image=photo, anchor="nw")
            canvas.image = photo
        else:
            canvas.create_rectangle(0, 0, width, image_height, fill="#1b2a3d", outline="")
            initials = (name or student_id or "?")[:2]
            canvas.create_text(
                width // 2,
                image_height // 2,
                text=initials,
                fill="#d6e6f5",
                font=scale_font(("Malgun Gothic", 18, "bold"), self._ui_scale),
            )

        badge_w = scale_px(32, self._ui_scale)
        badge_h = scale_px(18, self._ui_scale)
        canvas.create_rectangle(0, 0, badge_w, badge_h, fill="#2d8cff", outline="")
        canvas.create_text(
            badge_w // 2,
            badge_h // 2,
            text=str(index),
            fill="#ffffff",
            font=scale_font(("Malgun Gothic", 8, "bold"), self._ui_scale),
        )

        panel_top = image_height
        canvas.create_rectangle(0, panel_top, width, height, fill="#0a0f18", outline="")
        canvas.create_rectangle(0, panel_top, width // 2, panel_top + scale_px(3, self._ui_scale), fill="#4aa8e0", outline="")
        canvas.create_rectangle(width // 2, panel_top, width, panel_top + scale_px(3, self._ui_scale), fill="#f266b3", outline="")
        canvas.create_text(
            width // 2,
            panel_top + max(scale_px(20, self._ui_scale), (height - panel_top) // 2),
            text=name,
            width=width - scale_px(10, self._ui_scale),
            fill="#f2f7ff",
            justify="center",
            font=scale_font(("Malgun Gothic", 9, "bold"), self._ui_scale),
        )
        return canvas

    def _refresh_state(self) -> None:
        can_fast = self._same_order.get() and self._same_owned.get() and bool(self._ordered_students)
        self._fast_button.configure(state="normal" if can_fast else "disabled")

    def _finish(self, action: str) -> None:
        self.result = FastScanDialogResult(action=action)
        self.destroy()

    def _normal(self) -> None:
        self._finish("normal")

    def _fast(self) -> None:
        self._finish("fast")

    def _rollback(self) -> None:
        self._finish("rollback")

    def _edit(self) -> None:
        self._finish("edit")

    def _cancel(self) -> None:
        self._finish("cancel")


def choose_fast_scan_action(
    master,
    *,
    ordered_students: list[tuple[str, str]],
    has_rollback: bool,
    mode_label: str,
    roster_source_label: str,
    saved_student_count: int,
) -> FastScanDialogResult:
    dialog = FastScanDialog(
        master,
        ordered_students=ordered_students,
        has_rollback=has_rollback,
        mode_label=mode_label,
        roster_source_label=roster_source_label,
        saved_student_count=saved_student_count,
    )
    master.wait_window(dialog)
    return dialog.result
