"""
core/rescan.py — BA Analyzer v6
재스캔 / 후처리 친화적 구조

━━━ 설계 원칙 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  저장된 StudentEntry 목록에서 "어떤 학생의 어떤 필드를 재스캔할지"
  를 필터링하고 계획(RescanPlan)으로 만드는 쿼리 계층.

  실제 스캔 실행은 Scanner 가 담당하고,
  이 모듈은 "무엇을 재스캔할지 결정"만 담당함.

━━━ 재스캔 트리거 조건 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  FieldStatus 기준:
    failed          → 재스캔 대상 (인식 실패)
    uncertain       → 재스캔 대상 (신뢰도 낮음, 선택적)
    region_missing  → 재스캔 불필요 (설정 문제, 스캔으로 해결 안 됨)
    skipped         → 재스캔 불필요 (조건 미충족)
    inferred        → 재스캔 불필요 (논리적 추론값)
    ok              → 재스캔 불필요

  ScanState 기준:
    PARTIAL         → 재스캔 후보 (일부 필드 누락)
    FAILED          → 식별 실패, 재스캔 필요
    COMMITTED       → 재스캔 불필요 (단, uncertain 필드 있으면 선택적)

━━━ RescanPlan 구조 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  RescanPlan
    .targets: list[RescanTarget]
      각 target:
        .student_id   : 재스캔 대상 학생 ID
        .display_name : 표시 이름
        .fields       : 재스캔할 필드 목록
        .reason       : 재스캔 이유 (failed/uncertain/partial)
        .priority     : 높을수록 먼저 처리 (0~10)
    .total            : 대상 학생 수
    .field_counts     : 필드별 재스캔 필요 횟수
    .to_dict()        : 직렬화
    .summary()        : 텍스트 요약

━━━ 공개 인터페이스 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  # 재스캔 계획 생성
  plan = build_rescan_plan(
      entries,
      include_uncertain=True,
      fields=["level", "student_star"],  # 특정 필드만
  )

  # 결과 파일에서 직접 로드
  plan = load_rescan_plan_from_file(path)

  # 재스캔 대상 필터링 쿼리
  filter_by_state(entries, states)
  filter_by_field_status(entries, field, statuses)
  filter_failed_step(entries, step)

  # 저장
  save_rescan_plan(plan, path)
  load_rescan_plan(path) → RescanPlan
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── 지연 임포트 (순환 방지) ──────────────────────────────
def _types():
    from core.scanner import (
        StudentEntry, ScanState, FieldStatus, FieldSource,
    )
    return StudentEntry, ScanState, FieldStatus, FieldSource


# ══════════════════════════════════════════════════════════
# 재스캔 트리거 정의
# ══════════════════════════════════════════════════════════

# 항상 재스캔 대상인 FieldStatus
RESCAN_STATUSES_ALWAYS: set[str] = {"failed"}

# 선택적 재스캔 대상 (include_uncertain=True 일 때만)
RESCAN_STATUSES_OPTIONAL: set[str] = {"uncertain"}

# 재스캔이 의미 없는 FieldStatus (조건/설정 문제)
RESCAN_STATUSES_SKIP: set[str] = {"region_missing", "skipped", "inferred", "ok"}

# 필드별 우선순위 가중치 (높을수록 중요)
FIELD_PRIORITY: dict[str, int] = {
    "level":         10,
    "student_star":   9,
    "weapon_state":   8,
    "ex_skill":       7,
    "skill1":         7,
    "skill2":         7,
    "skill3":         7,
    "equip1":         6,
    "equip2":         6,
    "equip3":         6,
    "equip4":         5,
    "equip1_level":   4,
    "equip2_level":   4,
    "equip3_level":   4,
    "weapon_star":    3,
    "weapon_level":   3,
    "stat_hp":        2,
    "stat_atk":       2,
    "stat_heal":      2,
}


# ══════════════════════════════════════════════════════════
# 데이터 타입
# ══════════════════════════════════════════════════════════

@dataclass
class RescanTarget:
    """
    단일 학생의 재스캔 계획.

    Attributes
    ----------
    student_id   : 학생 ID
    display_name : 표시 이름
    fields       : 재스캔할 필드 목록
    field_reasons: {field: reason} — 왜 이 필드를 재스캔하는지
    reason       : 전체 재스캔 이유 (partial / failed / uncertain)
    priority     : 처리 우선순위 (0~10, 높을수록 먼저)
    scan_state   : 현재 ScanState
    """
    student_id:    str
    display_name:  str
    fields:        list[str]
    field_reasons: dict[str, str]   = field(default_factory=dict)
    reason:        str              = "unknown"
    priority:      int              = 0
    scan_state:    str              = "partial"

    def to_dict(self) -> dict:
        return {
            "student_id":    self.student_id,
            "display_name":  self.display_name,
            "fields":        self.fields,
            "field_reasons": self.field_reasons,
            "reason":        self.reason,
            "priority":      self.priority,
            "scan_state":    self.scan_state,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RescanTarget":
        return cls(
            student_id=d.get("student_id", ""),
            display_name=d.get("display_name", ""),
            fields=d.get("fields", []),
            field_reasons=d.get("field_reasons", {}),
            reason=d.get("reason", "unknown"),
            priority=d.get("priority", 0),
            scan_state=d.get("scan_state", "partial"),
        )


@dataclass
class RescanPlan:
    """
    재스캔 계획 전체.

    Attributes
    ----------
    targets      : 재스캔 대상 학생 목록 (priority 내림차순)
    source_scan  : 원본 scan_id
    created_at   : 계획 생성 시각
    field_counts : {field: 재스캔 필요 횟수}
    total_fields : 재스캔할 필드 총 수
    """
    targets:      list[RescanTarget]
    source_scan:  str               = ""
    created_at:   str               = ""
    field_counts: dict[str, int]    = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.targets)

    @property
    def total_fields(self) -> int:
        return sum(len(t.fields) for t in self.targets)

    def is_empty(self) -> bool:
        return len(self.targets) == 0

    def summary(self) -> list[str]:
        """텍스트 요약 — UI 로그에 바로 전달 가능."""
        if self.is_empty():
            return ["✅ 재스캔 대상 없음"]

        lines = [f"🔄 재스캔 계획: {self.total}명 / {self.total_fields}개 필드"]

        # 이유별 집계
        reason_count: dict[str, int] = {}
        for t in self.targets:
            reason_count[t.reason] = reason_count.get(t.reason, 0) + 1
        for reason, cnt in sorted(reason_count.items(), key=lambda x: -x[1]):
            lines.append(f"  {_reason_icon(reason)} {reason}: {cnt}명")

        # 필드별 집계 상위 5개
        top = sorted(self.field_counts.items(), key=lambda x: -x[1])[:5]
        if top:
            lines.append("  📊 필드별 재스캔 횟수 (상위 5):")
            for fname, cnt in top:
                lines.append(f"    - {fname}: {cnt}명")

        return lines

    def to_dict(self) -> dict:
        return {
            "source_scan":  self.source_scan,
            "created_at":   self.created_at,
            "total":        self.total,
            "total_fields": self.total_fields,
            "field_counts": self.field_counts,
            "targets":      [t.to_dict() for t in self.targets],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RescanPlan":
        targets = [RescanTarget.from_dict(t) for t in d.get("targets", [])]
        return cls(
            targets=targets,
            source_scan=d.get("source_scan", ""),
            created_at=d.get("created_at", ""),
            field_counts=d.get("field_counts", {}),
        )


def _reason_icon(reason: str) -> str:
    return {"failed": "❌", "uncertain": "⚠️", "partial": "🔶"}.get(reason, "•")


# ══════════════════════════════════════════════════════════
# 재스캔 계획 생성
# ══════════════════════════════════════════════════════════

def build_rescan_plan(
    entries:             list,
    *,
    include_uncertain:   bool        = True,
    fields:              Optional[list[str]] = None,
    source_scan:         str         = "",
    min_priority:        int         = 0,
) -> RescanPlan:
    """
    StudentEntry 목록 → RescanPlan 생성.

    Parameters
    ----------
    entries           : list[StudentEntry]
    include_uncertain : True 이면 uncertain 필드도 재스캔 대상
    fields            : 특정 필드만 검사. None 이면 전체
    source_scan       : 원본 scan_id (파일명)
    min_priority      : 이 값 이상인 필드만 포함

    Returns
    -------
    RescanPlan (priority 내림차순 정렬)
    """
    _, ScanState, FieldStatus, _ = _types()

    trigger_statuses = set(RESCAN_STATUSES_ALWAYS)
    if include_uncertain:
        trigger_statuses |= RESCAN_STATUSES_OPTIONAL

    targets:      list[RescanTarget] = []
    field_counts: dict[str, int]     = {}

    for entry in entries:
        target = _check_entry(
            entry,
            ScanState=ScanState,
            FieldStatus=FieldStatus,
            trigger_statuses=trigger_statuses,
            filter_fields=fields,
            min_priority=min_priority,
        )
        if target is None:
            continue

        targets.append(target)
        for fname in target.fields:
            field_counts[fname] = field_counts.get(fname, 0) + 1

    # priority 내림차순 정렬
    targets.sort(key=lambda t: -t.priority)

    return RescanPlan(
        targets=targets,
        source_scan=source_scan,
        created_at=datetime.now().isoformat(),
        field_counts=field_counts,
    )


def _check_entry(
    entry,
    *,
    ScanState,
    FieldStatus,
    trigger_statuses: set[str],
    filter_fields:    Optional[list[str]],
    min_priority:     int,
) -> Optional[RescanTarget]:
    """
    단일 StudentEntry 를 검사해 RescanTarget 반환.
    재스캔 불필요하면 None.
    """
    rescan_fields:  list[str]      = []
    field_reasons:  dict[str, str] = {}
    reason_set:     set[str]       = set()
    priority_sum:   int            = 0

    # ── FAILED 엔트리 — 식별 자체 실패 ───────────────────
    if entry.scan_state == ScanState.FAILED:
        return RescanTarget(
            student_id=entry.student_id or "unknown",
            display_name=entry.display_name or "?",
            fields=["__identify__"],
            field_reasons={"__identify__": "student_id_failed"},
            reason="failed",
            priority=10,
            scan_state=entry.scan_state,
        )

    # ── 필드별 메타 검사 ──────────────────────────────────
    check_fields = filter_fields or list(FIELD_PRIORITY.keys())

    for fname in check_fields:
        fp = FIELD_PRIORITY.get(fname, 1)
        if fp < min_priority:
            continue

        meta = entry.get_meta(fname)
        if meta is None:
            # 메타 없음 — 값이 None 이면 failed 로 간주
            val = getattr(entry, fname, None)
            if val is None:
                rescan_fields.append(fname)
                field_reasons[fname] = "no_meta_null_value"
                reason_set.add("partial")
                priority_sum += fp
            continue

        if meta.status in trigger_statuses:
            rescan_fields.append(fname)
            field_reasons[fname] = meta.status
            reason_set.add(meta.status)
            priority_sum += fp

    if not rescan_fields:
        return None

    # PARTIAL 상태도 reason에 포함
    if entry.scan_state == ScanState.PARTIAL and "partial" not in reason_set:
        reason_set.add("partial")

    # 대표 이유 결정 (failed > uncertain > partial)
    if "failed" in reason_set:
        reason = "failed"
    elif "uncertain" in reason_set:
        reason = "uncertain"
    else:
        reason = "partial"

    # 우선순위 정규화 (0~10)
    priority = min(10, priority_sum // max(len(rescan_fields), 1))

    return RescanTarget(
        student_id=entry.student_id or "unknown",
        display_name=entry.display_name or "?",
        fields=rescan_fields,
        field_reasons=field_reasons,
        reason=reason,
        priority=priority,
        scan_state=entry.scan_state,
    )


# ══════════════════════════════════════════════════════════
# 필터링 쿼리 함수
# ══════════════════════════════════════════════════════════

def filter_by_state(
    entries:  list,
    states:   list[str],
) -> list:
    """
    특정 ScanState 인 엔트리만 반환.

    예:
      partial_entries = filter_by_state(entries, ["partial", "failed"])
    """
    return [e for e in entries if e.scan_state in states]


def filter_by_field_status(
    entries:  list,
    fname:    str,
    statuses: list[str],
) -> list:
    """
    특정 필드가 주어진 상태인 엔트리만 반환.

    예:
      level_failed = filter_by_field_status(entries, "level", ["failed"])
      star_uncertain = filter_by_field_status(entries, "student_star", ["uncertain"])
    """
    result = []
    for e in entries:
        meta = e.get_meta(fname)
        if meta and meta.status in statuses:
            result.append(e)
        elif meta is None and getattr(e, fname, None) is None:
            # 메타 없이 값도 None → failed 로 간주
            if "failed" in statuses:
                result.append(e)
    return result


def filter_failed_step(
    entries:  list,
    step:     str,
    step_errors_map: Optional[dict[str, list[str]]] = None,
) -> list:
    """
    특정 단계 실패 학생 필터링.
    step_errors_map: {student_id: [failed_steps]} — 세션 로그 기반

    step_errors_map 없으면 field_status 기반 추론:
      step="read_level"   → field="level" status=failed
      step="read_skills"  → field in [ex_skill,skill1..3] status=failed
      step="read_weapon"  → field="weapon_state" status=failed/uncertain
      step="identify"     → scan_state=FAILED
    """
    _, ScanState, FieldStatus, _ = _types()

    if step_errors_map is not None:
        return [e for e in entries
                if step in step_errors_map.get(e.student_id or "", [])]

    # step → field 매핑으로 추론
    _STEP_FIELDS: dict[str, list[str]] = {
        "read_level":   ["level"],
        "read_skills":  ["ex_skill", "skill1", "skill2", "skill3"],
        "read_weapon":  ["weapon_state", "weapon_star", "weapon_level"],
        "read_equip":   ["equip1", "equip2", "equip3", "equip1_level",
                         "equip2_level", "equip3_level"],
        "read_star":    ["student_star"],
        "read_stats":   ["stat_hp", "stat_atk", "stat_heal"],
        "identify":     [],   # scan_state=FAILED 로 판별
    }

    if step == "identify":
        return [e for e in entries if e.scan_state == ScanState.FAILED]

    target_fields = _STEP_FIELDS.get(step, [])
    return filter_by_field_status(entries, target_fields[0],
                                  ["failed", "uncertain"]) if target_fields else []


def filter_low_confidence(
    entries:   list,
    threshold: float = 0.70,
) -> list:
    """confidence 가 threshold 미만인 엔트리 필터링."""
    return [e for e in entries if e.confidence() < threshold]


def filter_uncertain_fields(
    entries: list,
    fields:  Optional[list[str]] = None,
) -> list:
    """
    uncertain 필드를 가진 엔트리 필터링.
    fields 지정 시 그 필드가 uncertain 인 것만.
    """
    result = []
    for e in entries:
        uf = e.uncertain_fields()
        if fields:
            if any(f in uf for f in fields):
                result.append(e)
        elif uf:
            result.append(e)
    return result


# ══════════════════════════════════════════════════════════
# 파일 I/O
# ══════════════════════════════════════════════════════════

def save_rescan_plan(plan: RescanPlan, path: Path | str) -> None:
    """RescanPlan → JSON 파일 저장."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)


def load_rescan_plan(path: Path | str) -> Optional[RescanPlan]:
    """JSON 파일 → RescanPlan 복원."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return RescanPlan.from_dict(json.load(f))
    except Exception as e:
        from core.logger import get_logger, LOG_APP
        get_logger(LOG_APP).error(f"RescanPlan 로드 실패 ({path}): {e}")
        return None


def load_rescan_plan_from_file(scan_path: Path | str) -> RescanPlan:
    """
    스캔 결과 JSON 파일에서 직접 RescanPlan 생성.
    별도 저장 없이 기존 파일만으로 재스캔 계획 추출 가능.

    예:
      plan = load_rescan_plan_from_file("scans/scan_20260405_143000.json")
    """
    from core.serializer import load_scan_json

    result = load_scan_json(scan_path)
    if result is None:
        return RescanPlan(targets=[], source_scan=str(scan_path))

    scan_id = Path(scan_path).stem
    return build_rescan_plan(result.students, source_scan=scan_id)


# ══════════════════════════════════════════════════════════
# RescanPlan → Scanner 연동 헬퍼
# ══════════════════════════════════════════════════════════

def get_rescan_student_ids(plan: RescanPlan) -> list[str]:
    """재스캔 대상 student_id 목록 (priority 순)."""
    return [t.student_id for t in plan.targets]


def get_rescan_fields_for(plan: RescanPlan, student_id: str) -> list[str]:
    """
    특정 학생의 재스캔 필드 목록.
    Scanner 에 전달해 해당 단계만 재실행할 때 사용.
    """
    for t in plan.targets:
        if t.student_id == student_id:
            return t.fields
    return []


def make_rescan_maxed_cache(
    all_entries: list,
    plan:        RescanPlan,
) -> dict[str, dict]:
    """
    재스캔 시 만렙 스킵 캐시 생성.
    plan에 없는 학생(= 재스캔 불필요)은 기존 데이터를 캐시로 넘겨
    Scanner 의 만렙 스킵 로직에서 재활용.

    Returns
    -------
    {student_id: entry_dict}
    """
    rescan_ids = set(get_rescan_student_ids(plan))
    cache: dict[str, dict] = {}
    for e in all_entries:
        sid = e.student_id
        if sid and sid not in rescan_ids:
            cache[sid] = e.to_dict()
    return cache
