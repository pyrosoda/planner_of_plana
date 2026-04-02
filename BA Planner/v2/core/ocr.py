"""
core/ocr.py — EasyOCR 기반 텍스트 인식
숫자(수량), 한글(아이템명), 혼합 텍스트 처리
"""

import re
from PIL import Image, ImageFilter, ImageEnhance

# EasyOCR은 첫 import 시 모델 로딩이 느리므로 lazy init
_reader = None


def get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
        except ImportError:
            raise RuntimeError("easyocr 미설치: pip install easyocr")
    return _reader


def preprocess(img: Image.Image, scale: float = 2.0) -> Image.Image:
    """OCR 전처리: 업스케일 + 대비 강화"""
    w, h = img.size
    img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.5)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def read_text(img: Image.Image, preprocess_img: bool = True) -> str:
    """이미지에서 텍스트 추출 (전체)"""
    reader = get_reader()
    if preprocess_img:
        img = preprocess(img)
    import numpy as np
    arr = np.array(img)
    results = reader.readtext(arr, detail=0)
    return " ".join(results).strip()


def read_number(img: Image.Image) -> str | None:
    """수량 숫자 전용 인식 (x19K, x330, x1 등)"""
    text = read_text(img)
    # x로 시작하는 수량 패턴
    patterns = [
        r"[xX×]\s*(\d[\d,\.]*[KkMm]?)",  # x19K, x1,234
        r"(\d[\d,\.]*[KkMm]?)\s*[개수량]",  # 330개
        r"(\d[\d,\.]*[KkMm]?)",             # 순수 숫자
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            raw = m.group(1).replace(",", "")
            # K/M 단위 변환
            if raw.upper().endswith("K"):
                return str(int(float(raw[:-1]) * 1000))
            if raw.upper().endswith("M"):
                return str(int(float(raw[:-1]) * 1_000_000))
            return raw
    return None


def read_item_detail(img: Image.Image) -> dict:
    """
    아이템 상세 패널 인식
    반환: {"name": str, "quantity": str, "tier": str, "category": str}
    """
    text = read_text(img)
    result = {"name": None, "quantity": None, "tier": None, "category": None}

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        # 단일 라인인 경우
        lines = text.split("  ")

    # 수량 패턴
    qty_match = re.search(r"[xX×]\s*(\d[\d,]*[KkMm]?)", text)
    if qty_match:
        result["quantity"] = qty_match.group(1).replace(",", "")

    # 보유 수량 패턴
    own_match = re.search(r"보유\s*수량\s*[xX×]?\s*(\d[\d,]*)", text)
    if own_match:
        result["quantity"] = own_match.group(1).replace(",", "")

    # 티어 패턴
    tier_match = re.search(r"[Tt]ier\s*(\d+)|T(\d+)", text)
    if tier_match:
        t = tier_match.group(1) or tier_match.group(2)
        result["tier"] = f"T{t}"

    # 이름: 가장 긴 한글 토큰
    korean_chunks = re.findall(r"[가-힣\s]{2,}", text)
    if korean_chunks:
        name_candidate = max(korean_chunks, key=len).strip()
        # 불필요한 키워드 제거
        for kw in ["보유", "수량", "아이템", "장비", "카테고리"]:
            name_candidate = name_candidate.replace(kw, "").strip()
        if name_candidate:
            result["name"] = name_candidate

    return result


def read_resources(img: Image.Image) -> dict:
    """
    상단 재화 바 인식 (크레딧, 파이로사이트만)
    반환: {"크레딧": str, "청휘석": str}
    """
    text = read_text(img)
    result = {"크레딧": None, "청휘석": None}

    numbers = re.findall(r"\d[\d,]*", text)
    clean = [n.replace(",", "") for n in numbers]

    # AP(활동력) 패턴 제거 후 남은 숫자만 사용
    ap_match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if ap_match:
        clean = [n for n in clean if n not in [ap_match.group(1), ap_match.group(2)]]

    # 큰 순서로 크레딧, 파이로사이트 배정
    remaining = sorted(
        [int(n) for n in clean if n.isdigit()],
        reverse=True
    )
    if len(remaining) >= 1:
        result["크레딧"] = str(remaining[0])
    if len(remaining) >= 2:
        result["청휘석"] = str(remaining[1])

    return result


def read_student_info(img: Image.Image) -> dict:
    """
    학생 정보 영역 인식
    반환: {"name": str, "level": str, "stars": int}
    """
    text = read_text(img)
    result = {"name": None, "level": None, "stars": None}

    # 레벨
    lv_match = re.search(r"[Ll][Vv]\.?\s*(\d+)", text)
    if lv_match:
        result["level"] = lv_match.group(1)

    # 별 등급 (★ 카운트)
    star_count = text.count("★")
    if star_count > 0:
        result["stars"] = star_count

    # 이름
    korean = re.findall(r"[가-힣]{2,6}", text)
    if korean:
        # 레벨·수량 관련 단어 제외
        exclude = {"레벨", "최대", "공격", "방어", "체력", "스킬", "무기"}
        names = [k for k in korean if k not in exclude]
        if names:
            result["name"] = names[0]

    return result


def read_equipment_detail(img: Image.Image) -> dict:
    """
    장비 상세 패널 인식
    반환: {"name": str, "quantity": str, "tier": str}
    """
    # 장비도 아이템과 동일한 패널 구조
    return read_item_detail(img)


def read_student_basic(img: Image.Image) -> dict:
    """
    학생 기본 정보 영역 인식
    반환: {"name": str, "level": str, "stars": int, "bond": str}
    """
    text = read_text(img)
    result = {"name": None, "level": None, "stars": None, "bond": None}

    lv_match = re.search(r"[Ll][Vv]\.?\s*(\d+)", text)
    if lv_match:
        result["level"] = lv_match.group(1)

    bond_match = re.search(r"인연\s*(\d+)|bond\s*(\d+)", text, re.IGNORECASE)
    if bond_match:
        result["bond"] = bond_match.group(1) or bond_match.group(2)
    else:
        nums = re.findall(r"\b(\d{1,3})\b", text)
        candidates = [n for n in nums if n != result.get("level")]
        if candidates:
            result["bond"] = candidates[0]

    star_count = text.count("★")
    if star_count > 0:
        result["stars"] = star_count

    exclude = {"레벨", "최대", "공격", "방어", "체력", "스킬", "무기",
               "인연", "스트라이커", "스페셜", "STRIKER", "SPECIAL",
               "FRONT", "BACK", "MAX"}
    korean = re.findall(r"[가-힣]{2,6}", text)
    names = [k for k in korean if k not in exclude]
    if names:
        result["name"] = names[0]

    return result


def read_student_stats(img: Image.Image) -> dict:
    """
    학생 능력치/스킬/장비 패널 인식
    반환: {
        "hp": str, "atk": str, "def": str, "heal": str,
        "ex_skill": str, "basic_skill": str, "passive_skill": str, "sub_skill": str,
        "weapon_level": str,
        "equipment": [{"slot": int, "tier": str, "level": str}]
    }
    """
    text = read_text(img)
    result = {
        "hp": None, "atk": None, "def": None, "heal": None,
        "ex_skill": None, "basic_skill": None,
        "passive_skill": None, "sub_skill": None,
        "weapon_level": None,
        "equipment": []
    }

    stat_patterns = {
        "hp":   r"(?:최대\s*)?체력\s*([\d,]+)",
        "atk":  r"공격력\s*([\d,]+)",
        "def":  r"방어력\s*([\d,]+)",
        "heal": r"치유력\s*([\d,]+)",
    }
    for key, pat in stat_patterns.items():
        m = re.search(pat, text)
        if m:
            result[key] = m.group(1).replace(",", "")

    skill_matches = re.findall(r"(?:MAX|Lv\.?\s*\d+)", text, re.IGNORECASE)
    skill_keys = ["ex_skill", "basic_skill", "passive_skill", "sub_skill"]
    for i, sk in enumerate(skill_matches[:4]):
        result[skill_keys[i]] = sk.strip()

    weapon_match = re.search(r"(?:무기|weapon).*?[Ll][Vv]\.?\s*(\d+)", text, re.IGNORECASE)
    if weapon_match:
        result["weapon_level"] = weapon_match.group(1)

    equip_matches = re.findall(r"T(\d+).*?[Ll][Vv]\.?\s*(\d+)", text)
    for i, (tier, level) in enumerate(equip_matches[:4]):
        result["equipment"].append({
            "slot": i + 1,
            "tier": f"T{tier}",
            "level": level
        })

    return result