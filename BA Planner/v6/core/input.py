"""
core/input.py — BA Analyzer v6
HWND 기반 입력 통합 모듈

설계 원칙:
  - 모든 입력은 HWND 대상으로 수행 (포커스 이동 없음)
  - PostMessage 기반 1차 시도 → 실패 시 pyautogui fallback
  - 외부 코드에서 pyautogui 직접 호출 금지
  - 모든 좌표는 "클라이언트 기준" 으로 통일

공개 인터페이스:
  click_point(hwnd, cx, cy)              → bool
  click_region(hwnd, rect, region)       → bool   (비율 좌표 → 클라이언트)
  click_center_region(hwnd, rect, region)→ bool
  send_escape(hwnd)                      → bool
  scroll(hwnd, rect, rx, ry, amount)     → bool
  screen_to_client(hwnd, sx, sy)         → (cx, cy) | None
  client_to_screen(hwnd, cx, cy)         → (sx, sy) | None
  ratio_to_client(rect, rx, ry)          → (cx, cy)

하위 호환 (capture.py 에서 이전된 함수들):
  safe_click(rect, rx, ry, label)        → bool
  click_center(rect, region, label)      → bool
  scroll_at(rect, rx, ry, amount)        → None
  press_esc()                            → None
"""

import time
import ctypes
import ctypes.wintypes as wintypes
from typing import Optional

from core.logger import get_logger, LOG_INPUT
_log = get_logger(LOG_INPUT)

# ── pyautogui 선택적 임포트 (fallback 전용) ──────────────
try:
    import pyautogui as _pag
    _pag.FAILSAFE = False   # 모서리 이동 예외 비활성화
    HAS_PAG = True
except ImportError:
    _pag  = None  # type: ignore
    HAS_PAG = False

# ── Win32 상수 ────────────────────────────────────────────
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP   = 0x0202
WM_MOUSEWHEEL  = 0x020A
WM_KEYDOWN     = 0x0100
WM_KEYUP       = 0x0101
MK_LBUTTON     = 0x0001
VK_ESCAPE      = 0x1B
WHEEL_DELTA    = 120        # Windows 표준 휠 단위

# ── Win32 API ─────────────────────────────────────────────
_u32 = ctypes.windll.user32

class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

# ── 금지 구역 (비율 좌표) ─────────────────────────────────
# capture.py 와 동일 목록 유지
FORBIDDEN_ZONES: list[tuple[float, float, float, float]] = [
    (0.53, 0.86, 1.00, 1.00),
]


# ══════════════════════════════════════════════════════════
# 좌표 변환
# ══════════════════════════════════════════════════════════

def screen_to_client(
    hwnd: int,
    sx: int,
    sy: int,
) -> Optional[tuple[int, int]]:
    """화면 절대 좌표 → HWND 클라이언트 좌표."""
    pt = _POINT(sx, sy)
    if _u32.ScreenToClient(hwnd, ctypes.byref(pt)):
        return pt.x, pt.y
    return None


def client_to_screen(
    hwnd: int,
    cx: int,
    cy: int,
) -> Optional[tuple[int, int]]:
    """HWND 클라이언트 좌표 → 화면 절대 좌표."""
    pt = _POINT(cx, cy)
    if _u32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return pt.x, pt.y
    return None


def ratio_to_client(
    rect: tuple[int, int, int, int],
    rx: float,
    ry: float,
) -> tuple[int, int]:
    """
    (left, top, w, h) rect 와 비율 좌표(rx, ry) →
    클라이언트 기준 픽셀 좌표.
    rect 는 get_window_rect() 반환값 (left, top, w, h).
    클라이언트 좌표 = (w*rx, h*ry).
    """
    _, _, w, h = rect
    return int(w * rx), int(h * ry)


def _make_lparam(cx: int, cy: int) -> int:
    """LOWORD=x, HIWORD=y 형태의 lParam 생성."""
    return (cy << 16) | (cx & 0xFFFF)


def _make_wheel_wparam(delta_clicks: int) -> int:
    """
    WM_MOUSEWHEEL 의 wParam 상위 워드 = 휠 delta.
    delta_clicks 양수 = 위로 스크롤, 음수 = 아래로.
    """
    delta = delta_clicks * WHEEL_DELTA
    return (delta & 0xFFFF) << 16


# ══════════════════════════════════════════════════════════
# PostMessage 기반 입력 (포커스 불필요)
# ══════════════════════════════════════════════════════════

def _post_click(hwnd: int, cx: int, cy: int) -> bool:
    """
    PostMessage 로 WM_LBUTTONDOWN / UP 전송.
    클라이언트 좌표 기준.
    반환: True = 전송 성공 (수신 보장 아님)
    """
    lp = _make_lparam(cx, cy)
    ok1 = bool(_u32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp))
    ok2 = bool(_u32.PostMessageW(hwnd, WM_LBUTTONUP,   0,           lp))
    return ok1 and ok2


def _post_escape(hwnd: int) -> bool:
    """WM_KEYDOWN / UP (VK_ESCAPE) 전송."""
    ok1 = bool(_u32.PostMessageW(hwnd, WM_KEYDOWN, VK_ESCAPE, 0))
    ok2 = bool(_u32.PostMessageW(hwnd, WM_KEYUP,   VK_ESCAPE, 0))
    return ok1 and ok2


def _post_scroll(hwnd: int, cx: int, cy: int, delta_clicks: int) -> bool:
    """
    WM_MOUSEWHEEL 전송.
    delta_clicks: 양수 = 위, 음수 = 아래 (pyautogui scroll 과 동일 부호)
    lParam 은 화면 좌표여야 하지만 BlueArchive 는 클라이언트 기준도 수용함.
    """
    wp = _make_wheel_wparam(delta_clicks)
    lp = _make_lparam(cx, cy)
    return bool(_u32.PostMessageW(hwnd, WM_MOUSEWHEEL, wp, lp))


# ══════════════════════════════════════════════════════════
# pyautogui fallback
# ══════════════════════════════════════════════════════════

def _pag_click(sx: int, sy: int) -> bool:
    if not HAS_PAG:
        return False
    try:
        _pag.click(sx, sy)
        return True
    except Exception as e:
        _log.warning(f"pyautogui click 실패: {e}")
        return False


def _pag_scroll(sx: int, sy: int, amount: int) -> bool:
    if not HAS_PAG:
        return False
    try:
        _pag.moveTo(sx, sy, duration=0.08)
        _pag.scroll(amount)
        return True
    except Exception as e:
        _log.warning(f"pyautogui scroll 실패: {e}")
        return False


def _pag_escape() -> bool:
    if not HAS_PAG:
        return False
    try:
        _pag.press("escape")
        return True
    except Exception as e:
        _log.warning(f"pyautogui escape 실패: {e}")
        return False


def _can_use_physical_fallback(hwnd: int) -> bool:
    from core.capture import is_window_minimized

    if is_window_minimized(hwnd):
        _log.debug("minimized target: skip physical input fallback")
        return False
    return True


# ══════════════════════════════════════════════════════════
# 공개 입력 함수
# ══════════════════════════════════════════════════════════

def click_point(
    hwnd: int,
    cx: int,
    cy: int,
    *,
    label: str = "",
    delay: float = 0.0,
) -> bool:
    """
    HWND 클라이언트 좌표 (cx, cy) 를 클릭.
    PostMessage 실패 시 화면 좌표로 변환 후 pyautogui fallback.

    Parameters
    ----------
    hwnd  : 대상 창 핸들
    cx,cy : 클라이언트 기준 픽셀 좌표
    label : 디버그 로그용 레이블
    delay : 클릭 후 대기 시간 (초)
    """
    ok = _post_click(hwnd, cx, cy)
    if not ok:
        if not _can_use_physical_fallback(hwnd):
            if delay > 0:
                time.sleep(delay)
            return False
        _log.debug(f"PostMessage 실패 → pyautogui fallback ({label})")
        sx, sy = cx, cy   # 변환 실패 시 원본 사용
        converted = client_to_screen(hwnd, cx, cy)
        if converted:
            sx, sy = converted
        ok = _pag_click(sx, sy)

    if delay > 0:
        time.sleep(delay)
    return ok


def click_region(
    hwnd: int,
    rect: tuple[int, int, int, int],
    region: dict,
    *,
    label: str = "",
    delay: float = 0.0,
) -> bool:
    """
    비율 좌표 region {x1,y1,x2,y2} 의 중심을 클릭.

    Parameters
    ----------
    hwnd   : 대상 창 핸들
    rect   : get_window_rect() 반환값 (left, top, w, h)
    region : {"x1":…, "y1":…, "x2":…, "y2":…}  0.0~1.0 비율
    """
    rx = (region["x1"] + region["x2"]) / 2
    ry = (region["y1"] + region["y2"]) / 2

    # 금지 구역 체크
    for fx1, fy1, fx2, fy2 in FORBIDDEN_ZONES:
        if fx1 <= rx <= fx2 and fy1 <= ry <= fy2:
            _log.debug(f"⛔ 금지구역 차단: {label} ({rx:.3f},{ry:.3f})")
            return False

    cx, cy = ratio_to_client(rect, rx, ry)
    return click_point(hwnd, cx, cy, label=label, delay=delay)


# 별칭 (scanner.py 호환)
click_center_region = click_region


def send_escape(
    hwnd: int,
    *,
    delay: float = 0.35,
) -> bool:
    """
    ESC 키 전송.
    PostMessage(WM_KEYDOWN/UP) 먼저 시도, 실패 시 pyautogui.

    Parameters
    ----------
    hwnd  : 대상 창 핸들
    delay : 전송 후 대기 시간 (초)
    """
    ok = _post_escape(hwnd)
    if not ok:
        if not _can_use_physical_fallback(hwnd):
            if delay > 0:
                time.sleep(delay)
            return False
        _log.debug("ESC PostMessage 실패 → pyautogui fallback")
        ok = _pag_escape()

    if delay > 0:
        time.sleep(delay)
    return ok


def scroll(
    hwnd: int,
    rect: tuple[int, int, int, int],
    rx: float,
    ry: float,
    amount: int = -3,
    *,
    delay: float = 0.30,
) -> bool:
    """
    스크롤 입력.
    PostMessage(WM_MOUSEWHEEL) 먼저 시도, 실패 시 pyautogui.

    Parameters
    ----------
    hwnd   : 대상 창 핸들
    rect   : (left, top, w, h)
    rx, ry : 스크롤 위치 비율 좌표
    amount : 스크롤 클릭 수 (음수 = 아래, 양수 = 위)
    delay  : 스크롤 후 대기 시간 (초)
    """
    cx, cy = ratio_to_client(rect, rx, ry)
    ok = _post_scroll(hwnd, cx, cy, amount)

    if not ok:
        if not _can_use_physical_fallback(hwnd):
            if delay > 0:
                time.sleep(delay)
            return False
        _log.debug("scroll PostMessage 실패 → pyautogui fallback")
        converted = client_to_screen(hwnd, cx, cy)
        sx, sy = converted if converted else (cx, cy)
        ok = _pag_scroll(sx, sy, amount)

    if delay > 0:
        time.sleep(delay)
    return ok


# ══════════════════════════════════════════════════════════
# 하위 호환 래퍼
# (capture.py 에서 이전된 함수 시그니처 그대로 유지)
# scanner.py / 기타가 수정 없이 동작하도록
# ══════════════════════════════════════════════════════════

def _get_hwnd() -> int:
    """등록된 HWND 반환. 미등록 시 0."""
    from core.capture import find_target_hwnd
    hwnd = find_target_hwnd()
    return hwnd if hwnd else 0


def safe_click(
    rect: tuple[int, int, int, int],
    rx: float,
    ry: float,
    label: str = "",
) -> bool:
    """
    하위 호환 — capture.py safe_click() 대체.
    rect + 비율 좌표 기반 클릭.
    """
    # 금지 구역 체크
    for fx1, fy1, fx2, fy2 in FORBIDDEN_ZONES:
        if fx1 <= rx <= fx2 and fy1 <= ry <= fy2:
            _log.debug(f"⛔ 금지구역: {label} ({rx:.3f},{ry:.3f})")
            return False

    hwnd = _get_hwnd()
    if hwnd:
        cx, cy = ratio_to_client(rect, rx, ry)
        return click_point(hwnd, cx, cy, label=label)

    # HWND 없으면 pyautogui 직접
    if not HAS_PAG:
        return False
    l, t, w, h = rect
    sx = int(l + w * rx)
    sy = int(t + h * ry)
    return _pag_click(sx, sy)


def click_center(
    rect: tuple[int, int, int, int],
    region: dict,
    label: str = "",
) -> bool:
    """하위 호환 — capture.py click_center() 대체."""
    rx = (region["x1"] + region["x2"]) / 2
    ry = (region["y1"] + region["y2"]) / 2
    return safe_click(rect, rx, ry, label)


def scroll_at(
    rect: tuple[int, int, int, int],
    rx: float,
    ry: float,
    amount: int = -3,
) -> None:
    """하위 호환 — capture.py scroll_at() 대체."""
    hwnd = _get_hwnd()
    if hwnd:
        scroll(hwnd, rect, rx, ry, amount)
        return

    # HWND 없으면 pyautogui
    if HAS_PAG:
        l, t, w, h = rect
        sx = int(l + w * rx)
        sy = int(t + h * ry)
        _pag_scroll(sx, sy, amount)
        time.sleep(0.30)


def press_esc() -> None:
    """하위 호환 — capture.py press_esc() 대체."""
    hwnd = _get_hwnd()
    if hwnd:
        send_escape(hwnd)
        return
    _pag_escape()
    time.sleep(0.35)
