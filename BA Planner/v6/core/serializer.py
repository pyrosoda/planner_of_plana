"""
core/serializer.py — BA Analyzer v6
StudentEntry 직렬화 / 역직렬화 계층

━━━ 목적 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  저장 파일을 보고 "왜 이 값이 비어 있는지 / 왜 이렇게 들어갔는지"
  를 즉시 알 수 있도록, 값과 메타정보를 함께 저장.

━━━ 저장 JSON 구조 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {
    "student_id":          "shiroko",
    "display_name":        "시로코",
    "scan_state":          "committed",       ← ScanState
    "confidence":          0.93,
    "level":               90,
    "level_status":        "ok",              ← FieldStatus
    "level_source":        "template",        ← FieldSource
    "student_star":        5,
    "student_star_status": "inferred",
    "student_star_source": "inferred",
    "student_star_note":   "weapon_state → 5★ 확정",
    "weapon_state":        "weapon_equipped",
    "weapon_state_status": "ok",
    "weapon_state_source": "template",
    "weapon_state_score":  0.881,
    "ex_skill":            5,
    "ex_skill_status":     "ok",
    "skill1":              null,
    "skill1_status":       "failed",
    "skill1_source":       "template",
    "skill1_note":         "raw='unknown'",
    "equip1":              "T7",
    "equip1_status":       "ok",
    "equip1_level":        null,
    "equip1_level_status": "region_missing",
    ...
    "_field_meta": { ... }   ← 전체 메타 백업 (복원용)
  }

━━━ None 의 의미 분류 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  값=None + status=failed         → 인식 시도했으나 실패
  값=None + status=skipped        → 조건 미충족으로 시도 안 함
  값=None + status=region_missing → region 정의 없어서 시도 불가
  값=None (status 없음)           → 구버전 데이터 (메타 없음)

━━━ 공개 인터페이스 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  serialize_student(entry)         → dict       (저장용)
  deserialize_student(d)           → StudentEntry (복원용)
  serialize_scan_result(result)    → dict       (전체 스캔 결과)
  deserialize_scan_result(d)       → ScanResult
  save_scan_json(result, path)     → None
  load_scan_json(path)             → ScanResult | None
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass


# ══════════════════════════════════════════════════════════
# 임포트 — 순환 방지를 위해 지연 임포트 사용
# ══════════════════════════════════════════════════════════

def _get_scanner_types():
    from core.scanner import (
        StudentEntry, ItemEntry, ScanResult,
        ScanState, FieldStatus, FieldSource, FieldMeta,
        WeaponState,
    )
    return StudentEntry, ItemEntry, ScanResult, ScanState, FieldStatus, FieldSource, FieldMeta, WeaponState


# ══════════════════════════════════════════════════════════
# StudentEntry 직렬화 / 역직렬화
# ══════════════════════════════════════════════════════════

def serialize_student(entry) -> dict:
    """
    StudentEntry → 저장용 dict.

    entry.to_dict() 를 호출하되, 추가 직렬화 가드를 붙임:
      - WeaponState → str 변환 확인
      - 직렬화 불가 타입 제거
    """
    d = entry.to_dict()

    # WeaponState enum 변환 가드 (to_dict 에서 이미 처리하지만 이중 확인)
    for k, v in list(d.items()):
        if hasattr(v, "value"):   # Enum 계열
            d[k] = v.value
        elif not _is_json_serializable(v):
            d[k] = str(v)

    return d


def deserialize_student(d: dict):
    """
    저장 dict → StudentEntry 복원.
    StudentEntry.from_dict() 위임.
    """
    StudentEntry, *_ = _get_scanner_types()
    return StudentEntry.from_dict(d)


# ══════════════════════════════════════════════════════════
# ItemEntry 직렬화
# ══════════════════════════════════════════════════════════

def serialize_item(entry) -> dict:
    data = {
        "item_id":  entry.item_id,
        "name":     entry.name,
        "quantity": entry.quantity,
        "source":   entry.source,
        "index":    entry.index,
    }
    scan_meta = getattr(entry, "scan_meta", None)
    if scan_meta:
        data["scan_meta"] = scan_meta
    return data


def deserialize_item(d: dict):
    _, ItemEntry, *_ = _get_scanner_types()
    return ItemEntry(
        name=d.get("name"),
        quantity=d.get("quantity"),
        item_id=d.get("item_id"),
        source=d.get("source", "item"),
        index=d.get("index", 0),
        scan_meta=dict(d.get("scan_meta") or {}),
    )


# ══════════════════════════════════════════════════════════
# ScanResult 직렬화
# ══════════════════════════════════════════════════════════

def serialize_scan_result(result, meta: Optional[dict] = None) -> dict:
    """
    ScanResult 전체 → 저장용 dict.

    Parameters
    ----------
    result : ScanResult
    meta   : build_scan_meta() 반환값 (scan_id, timestamp 등)
    """
    students_raw = [serialize_student(e) for e in result.students]
    items_raw    = [serialize_item(e)    for e in result.items]
    equip_raw    = [serialize_item(e)    for e in result.equipment]

    # 상태별 집계
    from core.scanner import ScanState
    state_counts: dict[str, int] = {}
    uncertain_list: list[str]    = []
    partial_list:   list[str]    = []

    for e in result.students:
        state_counts[e.scan_state] = state_counts.get(e.scan_state, 0) + 1
        if e.uncertain_fields():
            uncertain_list.append(e.student_id or "?")
        if e.is_partial():
            partial_list.append(e.student_id or "?")

    return {
        "meta":           meta or {},
        "scan_summary": {
            "student_count":  len(result.students),
            "item_count":     len(result.items),
            "equipment_count":len(result.equipment),
            "state_counts":   state_counts,
            "uncertain_ids":  uncertain_list,
            "partial_ids":    partial_list,
        },
        "resources": result.resources,
        "students":  students_raw,
        "items":     items_raw,
        "equipment": equip_raw,
        "errors":    result.errors,
    }


def deserialize_scan_result(d: dict):
    """저장 dict → ScanResult 복원."""
    _, _, ScanResult, *_ = _get_scanner_types()

    students  = [deserialize_student(s) for s in d.get("students", [])]
    items     = [deserialize_item(i)    for i in d.get("items",    [])]
    equipment = [deserialize_item(e)    for e in d.get("equipment",[])]

    result = ScanResult(
        students=students,
        items=items,
        equipment=equipment,
        resources=d.get("resources", {}),
        errors=d.get("errors", []),
    )
    return result


# ══════════════════════════════════════════════════════════
# 파일 I/O
# ══════════════════════════════════════════════════════════

def save_scan_json(
    result,
    path:  Path | str,
    meta:  Optional[dict] = None,
    *,
    indent: int = 2,
) -> None:
    """
    ScanResult 를 JSON 파일로 저장.
    _field_meta 포함으로 "왜 이 값인지" 파일만 보면 알 수 있음.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = serialize_scan_result(result, meta)
    data["_saved_at"] = datetime.now().isoformat()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent,
                  default=_json_default)


def load_scan_json(path: Path | str):
    """JSON 파일 → ScanResult 복원. 실패 시 None."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return deserialize_scan_result(d)
    except Exception as e:
        from core.logger import get_logger, LOG_APP
        get_logger(LOG_APP).error(f"scan JSON 로드 실패 ({path}): {e}")
        return None


# ══════════════════════════════════════════════════════════
# 상태 요약 리포트 (로그/UI용)
# ══════════════════════════════════════════════════════════

def make_status_report(result) -> list[str]:
    """
    ScanResult → 상태 요약 텍스트 리스트.
    FloatingOverlay.add_log() 에 그대로 전달 가능.

    예:
      "📊 스캔 완료: 총 83명"
      "  ✅ committed: 79명"
      "  ⚠️ partial:   3명 (shiroko, hina, aris)"
      "  ⏭ skipped:   1명"
      "  🔍 uncertain 필드 있는 학생: 5명"
    """
    from core.scanner import ScanState, FieldStatus

    total = len(result.students)
    if total == 0:
        return ["학생 데이터 없음"]

    state_count: dict[str, list[str]] = {}
    uncertain_students: list[str] = []

    for e in result.students:
        state_count.setdefault(e.scan_state, []).append(e.label())
        if e.uncertain_fields():
            uncertain_students.append(e.label())

    lines = [f"📊 스캔 완료: 총 {total}명"]

    icons = {
        ScanState.COMMITTED: "✅",
        ScanState.PARTIAL:   "⚠️",
        ScanState.SKIPPED:   "⏭",
        ScanState.FAILED:    "❌",
    }
    for state in [ScanState.COMMITTED, ScanState.PARTIAL,
                  ScanState.SKIPPED, ScanState.FAILED]:
        names = state_count.get(state, [])
        if not names:
            continue
        icon = icons.get(state, "•")
        detail = ""
        if state in (ScanState.PARTIAL, ScanState.FAILED) and len(names) <= 5:
            detail = f" ({', '.join(names)})"
        lines.append(f"  {icon} {state:10s}: {len(names)}명{detail}")

    if uncertain_students:
        sample = uncertain_students[:3]
        rest   = len(uncertain_students) - len(sample)
        suffix = f" +{rest}" if rest > 0 else ""
        lines.append(
            f"  🔍 uncertain 필드 있음: {len(uncertain_students)}명"
            f" ({', '.join(sample)}{suffix})"
        )

    return lines


# ══════════════════════════════════════════════════════════
# 내부 유틸
# ══════════════════════════════════════════════════════════

def _is_json_serializable(v) -> bool:
    return isinstance(v, (str, int, float, bool, list, dict, type(None)))


def _json_default(obj):
    """json.dump default 핸들러."""
    if hasattr(obj, "value"):   # Enum
        return obj.value
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return str(obj)
