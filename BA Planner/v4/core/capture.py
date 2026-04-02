"""
core/capture.py — 블루아카이브 윈도우 캡처 + 클릭/스크롤

변경점:
  - 창 전체 rect 대신 client area 기준 사용
  - 창 테두리 / 제목바 / DPI 영향으로 인한 비율 좌표 오차 감소
  - HWND로 선택된 창을 안정적으로 추적
"""
import time
import ctypes
from ctypes import wintypes
from PIL import Image

try:
    import pygetwindow as gw
    import pyautogui
    HAS_CAPTURE = True
except ImportError:
    HAS_CAPTURE = False

FORBIDDEN_ZONES = [
    (0.53, 0.86, 1.00, 1.00),  # 사용/MIN/MAX 버튼
]

# ── Win32 API 설정 ──────────────────────────────────────
user32 = ctypes.windll.user32

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]

try:
    # 프로세스 DPI aware 설정
    user32.SetProcessDPIAware()
except Exception:
    pass


# ── 선택된 창 핸들 (전역) ────────────────────────────────
_selected_hwnd: int | None = None
_selected_title: str = ""


def set_target_window(hwnd: int, title: str):
    """사용자가 선택한 창 핸들 저장"""
    global _selected_hwnd, _selected_title
    _selected_hwnd = hwnd
    _selected_title = title
    print(f"[Capture] 타겟 창 설정: '{title}' (HWND={hwnd})")


def get_target_info() -> tuple[int | None, str]:
    return _selected_hwnd, _selected_title


def clear_target():
    global _selected_hwnd, _selected_title
    _selected_hwnd = None
    _selected_title = ""


def _get_window_by_hwnd(hwnd: int):
    """HWND로 pygetwindow 창 객체 가져오기"""
    if not HAS_CAPTURE:
        return None
    for win in gw.getAllWindows():
        try:
            if win._hWnd == hwnd:
                return win
        except Exception:
            pass
    return None


def _is_window(hwnd: int) -> bool:
    try:
        return bool(user32.IsWindow(hwnd))
    except Exception:
        return False


def _get_client_rect_screen(hwnd: int) -> tuple[int, int, int, int] | None:
    """
    선택된 HWND의 client area를 화면 좌표 기준으로 반환.
    return: (left, top, width, height)
    """
    if not hwnd or not _is_window(hwnd):
        return None

    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None

    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    pt = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None

    return pt.x, pt.y, width, height


def find_window():
    """선택된 HWND로 창 찾기. 없으면 None 반환"""
    if not HAS_CAPTURE:
        return None
    if _selected_hwnd is None:
        print("[Capture] 타겟 창이 설정되지 않았어")
        return None

    if not _is_window(_selected_hwnd):
        print(f"[Capture] HWND={_selected_hwnd} 창이 유효하지 않아 (종료됐을 수 있음)")
        return None

    win = _get_window_by_hwnd(_selected_hwnd)
    if win is None:
        print(f"[Capture] HWND={_selected_hwnd} 창을 pygetwindow에서 찾지 못했어")
    return win


def get_all_windows() -> list[dict]:
    """
    현재 실행 중인 모든 창 목록 반환.
    창 선택 UI에서 사용.
    """
    if not HAS_CAPTURE:
        return []

    result = []
    for win in gw.getAllWindows():
        title = win.title.strip()
        if not title:
            continue

        try:
            hwnd = win._hWnd
            client_rect = _get_client_rect_screen(hwnd)

            if client_rect is not None:
                _, _, cw, ch = client_rect
                size_text = f"{cw}×{ch}"
            else:
                size_text = f"{win.width}×{win.height}"

            result.append({
                "hwnd": hwnd,
                "title": title,
                "size": size_text,
            })
        except Exception:
            pass

    return result


def get_window_rect():
    """
    기존 함수명 유지.
    이제는 window rect가 아니라 client area rect를 반환.
    return: (left, top, width, height)
    """
    if _selected_hwnd is None:
        return None
    rect = _get_client_rect_screen(_selected_hwnd)
    if rect is None:
        print("[Capture] client area rect를 가져오지 못했어")
    return rect


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

        # 필요할 때만 활성화
        try:
            if not win.isActive:
                win.activate()
                time.sleep(0.2)
        except Exception:
            pass

        rect = get_window_rect()
        if rect is None:
            print("[Capture] client area 기준 rect 확보 실패")
            return None

        left, top, width, height = rect
        if width <= 0 or height <= 0:
            print(f"[Capture] 잘못된 client size: {width}x{height}")
            return None

        return pyautogui.screenshot(region=(left, top, width, height))

    except Exception as e:
        print(f"[Capture] 캡처 실패: {e}")
        return None


def crop_ratio(img: Image.Image, region: dict) -> Image.Image:
    w, h = img.size
    return img.crop((
        int(w * region["x1"]), int(h * region["y1"]),
        int(w * region["x2"]), int(h * region["y2"])
    ))


def ratio_to_screen(rect, rx: float, ry: float) -> tuple[int, int]:
    l, t, w, h = rect
    return int(l + w * rx), int(t + h * ry)


def safe_click(rect, rx: float, ry: float, label: str = "") -> bool:
    if not HAS_CAPTURE:
        return False

    for fx1, fy1, fx2, fy2 in FORBIDDEN_ZONES:
        if fx1 <= rx <= fx2 and fy1 <= ry <= fy2:
            print(f"[Capture] ⛔ 금지구역 차단: {label} ({rx:.3f},{ry:.3f})")
            return False

    x, y = ratio_to_screen(rect, rx, ry)
    pyautogui.click(x, y)
    return True


def click_center(rect, region: dict, label: str = "") -> bool:
    rx = (region["x1"] + region["x2"]) / 2
    ry = (region["y1"] + region["y2"]) / 2
    return safe_click(rect, rx, ry, label)


def scroll_at(rect, rx: float, ry: float, amount: int = -3):
    if not HAS_CAPTURE:
        return
    x, y = ratio_to_screen(rect, rx, ry)
    pyautogui.moveTo(x, y, duration=0.1)
    pyautogui.scroll(amount)
    time.sleep(0.35)


def press_esc():
    if HAS_CAPTURE:
        pyautogui.press("escape")
        time.sleep(0.4)