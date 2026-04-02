"""
core/config.py  —  설정 저장·로드
core/capture.py —  윈도우 캡처
core/ocr.py     —  EasyOCR 기반 텍스트 인식
core/scanner.py —  아이템 그리드 스캔 + 자동 스크롤
"""

# ════════════════════════════════════════════════════════════
# config.py
# ════════════════════════════════════════════════════════════
import json
from pathlib import Path

CONFIG_PATH = Path("config.json")


def save_config(regions: dict):
    """RegionResult dict를 JSON으로 저장"""
    data = {k: v.to_dict() for k, v in regions.items()}
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_config() -> dict | None:
    """저장된 설정 로드. 없으면 None 반환"""
    if not CONFIG_PATH.exists():
        return None
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def config_exists() -> bool:
    return CONFIG_PATH.exists()
