"""
core/config.py — 설정 저장/로드 + 경로 관리
"""
import json
from pathlib import Path

BASE_DIR     = Path(__file__).parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
REGIONS_DIR  = BASE_DIR / "regions"
CONFIG_FILE  = BASE_DIR / "config.json"

# ── unwrap 헬퍼 ───────────────────────────────────────────
_REGION_COORD_KEYS = frozenset({"x1", "y1", "x2", "y2"})


def _is_region_dict(d: dict) -> bool:
    """값이 {x1,y1,x2,y2} 형태의 실제 region dict인지 확인."""
    return _REGION_COORD_KEYS.issubset(d.keys())


def _unwrap_student_json(raw: dict) -> dict:
    """
    JSON 최상위에 래핑 키가 있을 때만 한 단계 벗겨냄.

    예) { "student_data": { "next_button": {...}, "back_button": {...} } }
         → { "next_button": {...}, "back_button": {...} }

    unwrap 금지 조건:
      1. 키가 2개 이상 → 래핑 구조가 아님, 그대로 반환
      2. 키가 1개지만 value 자체가 region dict ({x1,y1,x2,y2})
         → { "some_region": {x1:.., y1:.., x2:.., y2:..} } 는 이미 flat
      3. value의 항목 중 dict가 아닌 것이 있을 때
    """
    if len(raw) != 1:
        return raw
    only_key = next(iter(raw))
    value = raw[only_key]
    if not isinstance(value, dict):
        return raw
    # value 자체가 region coord dict면 unwrap 금지
    if _is_region_dict(value):
        return raw
    # value의 모든 항목이 dict인 경우만 unwrap (region 모음 구조)
    if all(isinstance(v, dict) for v in value.values()):
        return value
    return raw


# ── region 파일 매핑 ──────────────────────────────────────
# regions/ 폴더 안의 JSON 파일명과
# 최종 regions dict에서 사용할 최상위 키 매핑
_REGION_FILES: dict[str, str] = {
    "lobby_regions.json":               "lobby",
    "menu_regions.json":                "menu",
    "item_regions.json":                "item",
    "equipment_regions.json":           "equipment",
    "student_menu_regions.json":        "student_menu",
}

# student 아래로 병합할 파일 목록 (순서대로 덮어쓰기)
_STUDENT_REGION_FILES: list[str] = [
    "student_data_regions.json",
    "student_normal_info_regions.json",
    "student_level_info_regions.json",
    "student_star_region.json",
    "student_equipment_regions.json",   # 장비 창 region (티어 + 레벨)
    "student_skillmenu_regions.json",   # 스킬 메뉴 region
    "student_statmenu_regions.json",    # 스탯 메뉴 region
    "student_weaponmenu_regions.json",  # 무기 메뉴 region
]


def load_regions() -> dict:
    """
    regions/*.json 을 읽어 하나의 dict 로 병합해서 반환.

    최종 구조:
      {
        "lobby":        { ... },
        "menu":         { ... },
        "item":         { ... },
        "equipment":    { ... },
        "student_menu": { ... },
        "student":      { ... },   ← student_* 파일들을 모두 병합
      }
    """
    result: dict = {}

    # 일반 파일 — 최상위 키 하나만 꺼내서 저장
    for filename, top_key in _REGION_FILES.items():
        path = REGIONS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"{filename} 없음: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if top_key in raw:
            result[top_key] = raw[top_key]
        else:
            result[top_key] = raw

    # student 병합 — 여러 파일의 내용을 하나의 "student" 키 아래로 합침
    student: dict = {}
    for filename in _STUDENT_REGION_FILES:
        path = REGIONS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"{filename} 없음: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        unwrapped = _unwrap_student_json(raw)
        student.update(unwrapped)

    result["student"] = student
    return result


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(data: dict):
    CONFIG_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )