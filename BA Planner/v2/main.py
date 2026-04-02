"""
main.py — Blue Archive Analyzer v2
진입점: GUI 실행
"""

import sys
from pathlib import Path

# 패키지 경로 설정
sys.path.insert(0, str(Path(__file__).parent))

REQUIRED = {
    "customtkinter": "customtkinter",
    "PIL": "pillow",
    "pygetwindow": "pygetwindow",
    "pyautogui": "pyautogui",
    "easyocr": "easyocr",
    "numpy": "numpy",
}

missing = []
for mod, pkg in REQUIRED.items():
    try:
        __import__(mod)
    except ImportError:
        missing.append(pkg)

if missing:
    print("❌ 필요한 패키지가 없어. 아래 명령어로 설치해줘:")
    print(f"pip install {' '.join(missing)}")
    sys.exit(1)

from gui.dashboard import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
