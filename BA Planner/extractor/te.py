"""
template_extractor.py
스크린샷에서 드래그로 영역을 선택하고 파일명을 입력해서 저장하는 도구.

사용법:
  python template_extractor.py [이미지파일]
  또는 실행 후 이미지 열기

조작:
  - 드래그: 영역 선택
  - 영역 확정 후 파일명 입력 → Enter로 저장
  - R: 현재 선택 초기화
  - Ctrl+Z: 마지막 저장 취소
"""

import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import sys
from pathlib import Path

SAVE_DIR = Path("templates")
SAVE_DIR.mkdir(exist_ok=True)

BG    = "#0d1b2a"
CARD  = "#152435"
LBLUE = "#4aa8e0"
YELLOW= "#f5c842"
GREEN = "#3dbf7a"
TEXT  = "#e8f4fd"
SUB   = "#7ab3d4"
RED   = "#e85a5a"
FONT  = "Malgun Gothic"


class Extractor(tk.Tk):
    def __init__(self, image_path=None):
        super().__init__()
        self.title("Template Extractor")
        self.configure(bg=BG)
        self.geometry("1300x800")

        self._img_orig:  Image.Image | None = None
        self._img_tk:    ImageTk.PhotoImage | None = None
        self._scale      = 1.0
        self._ox = self._oy = 0          # 캔버스 내 이미지 오프셋

        self._drag_start = None
        self._sel        = None          # (x1,y1,x2,y2) 픽셀 비율
        self._saved      = []            # 저장 히스토리

        self._build_ui()

        if image_path and Path(image_path).exists():
            self._load(image_path)

    # ── UI ────────────────────────────────────────────────
    def _build_ui(self):
        # 상단 툴바
        bar = tk.Frame(self, bg=CARD, height=46)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        tk.Label(bar, text="✂  Template Extractor",
                 bg=CARD, fg=LBLUE,
                 font=(FONT, 13, "bold")).pack(side="left", padx=14)

        tk.Button(bar, text="📂 이미지 열기",
                  bg=LBLUE, fg=BG,
                  font=(FONT, 10, "bold"),
                  relief="flat", padx=10, pady=4,
                  cursor="hand2",
                  command=self._open).pack(side="left", padx=6, pady=8)

        tk.Button(bar, text="📁 저장 폴더 열기",
                  bg=CARD, fg=SUB,
                  font=(FONT, 10), relief="flat",
                  padx=10, pady=4, cursor="hand2",
                  command=self._open_folder).pack(side="left", padx=2)

        self._info_var = tk.StringVar(value="이미지를 열어주세요")
        tk.Label(bar, textvariable=self._info_var,
                 bg=CARD, fg=SUB,
                 font=(FONT, 9)).pack(side="right", padx=14)

        # 본문
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # 캔버스
        self.canvas = tk.Canvas(body, bg="#111122",
                                cursor="crosshair",
                                highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>",   self._press)
        self.canvas.bind("<B1-Motion>",       self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>",              lambda e: self._refit())
        self.bind("<r>",                      lambda e: self._reset_sel())
        self.bind("<R>",                      lambda e: self._reset_sel())
        self.bind("<Control-z>",              lambda e: self._undo())

        # 오른쪽 패널
        right = tk.Frame(body, bg=CARD, width=260)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self._build_right(right)

    def _build_right(self, p):
        tk.Label(p, text="저장 설정",
                 bg=CARD, fg=LBLUE,
                 font=(FONT, 12, "bold")).pack(padx=14, pady=(14,6), anchor="w")

        # 파일명 입력
        tk.Label(p, text="파일명 (.png 자동)",
                 bg=CARD, fg=SUB,
                 font=(FONT, 9)).pack(padx=14, anchor="w")

        self._name_var = tk.StringVar()
        self._entry = tk.Entry(p, textvariable=self._name_var,
                               bg="#0d1b2a", fg=TEXT,
                               insertbackground=TEXT,
                               font=(FONT, 12), relief="flat")
        self._entry.pack(fill="x", padx=10, pady=(2,8))
        self._entry.bind("<Return>", lambda e: self._save())
        self._entry.focus_set()

        # 저장 버튼
        tk.Button(p, text="💾  저장  (Enter)",
                  bg=GREEN, fg=BG,
                  font=(FONT, 11, "bold"),
                  relief="flat", pady=8,
                  cursor="hand2",
                  command=self._save).pack(fill="x", padx=10, pady=(0,6))

        tk.Button(p, text="↩  마지막 취소  (Ctrl+Z)",
                  bg=CARD, fg=SUB,
                  font=(FONT, 9), relief="flat",
                  pady=4, cursor="hand2",
                  command=self._undo).pack(fill="x", padx=10, pady=(0,10))

        tk.Frame(p, bg="#1a2e40", height=1).pack(fill="x", padx=10, pady=4)

        # 선택 영역 정보
        tk.Label(p, text="선택 영역",
                 bg=CARD, fg=SUB,
                 font=(FONT, 9)).pack(padx=14, pady=(4,2), anchor="w")

        self._sel_var = tk.StringVar(value="—")
        tk.Label(p, textvariable=self._sel_var,
                 bg="#0d1b2a", fg=YELLOW,
                 font=("Consolas", 9),
                 justify="left", anchor="nw",
                 wraplength=230).pack(fill="x", padx=10, pady=4, ipady=4)

        tk.Frame(p, bg="#1a2e40", height=1).pack(fill="x", padx=10, pady=4)

        # 저장 목록
        tk.Label(p, text="저장된 파일",
                 bg=CARD, fg=SUB,
                 font=(FONT, 9)).pack(padx=14, pady=(4,2), anchor="w")

        self._list_var = tk.StringVar()
        self._listbox = tk.Listbox(p,
                                   listvariable=self._list_var,
                                   bg="#0d1b2a", fg=GREEN,
                                   font=("Consolas", 8),
                                   relief="flat",
                                   selectbackground=LBLUE,
                                   height=14)
        self._listbox.pack(fill="both", expand=True, padx=10, pady=(0,10))

        tk.Frame(p, bg="#1a2e40", height=1).pack(fill="x", padx=10, pady=6)

        # regions.json 일괄 추출
        tk.Label(p, text="regions.json 일괄 추출",
                 bg=CARD, fg=LBLUE,
                 font=(FONT, 10, "bold")).pack(padx=14, anchor="w")

        tk.Label(p, text="JSON 불러오면 모든 영역을 한 번에 잘라 저장",
                 bg=CARD, fg=SUB,
                 font=(FONT, 8), wraplength=220, justify="left").pack(padx=14, anchor="w")

        tk.Button(p, text="📂  regions.json 불러와서 추출",
                  bg=LBLUE, fg=BG,
                  font=(FONT, 10, "bold"),
                  relief="flat", pady=6,
                  cursor="hand2",
                  command=self._batch_extract).pack(fill="x", padx=10, pady=6)

        # 단축키 안내
        tk.Label(p, text="R: 선택 초기화   Ctrl+Z: 마지막 취소",
                 bg=CARD, fg=SUB,
                 font=(FONT, 8)).pack(pady=(0,8))

    # ── 이미지 로드 ───────────────────────────────────────
    def _open(self):
        path = filedialog.askopenfilename(
            title="이미지 선택",
            filetypes=[("이미지", "*.png *.jpg *.jpeg *.bmp")]
        )
        if path:
            self._load(path)

    def _load(self, path):
        self._img_orig = Image.open(path).convert("RGB")
        w, h = self._img_orig.size
        self._info_var.set(f"{Path(path).name}  ({w}×{h})")
        self._sel = None
        self.after(50, self._refit)

    def _refit(self):
        if not self._img_orig:
            return
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 10 or ch < 10:
            return
        iw, ih = self._img_orig.size
        self._scale = min(cw/iw, ch/ih, 1.0)
        dw = int(iw * self._scale)
        dh = int(ih * self._scale)
        self._ox = (cw - dw) // 2
        self._oy = (ch - dh) // 2
        resized = self._img_orig.resize((dw, dh), Image.LANCZOS)
        self._img_tk = ImageTk.PhotoImage(resized)
        self._redraw()

    # ── 드로잉 ────────────────────────────────────────────
    def _redraw(self):
        self.canvas.delete("all")
        if self._img_tk:
            self.canvas.create_image(self._ox, self._oy,
                                     anchor="nw", image=self._img_tk)
        if self._sel:
            x1,y1,x2,y2 = self._sel_to_canvas()
            # 어두운 오버레이 (선택 영역 밖)
            iw = int(self._img_orig.width  * self._scale)
            ih = int(self._img_orig.height * self._scale)
            for rx,ry,rw,rh in [
                (self._ox, self._oy, iw, y1-self._oy),            # 위
                (self._ox, y2, iw, self._oy+ih-y2),               # 아래
                (self._ox, y1, x1-self._ox, y2-y1),               # 왼
                (x2, y1, self._ox+iw-x2, y2-y1),                  # 오른
            ]:
                if rw>0 and rh>0:
                    self.canvas.create_rectangle(
                        rx,ry,rx+rw,ry+rh,
                        fill="#000000", stipple="gray50", outline=""
                    )
            # 선택 테두리
            self.canvas.create_rectangle(
                x1,y1,x2,y2,
                outline=YELLOW, width=2
            )
            # 크기 표시
            sx1,sy1,sx2,sy2 = self._sel
            iw2,ih2 = self._img_orig.size
            pw = int((sx2-sx1)*iw2)
            ph = int((sy2-sy1)*ih2)
            self.canvas.create_text(
                x1+4, y1+4,
                text=f"{pw}×{ph}",
                fill=YELLOW, font=("Consolas",9),
                anchor="nw"
            )

    def _sel_to_canvas(self):
        if not self._sel or not self._img_orig:
            return 0,0,0,0
        iw,ih = self._img_orig.size
        s = self._scale
        x1 = self._ox + int(self._sel[0]*iw*s)
        y1 = self._oy + int(self._sel[1]*ih*s)
        x2 = self._ox + int(self._sel[2]*iw*s)
        y2 = self._oy + int(self._sel[3]*ih*s)
        return x1,y1,x2,y2

    def _canvas_to_ratio(self, cx, cy):
        if not self._img_orig:
            return 0.0,0.0
        iw,ih = self._img_orig.size
        rx = (cx - self._ox) / (iw * self._scale)
        ry = (cy - self._oy) / (ih * self._scale)
        return max(0.0,min(1.0,rx)), max(0.0,min(1.0,ry))

    # ── 이벤트 ────────────────────────────────────────────
    def _press(self, e):
        self._drag_start = (e.x, e.y)

    def _drag(self, e):
        if not self._drag_start:
            return
        self.canvas.delete("drag")
        sx,sy = self._drag_start
        self.canvas.create_rectangle(sx,sy,e.x,e.y,
                                     outline=YELLOW, width=2,
                                     dash=(6,3), tags="drag")
        # 실시간 크기
        rx1,ry1 = self._canvas_to_ratio(sx,sy)
        rx2,ry2 = self._canvas_to_ratio(e.x,e.y)
        rx1,rx2 = min(rx1,rx2), max(rx1,rx2)
        ry1,ry2 = min(ry1,ry2), max(ry1,ry2)
        if self._img_orig:
            iw,ih = self._img_orig.size
            pw = int((rx2-rx1)*iw)
            ph = int((ry2-ry1)*ih)
            self._sel_var.set(
                f"x1={rx1:.4f}  y1={ry1:.4f}\n"
                f"x2={rx2:.4f}  y2={ry2:.4f}\n"
                f"크기: {pw}×{ph}px"
            )

    def _release(self, e):
        self.canvas.delete("drag")
        if not self._drag_start:
            return
        sx,sy = self._drag_start
        self._drag_start = None

        rx1,ry1 = self._canvas_to_ratio(sx,sy)
        rx2,ry2 = self._canvas_to_ratio(e.x,e.y)
        rx1,rx2 = min(rx1,rx2), max(rx1,rx2)
        ry1,ry2 = min(ry1,ry2), max(ry1,ry2)

        if rx2-rx1 < 0.003 or ry2-ry1 < 0.003:
            return

        self._sel = (rx1,ry1,rx2,ry2)
        self._redraw()
        self._entry.focus_set()

    def _reset_sel(self):
        self._sel = None
        self._sel_var.set("—")
        self._redraw()

    # ── 저장 ──────────────────────────────────────────────
    def _save(self):
        if not self._sel:
            messagebox.showwarning("알림", "영역을 먼저 선택해줘")
            return
        if not self._img_orig:
            return

        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("알림", "파일명을 입력해줘")
            self._entry.focus_set()
            return

        if not name.endswith(".png"):
            name += ".png"

        iw,ih = self._img_orig.size
        x1,y1,x2,y2 = self._sel
        px1,py1 = int(x1*iw), int(y1*ih)
        px2,py2 = int(x2*iw), int(y2*ih)
        crop = self._img_orig.crop((px1,py1,px2,py2))

        out_path = SAVE_DIR / name
        crop.save(out_path)

        self._saved.append(out_path)
        self._listbox.insert(0, name)
        self._name_var.set("")
        self._sel = None
        self._sel_var.set("—")
        self._redraw()
        self._entry.focus_set()

        print(f"저장: {out_path}  ({px2-px1}×{py2-py1}px)")

    def _undo(self):
        if not self._saved:
            return
        path = self._saved.pop()
        if path.exists():
            path.unlink()
        if self._listbox.size() > 0:
            self._listbox.delete(0)
        print(f"삭제: {path}")

    def _open_folder(self):
        import os
        os.startfile(str(SAVE_DIR.resolve()))

    # ── regions.json 일괄 추출 ────────────────────────────
    def _batch_extract(self):
        if not self._img_orig:
            messagebox.showwarning("알림", "이미지를 먼저 열어줘")
            return

        json_path = filedialog.askopenfilename(
            title="regions.json 선택",
            filetypes=[("JSON", "*.json")]
        )
        if not json_path:
            return

        import json
        try:
            data = json.loads(open(json_path, encoding="utf-8").read())
        except Exception as e:
            messagebox.showerror("오류", f"JSON 읽기 실패: {e}")
            return

        iw, ih = self._img_orig.size
        count = 0
        skipped = 0

        # regions_v4.json 구조 처리
        # 최상위 키가 섹션(lobby/menu/item/...)인 경우와
        # 바로 영역인 경우 모두 지원
        def extract_region(name: str, region: dict):
            nonlocal count, skipped
            # x1/y1/x2/y2 키가 있어야 영역으로 판단
            if not all(k in region for k in ("x1","y1","x2","y2")):
                return
            x1 = int(iw * region["x1"])
            y1 = int(ih * region["y1"])
            x2 = int(iw * region["x2"])
            y2 = int(ih * region["y2"])
            if x2 <= x1 or y2 <= y1:
                skipped += 1
                return
            crop = self._img_orig.crop((x1, y1, x2, y2))
            fname = name if name.endswith(".png") else name + ".png"
            out = SAVE_DIR / fname
            crop.save(out)
            self._saved.append(out)
            self._listbox.insert(0, fname)
            count += 1
            print(f"  저장: {fname}  ({x2-x1}×{y2-y1}px)")

        def walk(prefix: str, obj):
            if isinstance(obj, dict):
                # 영역 딕셔너리면 바로 추출
                if all(k in obj for k in ("x1","y1","x2","y2")):
                    extract_region(prefix, obj)
                else:
                    # grid_slots 리스트 처리
                    if "grid_slots" in obj:
                        for i, slot in enumerate(obj["grid_slots"]):
                            walk(f"{prefix}_slot{i+1:02d}", slot)
                    # 나머지 키 재귀
                    for k, v in obj.items():
                        if k in ("grid_slots", "grid_cols", "grid_rows"):
                            continue
                        walk(f"{prefix}__{k}" if prefix else k, v)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    walk(f"{prefix}_{i+1:02d}", item)

        for section, content in data.items():
            walk(section, content)

        msg = f"완료: {count}개 추출"
        if skipped:
            msg += f"  ({skipped}개 건너뜀)"
        messagebox.showinfo("추출 완료", msg)
        print(msg)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    Extractor(path).mainloop()
