"""
core/ocr.py — BA Analyzer v6
EasyOCR 지연 로드 엔진

변경점 (v5 → v6):
  - 전처리 코드 제거 → core/preprocess.py 위임
  - _preprocess() 내부 PIL 변환 코드 제거
  - read_text() 가 preprocess_for_name_ocr / preprocess_for_digit_ocr 선택
  - 함수 내부에 cv2 / ImageEnhance / ImageFilter 직접 호출 없음
  - 각 read_* 함수가 어떤 전처리 경로를 쓰는지 독스트링에 명시
"""

from __future__ import annotations

import re
import gc
from PIL import Image
from typing import Optional

from core.preprocess import (
    preprocess_for_name_ocr,
    preprocess_for_digit_ocr,
)
from core.logger import get_logger, LOG_OCR

_log = get_logger(LOG_OCR)
_reader = None


# ══════════════════════════════════════════════════════════
# 엔진 로드 / 언로드
# ══════════════════════════════════════════════════════════

def load() -> None:
    global _reader
    if _reader is None:
        _log.info("모델 로딩 중...")
        import easyocr
        _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        _log.info("로딩 완료")


def unload() -> None:
    global _reader
    if _reader is not None:
        _reader = None
        gc.collect()
        _log.info("언로드 완료")


def is_loaded() -> bool:
    return _reader is not None


# ══════════════════════════════════════════════════════════
# 저수준 OCR 호출
# ══════════════════════════════════════════════════════════

def _run_ocr(arr) -> str:
    """
    numpy ndarray → easyocr → 결과 문자열.
    _reader 미로드 시 RuntimeError.
    """
    import numpy as np
    if _reader is None:
        raise RuntimeError("OCR 미로드 — load() 먼저 호출해야 해")
    results = _reader.readtext(arr, detail=0)
    return " ".join(results).strip()


def read_text(
    img: Image.Image,
    mode: str = "name",
) -> str:
    """
    OCR 기본 호출.

    Parameters
    ----------
    img  : PIL Image (이미 crop 된 ROI)
    mode : "name"  → preprocess_for_name_ocr  (이름/텍스트)
           "digit" → preprocess_for_digit_ocr (숫자/레벨)

    전처리 경로:
      name  → OCR_SCALE=2.0, Contrast=2.5, SHARPEN
      digit → OCR_SCALE=2.5, Contrast=3.0, SHARPEN
    """
    if mode == "digit":
        arr = preprocess_for_digit_ocr(img)
    else:
        arr = preprocess_for_name_ocr(img)
    return _run_ocr(arr)


# ══════════════════════════════════════════════════════════
# UI 잡문 제거 헬퍼
# ══════════════════════════════════════════════════════════

def _cleanup_common_ui_text(text: str) -> str:
    """
    이름/상세정보 OCR에서 자주 섞이는 UI 잡문 제거.
    """
    if not text:
        return ""

    # 괄호 통일
    for src, dst in [("（","("),("）",")"),("[","("),("](",")("),
                     ("【","("),("】",")")]:
        text = text.replace(src, dst)

    noise_keywords = [
        "레벨","최대","공격","방어","체력","스킬","무기",
        "인연","스트라이커","스페셜","프론트","미들","서포트",
        "학생","상세","정보","장비","프로필",
    ]
    for kw in noise_keywords:
        text = text.replace(kw, " ")

    text = text.replace("·"," ").replace("|"," ").replace(":"," ")
    text = re.sub(r"[^가-힣A-Za-z0-9\*\(\)\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ══════════════════════════════════════════════════════════
# 공개 read_* 함수
# ══════════════════════════════════════════════════════════

def read_item_name(img: Image.Image) -> str:
    """
    아이템/장비 이름 인식.
    전처리: preprocess_for_name_ocr (mode="name")
    """
    text = read_text(img, mode="name")
    for kw in ["보유 수량","보유수량","아이템","장비","카테고리","획득처"]:
        text = text.replace(kw, " ")
    return re.sub(r"\s+", " ", text).strip()


def read_item_count(img: Image.Image) -> str:
    """
    수량 인식 (x10, x19K, x1546 등).
    전처리: preprocess_for_digit_ocr (mode="digit")
    """
    text = read_text(img, mode="digit")

    m = re.search(r"[xX×]\s*(\d[\d,]*\.?\d*\s*[KkMm]?)", text)
    if m:
        raw = m.group(1).replace(",","").replace(" ","")
        if raw.upper().endswith("K"):
            return str(int(float(raw[:-1]) * 1_000))
        if raw.upper().endswith("M"):
            return str(int(float(raw[:-1]) * 1_000_000))
        return raw

    nums = re.findall(r"\d[\d,]*", text)
    if nums:
        return nums[0].replace(",","")
    return "0"


def read_student_name(img: Image.Image) -> str:
    """
    학생 이름+코스튬 태그 인식.
    전처리: preprocess_for_name_ocr (mode="name")
    """
    text = read_text(img, mode="name")
    text = _cleanup_common_ui_text(text)
    if not text:
        return ""
    # 괄호형이 있으면 최대한 보존
    if "(" in text and ")" in text:
        return text
    return text


def read_level(img: Image.Image) -> str:
    """
    레벨 숫자 인식 (Lv.90 → "90").
    전처리: preprocess_for_digit_ocr (mode="digit")
    """
    text = read_text(img, mode="digit")
    m = re.search(r"[Ll][Vv]\.?\s*(\d+)", text)
    if m:
        return m.group(1)
    nums = re.findall(r"\d+", text)
    return nums[0] if nums else "1"


def read_weapon_level(img: Image.Image) -> str:
    """
    무기 레벨 인식.
    전처리: preprocess_for_digit_ocr (mode="digit")
    """
    text = read_text(img, mode="digit")
    m = re.search(r"[Ll][Vv]\.?\s*(\d+)", text)
    if m:
        return m.group(1)
    nums = re.findall(r"\d+", text)
    return nums[0] if nums else "1"


# ══════════════════════════════════════════════════════════
# RecognitionResult 반환 버전 (메타정보 포함)
# ══════════════════════════════════════════════════════════

def _ocr_result(
    text: str,
    source_fn: str,
) -> "RecognitionResult":
    """
    OCR 결과 문자열 → RecognitionResult.
    easyocr 는 자체 confidence 를 반환하지 않으므로
    결과 존재 여부와 길이로 추정 신뢰도를 산출.
    """
    from core.matcher import RecognitionResult, RecogSource, _make_result

    if not text or text in ("0", "1", "unknown", ""):
        score = 0.3
    elif len(text) >= 2:
        score = 0.80   # 글자가 2자 이상이면 비교적 신뢰
    else:
        score = 0.60

    return _make_result(text, score, RecogSource.OCR)


def read_item_name_result(img: Image.Image) -> "RecognitionResult":
    """
    아이템 이름 인식 — RecognitionResult 반환.
    value=str, source=OCR, uncertain 플래그 포함.
    """
    text = read_item_name(img)
    return _ocr_result(text, "read_item_name")


def read_item_count_result(img: Image.Image) -> "RecognitionResult":
    """
    아이템 수량 인식 — RecognitionResult 반환.
    value=str (숫자 문자열), source=OCR.
    """
    text = read_item_count(img)
    return _ocr_result(text, "read_item_count")


def read_level_result(img: Image.Image) -> "RecognitionResult":
    """
    레벨 인식 — RecognitionResult 반환.
    """
    text = read_level(img)
    return _ocr_result(text, "read_level")