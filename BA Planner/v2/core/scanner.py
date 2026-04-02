"""
core/scanner.py
아이템 그리드를 자동 스크롤하며 전체 아이템을 수집하는 스캐너
"""

import time
import numpy as np
from PIL import Image
from dataclasses import dataclass, field
from typing import Callable

from core.capture import (
    capture_window, find_window,
    crop_region, scroll_down_in_window, click_slot_safe
)
from core.ocr import read_item_detail, read_resources, read_student_info


GRID_COLS = 5
SCROLL_AMOUNT = 3
MAX_SCROLL_ATTEMPTS = 50   # 무한 스크롤 방지
SAME_FRAME_THRESHOLD = 0.98  # 스크롤 종료 감지 임계값


@dataclass
class ItemEntry:
    name: str | None
    quantity: str | None
    tier: str | None
    category: str | None
    slot_index: int = 0

    def key(self):
        return f"{self.name}_{self.tier}"


@dataclass
class ScanResult:
    items: list[ItemEntry] = field(default_factory=list)
    resources: dict = field(default_factory=dict)
    students: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _images_similar(img1: Image.Image, img2: Image.Image,
                    threshold: float = SAME_FRAME_THRESHOLD) -> bool:
    """두 이미지가 유사한지 비교 (스크롤 종료 감지)"""
    try:
        a1 = np.array(img1.convert("L").resize((64, 64))).astype(float)
        a2 = np.array(img2.convert("L").resize((64, 64))).astype(float)
        corr = np.corrcoef(a1.flatten(), a2.flatten())[0, 1]
        return corr >= threshold
    except Exception:
        return False


def _get_slot_rects(grid_region: dict, img_w: int, img_h: int,
                   rows: int = 4) -> list[tuple]:
    """
    그리드 영역을 GRID_COLS × rows 로 나눠 슬롯 픽셀 좌표 반환
    반환: [(x1, y1, x2, y2), ...]
    """
    x1 = int(img_w * grid_region["x1"])
    y1 = int(img_h * grid_region["y1"])
    x2 = int(img_w * grid_region["x2"])
    y2 = int(img_h * grid_region["y2"])

    cw = (x2 - x1) / GRID_COLS
    rh = (y2 - y1) / rows

    slots = []
    for r in range(rows):
        for c in range(GRID_COLS):
            sx1 = x1 + int(c * cw)
            sy1 = y1 + int(r * rh)
            sx2 = x1 + int((c + 1) * cw)
            sy2 = y1 + int((r + 1) * rh)
            slots.append((sx1, sy1, sx2, sy2))
    return slots


def _crop_slot_icon(img: Image.Image, slot: tuple) -> Image.Image:
    """슬롯에서 아이콘 영역만 크롭 (수량 텍스트 제외, 상단 75%)"""
    x1, y1, x2, y2 = slot
    icon_y2 = y1 + int((y2 - y1) * 0.75)
    return img.crop((x1, y1, x2, icon_y2))


def _crop_slot_qty(img: Image.Image, slot: tuple) -> Image.Image:
    """슬롯 하단 수량 텍스트 영역 크롭"""
    x1, y1, x2, y2 = slot
    qty_y1 = y1 + int((y2 - y1) * 0.72)
    return img.crop((x1, qty_y1, x2, y2))


def _is_empty_slot(img: Image.Image) -> bool:
    """슬롯이 비어있는지 확인 (평균 밝기로 판단)"""
    arr = np.array(img.convert("L"))
    mean = arr.mean()
    std = arr.std()
    return mean > 220 and std < 20  # 거의 흰색 = 빈 슬롯


class ItemScanner:
    """
    아이템 그리드 전체를 스캔하는 스캐너.
    설정된 영역 좌표를 기반으로 슬롯 클릭 → OCR → 스크롤 반복.
    """

    def __init__(self, config: dict,
                 on_progress: Callable[[str, int, int], None] | None = None):
        """
        config: load_config()로 불러온 딕셔너리
        on_progress: (message, current, total) 콜백
        """
        self.config = config
        self.on_progress = on_progress or (lambda m, c, t: None)
        self.win = None
        self.result = ScanResult()

    def _log(self, msg: str, current: int = 0, total: int = 0):
        self.on_progress(msg, current, total)

    def scan_resources(self, img: Image.Image) -> dict:
        """상단 재화 바 스캔"""
        if "resources" not in self.config:
            return {}
        cropped = crop_region(img, self.config["resources"])
        return read_resources(cropped)

    def scan_items(self) -> list[ItemEntry]:
        """
        아이템 그리드 전체 스캔 (자동 스크롤 포함)
        - 각 슬롯을 클릭해서 하단 상세 패널로 이름+수량 읽기
        - 스크롤 후 새 아이템 없으면 종료
        """
        self.win = find_window()
        if not self.win:
            self._log("❌ 블루아카이브 윈도우를 찾지 못했어")
            return []

        if "item_grid" not in self.config or "item_detail" not in self.config:
            self._log("❌ 영역 설정이 없어. 먼저 설정을 완료해줘")
            return []

        items: list[ItemEntry] = []
        seen_keys: set[str] = set()
        scroll_count = 0
        slot_index = 0

        self._log("🔍 아이템 스캔 시작...", 0, 0)

        while scroll_count < MAX_SCROLL_ATTEMPTS:
            img = capture_window(self.win)
            if img is None:
                self._log("❌ 캡처 실패")
                break

            iw, ih = img.size
            slots = _get_slot_rects(self.config["item_grid"], iw, ih)
            new_found = 0

            for i, slot in enumerate(slots):
                slot_crop = _crop_slot_icon(img, slot)

                # 빈 슬롯 건너뜀
                if _is_empty_slot(slot_crop):
                    continue

                # 슬롯 클릭 (안전 클릭)
                click_slot_safe(self.win, slot, iw, ih)
                time.sleep(0.25)

                # 클릭 후 상세 패널 캡처
                img_after = capture_window(self.win)
                if img_after is None:
                    continue

                detail_crop = crop_region(img_after, self.config["item_detail"])
                detail = read_item_detail(detail_crop)

                entry = ItemEntry(
                    name=detail.get("name"),
                    quantity=detail.get("quantity"),
                    tier=detail.get("tier"),
                    category=detail.get("category"),
                    slot_index=slot_index,
                )

                key = entry.key()
                if key not in seen_keys:
                    seen_keys.add(key)
                    items.append(entry)
                    new_found += 1
                    self._log(
                        f"📦 {entry.name or '?'} x{entry.quantity or '?'}",
                        len(items), 0
                    )

                slot_index += 1

            # 스크롤 전 화면 저장
            before_scroll = capture_window(self.win)

            # 스크롤
            scroll_down_in_window(self.win, SCROLL_AMOUNT)
            scroll_count += 1

            # 스크롤 후 화면
            after_scroll = capture_window(self.win)
            if after_scroll is None:
                break

            # 화면 변화 없으면 끝
            grid_before = crop_region(before_scroll, self.config["item_grid"])
            grid_after  = crop_region(after_scroll,  self.config["item_grid"])

            if _images_similar(grid_before, grid_after):
                self._log(f"✅ 스캔 완료 — 총 {len(items)}개 아이템")
                break

            # 새 아이템이 없어도 종료
            if new_found == 0 and scroll_count > 3:
                self._log(f"✅ 새 아이템 없음 — 스캔 종료")
                break

        return items

    def run_full_scan(self) -> ScanResult:
        """전체 스캔 실행"""
        result = ScanResult()

        # 1. 재화
        self._log("💰 재화 스캔 중...")
        img = capture_window()
        if img:
            result.resources = self.scan_resources(img)

        # 2. 아이템
        self._log("📦 아이템 스캔 시작...")
        result.items = self.scan_items()

        self.result = result
        return result
