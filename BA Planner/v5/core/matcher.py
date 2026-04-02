"""
core/matcher.py — OpenCV 템플릿 매칭 엔진  (V5)

V5 추가:
  - WeaponState   : 무기 상태 3-상태 enum (WeaponStatus 는 하위 호환 alias)
  - identify_student_by_texture() : 텍스처 매칭으로 학생 ID 확정
  - detect_weapon_status()        : 3상태 무기 판별
기존 함수 전부 유지 (로비/별/스킬/장비/레벨 등)

[수정] 템플릿 폴더/파일명을 실제 파일 구조에 맞게 수정:
  - student_texture  → students
  - weapon_detect_flag → weapon_state
  - no_weapon.png      → NO_WEAPON_SYSTEM.png
  - weapon_locked.png  → WEAPON_UNLOCKED_NOT_EQUIPPED.png
  - weapon_unlocked.png → WEAPON_EQUIPPED.png
"""

import cv2
import numpy as np
from enum import Enum, auto
from pathlib import Path
from PIL import Image
from functools import lru_cache

from core.config import TEMPLATE_DIR, BASE_DIR


# ── 매칭 기준 ─────────────────────────────────────────────
THRESHOLD        = 0.80
THRESHOLD_LOOSE  = 0.72
THRESHOLD_LOBBY  = 0.75

# 텍스처 식별 기준 — 충분히 낮게 잡고, 1위/2위 격차로 판단
TEXTURE_THRESHOLD        = 0.60
TEXTURE_MARGIN_REQUIRED  = 0.05   # 1위가 2위보다 이만큼 이상 높아야 확정

# ── 실제 템플릿 폴더/파일명 ───────────────────────────────
STUDENT_TEXTURE_DIR  = "students"          # templates/students/
WEAPON_STATE_DIR     = "weapon_state"      # templates/weapon_state/

WEAPON_STATE_FILES = {
    "no_weapon":       "NO_WEAPON_SYSTEM.png",
    "weapon_locked":   "WEAPON_UNLOCKED_NOT_EQUIPPED.png",
    "weapon_unlocked": "WEAPON_EQUIPPED.png",
}


# ── 무기 상태 enum ────────────────────────────────────────
class WeaponState(Enum):
    NO_WEAPON_SYSTEM             = "no_weapon_system"
    WEAPON_EQUIPPED              = "weapon_equipped"
    WEAPON_UNLOCKED_NOT_EQUIPPED = "weapon_unlocked_not_equipped"

# 하위 호환 alias — V4 코드가 WeaponStatus 를 import 해도 동작
WeaponStatus = WeaponState


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
    """
    템플릿 로드 (캐시).
    반환: bgr, alpha_mask, gray
    """
    p = Path(path)
    if not p.exists():
        return None, None, None

    img = Image.open(p)

    if img.mode == "RGBA":
        arr = np.array(img)
        rgb = arr[:, :, :3]
        alpha = arr[:, :, 3]
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return bgr, alpha, gray

    rgb = np.array(img.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return bgr, None, gray


# ── 기본 템플릿 매칭 ──────────────────────────────────────
def match_score(crop: Image.Image, tmpl_path: str) -> float:
    bgr_t, alpha_mask, _ = _load_tmpl(tmpl_path)
    if bgr_t is None:
        return 0.0

    bgr_c = pil_to_bgr(crop)

    if bgr_t.shape[0] > bgr_c.shape[0] or bgr_t.shape[1] > bgr_c.shape[1]:
        return 0.0

    try:
        if alpha_mask is not None and alpha_mask.max() > 0:
            res = cv2.matchTemplate(bgr_c, bgr_t, cv2.TM_CCORR_NORMED,
                                    mask=alpha_mask)
        else:
            res = cv2.matchTemplate(bgr_c, bgr_t, cv2.TM_CCOEFF_NORMED)

        _, val, _, _ = cv2.minMaxLoc(res)
        return float(val)
    except cv2.error:
        return 0.0


# ── 리사이즈 기반 매칭 ────────────────────────────────────
def match_score_resized(
    crop: Image.Image,
    tmpl_path: str,
    focus_center: bool = False
) -> float:
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
        diff = np.mean(np.abs(crop_b.astype(np.float32) -
                              tmpl_b.astype(np.float32))) / 255.0
        return 0.7 * float(ncc) + 0.3 * (1.0 - float(diff))
    except cv2.error:
        return 0.0


# ── 투명 PNG(alpha) 전용 리사이즈 매칭 ───────────────────
def match_score_resized_masked(
    crop: Image.Image,
    tmpl_path: str,
    focus_center: bool = False,
    binarize: bool = True
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
            crop_proc = crop_proc[y1:y2, x1:x2]
            tmpl_proc = tmpl_proc[y1:y2, x1:x2]
            alpha_mask = alpha_mask[y1:y2, x1:x2]

    valid = alpha_mask > 0
    if not np.any(valid):
        return 0.0

    crop_f = crop_proc.astype(np.float32)
    tmpl_f = tmpl_proc.astype(np.float32)

    diff = np.abs(crop_f - tmpl_f)
    masked_diff = diff[valid].mean() / 255.0
    diff_score = 1.0 - float(masked_diff)

    crop_v = crop_f[valid] - crop_f[valid].mean()
    tmpl_v = tmpl_f[valid] - tmpl_f[valid].mean()
    denom = np.linalg.norm(crop_v) * np.linalg.norm(tmpl_v)
    if denom < 1e-6:
        corr_score = 0.0
    else:
        corr_score = float(np.dot(crop_v, tmpl_v) / denom)
        corr_score = max(0.0, min(1.0, (corr_score + 1.0) / 2.0))

    crop_edge = cv2.Canny(crop_proc, 50, 150)
    tmpl_edge = cv2.Canny(tmpl_proc, 50, 150)
    edge_diff = np.abs(crop_edge.astype(np.float32) - tmpl_edge.astype(np.float32))
    edge_score = 1.0 - float(edge_diff[valid].mean() / 255.0)

    return 0.50 * corr_score + 0.30 * diff_score + 0.20 * edge_score


# ── 어두운 글자 전용 비교 ─────────────────────────────────
def _extract_dark_text_mask(arr: np.ndarray,
                             out_size: tuple[int, int] = (96, 30)) -> np.ndarray:
    arr = cv2.GaussianBlur(arr, (3, 3), 0)
    _, th = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.where(th > 0)
    if len(xs) == 0 or len(ys) == 0:
        return np.zeros((out_size[1], out_size[0]), dtype=np.uint8)
    pad = 2
    x1 = max(0, int(xs.min()) - pad)
    x2 = min(th.shape[1], int(xs.max()) + pad + 1)
    y1 = max(0, int(ys.min()) - pad)
    y2 = min(th.shape[0], int(ys.max()) + pad + 1)
    roi = th[y1:y2, x1:x2]
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
        diff = np.mean(np.abs(crop_t.astype(np.float32) -
                              tmpl_t.astype(np.float32))) / 255.0
        return 0.7 * float(ncc) + 0.3 * (1.0 - float(diff))
    except cv2.error:
        return 0.0


# ── 후보 비교 ─────────────────────────────────────────────
def best_match(
    crop: Image.Image,
    candidates: dict[str, str],
    threshold: float = THRESHOLD,
    resized: bool = False,
    focus_center: bool = False,
    masked: bool = False
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
    crop = crop_ratio(img, region)
    score = match_score(crop, _LOBBY_TMPL)
    print(f"[Matcher] 로비 점수: {score:.3f}")
    return score >= THRESHOLD_LOBBY


# ── 학생 텍스처 식별 ─────────────────────────────────────
def identify_student_by_texture(
    crop: Image.Image,
) -> tuple[str | None, float]:
    """
    crop : student_texture_region 을 잘라낸 이미지
    반환 : (student_id | None, best_score)
    """
    import core.student_names as _sn

    texture_dir = TEMPLATE_DIR / STUDENT_TEXTURE_DIR
    if not texture_dir.exists():
        print(f"[Matcher] {STUDENT_TEXTURE_DIR} 폴더 없음: {texture_dir}")
        return None, 0.0

    cands: dict[str, str] = {}
    for sid in _sn.all_ids():
        tmpl_file = texture_dir / _sn.template_path(sid)
        if tmpl_file.exists():
            cands[sid] = str(tmpl_file)

    if not cands:
        print(f"[Matcher] {STUDENT_TEXTURE_DIR} 템플릿 없음 (DB 등록 항목 기준)")
        return None, 0.0

    scores: list[tuple[str, float]] = []
    for sid, path in cands.items():
        s_gray  = match_score_resized(crop, path, focus_center=False)
        s_color = _color_hist_score(crop, path)
        combined = 0.55 * s_gray + 0.45 * s_color
        scores.append((sid, combined))

    scores.sort(key=lambda x: x[1], reverse=True)

    best_id,    best_s    = scores[0]
    second_s = scores[1][1] if len(scores) > 1 else 0.0

    margin = best_s - second_s
    print(
        f"[Matcher] texture 1위={best_id}({best_s:.3f}) "
        f"2위={scores[1][0] if len(scores)>1 else '-'}({second_s:.3f}) "
        f"margin={margin:.3f}"
    )

    if best_s < TEXTURE_THRESHOLD or margin < TEXTURE_MARGIN_REQUIRED:
        print(f"[Matcher] texture 식별 불확실 — OCR 폴백 필요")
        return None, best_s

    return best_id, best_s


def _color_hist_score(crop: Image.Image, tmpl_path: str) -> float:
    bgr_t, _, _ = _load_tmpl(tmpl_path)
    if bgr_t is None:
        return 0.0

    bgr_c = pil_to_bgr(crop)

    try:
        size = (64, 64)
        c_resized = cv2.resize(bgr_c, size)
        t_resized = cv2.resize(bgr_t, size)

        c_hsv = cv2.cvtColor(c_resized, cv2.COLOR_BGR2HSV)
        t_hsv = cv2.cvtColor(t_resized, cv2.COLOR_BGR2HSV)

        hist_c = cv2.calcHist([c_hsv], [0, 1], None, [50, 32],
                               [0, 180, 0, 256])
        hist_t = cv2.calcHist([t_hsv], [0, 1], None, [50, 32],
                               [0, 180, 0, 256])

        cv2.normalize(hist_c, hist_c)
        cv2.normalize(hist_t, hist_t)

        score = cv2.compareHist(hist_c, hist_t, cv2.HISTCMP_CORREL)
        return max(0.0, float(score))
    except cv2.error:
        return 0.0


# ── 무기 상태 3-상태 판별 ────────────────────────────────
def detect_weapon_status(
    crop: Image.Image,
    stars: int
) -> WeaponStatus:
    if stars < 5:
        return WeaponStatus.NO_WEAPON_SYSTEM

    d = TEMPLATE_DIR / WEAPON_STATE_DIR

    scores: dict[str, float] = {}
    mapping = {
        "no_weapon":       WeaponState.NO_WEAPON_SYSTEM,
        "weapon_locked":   WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED,
        "weapon_unlocked": WeaponState.WEAPON_EQUIPPED,
    }

    for key in mapping:
        p = d / WEAPON_STATE_FILES[key]
        if p.exists():
            scores[key] = match_score_resized(crop, str(p))
        else:
            print(f"[Matcher] weapon_state 템플릿 없음: {p.name}")
            scores[key] = 0.0

    best_key = max(scores, key=lambda k: scores[k])
    best_val = scores[best_key]

    print(
        f"[Matcher] weapon_status scores: "
        f"{ {k: f'{v:.3f}' for k, v in scores.items()} } → {best_key}"
    )

    if best_val < 0.55:
        fallback = (WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED
                    if stars >= 5 else WeaponState.NO_WEAPON_SYSTEM)
        print(f"[Matcher] weapon_status 불확실 → 폴백: {fallback.name}")
        return fallback

    return mapping[best_key]


# ── 별 등급 ───────────────────────────────────────────────
def read_star(crop: Image.Image, folder: str, max_n: int) -> int:
    d = TEMPLATE_DIR / folder
    cands = {
        str(i): str(d / f"star_{i}.png")
        for i in range(max_n, 0, -1)
        if (d / f"star_{i}.png").exists()
    }
    lbl, score = best_match(
        crop, cands, threshold=0.68,
        resized=False, focus_center=False, masked=True
    )
    print(f"[Matcher] {folder} star -> {lbl} ({score:.3f})")
    return int(lbl) if lbl else 1


def read_student_star(crop: Image.Image) -> int:
    return read_star(crop, "star", 5)


def read_weapon_star(crop: Image.Image) -> int:
    return read_star(crop, "weapon_star", 4)


# ── 무기 해방 bool (하위 호환) ────────────────────────────
def read_weapon_unlocked(crop: Image.Image) -> bool:
    status = detect_weapon_status(crop, stars=5)
    return status == WeaponState.WEAPON_EQUIPPED


# ── 학생 레벨 digit 인식 ─────────────────────────────────
def read_level_digit(crop: Image.Image, digit_pos: int) -> str | None:
    folder = TEMPLATE_DIR / f"studentlevel_digit{digit_pos}"
    if not folder.exists():
        print(f"[Matcher] level digit folder 없음: {folder}")
        return None

    start = 1 if digit_pos == 1 else 0
    cands = {}
    for i in range(start, 10):
        p = folder / f"{digit_pos}_{i}.png"
        if p.exists():
            cands[str(i)] = str(p)

    if not cands:
        return None

    lbl, score = best_match(
        crop, cands, threshold=0.55, resized=True, focus_center=True
    )
    print(f"[Matcher] level_digit{digit_pos}: {lbl} (score={score:.3f})")
    return lbl


def read_student_level(
    img: Image.Image,
    digit1_region: dict,
    digit2_region: dict
) -> str:
    from core.capture import crop_ratio
    crop1 = crop_ratio(img, digit1_region)
    crop2 = crop_ratio(img, digit2_region)
    d1 = read_level_digit(crop1, 1)
    d2 = read_level_digit(crop2, 2)
    if d1 and d2:
        return f"{d1}{d2}"
    if d2:
        return d2
    return "unknown"


# ── 스킬 레벨 ─────────────────────────────────────────────
def read_skill(crop: Image.Image, skill_key: str) -> str:
    d = TEMPLATE_DIR / skill_key
    max_lv = 5 if skill_key == "EX_Skill" else 10

    cands: dict[str, str] = {}
    locked = d / f"{skill_key}_locked.png"
    if locked.exists():
        cands["locked"] = str(locked)

    for i in range(max_lv, 0, -1):
        p = d / f"{skill_key}_{i}.png"
        if p.exists():
            cands[str(i)] = str(p)

    if not cands:
        return "unknown"

    scores: dict[str, tuple[float, float, float]] = {}
    for lbl, path in cands.items():
        ui_score   = match_score_resized(crop, path, focus_center=True)
        text_score = match_score_textonly(crop, path) if lbl != "locked" else 0.0
        final = ui_score if lbl == "locked" else (0.55 * ui_score + 0.45 * text_score)
        scores[lbl] = (final, ui_score, text_score)

    ranked = sorted(scores.items(), key=lambda x: x[1][0], reverse=True)
    best_lbl, (best_score, best_ui, best_text) = ranked[0]

    if len(ranked) >= 2:
        second_lbl, (second_score, _, _) = ranked[1]
        if {best_lbl, second_lbl} == {"1", "2"} and abs(best_score - second_score) <= 0.035:
            chosen = "1" if scores["1"][2] >= scores["2"][2] else "2"
            best_lbl, (best_score, best_ui, best_text) = chosen, scores[chosen]

    print(
        f"[Matcher] {skill_key} -> {best_lbl} "
        f"(final={best_score:.3f}, ui={best_ui:.3f}, text={best_text:.3f})"
    )
    return best_lbl if best_score >= 0.60 else "unknown"


# ── 장비 슬롯 티어 ────────────────────────────────────────
def read_equip_tier(crop: Image.Image, slot: int) -> str:
    d = TEMPLATE_DIR / f"equip{slot}"

    if slot == 4:
        null_p = d / "equip4_null.png"
        if null_p.exists() and match_score(crop, str(null_p)) >= THRESHOLD_LOOSE:
            return "null"

    if slot in (2, 3, 4):
        locked_p = d / f"equip{slot}_locked.png"
        if locked_p.exists() and match_score(crop, str(locked_p)) >= THRESHOLD_LOOSE:
            return "locked"

    empty_p = d / f"equip{slot}_empty.png"
    if empty_p.exists() and match_score(crop, str(empty_p)) >= THRESHOLD_LOOSE:
        return "empty"

    large, normal = [], []
    for p in d.glob(f"equip{slot}_T*.png"):
        tier = p.stem.replace(f"equip{slot}_", "")
        w = Image.open(p).width
        (large if w > 40 else normal).append((tier, str(p), w))

    large.sort(key=lambda x: x[2], reverse=True)
    for tier, path, _ in large:
        if match_score(crop, path) >= THRESHOLD_LOOSE:
            return tier

    normal.sort(
        key=lambda x: int(x[0][1:]) if x[0][1:].isdigit() else 0,
        reverse=True
    )
    if normal:
        scored = [(tier, match_score(crop, path)) for tier, path, _ in normal]
        best_tier, best_score = max(scored, key=lambda x: x[1])
        print(f"[Matcher] equip{slot} tier scores: "
              f"{ {t: f'{s:.3f}' for t, s in scored} }")
        if best_score >= THRESHOLD_LOOSE:
            return best_tier

    if slot == 4:
        return "T1"
    if slot in (2, 3):
        return "locked"
    return "unknown"


# ══════════════════════════════════════════════════════════
# V5 공식 인터페이스
# ══════════════════════════════════════════════════════════

def match_student_texture(crop: Image.Image) -> tuple[str | None, float]:
    """
    student_names.STUDENTS DB 기준 템플릿 전체 비교.
    templates/students/ 폴더 사용.
    """
    import core.student_names as _sn

    texture_dir = TEMPLATE_DIR / STUDENT_TEXTURE_DIR
    if not texture_dir.exists():
        print(f"[Matcher] {STUDENT_TEXTURE_DIR} 폴더 없음: {texture_dir}")
        return None, 0.0

    cands: dict[str, str] = {}
    for sid in _sn.all_ids():
        tmpl_file = texture_dir / _sn.template_path(sid)
        if tmpl_file.exists():
            cands[sid] = str(tmpl_file)

    if not cands:
        print(f"[Matcher] match_student_texture: {STUDENT_TEXTURE_DIR} 에 템플릿 없음")
        return None, 0.0

    scores: list[tuple[str, float]] = []
    for sid, path in cands.items():
        s_gray  = match_score_resized(crop, path, focus_center=False)
        s_color = _color_hist_score(crop, path)
        scores.append((sid, 0.55 * s_gray + 0.45 * s_color))

    scores.sort(key=lambda x: x[1], reverse=True)
    best_id, best_s = scores[0]
    second_s = scores[1][1] if len(scores) > 1 else 0.0
    margin   = best_s - second_s

    print(
        f"[Matcher] texture 1위={best_id}({best_s:.3f}) "
        f"2위={scores[1][0] if len(scores)>1 else '-'}({second_s:.3f}) "
        f"margin={margin:.3f}"
    )

    if best_s < TEXTURE_THRESHOLD or margin < TEXTURE_MARGIN_REQUIRED:
        return None, best_s

    return best_id, best_s


def detect_weapon_state(crop: Image.Image) -> tuple[WeaponState, float]:
    """
    weapon_detect_flag_region crop 으로 3상태 판별.
    templates/weapon_state/ 폴더 사용.
    파일명: NO_WEAPON_SYSTEM.png / WEAPON_UNLOCKED_NOT_EQUIPPED.png / WEAPON_EQUIPPED.png
    """
    d = TEMPLATE_DIR / WEAPON_STATE_DIR

    mapping: dict[str, WeaponState] = {
        "no_weapon":       WeaponState.NO_WEAPON_SYSTEM,
        "weapon_locked":   WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED,
        "weapon_unlocked": WeaponState.WEAPON_EQUIPPED,
    }

    scores: dict[str, float] = {}
    for key in mapping:
        p = d / WEAPON_STATE_FILES[key]
        scores[key] = match_score_resized(crop, str(p)) if p.exists() else 0.0

    if not any(v > 0 for v in scores.values()):
        print(f"[Matcher] detect_weapon_state: {WEAPON_STATE_DIR} 템플릿 전무 → WEAPON_UNLOCKED_NOT_EQUIPPED")
        return WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED, 0.0

    best_key = max(scores, key=lambda k: scores[k])
    best_val = scores[best_key]

    print(
        f"[Matcher] weapon_state scores: "
        f"{ {k: f'{v:.3f}' for k, v in scores.items()} } → {best_key}({best_val:.3f})"
    )

    if best_val < 0.55:
        print(f"[Matcher] weapon_state 불확실(score={best_val:.3f}) → WEAPON_UNLOCKED_NOT_EQUIPPED")
        return WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED, best_val

    return mapping[best_key], best_val


def read_student_star_v5(crop: Image.Image) -> int | None:
    d = TEMPLATE_DIR / "star"
    cands = {
        str(i): str(d / f"star_{i}.png")
        for i in range(5, 0, -1)
        if (d / f"star_{i}.png").exists()
    }
    if not cands:
        print("[Matcher] read_student_star_v5: 템플릿 없음 → None")
        return None

    lbl, score = best_match(
        crop, cands,
        threshold=0.65,
        resized=False,
        focus_center=False,
        masked=True,
    )
    print(f"[Matcher] student_star_v5 → {lbl} (score={score:.3f})")
    return int(lbl) if lbl is not None else None


def read_weapon_star_v5(crop: Image.Image) -> int | None:
    d = TEMPLATE_DIR / "weapon_star"
    cands = {
        str(i): str(d / f"star_{i}.png")
        for i in range(4, 0, -1)
        if (d / f"star_{i}.png").exists()
    }
    if not cands:
        print("[Matcher] read_weapon_star_v5: 템플릿 없음 → None")
        return None

    lbl, score = best_match(
        crop, cands,
        threshold=0.65,
        resized=False,
        focus_center=False,
        masked=True,
    )
    print(f"[Matcher] weapon_star_v5 → {lbl} (score={score:.3f})")
    return int(lbl) if lbl is not None else None


def read_student_level_v5(
    img: Image.Image,
    digit1_region: dict,
    digit2_region: dict,
) -> int | None:
    raw = read_student_level(img, digit1_region, digit2_region)
    try:
        return int(raw)
    except (TypeError, ValueError):
        print(f"[Matcher] read_student_level_v5: 변환 실패 (raw='{raw}') → None")
        return None