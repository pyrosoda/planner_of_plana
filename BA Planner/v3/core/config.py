"""
core/config.py — 설정 저장·로드
"""
import json
from pathlib import Path

CONFIG_PATH = Path("config.json")


def save_config(data: dict):
    CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def config_exists() -> bool:
    return CONFIG_PATH.exists() and bool(load_config())
