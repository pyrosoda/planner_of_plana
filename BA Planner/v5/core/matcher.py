"""
core/matcher.py — OpenCV 템플릿 매칭 엔진  (V5.1)

[V5.1 추가]
  - CheckFlag            : true/false/impossible 플래그 enum
  - EquipSlotFlag        : 장비 슬롯 상태 enum (normal/empty/level_locked/love_locked/null)
  - read_check_flag()    : skillcheck / equipcheck 폴더 플래그 판별
  - read_skill_check()   : skillcheck 전용
  - read_equip_check()   : equipcheck 전용 (impossible 포함)
  - read_equip_slot_flag(): equip{N}_flag/ 아래 슬롯 상태 판별
  - read_stat_value()    : stat_hp/atk/heal 템플릿 매칭 (0~25)
  - read_equip_level()   : equip{N}level_digit{D} 폴더로 레벨 읽기
  - read_weapon_level()  : weaponlevel_digit{D} 폴더로 레벨 읽기 (null 처리)
  - read_skill()         : 실제 파일명 패턴 반영 (EX_Skill_N / Skill_M_N)
"""

import cv2
import numpy as np
from enum import Enum
from pathlib import Path
from PIL import Image
from functools import lru_cache

from core.config import TEMPLATE_DIR, BASE_DIR


# ── 매칭 기준 ─────────────────────────────────────────────
THRESHOLD        = 0.80
THRESHOLD_LOOSE  = 0.72
THRESHOLD_LOBBY  = 0.75
TEXTURE_THRESHOLD        = 0.60
TEXTURE_MARGIN_REQUIRED  = 0.05

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


# ── enum ──────────────────────────────────────────────────
class WeaponState(Enum):
    NO_WEAPON_SYSTEM             = "no_weapon_system"
    WEAPON_EQUIPPED              = "weapon_equipped"
    WEAPON_UNLOCKED_NOT_EQUIPPED = "weapon_unlocked_not_equipped"

WeaponStatus = WeaponState  # 하위 호환


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


# ── 기본 변환 ─────────────────────────────────────────────
def pil_to_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)

def pil_to_gray(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("L"))

def _normalize_gray(arr: np.ndarray) -> np.ndarray:
    return cv2.equalizeHist(arr)

def _binarize(arr: np.ndarray) -> np.ndarray:
    arr = cv2.GaussianBlur(arr, (3, 3), 0)
    _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th


# ── 템플릿 로드 ───────────────────────────────────────────
@lru_cache(maxsize=512)
def _load_tmpl(path: str):
    p = Path(path)
    if not p.exists():
        return None, None, None
    img = Image.open(p)
    if img.mode == "RGBA":
        arr   = np.array(img)
        rgb   = arr[:, :, :3]
        alpha = arr[:, :, 3]
        bgr   = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        gray  = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return bgr, alpha, gray
    rgb  = np.array(img.convert("RGB"))
    bgr  = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return bgr, None, gray


# ── 기본 매칭 ─────────────────────────────────────────────
def match_score(crop: Image.Image, tmpl_path: str) -> float:
    bgr_t, alpha_mask, _ = _load_tmpl(tmpl_path)
    if bgr_t is None:
        return 0.0
    bgr_c = pil_to_bgr(crop)
    if bgr_t.shape[0] > bgr_c.shape[0] or bgr_t.shape[1] > bgr_c.shape[1]:
        return 0.0
    try:
        if alpha_mask is not None and alpha_mask.max() > 0:
            res = cv2.matchTemplate(bgr_c, bgr_t, cv2.TM_CCORR_NORMED, mask=alpha_mask)
        else:
            res = cv2.matchTemplate(bgr_c, bgr_t, cv2.TM_CCOEFF_NORMED)
        _, val, _, _ = cv2.minMaxLoc(res)
        return float(val)
    except cv2.error:
        return 0.0


def match_score_resized(crop: Image.Image, tmpl_path: str, focus_center: bool = False) -> float:
    _, _, tmpl_g = _load_tmpl(tmpl_path)
    if tmpl_g is None:
        return 0.0
    crop_g = pil_to_gray(crop)
    h, w = crop_g.shape[:2]
    if h < 5 or w < 5:
        return 0.0
    tmpl_g = cv2.resize(tmpl_g, (w, h), interpolation=cv2.INTER_AREA)
    crop_g = _normalize_gray(crop_g)
    tmpl_g = _normalize_gray(tmpl_g)
    crop_b = _binarize(crop_g)
    tmpl_b = _binarize(tmpl_g)
    if focus_center:
        x1, x2 = int(w * 0.22), int(w * 0.78)
        y1, y2 = int(h * 0.10), int(h * 0.92)
        if x2 > x1 and y2 > y1:
            crop_b = crop_b[y1:y2, x1:x2]
            tmpl_b = tmpl_b[y1:y2, x1:x2]
    try:
        res = cv2.matchTemplate(crop_b, tmpl_b, cv2.TM_CCOEFF_NORMED)
        _, ncc, _, _ = cv2.minMaxLoc(res)
        diff = np.mean(np.abs(crop_b.astype(np.float32) - tmpl_b.astype(np.float32))) / 255.0
        return 0.7 * float(ncc) + 0.3 * (1.0 - float(diff))
    except cv2.error:
        return 0.0


def match_score_resized_masked(
    crop: Image.Image, tmpl_path: str,
    focus_center: bool = False, binarize: bool = True
) -> float:
    _, alpha_mask, tmpl_gray = _load_tmpl(tmpl_path)
    if tmpl_gray is None:
        return 0.0
    crop_gray = pil_to_gray(crop)
    h, w = crop_gray.shape[:2]
    if h < 5 or w < 5:
        return 0.0
    tmpl_gray = cv2.resize(tmpl_gray, (w, h), interpolation=cv2.INTER_AREA)
    if alpha_mask is not None:
        alpha_mask = cv2.resize(alpha_mask, (w, h), interpolation=cv2.INTER_NEAREST)
    else:
        alpha_mask = np.full((h, w), 255, dtype=np.uint8)
    crop_gray = _normalize_gray(crop_gray)
    tmpl_gray = _normalize_gray(tmpl_gray)
    if binarize:
        crop_proc = _binarize(crop_gray)
        tmpl_proc = _binarize(tmpl_gray)
    else:
        crop_proc = crop_gray
        tmpl_proc = tmpl_gray
    if focus_center:
        x1, x2 = int(w * 0.18), int(w * 0.82)
        y1, y2 = int(h * 0.08), int(h * 0.95)
        if x2 > x1 and y2 > y1:
            crop_proc  = crop_proc[y1:y2, x1:x2]
            tmpl_proc  = tmpl_proc[y1:y2, x1:x2]
            alpha_mask = alpha_mask[y1:y2, x1:x2]
    valid = alpha_mask > 0
    if not np.any(valid):
        return 0.0
    crop_f = crop_proc.astype(np.float32)
    tmpl_f = tmpl_proc.astype(np.float32)
    masked_diff = np.abs(crop_f - tmpl_f)[valid].mean() / 255.0
    diff_score  = 1.0 - float(masked_diff)
    crop_v = crop_f[valid] - crop_f[valid].mean()
    tmpl_v = tmpl_f[valid] - tmpl_f[valid].mean()
    denom = np.linalg.norm(crop_v) * np.linalg.norm(tmpl_v)
    if denom < 1e-6:
        corr_score = 0.0
    else:
        corr_score = float(np.dot(crop_v, tmpl_v) / denom)
        corr_score = max(0.0, min(1.0, (corr_score + 1.0) / 2.0))
    crop_edge  = cv2.Canny(crop_proc, 50, 150)
    tmpl_edge  = cv2.Canny(tmpl_proc, 50, 150)
    edge_score = 1.0 - float(np.abs(crop_edge.astype(np.float32) - tmpl_edge.astype(np.float32))[valid].mean() / 255.0)
    return 0.50 * corr_score + 0.30 * diff_score + 0.20 * edge_score


def _extract_dark_text_mask(arr: np.ndarray, out_size=(96, 30)) -> np.ndarray:
    arr = cv2.GaussianBlur(arr, (3, 3), 0)
    _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.where(th > 0)
    if len(xs) == 0:
        return np.zeros((out_size[1], out_size[0]), dtype=np.uint8)
    pad = 2
    roi = th[max(0, ys.min()-pad):min(th.shape[0], ys.max()+pad+1),
             max(0, xs.min()-pad):min(th.shape[1], xs.max()+pad+1)]
    if roi.size == 0:
        return np.zeros((out_size[1], out_size[0]), dtype=np.uint8)
    return cv2.resize(roi, out_size, interpolation=cv2.INTER_AREA)


def match_score_textonly(crop: Image.Image, tmpl_path: str) -> float:
    _, _, tmpl_g = _load_tmpl(tmpl_path)
    if tmpl_g is None:
        return 0.0
    crop_g = pil_to_gray(crop)
    h, w = crop_g.shape[:2]
    if h < 5 or w < 5:
        return 0.0
    tmpl_g = cv2.resize(tmpl_g, (w, h), interpolation=cv2.INTER_AREA)
    crop_t = _extract_dark_text_mask(crop_g)
    tmpl_t = _extract_dark_text_mask(tmpl_g)
    try:
        res = cv2.matchTemplate(crop_t, tmpl_t, cv2.TM_CCOEFF_NORMED)
        _, ncc, _, _ = cv2.minMaxLoc(res)
        diff = np.mean(np.abs(crop_t.astype(np.float32) - tmpl_t.astype(np.float32))) / 255.0
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
) -> tuple[str | None, float]:
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


# ── 로비 감지 ─────────────────────────────────────────────
_LOBBY_TMPL = str(BASE_DIR / "lobby_template.png")

def is_lobby(img: Image.Image, region: dict) -> bool:
    from core.capture import crop_ratio
    crop  = crop_ratio(img, region)
    score = match_score(crop, _LOBBY_TMPL)
    print(f"[Matcher] 로비 점수: {score:.3f}")
    return score >= THRESHOLD_LOBBY


# ── 학생 텍스처 ───────────────────────────────────────────
def _color_hist_score(crop: Image.Image, tmpl_path: str) -> float:
    bgr_t, _, _ = _load_tmpl(tmpl_path)
    if bgr_t is None:
        return 0.0
    bgr_c = pil_to_bgr(crop)
    try:
        sz = (64, 64)
        c_hsv = cv2.cvtColor(cv2.resize(bgr_c, sz), cv2.COLOR_BGR2HSV)
        t_hsv = cv2.cvtColor(cv2.resize(bgr_t, sz), cv2.COLOR_BGR2HSV)
        hc = cv2.calcHist([c_hsv], [0, 1], None, [50, 32], [0, 180, 0, 256])
        ht = cv2.calcHist([t_hsv], [0, 1], None, [50, 32], [0, 180, 0, 256])
        cv2.normalize(hc, hc)
        cv2.normalize(ht, ht)
        return max(0.0, float(cv2.compareHist(hc, ht, cv2.HISTCMP_CORREL)))
    except cv2.error:
        return 0.0


def match_student_texture(crop: Image.Image) -> tuple[str | None, float]:
    import core.student_names as _sn
    texture_dir = TEMPLATE_DIR / STUDENT_TEXTURE_DIR
    if not texture_dir.exists():
        return None, 0.0

    cands = {sid: str(texture_dir / _sn.template_path(sid))
             for sid in _sn.all_ids()
             if (texture_dir / _sn.template_path(sid)).exists()}
    if not cands:
        return None, 0.0

    scores = sorted(
        [(sid, 0.55 * match_score_resized(crop, p) + 0.45 * _color_hist_score(crop, p))
         for sid, p in cands.items()],
        key=lambda x: x[1], reverse=True
    )
    best_id, best_s = scores[0]
    second_s = scores[1][1] if len(scores) > 1 else 0.0
    margin   = best_s - second_s

    print(f"[Matcher] texture 1위={best_id}({best_s:.3f}) "
          f"2위={scores[1][0] if len(scores)>1 else '-'}({second_s:.3f}) "
          f"margin={margin:.3f}")

    if best_s < TEXTURE_THRESHOLD or margin < TEXTURE_MARGIN_REQUIRED:
        return None, best_s
    return best_id, best_s

identify_student_by_texture = match_student_texture  # 하위 호환


# ── 무기 상태 판별 ────────────────────────────────────────
def detect_weapon_state(crop: Image.Image) -> tuple[WeaponState, float]:
    d = TEMPLATE_DIR / WEAPON_STATE_DIR
    mapping = {
        "no_weapon":       WeaponState.NO_WEAPON_SYSTEM,
        "weapon_locked":   WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED,
        "weapon_unlocked": WeaponState.WEAPON_EQUIPPED,
    }
    scores = {k: (match_score_resized(crop, str(d / WEAPON_STATE_FILES[k]))
                  if (d / WEAPON_STATE_FILES[k]).exists() else 0.0)
              for k in mapping}

    if not any(v > 0 for v in scores.values()):
        return WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED, 0.0

    best_key = max(scores, key=lambda k: scores[k])
    best_val = scores[best_key]
    print(f"[Matcher] weapon_state: { {k: f'{v:.3f}' for k,v in scores.items()} } → {best_key}")

    if best_val < 0.55:
        return WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED, best_val
    return mapping[best_key], best_val

detect_weapon_status = detect_weapon_state  # 하위 호환


# ── check 플래그 ──────────────────────────────────────────
def read_check_flag(crop: Image.Image, folder: str) -> CheckFlag:
    d = TEMPLATE_DIR / folder
    cands = {}
    for flag in ("true", "false"):
        p = d / f"{flag}.png"
        if p.exists():
            cands[flag] = str(p)
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

    explicit_scores: dict[str, float] = {}
    for flag in ("possible", "impossible"):
        p = d / f"{flag}.png"
        if p.exists():
            explicit_scores[flag] = match_score_resized(crop, str(p), focus_center=True)

    if explicit_scores:
        print(
            f"[Matcher] equip_check explicit scores: "
            + " ".join(f"{k}={v:.3f}" for k, v in explicit_scores.items())
        )

        possible_s   = explicit_scores.get("possible", 0.0)
        impossible_s = explicit_scores.get("impossible", 0.0)
        best_label   = max(explicit_scores, key=explicit_scores.get)
        best_score   = explicit_scores[best_label]
        margin       = abs(possible_s - impossible_s)

        if best_label == "impossible" and (best_score >= 0.50 or margin >= 0.03):
            print(
                f"[Matcher] equip_check → IMPOSSIBLE "
                f"(possible={possible_s:.3f} impossible={impossible_s:.3f})"
            )
            return CheckFlag.IMPOSSIBLE

        print(
            f"[Matcher] equip_check → POSSIBLE/FALSE "
            f"(possible={possible_s:.3f} impossible={impossible_s:.3f})"
        )
        return CheckFlag.FALSE

    IMPOSSIBLE_TF_MAX = 0.45
    TRUE_THRESHOLD    = 0.55

    scores: dict[str, float] = {}
    for flag in ("impossible", "true", "false"):
        p = d / f"{flag}.png"
        if p.exists():
            scores[flag] = match_score_resized(crop, str(p))

    print(
        f"[Matcher] equip_check legacy scores: "
        + " ".join(f"{k}={v:.3f}" for k, v in scores.items())
    )

    true_s  = scores.get("true",  0.0)
    false_s = scores.get("false", 0.0)
    best_tf = max(true_s, false_s)

    if best_tf < IMPOSSIBLE_TF_MAX:
        print(f"[Matcher] equip_check → IMPOSSIBLE (best_tf={best_tf:.3f} < {IMPOSSIBLE_TF_MAX})")
        return CheckFlag.IMPOSSIBLE

    if true_s >= TRUE_THRESHOLD:
        print(f"[Matcher] equip_check → TRUE ({true_s:.3f})")
        return CheckFlag.TRUE

    print(f"[Matcher] equip_check → FALSE (true={true_s:.3f} false={false_s:.3f})")
    return CheckFlag.FALSE


def read_equip_check_inside(crop: Image.Image) -> CheckFlag:
    TRUE_THRESHOLD = 0.55

    d = TEMPLATE_DIR / EQUIP_CHECK_DIR
    scores: dict[str, float] = {}
    for flag in ("true", "false"):
        p = d / f"{flag}.png"
        if p.exists():
            scores[flag] = match_score_resized(crop, str(p))

    print(
        f"[Matcher] equip_check_inside scores: "
        + " ".join(f"{k}={v:.3f}" for k, v in scores.items())
    )

    true_s = scores.get("true", 0.0)
    if true_s >= TRUE_THRESHOLD:
        print(f"[Matcher] equip_check_inside → TRUE ({true_s:.3f})")
        return CheckFlag.TRUE

    print(f"[Matcher] equip_check_inside → FALSE")
    return CheckFlag.FALSE


# ── 장비 슬롯 플래그 ──────────────────────────────────────
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


# ── 스탯 읽기 ─────────────────────────────────────────────
def read_stat_value(crop: Image.Image, stat_key: str) -> int | None:
    folder = STAT_DIRS.get(stat_key)
    if not folder:
        return None
    d = TEMPLATE_DIR / folder
    if not d.exists():
        return None
    cands = {str(i): str(d / f"{i}.png") for i in range(26) if (d / f"{i}.png").exists()}
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.60, resized=True, focus_center=True)
    if lbl is None:
        return None
    print(f"[Matcher] stat_{stat_key}: {lbl} ({score:.3f})")
    return int(lbl)


# ── 장비 레벨 ─────────────────────────────────────────────
def _read_digit_from_folder(folder: Path, prefix: int, crop: Image.Image) -> str | None:
    if not folder.exists():
        return None
    cands = {}
    for p in folder.glob(f"{prefix}_*.png"):
        key = p.stem.split("_", 1)[1]
        cands[key] = str(p)
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.55, resized=True, focus_center=True)
    print(f"[Matcher] {folder.name}: {lbl} ({score:.3f})")
    return lbl


def read_equip_level(img: Image.Image, slot: int, d1_region: dict, d2_region: dict) -> int | None:
    """
    장비 레벨 읽기.
    - digit1 결과가 'v' 이거나 None → 1자리: digit2 값만 사용
    - 그 외 → digit1 + digit2 를 이어붙여 2자리
    """
    from core.capture import crop_ratio
    folder1 = TEMPLATE_DIR / f"equip{slot}level_digit1"
    folder2 = TEMPLATE_DIR / f"equip{slot}level_digit2"
    d1 = _read_digit_from_folder(folder1, 1, crop_ratio(img, d1_region))
    d2 = _read_digit_from_folder(folder2, 2, crop_ratio(img, d2_region))

    # digit1 == 'v' 또는 None → 1자리 숫자, digit2가 실제 값
    if not d1 or d1 == "v":
        if d2:
            try:
                return int(d2)
            except ValueError:
                pass
        print(f"[Matcher] equip{slot}_level: 1자리 판정 실패 (d1={d1!r} d2={d2!r})")
        return None

    # 2자리
    if d2:
        try:
            return int(d1 + d2)
        except ValueError:
            pass

    # d2 없으면 d1만으로 fallback
    try:
        return int(d1)
    except ValueError:
        pass

    print(f"[Matcher] equip{slot}_level: 변환 실패 (d1={d1!r} d2={d2!r})")
    return None


# ── 무기 레벨 ─────────────────────────────────────────────
def read_weapon_level(img: Image.Image, d1_region: dict, d2_region: dict) -> int | None:
    """
    무기 레벨 읽기.
    - digit2 결과가 'null' 또는 None → 1자리: digit1 값만 사용
    - 그 외 → digit1 + digit2 를 이어붙여 2자리
    """
    from core.capture import crop_ratio
    folder1 = TEMPLATE_DIR / "weaponlevel_digit1"
    folder2 = TEMPLATE_DIR / "weaponlevel_digit2"
    d1 = _read_digit_from_folder(folder1, 1, crop_ratio(img, d1_region))
    d2 = _read_digit_from_folder(folder2, 2, crop_ratio(img, d2_region))

    # digit2 == 'null' 또는 None → 1자리, digit1이 실제 값
    if not d2 or d2 == "null":
        if d1:
            try:
                return int(d1)
            except ValueError:
                pass
        print(f"[Matcher] weapon_level: 1자리 판정 실패 (d1={d1!r} d2={d2!r})")
        return None

    # 2자리
    if d1:
        try:
            return int(d1 + d2)
        except ValueError:
            pass

    # d1 없으면 d2만으로 fallback
    try:
        return int(d2)
    except ValueError:
        pass

    print(f"[Matcher] weapon_level: 변환 실패 (d1={d1!r} d2={d2!r})")
    return None


# ── 별 등급 ───────────────────────────────────────────────
def read_star(crop: Image.Image, folder: str, max_n: int) -> int:
    d = TEMPLATE_DIR / folder
    cands = {str(i): str(d / f"star_{i}.png")
             for i in range(max_n, 0, -1) if (d / f"star_{i}.png").exists()}
    lbl, score = best_match(crop, cands, threshold=0.68, resized=False, masked=True)
    print(f"[Matcher] {folder} star -> {lbl} ({score:.3f})")
    return int(lbl) if lbl else 1

def read_student_star(crop: Image.Image) -> int:
    return read_star(crop, "star", 5)

def read_weapon_star(crop: Image.Image) -> int:
    return read_star(crop, "weapon_star", 4)

def is_weapon_equipped(crop: Image.Image) -> bool:
    return detect_weapon_state(crop)[0] == WeaponState.WEAPON_EQUIPPED

read_weapon_unlocked = is_weapon_equipped


# ── 학생 레벨 digit ──────────────────────────────────────
def read_level_digit(crop: Image.Image, digit_pos: int) -> str | None:
    folder = TEMPLATE_DIR / f"studentlevel_digit{digit_pos}"
    if not folder.exists():
        return None
    start = 1 if digit_pos == 1 else 0
    cands = {str(i): str(folder / f"{digit_pos}_{i}.png")
             for i in range(start, 10) if (folder / f"{digit_pos}_{i}.png").exists()}
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.55, resized=True, focus_center=True)
    print(f"[Matcher] level_digit{digit_pos}: {lbl} ({score:.3f})")
    return lbl


def read_student_level(img: Image.Image, digit1_region: dict, digit2_region: dict) -> str:
    """
    학생 레벨 읽기.
    - digit2 결과가 'null' 또는 None → 1자리: digit1 값만 사용
    - 그 외 → digit1 + digit2 를 이어붙여 2자리
    """
    from core.capture import crop_ratio
    d1 = read_level_digit(crop_ratio(img, digit1_region), 1)
    d2 = read_level_digit(crop_ratio(img, digit2_region), 2)

    # digit2 == 'null' 또는 None → 1자리, digit1이 실제 값
    if not d2 or d2 == "null":
        if d1:
            print(f"[Matcher] student_level: 1자리 판정 → {d1}")
            return d1
        return "unknown"

    # 2자리
    if d1:
        return f"{d1}{d2}"

    # d1 없으면 d2만으로 fallback
    return d2


# ── 스킬 레벨 ─────────────────────────────────────────────
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
            chosen = "1" if scores["1"][2] >= scores["2"][2] else "2"
            best_lbl, (best_score, best_ui, best_text) = chosen, scores[chosen]

    print(f"[Matcher] {skill_key} -> {best_lbl} "
          f"(final={best_score:.3f}, ui={best_ui:.3f}, text={best_text:.3f})")
    return best_lbl if best_score >= 0.60 else "unknown"


# ── 장비 티어 ─────────────────────────────────────────────
def _score_equip_tier_tmpl(crop: Image.Image, tmpl_path: str) -> float:
    gray_s  = match_score_resized(crop, tmpl_path, focus_center=False)
    color_s = _color_hist_score(crop, tmpl_path)
    return 0.60 * gray_s + 0.40 * color_s


def read_equip_tier(crop: Image.Image, slot: int) -> str:
    d = TEMPLATE_DIR / f"equip{slot}"

    candidates: dict[str, str] = {}

    empty_p = d / f"equip{slot}_empty.png"
    if empty_p.exists():
        candidates["empty"] = str(empty_p)

    for p in d.glob(f"equip{slot}_T*.png"):
        tier = p.stem.replace(f"equip{slot}_", "")
        candidates[tier] = str(p)

    if not candidates:
        print(f"[Matcher] equip{slot}: 템플릿 없음 → unknown")
        return "unknown"

    scores: dict[str, float] = {
        lbl: _score_equip_tier_tmpl(crop, path)
        for lbl, path in candidates.items()
    }

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    print(
        f"[Matcher] equip{slot} tier scores: "
        + " ".join(f"{t}={s:.3f}" for t, s in ranked)
    )

    best_lbl, best_score = ranked[0]

    if best_score < THRESHOLD_LOOSE:
        print(f"[Matcher] equip{slot}: 최고점 {best_lbl}({best_score:.3f}) < {THRESHOLD_LOOSE} → unknown")
        return "unknown"

    return best_lbl


# ══════════════════════════════════════════════════════════
# V5 공식 인터페이스
# ══════════════════════════════════════════════════════════

def read_student_star_v5(crop: Image.Image) -> int | None:
    d = TEMPLATE_DIR / "star"
    cands = {str(i): str(d / f"star_{i}.png")
             for i in range(5, 0, -1) if (d / f"star_{i}.png").exists()}
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.65, resized=False, masked=True)
    print(f"[Matcher] student_star_v5 → {lbl} ({score:.3f})")
    return int(lbl) if lbl is not None else None


def read_weapon_star_v5(crop: Image.Image) -> int | None:
    d = TEMPLATE_DIR / "weapon_star"
    cands = {str(i): str(d / f"star_{i}.png")
             for i in range(4, 0, -1) if (d / f"star_{i}.png").exists()}
    if not cands:
        return None
    lbl, score = best_match(crop, cands, threshold=0.65, resized=False, masked=True)
    print(f"[Matcher] weapon_star_v5 → {lbl} ({score:.3f})")
    return int(lbl) if lbl is not None else None


def read_student_level_v5(img: Image.Image, digit1_region: dict, digit2_region: dict) -> int | None:
    raw = read_student_level(img, digit1_region, digit2_region)
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(f"[Matcher] read_student_level_v5: 변환 실패 (raw='{raw}') → None")
        return None