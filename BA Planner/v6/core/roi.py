"""
core/roi.py — BA Analyzer v6
ROI(관심 영역) 처리 표준화 모듈

━━━ 좌표계 정의 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
이 프로젝트에서 사용하는 좌표계는 세 가지야.

  [A] 정규화 비율 좌표 (Normalized)
      · x, y 모두 0.0 ~ 1.0
      · regions/*.json 에 저장되는 기본 단위
      · 창 해상도가 달라져도 항상 유효
      · 예: {"x1": 0.05, "y1": 0.10, "x2": 0.45, "y2": 0.20}

  [B] 클라이언트 픽셀 좌표 (Client Pixel)
      · 창의 client area 기준 픽셀 (좌상단 = 0,0)
      · get_window_rect() 반환값 (left, top, w, h) 에서
        w, h 를 곱해서 변환
      · 클릭 좌표 계산에 사용 (input.py)

  [C] 화면 절대 좌표 (Screen Absolute)
      · 모니터 전체 기준 픽셀
      · client_to_screen() 으로 변환
      · pyautogui fallback 클릭에 사용

이 파일에서 crop_roi() 는 [A] 정규화 좌표를 받아
PIL Image 에서 직접 crop — 화면 좌표와 무관.

━━━ ROI 처리 흐름 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  frame = capture_window_background()    # 전체 캡처 1회
  rois  = build_roi_frame(frame, region_table)
  name  = rois[ROI.STUDENT_NAME]        # crop 결과 재사용
  level = rois[ROI.LEVEL_DIGIT_1]

━━━ 공개 인터페이스 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ROI                           (str 상수 네임스페이스)

  crop_roi(frame, region)       → Image   단일 crop
  crop_named_roi(frame, name, table) → Image   이름 기반 crop

  RoiFrame                      (frame + table 묶음 클래스)
    .get(roi_name)              → Image
    .get_safe(roi_name)         → Image | None
    .debug_save(dir)            → 전체 ROI를 파일로 저장

  build_roi_frame(frame, table) → RoiFrame   factory 함수

  ROI 테이블 구성자:
    get_lobby_rois(regions)
    get_student_rois(regions)
    get_skill_rois(regions)
    get_weapon_rois(regions)
    get_equipment_rois(regions)
    get_stat_rois(regions)
    get_item_rois(regions)
    get_equipment_item_rois(regions)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union
from PIL import Image


# ══════════════════════════════════════════════════════════
# ROI 이름 상수
# ══════════════════════════════════════════════════════════

class ROI:
    """ROI 이름 문자열 상수. 오탈자 방지용."""

    # ── 로비 ─────────────────────────────────────────────
    LOBBY_FLAG      = "lobby_flag"
    CREDIT          = "credit"
    PYROXENE        = "pyroxene"
    MENU_BUTTON     = "menu_button"
    STUDENT_MENU    = "student_menu_button"

    # ── 학생 기본 ─────────────────────────────────────────
    STUDENT_TEXTURE   = "student_texture"
    STUDENT_STAR      = "student_star"
    LEVEL_DIGIT_1     = "level_digit_1"
    LEVEL_DIGIT_2     = "level_digit_2"

    # ── 스킬 ─────────────────────────────────────────────
    SKILL_CHECK       = "skill_all_view_check"
    EX_SKILL          = "ex_skill"
    SKILL_1           = "skill_1"
    SKILL_2           = "skill_2"
    SKILL_3           = "skill_3"

    # ── 무기 ─────────────────────────────────────────────
    WEAPON_FLAG       = "weapon_flag"
    WEAPON_STAR       = "weapon_star"
    WEAPON_LV_DIGIT_1 = "weapon_lv_digit_1"
    WEAPON_LV_DIGIT_2 = "weapon_lv_digit_2"

    # ── 장비 (학생 상세) ──────────────────────────────────
    EQUIP_CHECK       = "equip_all_view_check"
    EQUIP_BTN         = "equip_button"
    EQUIP_1           = "equip_1"
    EQUIP_2           = "equip_2"
    EQUIP_3           = "equip_3"
    EQUIP_4           = "equip_4"
    EQUIP_1_FLAG      = "equip_1_flag"
    EQUIP_2_FLAG      = "equip_2_flag"
    EQUIP_3_FLAG      = "equip_3_flag"
    EQUIP_4_FLAG      = "equip_4_flag"
    EQUIP_1_LV_D1     = "equip_1_lv_d1"
    EQUIP_1_LV_D2     = "equip_1_lv_d2"
    EQUIP_2_LV_D1     = "equip_2_lv_d1"
    EQUIP_2_LV_D2     = "equip_2_lv_d2"
    EQUIP_3_LV_D1     = "equip_3_lv_d1"
    EQUIP_3_LV_D2     = "equip_3_lv_d2"

    # ── 스탯 ─────────────────────────────────────────────
    STAT_HP           = "stat_hp"
    STAT_ATK          = "stat_atk"
    STAT_HEAL         = "stat_heal"

    # ── 아이템 / 장비 아이템 그리드 ──────────────────────
    ITEM_NAME         = "item_name"
    ITEM_COUNT        = "item_count"
    EQUIP_ITEM_NAME   = "equip_item_name"
    EQUIP_ITEM_COUNT  = "equip_item_count"


# ══════════════════════════════════════════════════════════
# 단일 crop 유틸
# ══════════════════════════════════════════════════════════

_MIN_SIDE = 4   # crop 결과의 최소 허용 크기 (px)


def crop_roi(
    frame: Image.Image,
    region: dict,
    *,
    label: str = "",
) -> Image.Image:
    """
    정규화 비율 좌표 region {x1,y1,x2,y2} 로 frame 을 crop.

    좌표계: [A] 정규화 비율 (0.0~1.0)
    반환:   PIL Image (RGB)

    실패 조건:
      - region 키 누락
      - crop 결과가 _MIN_SIDE 미만
    위 경우 ValueError 를 raise. 호출부에서 try/except 처리.
    """
    try:
        x1 = region["x1"]
        y1 = region["y1"]
        x2 = region["x2"]
        y2 = region["y2"]
    except KeyError as e:
        raise ValueError(f"[ROI] region 키 누락: {e} (label={label!r})")

    w, h = frame.size
    px1 = int(w * x1)
    py1 = int(h * y1)
    px2 = int(w * x2)
    py2 = int(h * y2)

    # 범위 클리핑
    px1 = max(0, min(px1, w))
    py1 = max(0, min(py1, h))
    px2 = max(0, min(px2, w))
    py2 = max(0, min(py2, h))

    crop_w = px2 - px1
    crop_h = py2 - py1

    if crop_w < _MIN_SIDE or crop_h < _MIN_SIDE:
        raise ValueError(
            f"[ROI] crop 크기 부족: {crop_w}×{crop_h} "
            f"(region={region} frame={w}×{h} label={label!r})"
        )

    return frame.crop((px1, py1, px2, py2))


def crop_named_roi(
    frame: Image.Image,
    name: str,
    table: dict[str, dict],
    *,
    warn: bool = True,
) -> Optional[Image.Image]:
    """
    ROI 이름으로 table 에서 region 을 찾아 crop.

    Parameters
    ----------
    frame : 전체 캡처 이미지
    name  : ROI 상수 (ROI.STUDENT_STAR 등)
    table : {roi_name: region_dict} 매핑
    warn  : True 이면 region 미등록 시 로그 출력

    반환: PIL Image 또는 None (미등록 / crop 실패)
    """
    region = table.get(name)
    if region is None:
        if warn:
            print(f"[ROI] '{name}' 미등록 — 스킵")
        return None
    try:
        return crop_roi(frame, region, label=name)
    except ValueError as e:
        print(e)
        return None


# ══════════════════════════════════════════════════════════
# RoiFrame — frame + table 묶음 클래스
# ══════════════════════════════════════════════════════════

class RoiFrame:
    """
    캡처 이미지(frame)와 ROI 테이블을 묶어 관리.

    사용 예
    -------
    rf = build_roi_frame(frame, get_student_rois(regions))
    name_img  = rf.get(ROI.STUDENT_TEXTURE)   # 없으면 ValueError
    level_img = rf.get_safe(ROI.LEVEL_DIGIT_1) # 없으면 None
    """

    def __init__(
        self,
        frame: Image.Image,
        table: dict[str, dict],
    ):
        self._frame = frame
        self._table = table
        # crop 결과 캐시: 같은 ROI 는 두 번 crop 하지 않음
        self._cache: dict[str, Image.Image] = {}

    # ── 조회 ──────────────────────────────────────────────

    def get(self, name: str) -> Image.Image:
        """
        ROI crop 결과 반환.
        미등록 / crop 실패 시 ValueError raise.
        """
        if name in self._cache:
            return self._cache[name]

        region = self._table.get(name)
        if region is None:
            raise ValueError(f"[RoiFrame] '{name}' 미등록")

        img = crop_roi(self._frame, region, label=name)
        self._cache[name] = img
        return img

    def get_safe(self, name: str) -> Optional[Image.Image]:
        """
        ROI crop 결과 반환.
        미등록 / crop 실패 시 None 반환 (예외 없음).
        """
        try:
            return self.get(name)
        except ValueError as e:
            print(e)
            return None

    # ── 프레임 접근 ───────────────────────────────────────

    @property
    def frame(self) -> Image.Image:
        """원본 캡처 이미지."""
        return self._frame

    @property
    def table(self) -> dict[str, dict]:
        return self._table

    def has(self, name: str) -> bool:
        """ROI 이름이 테이블에 등록돼 있는지 확인."""
        return name in self._table

    # ── 캐시 ──────────────────────────────────────────────

    def clear_cache(self) -> None:
        self._cache.clear()

    def preload(self, *names: str) -> "RoiFrame":
        """
        지정한 ROI 를 미리 crop 해 캐시에 올림.
        실패한 ROI 는 로그만 남기고 계속 진행.
        """
        for name in names:
            self.get_safe(name)
        return self

    # ── 디버그 ────────────────────────────────────────────

    def debug_save(self, out_dir: Union[str, Path] = "debug_rois") -> None:
        """
        테이블의 모든 ROI 를 out_dir/{roi_name}.png 로 저장.
        인식 결과를 눈으로 확인할 때 사용.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name in self._table:
            img = self.get_safe(name)
            if img is not None:
                img.save(out / f"{name}.png")
        print(f"[RoiFrame] debug_save → {out.resolve()} ({len(self._table)}개)")


# ══════════════════════════════════════════════════════════
# RoiFrame factory
# ══════════════════════════════════════════════════════════

def build_roi_frame(
    frame: Image.Image,
    table: dict[str, dict],
) -> RoiFrame:
    """
    캡처 이미지와 ROI 테이블로 RoiFrame 생성.

    Parameters
    ----------
    frame : capture_window_background() 반환값
    table : get_*_rois(regions) 반환값 (또는 직접 구성)
    """
    return RoiFrame(frame, table)


# ══════════════════════════════════════════════════════════
# ROI 테이블 구성자
# (regions = load_regions() 반환값)
# ══════════════════════════════════════════════════════════

def get_lobby_rois(regions: dict) -> dict[str, dict]:
    """
    로비 화면 ROI 테이블.
    좌표계: [A] 정규화 비율
    """
    lobby = regions.get("lobby", {})
    return {
        ROI.LOBBY_FLAG:   lobby.get("detect_flag",         {}),
        ROI.CREDIT:       lobby.get("credit_region",       {}),
        ROI.PYROXENE:     lobby.get("pyroxene_region",     {}),
        ROI.MENU_BUTTON:  lobby.get("menu_button",         {}),
        ROI.STUDENT_MENU: lobby.get("student_menu_button", {}),
    }


def get_student_rois(regions: dict) -> dict[str, dict]:
    """
    학생 기본 정보 탭 ROI 테이블.
    """
    sr = regions.get("student", {})
    return {
        ROI.STUDENT_TEXTURE: sr.get("student_texture_region", {}),
        ROI.STUDENT_STAR:    sr.get("student_star_region",    {}),
        ROI.LEVEL_DIGIT_1:   sr.get("level_digit_1",          {}),
        ROI.LEVEL_DIGIT_2:   sr.get("level_digit_2",          {}),
        ROI.WEAPON_FLAG:     (sr.get("weapon_detect_flag_region")
                              or sr.get("weapon_unlocked_flag", {})),
        ROI.EQUIP_BTN:       sr.get("equipment_button",       {}),
    }


def get_skill_rois(regions: dict) -> dict[str, dict]:
    """
    스킬 메뉴 탭 ROI 테이블.
    """
    sr = regions.get("student", {})
    return {
        ROI.SKILL_CHECK: sr.get("skill_all_view_check_region", {}),
        ROI.EX_SKILL:    sr.get("EX_skill",                    {}),
        ROI.SKILL_1:     sr.get("Skill_1",                     {}),
        ROI.SKILL_2:     sr.get("Skill_2",                     {}),
        ROI.SKILL_3:     sr.get("Skill_3",                     {}),
    }


def get_weapon_rois(regions: dict) -> dict[str, dict]:
    """
    무기 메뉴 탭 ROI 테이블.
    """
    sr = regions.get("student", {})
    return {
        ROI.WEAPON_STAR:       sr.get("weapon_star_region",  {}),
        ROI.WEAPON_LV_DIGIT_1: (sr.get("weapon_level_digit_1")
                                or sr.get("weapon_level_digit1", {})),
        ROI.WEAPON_LV_DIGIT_2: (sr.get("weapon_level_digit_2")
                                or sr.get("weapon_level_digit2", {})),
    }


def get_equipment_rois(regions: dict) -> dict[str, dict]:
    """
    장비 탭 ROI 테이블 (학생 상세 화면 내).
    """
    sr = regions.get("student", {})

    def _flag(slot: int) -> dict:
        return (sr.get(f"equip{slot}_flag")
                or sr.get(f"equip{slot}_emptyflag")
                or sr.get(f"equip{slot}_empty_flag", {}))

    return {
        ROI.EQUIP_CHECK:   sr.get("equipment_all_view_check_region", {}),
        ROI.EQUIP_1:       sr.get("equipment_1",              {}),
        ROI.EQUIP_2:       sr.get("equipment_2",              {}),
        ROI.EQUIP_3:       sr.get("equipment_3",              {}),
        ROI.EQUIP_4:       sr.get("equipment_4",              {}),
        ROI.EQUIP_1_FLAG:  _flag(1),
        ROI.EQUIP_2_FLAG:  _flag(2),
        ROI.EQUIP_3_FLAG:  _flag(3),
        ROI.EQUIP_4_FLAG:  _flag(4),
        ROI.EQUIP_1_LV_D1: sr.get("equipment_1_level_digit_1", {}),
        ROI.EQUIP_1_LV_D2: sr.get("equipment_1_level_digit_2", {}),
        ROI.EQUIP_2_LV_D1: sr.get("equipment_2_level_digit_1", {}),
        ROI.EQUIP_2_LV_D2: sr.get("equipment_2_level_digit_2", {}),
        ROI.EQUIP_3_LV_D1: sr.get("equipment_3_level_digit_1", {}),
        ROI.EQUIP_3_LV_D2: sr.get("equipment_3_level_digit_2", {}),
    }


def get_stat_rois(regions: dict) -> dict[str, dict]:
    """
    스탯 메뉴 탭 ROI 테이블.
    """
    sr = regions.get("student", {})
    return {
        ROI.STAT_HP:   sr.get("hp",   {}),
        ROI.STAT_ATK:  sr.get("atk",  {}),
        ROI.STAT_HEAL: sr.get("heal", {}),
    }


def get_item_rois(regions: dict) -> dict[str, dict]:
    """
    아이템 그리드 상세 패널 ROI 테이블.
    """
    item = regions.get("item", {})
    return {
        ROI.ITEM_NAME:  item.get("name_region",  {}),
        ROI.ITEM_COUNT: item.get("count_region", {}),
    }


def get_equipment_item_rois(regions: dict) -> dict[str, dict]:
    """
    장비 아이템 그리드 상세 패널 ROI 테이블.
    """
    eq = regions.get("equipment", {})
    return {
        ROI.EQUIP_ITEM_NAME:  eq.get("name_region",  {}),
        ROI.EQUIP_ITEM_COUNT: eq.get("count_region", {}),
    }


# ══════════════════════════════════════════════════════════
# 복합 ROI 테이블 (자주 쓰는 조합)
# ══════════════════════════════════════════════════════════

def get_student_detail_rois(regions: dict) -> dict[str, dict]:
    """
    학생 상세 화면 전체 ROI 테이블.
    기본 / 스킬 / 무기 / 장비 / 스탯 탭을 하나로 합침.

    scanner.py 에서 학생 1명 스캔 시작 전에 호출.
    각 단계 함수는 이 테이블을 공유하고 필요한 ROI 만 crop.
    """
    table: dict[str, dict] = {}
    table.update(get_student_rois(regions))
    table.update(get_skill_rois(regions))
    table.update(get_weapon_rois(regions))
    table.update(get_equipment_rois(regions))
    table.update(get_stat_rois(regions))
    return table
