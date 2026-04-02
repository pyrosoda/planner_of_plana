"""
core/config.py — 설정 저장/로드 + 경로 관리
"""
import json
from pathlib import Path

BASE_DIR     = Path(__file__).parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
REGIONS_FILE = BASE_DIR / "regions_v4.json"
CONFIG_FILE  = BASE_DIR / "config.json"


def load_regions() -> dict:
    if not REGIONS_FILE.exists():
        raise FileNotFoundError(f"regions_v4.json 없음: {REGIONS_FILE}")
    return json.loads(REGIONS_FILE.read_text(encoding="utf-8"))


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
