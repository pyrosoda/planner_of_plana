"""
core/log_context.py — BA Analyzer v6
로그 컨텍스트 표준화 + 예외 로그 강화 + 디버그 산출물 저장

━━━ 7-4 컨텍스트 표준화 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  포맷 규칙:
    [SCAN][idx=12][step=read_level] OCR 실패
    [WATCHER][state=paused] 체크 스킵
    [MATCHER][roi=weapon_state][score=0.82] matched=equipped
    [CAPTURE][hwnd=0x1A2B] PrintWindow 실패

  ScanCtx     — 학생 스캔 단계 컨텍스트
  WatcherCtx  — watcher 상태 컨텍스트
  MatchCtx    — 매처 결과 컨텍스트

━━━ 7-3 예외 로그 강화 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  예외 레벨 정책:
    치명 (스캔 중단)    → logger.exception  (traceback 포함)
    복구 가능 (단계 실패) → logger.warning   (컨텍스트 포함)
    캡처 실패 / retry   → logger.warning
    cv2.error / 값 변환 → logger.debug      (정상 흐름)
    hwnd 무효           → logger.error

  log_exc(logger, msg, exc, *, ctx, level)  — 표준 예외 로그 함수

━━━ 7-5 디버그 산출물 저장 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  DebugDumper.save(img, tag, *, score, reason)
    → debug_dump/{날짜}/{tag}_{seq}.png
    → 최대 MAX_DUMP_PER_TAG 개 per tag (FIFO 삭제)

  전역 on/off: set_debug_dump(enabled)
  자동 비활성화: 기본 False — main.py 에서 DEBUG 모드일 때만 켬

공개 인터페이스:
  ScanCtx(idx, student_id, step, retry)     → str 태그
  WatcherCtx(state)                         → str 태그
  MatchCtx(roi, score, result)              → str 태그
  log_exc(logger, msg, exc, ctx, level)     → None
  DebugDumper                               → 싱글톤
  set_debug_dump(enabled, dump_dir)         → None
  dump_roi(img, tag, score, reason)         → None  (편의 함수)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image


# ══════════════════════════════════════════════════════════
# 7-4  컨텍스트 태그 헬퍼
# ══════════════════════════════════════════════════════════

def _tag(**kwargs) -> str:
    """
    키워드 인수를 [key=val][key=val] 형태 태그로 변환.
    None 값은 생략.
    """
    parts = [f"[{k}={v}]" for k, v in kwargs.items() if v is not None]
    return "".join(parts)


@dataclass
class ScanCtx:
    """
    학생 스캔 단계 컨텍스트.

    사용 예
    -------
    ctx = ScanCtx(idx=5, student_id="shiroko", step="read_level")
    _log.warning(f"{ctx} Lv 숫자 인식 실패")
    # → [SCAN][idx=5][sid=shiroko][step=read_level] Lv 숫자 인식 실패
    """
    idx:        Optional[int] = None
    student_id: Optional[str] = None
    step:       Optional[str] = None
    retry:      Optional[int] = None

    def __str__(self) -> str:
        return "[SCAN]" + _tag(
            idx=self.idx,
            sid=self.student_id,
            step=self.step,
            retry=self.retry,
        )

    def with_step(self, step: str) -> "ScanCtx":
        """단계만 바꾼 새 컨텍스트 반환 (불변 패턴)."""
        return ScanCtx(self.idx, self.student_id, step, self.retry)

    def with_retry(self, retry: int) -> "ScanCtx":
        return ScanCtx(self.idx, self.student_id, self.step, retry)


@dataclass
class WatcherCtx:
    """
    watcher 상태 컨텍스트.

    사용 예
    -------
    ctx = WatcherCtx(state="paused")
    _log.info(f"{ctx} 체크 스킵")
    # → [WATCHER][state=paused] 체크 스킵
    """
    state:   Optional[str] = None
    hwnd:    Optional[int] = None

    def __str__(self) -> str:
        hwnd_hex = hex(self.hwnd) if self.hwnd else None
        return "[WATCHER]" + _tag(state=self.state, hwnd=hwnd_hex)


@dataclass
class MatchCtx:
    """
    매처 결과 컨텍스트.

    사용 예
    -------
    ctx = MatchCtx(roi="weapon_state", score=0.82, result="equipped")
    _log.debug(f"{ctx} 무기 상태 인식")
    # → [MATCHER][roi=weapon_state][score=0.82][result=equipped] 무기 상태 인식
    """
    roi:    Optional[str]   = None
    score:  Optional[float] = None
    result: Optional[str]   = None

    def __str__(self) -> str:
        score_str = f"{self.score:.3f}" if self.score is not None else None
        return "[MATCHER]" + _tag(roi=self.roi, score=score_str, result=self.result)


@dataclass
class CaptureCtx:
    """캡처 컨텍스트."""
    hwnd:    Optional[int] = None
    attempt: Optional[int] = None

    def __str__(self) -> str:
        hwnd_hex = hex(self.hwnd) if self.hwnd else None
        return "[CAPTURE]" + _tag(hwnd=hwnd_hex, attempt=self.attempt)


# ══════════════════════════════════════════════════════════
# 7-3  예외 로그 강화 유틸
# ══════════════════════════════════════════════════════════

# 예외 레벨 정책 상수
EXC_FATAL    = logging.CRITICAL   # 스캔 완전 중단
EXC_ERROR    = logging.ERROR      # hwnd 무효 등 외부 리소스 오류
EXC_WARNING  = logging.WARNING    # 복구 가능한 단계 실패
EXC_DEBUG    = logging.DEBUG      # cv2.error, ValueError 등 정상 흐름


def log_exc(
    logger:  logging.Logger,
    msg:     str,
    exc:     Exception,
    *,
    ctx:     object = "",
    level:   int    = EXC_WARNING,
    reraise: bool   = False,
) -> None:
    """
    표준 예외 로그 함수.

    Parameters
    ----------
    logger  : 모듈 로거
    msg     : 상황 설명 (한국어 OK)
    exc     : 발생한 예외 객체
    ctx     : 컨텍스트 태그 (ScanCtx / MatchCtx / str 등)
    level   : 로그 레벨 (EXC_WARNING / EXC_ERROR / EXC_FATAL)
    reraise : True 이면 로그 후 예외 재발생

    레벨별 동작:
      FATAL / ERROR  → logger.exception (traceback 포함)
      WARNING        → logger.warning   (한 줄, exc 타입+메시지)
      DEBUG          → logger.debug     (조용히)
    """
    full_msg = f"{ctx} {msg} — {type(exc).__name__}: {exc}"

    if level >= logging.ERROR:
        logger.exception(full_msg)       # traceback 자동 포함
    elif level == logging.WARNING:
        logger.warning(full_msg)
    else:
        logger.debug(full_msg)

    if reraise:
        raise exc


def log_cv2_error(
    logger: logging.Logger,
    msg:    str,
    exc:    Exception,
    ctx:    object = "",
) -> None:
    """cv2.error 전용 — DEBUG 레벨 (정상 흐름의 일부)."""
    log_exc(logger, msg, exc, ctx=ctx, level=EXC_DEBUG)


def log_capture_fail(
    logger:  logging.Logger,
    hwnd:    int,
    attempt: int,
    reason:  str = "",
) -> None:
    """캡처 실패 전용 — WARNING + 재시도 컨텍스트."""
    ctx = CaptureCtx(hwnd=hwnd, attempt=attempt)
    logger.warning(f"{ctx} 캡처 실패{': ' + reason if reason else ''}")


def log_hwnd_invalid(
    logger: logging.Logger,
    hwnd:   int,
) -> None:
    """HWND 무효 — ERROR."""
    ctx = CaptureCtx(hwnd=hwnd)
    logger.error(f"{ctx} HWND 유효하지 않음")


# ══════════════════════════════════════════════════════════
# 7-5  디버그 산출물 저장
# ══════════════════════════════════════════════════════════

_DEBUG_LOG = logging.getLogger("ba.debug_dump")

# 태그별 최대 저장 개수 (오래된 것부터 삭제)
MAX_DUMP_PER_TAG: int = 30

# 전체 저장 개수 상한 (세션 전체)
MAX_DUMP_TOTAL: int = 500

# 디버그 덤프 기본 경로
_DEFAULT_DUMP_DIR = Path(__file__).parent.parent / "debug_dump"


class DebugDumper:
    """
    인식 실패 / 불확실 ROI crop 이미지를 디스크에 저장.

    비활성화 시 save() 는 즉시 반환 (오버헤드 없음).
    활성화 시 debug_dump/{날짜}/{tag}_{seq:04d}.png 저장.

    사용 예
    -------
    # main.py 에서
    set_debug_dump(enabled=True)

    # scanner.py 에서
    dump_roi(crop_img, "read_level", score=0.42, reason="digit_fail")
    """

    def __init__(self) -> None:
        self._enabled:   bool      = False
        self._dump_dir:  Path      = _DEFAULT_DUMP_DIR
        self._counters:  dict[str, int] = {}  # tag → 저장 횟수
        self._total:     int       = 0
        self._today_dir: Path | None = None
        self._today_str: str       = ""

    # ── 설정 ──────────────────────────────────────────────

    def configure(
        self,
        enabled:  bool,
        dump_dir: Path | str = _DEFAULT_DUMP_DIR,
    ) -> None:
        self._enabled  = enabled
        self._dump_dir = Path(dump_dir)
        if enabled:
            self._dump_dir.mkdir(parents=True, exist_ok=True)
            _DEBUG_LOG.info(f"디버그 덤프 활성화 → {self._dump_dir}")
        else:
            _DEBUG_LOG.info("디버그 덤프 비활성화")

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ── 저장 ──────────────────────────────────────────────

    def save(
        self,
        img:    "Image.Image",
        tag:    str,
        *,
        score:  Optional[float] = None,
        reason: str             = "",
        level:  int             = logging.DEBUG,
    ) -> Optional[Path]:
        """
        이미지를 debug_dump/{날짜}/{tag}_{seq}.png 로 저장.

        Parameters
        ----------
        img    : 저장할 PIL Image (이미 crop 된 ROI)
        tag    : 식별 태그 (예: "read_level", "weapon_star", "equip1_T3")
        score  : 인식 점수 (파일명에 포함)
        reason : 실패 이유 (파일명에 포함)
        level  : 저장 로그 레벨

        Returns
        -------
        저장된 파일 Path 또는 None (비활성화 / 한도 초과)
        """
        if not self._enabled:
            return None

        if self._total >= MAX_DUMP_TOTAL:
            _DEBUG_LOG.debug(f"덤프 한도 초과 (total={self._total}) — 저장 생략")
            return None

        # 날짜별 하위 폴더
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._today_str:
            self._today_str = today
            self._today_dir = self._dump_dir / today
            self._today_dir.mkdir(parents=True, exist_ok=True)

        # 태그별 시퀀스 번호
        seq = self._counters.get(tag, 0) + 1
        self._counters[tag] = seq
        self._total += 1

        # 파일명 구성
        score_str  = f"_s{score:.2f}".replace(".", "") if score is not None else ""
        reason_str = f"_{reason}" if reason else ""
        fname = f"{tag}{score_str}{reason_str}_{seq:04d}.png"
        path  = self._today_dir / fname

        # 태그별 최대 개수 초과 시 가장 오래된 파일 삭제
        existing = sorted(self._today_dir.glob(f"{tag}_*.png"))
        while len(existing) >= MAX_DUMP_PER_TAG:
            existing[0].unlink(missing_ok=True)
            existing.pop(0)

        # 저장
        try:
            img.save(path)
            _DEBUG_LOG.log(level, f"덤프 저장: {path.name} (total={self._total})")
            return path
        except Exception as e:
            _DEBUG_LOG.warning(f"덤프 저장 실패: {e}")
            return None

    def stats(self) -> dict:
        return {
            "enabled": self._enabled,
            "total":   self._total,
            "by_tag":  dict(self._counters),
            "dump_dir": str(self._dump_dir),
        }


# ── 전역 싱글톤 ───────────────────────────────────────────

_DUMPER = DebugDumper()


def set_debug_dump(
    enabled:  bool,
    dump_dir: Path | str = _DEFAULT_DUMP_DIR,
) -> None:
    """전역 디버그 덤프 on/off. main.py 에서 1회 호출."""
    _DUMPER.configure(enabled=enabled, dump_dir=dump_dir)


def dump_roi(
    img:    "Image.Image",
    tag:    str,
    *,
    score:  Optional[float] = None,
    reason: str             = "",
) -> None:
    """
    편의 함수 — 전역 덤프 싱글톤에 이미지 저장.
    비활성화 시 no-op.

    사용 예
    -------
    dump_roi(crop, "read_level", score=r.score, reason="uncertain")
    dump_roi(crop, "weapon_star", score=0.41, reason="below_thresh")
    """
    _DUMPER.save(img, tag, score=score, reason=reason)


def get_dumper() -> DebugDumper:
    """전역 DebugDumper 싱글톤 반환."""
    return _DUMPER
