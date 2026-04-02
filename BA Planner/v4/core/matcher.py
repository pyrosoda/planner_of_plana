"""
core/matcher.py — OpenCV 템플릿 매칭 엔진
로비 감지 / 별 등급 / 스킬 레벨 / 장비 티어 / 무기 해방 / 학생 레벨 인식
"""

import cv2
import numpy as np
from pathlib import Path
from PIL import Image
from functools import lru_cache

from core.config import TEMPLATE_DIR, BASE_DIR


# ── 매칭 기준 ─────────────────────────────────────────────
THRESHOLD        = 0.80
THRESHOLD_LOOSE  = 0.72
THRESHOLD_LOBBY  = 0.75


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
    반환:
      - bgr: BGR 이미지
      - alpha_mask: 0~255 alpha mask 또는 None
      - gray: grayscale 이미지
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
    """
    원본 크기 기반 템플릿 매칭.
    RGBA 템플릿이면 alpha mask 사용.
    """
    bgr_t, alpha_mask, _ = _load_tmpl(tmpl_path)
    if bgr_t is None:
        return 0.0

    bgr_c = pil_to_bgr(crop)

    if bgr_t.shape[0] > bgr_c.shape[0] or bgr_t.shape[1] > bgr_c.shape[1]:
        return 0.0

    try:
        if alpha_mask is not None and alpha_mask.max() > 0:
            res = cv2.matchTemplate(
                bgr_c,
                bgr_t,
                cv2.TM_CCORR_NORMED,
                mask=alpha_mask
            )
        else:
            res = cv2.matchTemplate(
                bgr_c,
                bgr_t,
                cv2.TM_CCOEFF_NORMED
            )

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
    """
    crop과 template을 같은 크기로 정규화해서 비교.
    해상도 차이, client area 크기 차이, 비율 crop 오차에 더 강함.
    """

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
        x1 = int(w * 0.22)
        x2 = int(w * 0.78)
        y1 = int(h * 0.10)
        y2 = int(h * 0.92)

        if x2 > x1 and y2 > y1:
            crop_b = crop_b[y1:y2, x1:x2]
            tmpl_b = tmpl_b[y1:y2, x1:x2]

    try:
        res = cv2.matchTemplate(crop_b, tmpl_b, cv2.TM_CCOEFF_NORMED)
        _, ncc, _, _ = cv2.minMaxLoc(res)

        diff = np.mean(
            np.abs(crop_b.astype(np.float32) - tmpl_b.astype(np.float32))
        ) / 255.0
        diff_score = 1.0 - float(diff)

        score = 0.7 * float(ncc) + 0.3 * float(diff_score)
        return score
    except cv2.error:
        return 0.0


# ── 투명 PNG(alpha) 전용 리사이즈 매칭 ───────────────────
def match_score_resized_masked(
    crop: Image.Image,
    tmpl_path: str,
    focus_center: bool = False,
    binarize: bool = True
) -> float:
    """
    투명 PNG(alpha mask) 전용 리사이즈 매칭.
    템플릿의 투명한 부분은 비교에서 제외.
    별/무기별처럼 배경 영향 제거가 중요한 UI에 적합.
    """
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
        x1 = int(w * 0.18)
        x2 = int(w * 0.82)
        y1 = int(h * 0.08)
        y2 = int(h * 0.95)

        if x2 > x1 and y2 > y1:
            crop_proc = crop_proc[y1:y2, x1:x2]
            tmpl_proc = tmpl_proc[y1:y2, x1:x2]
            alpha_mask = alpha_mask[y1:y2, x1:x2]

    valid = alpha_mask > 0
    if not np.any(valid):
        return 0.0

    crop_f = crop_proc.astype(np.float32)
    tmpl_f = tmpl_proc.astype(np.float32)

    # masked difference
    diff = np.abs(crop_f - tmpl_f)
    masked_diff = diff[valid].mean() / 255.0
    diff_score = 1.0 - float(masked_diff)

    # masked correlation
    crop_v = crop_f[valid]
    tmpl_v = tmpl_f[valid]

    crop_v = crop_v - crop_v.mean()
    tmpl_v = tmpl_v - tmpl_v.mean()

    denom = (np.linalg.norm(crop_v) * np.linalg.norm(tmpl_v))
    if denom < 1e-6:
        corr_score = 0.0
    else:
        corr_score = float(np.dot(crop_v, tmpl_v) / denom)
        corr_score = max(0.0, min(1.0, (corr_score + 1.0) / 2.0))

    # edge 비교
    crop_edge = cv2.Canny(crop_proc, 50, 150)
    tmpl_edge = cv2.Canny(tmpl_proc, 50, 150)
    edge_diff = np.abs(crop_edge.astype(np.float32) - tmpl_edge.astype(np.float32))
    edge_score = 1.0 - float(edge_diff[valid].mean() / 255.0)

    score = 0.50 * corr_score + 0.30 * diff_score + 0.20 * edge_score
    return score


# ── 후보 비교 ─────────────────────────────────────────────
def best_match(
    crop: Image.Image,
    candidates: dict[str, str],
    threshold: float = THRESHOLD,
    resized: bool = False,
    focus_center: bool = False,
    masked: bool = False
) -> tuple[str | None, float]:
    """
    candidates = {label: path} → (best_label, score)
    """
    best_lbl, best_scr = None, threshold

    for lbl, path in candidates.items():
        if masked:
            s = match_score_resized_masked(
                crop,
                path,
                focus_center=focus_center
            )
        elif resized:
            s = match_score_resized(
                crop,
                path,
                focus_center=focus_center
            )
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


# ── 별 등급 ───────────────────────────────────────────────
def read_star(crop: Image.Image, folder: str, max_n: int) -> int:
    """
    folder:
      - star
      - weapon_star

    투명 PNG(alpha mask) 템플릿 우선 사용.
    파일명은 star_1.png 형태를 가정.
    """
    d = TEMPLATE_DIR / folder

    cands = {
        str(i): str(d / f"star_{i}.png")
        for i in range(max_n, 0, -1)
        if (d / f"star_{i}.png").exists()
    }

    lbl, score = best_match(
        crop,
        cands,
        threshold=0.68,
        resized=False,
        focus_center=False,
        masked=True
    )

    print(f"[Matcher] {folder} star -> {lbl} ({score:.3f})")
    return int(lbl) if lbl else 1


def read_student_star(crop: Image.Image) -> int:
    return read_star(crop, "star", 5)


def read_weapon_star(crop: Image.Image) -> int:
    return read_star(crop, "weapon_star", 4)


# ── 무기 해방 ─────────────────────────────────────────────
def read_weapon_unlocked(crop: Image.Image) -> bool:
    d = TEMPLATE_DIR / "weapon_unlocked_flag"

    s_on = match_score_resized(crop, str(d / "weapon_unlocked.png"))
    s_off = match_score_resized(crop, str(d / "weapon_locked.png"))

    print(f"[Matcher] weapon unlocked={s_on:.3f} locked={s_off:.3f}")
    return s_on > s_off


# ── 학생 레벨 digit 인식 ─────────────────────────────────
def read_level_digit(crop: Image.Image, digit_pos: int) -> str | None:
    """
    digit_pos:
      1 = 십의 자리
      2 = 일의 자리

    templates/studentlevel_digit1/1_1.png ...
    templates/studentlevel_digit2/2_0.png ...
    구조를 가정.
    """
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
        print(f"[Matcher] level digit candidates 없음: digit{digit_pos}")
        return None

    lbl, score = best_match(
        crop,
        cands,
        threshold=0.55,
        resized=True,
        focus_center=True
    )
    print(f"[Matcher] level_digit{digit_pos}: {lbl} (score={score:.3f})")
    return lbl


def read_student_level(
    img: Image.Image,
    digit1_region: dict,
    digit2_region: dict
) -> str:
    """
    scanner.py와 호환되는 기존 시그니처 유지.
    전체 학생 이미지 + 두 digit region을 받아 학생 레벨을 문자열로 반환.
    """
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
    """
    반환:
      - "locked"
      - "1" ~ "5" (EX)
      - "1" ~ "10" (일반 스킬)
      - 실패 시 "unknown"
    """
    d = TEMPLATE_DIR / skill_key
    max_lv = 5 if skill_key == "EX_Skill" else 10

    cands = {}

    locked = d / f"{skill_key}_locked.png"
    if locked.exists():
        cands["locked"] = str(locked)

    for i in range(max_lv, 0, -1):
        p = d / f"{skill_key}_{i}.png"
        if p.exists():
            cands[str(i)] = str(p)

    lbl, score = best_match(
        crop,
        cands,
        threshold=0.60,
        resized=True,
        focus_center=True
    )

    print(f"[Matcher] {skill_key} -> {lbl} ({score:.3f})")
    return lbl or "unknown"


# ── 장비 슬롯 티어 ────────────────────────────────────────
def read_equip_tier(crop: Image.Image, slot: int) -> str:
    """
    반환:
      null / locked / empty / T1 ~ T10+ / unknown
    """
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