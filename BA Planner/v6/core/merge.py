"""
core/merge.py — 스캔 결과 병합 + diff 계산

병합 규칙
─────────────────────────────────────────────────
기본
  · 새 값이 None          → 기존 값 유지
  · 새 값이 유효          → 갱신

필드별 엄격 규칙
  · level                 → max(old, new)
  · student_star          → max(old, new)
  · weapon_level          → max(old, new)
  · equip1~4              → new == "unknown"  이면 기존 유지
  · equip1~3_level        → max(old, new),  단 None이면 기존 유지
  · stat_hp/atk/heal      → 0 ≤ new ≤ 25 일 때만 갱신
  · weapon_state          → no_weapon_system ↔ weapon_equipped 충돌 시
                             로그 + 기존 값 보존 (보수적)

외부에서 사용하는 공개 함수
  · merge_student_entry(old, new)     → merged dict
  · merge_inventory_snapshot(old, new)→ merged dict
  · compute_student_diff(old, new)    → list[FieldDiff]
  · compute_inventory_diff(old, new)  → list[FieldDiff]
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

# ── 상수 ──────────────────────────────────────────────────
_TAKE_MAX_INT   = {"level", "student_star", "weapon_level",
                   "equip1_level", "equip2_level", "equip3_level"}
_EQUIP_TIER     = {"equip1", "equip2", "equip3", "equip4"}
_STAT_FIELDS    = {"stat_hp", "stat_atk", "stat_heal"}
_STAT_MIN, _STAT_MAX = 0, 25

# weapon_state 값 상수
_WS_NO_WEAPON  = "no_weapon_system"
_WS_EQUIPPED   = "weapon_equipped"
_WS_UNLOCKED   = "weapon_unlocked_not_equipped"

# ── FieldDiff ─────────────────────────────────────────────
@dataclass
class FieldDiff:
    field:     str
    old_value: Any
    new_value: Any

    def to_dict(self) -> dict:
        return {
            "field":     self.field,
            "old":       self.old_value,
            "new":       self.new_value,
        }


# ── 내부 헬퍼 ─────────────────────────────────────────────
def _str(v: Any) -> str | None:
    """None은 그대로, 나머지는 str로 정규화."""
    return None if v is None else str(v)


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _merge_weapon_state(old_v: str | None, new_v: str | None) -> str | None:
    """
    weapon_state 전용 병합.
    no_weapon_system ↔ weapon_equipped 충돌이면 로그 + old 보존.
    """
    if new_v is None:
        return old_v

    conflict = (
        {old_v, new_v} == {_WS_NO_WEAPON, _WS_EQUIPPED}
    )
    if conflict:
        print(
            f"[Merge] ⚠️  weapon_state 충돌: "
            f"기존={old_v!r} vs 신규={new_v!r} → 기존 유지"
        )
        return old_v

    return new_v


def _merge_field(field: str, old_v: Any, new_v: Any) -> Any:
    """
    단일 필드 병합 규칙 적용.
    반환값은 항상 str | int | None (dict 저장 호환).
    """
    # ── weapon_state 전용 ──────────────────────────────────
    if field == "weapon_state":
        return _merge_weapon_state(_str(old_v), _str(new_v))

    # ── 기본: 새 값이 None이면 기존 유지 ─────────────────
    if new_v is None:
        return old_v

    # ── stat 범위 검증 ────────────────────────────────────
    if field in _STAT_FIELDS:
        n = _int_or_none(new_v)
        if n is None or not (_STAT_MIN <= n <= _STAT_MAX):
            print(
                f"[Merge] stat 범위 오류: {field}={new_v!r} "
                f"(허용 {_STAT_MIN}~{_STAT_MAX}) → 기존 유지"
            )
            return old_v
        return n

    # ── equip 티어: unknown 무시 ──────────────────────────
    if field in _EQUIP_TIER:
        if _str(new_v) == "unknown":
            return old_v
        return _str(new_v)

    # ── max 채택 (int 필드) ───────────────────────────────
    if field in _TAKE_MAX_INT:
        o = _int_or_none(old_v)
        n = _int_or_none(new_v)
        if o is None and n is None:
            return None
        if o is None:
            return n
        if n is None:
            return o
        result = max(o, n)
        if result != n:
            print(
                f"[Merge] max 규칙: {field} "
                f"기존={o} > 신규={n} → {result} 유지"
            )
        return result

    # ── 기본 갱신 ─────────────────────────────────────────
    return new_v


# ── 학생 병합 ─────────────────────────────────────────────
# 병합 대상 전체 필드 (meta 제외)
_STUDENT_MERGE_FIELDS: tuple[str, ...] = (
    "display_name",
    "level",
    "student_star",
    "weapon_state",
    "weapon_star",
    "weapon_level",
    "ex_skill",
    "skill1",
    "skill2",
    "skill3",
    "equip1",
    "equip2",
    "equip3",
    "equip4",
    "equip1_level",
    "equip2_level",
    "equip3_level",
    "stat_hp",
    "stat_atk",
    "stat_heal",
)


def merge_student_entry(old: dict, new: dict) -> dict:
    """
    학생 1명의 old 상태와 new 스캔 결과를 병합해 반환.
    meta 필드(last_seen_at, last_scan_id)는 호출자가 채운다.

    Parameters
    ----------
    old : 기존 current/students.json 레코드 (없으면 빈 dict)
    new : 이번 스캔 결과 dict

    Returns
    -------
    merged dict (meta 제외)
    """
    merged = dict(old)  # old를 베이스로 복사

    for field in _STUDENT_MERGE_FIELDS:
        old_v = old.get(field)
        new_v = new.get(field)
        merged[field] = _merge_field(field, old_v, new_v)

    return merged


def compute_student_diff(old: dict, new_merged: dict) -> list[FieldDiff]:
    """
    병합 후 실제로 바뀐 필드 목록 반환.
    new_merged는 merge_student_entry() 결과.
    """
    diffs: list[FieldDiff] = []
    for field in _STUDENT_MERGE_FIELDS:
        ov = _str(old.get(field))
        nv = _str(new_merged.get(field))
        if ov != nv:
            diffs.append(FieldDiff(field=field, old_value=ov, new_value=nv))
    return diffs


# ── 인벤토리 병합 ─────────────────────────────────────────
# inventory: {"아이템명": {"quantity": "10", "index": 0}, ...}

def merge_inventory_snapshot(old: dict, new: dict) -> dict:
    """
    인벤토리 스냅샷 병합.

    규칙:
      - 새 스캔에 있는 항목은 갱신 (quantity 덮어쓰기)
      - 새 스캔에 없는 항목은 기존 유지 (부분 스캔 대응)
      - quantity가 None / "" 이면 기존 유지

    Parameters
    ----------
    old : {"item_name": {"quantity": str, "index": int}, ...}
    new : 같은 구조

    Returns
    -------
    merged dict
    """
    merged = dict(old)

    for name, new_entry in new.items():
        new_qty = new_entry.get("quantity")
        if not new_qty:          # None or ""
            continue             # 기존 유지
        merged[name] = {
            "item_id":  new_entry.get("item_id", merged.get(name, {}).get("item_id")),
            "name":     new_entry.get("name", merged.get(name, {}).get("name")),
            "quantity": new_qty,
            "index":    new_entry.get("index", merged.get(name, {}).get("index")),
            "item_source": new_entry.get("item_source", merged.get(name, {}).get("item_source")),
        }

    return merged


def compute_inventory_diff(old: dict, new_merged: dict) -> list[FieldDiff]:
    """
    인벤토리 변경 항목 목록 반환.
    추가된 항목, 수량 변경 항목만 포함. 삭제(=기존 유지)는 기록하지 않음.
    """
    diffs: list[FieldDiff] = []
    all_keys = set(old) | set(new_merged)

    for name in sorted(all_keys):
        ov = _str(old.get(name, {}).get("quantity") if name in old else None)
        nv = _str(new_merged.get(name, {}).get("quantity") if name in new_merged else None)
        if ov != nv:
            diffs.append(FieldDiff(field=name, old_value=ov, new_value=nv))

    return diffs
