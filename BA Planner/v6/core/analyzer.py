"""
core/analyzer.py — 분석기 계층

담당
  · 변경 통계       : 이번 스캔에서 바뀐 필드 수/종류 집계
  · 누락 필드 검출  : None 이 남아있는 필드 목록
  · 신뢰도 평가     : 필드 채움률 기반 0.0~1.0 점수
  · 최대값 도달 판정: 스캔 스킵 로직용

만렙 기준 (2026-04 현재)
  · level          : 90
  · student_star   : 5  (무기 보유 시 확정 5)
  · weapon_level   : 60  (전용무기 4성 장착 기준)
  · ex_skill       : 5
  · skill1~3       : 10
  · equip1~3_level : 70
  · equip4         : T2  (장착 가능 학생 한정)
  · stat_hp/atk/heal: 25  (Lv90 + 5★ 이상 시)

공개 인터페이스
  · analyze_scan_summary(student_dicts, changes, scan_id) → ScanSummary
  · is_student_maxed(student_dict)                        → bool
  · missing_fields(student_dict)                          → list[str]
  · field_confidence(student_dict)                        → float
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from core.equip4_students import has_equip4, EQUIP4_MAX_TIER

# ── 만렙 기준 상수 ────────────────────────────────────────
MAX_LEVEL        = 90
MAX_STUDENT_STAR = 5
MAX_WEAPON_LEVEL = 60   # 전용무기 4성 장착 기준 상한
MAX_EX_SKILL     = 5
MAX_SKILL        = 10
MAX_EQUIP_LEVEL  = 70   # equip1~3
STAT_MAX_VALUE   = 25
STAT_MIN_VALUE   = 0

# 스탯 해금 조건
STAT_UNLOCK_LEVEL = 90
STAT_UNLOCK_STAR  = 5

# 신뢰도 채점 기본 필드 (weapon/equip4/stat 은 조건부 추가)
_BASE_SCORED_FIELDS: tuple[str, ...] = (
    "level",
    "student_star",
    "weapon_state",
    "ex_skill",
    "skill1",
    "skill2",
    "skill3",
    "equip1",
    "equip2",
    "equip3",
    "equip1_level",
    "equip2_level",
    "equip3_level",
)
_WEAPON_SCORED_FIELDS  = ("weapon_star", "weapon_level")
_STAT_FIELDS           = ("stat_hp", "stat_atk", "stat_heal")


# ── 데이터 클래스 ─────────────────────────────────────────
@dataclass
class StudentSummary:
    student_id:   str
    display_name: str | None
    confidence:   float
    missing:      list[str]
    is_maxed:     bool


@dataclass
class ScanSummary:
    scan_id:             str
    total_students:      int
    changed_students:    int
    total_field_changes: int
    changed_fields_freq: dict[str, int]
    low_confidence:      list[StudentSummary]
    maxed_students:      list[str]


# ── 내부 헬퍼 ─────────────────────────────────────────────
def _scored_fields_for(student: dict) -> list[str]:
    """학생 상태에 따라 채점 대상 필드 목록을 동적으로 구성."""
    fields = list(_BASE_SCORED_FIELDS)

    sid = student.get("student_id", "")

    # equip4: 해당 학생만 채점
    if has_equip4(sid):
        fields.append("equip4")

    # 무기 보유 시 weapon 필드 채점
    ws = student.get("weapon_state")
    if ws in ("weapon_equipped", "weapon_unlocked_not_equipped"):
        fields += list(_WEAPON_SCORED_FIELDS)

    # 스탯: 해금 조건(Lv90 + 5★) 충족 시만 채점
    level = student.get("level") or 0
    star  = student.get("student_star") or 0
    if level >= STAT_UNLOCK_LEVEL and star >= STAT_UNLOCK_STAR:
        fields += list(_STAT_FIELDS)

    return fields


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _valid(v: Any) -> bool:
    """None / 'unknown' / '' 이면 False."""
    return v is not None and str(v) not in ("unknown", "")


# ── 학생 단위 분석 ────────────────────────────────────────
def missing_fields(student: dict) -> list[str]:
    """유효하지 않은(None / 'unknown') 채점 필드 목록."""
    return [f for f in _scored_fields_for(student) if not _valid(student.get(f))]


def field_confidence(student: dict) -> float:
    """채점 대상 중 유효하게 채워진 비율 (0.0~1.0)."""
    fields = _scored_fields_for(student)
    if not fields:
        return 1.0
    filled = sum(1 for f in fields if _valid(student.get(f)))
    return round(filled / len(fields), 3)


def is_student_maxed(student: dict) -> bool:
    """
    학생이 현재 만렙 기준을 모두 충족하는지 판정.
    True 이면 스캔 스킵 대상.

    조건 (AND):
      · level == 90
      · student_star == 5
      · ex_skill == 5,  skill1~3 == 10
      · equip1~3_level == 70
      · equip4 대상 학생: equip4 == "T2"
      · weapon_equipped: weapon_level == 60
      · 스탯 해금 상태: stat_hp/atk/heal == 25
    """
    sid = student.get("student_id", "")

    # 레벨/성작
    if _int(student.get("level"))        != MAX_LEVEL:        return False
    if _int(student.get("student_star")) != MAX_STUDENT_STAR: return False

    # 스킬
    if _int(student.get("ex_skill")) != MAX_EX_SKILL: return False
    for sk in ("skill1", "skill2", "skill3"):
        if _int(student.get(sk)) != MAX_SKILL:        return False

    # 장비 티어 (equip1~3 유효하면 OK, T 숫자는 별도 제한 없음)
    for eq in ("equip1", "equip2", "equip3"):
        if not _valid(student.get(eq)):               return False

    # 장비 레벨 (equip1~3 모두 70)
    for eql in ("equip1_level", "equip2_level", "equip3_level"):
        if _int(student.get(eql)) != MAX_EQUIP_LEVEL: return False

    # equip4: 해당 학생만 T2 확인
    if has_equip4(sid):
        if str(student.get("equip4", "")) != EQUIP4_MAX_TIER: return False

    # 무기
    ws = student.get("weapon_state")
    if ws == "weapon_equipped":
        if _int(student.get("weapon_level")) != MAX_WEAPON_LEVEL: return False

    # 스탯 (Lv90 + 5★ → 해금 확정이므로 반드시 25)
    for st in _STAT_FIELDS:
        if _int(student.get(st)) != STAT_MAX_VALUE:   return False

    return True


def analyze_student(student: dict) -> StudentSummary:
    sid = student.get("student_id", "?")
    return StudentSummary(
        student_id=sid,
        display_name=student.get("display_name"),
        confidence=field_confidence(student),
        missing=missing_fields(student),
        is_maxed=is_student_maxed(student),
    )


# ── 스캔 전체 분석 ────────────────────────────────────────
def analyze_scan_summary(
    students: list[dict],
    changes:  list[dict],
    scan_id:  str = "",
) -> ScanSummary:
    freq: dict[str, int] = {}
    changed_sids: set[str] = set()
    for c in changes:
        f = c.get("field", "?")
        freq[f] = freq.get(f, 0) + 1
        changed_sids.add(c.get("student_id", ""))

    summaries = [analyze_student(s) for s in students]
    low_conf  = [s for s in summaries if s.confidence < 0.7]
    maxed     = [s.student_id for s in summaries if s.is_maxed]

    if low_conf:
        print(f"[Analyzer] 신뢰도 낮은 학생 {len(low_conf)}명:")
        for s in low_conf:
            print(f"  {s.student_id}({s.display_name}): "
                  f"conf={s.confidence:.2f} 누락={s.missing}")

    return ScanSummary(
        scan_id=scan_id,
        total_students=len(students),
        changed_students=len(changed_sids),
        total_field_changes=len(changes),
        changed_fields_freq=freq,
        low_confidence=low_conf,
        maxed_students=maxed,
    )
