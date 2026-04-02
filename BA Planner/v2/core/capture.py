"""
core/capture.py — 블루아카이브 윈도우 캡처
"""

import time
from PIL import Image

try:
    import pygetwindow as gw
    import pyautogui
    HAS_CAPTURE = True
except ImportError:
    HAS_CAPTURE = False

WINDOW_KEYWORDS = ["Blue Archive", "블루 아카이브", "ブルーアーカイブ"]


def find_window():
    """블루아카이브 윈도우 탐색"""
    if not HAS_CAPTURE:
        return None
    for win in gw.getAllWindows():
        for kw in WINDOW_KEYWORDS:
            if kw.lower() in win.title.lower():
                return win
    return None


def capture_window(win=None) -> Image.Image | None:
    """윈도우 캡처. win=None 이면 자동 탐색"""
    if not HAS_CAPTURE:
        return None
    if win is None:
        win = find_window()
    if win is None:
        return None
    try:
        if win.isMinimized:
            win.restore()
            time.sleep(0.5)
        win.activate()
        time.sleep(0.3)
        region = (win.left, win.top, win.width, win.height)
        return pyautogui.screenshot(region=region)
    except Exception as e:
        print(f"캡처 실패: {e}")
        return None


def get_window_size(win=None):
    """윈도우 크기 반환 (w, h)"""
    if win is None:
        win = find_window()
    if win is None:
        return None
    return win.width, win.height


def crop_region(img: Image.Image, region: dict) -> Image.Image:
    """비율 좌표로 이미지 크롭"""
    w, h = img.size
    x1 = int(w * region["x1"])
    y1 = int(h * region["y1"])
    x2 = int(w * region["x2"])
    y2 = int(h * region["y2"])
    return img.crop((x1, y1, x2, y2))


def scroll_down_in_window(win, amount: int = 3):
    """윈도우 내 그리드 영역에서 스크롤 다운"""
    if not HAS_CAPTURE:
        return
    try:
        cx = win.left + win.width // 2
        cy = win.top + win.height // 2
        pyautogui.moveTo(cx, cy, duration=0.1)
        pyautogui.scroll(-amount)
        time.sleep(0.4)
    except Exception as e:
        print(f"스크롤 실패: {e}")


def click_slot_safe(win, slot_rect: tuple, screen_w: int, screen_h: int):
    """
    슬롯 중앙 상단부만 클릭 (사용 버튼 절대 금지 구역 검사 포함)
    slot_rect: (x1, y1, x2, y2) 픽셀 좌표
    """
    if not HAS_CAPTURE:
        return

    x1, y1, x2, y2 = slot_rect
    # 슬롯 아이콘 중앙 (40% 지점, 하단 수량 텍스트 제외)
    click_x = win.left + (x1 + x2) // 2
    click_y = win.top + y1 + int((y2 - y1) * 0.4)

    # 금지 구역 (화면 비율)
    FORBIDDEN = [
        (0.53, 0.86, 1.00, 1.00),  # 사용/MIN/MAX 버튼
    ]
    rx = (click_x - win.left) / screen_w
    ry = (click_y - win.top) / screen_h
    for fx1, fy1, fx2, fy2 in FORBIDDEN:
        if fx1 <= rx <= fx2 and fy1 <= ry <= fy2:
            print(f"⛔ 금지 구역 클릭 차단: ({rx:.3f}, {ry:.3f})")
            return

    pyautogui.click(click_x, click_y)
    time.sleep(0.2)
