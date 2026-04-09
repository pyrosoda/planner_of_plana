"""
gui/window_picker.py — 창 선택 UI
실행 중인 창 목록을 표시하고 사용자가 블루아카이브 창을 직접 선택.
"""
import tkinter as tk
from typing import Callable

from core.capture import get_all_windows, set_target_window, get_target_info
from gui.ui_scale import get_ui_scale, scale_font, scale_px

BG    = "#0d1b2a"
CARD  = "#152435"
CARD2 = "#1a2e40"
BLUE  = "#1a6fad"
LBLUE = "#4aa8e0"
GREEN = "#3dbf7a"
RED   = "#e85a5a"
TEXT  = "#e8f4fd"
SUB   = "#7ab3d4"
FONT  = "Malgun Gothic"

# 블루아카이브 관련 키워드 (하이라이트용)
BA_KEYWORDS = ["blue archive", "블루 아카이브", "ブルーアーカイブ"]


class WindowPicker(tk.Toplevel):
    """
    창 선택 팝업.
    on_select(hwnd, title) 콜백으로 선택 결과 전달.
    """

    def __init__(self, master,
                 on_select: Callable[[int, str], None],
                 on_cancel: Callable):
        super().__init__(master)
        self.on_select = on_select
        self.on_cancel = on_cancel

        self.title("블루아카이브 창 선택")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self._ui_scale = get_ui_scale(self, base_width=700, base_height=560)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = scale_px(560, self._ui_scale), scale_px(480, self._ui_scale)
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._windows: list[dict] = []
        self._selected_idx: int | None = None

        self._build_ui()
        self._refresh()

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda e: self._cancel())

        self.grab_set()
        self.focus_force()

    def _build_ui(self):
        # 헤더
        hdr = tk.Frame(self, bg=BLUE, height=scale_px(52, self._ui_scale))
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text="🎯  블루아카이브 창을 선택해줘",
            bg=BLUE,
            fg=TEXT,
            font=scale_font((FONT, 13, "bold"), self._ui_scale)
        ).pack(expand=True)

        # 안내
        tk.Label(
            self,
            text="아래 목록에서 블루아카이브 게임 창을 클릭해서 선택해.\n"
                 "이름이 비슷한 브라우저 탭과 구별할 수 있어.",
            bg=BG,
            fg=SUB,
            font=scale_font((FONT, 9), self._ui_scale),
            justify="center"
        ).pack(pady=(scale_px(10, self._ui_scale), scale_px(4, self._ui_scale)))

        # 현재 선택된 창
        self._cur_var = tk.StringVar(value="선택 없음")
        cur_frame = tk.Frame(self, bg=CARD, height=scale_px(36, self._ui_scale))
        cur_frame.pack(fill="x", padx=scale_px(14, self._ui_scale), pady=(0, scale_px(6, self._ui_scale)))
        cur_frame.pack_propagate(False)

        tk.Label(
            cur_frame,
            text="현재:",
            bg=CARD,
            fg=SUB,
            font=scale_font((FONT, 9), self._ui_scale)
        ).pack(side="left", padx=scale_px(10, self._ui_scale))

        tk.Label(
            cur_frame,
            textvariable=self._cur_var,
            bg=CARD,
            fg=GREEN,
            font=scale_font((FONT, 9, "bold"), self._ui_scale)
        ).pack(side="left")

        # 창 목록
        list_frame = tk.Frame(self, bg=CARD)
        list_frame.pack(fill="both", expand=True, padx=scale_px(14, self._ui_scale))

        # 컬럼 헤더
        hdr2 = tk.Frame(list_frame, bg=CARD2)
        hdr2.pack(fill="x")
        tk.Label(
            hdr2,
            text="창 제목",
            bg=CARD2,
            fg=LBLUE,
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            anchor="w",
            width=45
        ).pack(side="left", padx=scale_px(8, self._ui_scale), pady=scale_px(4, self._ui_scale))

        tk.Label(
            hdr2,
            text="크기",
            bg=CARD2,
            fg=LBLUE,
            font=scale_font((FONT, 9, "bold"), self._ui_scale),
            anchor="w",
            width=10
        ).pack(side="left")

        # 스크롤 목록
        scroll = tk.Scrollbar(list_frame)
        scroll.pack(side="right", fill="y")

        self._listbox = tk.Listbox(
            list_frame,
            bg=CARD,
            fg=TEXT,
            font=scale_font((FONT, 9), self._ui_scale),
            selectbackground=BLUE,
            selectforeground=TEXT,
            relief="flat",
            yscrollcommand=scroll.set,
            activestyle="none",
            height=max(10, scale_px(14, self._ui_scale)),
        )
        self._listbox.pack(fill="both", expand=True)
        scroll.config(command=self._listbox.yview)

        self._listbox.bind("<<ListboxSelect>>", self._on_select)
        self._listbox.bind("<Double-Button-1>", lambda e: self._confirm())

        # 버튼
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.pack(fill="x", padx=scale_px(14, self._ui_scale), pady=scale_px(10, self._ui_scale))

        tk.Button(
            btn_frame,
            text="🔄  새로고침",
            bg=CARD,
            fg=SUB,
            font=scale_font((FONT, 9), self._ui_scale),
            relief="flat",
            padx=scale_px(10, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
            cursor="hand2",
            command=self._refresh
        ).pack(side="left")

        tk.Button(
            btn_frame,
            text="❌  취소",
            bg=CARD,
            fg=SUB,
            font=scale_font((FONT, 10), self._ui_scale),
            relief="flat",
            padx=scale_px(12, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
            cursor="hand2",
            command=self._cancel
        ).pack(side="right", padx=(scale_px(6, self._ui_scale), 0))

        self._confirm_btn = tk.Button(
            btn_frame,
            text="✅  이 창으로 설정",
            bg=GREEN,
            fg=BG,
            font=scale_font((FONT, 10, "bold"), self._ui_scale),
            relief="flat",
            padx=scale_px(12, self._ui_scale),
            pady=scale_px(6, self._ui_scale),
            cursor="hand2",
            state="disabled",
            command=self._confirm
        )
        self._confirm_btn.pack(side="right")

    def _refresh(self):
        self._windows = get_all_windows()
        self._listbox.delete(0, "end")
        self._selected_idx = None
        self._confirm_btn.configure(state="disabled")

        for i, win in enumerate(self._windows):
            title = win["title"]
            size = win["size"]
            is_ba = any(kw in title.lower() for kw in BA_KEYWORDS)

            label = f"  {'★ ' if is_ba else '  '}{title[:48]:48s}  {size}"
            self._listbox.insert("end", label)

            if is_ba:
                self._listbox.itemconfig(i, fg=GREEN)

        hwnd, title = get_target_info()
        if hwnd and title:
            self._cur_var.set(f"{title}")
        else:
            self._cur_var.set("선택 없음")

    def _on_select(self, _event):
        sel = self._listbox.curselection()
        if not sel:
            self._selected_idx = None
            self._confirm_btn.configure(state="disabled")
            self._cur_var.set("선택 없음")
            return

        self._selected_idx = sel[0]
        title = self._windows[self._selected_idx]["title"]
        self._confirm_btn.configure(state="normal")
        self._cur_var.set(f"선택됨: {title}")

    def _confirm(self):
        if self._selected_idx is None:
            return

        win = self._windows[self._selected_idx]
        set_target_window(win["hwnd"], win["title"])

        try:
            self.destroy()
        finally:
            self.on_select(win["hwnd"], win["title"])

    def _cancel(self):
        try:
            self.destroy()
        finally:
            self.on_cancel()
