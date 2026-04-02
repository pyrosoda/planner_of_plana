import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import pyautogui
import pygetwindow as gw
from PIL import Image, ImageTk

APP_TITLE = "BA Region Capture Tool"
JSON_FILENAME = "student_name.json"
REGION_KEY = "student_name_region"

WINDOW_KEYWORDS = [
    "Blue Archive", "블루 아카이브", "ブルーアーカイブ",
    "LDPlayer", "BlueStacks", "MuMu", "Nox"
]

WHITE_THRESHOLD = 210  # 이 값 이상이면 흰색 글자로 간주


def resource_dir() -> Path:
    return Path(__file__).resolve().parent


def load_region(json_path: Path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    region = data.get(REGION_KEY)
    if not region:
        raise ValueError(f"JSON 안에 '{REGION_KEY}' 영역이 없습니다.")

    return (
        float(region["x1"]),
        float(region["y1"]),
        float(region["x2"]),
        float(region["y2"]),
    )


def is_valid_target_window(win):
    try:
        if not win.title:
            return False
        if win.title == APP_TITLE:
            return False
        if win.width < 300 or win.height < 200:
            return False
        return True
    except Exception:
        return False


def find_blue_archive_window():
    candidates = []
    for win in gw.getAllWindows():
        if not is_valid_target_window(win):
            continue

        title = win.title.lower()
        if any(keyword.lower() in title for keyword in WINDOW_KEYWORDS):
            candidates.append(win)

    if not candidates:
        return None

    candidates.sort(key=lambda w: w.width * w.height, reverse=True)
    return candidates[0]


def crop_region_from_window(win, region_ratio):
    x1r, y1r, x2r, y2r = region_ratio

    left = max(0, win.left)
    top = max(0, win.top)
    width = win.width
    height = win.height

    screenshot = pyautogui.screenshot(region=(left, top, width, height))

    x1 = int(width * x1r)
    y1 = int(height * y1r)
    x2 = int(width * x2r)
    y2 = int(height * y2r)

    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(x1 + 1, min(x2, width))
    y2 = max(y1 + 1, min(y2, height))

    return screenshot.crop((x1, y1, x2, y2))


def white_text_to_binary(img: Image.Image, threshold: int = WHITE_THRESHOLD) -> Image.Image:
    """
    흰색 계열 글자는 흰색(255), 나머지는 검은색(0)으로 변환
    """
    rgb = img.convert("RGB")
    out = Image.new("L", rgb.size, 0)
    src = rgb.load()
    dst = out.load()

    w, h = rgb.size
    for y in range(h):
        for x in range(w):
            r, g, b = src[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                dst[x, y] = 255
            else:
                dst[x, y] = 0

    return out


class CaptureApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("520x420")
        self.root.resizable(False, False)

        self.base_dir = resource_dir()
        self.json_path = self.base_dir / JSON_FILENAME

        if not self.json_path.exists():
            messagebox.showerror("오류", f"{JSON_FILENAME} 파일을 찾을 수 없습니다.")
            root.destroy()
            return

        try:
            self.region_ratio = load_region(self.json_path)
        except Exception as e:
            messagebox.showerror("오류", f"JSON 로드 실패:\n{e}")
            root.destroy()
            return

        self.preview_label = tk.Label(root, text="아직 캡처된 이미지가 없답니다.", bd=1, relief="sunken")
        self.preview_label.pack(padx=12, pady=12, fill="both", expand=True)

        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=8)

        capture_btn = tk.Button(btn_frame, text="캡처 + 흑백변환", command=self.capture_and_save, width=18, height=2)
        capture_btn.pack(side="left", padx=6)

        refresh_btn = tk.Button(btn_frame, text="창 다시 찾기", command=self.show_target_window_info, width=12, height=2)
        refresh_btn.pack(side="left", padx=6)

        info_text = (
            "흰색 글자만 남기고 나머지는 검은색으로 변환합니다.\n"
            f"현재 threshold = {WHITE_THRESHOLD}"
        )
        self.info_label = tk.Label(root, text=info_text, justify="center")
        self.info_label.pack(pady=(0, 12))

        self.tk_preview = None
        self.show_target_window_info()

    def show_target_window_info(self):
        win = find_blue_archive_window()
        if win is None:
            messagebox.showwarning("창 탐색", "블루 아카이브 관련 창을 찾지 못했습니다.\n에뮬레이터 창이 켜져 있는지 확인해주세요.")
        else:
            messagebox.showinfo("탐색 결과", f"인식된 창:\n{win.title}")

    def update_preview(self, img: Image.Image):
        preview = img.copy()
        preview.thumbnail((480, 280))
        self.tk_preview = ImageTk.PhotoImage(preview)
        self.preview_label.config(image=self.tk_preview, text="")

    def capture_and_save(self):
        try:
            win = find_blue_archive_window()
            if win is None:
                messagebox.showerror("오류", "블루 아카이브 관련 창을 찾지 못했습니다.")
                return

            cropped = crop_region_from_window(win, self.region_ratio)
            binary_img = white_text_to_binary(cropped)

            default_path = self.base_dir / "captured_name_bw.png"
            save_path = filedialog.asksaveasfilename(
                title="저장할 파일 이름을 정해주세요",
                initialdir=str(self.base_dir),
                initialfile=default_path.name,
                defaultextension=".png",
                filetypes=[("PNG Image", "*.png")]
            )

            if not save_path:
                return

            binary_img.save(save_path)
            self.update_preview(binary_img)
            messagebox.showinfo("완료", f"저장 완료:\n{save_path}")

        except Exception as e:
            messagebox.showerror("오류", str(e))


def main():
    root = tk.Tk()
    app = CaptureApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
