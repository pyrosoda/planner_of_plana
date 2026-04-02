"""
core/config.py — 설정 저장/로드 + 경로 관리
"""
import json
from pathlib import Path

BASE_DIR     = Path(__file__).parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
REGIONS_DIR  = BASE_DIR / "regions"
CONFIG_FILE  = BASE_DIR / "config.json"

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

    scanner.py 가 기대하는 self.r["student"] 키가 여기서 만들어짐.
    """
    result: dict = {}

    # 일반 파일 — 최상위 키 하나만 꺼내서 저장
    for filename, top_key in _REGION_FILES.items():
        path = REGIONS_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"{filename} 없음: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        # JSON 최상위가 { "lobby": {...} } 형태일 수도 있고
        # 바로 { "menu_button": {...} } 형태일 수도 있음 → 자동 감지
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

        # JSON 최상위에 래핑 키가 있으면 벗겨냄
        # 예: { "student_data": { "next_student_button": ... } }
        #  → { "next_student_button": ... } 만 병합
        unwrapped = raw
        if len(raw) == 1:
            only_key = next(iter(raw))
            if isinstance(raw[only_key], dict):
                unwrapped = raw[only_key]

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