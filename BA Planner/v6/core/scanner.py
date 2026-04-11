"""
core/scanner.py — BA Analyzer v6
스캔 자동화 엔진

변경점 (v5 → v6):
  - 스캔 파이프라인 단계 함수 완전 분리
      enter_student_menu() / enter_first_student()
      identify_student()   / go_next_student()
      read_skills()        / read_weapon()
      read_equipment()     / read_level()
      read_student_star()  / read_stats()
  - 캡처 최소화
      · 각 단계 진입 직후 capture 1회 → 이후 crop 재사용
      · 불필요한 중간 capture 제거
  - UI 전환 중앙화
      · _tab(key)      : 탭 버튼 클릭 + 대기
      · _esc(n)        : ESC n회 + 대기
      · _click_r(rect) : region 중심 클릭 (HWND 기반)
  - retry 정책 통일
      · _retry(fn, max_attempts, delay) 헬퍼
      · 단계별 실패 시 skip / abort 정책 명시
  - input.py 기반 입력 (pyautogui 직접 호출 제거)
"""

import time
import hashlib
import numpy as np
from dataclasses import dataclass, field
from typing import Callable, Optional
from PIL import Image

from core.logger import get_logger, log_section, LOG_SCANNER
from core.log_context import (
    ScanCtx, log_exc, EXC_WARNING, EXC_ERROR, EXC_FATAL,
    dump_roi,
)

# 모듈 로거
_log = get_logger(LOG_SCANNER)

# ── 캡처 / 입력 ──────────────────────────────────────────
from core.capture import (
    capture_window_background,
    crop_region,
    get_window_rect,
    find_target_hwnd,
)
from core.input import (
    click_center,
    safe_click,
    scroll_at,
    press_esc,
    click_point,
    send_escape,
    ratio_to_client,
)

# ── 매처 ──────────────────────────────────────────────────
from core.matcher import (
    WeaponState,
    CheckFlag,
    EquipSlotFlag,
    match_student_texture,
    is_lobby,
    is_student_menu,
    detect_weapon_state,
    read_skill_check,
    read_equip_check,
    read_equip_check_inside,
    read_equip_slot_flag,
    read_stat_value,
    read_student_star_v5,
    read_weapon_star_v5,
    read_skill,
    read_equip_tier,
    read_equip_level,
    read_weapon_level,
    read_student_level_v5,
)

import core.ocr as ocr
import core.student_meta as student_meta
from core.item_names import correct_item_name


# ══════════════════════════════════════════════════════════
# 상수
# ══════════════════════════════════════════════════════════

MAX_SCROLLS          = 60
SCROLL_ITEM          = -3
SCROLL_EQUIP         = -2
SAME_THRESH          = 0.97
STUDENT_MENU_WAIT    = 3.0
MAX_CONSECUTIVE_DUP  = 3
MAX_STUDENT_LEVEL    = 90
STAT_UNLOCK_LEVEL    = 90
STAT_UNLOCK_STAR     = 5
DETAIL_READY_SCORE   = 0.40
DETAIL_READY_WAIT    = 3.5
LOBBY_EXIT_WAIT      = 3.0

# retry 정책
RETRY_IDENTIFY   = 2      # 학생 식별 최대 시도
RETRY_CAPTURE    = 2      # 캡처 실패 시 재시도
DELAY_AFTER_CLICK = 0.22  # 슬롯 클릭 후 대기
DELAY_TAB_SWITCH  = 0.45  # 탭 전환 후 대기
DELAY_NEXT        = 0.90  # 다음 학생 버튼 후 대기
DELAY_ESC         = 0.35  # ESC 후 대기


# ══════════════════════════════════════════════════════════
# 데이터 클래스
# ══════════════════════════════════════════════════════════

@dataclass
class ItemEntry:
    name:     Optional[str]
    quantity: Optional[str]
    source:   str = "item"
    index:    int = 0

    def key(self) -> str:
        return f"{self.name}_{self.source}_{self.index}"


# ══════════════════════════════════════════════════════════
# 필드 메타정보 — 값과 출처/상태 분리
# ══════════════════════════════════════════════════════════

class FieldStatus:
    """
    필드 획득 상태 상수.

    ok          : 정상 인식
    inferred    : 다른 값에서 추론 (예: 무기 보유 → 5★)
    uncertain   : 인식했지만 score 낮음 (RecognitionResult.uncertain=True)
    failed      : 인식 시도했으나 실패 (None 저장)
    skipped     : 조건 미충족으로 시도하지 않음
    region_missing : region 정의 없음
    """
    OK              = "ok"
    INFERRED        = "inferred"
    UNCERTAIN       = "uncertain"
    FAILED          = "failed"
    SKIPPED         = "skipped"
    REGION_MISSING  = "region_missing"


class FieldSource:
    """
    필드 획득 방법 상수.

    template    : 템플릿 매칭
    ocr         : OCR (easyocr)
    inferred    : 다른 필드에서 논리적 추론
    cached      : 이전 스캔 캐시에서 복사 (만렙 스킵)
    default     : 기본값 (fallback)
    """
    TEMPLATE = "template"
    OCR      = "ocr"
    INFERRED = "inferred"
    CACHED   = "cached"
    DEFAULT  = "default"


@dataclass
class FieldMeta:
    """
    단일 필드의 메타정보.

    Attributes
    ----------
    status  : FieldStatus 상수 — 어떤 상태로 얻었는지
    source  : FieldSource 상수 — 어떤 방법으로 얻었는지
    score   : 인식 점수 (0.0~1.0). 템플릿/OCR 외 경우 None
    note    : 자유 텍스트 (추론 근거, 실패 이유 등)
    """
    status: str            = FieldStatus.OK
    source: str            = FieldSource.TEMPLATE
    score:  Optional[float] = None
    note:   str            = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "source": self.source,
            "score":  round(self.score, 3) if self.score is not None else None,
            "note":   self.note,
        }

    @classmethod
    def ok(cls, source: str, score: Optional[float] = None) -> "FieldMeta":
        return cls(status=FieldStatus.OK, source=source, score=score)

    @classmethod
    def inferred(cls, note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.INFERRED,
                   source=FieldSource.INFERRED, note=note)

    @classmethod
    def uncertain(cls, source: str, score: Optional[float] = None,
                  note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.UNCERTAIN,
                   source=source, score=score, note=note)

    @classmethod
    def failed(cls, source: str, note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.FAILED, source=source, note=note)

    @classmethod
    def skipped(cls, note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.SKIPPED,
                   source=FieldSource.DEFAULT, note=note)

    @classmethod
    def region_missing(cls, note: str = "") -> "FieldMeta":
        return cls(status=FieldStatus.REGION_MISSING,
                   source=FieldSource.DEFAULT, note=note)


# ── 스캔 상태 ─────────────────────────────────────────────

class ScanState:
    """
    StudentEntry 의 현재 확정 상태.

    TEMP      : 스캔 진행 중 (각 단계가 채워가는 중)
    PARTIAL   : 일부 단계 실패 후 저장된 불완전 엔트리
    COMMITTED : 검증 통과 후 확정된 완성 엔트리
    SKIPPED   : 만렙 스킵 (이전 데이터 재활용)
    FAILED    : 식별 자체 실패 — 저장하지 않음
    """
    TEMP      = "temp"
    PARTIAL   = "partial"
    COMMITTED = "committed"
    SKIPPED   = "skipped"
    FAILED    = "failed"


@dataclass
class StudentEntry:
    student_id:   Optional[str] = None
    display_name: Optional[str] = None
    level:        Optional[int] = None
    student_star: Optional[int] = None
    # 무기
    weapon_state: Optional[WeaponState] = None
    weapon_star:  Optional[int]         = None
    weapon_level: Optional[int]         = None
    # 스킬
    ex_skill: Optional[int] = None
    skill1:   Optional[int] = None
    skill2:   Optional[int] = None
    skill3:   Optional[int] = None
    # 장비 티어
    equip1:   Optional[str] = None
    equip2:   Optional[str] = None
    equip3:   Optional[str] = None
    equip4:   Optional[str] = None
    # 장비 레벨
    equip1_level: Optional[int] = None
    equip2_level: Optional[int] = None
    equip3_level: Optional[int] = None
    # 스탯
    stat_hp:   Optional[int] = None
    stat_atk:  Optional[int] = None
    stat_heal: Optional[int] = None
    # 메타
    skipped:    bool = False
    scan_state: str  = ScanState.TEMP

    # ── 필드 메타 딕셔너리 ────────────────────────────────
    # {field_name: FieldMeta} — 값과 출처/상태를 분리 저장
    # 추적 대상 필드:
    #   level / student_star / weapon_state / weapon_star / weapon_level
    #   ex_skill / skill1~3 / equip1~4 / equip1~3_level
    #   stat_hp / stat_atk / stat_heal
    _meta: dict = field(default_factory=dict)

    def label(self) -> str:
        return self.display_name or self.student_id or "?"

    def is_committed(self) -> bool:
        return self.scan_state == ScanState.COMMITTED

    def is_partial(self) -> bool:
        return self.scan_state == ScanState.PARTIAL

    def set_meta(self, field_name: str, meta: FieldMeta) -> None:
        """필드 메타 설정."""
        self._meta[field_name] = meta

    def get_meta(self, field_name: str) -> Optional[FieldMeta]:
        """필드 메타 조회. 없으면 None."""
        return self._meta.get(field_name)

    def meta_summary(self) -> dict[str, dict]:
        """전체 메타 딕셔너리를 직렬화 가능한 형태로 반환."""
        return {k: v.to_dict() for k, v in self._meta.items()}

    def uncertain_fields(self) -> list[str]:
        """uncertain 상태인 필드 목록."""
        return [k for k, v in self._meta.items()
                if v.status == FieldStatus.UNCERTAIN]

    def failed_fields(self) -> list[str]:
        """failed 상태인 필드 목록."""
        return [k for k, v in self._meta.items()
                if v.status == FieldStatus.FAILED]

    def missing_fields(self) -> list[str]:
        """None 으로 남아 있는 필수 필드 목록."""
        required = [
            "level", "student_star", "weapon_state",
            "ex_skill", "skill1", "skill2", "skill3",
            "equip1", "equip2", "equip3",
            "equip1_level", "equip2_level", "equip3_level",
        ]
        return [f for f in required if getattr(self, f) is None]

    def confidence(self) -> float:
        """채워진 필드 비율 0.0~1.0."""
        required_all = [
            "level", "student_star", "weapon_state",
            "ex_skill", "skill1", "skill2", "skill3",
            "equip1", "equip2", "equip3",
            "equip1_level", "equip2_level", "equip3_level",
        ]
        filled = sum(1 for f in required_all if getattr(self, f) is not None)
        return round(filled / len(required_all), 3)

    def to_dict(self) -> dict:
        """
        저장용 직렬화.

        출력 구조:
          {
            "student_id": "shiroko",
            "level": 90,
            "level_status": "ok",
            "level_source": "template",
            "level_score": null,
            "student_star": 5,
            "student_star_status": "inferred",
            "student_star_source": "inferred",
            "student_star_note": "weapon_state → 5★ 확정",
            ...
            "scan_state": "committed",
            "confidence": 1.0,
            "_field_meta": { ... }   ← 전체 메타 백업
          }

        규칙:
          - 값 필드는 그대로 유지 (기존 코드 호환)
          - 각 추적 필드마다 {field}_status / {field}_source / {field}_score /
            {field}_note 를 플랫하게 추가
          - _field_meta 에 전체 메타 딕셔너리 중첩 저장 (풀 복원용)
        """
        ws = self.weapon_state
        d: dict = {
            "student_id":   self.student_id,
            "display_name": self.display_name,
            "level":        self.level,
            "student_star": self.student_star,
            "weapon_state": ws.value if ws else None,
            "weapon_star":  self.weapon_star,
            "weapon_level": self.weapon_level,
            "ex_skill":     self.ex_skill,
            "skill1":       self.skill1,
            "skill2":       self.skill2,
            "skill3":       self.skill3,
            "equip1":       self.equip1,
            "equip2":       self.equip2,
            "equip3":       self.equip3,
            "equip4":       self.equip4,
            "equip1_level": self.equip1_level,
            "equip2_level": self.equip2_level,
            "equip3_level": self.equip3_level,
            "stat_hp":      self.stat_hp,
            "stat_atk":     self.stat_atk,
            "stat_heal":    self.stat_heal,
            "skipped":      self.skipped,
            "scan_state":   self.scan_state,
            "confidence":   self.confidence(),
        }

        # 추적 필드별 플랫 메타 추가
        _TRACKED = [
            "level", "student_star",
            "weapon_state", "weapon_star", "weapon_level",
            "ex_skill", "skill1", "skill2", "skill3",
            "equip1", "equip2", "equip3", "equip4",
            "equip1_level", "equip2_level", "equip3_level",
            "stat_hp", "stat_atk", "stat_heal",
        ]
        for fname in _TRACKED:
            meta = self._meta.get(fname)
            if meta:
                d[f"{fname}_status"] = meta.status
                d[f"{fname}_source"] = meta.source
                if meta.score is not None:
                    d[f"{fname}_score"] = round(meta.score, 3)
                if meta.note:
                    d[f"{fname}_note"] = meta.note
            else:
                # 메타 없으면 값으로 상태 추론
                val = getattr(self, fname, None)
                d[f"{fname}_status"] = (
                    FieldStatus.OK if val is not None else FieldStatus.FAILED
                )

        # 전체 메타 백업 (복원용)
        if self._meta:
            d["_field_meta"] = self.meta_summary()

        return d

    @classmethod
    def from_dict(cls, d: dict) -> "StudentEntry":
        """
        저장 데이터 → StudentEntry 복원.
        _field_meta 가 있으면 메타도 복원.
        """
        ws_raw = d.get("weapon_state")
        try:
            ws = WeaponState(ws_raw) if ws_raw else None
        except ValueError:
            ws = None

        entry = cls(
            student_id=d.get("student_id"),
            display_name=d.get("display_name"),
            level=d.get("level"),
            student_star=d.get("student_star"),
            weapon_state=ws,
            weapon_star=d.get("weapon_star"),
            weapon_level=d.get("weapon_level"),
            ex_skill=d.get("ex_skill"),
            skill1=d.get("skill1"),
            skill2=d.get("skill2"),
            skill3=d.get("skill3"),
            equip1=d.get("equip1"),
            equip2=d.get("equip2"),
            equip3=d.get("equip3"),
            equip4=d.get("equip4"),
            equip1_level=d.get("equip1_level"),
            equip2_level=d.get("equip2_level"),
            equip3_level=d.get("equip3_level"),
            stat_hp=d.get("stat_hp"),
            stat_atk=d.get("stat_atk"),
            stat_heal=d.get("stat_heal"),
            skipped=d.get("skipped", False),
            scan_state=d.get("scan_state", ScanState.COMMITTED),
        )

        # 메타 복원
        raw_meta = d.get("_field_meta", {})
        for fname, md in raw_meta.items():
            entry.set_meta(fname, FieldMeta(
                status=md.get("status", FieldStatus.OK),
                source=md.get("source", FieldSource.TEMPLATE),
                score=md.get("score"),
                note=md.get("note", ""),
            ))

        return entry


@dataclass
class EntryCommitResult:
    """
    finalize_student_entry() 결과.

    Attributes
    ----------
    entry       : 처리된 StudentEntry
    committed   : True 이면 COMMITTED (results에 추가할 것)
    missing     : 비어 있는 필드 목록
    confidence  : 채움 비율 0.0~1.0
    reason      : partial / skip 이유 (디버그용)
    """
    entry:      StudentEntry
    committed:  bool
    missing:    list[str]
    confidence: float
    reason:     str = ""


@dataclass
class ScanResult:
    items:     list[ItemEntry]    = field(default_factory=list)
    equipment: list[ItemEntry]    = field(default_factory=list)
    students:  list[StudentEntry] = field(default_factory=list)
    resources: dict               = field(default_factory=dict)
    errors:    list[str]          = field(default_factory=list)


# ══════════════════════════════════════════════════════════
# 유틸
# ══════════════════════════════════════════════════════════

def _img_hash(img: Image.Image) -> str:
    small = img.convert("L").resize((16, 16))
    return hashlib.md5(small.tobytes()).hexdigest()


def _images_similar(a: Image.Image, b: Image.Image, thresh: float = SAME_THRESH) -> bool:
    try:
        a2 = np.array(a.convert("L").resize((64, 64))).flatten().astype(float)
        b2 = np.array(b.convert("L").resize((64, 64))).flatten().astype(float)
        return float(np.corrcoef(a2, b2)[0, 1]) >= thresh
    except Exception:
        return False


def _grid_region(slots: list[dict]) -> dict:
    return {
        "x1": min(s["x1"] for s in slots),
        "y1": min(s["y1"] for s in slots),
        "x2": max(s["x2"] for s in slots),
        "y2": max(s["y2"] for s in slots),
    }


def _dict_to_student_entry(d: dict) -> StudentEntry:
    ws_raw = d.get("weapon_state")
    try:
        ws = WeaponState(ws_raw) if ws_raw else None
    except ValueError:
        ws = None
    return StudentEntry(
        student_id=d.get("student_id"),
        display_name=d.get("display_name"),
        level=d.get("level"),
        student_star=d.get("student_star"),
        weapon_state=ws,
        weapon_star=d.get("weapon_star"),
        weapon_level=d.get("weapon_level"),
        ex_skill=d.get("ex_skill"),
        skill1=d.get("skill1"),
        skill2=d.get("skill2"),
        skill3=d.get("skill3"),
        equip1=d.get("equip1"),
        equip2=d.get("equip2"),
        equip3=d.get("equip3"),
        equip4=d.get("equip4"),
        equip1_level=d.get("equip1_level"),
        equip2_level=d.get("equip2_level"),
        equip3_level=d.get("equip3_level"),
        stat_hp=d.get("stat_hp"),
        stat_atk=d.get("stat_atk"),
        stat_heal=d.get("stat_heal"),
        skipped=True,
    )


# ══════════════════════════════════════════════════════════
# Scanner
# ══════════════════════════════════════════════════════════

class Scanner:

    def __init__(
        self,
        regions: dict,
        on_progress: Optional[Callable[[str], None]] = None,
        on_progress_state: Optional[Callable[[dict], None]] = None,
        maxed_ids:   Optional[set[str]]  = None,
        maxed_cache: Optional[dict[str, dict]] = None,
        student_total_hint: Optional[int] = None,
        autosave_manager = None,   # AutoSaveManager | None
    ):
        self.r             = regions
        self._on_progress  = on_progress
        self._on_progress_state = on_progress_state
        self._stop         = False
        self._maxed_ids    = frozenset(maxed_ids or [])
        self._maxed_cache: dict[str, dict] = maxed_cache or {}
        self._student_total_hint = student_total_hint if student_total_hint and student_total_hint > 0 else None
        self._asv          = autosave_manager   # AutoSaveManager (없으면 None)
        self._student_basic_img: Optional[Image.Image] = None

        if self._maxed_ids:
            self._info(f"⏭ 만렙 스킵 대상: {len(self._maxed_ids)}명")

    def stop(self) -> None:
        self._stop = True
        _log.info("스캔 중지 요청")

    def clear_stop(self) -> None:
        self._stop = False

    def _stop_requested(self) -> bool:
        return self._stop

    def _wait(self, seconds: float, step: float = 0.05) -> bool:
        end = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < end:
            if self._stop_requested():
                return False
            time.sleep(min(step, end - time.monotonic()))
        return not self._stop_requested()

    # ── 로그 헬퍼 ─────────────────────────────────────────
    # logger + UI 콜백을 동시에 처리

    def _debug(self, msg: str) -> None:
        _log.debug(msg)

    def _info(self, msg: str) -> None:
        _log.info(msg)
        if self._on_progress:
            self._on_progress(msg)

    def _emit_progress_state(
        self,
        *,
        current: int | None = None,
        total: int | None = None,
        note: str = "",
    ) -> None:
        if self._on_progress_state:
            self._on_progress_state(
                {
                    "current": current,
                    "total": total,
                    "note": note,
                }
            )

    def _warn(self, msg: str) -> None:
        _log.warning(msg)
        if self._on_progress:
            self._on_progress(f"⚠️ {msg}")

    def _error(self, msg: str) -> None:
        _log.error(msg)
        if self._on_progress:
            self._on_progress(f"❌ {msg}")

    # 하위 호환: self.log(msg) 호출 지점 처리
    @property
    def log(self):
        return self._info

    # ══════════════════════════════════════════════════════
    # 8-1. StudentEntry 갱신 흐름 — temp / finalize / commit
    # ══════════════════════════════════════════════════════

    def begin_student_scan(self, student_id: str) -> StudentEntry:
        """
        학생 1명 스캔 시작 — TEMP 상태 엔트리 생성.
        각 단계 함수는 이 temp 엔트리만 수정한다.
        원본 results 에는 아직 추가하지 않음.
        """
        entry = StudentEntry(
            student_id=student_id,
            display_name=student_meta.display_name(student_id),
            scan_state=ScanState.TEMP,
        )
        _log.debug(f"[TEMP] 시작: {entry.label()}")
        return entry

    def finalize_student_entry(
        self,
        entry:   StudentEntry,
        ctx:     "ScanCtx",
        *,
        partial_ok: bool = True,
    ) -> EntryCommitResult:
        """
        TEMP 엔트리 검증 — COMMITTED 또는 PARTIAL 상태 결정.

        검증 규칙:
          - student_id 없음    → FAILED (results에 추가 안 함)
          - 필수 필드 전부 있음 → COMMITTED
          - 일부 필드 누락
              partial_ok=True  → PARTIAL (results에 추가, 불완전 표시)
              partial_ok=False → FAILED

        Parameters
        ----------
        entry      : TEMP 상태 StudentEntry
        ctx        : ScanCtx (로그 컨텍스트)
        partial_ok : True 이면 일부 누락 허용, False 이면 엄격 검증

        Returns
        -------
        EntryCommitResult
        """
        if not entry.student_id:
            entry.scan_state = ScanState.FAILED
            return EntryCommitResult(
                entry=entry, committed=False,
                missing=[], confidence=0.0,
                reason="student_id 없음",
            )

        missing    = entry.missing_fields()
        confidence = entry.confidence()

        if not missing:
            # 모든 필수 필드 채워짐 → COMMITTED
            entry.scan_state = ScanState.COMMITTED

            # uncertain 필드가 있으면 경고
            uncertain = entry.uncertain_fields()
            if uncertain:
                _log.warning(
                    f"{ctx} ⚠️ COMMITTED 하지만 불확실 필드 있음: {uncertain}"
                )
            else:
                _log.info(
                    f"{ctx} ✅ COMMITTED "
                    f"(confidence={confidence:.2f})"
                )
            return EntryCommitResult(
                entry=entry, committed=True,
                missing=[], confidence=confidence,
            )

        # 일부 누락
        if partial_ok:
            entry.scan_state = ScanState.PARTIAL
            _log.warning(
                f"{ctx} ⚠️ PARTIAL "
                f"(confidence={confidence:.2f} missing={missing})"
            )
            return EntryCommitResult(
                entry=entry, committed=True,   # results에 추가하되 PARTIAL 표시
                missing=missing, confidence=confidence,
                reason=f"missing={missing}",
            )

        # 엄격 모드 — 누락 있으면 FAILED
        entry.scan_state = ScanState.FAILED
        _log.warning(
            f"{ctx} ❌ FAILED (strict) "
            f"(confidence={confidence:.2f} missing={missing})"
        )
        return EntryCommitResult(
            entry=entry, committed=False,
            missing=missing, confidence=confidence,
            reason=f"strict_fail missing={missing}",
        )

    def commit_student_entry(
        self,
        result:  EntryCommitResult,
        results: list[StudentEntry],
        idx:     int,
    ) -> bool:
        """
        EntryCommitResult 를 최종 results 목록에 추가.
        committed=False 이면 추가하지 않고 로그만 남김.

        Returns
        -------
        True  = results 에 추가됨
        False = 폐기됨
        """
        entry = result.entry
        if not result.committed:
            _log.warning(
                f"[{idx+1:>3}] 엔트리 폐기: {entry.label()} "
                f"— {result.reason}"
            )
            return False

        results.append(entry)

        state_tag = "COMMITTED" if entry.is_committed() else "PARTIAL"
        _log.info(
            f"[{idx+1:>3}] ✓ {state_tag}: {entry.label()} "
            f"(confidence={result.confidence:.2f})"
        )
        if result.missing:
            self._warn(
                f"  [{idx+1:>3}] {entry.label()} — "
                f"누락 필드: {result.missing}"
            )
        return True

    # ── 내부 유틸 ─────────────────────────────────────────

    def _capture(self, retry: int = RETRY_CAPTURE) -> Optional[Image.Image]:
        """캡처 + retry. 실패 시 None."""
        for i in range(retry + 1):
            if self._stop_requested():
                return None
            img = capture_window_background()
            if img is not None:
                return img
            if i < retry:
                _log.debug(f"캡처 재시도 ({i+1}/{retry})")
                if not self._wait(0.1):
                    return None
        self._error("캡처 실패")
        return None

    def _invalidate_student_basic_capture(self) -> None:
        self._student_basic_img = None

    def _get_student_basic_capture(
        self,
        *,
        refresh: bool = False,
    ) -> Optional[Image.Image]:
        if refresh or self._student_basic_img is None:
            img = self._capture()
            if img is None:
                return None
            self._student_basic_img = img
        return self._student_basic_img

    def _adjust_region(
        self,
        region: dict,
        *,
        left: float = 0.0,
        top: float = 0.0,
        right: float = 0.0,
        bottom: float = 0.0,
    ) -> dict:
        return {
            "x1": max(0.0, min(1.0, region["x1"] + left)),
            "y1": max(0.0, min(1.0, region["y1"] + top)),
            "x2": max(0.0, min(1.0, region["x2"] + right)),
            "y2": max(0.0, min(1.0, region["y2"] + bottom)),
        }

    def _is_lobby_capture(self, img: Optional[Image.Image]) -> bool:
        detect_r = self.r.get("lobby", {}).get("detect_flag")
        if img is None or not detect_r:
            return False
        roi = crop_region(img, detect_r)
        return is_lobby(roi, {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0})

    def _is_student_menu_capture(self, img: Optional[Image.Image]) -> bool:
        detect_r = self.r.get("student_menu", {}).get("menu_detect_flag")
        if img is None or not detect_r:
            return False
        roi = crop_region(img, detect_r)
        return is_student_menu(roi, {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0})

    def _student_detail_score(self, img: Optional[Image.Image]) -> float:
        texture_r = self.r.get("student", {}).get("student_texture_region")
        if img is None or not texture_r:
            return 0.0
        crop = crop_region(img, texture_r)
        _, score = match_student_texture(crop)
        return score

    def _wait_for_student_menu_state(
        self,
        expected_in_student_menu: bool,
        *,
        timeout: float,
        poll: float = 0.25,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop_requested():
                return False
            img = self._capture()
            if img is not None and self._is_student_menu_capture(img) == expected_in_student_menu:
                self._invalidate_student_basic_capture()
                return True
            if not self._wait(poll):
                return False
        return False

    def _wait_for_student_detail(
        self,
        *,
        timeout: float = DETAIL_READY_WAIT,
        poll: float = 0.25,
    ) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._stop_requested():
                return False
            img = self._capture()
            score = self._student_detail_score(img)
            _log.debug(f"[detail_wait] texture_score={score:.3f}")
            if score >= DETAIL_READY_SCORE:
                self._student_basic_img = img
                return True
            if not self._wait(poll):
                return False
        return False

    def _recover_first_student_entry(self) -> bool:
        _log.warning("첫 학생 진입 복구 루틴 시작")
        img = self._capture()
        if img is not None:
            if self._is_lobby_capture(img):
                _log.warning("복구 감지: 아직 로비 화면에 머무름")
                if not self.enter_student_menu():
                    return False
            elif self._is_student_menu_capture(img):
                _log.warning("복구 감지: 학생 메뉴 화면에 머무름")
        self._invalidate_student_basic_capture()
        return self.enter_first_student()

    def _rect(self) -> Optional[tuple[int, int, int, int]]:
        return get_window_rect()

    def _hwnd(self) -> Optional[int]:
        return find_target_hwnd()

    def _retry(
        self,
        fn: Callable,
        max_attempts: int = 2,
        delay: float = 0.3,
        label: str = "",
    ):
        """
        fn() 을 최대 max_attempts 회 시도.
        None 이 아닌 값 반환 시 즉시 반환.
        모두 실패 시 None 반환.
        """
        for i in range(max_attempts):
            if self._stop_requested():
                return None
            result = fn()
            if result is not None:
                return result
            if i < max_attempts - 1:
                self.log(f"  ↩ {label} 재시도 ({i+2}/{max_attempts})")
                if not self._wait(delay):
                    return None
        return None

    # ── UI 전환 중앙화 ────────────────────────────────────

    def _click_r(self, region: dict, label: str = "") -> bool:
        """region 중심 클릭 (HWND 기반 우선)."""
        rect = self._rect()
        if rect is None:
            return False
        hwnd = self._hwnd()
        if hwnd:
            rx = (region["x1"] + region["x2"]) / 2
            ry = (region["y1"] + region["y2"]) / 2
            cx, cy = ratio_to_client(rect, rx, ry)
            return click_point(hwnd, cx, cy, label=label)
        return click_center(rect, region, label)

    def _tab(self, region_key: str, delay: float = DELAY_TAB_SWITCH) -> bool:
        """탭 버튼 클릭 + 대기."""
        sr = self.r["student"]
        region = sr.get(region_key)
        if not region:
            self.log(f"  ⚠️ {region_key} 미정의 — 탭 이동 생략")
            return False
        ok = self._click_r(region, region_key)
        if delay > 0:
            if not self._wait(delay):
                return False
        return ok

    def _esc(self, n: int = 1, delay: float = DELAY_ESC) -> None:
        """ESC n회 전송."""
        hwnd = self._hwnd()
        for _ in range(n):
            if self._stop_requested():
                return
            if hwnd:
                send_escape(hwnd, delay=delay)
            else:
                press_esc()

    def _restore_basic_tab(self) -> None:
        """기본 정보 탭으로 복귀."""
        sr = self.r["student"]
        if "basic_info_button" in sr:
            self._click_r(sr["basic_info_button"], "basic_info_tab")
            self._wait(0.3)
        else:
            self._esc()

    # ══════════════════════════════════════════════════════
    # 재화 스캔
    # ══════════════════════════════════════════════════════

    def scan_resources(self) -> dict:
        self.log("💰 재화 스캔 중...")
        img = self._capture()
        if img is None:
            return {}

        lobby_r = self.r["lobby"]
        result: dict = {}

        ocr.load()
        try:
            for key, rk in [("크레딧", "credit_region"),
                             ("청휘석", "pyroxene_region")]:
                try:
                    crop = crop_region(img, lobby_r[rk])
                    result[key] = ocr.read_item_count(crop)
                except Exception as e:
                    result[key] = None
                    _log.warning(f"재화 OCR 실패 ({key}): {type(e).__name__}: {e}")
        finally:
            ocr.unload()

        self.log(f"💰 청휘석={result.get('청휘석','-')}  크레딧={result.get('크레딧','-')}")
        return result

    # ══════════════════════════════════════════════════════
    # 그리드 스캔 (아이템 / 장비 공통)
    # ══════════════════════════════════════════════════════

    def _open_menu(self) -> bool:
        rect = self._rect()
        if not rect:
            return False
        self.log("📂 메뉴 열기...")
        self._click_r(self.r["lobby"]["menu_button"], "menu_button")
        return self._wait(0.7)

    def _go_to(self, btn_key: str, label: str) -> bool:
        btn = self.r["menu"].get(btn_key)
        if not btn:
            self.log(f"❌ {label} 버튼 설정 없음")
            return False
        self.log(f"  → {label} 진입...")
        self._click_r(btn, label)
        return self._wait(1.0)

    def _return_lobby(self) -> None:
        self.log("🏠 로비 복귀...")
        self._esc()

    def _scan_grid(
        self,
        section: str,
        source: str,
        scroll_amount: int,
    ) -> list[ItemEntry]:
        r_sec   = self.r[section]
        slots   = r_sec["grid_slots"]
        name_r  = r_sec["name_region"]
        count_r = r_sec["count_region"]
        grid_r  = _grid_region(slots)

        rect = self._rect()
        if not rect:
            self.log("❌ 창 없음")
            return []

        scroll_cx = (grid_r["x1"] + grid_r["x2"]) / 2
        scroll_cy = (grid_r["y1"] + grid_r["y2"]) / 2

        items:       list[ItemEntry] = []
        seen_keys:   set[str]        = set()
        seen_hashes: list[str]       = []
        icon = "📦" if source == "item" else "🔧"

        self.log(f"{icon} 그리드 스캔 시작 (슬롯 {len(slots)}개)")

        for scroll_i in range(MAX_SCROLLS):
            if self._stop_requested():
                break

            # ── 1회 캡처 → 이후 crop 재사용 ──────────────
            img = self._capture()
            if img is None:
                break

            grid_crop = crop_region(img, grid_r)
            cur_hash  = _img_hash(grid_crop)

            if cur_hash in seen_hashes:
                self.log(f"  🔁 화면 반복 감지 → 스캔 종료 ({len(items)}개)")
                break
            seen_hashes.append(cur_hash)
            if len(seen_hashes) > 10:
                seen_hashes.pop(0)

            new_this = 0
            for slot in slots:
                if self._stop_requested():
                    break

                click_ry = slot["y1"] + (slot["y2"] - slot["y1"]) * 0.4
                safe_click(rect, slot["cx"], click_ry, f"{source}_slot")
                if not self._wait(DELAY_AFTER_CLICK):
                    break

                # 슬롯 클릭 후 1회 캡처
                img2 = self._capture()
                if img2 is None:
                    continue

                # 이름/수량 crop 재사용
                name_crop  = crop_region(img2, name_r)
                count_crop = crop_region(img2, count_r)

                name  = ocr.read_item_name(name_crop)
                count = ocr.read_item_count(count_crop)
                if not name:
                    continue

                entry = ItemEntry(
                    name=name,
                    quantity=count,
                    source=source,
                    index=len(items),
                )
                k = entry.key()
                if k not in seen_keys:
                    seen_keys.add(k)
                    items.append(entry)
                    new_this += 1
                    self.log(f"  {icon} [{len(items):>3}] {name}  ×{count}")

            self.log(f"  스크롤 {scroll_i+1}회차: 신규 {new_this}개 / 누계 {len(items)}개")

            # 스크롤 전 기준 캡처
            before_img = self._capture()
            before = crop_region(before_img, grid_r) if before_img else None

            scroll_at(rect, scroll_cx, scroll_cy, scroll_amount)
            if not self._wait(0.15):
                break

            after_img = self._capture()
            if after_img is None:
                break
            after = crop_region(after_img, grid_r)

            if before is not None and _images_similar(before, after):
                self.log(f"  ✅ 스크롤 끝 — 총 {len(items)}개")
                break
            if new_this == 0 and scroll_i >= 2:
                self.log(f"  ✅ 신규 없음 — 총 {len(items)}개")
                break

        return items

    # ── 아이템 / 장비 공개 스캔 ──────────────────────────

    def scan_items(self) -> list[ItemEntry]:
        self.log("━━━ 📦 아이템 스캔 시작 ━━━")
        try:
            ocr.load()
            if not self._open_menu():
                return []
            if not self._go_to("item_entry_button", "아이템"):
                return []
            if not self._wait(0.5):
                return []
            result = self._scan_grid("item", "item", SCROLL_ITEM)
            self.log(f"━━━ 📦 아이템 스캔 완료: {len(result)}개 ━━━")
            return result
        except Exception as e:
            self.log(f"❌ 아이템 스캔 오류: {e}")
            return []
        finally:
            self._return_lobby()
            ocr.unload()

    def scan_equipment(self) -> list[ItemEntry]:
        self.log("━━━ 🔧 장비 스캔 시작 ━━━")
        try:
            ocr.load()
            if not self._open_menu():
                return []
            if not self._go_to("equipment_entry_button", "장비"):
                return []
            if not self._wait(0.5):
                return []
            result = self._scan_grid("equipment", "equipment", SCROLL_EQUIP)
            self.log(f"━━━ 🔧 장비 스캔 완료: {len(result)}개 ━━━")
            return result
        except Exception as e:
            self.log(f"❌ 장비 스캔 오류: {e}")
            return []
        finally:
            self._return_lobby()
            ocr.unload()

    # ══════════════════════════════════════════════════════
    # 학생 스캔 — 파이프라인
    # ══════════════════════════════════════════════════════

    def scan_students(self) -> list[StudentEntry]:
        return self.scan_students_v5()

    def scan_current_student(self) -> list[StudentEntry]:
        self._info("━━━ 👤 현재 학생 스캔 시작 ━━━")
        self._emit_progress_state(current=0, total=1, note="현재 학생")
        results: list[StudentEntry] = []

        try:
            sid = self.identify_student(0)
            if sid is None:
                self._warn("[현재 학생] 식별 실패")
                return []

            if sid in self._maxed_ids:
                entry = self._make_skipped_entry(sid)
                results.append(entry)
                self._emit_progress_state(current=1, total=1, note="현재 학생")
                self._info(f"  ⏭ {entry.label()} — 만렙 스킵")
                return results

            ctx = ScanCtx(idx=1, student_id=sid)
            entry = self.begin_student_scan(sid)

            self.read_skills(entry)
            if self._stop_requested():
                return results
            self.read_weapon(entry)
            if self._stop_requested():
                return results
            self.read_equipment(entry)
            if self._stop_requested():
                return results
            self.read_level(entry)
            if self._stop_requested():
                return results
            self.read_student_star(entry)
            if self._stop_requested():
                return results
            self.read_stats(entry)
            if self._stop_requested():
                return results

            commit_result = self.finalize_student_entry(entry, ctx, partial_ok=True)
            added = self.commit_student_entry(commit_result, results, 0)
            if added:
                self._emit_progress_state(current=1, total=1, note="현재 학생")
                self._log_student(entry, 0)
                if self._asv:
                    self._asv.on_student_committed(entry)
        except Exception as e:
            _log.exception(f"현재 학생 스캔 중 예외 발생: {e}")
            self._error(f"현재 학생 스캔 오류: {e}")
            if self._asv:
                partial = ScanResult(students=list(results))
                self._asv.emergency_save(partial, {})
        finally:
            self._restore_basic_tab()
            if self._asv:
                self._asv.log_stats()

        summary = f"현재 학생 스캔 완료: 총 {len(results)}명"
        self._emit_progress_state(current=len(results), total=1, note="현재 학생")
        _log.info(summary)
        self._info(f"━━━ 👤 {summary} ━━━")
        return results

    def scan_students_v5(self) -> list[StudentEntry]:
        log_section(_log, "학생 스캔 시작 (V6)")
        self._info("━━━ 👩 학생 스캔 시작 (V6) ━━━")
        results:       list[StudentEntry] = []
        skipped_count  = 0
        scanned_count  = 0
        self._emit_progress_state(
            current=0,
            total=self._student_total_hint,
            note="학생 스캔",
        )

        try:
            if not self.enter_student_menu():
                return []
            if not self.enter_first_student():
                return []

            seen_ids:        set[str]       = set()
            consecutive_dup: int            = 0
            prev_id:         Optional[str]  = None

            for idx in range(500):
                if self._stop_requested():
                    _log.info("스캔 중지 플래그 감지 → 루프 종료")
                    break

                # ── 1. 학생 식별 ──────────────────────────
                _log.debug(f"[{idx+1}] 학생 식별 시작")
                sid = self.identify_student(idx)
                if sid is None:
                    self._warn(f"[{idx+1}] 식별 실패 → 스캔 종료")
                    break

                # ── 2. 중복 / 종료 판정 ───────────────────
                if sid == prev_id:
                    consecutive_dup += 1
                    _log.info(
                        f"[{idx+1}] 동일 학생 연속: {sid} "
                        f"({consecutive_dup}/{MAX_CONSECUTIVE_DUP})"
                    )
                    if consecutive_dup >= MAX_CONSECUTIVE_DUP:
                        _log.info("연속 동일 → 마지막 학생 판정, 스캔 종료")
                        self._info("  ✅ 연속 동일 → 마지막 학생, 종료")
                        break
                    self._restore_basic_tab()
                    self.go_next_student()
                    continue

                consecutive_dup = 0
                prev_id = sid

                if sid in seen_ids:
                    _log.info(f"[{idx+1}] 이미 스캔됨: {sid} → 종료")
                    self._info(f"  🔁 이미 스캔됨: {sid} — 종료")
                    break
                seen_ids.add(sid)

                # ── 3. 만렙 스킵 ──────────────────────────
                if sid in self._maxed_ids:
                    entry = self._make_skipped_entry(sid)
                    results.append(entry)
                    skipped_count += 1
                    self._emit_progress_state(
                        current=len(results),
                        total=self._student_total_hint,
                        note="학생 스캔",
                    )
                    _log.info(f"[{idx+1:>3}] {entry.label()} — 만렙 스킵")
                    self._info(f"  ⏭ [{idx+1:>3}] {entry.label()} — 만렙 스킵")
                    self._restore_basic_tab()
                    self.go_next_student()
                    continue

                # ── 4. 세부 스캔 ──────────────────────────
                _log.info(f"[{idx+1:>3}] ▶ 스캔 시작: {sid}")
                ctx = ScanCtx(idx=idx+1, student_id=sid)

                # TEMP 엔트리 생성 — 이 시점부터 각 단계가 채워넣음
                entry = self.begin_student_scan(sid)

                # 각 단계: 실패해도 나머지 진행 (skip 정책)
                # 단계마다 entry.scan_state 는 여전히 TEMP
                self.read_skills(entry)
                if self._stop_requested():
                    break
                self.read_weapon(entry)
                if self._stop_requested():
                    break
                self.read_equipment(entry)
                if self._stop_requested():
                    break
                self.read_level(entry)
                if self._stop_requested():
                    break
                self.read_student_star(entry)
                if self._stop_requested():
                    break
                self.read_stats(entry)
                if self._stop_requested():
                    break

                # TEMP → COMMITTED or PARTIAL 검증
                commit_result = self.finalize_student_entry(
                    entry, ctx, partial_ok=True
                )

                # 검증 결과에 따라 results 에 추가 (FAILED 이면 폐기)
                added = self.commit_student_entry(commit_result, results, idx)
                if added:
                    scanned_count += 1
                    self._emit_progress_state(
                        current=len(results),
                        total=self._student_total_hint,
                        note="학생 스캔",
                    )
                    self._log_student(entry, len(results) - 1)
                    # ── per-student autosave ──────────────
                    if self._asv:
                        self._asv.on_student_committed(entry)

                self._restore_basic_tab()
                self.go_next_student()

        except Exception as e:
            _log.exception(f"학생 스캔 중 예외 발생: {e}")
            self._error(f"학생 스캔 오류: {e}")
            # ── emergency save ────────────────────────────
            if self._asv:
                partial = ScanResult(students=list(results))
                self._asv.emergency_save(partial, {})
        finally:
            self._return_lobby()
            # ── autosave 통계 로그 ────────────────────────
            if self._asv:
                self._asv.log_stats()

        summary = (
            f"학생 스캔 완료: 총 {len(results)}명 "
            f"(스캔:{scanned_count} / 스킵:{skipped_count})"
        )
        self._emit_progress_state(
            current=len(results),
            total=max(self._student_total_hint or 0, len(results)) or None,
            note="학생 스캔",
        )
        _log.info(summary)
        self._info(f"━━━ 👩 {summary} ━━━")
        return results

    # ── 만렙 스킵 헬퍼 ───────────────────────────────────

    def _make_skipped_entry(self, student_id: str) -> StudentEntry:
        if student_id in self._maxed_cache:
            entry = _dict_to_student_entry(self._maxed_cache[student_id])
        else:
            entry = StudentEntry(
                student_id=student_id,
                display_name=student_meta.display_name(student_id),
                skipped=True,
            )
        entry.skipped = True
        return entry

    # ══════════════════════════════════════════════════════
    # 파이프라인 단계 함수
    # ══════════════════════════════════════════════════════

    # ── 네비게이션 ────────────────────────────────────────

    def enter_student_menu(self) -> bool:
        self.log("  학생 메뉴 진입...")
        btn = self.r["lobby"].get("student_menu_button")
        if not btn:
            self.log("  ⚠️ student_menu_button 미정의")
            return False

        attempts = [
            btn,
            self._adjust_region(btn, left=-0.01, top=-0.01, right=0.04, bottom=0.01),
        ]
        for attempt, region in enumerate(attempts, start=1):
            self._click_r(region, f"student_menu_{attempt}")
            if self._wait_for_student_menu_state(True, timeout=LOBBY_EXIT_WAIT):
                return self._wait(0.6)
            if attempt < len(attempts):
                self.log(f"  학생 메뉴 재시도... ({attempt+1}/{len(attempts)})")
        return False

    def enter_first_student(self) -> bool:
        self.log("  첫 학생 선택...")
        btn = self.r["student_menu"].get("first_student_button")
        if not btn:
            self.log("  ⚠️ first_student_button 미정의")
            return False

        attempts = [
            btn,
            self._adjust_region(btn, left=-0.01, top=-0.02, right=0.08, bottom=0.02),
        ]
        for attempt, region in enumerate(attempts, start=1):
            self._click_r(region, f"first_student_{attempt}")
            if self._wait_for_student_detail():
                return True
            if attempt < len(attempts):
                self.log(f"  첫 학생 재선택... ({attempt+1}/{len(attempts)})")
        return False

    def go_next_student(self) -> bool:
        btn = self.r["student"].get("next_student_button")
        if not btn:
            self.log("  ⚠️ next_student_button 미정의")
            return False
        self._click_r(btn, "next_student")
        return self._wait(DELAY_NEXT)

    # ── 학생 식별 ─────────────────────────────────────────

    def identify_student(self, idx: int = 0) -> Optional[str]:
        """
        텍스처 매칭으로 학생 식별.
        RETRY_IDENTIFY 회 시도 후 실패 시 None.
        """
        sr        = self.r["student"]
        texture_r = sr.get("student_texture_region")
        ctx       = ScanCtx(idx=idx+1, step="identify")

        if not texture_r:
            _log.warning(f"{ctx} student_texture_region 미정의 — 식별 불가")
            return None

        def _try() -> Optional[str]:
            img = self._get_student_basic_capture(refresh=True)
            if img is None:
                return None
            crop = crop_region(img, texture_r)
            sid, score = match_student_texture(crop)
            if sid is not None:
                _log.info(
                    f"{ctx} 식별 성공: {student_meta.display_name(sid)} "
                    f"(score={score:.3f})"
                )
                self._info(f"  🔍 [{idx+1}] {student_meta.display_name(sid)} (score={score:.3f})")
                return sid
            # 식별 실패 → 디버그 덤프
            _log.debug(f"{ctx} 텍스처 식별 미달 (score={score:.3f})")
            dump_roi(crop, "identify_fail", score=score, reason="below_thresh")
            if self._asv:
                self._asv.on_step_error("identify")
            self._warn(f"[{idx+1}] 텍스처 식별 실패 (score={score:.3f})")
            return None

        sid = self._retry(_try, max_attempts=RETRY_IDENTIFY, delay=0.6, label="식별")
        if sid is not None or idx != 0:
            return sid

        _log.warning(f"{ctx} 첫 학생 식별 실패 → 진입 복구 시도")
        self._warn(f"[{idx+1}] 첫 학생 진입 복구 시도")
        if not self._recover_first_student_entry():
            return None
        self._restore_basic_tab()
        self._invalidate_student_basic_capture()
        return self._retry(_try, max_attempts=RETRY_IDENTIFY, delay=0.6, label="식별 복구")

    # ── 스킬 스캔 ─────────────────────────────────────────

    def read_skills(self, entry: StudentEntry) -> None:
        """
        스킬 메뉴 진입 → 캡처 1회 → 4개 스킬 crop 재사용.
        실패 시 해당 필드 None 유지 (skip).
        """
        ctx = ScanCtx(student_id=entry.student_id, step="read_skills")

        if not self._tab("skill_menu_button"):
            _log.warning(f"{ctx} 스킬 탭 이동 실패")
            return

        img = self._capture()
        if img is None:
            _log.warning(f"{ctx} 캡처 실패")
            self._esc()
            return

        sr      = self.r["student"]
        check_r = sr.get("skill_all_view_check_region")

        if check_r:
            if read_skill_check(crop_region(img, check_r)) == CheckFlag.FALSE:
                self.log("  🔘 스킬 일괄성장 체크 클릭")
                self._click_r(check_r, "skill_check")
                if not self._wait(0.3):
                    self._esc()
                    return
                img = self._capture()
                if img is None:
                    _log.warning(f"{ctx} 체크 후 재캡처 실패")
                    self._esc()
                    return

        for field_name, region_key, tmpl_key in [
            ("ex_skill", "EX_skill", "EX_Skill"),
            ("skill1",   "Skill_1",  "Skill1"),
            ("skill2",   "Skill_2",  "Skill2"),
            ("skill3",   "Skill_3",  "Skill3"),
        ]:
            region = sr.get(region_key)
            if region is None:
                _log.warning(f"{ctx.with_step(field_name)} region 미정의 — 생략")
                entry.set_meta(field_name, FieldMeta.region_missing(region_key))
                continue
            crop = crop_region(img, region)
            raw  = read_skill(crop, tmpl_key)
            try:
                setattr(entry, field_name, int(raw))
                entry.set_meta(field_name, FieldMeta.ok(FieldSource.TEMPLATE))
            except (TypeError, ValueError):
                _log.debug(f"{ctx.with_step(field_name)} 값 변환 실패 (raw={raw!r})")
                dump_roi(crop, f"skill_{field_name}", reason="convert_fail")
                setattr(entry, field_name, None)
                entry.set_meta(field_name,
                               FieldMeta.failed(FieldSource.TEMPLATE,
                                                note=f"raw={raw!r}"))
                if self._asv:
                    self._asv.on_step_error("read_skills", entry.student_id or "")

        self.log(
            f"  🎓 스킬: EX={entry.ex_skill} "
            f"S1={entry.skill1} S2={entry.skill2} S3={entry.skill3}"
        )
        self._esc()

    # ── 무기 스캔 ─────────────────────────────────────────

    def read_weapon(self, entry: StudentEntry) -> None:
        """
        기본 화면에서 무기 감지 플래그 crop → 상태 판정.
        WEAPON_EQUIPPED 일 때만 무기 메뉴 진입.
        """
        ctx      = ScanCtx(student_id=entry.student_id, step="read_weapon")
        sr       = self.r["student"]
        weapon_r = sr.get("weapon_detect_flag_region") or sr.get("weapon_unlocked_flag")
        if not weapon_r:
            self.log("  ⚠️ weapon_detect_flag_region 미정의 → NO_WEAPON_SYSTEM")
            entry.weapon_state = WeaponState.NO_WEAPON_SYSTEM
            entry.set_meta("weapon_state", FieldMeta.region_missing("weapon_detect_flag_region"))
            return

        img = self._get_student_basic_capture()
        if img is None:
            entry.weapon_state = WeaponState.NO_WEAPON_SYSTEM
            entry.set_meta("weapon_state", FieldMeta.failed(FieldSource.TEMPLATE, "capture_fail"))
            return

        state, score = detect_weapon_state(crop_region(img, weapon_r))
        entry.weapon_state = state

        if score < 0.60:
            entry.set_meta("weapon_state",
                           FieldMeta.uncertain(FieldSource.TEMPLATE, score=score,
                                               note=state.value))
            _log.warning(f"{ctx} 무기 상태 불확실 (score={score:.3f} → {state.name})")
        else:
            entry.set_meta("weapon_state",
                           FieldMeta.ok(FieldSource.TEMPLATE, score=score))
        self.log(f"  🗡 무기 상태: {state.name} (score={score:.3f})")

        if state == WeaponState.NO_WEAPON_SYSTEM:
            return

        if state == WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED:
            entry.weapon_star  = None
            entry.weapon_level = None
            entry.set_meta("weapon_star",  FieldMeta.skipped("not_equipped"))
            entry.set_meta("weapon_level", FieldMeta.skipped("not_equipped"))
            self.log("  🗡 무기 미장착 — 레벨/성작 스킵")
            return

        # WEAPON_EQUIPPED → 무기 메뉴 진입
        menu_btn = sr.get("weapon_info_menu_button")
        if not menu_btn:
            self.log("  ⚠️ weapon_info_menu_button 미정의")
            return

        self._click_r(menu_btn, "weapon_info_menu")
        if not self._wait(DELAY_TAB_SWITCH):
            self._esc()
            return

        img = self._capture()
        if img is None:
            self._esc()
            return

        star_r = sr.get("weapon_star_region")
        if star_r:
            from core.matcher import read_weapon_star_v5_result
            rs = read_weapon_star_v5_result(crop_region(img, star_r))
            entry.weapon_star = rs.value
            entry.set_meta("weapon_star",
                           FieldMeta.ok(FieldSource.TEMPLATE, score=rs.score)
                           if not rs.uncertain
                           else FieldMeta.uncertain(FieldSource.TEMPLATE,
                                                    score=rs.score))
        else:
            entry.set_meta("weapon_star", FieldMeta.region_missing("weapon_star_region"))

        d1 = sr.get("weapon_level_digit_1") or sr.get("weapon_level_digit1")
        d2 = sr.get("weapon_level_digit_2") or sr.get("weapon_level_digit2")
        if d1 and d2:
            entry.weapon_level = read_weapon_level(img, d1, d2)
            entry.set_meta("weapon_level",
                           FieldMeta.ok(FieldSource.TEMPLATE)
                           if entry.weapon_level is not None
                           else FieldMeta.failed(FieldSource.TEMPLATE, "digit_read_fail"))
            self.log(f"  🗡 무기: {entry.weapon_star}★  Lv.{entry.weapon_level}")
        else:
            self.log("  ⚠️ weapon_level_digit 미정의")
            entry.set_meta("weapon_level", FieldMeta.region_missing("weapon_level_digit"))

        self._esc()

    # ── 장비 스캔 ─────────────────────────────────────────

    def read_equipment(self, entry: StudentEntry) -> None:
        """
        장비 탭 진입 → 캡처 1회 → 슬롯 1~4 crop 재사용.
        impossible 판정 시 전체 스킵.
        """
        sr        = self.r["student"]
        equip_btn = sr.get("equipment_button")
        if not equip_btn:
            self.log("  ⚠️ equipment_button 미정의")
            return

        # 탭 진입 전 pre-check (기본 화면에서)
        img = self._get_student_basic_capture()
        if img is None:
            return

        pre = read_equip_check(crop_region(img, equip_btn))
        if pre == CheckFlag.IMPOSSIBLE:
            self.log("  🚫 equipment_button=impossible — 장비 스캔 스킵")
            # impossible → 모든 장비 필드를 skipped로 마킹
            for slot in (1, 2, 3, 4):
                entry.set_meta(f"equip{slot}",
                               FieldMeta.skipped("equipment_impossible"))
                if slot <= 3:
                    entry.set_meta(f"equip{slot}_level",
                                   FieldMeta.skipped("equipment_impossible"))
            return

        self._click_r(equip_btn, "equipment_tab")
        if not self._wait(DELAY_TAB_SWITCH):
            self._esc()
            return

        # 장비 메뉴 캡처 1회
        img = self._capture()
        if img is None:
            self._esc()
            return

        check_r = sr.get("equipment_all_view_check_region")
        if check_r:
            if read_equip_check_inside(crop_region(img, check_r)) == CheckFlag.FALSE:
                self.log("  🔘 장비 일괄성장 체크 클릭")
                self._click_r(check_r, "equip_check")
                if not self._wait(0.3):
                    self._esc()
                    return
                img = self._capture()   # 체크 후 재캡처
                if img is None:
                    self._esc()
                    return

        sid = entry.student_id or ""

        # 슬롯 1~3: 캡처 이미지 공유
        for slot in (1, 2, 3):
            skip_flags = {EquipSlotFlag.EMPTY}
            if slot in (2, 3):
                skip_flags.add(EquipSlotFlag.LEVEL_LOCKED)
            self._scan_equip_slot(entry, img, sr, slot,
                                  skip_flags=skip_flags, scan_level=True)

        # 슬롯 4
        if student_meta.favorite_item_enabled(sid):
            self._scan_equip_slot(
                entry, img, sr, 4,
                skip_flags={EquipSlotFlag.EMPTY,
                            EquipSlotFlag.LOVE_LOCKED,
                            EquipSlotFlag.NULL},
                scan_level=False,
            )
        else:
            self.log(f"  🎒 장비4: {sid} equip4 없음 — 스킵")

        self._esc()

    def _scan_equip_slot(
        self,
        entry: StudentEntry,
        img: Image.Image,
        sr: dict,
        slot: int,
        skip_flags: set[EquipSlotFlag],
        scan_level: bool,
    ) -> None:
        """단일 장비 슬롯 판독. img는 장비 메뉴 캡처 이미지 (재사용)."""
        equip_key = f"equip{slot}"
        level_key = f"equip{slot}_level"

        flag_r = (sr.get(f"equip{slot}_flag")
                  or sr.get(f"equip{slot}_emptyflag")
                  or sr.get(f"equip{slot}_empty_flag"))
        if flag_r:
            slot_flag = read_equip_slot_flag(crop_region(img, flag_r), slot)
            if slot_flag in skip_flags:
                self.log(f"  🎒 장비{slot}: {slot_flag.value} — 스킵")
                setattr(entry, equip_key, slot_flag.value)
                entry.set_meta(equip_key,
                               FieldMeta.skipped(f"slot_flag={slot_flag.value}"))
                if scan_level:
                    entry.set_meta(level_key,
                                   FieldMeta.skipped(f"slot_flag={slot_flag.value}"))
                return

        tier_r = sr.get(f"equipment_{slot}")
        if tier_r:
            tier = read_equip_tier(crop_region(img, tier_r), slot)
            setattr(entry, equip_key, tier)
            entry.set_meta(equip_key,
                           FieldMeta.ok(FieldSource.TEMPLATE)
                           if tier and tier != "unknown"
                           else FieldMeta.uncertain(FieldSource.TEMPLATE,
                                                    note=f"tier={tier}"))
            self.log(f"  🎒 장비{slot} 티어: {tier}")
        else:
            entry.set_meta(equip_key, FieldMeta.region_missing(f"equipment_{slot}"))

        if scan_level:
            d1 = sr.get(f"equipment_{slot}_level_digit_1")
            d2 = sr.get(f"equipment_{slot}_level_digit_2")
            if d1 and d2:
                lv = read_equip_level(img, slot, d1, d2)
                setattr(entry, level_key, lv)
                entry.set_meta(level_key,
                               FieldMeta.ok(FieldSource.TEMPLATE)
                               if lv is not None
                               else FieldMeta.failed(FieldSource.TEMPLATE,
                                                     "digit_read_fail"))
                self.log(f"  🎒 장비{slot} 레벨: {lv}")
            else:
                self.log(f"  ⚠️ equipment_{slot}_level_digit 미정의")
                entry.set_meta(level_key,
                               FieldMeta.region_missing(f"equipment_{slot}_level_digit"))

    # ── 레벨 스캔 ─────────────────────────────────────────

    def read_level(self, entry: StudentEntry) -> None:
        """레벨 탭 진입 → 캡처 1회 → digit crop 재사용."""
        ctx = ScanCtx(student_id=entry.student_id, step="read_level")

        if entry.level == MAX_STUDENT_LEVEL:
            self.log(f"  ⏭ 레벨 스캔 생략 (이미 Lv.90)")
            entry.set_meta("level", FieldMeta.skipped("already_max"))
            return

        if not self._tab("levelcheck_button", delay=0.4):
            _log.warning(f"{ctx} 레벨 탭 이동 실패")
            entry.set_meta("level", FieldMeta.failed(FieldSource.TEMPLATE, "tab_fail"))
            return

        img = self._capture()
        if img is None:
            self._restore_basic_tab()
            entry.set_meta("level", FieldMeta.failed(FieldSource.TEMPLATE, "capture_fail"))
            return

        sr = self.r["student"]
        d1 = sr.get("level_digit_1")
        d2 = sr.get("level_digit_2")
        if not d1 or not d2:
            _log.warning(f"{ctx} level_digit region 미정의")
            self._restore_basic_tab()
            entry.set_meta("level", FieldMeta.region_missing("level_digit"))
            return

        lv = read_student_level_v5(img, d1, d2)
        entry.level = lv

        if lv is not None:
            entry.set_meta("level", FieldMeta.ok(FieldSource.TEMPLATE))
            self.log(f"  📊 레벨: {entry.label()} → Lv.{lv}")
        else:
            entry.set_meta("level", FieldMeta.failed(FieldSource.TEMPLATE, "digit_read_fail"))
            _log.warning(f"{ctx} 레벨 인식 실패")
            if self._asv:
                self._asv.on_step_error("read_level", entry.student_id or "")

        self._restore_basic_tab()

    # ── 성작 스캔 ─────────────────────────────────────────

    def read_student_star(self, entry: StudentEntry) -> None:
        """
        무기 보유 학생은 5★ 확정.
        그 외 star_menu 탭 진입 → 캡처 1회.
        """
        ctx = ScanCtx(student_id=entry.student_id, step="read_student_star")

        if entry.weapon_state != WeaponState.NO_WEAPON_SYSTEM:
            # 무기 보유 = 5★ 확정 — 인식 불필요
            entry.student_star = 5
            entry.set_meta("student_star",
                           FieldMeta.inferred("weapon_state → 5★ 확정"))
            self.log(f"  ⏭ 성작 스캔 생략 (무기 보유 → 5★)")
            return

        sr       = self.r["student"]
        star_btn = sr.get("star_menu_button")
        if star_btn:
            self._click_r(star_btn, "star_menu")
            if not self._wait(0.3):
                return

        img = self._capture()
        if img is None:
            entry.set_meta("student_star",
                           FieldMeta.failed(FieldSource.TEMPLATE, "capture_fail"))
            return

        region_key = (
            "student_star_region"
            if "student_star_region" in sr
            else "star_region"
        )
        star_r = sr.get(region_key)
        if not star_r:
            entry.set_meta("student_star",
                           FieldMeta.region_missing(region_key))
            return

        from core.matcher import read_student_star_v5_result
        r = read_student_star_v5_result(crop_region(img, star_r))

        entry.student_star = r.value
        if r.uncertain or r.value is None:
            entry.set_meta("student_star",
                           FieldMeta.uncertain(FieldSource.TEMPLATE,
                                               score=r.score,
                                               note=f"value={r.value}"))
            _log.warning(f"{ctx} 성작 인식 불확실 (score={r.score:.3f} val={r.value})")
        else:
            entry.set_meta("student_star",
                           FieldMeta.ok(FieldSource.TEMPLATE, score=r.score))
            self.log(f"  ⭐ 성작: {entry.label()} → {entry.student_star}★ (score={r.score:.3f})")

    # ── 스탯 스캔 ─────────────────────────────────────────

    def read_stats(self, entry: StudentEntry) -> None:
        """
        Lv.90 + 5★ 조건 미충족 시 스킵.
        stat 메뉴 진입 → 캡처 1회 → 3종 crop 재사용.
        """
        level_ok = entry.level is not None and entry.level >= STAT_UNLOCK_LEVEL
        star_ok  = entry.student_star is not None and entry.student_star >= STAT_UNLOCK_STAR

        if not level_ok or not star_ok:
            self.log(
                f"  ⏭ 스탯 스캔 생략 "
                f"(Lv.{entry.level} / {entry.student_star}★)"
            )
            return

        if not self._tab("stat_menu_button", delay=0.4):
            return

        img = self._capture()
        if img is None:
            self._esc()
            return

        ctx = ScanCtx(student_id=entry.student_id, step="read_stats")

        sr = self.r["student"]
        for stat_key, field_name, region_key in [
            ("hp",   "stat_hp",   "hp"),
            ("atk",  "stat_atk",  "atk"),
            ("heal", "stat_heal", "heal"),
        ]:
            region = sr.get(region_key)
            if not region:
                _log.warning(f"{ctx.with_step(field_name)} region 미정의")
                entry.set_meta(field_name, FieldMeta.region_missing(region_key))
                continue

            from core.matcher import read_stat_value_result
            r = read_stat_value_result(crop_region(img, region), stat_key)
            setattr(entry, field_name, r.value)

            if r.value is None or r.uncertain:
                entry.set_meta(field_name,
                               FieldMeta.uncertain(FieldSource.TEMPLATE,
                                                   score=r.score,
                                                   note=f"val={r.value}"))
                _log.warning(f"{ctx.with_step(field_name)} 스탯 인식 불확실 "
                             f"(score={r.score:.3f} val={r.value})")
            else:
                entry.set_meta(field_name,
                               FieldMeta.ok(FieldSource.TEMPLATE, score=r.score))

        self.log(
            f"  📈 스탯: HP={entry.stat_hp} "
            f"ATK={entry.stat_atk} HEAL={entry.stat_heal}"
        )
        self._esc()

    # ── 로그 ──────────────────────────────────────────────

    def _log_student(self, entry: StudentEntry, idx: int) -> None:
        weapon_info = ""
        if entry.weapon_state == WeaponState.WEAPON_EQUIPPED:
            weapon_info = f" | 무기:{entry.weapon_star}★ Lv.{entry.weapon_level}"
        elif entry.weapon_state == WeaponState.WEAPON_UNLOCKED_NOT_EQUIPPED:
            weapon_info = " | 무기:미장착"

        equip_info = (
            f"{entry.equip1}(Lv.{entry.equip1_level})/"
            f"{entry.equip2}(Lv.{entry.equip2_level})/"
            f"{entry.equip3}(Lv.{entry.equip3_level})/"
            f"{entry.equip4}"
        )
        self.log(
            f"  👩 [{idx+1:>3}] {entry.label()}  Lv.{entry.level}  "
            f"{entry.student_star}★{weapon_info}  "
            f"EX:{entry.ex_skill} S1:{entry.skill1} "
            f"S2:{entry.skill2} S3:{entry.skill3}  "
            f"장비:{equip_info}  "
            f"스탯(HP:{entry.stat_hp}/ATK:{entry.stat_atk}/HEAL:{entry.stat_heal})"
        )

        # ── 메타 요약 로그 ────────────────────────────────
        # uncertain / failed / inferred 필드만 출력
        uncertain = entry.uncertain_fields()
        failed    = entry.failed_fields()
        inferred  = [k for k, v in entry._meta.items()
                     if v.status == FieldStatus.INFERRED]

        if uncertain:
            _log.warning(
                f"  [{idx+1:>3}] {entry.label()} "
                f"— uncertain: {uncertain}"
            )
        if failed:
            _log.warning(
                f"  [{idx+1:>3}] {entry.label()} "
                f"— failed: {failed}"
            )
        if inferred:
            _log.info(
                f"  [{idx+1:>3}] {entry.label()} "
                f"— inferred: {inferred}"
            )

    # ── 전체 스캔 ─────────────────────────────────────────

    def run_full_scan(self) -> ScanResult:
        self.clear_stop()
        result = ScanResult()
        self.log("━━━━━ 전체 스캔 시작 ━━━━━")
        result.resources = self.scan_resources()
        result.items     = self.scan_items()
        if not self._stop_requested():
            result.equipment = self.scan_equipment()
        if not self._stop_requested():
            result.students  = self.scan_students_v5()
        self.log("━━━━━ 전체 스캔 완료 ━━━━━")
        return result
