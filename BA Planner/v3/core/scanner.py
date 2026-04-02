"""
core/scanner.py
메뉴 열기 → 아이템/장비 화면 진입 → 스캔 → 로비 복귀
"""
import time
import threading
import numpy as np
from PIL import Image
from dataclasses import dataclass, field
from typing import Callable

from core.capture import (
    capture_window, crop_ratio, safe_click,
    scroll_at, press_esc, get_window_rect
)
from core.ocr import read_item_detail, read_resources

GRID_COLS     = 5
GRID_ROWS     = 4
MAX_SCROLLS   = 60
SCROLL_AMOUNT = -3
SAME_THRESH   = 0.97


@dataclass
class ItemEntry:
    name: str | None
    quantity: str | None
    tier: str | None
    source: str = "item"   # "item" or "equipment"

    def key(self):
        return f"{self.name}_{self.tier}_{self.source}"


@dataclass
class ScanResult:
    items: list[ItemEntry]       = field(default_factory=list)
    equipment: list[ItemEntry]   = field(default_factory=list)
    resources: dict              = field(default_factory=dict)
    errors: list[str]            = field(default_factory=list)


def _similar(a: Image.Image, b: Image.Image, thresh=SAME_THRESH) -> bool:
    try:
        a2 = np.array(a.convert("L").resize((64, 64))).flatten().astype(float)
        b2 = np.array(b.convert("L").resize((64, 64))).flatten().astype(float)
        return float(np.corrcoef(a2, b2)[0, 1]) >= thresh
    except Exception:
        return False


def _slot_rects(grid_r: dict, iw: int, ih: int):
    """그리드 영역을 슬롯 픽셀 좌표 리스트로 분해"""
    x1 = int(iw * grid_r["x1"]); y1 = int(ih * grid_r["y1"])
    x2 = int(iw * grid_r["x2"]); y2 = int(ih * grid_r["y2"])
    cw = (x2 - x1) / GRID_COLS
    rh = (y2 - y1) / GRID_ROWS
    return [
        (x1 + int(c*cw), y1 + int(r*rh),
         x1 + int((c+1)*cw), y1 + int((r+1)*rh))
        for r in range(GRID_ROWS) for c in range(GRID_COLS)
    ]


def _is_empty(img: Image.Image) -> bool:
    arr = np.array(img.convert("L"))
    return arr.mean() > 215 and arr.std() < 25


class Scanner:
    def __init__(self, config: dict,
                 on_progress: Callable[[str], None] | None = None):
        self.cfg = config
        self.log = on_progress or print
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    # ── 재화 스캔 ─────────────────────────────────────────
    def scan_resources(self) -> dict:
        self.log("💰 재화 스캔 중...")
        img = capture_window()
        if img is None:
            return {}
        region = self.cfg.get("resources")
        if not region:
            return {}
        cropped = crop_ratio(img, region)
        result = read_resources(cropped)
        self.log(f"💰 청휘석 {result.get('청휘석','-')}  크레딧 {result.get('크레딧','-')}")
        return result

    # ── 공통 그리드 스캔 ──────────────────────────────────
    def _scan_grid(self, grid_key: str, detail_key: str,
                   source: str) -> list[ItemEntry]:
        items: list[ItemEntry] = []
        seen: set[str] = set()
        rect = get_window_rect()
        if not rect:
            return items

        grid_r   = self.cfg.get(grid_key)
        detail_r = self.cfg.get(detail_key)
        if not grid_r or not detail_r:
            self.log(f"❌ {grid_key} 설정 없음")
            return items

        scroll_cx = (grid_r["x1"] + grid_r["x2"]) / 2
        scroll_cy = (grid_r["y1"] + grid_r["y2"]) / 2

        for scroll_i in range(MAX_SCROLLS):
            if self._stop_flag:
                break

            img = capture_window()
            if img is None:
                break

            iw, ih = img.size
            slots = _slot_rects(grid_r, iw, ih)
            new_this_pass = 0

            for slot in slots:
                if self._stop_flag:
                    break

                sx1, sy1, sx2, sy2 = slot
                icon_crop = img.crop((sx1, sy1, sx2, sy1 + int((sy2-sy1)*0.75)))

                if _is_empty(icon_crop):
                    continue

                # 슬롯 아이콘 중앙 40% 지점 클릭
                srx = (sx1 + sx2) / 2 / iw
                sry = (sy1 + (sy2-sy1)*0.4) / ih
                safe_click(rect, srx, sry, label=f"{source} slot")
                time.sleep(0.22)

                img2 = capture_window()
                if img2 is None:
                    continue

                detail_crop = crop_ratio(img2, detail_r)
                detail = read_item_detail(detail_crop)

                entry = ItemEntry(
                    name=detail.get("name"),
                    quantity=detail.get("quantity"),
                    tier=detail.get("tier"),
                    source=source,
                )
                k = entry.key()
                if k not in seen:
                    seen.add(k)
                    items.append(entry)
                    new_this_pass += 1
                    self.log(f"  {'📦' if source=='item' else '🔧'} "
                             f"{entry.name or '?'}  {entry.tier or ''}  ×{entry.quantity or '?'}")

            # 스크롤 전후 비교
            before = crop_ratio(capture_window() or img, grid_r)
            scroll_at(rect, scroll_cx, scroll_cy, SCROLL_AMOUNT)
            after_img = capture_window()
            if after_img is None:
                break
            after = crop_ratio(after_img, grid_r)

            if _similar(before, after):
                self.log(f"  ✅ 스크롤 끝 ({len(items)}개)")
                break
            if new_this_pass == 0 and scroll_i > 2:
                self.log(f"  ✅ 새 항목 없음 ({len(items)}개)")
                break

        return items

    # ── 메뉴 열기 / 화면 이동 ─────────────────────────────
    def _open_menu(self) -> bool:
        rect = get_window_rect()
        if not rect:
            return False
        menu_btn = self.cfg.get("menu_button")
        if not menu_btn:
            self.log("❌ 메뉴 버튼 설정 없음")
            return False
        self.log("📂 메뉴 열기...")
        safe_click(rect, menu_btn["rx"], menu_btn["ry"], "menu_button")
        time.sleep(0.6)
        return True

    def _click_nav(self, key: str, label: str) -> bool:
        rect = get_window_rect()
        if not rect:
            return False
        btn = self.cfg.get(key)
        if not btn:
            self.log(f"❌ {label} 버튼 설정 없음")
            return False
        safe_click(rect, btn["rx"], btn["ry"], key)
        time.sleep(0.8)
        return True

    def _return_to_lobby(self):
        self.log("🏠 로비로 복귀...")
        press_esc()
        time.sleep(0.5)

    # ── 퍼블릭 스캔 메서드 ───────────────────────────────
    def scan_items(self) -> list[ItemEntry]:
        self._stop_flag = False
        self.log("─── 아이템 스캔 시작 ───")
        if not self._open_menu():
            return []
        if not self._click_nav("menu_item_button", "아이템"):
            return []
        time.sleep(0.5)
        result = self._scan_grid("item_grid", "item_detail", "item")
        self._return_to_lobby()
        return result

    def scan_equipment(self) -> list[ItemEntry]:
        self._stop_flag = False
        self.log("─── 장비 스캔 시작 ───")
        if not self._open_menu():
            return []
        if not self._click_nav("menu_equipment_button", "장비"):
            return []
        time.sleep(0.5)
        result = self._scan_grid("equipment_grid", "equipment_detail", "equipment")
        self._return_to_lobby()
        return result

    def run_full_scan(self) -> ScanResult:
        self._stop_flag = False
        result = ScanResult()
        result.resources = self.scan_resources()
        result.items = self.scan_items()
        if self._stop_flag:
            return result
        result.equipment = self.scan_equipment()
        return result
