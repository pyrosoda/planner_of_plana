"""
core/matcher.py — BA Analyzer v6
OpenCV 템플릿 매칭 엔진

변경점 (v5 → v6):
  - 전처리 코드 제거 → core/preprocess.py 위임
  - 파일 I/O 제거 → core/template_cache.py 위임
    · _load_tmpl (lru_cache) 완전 제거
    · 모든 템플릿 접근은 _tmpl(path) 헬퍼를 통해 캐시에서만 읽음
  - 함수 내부에 Image.open / cv2.imread / lru_cache 없음
  - 디버그 로그 포맷 통일: [Matcher] {함수명}: {결과} ({점수:.3f})
"""

from __future__ import annotations

import cv2
import numpy as np
from enum import Enum
from pathlib import Path
from PIL import Image
from typing import Optional

from core.config import TEMPLATE_DIR, BASE_DIR
from core.preprocess import (
    to_gray,
    to_bgr,
    normalize_hist,
    binarize,
    focus_center_crop,
    preprocess_for_template,
    preprocess_for_masked_template,
    preprocess_for_text_template,
    preprocess_for_color_hist,
    calc_color_hist,
)
from core.template_cache import get_cache, TemplateEntry


# ── 템플릿 접근 헬퍼 ──────────────────────────────────────

def _tmpl(path: str) -> Optional[TemplateEntry]:
    """
    경로로 캐시에서 TemplateEntry 조회.
    캐시 미스 시 on-demand 로드 후 반환.
    파일 없으면 None.
    """
    cache = get_cache()
    entry = cache.get_by_path(path)
    if entry is not None:
        return entry
    # warmup 에 포함되지 않은 파일 — on-demand 로드
    return cache.load(path)


# ══════════════════════════════════════════════════════════
# 매칭 임계값
# ══════════════════════════════════════════════════════════

THRESHOLD         = 0.80
THRESHOLD_LOOSE   = 0.72
THRESHOLD_LOBBY   = 0.75
TEXTURE_THRESHOLD        = 0.60
TEXTURE_MARGIN_REQUIRED  = 0.05


# ══════════════════════════════════════════════════════════
# 디렉터리 / 파일 상수
# ══════════════════════════════════════════════════════════

STUDENT_TEXTURE_DIR = "students"
WEAPON_STATE_DIR    = "weapon_state"
SKILL_CHECK_DIR     = "skillcheck"
EQUIP_CHECK_DIR     = "equipcheck"

WEAPON_STATE_FILES = {
    "no_weapon":       "NO_WEAPON_SYSTEM.png",
    "weapon_locked":   "WEAPON_UNLOCKED_NOT_EQUIPPED.png",
    "weapon_unlocked": "WEAPON_EQUIPPED.png",
}

STAT_DIRS = {
    "hp":   "stat_hp",
    "atk":  "stat_atk",
    "heal": "stat_heal",
}


# ══════════════════════════════════════════════════════════
# Enum
# ══════════════════════════════════════════════════════════

class WeaponState(Enum):
    NO_WEAPON_SYSTEM             = "no_weapon_system"
    WEAPON_EQUIPPED              = "weapon_equipped"
    WEAPON_UNLOCKED_NOT_EQUIPPED = "weapon_unlocked_not_equipped"

WeaponStatus = WeaponState   # 하위 호환


class CheckFlag(Enum):
    TRUE       = "true"
    FALSE      = "false"
    IMPOSSIBLE = "impossible"


class EquipSlotFlag(Enum):
    NORMAL       = "normal"
    EMPTY        = "empty"
    LEVEL_LOCKED = "level_locked"
    LOVE_LOCKED  = "love_locked"
    NULL         = "null"


# ── _load_tmpl 은 제거됨 → _tmpl() 헬퍼 사용 (파일 상단)


# ══════════════════════════════════════════════════════════
# 기본 매칭 함수
# ══════════════════════════════════════════════════════════

def match_score(crop: Image.Image, tmpl_path: str) -> float:
    """
    원본 해상도 TM_CCOEFF_NORMED 매칭 (알파 마스크 지원).
    로비 감지처럼 크기가 고정된 경우에 사용.
    파일 I/O 없음 — _tmpl() 캐시에서 읽음.
    """
    entry = _tmpl(tmpl_path)
    if entry is None:
        return 0.0
    bgr_c = to_bgr(crop)
    if entry.bgr.shape[0] > bgr_c.shape[0] or entry.bgr.shape[1] > bgr_c.shape[1]:
        return 0.0
    try:
        if entry.has_alpha and entry.alpha.max() > 0:
            res = cv2.matchTemplate(bgr_c, entry.bgr, cv2.TM_CCORR_NORMED,
                                    mask=entry.alpha)
        else:
            res = cv2.matchTemplate(bgr_c, entry.bgr, cv2.TM_CCOEFF_NORMED)
        _, val, _, _ = cv2.minMaxLoc(res)
        return float(val)
    except cv2.error:
        return 0.0


def match_score_resized(
    crop: Image.Image,
    tmpl_path: str,
    focus_center: bool = False,
) -> float:
    """
    crop 을 템플릿 크기에 맞춰 리사이즈 후 이진화 비교.
    전처리: preprocess_for_template()
    점수: NCC 0.7 + pixel_diff 0.3
    파일 I/O 없음 — _tmpl() 캐시에서 읽음.
    """
    entry = _tmpl(tmpl_path)
    if entry is None:
        return 0.0

    h_t, w_t = entry.gray.shape[:2]
    if h_t < 2 or w_t < 2:
        return 0.0

    crop_proc = preprocess_for_template(crop, w_t, h_t, use_focus_crop=focus_center)
    tmpl_proc = _preprocess_tmpl_gray(entry.gray, w_t, h_t, use_focus_crop=focus_center)

    return _ncc_diff_score(crop_proc, tmpl_proc)


def match_score_resized_masked(
    crop: Image.Image,
    tmpl_path: str,
    focus_center: bool = False,
    binarize_flag: bool = True,
) -> float:
    """
    알파 마스크 기반 리사이즈 매칭.
    전처리: preprocess_for_masked_template()
    점수: corr 0.50 + diff 0.30 + edge 0.20
    파일 I/O 없음 — _tmpl() 캐시에서 읽음.
    """
    entry = _tmpl(tmpl_path)
    if entry is None:
        return 0.0

    h_t, w_t = entry.gray.shape[:2]
    if h_t < 2 or w_t < 2:
        return 0.0

    crop_proc, alpha_r = preprocess_for_masked_template(
        crop, w_t, h_t, entry.alpha,
        use_focus_crop=focus_center,
        do_binarize=binarize_flag,
    )
    tmpl_proc = _preprocess_tmpl_gray(entry.gray, w_t, h_t,
                                      use_focus_crop=focus_center,
                                      do_binarize=binarize_flag)

    # alpha_r 이 focus_crop 으로 잘렸을 수 있으니 크기 재확인
    h_p, w_p = crop_proc.shape[:2]
    if alpha_r is None:
        alpha_r = np.full((h_p, w_p), 255, dtype=np.uint8)
    else:
        alpha_r = cv2.resize(alpha_r, (w_p, h_p), interpolation=cv2.INTER_NEAREST)

    valid = alpha_r > 0
    if not np.any(valid):
        return 0.0

    crop_f = crop_proc.astype(np.float32)
    tmpl_f = tmpl_proc.astype(np.float32)

    masked_diff = np.abs(crop_f - tmpl_f)[valid].mean() / 255.0
    diff_score  = 1.0 - float(masked_diff)

    cv_  = crop_f[valid] - crop_f[valid].mean()
    tv_  = tmpl_f[valid] - tmpl_f[valid].mean()
    dnom = np.linalg.norm(cv_) * np.linalg.norm(tv_)
    corr = 0.0 if dnom < 1e-6 else float(np.dot(cv_, tv_) / dnom)
    corr = max(0.0, min(1.0, (corr + 1.0) / 2.0))

    crop_edge = cv2.Canny(crop_proc, 50, 150)
    tmpl_edge = cv2.Canny(tmpl_proc, 50, 150)
    edge_score = 1.0 - float(
        np.abs(crop_edge.astype(np.float32) - tmpl_edge.astype(np.float32))[valid].mean() / 255.0
    )

    return 0.50 * corr + 0.30 * diff_score + 0.20 * edge_score


def match_score_textonly(crop: Image.Image, tmpl_path: str) -> float:
    """
    텍스트(숫자) 픽셀만 추출해서 비교.
    전처리: preprocess_for_text_template()
    점수: NCC 0.7 + pixel_diff 0.3
    파일 I/O 없음 — _tmpl() 캐시에서 읽음.
    """
    entry = _tmpl(tmpl_path)
    if entry is None:
        return 0.0

    h_t, w_t = entry.gray.shape[:2]
    if h_t < 2 or w_t < 2:
        return 0.0

    crop_proc = preprocess_for_text_template(crop, w_t, h_t)
    tmpl_proc = preprocess_for_text_template(
        Image.fromarray(entry.gray), w_t, h_t
    )
    return _ncc_diff_score(crop_proc, tmpl_proc)


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _preprocess_tmpl_gray(
    tmpl_g: np.ndarray,
    w: int,
    h: int,
    use_focus_crop: bool = False,
    do_binarize: bool = True,
) -> np.ndarray:
    """
    이미 로드된 템플릿 gray ndarray 를 동일 파이프라인으로 전처리.
    (PIL Image 변환 없이 바로 처리해 속도 절감)
    """
    arr = cv2.resize(tmpl_g, (w, h), interpolation=cv2.INTER_AREA)
    arr = normalize_hist(arr)
    if do_binarize:
        arr = binarize(arr)
    if use_focus_crop:
        arr, _ = focus_center_crop(arr)
    return arr


def _ncc_diff_score(a: np.ndarray, b: np.ndarray) -> float:
    """NCC 0.7 + pixel_diff 0.3 점수."""
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    try:
        res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
        _, ncc, _, _ = cv2.minMaxLoc(res)
        diff = np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0
        return 0.7 * float(ncc) + 0.3 * (1.0 - float(diff))
    except cv2.error:
        return 0.0


def best_match(
    crop: Image.Image,
    candidates: dict[str, str],
    threshold: float = THRESHOLD,
    resized: bool = False,
    focus_center: bool = False,
    masked: bool = False,
) -> tuple[Optional[str], float]:
    best_lbl, best_scr = None, threshold
    for lbl, path in candidates.items():
        if masked:
            s = match_score_resized_masked(crop, path, focus_center=focus_center)
        elif resized:
            s = match_score_resized(crop, path, focus_center=focus_center)
        else:
            s = match_score(crop, path)
        if s > best_scr:
            best_scr, best_lbl = s, lbl
    return best_lbl, best_scr


# ══════════════════════════════════════════════════════════
# 로비 감지
# ══════════════════════════════════════════════════════════

_LOBBY_TMPL = str(BASE_DIR / "lobby_template.png")


def is_lobby(img: Image.Image, region: dict) -> bool:
    from core.capture import crop_region
    crop  = crop_region(img, region)
    score = match_score(crop, _LOBBY_TMPL)
    print(f"[Matcher] is_lobby: {score:.3f}")
    return score >= THRESHOLD_LOBBY


# ══════════════════════════════════════════════════════════
# 학생 텍스처 매칭
# ══════════════════════════════════════════════════════════

def _color_hist_score(crop: Image.Image, tmpl_path: str) -> float:
    """컬러 히스토그램 유사도. 파일 I/O 없음 — _tmpl() 캐시에서 읽음."""
    entry = _tmpl(tmpl_path)
    if entry is None:
        return 0.0
    try:
        hsv_c = preprocess_for_color_hist(crop)
        tmpl_small = cv2.resize(entry.bgr, (64, 64), interpolation=cv2.INTER_AREA)
        hsv_t = cv2.cvtColor(tmpl_small, cv2.COLOR_BGR2HSV)
        hc = calc_color_hist(hsv_c)
        ht = calc_color_hist(hsv_t)
        return max(0.0, float(cv2.compareHist(hc, ht, cv2.HISTCMP_CORREL)))
    except cv2.error:
        return 0.0


def match_student_texture(crop: Image.Image) -> tuple[Optional[str], float]:
    import core.student_names as _sn
    texture_dir = TEMPLATE_DIR / STUDENT_TEXTURE_DIR
    if not texture_dir.exists():
        return None, 0.0

    cands = {
        sid: str(texture_dir / _sn.template_path(sid))
        for sid in _sn.all_ids()
        if (texture_dir / _sn.template_path(sid)).exists()
    }
    if not cands:
        return None, 0.0

    scores = sorted(
        [
            (sid, 0.55 * match_score_resized(crop, p)
                + 0.45 * _color_hist_score(crop, p))
            for sid, p in cands.items()
        ],
        key=lambda x: x[1],
        reverse=True,
    )
    best_id, best_s = scores[0]
    second_s = scores[1][1] if len(scores) > 1 else 0.0
    margin   = best_s - second_s

    print(
        f"[Matcher] texture: 1위={best_id}({best_s:.3f}) "
        f"2위={scores[1][0] if len(scores)>1 else '-'}({second_s:.3f}) "
        f"margin={margin:.3f}"
    )

    if best_s < TEXTURE_THRESHOLD or margin < TEXTURE_MARGIN_REQUIRED:
        return None, best_s
    return best_id, best_s

identify_student_by_texture = match_student_texture   # 하위 호환


# ══════════════════════════════════════════════════════════
# 무기 상태
# ══════════════════════════════════════════════════════════

def detect_weapon_state(crop: Image.Image) -> tuple[WeaponState, float]:
    d = TEMPLATE_DIR / WEAPON_STATE_DIR
    mapping = {
        "no_weapon":       WeaponState.NO_WEAPON_SYSTEM,
        "weapon_locked":   WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED,
        "weapon_unlocked": WeaponState.WEAPON_EQUIPPED,
    }
    scores = {
        k: (match_score_resized(crop, str(d / WEAPON_STATE_FILES[k]))
            if (d / WEAPON_STATE_FILES[k]).exists() else 0.0)
        for k in mapping
    }

    if not any(v > 0 for v in scores.values()):
        return WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED, 0.0

    best_key = max(scores, key=lambda k: scores[k])
    best_val = scores[best_key]
    print(f"[Matcher] weapon_state: { {k: f'{v:.3f}' for k,v in scores.items()} } → {best_key}")

    if best_val < 0.55:
        return WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED, best_val
    return mapping[best_key], best_val

detect_weapon_status = detect_weapon_state   # 하위 호환


# ══════════════════════════════════════════════════════════
# Check 플래그
# ══════════════════════════════════════════════════════════

def read_check_flag(crop: Image.Image, folder: str) -> CheckFlag:
    d = TEMPLATE_DIR / folder
    cands = {
        flag: str(d / f"{flag}.png")
        for flag in ("true", "false")
        if (d / f"{flag}.png").exists()
    }
    if not cands:
        return CheckFlag.FALSE
    lbl, score = best_match(crop, cands, threshold=0.55, resized=True)
    if lbl is None:
        return CheckFlag.FALSE
    print(f"[Matcher] check_flag({folder}): {lbl} ({score:.3f})")
    return CheckFlag(lbl)


def read_skill_check(crop: Image.Image) -> CheckFlag:
    return read_check_flag(crop, SKILL_CHECK_DIR)


def read_equip_check(crop: Image.Image) -> CheckFlag:
    d = TEMPLATE_DIR / EQUIP_CHECK_DIR

    explicit: dict[str, float] = {}
    for flag in ("possible", "impossible"):
        p = d / f"{flag}.png"
        if p.exists():
            explicit[flag] = match_score_resized(crop, str(p), focus_center=True)

    if explicit:
        print(f"[Matcher] equip_check explicit: "
              + " ".join(f"{k}={v:.3f}" for k, v in explicit.items()))

        possible_s   = explicit.get("possible",   0.0)
        impossible_s = explicit.get("impossible", 0.0)
        best_label   = max(explicit, key=explicit.get)
        best_score   = explicit[best_label]
        margin       = abs(possible_s - impossible_s)

        if best_label == "impossible" and (best_score >= 0.50 or margin >= 0.03):
            print(f"[Matcher] equip_check → IMPOSSIBLE")
            return CheckFlag.IMPOSSIBLE
        return CheckFlag.FALSE

    IMPOSSIBLE_TF_MAX = 0.45
    TRUE_THRESHOLD    = 0.55

    scores: dict[str, float] = {
        flag: match_score_resized(crop, str(d / f"{flag}.png"))
        for flag in ("impossible", "true", "false")
        if (d / f"{flag}.png").exists()
    }
    print(f"[Matcher] equip_check legacy: "
          + " ".join(f"{k}={v:.3f}" for k, v in scores.items()))

    true_s  = scores.get("true",  0.0)
    false_s = scores.get("false", 0.0)
    if max(true_s, false_s) < IMPOSSIBLE_TF_MAX:
        return CheckFlag.IMPOSSIBLE
    if true_s >= TRUE_THRESHOLD:
        return CheckFlag.TRUE
    return CheckFlag.FALSE


def read_equip_check_inside(crop: Image.Image) -> CheckFlag:
    TRUE_THRESHOLD = 0.55
    d = TEMPLATE_DIR / EQUIP_CHECK_DIR
    scores = {
        flag: match_score_resized(crop, str(d / f"{flag}.png"))
        for flag in ("true", "false")
        if (d / f"{flag}.png").exists()
    }
    print(f"[Matcher] equip_check_inside: "
          + " ".join(f"{k}={v:.3f}" for k, v in scores.items()))
    return CheckFlag.TRUE if scores.get("true", 0.0) >= TRUE_THRESHOLD else CheckFlag.FALSE


# ══════════════════════════════════════════════════════════
# 장비 슬롯 플래그
# ══════════════════════════════════════════════════════════

def read_equip_slot_flag(crop: Image.Image, slot: int) -> EquipSlotFlag:
    d = TEMPLATE_DIR / f"equip{slot}_flag"
    flag_files: dict[str, str] = {
        "empty": f"equip{slot}_empty.png",
    }
    if slot in (2, 3):
        flag_files["level_locked"] = f"equip{slot}_level_locked.png"
    if slot == 4:
        flag_files["love_locked"] = "equip4_love_locked.png"
        flag_files["null"]        = "equip4_null.png"

    cands = {k: str(d / v) for k, v in flag_files.items() if (d / v).exists()}
    if not cands:
        return EquipSlotFlag.NORMAL

    lbl, score = best_match(crop, cands, threshold=0.60, resized=True)
    if lbl is None:
        return EquipSlotFlag.NORMAL
    print(f"[Matcher] equip{slot}_flag: {lbl} ({score:.3f})")
    return EquipSlotFlag(lbl)


# ══════════════════════════════════════════════════════════
# 스탯
# ══════════════════════════════════════════════════════════

def read_stat_value(crop: Image.Image, stat_key: str) -> Optional[int]:
    folder = STAT_DIRS.get(stat_key)
    if not folder:
        return None
    d = TEMPLATE_DIR / folder
    if not d.exists():
        return None
    cands = {
        str(i): str(d / f"{i}.png")
        for i in range(26)
        if (d / f"{i}.png").exists()
    }
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.60,
                             resized=True, focus_center=True)
    if lbl is None:
        return None
    print(f"[Matcher] stat_{stat_key}: {lbl} ({score:.3f})")
    return int(lbl)


# ══════════════════════════════════════════════════════════
# Digit 폴더 읽기 (장비 레벨 / 무기 레벨 / 학생 레벨 공통)
# ══════════════════════════════════════════════════════════

def _read_digit_from_folder(
    folder: Path,
    prefix: int,
    crop: Image.Image,
) -> Optional[str]:
    if not folder.exists():
        return None
    cands = {
        p.stem.split("_", 1)[1]: str(p)
        for p in folder.glob(f"{prefix}_*.png")
    }
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.55,
                             resized=True, focus_center=True)
    print(f"[Matcher] {folder.name}: {lbl} ({score:.3f})")
    return lbl


def read_equip_level(
    img: Image.Image,
    slot: int,
    d1_region: dict,
    d2_region: dict,
) -> Optional[int]:
    from core.capture import crop_region
    folder1 = TEMPLATE_DIR / f"equip{slot}level_digit1"
    folder2 = TEMPLATE_DIR / f"equip{slot}level_digit2"
    d1 = _read_digit_from_folder(folder1, 1, crop_region(img, d1_region))
    d2 = _read_digit_from_folder(folder2, 2, crop_region(img, d2_region))

    if not d1 or d1 == "v":
        if d2:
            try: return int(d2)
            except ValueError: pass
        return None
    if d2:
        try: return int(d1 + d2)
        except ValueError: pass
    try: return int(d1)
    except ValueError: return None


def read_weapon_level(
    img: Image.Image,
    d1_region: dict,
    d2_region: dict,
) -> Optional[int]:
    from core.capture import crop_region
    folder1 = TEMPLATE_DIR / "weaponlevel_digit1"
    folder2 = TEMPLATE_DIR / "weaponlevel_digit2"
    d1 = _read_digit_from_folder(folder1, 1, crop_region(img, d1_region))
    d2 = _read_digit_from_folder(folder2, 2, crop_region(img, d2_region))

    if not d2 or d2 == "null":
        if d1:
            try: return int(d1)
            except ValueError: pass
        return None
    if d1:
        try: return int(d1 + d2)
        except ValueError: pass
    try: return int(d2)
    except ValueError: return None


# ══════════════════════════════════════════════════════════
# 별 등급
# ══════════════════════════════════════════════════════════

def read_star(crop: Image.Image, folder: str, max_n: int) -> int:
    d = TEMPLATE_DIR / folder
    cands = {
        str(i): str(d / f"star_{i}.png")
        for i in range(max_n, 0, -1)
        if (d / f"star_{i}.png").exists()
    }
    lbl, score = best_match(crop, cands, threshold=0.68, masked=True)
    print(f"[Matcher] {folder} star: {lbl} ({score:.3f})")
    return int(lbl) if lbl else 1


def read_student_star(crop: Image.Image) -> int:
    return read_star(crop, "star", 5)


def read_weapon_star(crop: Image.Image) -> int:
    return read_star(crop, "weapon_star", 4)


def is_weapon_equipped(crop: Image.Image) -> bool:
    return detect_weapon_state(crop)[0] == WeaponState.WEAPON_EQUIPPED

read_weapon_unlocked = is_weapon_equipped   # 하위 호환


# ══════════════════════════════════════════════════════════
# 학생 레벨
# ══════════════════════════════════════════════════════════

def read_level_digit(crop: Image.Image, digit_pos: int) -> Optional[str]:
    folder = TEMPLATE_DIR / f"studentlevel_digit{digit_pos}"
    if not folder.exists():
        return None
    start = 1 if digit_pos == 1 else 0
    cands = {
        str(i): str(folder / f"{digit_pos}_{i}.png")
        for i in range(start, 10)
        if (folder / f"{digit_pos}_{i}.png").exists()
    }
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.55,
                             resized=True, focus_center=True)
    print(f"[Matcher] level_digit{digit_pos}: {lbl} ({score:.3f})")
    return lbl


def read_student_level(
    img: Image.Image,
    digit1_region: dict,
    digit2_region: dict,
) -> str:
    from core.capture import crop_region
    d1 = read_level_digit(crop_region(img, digit1_region), 1)
    d2 = read_level_digit(crop_region(img, digit2_region), 2)

    if not d2 or d2 == "null":
        if d1:
            print(f"[Matcher] student_level: 1자리 → {d1}")
            return d1
        return "unknown"
    return f"{d1}{d2}" if d1 else d2


# ══════════════════════════════════════════════════════════
# 스킬 레벨
# ══════════════════════════════════════════════════════════

def read_skill(crop: Image.Image, skill_key: str) -> str:
    d = TEMPLATE_DIR / skill_key
    max_lv = 5 if skill_key == "EX_Skill" else 10
    cands: dict[str, str] = {}

    if skill_key == "EX_Skill":
        for i in range(max_lv, 0, -1):
            p = d / f"EX_Skill_{i}.png"
            if p.exists():
                cands[str(i)] = str(p)
    else:
        prefix = skill_key.replace("Skill", "Skill_")
        locked = d / f"{prefix}_locked.png"
        if locked.exists():
            cands["locked"] = str(locked)
        for i in range(max_lv, 0, -1):
            p = d / f"{prefix}_{i}.png"
            if p.exists():
                cands[str(i)] = str(p)

    if not cands:
        return "unknown"

    scores: dict[str, tuple[float, float, float]] = {}
    for lbl, path in cands.items():
        ui   = match_score_resized(crop, path, focus_center=True)
        text = match_score_textonly(crop, path) if lbl != "locked" else 0.0
        final = ui if lbl == "locked" else (0.55 * ui + 0.45 * text)
        scores[lbl] = (final, ui, text)

    ranked = sorted(scores.items(), key=lambda x: x[1][0], reverse=True)
    best_lbl, (best_score, best_ui, best_text) = ranked[0]

    if len(ranked) >= 2:
        second_lbl, (second_score, _, _) = ranked[1]
        if {best_lbl, second_lbl} == {"1", "2"} and abs(best_score - second_score) <= 0.035:
            chosen   = "1" if scores["1"][2] >= scores["2"][2] else "2"
            best_lbl = chosen
            best_score, best_ui, best_text = scores[chosen]

    print(f"[Matcher] {skill_key}: {best_lbl} "
          f"(final={best_score:.3f} ui={best_ui:.3f} text={best_text:.3f})")
    return best_lbl if best_score >= 0.60 else "unknown"


# ══════════════════════════════════════════════════════════
# 장비 티어
# ══════════════════════════════════════════════════════════

def read_equip_tier(crop: Image.Image, slot: int) -> str:
    d = TEMPLATE_DIR / f"equip{slot}"
    candidates: dict[str, str] = {}

    empty_p = d / f"equip{slot}_empty.png"
    if empty_p.exists():
        candidates["empty"] = str(empty_p)
    for p in d.glob(f"equip{slot}_T*.png"):
        candidates[p.stem.replace(f"equip{slot}_", "")] = str(p)

    if not candidates:
        print(f"[Matcher] equip{slot}: 템플릿 없음 → unknown")
        return "unknown"

    scores = {
        lbl: (0.60 * match_score_resized(crop, path)
              + 0.40 * _color_hist_score(crop, path))
        for lbl, path in candidates.items()
    }
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    print(f"[Matcher] equip{slot} tier: "
          + " ".join(f"{t}={s:.3f}" for t, s in ranked))

    best_lbl, best_score = ranked[0]
    if best_score < THRESHOLD_LOOSE:
        print(f"[Matcher] equip{slot}: {best_lbl}({best_score:.3f}) < {THRESHOLD_LOOSE} → unknown")
        return "unknown"
    return best_lbl


# ══════════════════════════════════════════════════════════
# V5 공식 인터페이스 (하위 호환)
# ══════════════════════════════════════════════════════════

def read_student_star_v5(crop: Image.Image) -> Optional[int]:
    d = TEMPLATE_DIR / "star"
    cands = {
        str(i): str(d / f"star_{i}.png")
        for i in range(5, 0, -1)
        if (d / f"star_{i}.png").exists()
    }
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.65, masked=True)
    print(f"[Matcher] student_star_v5: {lbl} ({score:.3f})")
    return int(lbl) if lbl is not None else None


def read_weapon_star_v5(crop: Image.Image) -> Optional[int]:
    d = TEMPLATE_DIR / "weapon_star"
    cands = {
        str(i): str(d / f"star_{i}.png")
        for i in range(4, 0, -1)
        if (d / f"star_{i}.png").exists()
    }
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.65, masked=True)
    print(f"[Matcher] weapon_star_v5: {lbl} ({score:.3f})")
    return int(lbl) if lbl is not None else None


def read_student_level_v5(
    img: Image.Image,
    digit1_region: dict,
    digit2_region: dict,
) -> Optional[int]:
    raw = read_student_level(img, digit1_region, digit2_region)
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(f"[Matcher] read_student_level_v5: 변환 실패 (raw='{raw}')")
        return None