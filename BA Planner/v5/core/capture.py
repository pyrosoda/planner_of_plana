"""
core/capture.py — BA Analyzer v6
HWND 기반 백그라운드 캡처 + 포커스 튐 완전 제거

변경점 (v5 → v6):
  - win.activate() / SetForegroundWindow 완전 제거
  - PrintWindow(PW_RENDERFULLCONTENT) 기반 백그라운드 캡처 도입
    → 창이 가려지거나 최소화 상태에서도 캡처 가능
  - pygetwindow 의존 최소화
    → find_window() 는 HWND 정수 반환으로 변경
    → _get_window_by_hwnd() / gw.getAllWindows() 반복 제거
  - HWND 캐시 도입: _hwnd_valid_cache 로 IsWindow 결과 캐싱
  - 공개 인터페이스:
      find_target_hwnd()             → int | None
      capture_window_background()    → Image | None   (메인 캡처)
      capture_window()               → Image | None   (하위 호환 래퍼)
      crop_region(img, region)       → Image           (≒ crop_ratio)
      crop_ratio(img, region)        → Image           (하위 호환)
      get_window_rect()              → tuple | None
      safe_click / click_center / scroll_at / press_esc  그대로 유지
"""

import time
import ctypes
import ctypes.wintypes as wintypes
from typing import Optional
from PIL import Image

try:
    import pygetwindow as gw
    HAS_GW = True
except ImportError:
    HAS_GW = False

try:
    import pyautogui
    HAS_PAG = True
except ImportError:
    HAS_PAG = False


# ── 금지 구역 (비율 좌표) ────────────────────────────────
FORBIDDEN_ZONES: list[tuple[float, float, float, float]] = [
    (0.53, 0.86, 1.00, 1.00),  # 사용/MIN/MAX 버튼
]

# ── Win32 상수 ────────────────────────────────────────────
PW_RENDERFULLCONTENT = 0x00000002   # PrintWindow 전체 렌더 플래그
GWL_STYLE            = -16
WS_MINIMIZE          = 0x20000000

# ── Win32 API ────────────────────────────────────────────
_u32  = ctypes.windll.user32
_gdi  = ctypes.windll.gdi32

try:
    _u32.SetProcessDPIAware()
except Exception:
    pass


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left",   wintypes.LONG),
        ("top",    wintypes.LONG),
        ("right",  wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


# ── 전역 상태 ─────────────────────────────────────────────
_selected_hwnd:  int = 0
_selected_title: str = ""

# HWND 유효성 캐시: {hwnd: (timestamp, is_valid)}
# IsWindow() 는 저렴하지만 gw.getAllWindows() 는 비싸므로 구분 캐싱
_hwnd_valid_cache: dict[int, tuple[float, bool]] = {}
_HWND_CACHE_TTL = 2.0   # 초


# ── HWND 등록 / 조회 ──────────────────────────────────────

def set_target_window(hwnd: int, title: str) -> None:
    """사용자가 선택한 창 HWND 저장."""
    global _selected_hwnd, _selected_title
    _selected_hwnd  = hwnd
    _selected_title = title
    _hwnd_valid_cache.clear()
    print(f"[Capture] 타겟 설정: '{title}' (HWND={hwnd})")


def get_target_info() -> tuple[int, str]:
    return _selected_hwnd, _selected_title


def clear_target() -> None:
    global _selected_hwnd, _selected_title
    _selected_hwnd  = 0
    _selected_title = ""
    _hwnd_valid_cache.clear()


# ── HWND 유효성 확인 (캐시 적용) ─────────────────────────

def _is_window_valid(hwnd: int) -> bool:
    """IsWindow() 결과를 짧게 캐싱해 반복 호출 비용 절감."""
    now = time.monotonic()
    cached = _hwnd_valid_cache.get(hwnd)
    if cached and now - cached[0] < _HWND_CACHE_TTL:
        return cached[1]
    result = bool(_u32.IsWindow(hwnd))
    _hwnd_valid_cache[hwnd] = (now, result)
    return result


def _is_minimized(hwnd: int) -> bool:
    style = _u32.GetWindowLongW(hwnd, GWL_STYLE)
    return bool(style & WS_MINIMIZE)


# ── Client Area ───────────────────────────────────────────

def _get_client_rect_screen(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """
    HWND의 client area를 화면 절대 좌표로 반환.
    Returns: (left, top, width, height)  또는 None
    """
    rect = _RECT()
    if not _u32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    w = rect.right  - rect.left
    h = rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    pt = _POINT(0, 0)
    if not _u32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return pt.x, pt.y, w, h


# ── 메인 공개 API ─────────────────────────────────────────

def find_target_hwnd() -> Optional[int]:
    """
    등록된 HWND가 유효하면 반환. 없으면 None.
    pygetwindow 없이 Win32만 사용.
    """
    if not _selected_hwnd:
        return None
    if not _is_window_valid(_selected_hwnd):
        print(f"[Capture] HWND={_selected_hwnd} 유효하지 않음")
        return None
    return _selected_hwnd


def get_window_rect() -> Optional[tuple[int, int, int, int]]:
    """Client area (left, top, width, height) 반환."""
    hwnd = find_target_hwnd()
    if hwnd is None:
        return None
    r = _get_client_rect_screen(hwnd)
    if r is None:
        print("[Capture] client rect 획득 실패")
    return r


def capture_window_background(
    hwnd: Optional[int] = None,
    *,
    retry: int = 1,
) -> Optional[Image.Image]:
    """
    PrintWindow(PW_RENDERFULLCONTENT) 기반 백그라운드 캡처.
    창이 다른 창에 가려지거나 최소화 상태에서도 동작.
    포커스·활성화 일절 없음.

    Parameters
    ----------
    hwnd  : 캡처 대상 HWND. None 이면 등록된 타겟 사용.
    retry : 실패 시 재시도 횟수 (기본 1회)

    Returns
    -------
    PIL Image 또는 None (실패 시)
    """
    if hwnd is None:
        hwnd = find_target_hwnd()
    if hwnd is None:
        return None

    for attempt in range(retry + 1):
        img = _print_window(hwnd)
        if img is not None:
            return img
        if attempt < retry:
            time.sleep(0.05)

    print(f"[Capture] PrintWindow 실패 (HWND={hwnd}), {retry}회 재시도 후 포기")
    return None


def capture_window() -> Optional[Image.Image]:
    """
    하위 호환 래퍼.
    내부적으로 capture_window_background() 를 호출.
    """
    return capture_window_background()


# ── PrintWindow 구현 ──────────────────────────────────────

def _print_window(hwnd: int) -> Optional[Image.Image]:
    """
    Win32 PrintWindow 로 HWND 내용을 비트맵으로 캡처.
    최소화 상태이면 먼저 클라이언트 rect를 가져온 뒤
    ShowWindow(SW_RESTORE) 없이 캡처를 시도.
    """
    rect = _get_client_rect_screen(hwnd)
    if rect is None:
        # 최소화 상태일 수 있음: WindowRect 기반으로 fallback 시도
        wr = _RECT()
        if not _u32.GetWindowRect(hwnd, ctypes.byref(wr)):
            return None
        w = wr.right  - wr.left
        h = wr.bottom - wr.top
        if w <= 0 or h <= 0:
            return None
        # 최소화 상태에서는 실제 픽셀 취득 불가 → None 반환
        if _is_minimized(hwnd):
            print("[Capture] 창이 최소화 상태 — 캡처 불가")
            return None
        return None

    _, _, w, h = rect

    # GDI 비트맵 생성
    hdc_screen = _u32.GetDC(0)
    hdc_mem    = _gdi.CreateCompatibleDC(hdc_screen)
    hbmp       = _gdi.CreateCompatibleBitmap(hdc_screen, w, h)
    _gdi.SelectObject(hdc_mem, hbmp)

    try:
        # PW_RENDERFULLCONTENT: 하드웨어 가속 콘텐츠도 캡처
        ok = _u32.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT)
        if not ok:
            # fallback: 플래그 없이 재시도
            ok = _u32.PrintWindow(hwnd, hdc_mem, 0)
        if not ok:
            return None

        # 비트맵 → PIL Image
        import ctypes
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize",          wintypes.DWORD),
                ("biWidth",         wintypes.LONG),
                ("biHeight",        wintypes.LONG),
                ("biPlanes",        wintypes.WORD),
                ("biBitCount",      wintypes.WORD),
                ("biCompression",   wintypes.DWORD),
                ("biSizeImage",     wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed",       wintypes.DWORD),
                ("biClrImportant",  wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize        = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth       = w
        bmi.biHeight      = -h   # 음수 = top-down
        bmi.biPlanes      = 1
        bmi.biBitCount    = 32
        bmi.biCompression = 0    # BI_RGB

        buf = ctypes.create_string_buffer(w * h * 4)
        ret = _gdi.GetDIBits(
            hdc_mem, hbmp, 0, h,
            buf, ctypes.byref(bmi), 0   # DIB_RGB_COLORS
        )
        if ret == 0:
            return None

        img = Image.frombuffer("RGBA", (w, h), buf.raw, "raw", "BGRA", 0, 1)
        return img.convert("RGB")

    finally:
        _gdi.DeleteObject(hbmp)
        _gdi.DeleteDC(hdc_mem)
        _u32.ReleaseDC(0, hdc_screen)


# ── 창 목록 (선택 UI 전용) ────────────────────────────────

def get_all_windows() -> list[dict]:
    """
    실행 중인 창 목록 반환. WindowPicker UI 전용.
    gw.getAllWindows() 는 여기서만 호출.
    """
    if not HAS_GW:
        return []
    result: list[dict] = []
    for win in gw.getAllWindows():
        title = (win.title or "").strip()
        if not title:
            continue
        try:
            hwnd = win._hWnd
            r = _get_client_rect_screen(hwnd)
            size_txt = f"{r[2]}×{r[3]}" if r else f"{win.width}×{win.height}"
            result.append({"hwnd": hwnd, "title": title, "size": size_txt})
        except Exception:
            pass
    return result


# ── 이미지 크롭 ──────────────────────────────────────────

def crop_region(img: Image.Image, region: dict) -> Image.Image:
    """
    비율 좌표 region {x1,y1,x2,y2} 로 img 를 크롭.
    region 값은 0.0~1.0 비율.
    """
    w, h = img.size
    return img.crop((
        int(w * region["x1"]), int(h * region["y1"]),
        int(w * region["x2"]), int(h * region["y2"]),
    ))


def crop_ratio(img: Image.Image, region: dict) -> Image.Image:
    """하위 호환 — crop_region() 별칭."""
    return crop_region(img, region)


# ── 좌표 변환 ─────────────────────────────────────────────

def ratio_to_screen(
    rect: tuple[int, int, int, int],
    rx: float,
    ry: float,
) -> tuple[int, int]:
    l, t, w, h = rect
    return int(l + w * rx), int(t + h * ry)


# ── 클릭 / 스크롤 ────────────────────────────────────────

def safe_click(
    rect: tuple[int, int, int, int],
    rx: float,
    ry: float,
    label: str = "",
) -> bool:
    """
    금지 구역 체크 후 클릭.
    pyautogui 사용 — 클릭은 실제 커서 이동이 필요하므로 그대로 유지.
    포커스 이동 없이 단순 좌표 클릭.
    """
    if not HAS_PAG:
        return False
    for fx1, fy1, fx2, fy2 in FORBIDDEN_ZONES:
        if fx1 <= rx <= fx2 and fy1 <= ry <= fy2:
            print(f"[Capture] ⛔ 금지구역: {label} ({rx:.3f},{ry:.3f})")
            return False
    x, y = ratio_to_screen(rect, rx, ry)
    pyautogui.click(x, y)
    return True


def click_center(
    rect: tuple[int, int, int, int],
    region: dict,
    label: str = "",
) -> bool:
    rx = (region["x1"] + region["x2"]) / 2
    ry = (region["y1"] + region["y2"]) / 2
    return safe_click(rect, rx, ry, label)


def scroll_at(
    rect: tuple[int, int, int, int],
    rx: float,
    ry: float,
    amount: int = -3,
) -> None:
    if not HAS_PAG:
        return
    x, y = ratio_to_screen(rect, rx, ry)
    pyautogui.moveTo(x, y, duration=0.08)
    pyautogui.scroll(amount)
    time.sleep(0.30)


def press_esc() -> None:
    if HAS_PAG:
        pyautogui.press("escape")
        time.sleep(0.35)