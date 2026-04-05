"""
core/preprocess.py — BA Analyzer v6
인식 전처리 표준화 모듈

설계 원칙:
  - 모든 전처리 함수는 용도 이름으로 명확히 구분
  - 입력: PIL.Image  →  출력: np.ndarray (uint8, grayscale 또는 BGR)
  - threshold / resize 배율 / blur 커널 등을 전부 상수로 분리
  - matcher.py / ocr.py 내부에서 cv2.threshold / cv2.resize / cvtColor 를
    직접 호출하지 않고 여기 함수만 호출

공개 인터페이스 (용도별):
  ── 해상도 정규화 ─────────────────────────────────────────
  normalize_frame(frame)                → PIL.Image  (기준 해상도로 정규화)
  get_frame_scale(frame)                → (sx, sy)   (현재 → 기준 스케일 비율)
  scale_region(region, sx, sy)          → dict        (비율 좌표는 항상 1:1)

  ── OCR 전처리 ───────────────────────────────────────────
  preprocess_for_name_ocr(img)          → np.ndarray (gray)
  preprocess_for_digit_ocr(img)         → np.ndarray (gray)

  ── 템플릿 매칭 전처리 ───────────────────────────────────
  preprocess_for_template(img)          → np.ndarray (gray, 이진화)
  preprocess_for_masked_template(img)   → np.ndarray (gray, 이진화)
  preprocess_for_text_template(img)     → np.ndarray (gray, 텍스트 마스크)
  preprocess_for_color_hist(img)        → np.ndarray (BGR, 64×64)

  ── 저수준 유틸 ──────────────────────────────────────────
  to_gray(img)                          → np.ndarray (gray)
  to_bgr(img)                           → np.ndarray (BGR)
  normalize_hist(arr)                   → np.ndarray (gray)
  binarize(arr)                         → np.ndarray (binary)
  focus_center_crop(arr, alpha=None)    → (arr, alpha)  중앙 집중 crop
"""

from __future__ import annotations
import numpy as np
import cv2
from PIL import Image, ImageFilter, ImageEnhance
from typing import Optional


# ══════════════════════════════════════════════════════════
# 튜닝 상수 — 여기만 수정하면 전체에 반영됨
# ══════════════════════════════════════════════════════════

# ── 내부 기준 해상도 (QHD 기준 16:9) ────────────────────
#   템플릿은 이 해상도에서 촬영·저장한 것을 기준으로 함.
#   캡처 이미지는 normalize_frame() 에서 이 크기로 리사이즈.
#   ROI 는 비율 좌표(0.0~1.0) 이므로 별도 변환 불필요.
REF_WIDTH:  int = 2560
REF_HEIGHT: int = 1440

# 정규화 적용 최소 크기 — 이보다 작으면 업스케일 생략
_NORM_MIN_SIDE: int = 320

# ── OCR 전처리 ────────────────────────────────────────────
OCR_SCALE        = 2.0    # 업스케일 배율 (easyocr 인식률 향상)
OCR_CONTRAST     = 2.5    # PIL ImageEnhance.Contrast 강도
OCR_SHARPEN      = True   # SHARPEN 필터 적용 여부

# ── 이름 OCR 전용 ─────────────────────────────────────────
NAME_OCR_SCALE    = 2.0   # 이름은 기본 배율과 동일
NAME_OCR_CONTRAST = 2.5

# ── 숫자(digit) OCR 전용 ─────────────────────────────────
DIGIT_OCR_SCALE    = 2.5  # 숫자는 더 크게 확대 (작은 영역)
DIGIT_OCR_CONTRAST = 3.0  # 대비도 더 강하게

# ── 템플릿 매칭 전처리 ────────────────────────────────────
BLUR_KERNEL       = (3, 3)   # GaussianBlur 커널
BLUR_SIGMA        = 0        # sigma=0 → 커널 크기 자동

# ── focus_center_crop 비율 ────────────────────────────────
FOCUS_X1 = 0.18
FOCUS_X2 = 0.82
FOCUS_Y1 = 0.08
FOCUS_Y2 = 0.95

# ── 텍스트 마스크 정규화 크기 ─────────────────────────────
TEXT_MASK_W = 96
TEXT_MASK_H = 30

# ── 컬러 히스토그램 ──────────────────────────────────────
HIST_RESIZE  = 64    # 히스토그램 계산 전 리사이즈 크기
HIST_H_BINS  = 50    # Hue 빈 수
HIST_S_BINS  = 32    # Saturation 빈 수


# ══════════════════════════════════════════════════════════
# 해상도 정규화
# ══════════════════════════════════════════════════════════

def get_frame_scale(frame: Image.Image) -> tuple[float, float]:
    """
    현재 frame 크기 → 기준 해상도 스케일 비율 반환.

    Returns
    -------
    (scale_x, scale_y)
      - scale > 1.0 : frame 이 기준보다 작음 → 업스케일
      - scale < 1.0 : frame 이 기준보다 큼   → 다운스케일
      - scale = 1.0 : 기준 해상도와 동일
    """
    w, h = frame.size
    return REF_WIDTH / max(w, 1), REF_HEIGHT / max(h, 1)


def normalize_frame(
    frame:    Image.Image,
    *,
    verbose:  bool = False,
) -> Image.Image:
    """
    캡처 이미지를 내부 기준 해상도(REF_WIDTH × REF_HEIGHT)로 정규화.

    규칙:
      - 비율 유지 (letterbox 없음) — 16:9 비율이 맞지 않으면 가로 기준으로 높이 조정
      - 이미 기준 해상도이면 복사 없이 원본 반환
      - 너무 작은 이미지(_NORM_MIN_SIDE 미만)는 정규화 생략 후 경고

    Parameters
    ----------
    frame   : PrintWindow 결과 PIL Image
    verbose : True 이면 스케일 정보 로그 출력

    Returns
    -------
    정규화된 PIL Image (RGB)

    사용 예
    -------
    frame = capture_window_background()
    frame = normalize_frame(frame)          # ← 캡처 직후 1회만
    rf    = build_roi_frame(frame, table)   # 이후 crop 재사용
    """
    w, h = frame.size

    # 너무 작으면 정규화 생략
    if w < _NORM_MIN_SIDE or h < _NORM_MIN_SIDE:
        print(f"[Preprocess] ⚠️ 프레임이 너무 작음({w}×{h}) — 정규화 생략")
        return frame

    # 이미 기준 해상도
    if w == REF_WIDTH and h == REF_HEIGHT:
        return frame

    # 16:9 비율 기준으로 목표 크기 결정
    # 가로를 REF_WIDTH 로 맞추고 비율에 따라 높이 결정
    target_w = REF_WIDTH
    target_h = round(h * REF_WIDTH / max(w, 1))

    # 비율이 16:9 에서 크게 벗어나면 (예: 4:3) 높이 기준으로 재계산
    if abs(target_h - REF_HEIGHT) > REF_HEIGHT * 0.1:
        target_h = REF_HEIGHT
        target_w = round(w * REF_HEIGHT / max(h, 1))

    sx = target_w / max(w, 1)
    sy = target_h / max(h, 1)

    if verbose:
        print(
            f"[Preprocess] 해상도 정규화: {w}×{h} → {target_w}×{target_h} "
            f"(sx={sx:.3f} sy={sy:.3f})"
        )
    elif (w, h) != (target_w, target_h):
        # 해상도가 실제로 다를 때만 출력 (매 캡처마다 로그 방지)
        _log_once(f"[Preprocess] 해상도 정규화: {w}×{h} → {target_w}×{target_h}")

    if w == target_w and h == target_h:
        return frame

    return frame.resize((target_w, target_h), Image.LANCZOS)


def scale_region(
    region: dict,
    sx: float,
    sy: float,
) -> dict:
    """
    비율 좌표 region 에 스케일 적용.

    주의: 비율 좌표(0.0~1.0)는 해상도 무관하게 항상 유효하므로
    이 함수는 실제로 region 을 변경하지 않음.
    단, 절대 픽셀 좌표 region 을 쓰는 레거시 코드와의 인터페이스
    통일을 위해 제공.

    Returns
    -------
    region dict 그대로 반환 (비율 좌표는 스케일 불변)
    """
    # 비율 좌표는 스케일 무관 — 패스스루
    return region


# ── 중복 로그 억제 헬퍼 ───────────────────────────────────
_logged_messages: set[str] = set()

def _log_once(msg: str) -> None:
    """동일 메시지는 프로세스 생애 1회만 출력."""
    if msg not in _logged_messages:
        _logged_messages.add(msg)
        print(msg)


# ══════════════════════════════════════════════════════════
# 저수준 유틸
# ══════════════════════════════════════════════════════════

def to_gray(img: Image.Image) -> np.ndarray:
    """PIL Image → numpy grayscale (uint8)."""
    return np.array(img.convert("L"))


def to_bgr(img: Image.Image) -> np.ndarray:
    """PIL Image → numpy BGR (uint8)."""
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)


def normalize_hist(arr: np.ndarray) -> np.ndarray:
    """
    히스토그램 평활화 (equalizeHist).
    조명 차이·밝기 차이에 강건한 비교를 위해 사용.
    입력: grayscale ndarray
    """
    return cv2.equalizeHist(arr)


def binarize(arr: np.ndarray) -> np.ndarray:
    """
    Otsu 이진화.
    GaussianBlur → THRESH_BINARY + THRESH_OTSU 순서.
    입력: grayscale ndarray
    """
    blurred = cv2.GaussianBlur(arr, BLUR_KERNEL, BLUR_SIGMA)
    _, th = cv2.threshold(blurred, 0, 255,
                          cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th


def focus_center_crop(
    arr: np.ndarray,
    alpha: Optional[np.ndarray] = None,
) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """
    이미지 중앙부만 사용하는 crop.
    가장자리 노이즈(테두리 UI 등)를 제거해 매칭 안정성 향상.

    Returns
    -------
    (cropped_arr, cropped_alpha)  alpha 없으면 None
    """
    h, w = arr.shape[:2]
    x1 = int(w * FOCUS_X1)
    x2 = int(w * FOCUS_X2)
    y1 = int(h * FOCUS_Y1)
    y2 = int(h * FOCUS_Y2)
    if x2 <= x1 or y2 <= y1:
        return arr, alpha
    cropped = arr[y1:y2, x1:x2]
    cropped_alpha = alpha[y1:y2, x1:x2] if alpha is not None else None
    return cropped, cropped_alpha


def _resize_to(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    return cv2.resize(arr, (w, h), interpolation=cv2.INTER_AREA)


# ══════════════════════════════════════════════════════════
# OCR 전처리
# ══════════════════════════════════════════════════════════

def _pil_upscale_enhance(
    img: Image.Image,
    scale: float,
    contrast: float,
    sharpen: bool,
) -> np.ndarray:
    """
    공통 PIL 기반 OCR 전처리 파이프라인.
    PIL → resize → L → Contrast → (SHARPEN) → numpy gray
    """
    w, h = img.size
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(contrast)
    if sharpen:
        img = img.filter(ImageFilter.SHARPEN)
    return np.array(img)


def preprocess_for_name_ocr(img: Image.Image) -> np.ndarray:
    """
    학생 이름 / 아이템 이름 OCR 전처리.
    한글 이름은 중간 크기 글자가 많아 기본 배율 사용.

    반환: grayscale ndarray (easyocr 에 바로 전달 가능)
    """
    return _pil_upscale_enhance(
        img,
        scale=NAME_OCR_SCALE,
        contrast=NAME_OCR_CONTRAST,
        sharpen=OCR_SHARPEN,
    )


def preprocess_for_digit_ocr(img: Image.Image) -> np.ndarray:
    """
    숫자(레벨, 수량, 스킬 레벨 등) OCR 전처리.
    작은 영역의 숫자는 더 크게 확대 + 강한 대비 적용.

    반환: grayscale ndarray
    """
    return _pil_upscale_enhance(
        img,
        scale=DIGIT_OCR_SCALE,
        contrast=DIGIT_OCR_CONTRAST,
        sharpen=OCR_SHARPEN,
    )


# ══════════════════════════════════════════════════════════
# 템플릿 매칭 전처리
# ══════════════════════════════════════════════════════════

def preprocess_for_template(
    img: Image.Image,
    target_w: int,
    target_h: int,
    *,
    use_focus_crop: bool = False,
) -> np.ndarray:
    """
    일반 템플릿 매칭 전처리.
    PIL → gray → resize(target) → equalizeHist → binarize

    Parameters
    ----------
    img          : 비교 대상 이미지 (crop 된 ROI)
    target_w/h   : 템플릿 크기에 맞게 리사이즈할 목표 해상도
    use_focus_crop: True 이면 중앙부만 사용

    반환: binarized grayscale ndarray (target_w × target_h)
    """
    arr = to_gray(img)
    arr = _resize_to(arr, target_w, target_h)
    arr = normalize_hist(arr)
    arr = binarize(arr)
    if use_focus_crop:
        arr, _ = focus_center_crop(arr)
    return arr


def preprocess_for_masked_template(
    img: Image.Image,
    target_w: int,
    target_h: int,
    alpha_mask: Optional[np.ndarray] = None,
    *,
    use_focus_crop: bool = False,
    do_binarize: bool = True,
) -> tuple[np.ndarray, Optional[np.ndarray]]:
    """
    알파 마스크 기반 템플릿 매칭 전처리.
    PIL → gray → resize(target) → equalizeHist → (binarize) → (focus crop)

    Parameters
    ----------
    img        : 비교 대상 이미지
    target_w/h : 리사이즈 목표 크기
    alpha_mask : 템플릿의 알파 채널 (없으면 None → 전체 유효)
    do_binarize: False 이면 이진화 생략 (연속값 비교 시)

    반환: (processed_arr, resized_alpha_mask)
    """
    arr = to_gray(img)
    arr = _resize_to(arr, target_w, target_h)
    arr = normalize_hist(arr)

    # 알파 마스크 리사이즈
    if alpha_mask is not None:
        alpha_r = _resize_to(alpha_mask, target_w, target_h)
    else:
        alpha_r = np.full((target_h, target_w), 255, dtype=np.uint8)

    if do_binarize:
        arr = binarize(arr)

    if use_focus_crop:
        arr, alpha_r = focus_center_crop(arr, alpha_r)

    return arr, alpha_r


def preprocess_for_text_template(
    img: Image.Image,
    target_w: int,
    target_h: int,
) -> np.ndarray:
    """
    어두운 텍스트(숫자/문자) 기반 템플릿 매칭 전처리.
    배경을 날리고 텍스트 픽셀만 추출 → 정규화 크기(TEXT_MASK_W × TEXT_MASK_H) 로 리사이즈.

    파이프라인:
      PIL → gray → resize(target) → GaussianBlur → Otsu(inverse) →
      텍스트 bbox crop (패딩 2px) → resize(TEXT_MASK_W, TEXT_MASK_H)

    반환: text-only grayscale ndarray (TEXT_MASK_W × TEXT_MASK_H)
    """
    arr = to_gray(img)
    arr = _resize_to(arr, target_w, target_h)
    return _extract_text_mask(arr)


def _extract_text_mask(
    arr: np.ndarray,
    out_size: tuple[int, int] = (TEXT_MASK_W, TEXT_MASK_H),
    pad: int = 2,
) -> np.ndarray:
    """
    grayscale ndarray → 어두운 텍스트만 추출한 마스크.
    Otsu 역이진화 → 픽셀 bbox → crop → resize.
    """
    blurred = cv2.GaussianBlur(arr, BLUR_KERNEL, BLUR_SIGMA)
    _, th = cv2.threshold(blurred, 0, 255,
                          cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.where(th > 0)
    if len(xs) == 0:
        return np.zeros((out_size[1], out_size[0]), dtype=np.uint8)
    h_arr, w_arr = th.shape
    y1 = max(0,     ys.min() - pad)
    y2 = min(h_arr, ys.max() + pad + 1)
    x1 = max(0,     xs.min() - pad)
    x2 = min(w_arr, xs.max() + pad + 1)
    roi = th[y1:y2, x1:x2]
    if roi.size == 0:
        return np.zeros((out_size[1], out_size[0]), dtype=np.uint8)
    return cv2.resize(roi, out_size, interpolation=cv2.INTER_AREA)


def preprocess_for_color_hist(img: Image.Image) -> np.ndarray:
    """
    컬러 히스토그램 비교용 전처리.
    PIL → BGR → resize(HIST_RESIZE × HIST_RESIZE) → HSV 변환.

    반환: HSV ndarray (HIST_RESIZE × HIST_RESIZE × 3)
    """
    bgr = to_bgr(img)
    bgr = cv2.resize(bgr, (HIST_RESIZE, HIST_RESIZE), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)


def calc_color_hist(hsv: np.ndarray) -> np.ndarray:
    """
    HSV 배열 → 정규화된 H-S 2D 히스토그램.
    preprocess_for_color_hist() 결과를 받아 비교용 벡터 생성.
    """
    hist = cv2.calcHist(
        [hsv], [0, 1], None,
        [HIST_H_BINS, HIST_S_BINS],
        [0, 180, 0, 256],
    )
    cv2.normalize(hist, hist)
    return hist