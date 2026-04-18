from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image

from core.config import TEMPLATE_DIR

REGION_CAPTURE_DIR = TEMPLATE_DIR / "inventory_count"


@dataclass(frozen=True)
class CountTemplateEntry:
    value: str
    image: Image.Image


@dataclass(frozen=True)
class CountRegionSet:
    region_payload: dict
    templates: tuple[CountTemplateEntry, ...]


@dataclass(frozen=True)
class CountTemplatePack:
    x_regions: dict[int, CountRegionSet]
    digit_regions: dict[int, dict[int, CountRegionSet]]


@dataclass(frozen=True)
class CountMatchResult:
    value: Optional[str]
    digit_count: Optional[int]
    confidence: float
    method: str
    reason: str = ""


_PACK_CACHE: CountTemplatePack | None = None


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _digit_value_for_index(position: int, index: int) -> str | None:
    if 1 <= index <= 9:
        return str(index)
    if position > 1 and index == 10:
        return "0"
    return None


def _load_region_set(region_name: str, *, position: int | None = None) -> CountRegionSet | None:
    region_path = REGION_CAPTURE_DIR / f"{region_name}.region.json"
    region_payload = _load_json(region_path)
    if not region_payload:
        return None

    template_paths = sorted(REGION_CAPTURE_DIR.glob(f"{region_name}_*.png"))
    templates: list[CountTemplateEntry] = []
    for path in template_paths:
        match = re.search(r"_(\d{3})\.png$", path.name)
        if not match:
            continue
        index = int(match.group(1))
        if position is None:
            value = str(index)
        else:
            value = _digit_value_for_index(position, index)
            if value is None:
                continue
        try:
            img = Image.open(path).convert("L")
        except Exception:
            continue
        templates.append(CountTemplateEntry(value=value, image=img))

    if not templates:
        return None
    return CountRegionSet(region_payload=region_payload, templates=tuple(templates))


def _load_template_pack() -> CountTemplatePack:
    global _PACK_CACHE
    if _PACK_CACHE is not None:
        return _PACK_CACHE

    x_regions: dict[int, CountRegionSet] = {}
    digit_regions: dict[int, dict[int, CountRegionSet]] = {}

    for digit_count in range(1, 5):
        x_region = _load_region_set(f"x_digit{digit_count}")
        if x_region is not None:
            x_regions[digit_count] = x_region

        pos_map: dict[int, CountRegionSet] = {}
        for position in range(1, digit_count + 1):
            region_name = f"digit{digit_count}_{position}"
            if digit_count == 1 and position == 1:
                region_name = "digit1"
            region = _load_region_set(region_name, position=position)
            if region is not None:
                pos_map[position] = region
        if pos_map:
            digit_regions[digit_count] = pos_map

    _PACK_CACHE = CountTemplatePack(x_regions=x_regions, digit_regions=digit_regions)
    return _PACK_CACHE


def invalidate_cache() -> None:
    global _PACK_CACHE
    _PACK_CACHE = None


def has_count_templates() -> bool:
    pack = _load_template_pack()
    return bool(pack.x_regions and pack.digit_regions)


def _warp_region_from_payload(image: Image.Image, payload: dict) -> Image.Image | None:
    points_ratio = payload.get("points_ratio") or []
    if len(points_ratio) != 4:
        return None

    width, height = image.size
    points_client = [
        (float(point["x"]) * width, float(point["y"]) * height)
        for point in points_ratio
    ]
    top_left, top_right, bottom_right, bottom_left = points_client
    top_width = ((top_right[0] - top_left[0]) ** 2 + (top_right[1] - top_left[1]) ** 2) ** 0.5
    bottom_width = ((bottom_right[0] - bottom_left[0]) ** 2 + (bottom_right[1] - bottom_left[1]) ** 2) ** 0.5
    left_height = ((bottom_left[0] - top_left[0]) ** 2 + (bottom_left[1] - top_left[1]) ** 2) ** 0.5
    right_height = ((bottom_right[0] - top_right[0]) ** 2 + (bottom_right[1] - top_right[1]) ** 2) ** 0.5
    dst_w = max(1, int(round(max(top_width, bottom_width))))
    dst_h = max(1, int(round(max(left_height, right_height))))

    src = np.array(points_client, dtype=np.float32)
    dst = np.array(
        [(0.0, 0.0), (dst_w - 1.0, 0.0), (dst_w - 1.0, dst_h - 1.0), (0.0, dst_h - 1.0)],
        dtype=np.float32,
    )
    image_np = np.array(image.convert("RGB"))
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(image_np, matrix, (dst_w, dst_h))
    return Image.fromarray(warped).convert("L")


def _normalize_for_compare(img: Image.Image, size: tuple[int, int]) -> np.ndarray:
    arr = np.array(img.resize(size).convert("L"), dtype=np.uint8)
    _thr, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary.astype(np.float32)


def _similarity(a: Image.Image, b: Image.Image) -> float:
    target_size = b.size
    aa = _normalize_for_compare(a, target_size).reshape(-1)
    bb = _normalize_for_compare(b, target_size).reshape(-1)
    aa = aa - aa.mean()
    bb = bb - bb.mean()
    denom = float(np.linalg.norm(aa) * np.linalg.norm(bb))
    if denom <= 1e-6:
        return 0.0
    corr = float(np.dot(aa, bb) / denom)
    return max(0.0, min(1.0, (corr + 1.0) / 2.0))


def _match_region(image: Image.Image, region_set: CountRegionSet) -> tuple[str | None, float]:
    warped = _warp_region_from_payload(image, region_set.region_payload)
    if warped is None:
        return None, 0.0

    best_value: str | None = None
    best_score = 0.0
    for entry in region_set.templates:
        score = _similarity(warped, entry.image)
        if score > best_score:
            best_score = score
            best_value = entry.value
    return best_value, best_score


def read_item_count_from_detail(image: Image.Image) -> CountMatchResult:
    pack = _load_template_pack()
    if not pack.x_regions:
        return CountMatchResult(None, None, 0.0, "template", "no_x_templates")

    best_digit_count: int | None = None
    best_x_score = 0.0
    for digit_count, region_set in sorted(pack.x_regions.items()):
        _value, score = _match_region(image, region_set)
        if score > best_x_score:
            best_x_score = score
            best_digit_count = digit_count

    if best_digit_count is None:
        return CountMatchResult(None, None, 0.0, "template", "no_match")
    if best_x_score < 0.72:
        return CountMatchResult(None, best_digit_count, best_x_score, "template", "weak_x_match")

    pos_map = pack.digit_regions.get(best_digit_count) or {}
    if len(pos_map) < best_digit_count:
        return CountMatchResult(None, best_digit_count, best_x_score, "template", "missing_digit_templates")

    digits: list[str] = []
    scores: list[float] = [best_x_score]
    for position in range(1, best_digit_count + 1):
        value, score = _match_region(image, pos_map[position])
        if value is None:
            return CountMatchResult(None, best_digit_count, min(scores), "template", f"pos{position}_no_match")
        digits.append(value)
        scores.append(score)

    confidence = min(scores) if scores else best_x_score
    if confidence < 0.66:
        return CountMatchResult(None, best_digit_count, confidence, "template", "weak_digit_match")
    return CountMatchResult("".join(digits), best_digit_count, confidence, "template")
