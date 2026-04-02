"""
core/capture.py — 윈도우 캡처 + 좌표 클릭
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

# 절대 클릭 금지 구역 (화면 비율)
# 아이템/장비 화면의 사용 버튼 영역
FORBIDDEN_ZONES = [
    (0.53, 0.86, 1.00, 1.00),
]


def find_window():
    if not HAS_CAPTURE:
        print("[Capture] pygetwindow/pyautogui 없음")
        return None
    all_wins = gw.getAllWindows()
    titles = [w.title for w in all_wins if w.title.strip()]
    print(f"[Capture] 전체 창 목록: {titles[:10]}")  # 최대 10개만 출력
    for win in all_wins:
        for kw in WINDOW_KEYWORDS:
            if kw.lower() in win.title.lower():
                print(f"[Capture] 블루아카이브 창 발견: '{win.title}'")
                return win
    print("[Capture] 블루아카이브 창 없음 (키워드: " + str(WINDOW_KEYWORDS) + ")")
    return None


def get_window_rect():
    """(left, top, width, height) 반환. 없으면 None"""
    win = find_window()
    if not win:
        return None
    return win.left, win.top, win.width, win.height


def capture_window() -> Image.Image | None:
    if not HAS_CAPTURE:
        return None
    win = find_window()
    if not win:
        return None
    try:
        if win.isMinimized:
            win.restore()
            time.sleep(0.4)
        win.activate()
        time.sleep(0.25)
        return pyautogui.screenshot(
            region=(win.left, win.top, win.width, win.height)
        )
    except Exception as e:
        print(f"캡처 실패: {e}")
        return None


def crop_ratio(img: Image.Image, r: dict) -> Image.Image:
    """비율 좌표로 크롭. r = {x1,y1,x2,y2} (0~1)"""
    w, h = img.size
    return img.crop((
        int(w * r["x1"]), int(h * r["y1"]),
        int(w * r["x2"]), int(h * r["y2"])
    ))


def ratio_to_pixel(win_rect, rx: float, ry: float):
    """비율 좌표 → 스크린 절대 픽셀"""
    l, t, w, h = win_rect
    return int(l + w * rx), int(t + h * ry)


def safe_click(win_rect, rx: float, ry: float, label: str = ""):
    """비율 좌표로 안전 클릭 (금지 구역 차단)"""
    if not HAS_CAPTURE:
        return False
    for fx1, fy1, fx2, fy2 in FORBIDDEN_ZONES:
        if fx1 <= rx <= fx2 and fy1 <= ry <= fy2:
            print(f"⛔ 금지 구역 차단: {label} ({rx:.3f},{ry:.3f})")
            return False
    x, y = ratio_to_pixel(win_rect, rx, ry)
    pyautogui.click(x, y)
    return True


def scroll_at(win_rect, rx: float, ry: float, amount: int = -3):
    """비율 좌표 위치에서 스크롤"""
    if not HAS_CAPTURE:
        return
    x, y = ratio_to_pixel(win_rect, rx, ry)
    pyautogui.moveTo(x, y, duration=0.1)
    pyautogui.scroll(amount)
    time.sleep(0.35)


def press_esc():
    pyautogui.press("escape")
    time.sleep(0.4)