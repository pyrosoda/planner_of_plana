"""
Blue Archive Screen Analyzer
블루아카이브 스팀 클라이언트 화면을 캡처하고 분석하는 도구

분석 모드:
  - API 키 있음 → Claude Vision (정확)
  - API 키 없음 → Tesseract OCR (무료)
"""

import sys
import os
import re
import json
import base64
import threading
import time
from datetime import datetime
from pathlib import Path
import io

# ── 필수 패키지 체크 ───────────────────────────────────────
MISSING = []
try:
    import customtkinter as ctk
    from PIL import Image, ImageTk, ImageFilter, ImageEnhance
except ImportError:
    MISSING.append("customtkinter pillow")

try:
    import pygetwindow as gw
    import pyautogui
except ImportError:
    MISSING.append("pygetwindow pyautogui")

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

if MISSING:
    print(f"필요한 패키지가 없어: {' '.join(MISSING)}")
    print("pip install customtkinter pillow pygetwindow pyautogui anthropic pytesseract")
    sys.exit(1)


# ── 설정 ──────────────────────────────────────────────────
WINDOW_TITLE_KEYWORDS = ["Blue Archive", "블루 아카이브", "ブルーアーカイブ"]
CAPTURE_DIR = Path("captures")
CAPTURE_DIR.mkdir(exist_ok=True)

TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

ANALYSIS_PROMPT = """
이 블루아카이브 게임 스크린샷을 분석해서 아래 JSON 형식으로만 응답해줘.
다른 텍스트 없이 JSON만 반환해.

{
  "screen_type": "현재 화면 종류 (예: 로비, 학생목록, 상점, 재화현황, 전투, 이벤트, 기타)",
  "students": [
    {
      "name": "학생 이름",
      "star": "별 등급 (1~3 또는 알 수 없음)",
      "level": "레벨 (숫자 또는 알 수 없음)",
      "bond": "호감도 레벨 (숫자 또는 알 수 없음)"
    }
  ],
  "resources": {
    "pyroxene": "파이로사이트 수량 (숫자 또는 알 수 없음)",
    "credits": "크레딧 수량 (숫자 또는 알 수 없음)",
    "activity_points": "활동력 (숫자 또는 알 수 없음)",
    "gems": "보석류 기타",
    "other_items": ["기타 확인된 아이템 목록"]
  },
  "notes": "추가로 확인된 중요 정보"
}

화면에서 확인할 수 없는 항목은 null로 설정해.
"""


# ── 캡처 유틸 ─────────────────────────────────────────────
def find_blue_archive_window():
    all_windows = gw.getAllWindows()
    for win in all_windows:
        for keyword in WINDOW_TITLE_KEYWORDS:
            if keyword.lower() in win.title.lower():
                return win
    return None


def capture_window(window):
    try:
        if window.isMinimized:
            window.restore()
            time.sleep(0.5)
        window.activate()
        time.sleep(0.3)
        region = (window.left, window.top, window.width, window.height)
        return pyautogui.screenshot(region=region)
    except Exception as e:
        print(f"캡처 실패: {e}")
        return None


def image_to_base64(img):
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return base64.standard_b64encode(buffer.getvalue()).decode("utf-8")


# ── Claude Vision 분석 ────────────────────────────────────
def analyze_with_claude(img, api_key):
    if not HAS_ANTHROPIC:
        raise RuntimeError("anthropic 패키지가 없어. pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_to_base64(img),
                    },
                },
                {"type": "text", "text": ANALYSIS_PROMPT}
            ],
        }],
    )
    raw = response.content[0].text.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


# ── OCR 분석 ──────────────────────────────────────────────
def setup_tesseract():
    if not HAS_TESSERACT:
        return False
    for path in TESSERACT_PATHS:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return True
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def preprocess_for_ocr(img):
    w, h = img.size
    img = img.resize((w * 2, h * 2), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def parse_ocr_text(text):
    result = {
        "screen_type": "OCR 분석",
        "students": [],
        "resources": {
            "pyroxene": None,
            "credits": None,
            "activity_points": None,
            "gems": None,
            "other_items": []
        },
        "notes": "OCR 모드로 분석됨 (정확도가 Claude Vision보다 낮을 수 있어)"
    }

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    resource_keywords = {
        "파이로": "pyroxene", "pyroxene": "pyroxene",
        "크레딧": "credits",  "credit": "credits",
        "활동력": "activity_points", "ap": "activity_points",
        "보석": "gems", "gem": "gems",
    }

    screen_keywords = {
        "로비": "로비", "lobby": "로비",
        "학생": "학생 목록", "student": "학생 목록",
        "상점": "상점", "shop": "상점",
        "임무": "임무", "mission": "임무",
        "이벤트": "이벤트", "event": "이벤트",
        "전술": "전투", "battle": "전투",
        "편성": "편성",
    }

    for line in lines:
        lower = line.lower()

        for kw, screen in screen_keywords.items():
            if kw in lower:
                result["screen_type"] = screen
                break

        nums = re.findall(r"[\d,]+", line)
        num_val = nums[0].replace(",", "") if nums else None

        for kw, field in resource_keywords.items():
            if kw in lower and num_val:
                result["resources"][field] = num_val
                break

        lv_match = re.search(r"lv\.?\s*(\d+)", lower)
        if lv_match:
            name_candidate = re.sub(r"lv\.?\s*\d+", "", line, flags=re.IGNORECASE)
            name_candidate = re.sub(r"[^\w가-힣]", " ", name_candidate).strip()
            if name_candidate:
                result["students"].append({
                    "name": name_candidate[:20],
                    "star": None,
                    "level": lv_match.group(1),
                    "bond": None
                })

    preview = " | ".join(lines[:8])
    if len(preview) > 200:
        preview = preview[:200] + "..."
    result["notes"] += f"\n[OCR 원문 미리보기] {preview}"

    return result


def analyze_with_ocr(img):
    if not setup_tesseract():
        raise RuntimeError(
            "Tesseract가 설치되지 않았어.\n"
            "https://github.com/UB-Mannheim/tesseract/wiki 에서 설치해줘."
        )
    processed = preprocess_for_ocr(img)
    try:
        text = pytesseract.image_to_string(processed, lang="kor+eng")
    except Exception:
        text = pytesseract.image_to_string(processed, lang="eng")
    return parse_ocr_text(text)


def analyze_screenshot(img, api_key=""):
    """
    API 키 유무에 따라 자동으로 분석 방식 선택
    returns (result_dict, mode_used)
    """
    if api_key and HAS_ANTHROPIC:
        return analyze_with_claude(img, api_key), "claude"
    else:
        return analyze_with_ocr(img), "ocr"


# ── GUI ───────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BA_BLUE       = "#1a6fad"
BA_LIGHT_BLUE = "#4aa8e0"
BA_YELLOW     = "#f5c842"
BA_GREEN      = "#3dbf7a"
BA_ORANGE     = "#e8894a"
BA_BG         = "#0d1b2a"
BA_CARD       = "#152435"
BA_TEXT       = "#e8f4fd"
BA_SUBTEXT    = "#7ab3d4"


class ModeBadge(ctk.CTkFrame):
    def __init__(self, master, mode, **kwargs):
        color = BA_BLUE if mode == "claude" else BA_ORANGE
        super().__init__(master, fg_color=color, corner_radius=6, **kwargs)
        label = "🤖 Claude Vision" if mode == "claude" else "🔍 OCR 모드"
        ctk.CTkLabel(self, text=f"  {label}  ",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="white").pack(padx=4, pady=3)


class StudentCard(ctk.CTkFrame):
    def __init__(self, master, student_data, **kwargs):
        super().__init__(master, fg_color=BA_CARD, corner_radius=12, **kwargs)

        name  = student_data.get("name") or "알 수 없음"
        star  = student_data.get("star")
        level = student_data.get("level") or "?"
        bond  = student_data.get("bond") or "?"

        ctk.CTkLabel(self, text=name,
                     font=ctk.CTkFont(family="Malgun Gothic", size=14, weight="bold"),
                     text_color=BA_TEXT).pack(padx=12, pady=(10, 2))

        star_str = ("★" * int(star)) if (star and str(star).isdigit()) else "★?"
        ctk.CTkLabel(self, text=star_str,
                     font=ctk.CTkFont(size=12), text_color=BA_YELLOW).pack()

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(padx=12, pady=(4, 10))
        ctk.CTkLabel(info, text=f"Lv.{level}", font=ctk.CTkFont(size=11),
                     text_color=BA_LIGHT_BLUE).grid(row=0, column=0, padx=6)
        ctk.CTkLabel(info, text=f"호감도 {bond}", font=ctk.CTkFont(size=11),
                     text_color=BA_SUBTEXT).grid(row=0, column=1, padx=6)


class ResourcePanel(ctk.CTkFrame):
    def __init__(self, master, resources, **kwargs):
        super().__init__(master, fg_color=BA_CARD, corner_radius=12, **kwargs)

        ctk.CTkLabel(self, text="재화 현황",
                     font=ctk.CTkFont(family="Malgun Gothic", size=15, weight="bold"),
                     text_color=BA_LIGHT_BLUE).pack(padx=16, pady=(12, 6))

        for label, key in [("💎 파이로사이트", "pyroxene"), ("💰 크레딧", "credits"),
                            ("⚡ 활동력", "activity_points"), ("💠 보석류", "gems")]:
            value = resources.get(key)
            row = ctk.CTkFrame(self, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=2)
            ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=12),
                         text_color=BA_SUBTEXT, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=str(value) if value else "-",
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=BA_TEXT, anchor="e").pack(side="right")

        others = resources.get("other_items") or []
        if others:
            ctk.CTkLabel(self, text="기타 아이템",
                         font=ctk.CTkFont(size=11), text_color=BA_SUBTEXT).pack(padx=16, pady=(8, 2))
            for item in others:
                ctk.CTkLabel(self, text=f"• {item}", font=ctk.CTkFont(size=11),
                             text_color=BA_TEXT).pack(padx=20, anchor="w")
        ctk.CTkLabel(self, text="").pack(pady=4)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Blue Archive Analyzer")
        self.geometry("1100x760")
        self.minsize(900, 600)
        self.configure(fg_color=BA_BG)

        self.api_key      = ctk.StringVar()
        self.status_text  = ctk.StringVar(value="대기 중...")
        self.last_result  = None
        self.is_analyzing = False
        self.preview_image = None

        self._build_ui()
        self.after(200, self._check_ocr_available)

    def _check_ocr_available(self):
        if setup_tesseract():
            self.ocr_status_label.configure(
                text="✅ Tesseract OCR 감지됨 (API 없이도 사용 가능)",
                text_color=BA_GREEN)
        else:
            self.ocr_status_label.configure(
                text="⚠️ Tesseract 미설치 — API 키 필수\ngithub.com/UB-Mannheim/tesseract",
                text_color=BA_ORANGE)

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color=BA_CARD, corner_radius=0, height=60)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="🎓  Blue Archive  Analyzer",
                     font=ctk.CTkFont(family="Malgun Gothic", size=20, weight="bold"),
                     text_color=BA_LIGHT_BLUE).pack(side="left", padx=24, pady=10)
        ctk.CTkLabel(header, textvariable=self.status_text,
                     font=ctk.CTkFont(size=12), text_color=BA_SUBTEXT).pack(side="right", padx=24)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=12)

        left = ctk.CTkFrame(body, fg_color="transparent", width=300)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        self._build_control_panel(left)

        self.result_frame = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self.result_frame.pack(side="left", fill="both", expand=True)
        self._show_empty_state()

    def _build_control_panel(self, parent):
        api_frame = ctk.CTkFrame(parent, fg_color=BA_CARD, corner_radius=12)
        api_frame.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(api_frame, text="Anthropic API Key (선택)",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=BA_LIGHT_BLUE).pack(padx=14, pady=(12, 4), anchor="w")

        self.api_entry = ctk.CTkEntry(
            api_frame, textvariable=self.api_key,
            placeholder_text="없으면 OCR 모드로 자동 전환",
            show="*", width=260,
            fg_color="#0d1b2a", border_color=BA_BLUE)
        self.api_entry.pack(padx=14, pady=(0, 8))

        self.ocr_status_label = ctk.CTkLabel(
            api_frame, text="OCR 상태 확인 중...",
            font=ctk.CTkFont(size=10), text_color=BA_SUBTEXT, wraplength=260)
        self.ocr_status_label.pack(padx=14, pady=(0, 10))

        self.capture_btn = ctk.CTkButton(
            parent, text="📸  블루아카이브 화면 캡처 & 분석",
            font=ctk.CTkFont(family="Malgun Gothic", size=13, weight="bold"),
            fg_color=BA_BLUE, hover_color=BA_LIGHT_BLUE,
            height=44, corner_radius=10, command=self._on_capture)
        self.capture_btn.pack(fill="x", pady=(0, 6))

        ctk.CTkButton(parent, text="📁  스크린샷 파일 선택",
                      font=ctk.CTkFont(family="Malgun Gothic", size=12),
                      fg_color="#1e3a52", hover_color=BA_BLUE,
                      height=36, corner_radius=10, command=self._on_open_file
                      ).pack(fill="x", pady=(0, 10))

        preview_frame = ctk.CTkFrame(parent, fg_color=BA_CARD, corner_radius=12)
        preview_frame.pack(fill="both", expand=True)
        ctk.CTkLabel(preview_frame, text="미리보기",
                     font=ctk.CTkFont(size=11), text_color=BA_SUBTEXT).pack(pady=(10, 4))
        self.preview_label = ctk.CTkLabel(preview_frame, text="캡처 후 표시됩니다",
                                           text_color=BA_SUBTEXT, font=ctk.CTkFont(size=11))
        self.preview_label.pack(expand=True)

        ctk.CTkButton(parent, text="💾  결과 JSON 저장",
                      font=ctk.CTkFont(family="Malgun Gothic", size=12),
                      fg_color="#1e3a52", hover_color=BA_BLUE,
                      height=36, corner_radius=10, command=self._save_result
                      ).pack(fill="x", pady=(10, 0))

    def _show_empty_state(self):
        for w in self.result_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.result_frame,
            text="📋\n\nAPI 키가 있으면 Claude Vision으로,\n없으면 OCR 모드로 자동 분석해줄게\n\n블루아카이브를 실행하고 캡처해봐",
            font=ctk.CTkFont(family="Malgun Gothic", size=13),
            text_color=BA_SUBTEXT, justify="center"
        ).pack(expand=True, pady=60)

    def _show_result(self, data, mode):
        for w in self.result_frame.winfo_children():
            w.destroy()
        self.last_result = data

        top_row = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        top_row.pack(fill="x", pady=(0, 6))
        badge = ctk.CTkFrame(top_row, fg_color=BA_BLUE, corner_radius=8)
        badge.pack(side="left")
        ctk.CTkLabel(badge, text=f"  📺 {data.get('screen_type', '알 수 없음')}  ",
                     font=ctk.CTkFont(family="Malgun Gothic", size=13, weight="bold"),
                     text_color="white").pack(padx=4, pady=4)
        ModeBadge(top_row, mode).pack(side="left", padx=8)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ctk.CTkLabel(self.result_frame, text=f"분석 시간: {ts}",
                     font=ctk.CTkFont(size=11), text_color=BA_SUBTEXT).pack(anchor="w", pady=(0, 10))

        resources = data.get("resources") or {}
        if any(v for v in resources.values() if v):
            ResourcePanel(self.result_frame, resources).pack(fill="x", pady=(0, 14))

        students = data.get("students") or []
        if students:
            ctk.CTkLabel(self.result_frame,
                         text=f"학생 정보  ({len(students)}명)",
                         font=ctk.CTkFont(family="Malgun Gothic", size=14, weight="bold"),
                         text_color=BA_LIGHT_BLUE).pack(anchor="w", pady=(0, 8))
            grid = ctk.CTkFrame(self.result_frame, fg_color="transparent")
            grid.pack(fill="x")
            cols = 3
            for i, s in enumerate(students):
                StudentCard(grid, s).grid(row=i // cols, column=i % cols,
                                          padx=6, pady=6, sticky="nsew")
            for c in range(cols):
                grid.columnconfigure(c, weight=1)

        notes = data.get("notes") or ""
        if notes:
            note_frame = ctk.CTkFrame(self.result_frame, fg_color="#1a2e40", corner_radius=10)
            note_frame.pack(fill="x", pady=(14, 0))
            ctk.CTkLabel(note_frame, text="📝 " + notes,
                         font=ctk.CTkFont(family="Malgun Gothic", size=11),
                         text_color=BA_SUBTEXT, wraplength=580, justify="left").pack(padx=14, pady=10)

    def _update_preview(self, img):
        img_copy = img.copy()
        img_copy.thumbnail((268, 180), Image.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(img_copy)
        self.preview_label.configure(image=self.preview_image, text="")

    def _run_analysis(self, img):
        api_key = self.api_key.get().strip()
        mode_label = "Claude Vision" if api_key else "OCR"
        self.status_text.set(f"🔍 {mode_label}로 분석 중...")
        result, mode = analyze_screenshot(img, api_key)
        self.after(0, lambda: self._show_result(result, mode))
        self.status_text.set(f"✅ {mode_label} 분석 완료")

    def _on_capture(self):
        if self.is_analyzing:
            return
        api_key = self.api_key.get().strip()
        if not api_key and not setup_tesseract():
            self.status_text.set("❌ API 키 또는 Tesseract가 필요해")
            return
        win = find_blue_archive_window()
        if not win:
            self.status_text.set("❌ 블루아카이브 윈도우를 찾지 못했어")
            return
        self.status_text.set(f"📸 '{win.title}' 캡처 중...")

        def task():
            self.is_analyzing = True
            self.capture_btn.configure(state="disabled", text="분석 중...")
            try:
                img = capture_window(win)
                if img is None:
                    self.status_text.set("❌ 캡처 실패")
                    return
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                img.save(CAPTURE_DIR / f"capture_{ts}.png")
                self.after(0, lambda: self._update_preview(img))
                self._run_analysis(img)
            except Exception as e:
                self.status_text.set(f"❌ 오류: {e}")
            finally:
                self.is_analyzing = False
                self.after(0, lambda: self.capture_btn.configure(
                    state="normal", text="📸  블루아카이브 화면 캡처 & 분석"))

        threading.Thread(target=task, daemon=True).start()

    def _on_open_file(self):
        from tkinter import filedialog
        api_key = self.api_key.get().strip()
        if not api_key and not setup_tesseract():
            self.status_text.set("❌ API 키 또는 Tesseract가 필요해")
            return
        path = filedialog.askopenfilename(
            title="스크린샷 파일 선택",
            filetypes=[("이미지 파일", "*.png *.jpg *.jpeg *.bmp")])
        if not path:
            return

        def task():
            self.is_analyzing = True
            try:
                img = Image.open(path)
                self.after(0, lambda: self._update_preview(img))
                self._run_analysis(img)
            except Exception as e:
                self.status_text.set(f"❌ 오류: {e}")
            finally:
                self.is_analyzing = False

        threading.Thread(target=task, daemon=True).start()

    def _save_result(self):
        if not self.last_result:
            self.status_text.set("⚠️ 저장할 결과가 없어")
            return
        from tkinter import filedialog
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"ba_result_{ts}.json",
            filetypes=[("JSON 파일", "*.json")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.last_result, f, ensure_ascii=False, indent=2)
            self.status_text.set(f"💾 저장 완료: {Path(path).name}")


if __name__ == "__main__":
    app = App()
    app.mainloop()
