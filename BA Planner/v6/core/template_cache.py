"""
core/template_cache.py — BA Analyzer v6
템플릿 이미지 캐시 저장소

━━━ 설계 원칙 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. 파일 I/O 는 오직 이 모듈에서만 수행.
     matcher.py 는 캐시 객체만 참조하고 직접 imread 하지 않음.

  2. 캐시 엔트리 구조:
       TemplateEntry
         .gray  : np.ndarray  grayscale (uint8)  — 항상 존재
         .bgr   : np.ndarray  BGR        (uint8)  — 항상 존재
         .alpha : np.ndarray | None      (uint8)  — RGBA 템플릿만 존재
         .path  : str                              — 원본 경로 (디버그)

  3. 원본 이미지만 캐시. 전처리(리사이즈·이진화)는 매칭 시 수행.
     → 전처리 파라미터가 바뀌어도 캐시 무효화 불필요.

  4. 파일 경로 → 캐시 키 변환 규칙:
       templates/star/star_5.png  →  "star/star_5"
       templates/equip1/equip1_T3.png  →  "equip1/equip1_T3"
     즉, TEMPLATE_DIR 이하의 상대 경로에서 확장자만 제거.

  5. 시작 시 warmup(dirs) 으로 디렉터리 단위 일괄 로드.
     누락 파일은 WARNING 으로 기록하되 시작을 막지 않음.

━━━ 캐시 키 ↔ 파일 경로 대응표 ━━━━━━━━━━━━━━━━━━━━━━━━

  분류          캐시 키 예시                   파일 경로 예시
  ─────────     ────────────────────────────   ─────────────────────────────
  로비          "menu_detect_flag/lobby_template" templates/menu_detect_flag/lobby_template.png
  학생 메뉴     "menu_detect_flag/student_menu__menu_detect_flag" templates/menu_detect_flag/student_menu__menu_detect_flag.png
  별 등급       "star/star_5"                  templates/star/star_5.png
  무기 별       "weapon_star/star_4"           templates/weapon_star/star_4.png
  무기 상태     "weapon_state/WEAPON_EQUIPPED" templates/weapon_state/WEAPON_EQUIPPED.png
  스킬 check   "skillcheck/true"              templates/skillcheck/true.png
  장비 check   "equipcheck/possible"          templates/equipcheck/possible.png
  장비 슬롯    "equip1_flag/equip1_empty"     templates/equip1_flag/equip1_empty.png
  장비 티어    "equip1/equip1_T3"             templates/equip1/equip1_T3.png
  장비 레벨    "equip1level_digit1/1_5"       templates/equip1level_digit1/1_5.png
  무기 레벨    "weaponlevel_digit1/1_3"       templates/weaponlevel_digit1/1_3.png
  학생 레벨    "studentlevel_digit1/1_9"      templates/studentlevel_digit1/1_9.png
  스킬 레벨    "EX_Skill/EX_Skill_5"          templates/EX_Skill/EX_Skill_5.png
  스탯         "stat_hp/25"                   templates/stat_hp/25.png
  텍스처       "students/shiroko"             templates/students/shiroko.png

━━━ 공개 인터페이스 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  TemplateEntry      dataclass — 캐시 엔트리
  TemplateCache      저장소 클래스
    .get(key)        → TemplateEntry | None
    .load(path)      → TemplateEntry | None   (단일 파일 로드)
    .warmup(dirs)    → WarmupResult           (디렉터리 일괄 로드)
    .clear()         → None
    .stats()         → dict                   (로드 현황)

  get_cache()        → TemplateCache          (전역 싱글톤)
  warmup_all()       → WarmupResult           (권장 진입점)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from core.config import TEMPLATE_DIR, BASE_DIR


# ══════════════════════════════════════════════════════════
# 데이터 타입
# ══════════════════════════════════════════════════════════

@dataclass
class TemplateEntry:
    """
    단일 템플릿 파일의 캐시 엔트리.

    Attributes
    ----------
    gray  : grayscale ndarray (H×W, uint8)
    bgr   : BGR ndarray (H×W×3, uint8)
    alpha : alpha mask ndarray (H×W, uint8) or None — RGBA 파일만 존재
    path  : 원본 파일 절대 경로 (디버그용)
    """
    gray:  np.ndarray
    bgr:   np.ndarray
    alpha: Optional[np.ndarray]
    path:  str

    @property
    def has_alpha(self) -> bool:
        return self.alpha is not None

    @property
    def size(self) -> tuple[int, int]:
        """(width, height)"""
        h, w = self.gray.shape[:2]
        return w, h


@dataclass
class WarmupResult:
    """warmup() 결과 요약."""
    loaded:  list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    errors:  list[str] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        return (
            f"[TemplateCache] warmup 완료: "
            f"로드={len(self.loaded)} 누락={len(self.missing)} "
            f"오류={len(self.errors)} ({self.elapsed:.2f}s)"
        )


# ══════════════════════════════════════════════════════════
# 캐시 저장소
# ══════════════════════════════════════════════════════════

class TemplateCache:
    """
    템플릿 이미지 캐시 저장소.

    파일은 한 번만 읽고, 이후 get(key) 로 즉시 반환.
    matcher.py 는 이 클래스만 참조하고 파일 I/O 없음.
    """

    def __init__(self) -> None:
        self._store: dict[str, TemplateEntry] = {}
        self._miss:  set[str]                 = set()   # 로드 실패 경로

    # ── 조회 ──────────────────────────────────────────────

    def get(self, key: str) -> Optional[TemplateEntry]:
        """
        캐시 키로 TemplateEntry 반환.
        미등록 시 None (매칭 함수가 0.0 점수를 반환하도록 유도).
        """
        return self._store.get(key)

    def get_by_path(self, path: str) -> Optional[TemplateEntry]:
        """절대 경로를 캐시 키로 변환 후 반환."""
        return self.get(_path_to_key(path))

    def has(self, key: str) -> bool:
        return key in self._store

    # ── 로드 ──────────────────────────────────────────────

    def load(self, path: str) -> Optional[TemplateEntry]:
        """
        단일 파일 로드 + 캐시 등록.
        이미 캐시된 경우 즉시 반환 (중복 읽기 없음).
        실패 시 None + 로그.
        """
        key = _path_to_key(path)

        if key in self._store:
            return self._store[key]

        if path in self._miss:
            return None

        entry = _read_template(path)
        if entry is None:
            self._miss.add(path)
            return None

        self._store[key] = entry
        return entry

    # ── 일괄 로드 ─────────────────────────────────────────

    def warmup(
        self,
        dirs: Optional[list[Path]] = None,
        *,
        verbose: bool = False,
    ) -> WarmupResult:
        """
        디렉터리 목록을 순회해 PNG 파일 전체 로드.

        Parameters
        ----------
        dirs    : 로드할 디렉터리 목록. None 이면 WARMUP_DIRS 사용.
        verbose : True 이면 파일마다 로그 출력.

        Returns
        -------
        WarmupResult — 로드/누락/오류 집계
        """
        dirs = dirs or _default_warmup_dirs()
        result = WarmupResult()
        t0 = time.monotonic()

        for d in dirs:
            if not d.exists():
                result.missing.append(str(d))
                print(f"[TemplateCache] ⚠️  디렉터리 없음: {d}")
                continue

            for png in sorted(d.rglob("*.png")):
                key = _path_to_key(str(png))
                if key in self._store:
                    result.loaded.append(key)
                    continue

                entry = _read_template(str(png))
                if entry is None:
                    msg = f"{png.relative_to(TEMPLATE_DIR)}"
                    result.errors.append(msg)
                    print(f"[TemplateCache] ❌ 로드 실패: {msg}")
                else:
                    self._store[key] = entry
                    result.loaded.append(key)
                    if verbose:
                        print(f"[TemplateCache] ✅ {key} {entry.size}")

        result.elapsed = time.monotonic() - t0
        print(result.summary())

        if result.missing:
            print(f"[TemplateCache] ⚠️  누락 디렉터리 {len(result.missing)}개:")
            for m in result.missing:
                print(f"  - {m}")

        return result

    # ── 관리 ──────────────────────────────────────────────

    def clear(self) -> None:
        self._store.clear()
        self._miss.clear()
        print("[TemplateCache] 캐시 초기화 완료")

    def stats(self) -> dict:
        """로드 현황 요약 dict."""
        by_dir: dict[str, int] = {}
        alpha_count = 0
        for key, entry in self._store.items():
            top = key.split("/")[0]
            by_dir[top] = by_dir.get(top, 0) + 1
            if entry.has_alpha:
                alpha_count += 1
        return {
            "total":      len(self._store),
            "with_alpha": alpha_count,
            "miss":       len(self._miss),
            "by_dir":     by_dir,
        }

    def print_stats(self) -> None:
        s = self.stats()
        print(f"[TemplateCache] 총 {s['total']}개 "
              f"(알파마스크:{s['with_alpha']} 실패:{s['miss']})")
        for d, cnt in sorted(s["by_dir"].items()):
            print(f"  {d:30s}: {cnt}개")


# ══════════════════════════════════════════════════════════
# 전역 싱글톤
# ══════════════════════════════════════════════════════════

_CACHE: Optional[TemplateCache] = None


def get_cache() -> TemplateCache:
    """전역 TemplateCache 싱글톤 반환."""
    global _CACHE
    if _CACHE is None:
        _CACHE = TemplateCache()
    return _CACHE


def warmup_all(*, verbose: bool = False) -> WarmupResult:
    """
    권장 진입점. main.py 시작 시 호출.
    전역 캐시에 모든 기본 디렉터리를 로드.
    """
    return get_cache().warmup(verbose=verbose)


# ══════════════════════════════════════════════════════════
# 내부 유틸
# ══════════════════════════════════════════════════════════

def _path_to_key(path: str) -> str:
    """
    절대(또는 상대) 경로 → 캐시 키 변환.

    규칙:
      - TEMPLATE_DIR 이하 상대 경로
      - 확장자 제거
      - 구분자를 '/' 로 통일

    예:
      .../templates/star/star_5.png  →  "star/star_5"
      .../templates/menu_detect_flag/lobby_template.png         →  "menu_detect_flag/lobby_template"
    """
    p = Path(path)
    try:
        rel = p.relative_to(TEMPLATE_DIR)
    except ValueError:
        # TEMPLATE_DIR 밖 (예: lobby_template.png)
        try:
            rel = p.relative_to(BASE_DIR)
        except ValueError:
            rel = p
    return str(rel.with_suffix("")).replace("\\", "/")


def _read_template(path: str) -> Optional[TemplateEntry]:
    """
    PNG 파일 → TemplateEntry.
    RGBA: gray/bgr/alpha 분리 저장.
    RGB : gray/bgr 저장, alpha=None.
    실패 시 None.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        img = Image.open(p)

        if img.mode == "RGBA":
            arr   = np.array(img, dtype=np.uint8)
            rgb   = arr[:, :, :3]
            alpha = arr[:, :, 3]
            bgr   = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            gray  = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            return TemplateEntry(gray=gray, bgr=bgr, alpha=alpha, path=path)

        # RGB / L / P → RGB 로 통일
        rgb  = np.array(img.convert("RGB"), dtype=np.uint8)
        bgr  = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return TemplateEntry(gray=gray, bgr=bgr, alpha=None, path=path)

    except Exception as e:
        print(f"[TemplateCache] 파일 읽기 오류 ({path}): {e}")
        return None


def _default_warmup_dirs() -> list[Path]:
    """기본 warmup 대상 디렉터리 목록."""
    names = [
        "menu_detect_flag",
        # 별 등급
        "star",
        "weapon_star",
        # 무기 상태
        "weapon_state",
        # check 플래그
        "skillcheck",
        "equipcheck",
        # 장비 슬롯 플래그
        "equip1_flag",
        "equip2_flag",
        "equip3_flag",
        "equip4_flag",
        # 장비 티어
        "equip1",
        "equip2",
        "equip3",
        "equip4",
        # 장비 레벨 digit
        "equip1level_digit1",
        "equip1level_digit2",
        "equip2level_digit1",
        "equip2level_digit2",
        "equip3level_digit1",
        "equip3level_digit2",
        # 무기 레벨 digit
        "weaponlevel_digit1",
        "weaponlevel_digit2",
        # 학생 레벨 digit
        "studentlevel_digit1",
        "studentlevel_digit2",
        # 스킬 레벨
        "EX_Skill",
        "Skill1",
        "Skill2",
        "Skill3",
        # 스탯
        "stat_hp",
        "stat_atk",
        "stat_heal",
        # 학생 텍스처
        "students",
    ]
    dirs = [TEMPLATE_DIR / n for n in names]
    return dirs
