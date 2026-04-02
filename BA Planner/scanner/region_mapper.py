"""
region_mapper.py
개발용 영역 매핑 도구.

사용법:
  python region_mapper.py [이미지파일]
  또는 실행 후 파일 드래그&드롭 / 열기 버튼으로 이미지 로드

기능:
  - 이미지 위에 드래그로 영역 지정
  - 지정된 영역의 비율 좌표(0~1) + 픽셀 좌표 즉시 표시
  - 여러 영역에 라벨 붙여서 저장
  - regions.json으로 내보내기 (v4에서 그대로 사용)
  - 영역 위에 마우스 올리면 정보 표시
  - 영역 클릭으로 삭제
"""

import tkinter as tk
from tkinter import filedialog, messagebox
import json
import sys
from pathlib import Path
from PIL import Image, ImageTk

# ── 색상 ──────────────────────────────────────────────────
BG       = "#0d1b2a"
CARD     = "#152435"
CARD2    = "#1a2e40"
BLUE     = "#1a6fad"
LBLUE    = "#4aa8e0"
YELLOW   = "#f5c842"
GREEN    = "#3dbf7a"
ORANGE   = "#e8894a"
PURPLE   = "#c97bec"
RED      = "#e85a5a"
TEXT     = "#e8f4fd"
SUBTEXT  = "#7ab3d4"
FONT     = "Malgun Gothic"

# 영역별 색상 순환
REGION_COLORS = [LBLUE, GREEN, YELLOW, ORANGE, PURPLE, RED, "#5bc2e7", "#f0a070"]

# 미리 정의된 라벨 제안
LABEL_PRESETS = [
    "nickname_region",
    "resources",
    "menu_button",
    "menu_item_button",
    "menu_equipment_button",
    "item_grid",
    "item_detail",
    "equipment_grid",
    "equipment_detail",
    "student_basic",
    "student_stats",
    "lobby_indicator",
]


class RegionMapper(tk.Tk):
    def __init__(self, image_path: str | None = None):
        super().__init__()

        self.title("BA Region Mapper — 개발용 영역 지정 도구")
        self.configure(bg=BG)
        self.geometry("1400x820")
        self.minsize(1000, 600)

        # 상태
        self._image_orig: Image.Image | None = None
        self._image_tk:   ImageTk.PhotoImage | None = None
        self._scale:      float = 1.0          # 표시 배율
        self._offset_x:   int   = 0            # 캔버스 내 이미지 오프셋
        self._offset_y:   int   = 0

        self._regions:    list[dict] = []       # 저장된 영역들
        self._drag_start: tuple | None = None
        self._current_rect = None              # 드래그 중인 사각형
        self._hover_idx:  int = -1

        self._build_ui()

        if image_path and Path(image_path).exists():
            self._load_image(image_path)

    # ── UI 구성 ───────────────────────────────────────────
    def _build_ui(self):
        # 상단 툴바
        toolbar = tk.Frame(self, bg=CARD, height=48)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text="🗺  BA Region Mapper",
                 bg=CARD, fg=LBLUE,
                 font=(FONT, 14, "bold")).pack(side="left", padx=16)

        for text, cmd, color in [
            ("📂  이미지 열기",  self._open_image,   BLUE),
            ("💾  regions.json 저장", self._save_json, GREEN),
            ("📋  좌표 복사",    self._copy_all,     ORANGE),
            ("🗑  전체 삭제",    self._clear_all,    RED),
        ]:
            tk.Button(toolbar, text=text, command=cmd,
                      bg=color, fg=BG if color != RED else TEXT,
                      font=(FONT, 10, "bold"),
                      relief="flat", padx=12, pady=4,
                      cursor="hand2").pack(side="left", padx=4, pady=8)

        # 이미지 원본 크기 표시
        self._size_var = tk.StringVar(value="이미지를 불러와주세요")
        tk.Label(toolbar, textvariable=self._size_var,
                 bg=CARD, fg=SUBTEXT,
                 font=(FONT, 10)).pack(side="right", padx=16)

        # 본문
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # ── 캔버스 ──
        canvas_frame = tk.Frame(body, bg=BG)
        canvas_frame.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg="#1a1a2e",
                                cursor="crosshair",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>",          self._on_hover)
        self.canvas.bind("<Button-3>",        self._on_right_click)
        self.bind("<Configure>",              self._on_resize)

        # ── 오른쪽 패널 ──
        right = tk.Frame(body, bg=CARD, width=320)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        self._build_right_panel(right)

    def _build_right_panel(self, parent):
        tk.Label(parent, text="영역 목록",
                 bg=CARD, fg=LBLUE,
                 font=(FONT, 13, "bold")).pack(padx=14, pady=(14, 6), anchor="w")

        # 스크롤 가능한 영역 리스트
        list_frame = tk.Frame(parent, bg=CARD)
        list_frame.pack(fill="both", expand=True, padx=8)

        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")

        self._listbox = tk.Listbox(
            list_frame,
            bg=CARD2, fg=TEXT,
            font=(FONT, 10),
            selectbackground=BLUE,
            relief="flat",
            yscrollcommand=scrollbar.set,
            activestyle="none",
            height=12
        )
        self._listbox.pack(fill="both", expand=True)
        scrollbar.config(command=self._listbox.yview)
        self._listbox.bind("<<ListboxSelect>>", self._on_list_select)

        # 선택 영역 삭제 버튼
        tk.Button(parent, text="🗑  선택 영역 삭제",
                  bg=RED, fg=TEXT,
                  font=(FONT, 10), relief="flat",
                  padx=8, pady=4, cursor="hand2",
                  command=self._delete_selected).pack(fill="x", padx=8, pady=4)

        tk.Frame(parent, bg=CARD2, height=1).pack(fill="x", padx=8, pady=4)

        # 라벨 입력
        tk.Label(parent, text="라벨 입력",
                 bg=CARD, fg=SUBTEXT,
                 font=(FONT, 10)).pack(padx=14, anchor="w")

        self._label_var = tk.StringVar()
        label_entry = tk.Entry(parent, textvariable=self._label_var,
                               bg=CARD2, fg=TEXT,
                               insertbackground=TEXT,
                               font=(FONT, 11), relief="flat")
        label_entry.pack(fill="x", padx=8, pady=4)

        # 프리셋 버튼들
        tk.Label(parent, text="빠른 라벨",
                 bg=CARD, fg=SUBTEXT,
                 font=(FONT, 9)).pack(padx=14, pady=(4, 2), anchor="w")

        preset_frame = tk.Frame(parent, bg=CARD)
        preset_frame.pack(fill="x", padx=8)

        for i, preset in enumerate(LABEL_PRESETS):
            short = preset.replace("_", "\n")
            color = REGION_COLORS[i % len(REGION_COLORS)]
            tk.Button(preset_frame, text=short,
                      bg=CARD2, fg=color,
                      font=(FONT, 7), relief="flat",
                      padx=2, pady=2, cursor="hand2",
                      command=lambda p=preset: self._label_var.set(p)
                      ).grid(row=i//2, column=i%2,
                             padx=2, pady=2, sticky="ew")
        preset_frame.columnconfigure(0, weight=1)
        preset_frame.columnconfigure(1, weight=1)

        tk.Frame(parent, bg=CARD2, height=1).pack(fill="x", padx=8, pady=8)

        # 좌표 표시
        tk.Label(parent, text="현재 좌표",
                 bg=CARD, fg=SUBTEXT,
                 font=(FONT, 10)).pack(padx=14, anchor="w")

        self._coord_var = tk.StringVar(value="-")
        tk.Label(parent, textvariable=self._coord_var,
                 bg=CARD2, fg=YELLOW,
                 font=("Consolas", 9),
                 justify="left", wraplength=290,
                 anchor="nw").pack(fill="x", padx=8, pady=4, ipady=6)

        # JSON 미리보기
        tk.Label(parent, text="JSON 미리보기",
                 bg=CARD, fg=SUBTEXT,
                 font=(FONT, 10)).pack(padx=14, pady=(4, 2), anchor="w")

        self._json_text = tk.Text(parent, bg=CARD2, fg=GREEN,
                                  font=("Consolas", 8),
                                  height=8, relief="flat",
                                  state="disabled", wrap="none")
        self._json_text.pack(fill="x", padx=8, pady=(0, 8))

    # ── 이미지 로드 ───────────────────────────────────────
    def _open_image(self):
        path = filedialog.askopenfilename(
            title="스크린샷 선택",
            filetypes=[("이미지", "*.png *.jpg *.jpeg *.bmp")]
        )
        if path:
            self._load_image(path)

    def _load_image(self, path: str):
        self._image_orig = Image.open(path).convert("RGB")
        w, h = self._image_orig.size
        self._size_var.set(f"원본: {w}×{h}px  |  {Path(path).name}")
        self._regions.clear()
        self._update_listbox()
        self.after(50, self._fit_image)

    def _fit_image(self):
        if not self._image_orig:
            return
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        iw, ih = self._image_orig.size

        scale_w = cw / iw
        scale_h = ch / ih
        self._scale = min(scale_w, scale_h, 1.0)

        dw = int(iw * self._scale)
        dh = int(ih * self._scale)
        self._offset_x = (cw - dw) // 2
        self._offset_y = (ch - dh) // 2

        resized = self._image_orig.resize((dw, dh), Image.LANCZOS)
        self._image_tk = ImageTk.PhotoImage(resized)
        self._redraw()

    def _on_resize(self, e):
        if self._image_orig:
            self.after(100, self._fit_image)

    # ── 드로잉 ────────────────────────────────────────────
    def _redraw(self):
        self.canvas.delete("all")

        if self._image_tk:
            self.canvas.create_image(
                self._offset_x, self._offset_y,
                anchor="nw", image=self._image_tk
            )

        for i, region in enumerate(self._regions):
            self._draw_region(i, region)

    def _draw_region(self, idx: int, region: dict):
        color = region.get("color", LBLUE)
        is_hover = (idx == self._hover_idx)

        cx1, cy1, cx2, cy2 = self._ratio_to_canvas(
            region["x1"], region["y1"],
            region["x2"], region["y2"]
        )

        # 반투명 내부
        self.canvas.create_rectangle(
            cx1, cy1, cx2, cy2,
            fill=color, stipple="gray25" if not is_hover else "gray50",
            outline="", tags=f"region_{idx}"
        )
        # 테두리
        self.canvas.create_rectangle(
            cx1, cy1, cx2, cy2,
            fill="", outline=color,
            width=2 if not is_hover else 3,
            tags=f"region_{idx}"
        )

        # 라벨
        label = region.get("label", f"region_{idx}")
        self.canvas.create_text(
            cx1 + 5, cy1 + 5,
            text=label, fill=color,
            font=(FONT, 9, "bold"),
            anchor="nw", tags=f"region_{idx}"
        )

        # 호버 시 상세 좌표 표시
        if is_hover:
            info = (f"x1={region['x1']:.4f}  y1={region['y1']:.4f}\n"
                    f"x2={region['x2']:.4f}  y2={region['y2']:.4f}")
            self.canvas.create_text(
                cx1 + 5, cy2 - 5,
                text=info, fill=YELLOW,
                font=("Consolas", 8),
                anchor="sw", tags=f"region_{idx}"
            )

        # 삭제 버튼 (우측 상단)
        if is_hover:
            bx, by = cx2 - 14, cy1 + 2
            self.canvas.create_oval(bx-8, by-8, bx+8, by+8,
                                    fill=RED, outline="",
                                    tags=f"del_{idx}")
            self.canvas.create_text(bx, by, text="×",
                                    fill="white",
                                    font=("Arial", 10, "bold"),
                                    tags=f"del_{idx}")

    # ── 좌표 변환 ─────────────────────────────────────────
    def _canvas_to_ratio(self, cx: int, cy: int) -> tuple[float, float]:
        if not self._image_orig:
            return 0.0, 0.0
        iw, ih = self._image_orig.size
        rx = (cx - self._offset_x) / (iw * self._scale)
        ry = (cy - self._offset_y) / (ih * self._scale)
        return max(0.0, min(1.0, rx)), max(0.0, min(1.0, ry))

    def _ratio_to_canvas(self, x1, y1, x2, y2) -> tuple:
        if not self._image_orig:
            return 0, 0, 0, 0
        iw, ih = self._image_orig.size
        s = self._scale
        ox, oy = self._offset_x, self._offset_y
        return (
            int(ox + x1 * iw * s), int(oy + y1 * ih * s),
            int(ox + x2 * iw * s), int(oy + y2 * ih * s)
        )

    # ── 이벤트 ────────────────────────────────────────────
    def _on_press(self, e):
        # 삭제 버튼 클릭 체크
        items = self.canvas.find_withtag("current")
        for item in items:
            tags = self.canvas.gettags(item)
            for tag in tags:
                if tag.startswith("del_"):
                    idx = int(tag.split("_")[1])
                    self._regions.pop(idx)
                    self._update_listbox()
                    self._redraw()
                    return

        self._drag_start = (e.x, e.y)
        self._current_rect = None

    def _on_drag(self, e):
        if not self._drag_start:
            return
        sx, sy = self._drag_start
        self.canvas.delete("dragging")
        self.canvas.create_rectangle(
            sx, sy, e.x, e.y,
            outline=YELLOW, width=2,
            dash=(6, 3), tags="dragging"
        )
        # 실시간 좌표 표시
        rx1, ry1 = self._canvas_to_ratio(sx, sy)
        rx2, ry2 = self._canvas_to_ratio(e.x, e.y)
        rx1, rx2 = min(rx1, rx2), max(rx1, rx2)
        ry1, ry2 = min(ry1, ry2), max(ry1, ry2)

        if self._image_orig:
            iw, ih = self._image_orig.size
            px1, py1 = int(rx1*iw), int(ry1*ih)
            px2, py2 = int(rx2*iw), int(ry2*ih)
            self._coord_var.set(
                f"비율:\n  x1={rx1:.4f}  y1={ry1:.4f}\n"
                f"  x2={rx2:.4f}  y2={ry2:.4f}\n\n"
                f"픽셀 ({iw}×{ih}):\n"
                f"  ({px1},{py1}) → ({px2},{py2})\n"
                f"  크기: {px2-px1}×{py2-py1}"
            )

    def _on_release(self, e):
        if not self._drag_start:
            return
        self.canvas.delete("dragging")
        sx, sy = self._drag_start
        self._drag_start = None

        rx1, ry1 = self._canvas_to_ratio(sx, sy)
        rx2, ry2 = self._canvas_to_ratio(e.x, e.y)
        rx1, rx2 = min(rx1, rx2), max(rx1, rx2)
        ry1, ry2 = min(ry1, ry2), max(ry1, ry2)

        # 너무 작으면 무시
        if rx2 - rx1 < 0.005 or ry2 - ry1 < 0.005:
            return

        color = REGION_COLORS[len(self._regions) % len(REGION_COLORS)]
        label = self._label_var.get().strip() or f"region_{len(self._regions)}"

        region = {
            "label": label,
            "x1": round(rx1, 4),
            "y1": round(ry1, 4),
            "x2": round(rx2, 4),
            "y2": round(ry2, 4),
            "color": color,
        }
        self._regions.append(region)
        self._update_listbox()
        self._redraw()
        self._update_json_preview()

    def _on_hover(self, e):
        prev = self._hover_idx
        self._hover_idx = -1

        for i, region in enumerate(self._regions):
            cx1, cy1, cx2, cy2 = self._ratio_to_canvas(
                region["x1"], region["y1"],
                region["x2"], region["y2"]
            )
            if cx1 <= e.x <= cx2 and cy1 <= e.y <= cy2:
                self._hover_idx = i
                break

        if self._hover_idx != prev:
            self._redraw()

    def _on_right_click(self, e):
        """우클릭으로 해당 위치 영역 삭제"""
        for i, region in enumerate(self._regions):
            cx1, cy1, cx2, cy2 = self._ratio_to_canvas(
                region["x1"], region["y1"],
                region["x2"], region["y2"]
            )
            if cx1 <= e.x <= cx2 and cy1 <= e.y <= cy2:
                if messagebox.askyesno("삭제", f"'{region['label']}' 영역을 삭제할까?"):
                    self._regions.pop(i)
                    self._update_listbox()
                    self._redraw()
                    self._update_json_preview()
                return

    def _on_list_select(self, e):
        sel = self._listbox.curselection()
        if sel:
            idx = sel[0]
            self._hover_idx = idx
            if idx < len(self._regions):
                self._label_var.set(self._regions[idx]["label"])
            self._redraw()

    # ── 리스트/JSON 업데이트 ──────────────────────────────
    def _update_listbox(self):
        self._listbox.delete(0, "end")
        for i, r in enumerate(self._regions):
            self._listbox.insert(
                "end",
                f"  {i+1:>2}. {r['label']}"
                f"  ({r['x1']:.3f},{r['y1']:.3f})→({r['x2']:.3f},{r['y2']:.3f})"
            )
        self._update_json_preview()

    def _update_json_preview(self):
        data = {r["label"]: {
            "x1": r["x1"], "y1": r["y1"],
            "x2": r["x2"], "y2": r["y2"]
        } for r in self._regions}
        text = json.dumps(data, indent=2, ensure_ascii=False)
        self._json_text.config(state="normal")
        self._json_text.delete("1.0", "end")
        self._json_text.insert("1.0", text)
        self._json_text.config(state="disabled")

    def _delete_selected(self):
        sel = self._listbox.curselection()
        if sel:
            self._regions.pop(sel[0])
            self._hover_idx = -1
            self._update_listbox()
            self._redraw()

    def _clear_all(self):
        if self._regions and messagebox.askyesno("전체 삭제", "모든 영역을 삭제할까?"):
            self._regions.clear()
            self._hover_idx = -1
            self._update_listbox()
            self._redraw()

    # ── 저장/복사 ─────────────────────────────────────────
    def _save_json(self):
        if not self._regions:
            messagebox.showinfo("알림", "저장할 영역이 없어")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile="regions.json",
            filetypes=[("JSON", "*.json")]
        )
        if path:
            data = {r["label"]: {
                "x1": r["x1"], "y1": r["y1"],
                "x2": r["x2"], "y2": r["y2"]
            } for r in self._regions}
            Path(path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            messagebox.showinfo("저장 완료", f"{Path(path).name} 저장됨\n{len(self._regions)}개 영역")

    def _copy_all(self):
        if not self._regions:
            return
        data = {r["label"]: {
            "x1": r["x1"], "y1": r["y1"],
            "x2": r["x2"], "y2": r["y2"]
        } for r in self._regions}
        text = json.dumps(data, indent=2, ensure_ascii=False)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("복사됨", "JSON이 클립보드에 복사됐어")


if __name__ == "__main__":
    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = RegionMapper(image_path)
    app.mainloop()
