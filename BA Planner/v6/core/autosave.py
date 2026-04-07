"""
core/autosave.py — BA Analyzer v6
autosave 정책 명문화 + 원자적 쓰기 + emergency save + 세션 메타데이터

━━━ autosave 정책 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. 학생 1명 완료 시 즉시 저장 (per-student save)
       → 세션 중간에 죽어도 마지막 완료 학생까지 복구 가능

  2. FLUSH_EVERY 명마다 전체 flush (기본 10명)
       → 임시 파일 → 교체 방식으로 기존 파일 손상 없음

  3. 스캔 완료 시 최종 저장 (final save)
       → 완전한 ScanResult + SessionMeta 를 저장

  4. 예외 발생 시 emergency save
       → 진행된 데이터를 emergency_{scan_id}_{ts}.json 으로 저장
       → 기존 파일 덮어쓰지 않음

━━━ 세션 메타데이터 구조 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {
    "session": {
      "scan_id":             "scan_20260405_143000",
      "session_started_at":  "2026-04-05T14:30:00.123",
      "session_finished_at": "2026-04-05T14:52:17.456",
      "duration_sec":        1337.3,
      "students_total":      83,
      "students_committed":  79,
      "students_partial":     3,
      "students_skipped":     1,
      "students_failed":      0,
      "items_total":         241,
      "equipment_total":      88,
      "errors_by_step": {
        "read_level":        2,
        "read_skills":       1,
        "identify":          0
      },
      "uncertain_by_field": {
        "weapon_state":      3,
        "student_star":      1
      },
      "avg_confidence":      0.94,
      "low_confidence_ids":  ["hina", "aris"],
      "autosave_flushes":    8,
      "save_failures":       0
    }
  }

━━━ 원자적 쓰기 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {path}.tmp 에 쓴 뒤 os.replace({path}.tmp, {path}) 로 교체.
  replace 는 POSIX 에서 원자적, Windows 에서는 best-effort 원자적.
  → 쓰기 도중 프로세스 종료 시 기존 파일 손상 없음.

━━━ 파일 경로 규칙 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  scans/
    {scan_id}.json              ← 최종 / flush 파일
    {scan_id}.tmp               ← 원자적 쓰기 중간 파일 (자동 삭제)
    checkpoint_{scan_id}.json   ← per-student 체크포인트
    emergency_{scan_id}_{ts}.json ← 예외 시 긴급 저장

━━━ 공개 인터페이스 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  SessionMeta                              (세션 메타 데이터클래스)
    .to_dict()                             → dict
    .elapsed_sec                           → float

  AutoSaveManager(scan_id, save_dir)
    .on_student_committed(entry)    → None  (1명 완료 시)
    .on_step_error(step, entry_id)  → None  (단계 오류 기록)
    .flush(results, meta)           → bool  (전체 flush)
    .final_save(result, meta)       → bool  (스캔 완료 시)
    .emergency_save(result, meta)   → Path | None  (예외 시)
    .load_checkpoint()              → list[StudentEntry]  (복원)
    .build_session_meta()           → SessionMeta
    .stats()                        → dict
"""

from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.logger import get_logger, LOG_APP

_log = get_logger(LOG_APP)


# ══════════════════════════════════════════════════════════
# 정책 상수 — 여기만 조정하면 전체에 반영됨
# ══════════════════════════════════════════════════════════

AUTOSAVE_PER_STUDENT: bool = True   # 학생 1명 완료마다 체크포인트 저장
FLUSH_EVERY:          int  = 10     # N명마다 전체 flush
CHECKPOINT_ONLY_NEW:  bool = True   # True: 신규 항목만 추가 (기존 덮어쓰기 X)

# flush / final save 실패 시 재시도 횟수
SAVE_RETRY:   int   = 2
SAVE_DELAY:   float = 0.5   # 재시도 간격(초)

# 낮은 신뢰도 기준
LOW_CONFIDENCE_THRESHOLD: float = 0.70


# ══════════════════════════════════════════════════════════
# SessionMeta 데이터클래스
# ══════════════════════════════════════════════════════════

@dataclass
class SessionMeta:
    """
    스캔 세션 전체 요약 메타데이터.

    AutoSaveManager.build_session_meta() 로 생성.
    저장 파일의 "session" 키 아래에 포함됨.
    """
    scan_id:             str
    session_started_at:  str
    session_finished_at: str = ""
    duration_sec:        float = 0.0

    # 학생 수 통계
    students_total:     int = 0
    students_committed: int = 0
    students_partial:   int = 0
    students_skipped:   int = 0
    students_failed:    int = 0

    # 아이템 / 장비
    items_total:     int = 0
    equipment_total: int = 0

    # 오류 통계 — 단계별 오류 횟수
    # key: step 이름  value: 오류 횟수
    errors_by_step: dict = field(default_factory=dict)

    # 불확실 인식 통계 — 필드별 uncertain 횟수
    uncertain_by_field: dict = field(default_factory=dict)

    # 신뢰도
    avg_confidence:      float      = 0.0
    low_confidence_ids:  list[str]  = field(default_factory=list)

    # autosave 통계
    autosave_flushes: int = 0
    save_failures:    int = 0

    # 세션 종료 상태
    finished_normally: bool = True   # False 이면 예외/중단으로 종료

    @property
    def elapsed_sec(self) -> float:
        return self.duration_sec

    def to_dict(self) -> dict:
        return {
            "scan_id":             self.scan_id,
            "session_started_at":  self.session_started_at,
            "session_finished_at": self.session_finished_at,
            "duration_sec":        round(self.duration_sec, 1),
            "students_total":      self.students_total,
            "students_committed":  self.students_committed,
            "students_partial":    self.students_partial,
            "students_skipped":    self.students_skipped,
            "students_failed":     self.students_failed,
            "items_total":         self.items_total,
            "equipment_total":     self.equipment_total,
            "errors_by_step":      dict(self.errors_by_step),
            "uncertain_by_field":  dict(self.uncertain_by_field),
            "avg_confidence":      round(self.avg_confidence, 3),
            "low_confidence_ids":  list(self.low_confidence_ids),
            "autosave_flushes":    self.autosave_flushes,
            "save_failures":       self.save_failures,
            "finished_normally":   self.finished_normally,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SessionMeta":
        return cls(
            scan_id=d.get("scan_id", ""),
            session_started_at=d.get("session_started_at", ""),
            session_finished_at=d.get("session_finished_at", ""),
            duration_sec=d.get("duration_sec", 0.0),
            students_total=d.get("students_total", 0),
            students_committed=d.get("students_committed", 0),
            students_partial=d.get("students_partial", 0),
            students_skipped=d.get("students_skipped", 0),
            students_failed=d.get("students_failed", 0),
            items_total=d.get("items_total", 0),
            equipment_total=d.get("equipment_total", 0),
            errors_by_step=d.get("errors_by_step", {}),
            uncertain_by_field=d.get("uncertain_by_field", {}),
            avg_confidence=d.get("avg_confidence", 0.0),
            low_confidence_ids=d.get("low_confidence_ids", []),
            autosave_flushes=d.get("autosave_flushes", 0),
            save_failures=d.get("save_failures", 0),
            finished_normally=d.get("finished_normally", True),
        )


# ══════════════════════════════════════════════════════════
# 원자적 파일 쓰기
# ══════════════════════════════════════════════════════════

def _atomic_write(path: Path, data: dict, *, indent: int = 2) -> bool:
    """
    {path}.tmp 에 쓴 뒤 os.replace 로 교체.
    쓰기 실패 시 .tmp 파일 정리 후 False 반환.

    Returns True = 성공, False = 실패
    """
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent,
                      default=_json_default)
        os.replace(tmp, path)   # 원자적 교체
        return True
    except Exception as e:
        _log.error(f"[AutoSave] 원자적 쓰기 실패 ({path}): {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _atomic_write_with_retry(
    path:  Path,
    data:  dict,
    retry: int   = SAVE_RETRY,
    delay: float = SAVE_DELAY,
) -> bool:
    """_atomic_write 를 retry 회 재시도."""
    for attempt in range(retry + 1):
        if _atomic_write(path, data):
            return True
        if attempt < retry:
            _log.warning(
                f"[AutoSave] 재시도 {attempt+1}/{retry}: {path.name}"
            )
            time.sleep(delay)
    _log.error(f"[AutoSave] {retry}회 재시도 후 저장 포기: {path}")
    return False


def _json_default(obj):
    if hasattr(obj, "value"):    # Enum
        return obj.value
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return str(obj)


# ══════════════════════════════════════════════════════════
# AutoSaveManager
# ══════════════════════════════════════════════════════════

class AutoSaveManager:
    """
    학생 스캔 세션 단위 autosave 관리자.

    사용 예
    -------
    asv = AutoSaveManager(scan_id="scan_20260405_143000",
                          save_dir=BASE_DIR / "scans")
    # 학생 1명 완료 시
    asv.on_student_committed(entry)

    # 스캔 완료 시
    asv.final_save(result, meta)

    # 예외 발생 시 (finally 블록에서)
    asv.emergency_save(result, meta)
    """

    def __init__(
        self,
        scan_id:  str,
        save_dir: Path | str,
        *,
        on_save_ok:   Optional[callable] = None,
        on_save_fail: Optional[callable] = None,
    ):
        self._scan_id     = scan_id
        self._save_dir    = Path(save_dir)
        self._on_ok       = on_save_ok   or (lambda msg: None)
        self._on_fail     = on_save_fail or (lambda msg: None)

        self._committed:  list[dict] = []
        self._lock        = threading.Lock()
        self._flush_count = 0
        self._save_count  = 0
        self._fail_count  = 0

        # ── 세션 메타 수집 ────────────────────────────────
        self._started_at:  float = time.monotonic()
        self._started_iso: str   = datetime.now().isoformat()
        self._finished_iso: str  = ""
        self._finished_normally: bool = True

        # 단계별 오류 횟수: {"read_level": 2, "identify": 1, ...}
        self._step_errors: dict[str, int] = {}

        # 필드별 uncertain 횟수: {"weapon_state": 3, ...}
        self._uncertain_counts: dict[str, int] = {}

        # 파일 경로
        self._final_path  = self._save_dir / f"{scan_id}.json"
        self._ckpt_path   = self._save_dir / f"checkpoint_{scan_id}.json"

        _log.info(
            f"[AutoSave] 세션 시작: {scan_id}  "
            f"(per_student={AUTOSAVE_PER_STUDENT} "
            f"flush_every={FLUSH_EVERY})"
        )

    # ── 학생 1명 완료 시 ──────────────────────────────────

    def on_student_committed(self, entry) -> None:
        """
        학생 1명 COMMITTED / PARTIAL 완료 시 호출.
        uncertain 필드 집계 + 체크포인트 저장 + flush 조건 확인.
        """
        from core.serializer import serialize_student

        # uncertain 필드 집계
        with self._lock:
            for fname in entry.uncertain_fields():
                self._uncertain_counts[fname] = (
                    self._uncertain_counts.get(fname, 0) + 1
                )
            serialized = serialize_student(entry)
            self._committed.append(serialized)
            count = len(self._committed)

        if AUTOSAVE_PER_STUDENT:
            self._save_checkpoint()

        if count > 0 and count % FLUSH_EVERY == 0:
            self._flush_locked()
            _log.info(
                f"[AutoSave] flush 완료: {count}명 "
                f"(flush #{self._flush_count})"
            )
            self._on_ok(f"💾 중간 저장 ({count}명)")

    def on_step_error(self, step: str, student_id: str = "") -> None:
        """
        단계 오류 발생 시 호출 — step별 오류 횟수 집계.

        Parameters
        ----------
        step       : 오류 발생 단계 ("read_level", "identify", ...)
        student_id : 오류가 발생한 학생 ID (로그용)
        """
        with self._lock:
            self._step_errors[step] = self._step_errors.get(step, 0) + 1
        _log.debug(
            f"[AutoSave] step_error: step={step} "
            f"student={student_id or '?'} "
            f"(누계={self._step_errors[step]})"
        )

    # ── 세션 메타 생성 ────────────────────────────────────

    def build_session_meta(self, result=None) -> SessionMeta:
        """
        현재까지 수집된 데이터로 SessionMeta 생성.
        final_save / emergency_save 전에 호출.

        Parameters
        ----------
        result : ScanResult (있으면 통계에 반영, 없으면 committed 기준)
        """
        from core.scanner import ScanState

        now = datetime.now().isoformat()
        dur = time.monotonic() - self._started_at

        with self._lock:
            step_errors     = dict(self._step_errors)
            uncertain_cnts  = dict(self._uncertain_counts)

        # 학생 수 통계
        if result is not None:
            students  = result.students
            items_n   = len(result.items)
            equip_n   = len(result.equipment)
        else:
            # result 없으면 committed 캐시 기준
            students  = []
            items_n   = 0
            equip_n   = 0

        state_counts: dict[str, int] = {}
        confidences:  list[float]    = []
        low_ids:      list[str]      = []

        for e in students:
            state_counts[e.scan_state] = state_counts.get(e.scan_state, 0) + 1
            c = e.confidence()
            confidences.append(c)
            if c < LOW_CONFIDENCE_THRESHOLD:
                low_ids.append(e.student_id or "?")

        avg_conf = (
            round(sum(confidences) / len(confidences), 3)
            if confidences else 0.0
        )

        return SessionMeta(
            scan_id=self._scan_id,
            session_started_at=self._started_iso,
            session_finished_at=now,
            duration_sec=round(dur, 1),
            students_total=len(students),
            students_committed=state_counts.get(ScanState.COMMITTED, 0),
            students_partial=state_counts.get(ScanState.PARTIAL, 0),
            students_skipped=state_counts.get(ScanState.SKIPPED, 0),
            students_failed=state_counts.get(ScanState.FAILED, 0),
            items_total=items_n,
            equipment_total=equip_n,
            errors_by_step=step_errors,
            uncertain_by_field=uncertain_cnts,
            avg_confidence=avg_conf,
            low_confidence_ids=low_ids,
            autosave_flushes=self._flush_count,
            save_failures=self._fail_count,
            finished_normally=self._finished_normally,
        )

    def _save_checkpoint(self) -> bool:
        """
        체크포인트 저장 — 지금까지 committed 된 항목만.
        기존 체크포인트 파일을 원자적으로 교체.
        """
        with self._lock:
            data = {
                "scan_id":   self._scan_id,
                "saved_at":  datetime.now().isoformat(),
                "count":     len(self._committed),
                "students":  self._committed.copy(),
            }

        ok = _atomic_write(self._ckpt_path, data)
        if ok:
            self._save_count += 1
            _log.debug(
                f"[AutoSave] 체크포인트: {self._ckpt_path.name} "
                f"({len(self._committed)}명)"
            )
        else:
            self._fail_count += 1
            self._on_fail("⚠️ 체크포인트 저장 실패")
        return ok

    def _flush_locked(self) -> bool:
        """전체 flush — 체크포인트와 동일한 내용을 final 파일에도 씀."""
        with self._lock:
            data = {
                "scan_id":    self._scan_id,
                "flushed_at": datetime.now().isoformat(),
                "flush_num":  self._flush_count + 1,
                "count":      len(self._committed),
                "students":   self._committed.copy(),
                "_partial":   True,   # 스캔 미완료 표시
            }

        ok = _atomic_write_with_retry(self._final_path, data)
        if ok:
            self._flush_count += 1
            self._save_count  += 1
        else:
            self._fail_count += 1
        return ok

    # ── 전체 flush (외부 호출용) ──────────────────────────

    def flush(self, results: list, meta: dict) -> bool:
        """
        외부에서 명시적으로 전체 flush 요청.
        results 의 전체 직렬화 포함.
        """
        from core.serializer import serialize_student

        with self._lock:
            serialized = [serialize_student(e) for e in results]
            data = {
                "scan_id":    self._scan_id,
                "flushed_at": datetime.now().isoformat(),
                "meta":       meta,
                "count":      len(serialized),
                "students":   serialized,
                "_partial":   True,
            }

        ok = _atomic_write_with_retry(self._final_path, data)
        if ok:
            self._flush_count += 1
            _log.info(f"[AutoSave] 명시적 flush 완료: {len(serialized)}명")
        else:
            _log.error("[AutoSave] flush 실패")
        return ok

    # ── 스캔 완료 시 최종 저장 ────────────────────────────

    def final_save(self, result, meta: dict) -> bool:
        """스캔 완료 후 최종 ScanResult + SessionMeta 저장."""
        from core.serializer import serialize_scan_result

        self._finished_normally = True
        self._finished_iso      = datetime.now().isoformat()
        session = self.build_session_meta(result)

        data = serialize_scan_result(result, meta)
        data["session"]   = session.to_dict()
        data["_partial"]  = False
        data["_saved_at"] = self._finished_iso

        ok = _atomic_write_with_retry(self._final_path, data)
        if ok:
            self._save_count += 1
            _log.info(
                f"[AutoSave] 최종 저장 완료: {self._final_path.name} "
                f"({len(result.students)}명 "
                f"duration={session.duration_sec}s "
                f"committed={session.students_committed} "
                f"partial={session.students_partial})"
            )
            self._on_ok(f"💾 최종 저장 완료 ({len(result.students)}명)")
            self._cleanup_checkpoint()
        else:
            self._fail_count += 1
            self._on_fail("❌ 최종 저장 실패 — 체크포인트 유지")
        return ok

    # ── 예외 시 emergency save ────────────────────────────

    def emergency_save(self, result, meta: dict) -> Optional[Path]:
        """예외/중단 시 긴급 저장. 기존 파일 덮어쓰지 않음."""
        self._finished_normally = False
        self._finished_iso      = datetime.now().isoformat()

        ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        epath = self._save_dir / f"emergency_{self._scan_id}_{ts}.json"
        session = self.build_session_meta(result)

        with self._lock:
            committed_now = self._committed.copy()

        try:
            from core.serializer import serialize_scan_result
            data = serialize_scan_result(result, meta)
        except Exception:
            data = {
                "scan_id":   self._scan_id,
                "students":  committed_now,
                "items":     [],
                "equipment": [],
                "resources": {},
                "errors":    [],
            }

        data["session"]    = session.to_dict()
        data["_emergency"] = True
        data["_saved_at"]  = self._finished_iso
        data["_partial"]   = True

        ok = _atomic_write(epath, data)
        if ok:
            _log.warning(
                f"[AutoSave] ⚠️ Emergency 저장: {epath.name} "
                f"({len(result.students)}명 "
                f"duration={session.duration_sec}s)"
            )
            self._on_ok(f"⚠️ 긴급 저장: {epath.name}")
            return epath
        else:
            _log.error(f"[AutoSave] ❌ Emergency 저장 실패: {epath}")
            self._on_fail("❌ 긴급 저장 실패 — 데이터 유실 위험")
            return None

    # ── 체크포인트 복원 ───────────────────────────────────

    def load_checkpoint(self) -> list:
        """
        체크포인트 파일에서 StudentEntry 목록 복원.
        파일 없거나 손상 시 빈 목록 반환.

        Returns
        -------
        list[StudentEntry]
        """
        from core.serializer import deserialize_student

        if not self._ckpt_path.exists():
            return []

        try:
            with open(self._ckpt_path, encoding="utf-8") as f:
                data = json.load(f)
            students = [deserialize_student(d)
                        for d in data.get("students", [])]
            _log.info(
                f"[AutoSave] 체크포인트 복원: {len(students)}명 "
                f"({self._ckpt_path.name})"
            )
            return students
        except Exception as e:
            _log.error(f"[AutoSave] 체크포인트 복원 실패: {e}")
            return []

    def has_checkpoint(self) -> bool:
        """복원 가능한 체크포인트 파일이 있는지 확인."""
        return self._ckpt_path.exists()

    # ── 정리 ──────────────────────────────────────────────

    def _cleanup_checkpoint(self) -> None:
        """최종 저장 성공 후 체크포인트 파일 삭제."""
        try:
            self._ckpt_path.unlink(missing_ok=True)
            _log.debug(f"[AutoSave] 체크포인트 삭제: {self._ckpt_path.name}")
        except Exception as e:
            _log.warning(f"[AutoSave] 체크포인트 삭제 실패: {e}")

    # ── 통계 ──────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            committed = len(self._committed)
            step_err  = dict(self._step_errors)
            uncertain = dict(self._uncertain_counts)
        return {
            "scan_id":        self._scan_id,
            "committed":      committed,
            "flush_count":    self._flush_count,
            "save_ok":        self._save_count,
            "save_fail":      self._fail_count,
            "step_errors":    step_err,
            "uncertain":      uncertain,
            "elapsed_sec":    round(time.monotonic() - self._started_at, 1),
            "final_path":     str(self._final_path),
            "ckpt_path":      str(self._ckpt_path),
            "has_ckpt":       self.has_checkpoint(),
        }

    def log_stats(self) -> None:
        s = self.stats()
        _log.info(
            f"[AutoSave] 세션 통계: "
            f"committed={s['committed']} "
            f"flush={s['flush_count']} "
            f"save_ok={s['save_ok']} "
            f"save_fail={s['save_fail']} "
            f"elapsed={s['elapsed_sec']}s"
        )
        if s["step_errors"]:
            _log.info(f"[AutoSave] 단계별 오류: {s['step_errors']}")
        if s["uncertain"]:
            _log.info(f"[AutoSave] uncertain 집계: {s['uncertain']}")