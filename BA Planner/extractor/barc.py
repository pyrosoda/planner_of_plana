import json
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from PIL import Image, ImageTk
except ImportError:
    print("Pillow가 필요합니다. pip install pillow")
    raise

try:
    import pygetwindow as gw
    import pyautogui
except ImportError:
    print("pygetwindow, pyautogui가 필요합니다. pip install pygetwindow pyautogui")
    raise

WINDOW_KEYWORDS = ["Blue Archive", "블루 아카이브", "ブルーアーカイブ"]
APP_DIR = Path(__file__).resolve().parent
DEFAULT_JSON = APP_DIR / "student_name.json"


class RegionCaptureApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BA Region Capture Tool")
        self.geometry("820x720")
        self.minsize(760, 650)

        self.json_path = tk.StringVar(value=str(DEFAULT_JSON if DEFAULT_JSON.exists() else APP_DIR))
        self.region_name = tk.StringVar(value="student_name_region")
        self.status_var = tk.StringVar(value="준비 완료")
        self.window_title_var = tk.StringVar(value="미탐지")
        self.save_name_var = tk.StringVar(value="student_name")
        self.save_dir_var = tk.StringVar(value=str(APP_DIR))

        self.region_data = {}
        self.preview_tk = None

        self._build_ui()
        self._try_load_default_json()
        self.refresh_window_status()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="JSON 파일").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.json_path).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(top, text="찾기", command=self.browse_json).grid(row=0, column=2)
        ttk.Button(top, text="불러오기", command=self.load_json).grid(row=0, column=3, padx=(8, 0))

        ttk.Label(top, text="영역 이름").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.region_combo = ttk.Combobox(top, textvariable=self.region_name, state="readonly")
        self.region_combo.grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(10, 0))
        self.region_combo.bind("<<ComboboxSelected>>", lambda e: self.update_status("영역 선택 완료"))

        ttk.Button(top, text="창 다시 찾기", command=self.refresh_window_status).grid(row=1, column=2, pady=(10, 0))
        ttk.Button(top, text="캡처", command=self.capture_selected_region).grid(row=1, column=3, padx=(8, 0), pady=(10, 0))

        info = ttk.LabelFrame(self, text="현재 상태", padding=12)
        info.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        info.columnconfigure(1, weight=1)

        ttk.Label(info, text="인식된 창").grid(row=0, column=0, sticky="w")
        ttk.Label(info, textvariable=self.window_title_var).grid(row=0, column=1, sticky="w", padx=(8, 0), columnspan=2)

        ttk.Label(info, text="저장 파일명").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(info, textvariable=self.save_name_var).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(10, 0), columnspan=2)

        ttk.Label(info, text="저장 폴더").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(info, textvariable=self.save_dir_var).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
        ttk.Button(info, text="폴더 선택", command=self.browse_save_dir).grid(row=2, column=2, sticky="e", padx=(8, 0), pady=(10, 0))

        preview_frame = ttk.LabelFrame(self, text="미리보기", padding=12)
        preview_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 12))
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        self.preview_label = ttk.Label(preview_frame, anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def update_status(self, text: str):
        self.status_var.set(text)
        self.update_idletasks()

    def _try_load_default_json(self):
        if DEFAULT_JSON.exists():
            self.load_json()
        else:
            self.update_status("기본 JSON 파일이 같은 폴더에 없습니다.")

    def browse_json(self):
        path = filedialog.askopenfilename(
            title="영역 JSON 파일 선택",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialdir=str(APP_DIR),
        )
        if path:
            self.json_path.set(path)
            self.load_json()

    def browse_save_dir(self):
        path = filedialog.askdirectory(title="저장 폴더 선택", initialdir=self.save_dir_var.get() or str(APP_DIR))
        if path:
            self.save_dir_var.set(path)
            self.update_status(f"저장 폴더 설정: {Path(path).name}")

    def load_json(self):
        path = Path(self.json_path.get())
        if path.is_dir():
            messagebox.showinfo("알림", "JSON 파일을 직접 선택해주세요.")
            return
        if not path.exists():
            messagebox.showerror("오류", f"JSON 파일을 찾을 수 없습니다.\n{path}")
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            messagebox.showerror("오류", f"JSON 로드 실패:\n{e}")
            return

        valid = {k: v for k, v in data.items() if self._is_valid_region(v)}
        if not valid:
            messagebox.showerror("오류", '유효한 영역 정보가 없습니다.\n형식: {"name": {"x1":..., "y1":..., "x2":..., "y2":...}}')
            return

        self.region_data = valid
        names = list(valid.keys())
        self.region_combo["values"] = names
        if self.region_name.get() not in names:
            self.region_name.set(names[0])
        self.update_status(f"JSON 로드 완료: {path.name}")

    @staticmethod
    def _is_valid_region(region):
        if not isinstance(region, dict):
            return False
        keys = {"x1", "y1", "x2", "y2"}
        if not keys.issubset(region.keys()):
            return False
        try:
            x1, y1, x2, y2 = [float(region[k]) for k in ("x1", "y1", "x2", "y2")]
        except Exception:
            return False
        return 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1

    def find_blue_archive_window(self):
        current_app_title = self.title().strip().lower()
        candidates = []

        for win in gw.getAllWindows():
            title = (win.title or "").strip()
            if not title:
                continue
            lower_title = title.lower()

            if lower_title == current_app_title:
                continue

            if getattr(win, "width", 0) <= 300 or getattr(win, "height", 0) <= 200:
                continue

            for kw in WINDOW_KEYWORDS:
                if kw.lower() in lower_title:
                    candidates.append(win)
                    break

        if not candidates:
            return None

        candidates.sort(key=lambda w: w.width * w.height, reverse=True)
        return candidates[0]

    def refresh_window_status(self):
        win = self.find_blue_archive_window()
        if win is None:
            self.window_title_var.set("찾지 못함")
            self.update_status("블루 아카이브 창을 찾지 못했습니다.")
        else:
            self.window_title_var.set(f"{win.title} ({win.width}x{win.height})")
            self.update_status("블루 아카이브 창을 찾았습니다.")

    def capture_selected_region(self):
        if not self.region_data:
            messagebox.showwarning("주의", "먼저 JSON 파일을 불러와주세요.")
            return

        region_key = self.region_name.get()
        region = self.region_data.get(region_key)
        if region is None:
            messagebox.showwarning("주의", "캡처할 영역을 선택해주세요.")
            return

        win = self.find_blue_archive_window()
        if win is None:
            messagebox.showerror("오류", "블루 아카이브 창을 찾지 못했습니다.")
            self.refresh_window_status()
            return

        try:
            if getattr(win, "isMinimized", False):
                win.restore()
                time.sleep(0.5)
            win.activate()
            time.sleep(0.3)
        except Exception:
            pass

        try:
            screenshot = pyautogui.screenshot(region=(win.left, win.top, win.width, win.height))
        except Exception as e:
            messagebox.showerror("오류", f"창 캡처 실패:\n{e}")
            return

        cropped = self.crop_region(screenshot, region)
        self.show_preview(cropped)

        default_name = self.save_name_var.get().strip() or region_key
        save_dir = Path(self.save_dir_var.get().strip() or str(APP_DIR))

        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("오류", f"저장 폴더를 만들 수 없습니다:\n{e}")
            return

        save_path = save_dir / f"{default_name}.png"

        try:
            cropped.save(save_path)
        except Exception as e:
            messagebox.showerror("오류", f"파일 저장 실패:\n{e}")
            return

        self.update_status(f"저장 완료: {save_path.name}")

    @staticmethod
    def crop_region(image, region):
        w, h = image.size
        x1 = int(w * float(region["x1"]))
        y1 = int(h * float(region["y1"]))
        x2 = int(w * float(region["x2"]))
        y2 = int(h * float(region["y2"]))
        return image.crop((x1, y1, x2, y2))

    def show_preview(self, image):
        preview = image.copy()
        preview.thumbnail((720, 460))
        self.preview_tk = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.preview_tk)


if __name__ == "__main__":
    try:
        app = RegionCaptureApp()
        app.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
