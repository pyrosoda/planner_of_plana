"""
core/ocr.py — EasyOCR 지연 로드 엔진
스캔 세션 시작 시 로드, 완료 시 언로드
"""

import re
import gc
from PIL import Image, ImageFilter, ImageEnhance

_reader = None


def load():
    global _reader
    if _reader is None:
        print("[OCR] 모델 로딩 중...")
        import easyocr
        _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        print("[OCR] 로딩 완료")


def unload():
    global _reader
    if _reader is not None:
        _reader = None
        gc.collect()
        print("[OCR] 언로드 완료")


def is_loaded() -> bool:
    return _reader is not None


def _preprocess(img: Image.Image, scale: float = 2.0) -> Image.Image:
    """
    OCR 전처리:
      - 2배 확대
      - grayscale
      - 대비 강화
      - sharpen
    """
    w, h = img.size
    img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.5)
    return img.filter(ImageFilter.SHARPEN)


def read_text(img: Image.Image, preproc: bool = True) -> str:
    """
    기본 OCR 호출.
    """
    if _reader is None:
        raise RuntimeError("OCR 미로드 — load() 먼저 호출해야 해")

    import numpy as np

    if preproc:
        img = _preprocess(img)

    arr = np.array(img)
    results = _reader.readtext(arr, detail=0)
    return " ".join(results).strip()


def _cleanup_common_ui_text(text: str) -> str:
    """
    이름/상세정보 OCR에서 자주 섞이는 UI 잡문 제거.
    """
    if not text:
        return ""

    # 괄호 통일
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("[", "(").replace("]", ")")
    text = text.replace("【", "(").replace("】", ")")

    # 자주 섞이는 UI 단어 제거
    noise_keywords = [
        "레벨", "최대", "공격", "방어", "체력", "스킬", "무기",
        "인연", "스트라이커", "스페셜", "프론트", "미들", "서포트",
        "학생", "상세", "정보", "장비", "프로필",
    ]
    for kw in noise_keywords:
        text = text.replace(kw, " ")

    # 의미 없는 기호 정리
    text = text.replace("·", " ")
    text = text.replace("|", " ")
    text = text.replace(":", " ")

    # 이름/태그에 필요할 수 있는 문자만 남김
    # - 한글
    # - 영문/숫자
    # - *, 공백, 괄호
    text = re.sub(r"[^가-힣A-Za-z0-9\*\(\)\s]", " ", text)

    # 공백 정리
    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_item_name(img: Image.Image) -> str:
    """아이템/장비 이름 인식"""
    text = read_text(img)

    for kw in ["보유 수량", "보유수량", "아이템", "장비", "카테고리", "획득처"]:
        text = text.replace(kw, " ")

    text = re.sub(r"\s+", " ", text).strip()
    return text


def read_item_count(img: Image.Image) -> str:
    """수량 인식 (x10, x19K, x1546 등)"""
    text = read_text(img)

    # x숫자K/M 패턴
    m = re.search(r"[xX×]\s*(\d[\d,]*\.?\d*\s*[KkMm]?)", text)
    if m:
        raw = m.group(1).replace(",", "").replace(" ", "")
        if raw.upper().endswith("K"):
            return str(int(float(raw[:-1]) * 1000))
        if raw.upper().endswith("M"):
            return str(int(float(raw[:-1]) * 1_000_000))
        return raw

    # 숫자만
    nums = re.findall(r"\d[\d,]*", text)
    if nums:
        return nums[0].replace(",", "")

    return "0"


def read_student_name(img: Image.Image) -> str:
    """
    학생 이름+코스튬 태그 인식.

    기존처럼 첫 번째 한글 덩어리만 잘라내지 않고,
    가능한 한 전체 문자열을 보존해서 student_names.py가
    이름/코스튬을 후처리로 분리할 수 있게 만든다.
    """
    text = read_text(img)
    text = _cleanup_common_ui_text(text)

    if not text:
        return ""

    # 괄호형이 있으면 최대한 보존
    # 예: "시즈코 (수영복)" -> "시즈코 (수영복)"
    if "(" in text and ")" in text:
        return text

    # 괄호는 없지만 "이름 태그" 구조일 수도 있으니 전체 유지
    # 예: "시즈코 수영복", "아코 드레스"
    return text


def read_level(img: Image.Image) -> str:
    """레벨 숫자 인식 (Lv.90 → 90)"""
    text = read_text(img)

    m = re.search(r"[Ll][Vv]\.?\s*(\d+)", text)
    if m:
        return m.group(1)

    nums = re.findall(r"\d+", text)
    return nums[0] if nums else "1"


def read_weapon_level(img: Image.Image) -> str:
    """무기 레벨 인식"""
    text = read_text(img)

    m = re.search(r"[Ll][Vv]\.?\s*(\d+)", text)
    if m:
        return m.group(1)

    nums = re.findall(r"\d+", text)
    return nums[0] if nums else "1"