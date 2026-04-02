"""
core/ocr.py — EasyOCR 기반 인식
"""
import re
from PIL import Image, ImageFilter, ImageEnhance

_reader = None


def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["ko", "en"], gpu=False, verbose=False)
    return _reader


def preprocess(img: Image.Image, scale: float = 2.0) -> Image.Image:
    w, h = img.size
    img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.5)
    return img.filter(ImageFilter.SHARPEN)


def read_text(img: Image.Image) -> str:
    import numpy as np
    arr = np.array(preprocess(img))
    results = get_reader().readtext(arr, detail=0)
    return " ".join(results).strip()


def read_number(img: Image.Image) -> str | None:
    text = read_text(img)
    m = re.search(r"(\d[\d,]*\.?\d*)\s*([KkMm]?)", text)
    if not m:
        return None
    val = m.group(1).replace(",", "")
    unit = m.group(2).upper()
    if unit == "K":
        return str(int(float(val) * 1000))
    if unit == "M":
        return str(int(float(val) * 1_000_000))
    return val


def read_resources(img: Image.Image) -> dict:
    """청휘석·크레딧 인식"""
    text = read_text(img)
    result = {"크레딧": None, "청휘석": None}
    # AP 패턴 제거
    text = re.sub(r"\d+\s*/\s*\d+", "", text)
    nums = sorted(
        [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text) if n.replace(",","").isdigit()],
        reverse=True
    )
    if len(nums) >= 1:
        result["크레딧"] = str(nums[0])
    if len(nums) >= 2:
        result["청휘석"] = str(nums[1])
    return result


def read_nickname_region(img: Image.Image) -> str:
    """좌측 상단 닉네임 영역 텍스트 추출"""
    return read_text(img).strip()


def read_item_detail(img: Image.Image) -> dict:
    text = read_text(img)
    result = {"name": None, "quantity": None, "tier": None}

    qty = re.search(r"보유\s*수량\s*[xX×]?\s*(\d[\d,]*)|[xX×]\s*(\d[\d,]*)", text)
    if qty:
        result["quantity"] = (qty.group(1) or qty.group(2) or "").replace(",", "")

    tier = re.search(r"[Tt](?:ier)?\s*(\d+)|T(\d+)", text)
    if tier:
        result["tier"] = f"T{tier.group(1) or tier.group(2)}"

    korean = re.findall(r"[가-힣]{2,}", text)
    exclude = {"보유", "수량", "아이템", "장비", "강화", "설계", "카테고리"}
    names = [k for k in korean if k not in exclude and len(k) >= 2]
    if names:
        result["name"] = max(names, key=len)

    return result
