"""
core/logger.py — BA Analyzer v6
공통 로거 설정

━━━ 로거 계층 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ba                     ← 루트 (전체 제어)
  ├─ ba.capture          ← capture.py
  ├─ ba.input            ← input.py
  ├─ ba.watcher          ← lobby_watcher.py
  ├─ ba.scanner          ← scanner.py
  │   ├─ ba.scanner.item
  │   ├─ ba.scanner.equip
  │   └─ ba.scanner.student
  ├─ ba.matcher          ← matcher.py
  ├─ ba.ocr              ← ocr.py
  └─ ba.app              ← main.py

━━━ 로그 파일 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  logs/ba_{YYYY-MM-DD}.log   — 날짜별 파일
  logs/latest.log            — 현재 세션 심볼릭 링크 (Windows에서는 복사)

━━━ 포맷 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  콘솔: [HH:MM:SS] LEVEL  [모듈] 메시지
  파일: YYYY-MM-DD HH:MM:SS,ms  LEVEL  [스레드] [모듈] 메시지

━━━ 공개 인터페이스 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  setup_logging(level, log_dir)    → None   (앱 시작 시 1회 호출)
  get_logger(name)                 → Logger (모듈별 로거 반환)

  사전 정의 로거 상수:
    LOG_CAPTURE / LOG_INPUT / LOG_WATCHER
    LOG_SCANNER / LOG_MATCHER / LOG_OCR / LOG_APP
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# ══════════════════════════════════════════════════════════
# 로거 이름 상수
# ══════════════════════════════════════════════════════════

ROOT        = "ba"
LOG_CAPTURE = "ba.capture"
LOG_INPUT   = "ba.input"
LOG_WATCHER = "ba.watcher"
LOG_SCANNER = "ba.scanner"
LOG_MATCHER = "ba.matcher"
LOG_OCR     = "ba.ocr"
LOG_APP     = "ba.app"


# ══════════════════════════════════════════════════════════
# 포맷터
# ══════════════════════════════════════════════════════════

# 콘솔: 간결하게
_CONSOLE_FMT = "[%(asctime)s] %(levelname)-5s [%(name)s] %(message)s"
_CONSOLE_DATEFMT = "%H:%M:%S"

# 파일: 스레드 이름 포함, 풀 타임스탬프
_FILE_FMT = "%(asctime)s  %(levelname)-5s  [%(threadName)s] [%(name)s] %(message)s"
_FILE_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _LevelFilter(logging.Filter):
    """콘솔에서 DEBUG 메시지를 제외할 때 사용."""
    def __init__(self, min_level: int):
        super().__init__()
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.min_level


# ══════════════════════════════════════════════════════════
# 초기화
# ══════════════════════════════════════════════════════════

_initialized = False


def setup_logging(
    console_level: int = logging.INFO,
    file_level:    int = logging.DEBUG,
    log_dir:       Optional[Path] = None,
) -> None:
    """
    로깅 시스템 초기화. 앱 시작 시 1회만 호출.

    Parameters
    ----------
    console_level : 콘솔 출력 최소 레벨 (기본 INFO)
    file_level    : 파일 출력 최소 레벨 (기본 DEBUG — 전체 기록)
    log_dir       : 로그 파일 저장 디렉터리 (기본 BASE_DIR/logs)
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    # ── 루트 로거 ─────────────────────────────────────────
    root = logging.getLogger(ROOT)
    root.setLevel(logging.DEBUG)   # 핸들러에서 필터링
    root.propagate = False         # 파이썬 루트 로거로 전파 차단

    # ── 콘솔 핸들러 ───────────────────────────────────────
    console_h = logging.StreamHandler(sys.stdout)
    console_h.setLevel(console_level)
    console_h.setFormatter(
        logging.Formatter(_CONSOLE_FMT, datefmt=_CONSOLE_DATEFMT)
    )
    root.addHandler(console_h)

    # ── 파일 핸들러 ───────────────────────────────────────
    try:
        if log_dir is None:
            from core.config import BASE_DIR
            log_dir = BASE_DIR / "logs"

        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        today      = datetime.now().strftime("%Y-%m-%d")
        log_path   = log_dir / f"ba_{today}.log"

        file_h = logging.FileHandler(log_path, encoding="utf-8")
        file_h.setLevel(file_level)
        file_h.setFormatter(
            logging.Formatter(_FILE_FMT, datefmt=_FILE_DATEFMT)
        )
        root.addHandler(file_h)

        # latest.log 복사 (Windows 는 symlink 권한 없을 수 있어서 복사로 대체)
        latest = log_dir / "latest.log"
        try:
            if latest.exists() or latest.is_symlink():
                latest.unlink()
            latest.symlink_to(log_path.name)
        except (OSError, NotImplementedError):
            # symlink 실패 시 그냥 같은 파일에 추가 핸들러
            pass

        root.info(
            f"[Logger] 로그 파일: {log_path}  "
            f"(콘솔={logging.getLevelName(console_level)} "
            f"파일={logging.getLevelName(file_level)})"
        )

    except Exception as e:
        root.warning(f"[Logger] 파일 핸들러 설정 실패 (콘솔만 사용): {e}")


def get_logger(name: str) -> logging.Logger:
    """
    모듈별 로거 반환.
    setup_logging() 이 아직 호출되지 않았으면 자동으로 호출.

    Parameters
    ----------
    name : 로거 이름 (LOG_SCANNER 등 상수 사용 권장)
    """
    if not _initialized:
        setup_logging()
    return logging.getLogger(name)


# ══════════════════════════════════════════════════════════
# 편의 함수
# ══════════════════════════════════════════════════════════

def set_console_level(level: int) -> None:
    """런타임 콘솔 레벨 변경 (디버깅 시 DEBUG 로 낮출 때 사용)."""
    root = logging.getLogger(ROOT)
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout:
            h.setLevel(level)
            root.info(f"[Logger] 콘솔 레벨 변경: {logging.getLevelName(level)}")
            return


def log_section(logger: logging.Logger, title: str, char: str = "━", width: int = 50) -> None:
    """
    구분선 로그.
    예: ━━━━━ 학생 스캔 시작 ━━━━━
    """
    pad = max(0, width - len(title) - 2)
    left  = char * (pad // 2)
    right = char * (pad - pad // 2)
    logger.info(f"{left} {title} {right}")
