"""
core/states.py — BA Analyzer v6
프로그램 전체 상태 enum 단일 관리

━━━ 상태 계층 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  AppState    — 앱 전체 생애주기
  WatcherState — LobbyWatcher 내부 상태
  ScanPhase   — 스캔 파이프라인 단계 (Scanner 내부)

  ┌─ AppState 전이 다이어그램 ──────────────────────────┐
  │                                                     │
  │  INIT ──→ IDLE ──→ WATCHING ──→ SCANNING            │
  │            ↑           ↑            │               │
  │            └───────────┴────────────┘               │
  │                                     ↓               │
  │                              ERROR ──→ WATCHING     │
  │                                                     │
  │  * ──→ STOPPING ──→ (종료)                          │
  └─────────────────────────────────────────────────────┘

━━━ 책임 경계 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  AppState    : main.py(App 클래스)가 소유 및 전이
  WatcherState: LobbyWatcher 가 소유, App 은 pause()/resume() 만 호출
  ScanPhase   : Scanner 내부용, 외부에는 노출하지 않음

━━━ 공개 인터페이스 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  AppState    (Enum)
  WatcherState (Enum)
  ScanPhase   (Enum)

  ALLOWED_TRANSITIONS  — AppState 허용 전이표
  is_valid_transition(from_, to) → bool
  StateMachine(initial, name)    — 검증+로깅 전이 관리자
    .transition(new_state)       → bool
    .state                       → 현재 상태
    .history                     → 전이 이력
"""

from __future__ import annotations

import threading
from datetime import datetime
from enum import Enum, auto
from typing import Optional

from core.logger import get_logger, LOG_APP

_log = get_logger(LOG_APP)


# ══════════════════════════════════════════════════════════
# AppState — 앱 전체 생애주기
# ══════════════════════════════════════════════════════════

class AppState(Enum):
    """
    앱 전체 상태.

    INIT        : 초기화 중 (의존성 로드, 템플릿 warmup)
    IDLE        : 창 미선택 — 스캔 불가
    WATCHING    : watcher 동작 중, 로비 감지 대기, 스캔 가능
    SCANNING    : 스캔 진행 중 — watcher paused
    PAUSED      : 스캔 일시정지 (미래 확장용)
    ERROR       : 복구 가능한 오류 발생 후 대기
    STOPPING    : 앱 종료 시퀀스 진행 중
    """
    INIT     = auto()
    IDLE     = auto()
    WATCHING = auto()
    SCANNING = auto()
    PAUSED   = auto()
    ERROR    = auto()
    STOPPING = auto()


# ══════════════════════════════════════════════════════════
# WatcherState — LobbyWatcher 내부 상태
# ══════════════════════════════════════════════════════════

class WatcherState(Enum):
    """
    LobbyWatcher 내부 상태.
    AppState 와 독립적으로 관리됨.

    IDLE    : start() 전
    RUNNING : 로비 감지 루프 동작 중
    PAUSED  : scanner 실행 중 — 감지 루프 skip
    STOPPED : stop() 호출 후 — 재사용 불가
    """
    IDLE    = auto()
    RUNNING = auto()
    PAUSED  = auto()
    STOPPED = auto()


# ══════════════════════════════════════════════════════════
# ScanPhase — Scanner 내부 파이프라인 단계
# ══════════════════════════════════════════════════════════

class ScanPhase(Enum):
    """
    Scanner 내부 파이프라인 단계.
    외부(main.py)에는 AppState.SCANNING 하나로 노출됨.

    IDLE        : 스캔 전
    RESOURCES   : 재화 스캔 중
    ITEMS       : 아이템 스캔 중
    EQUIPMENT   : 장비 스캔 중
    STUDENTS    : 학생 스캔 중
      IDENTIFY  : 학생 식별 중
      READ_SKILLS : 스킬 읽기
      READ_WEAPON : 무기 읽기
      READ_EQUIP  : 장비 읽기
      READ_LEVEL  : 레벨 읽기
      READ_STAR   : 성작 읽기
      READ_STATS  : 스탯 읽기
    DONE        : 완료
    STOPPED     : 중지 요청으로 중단
    """
    IDLE         = auto()
    RESOURCES    = auto()
    ITEMS        = auto()
    EQUIPMENT    = auto()
    STUDENTS     = auto()
    IDENTIFY     = auto()
    READ_SKILLS  = auto()
    READ_WEAPON  = auto()
    READ_EQUIP   = auto()
    READ_LEVEL   = auto()
    READ_STAR    = auto()
    READ_STATS   = auto()
    DONE         = auto()
    STOPPED      = auto()


# ══════════════════════════════════════════════════════════
# 허용 전이표 — AppState
# ══════════════════════════════════════════════════════════

ALLOWED_TRANSITIONS: dict[AppState, set[AppState]] = {
    AppState.INIT:     {AppState.IDLE, AppState.STOPPING},
    AppState.IDLE:     {AppState.WATCHING, AppState.STOPPING},
    AppState.WATCHING: {AppState.SCANNING, AppState.IDLE,
                        AppState.ERROR, AppState.STOPPING},
    AppState.SCANNING: {AppState.WATCHING, AppState.PAUSED,
                        AppState.ERROR, AppState.STOPPING},
    AppState.PAUSED:   {AppState.SCANNING, AppState.WATCHING,
                        AppState.ERROR, AppState.STOPPING},
    AppState.ERROR:    {AppState.WATCHING, AppState.IDLE,
                        AppState.STOPPING},
    AppState.STOPPING: set(),   # 종료 상태 — 어디서도 나갈 수 없음
}


def is_valid_transition(from_: AppState, to: AppState) -> bool:
    """전이 허용 여부 확인."""
    return to in ALLOWED_TRANSITIONS.get(from_, set())


# ══════════════════════════════════════════════════════════
# StateMachine — 검증 + 로깅 전이 관리자
# ══════════════════════════════════════════════════════════

class StateTransitionError(Exception):
    """허용되지 않은 상태 전이 시도."""
    pass


class StateMachine:
    """
    상태 전이 검증 + 이력 관리.

    사용 예 (main.py)
    ─────────────────
    self._sm = StateMachine(AppState.INIT, name="App")
    self._sm.transition(AppState.IDLE)      # OK
    self._sm.transition(AppState.SCANNING)  # ❌ IDLE → SCANNING 불허 → False
    self._sm.state                          # AppState.IDLE

    허용되지 않은 전이는 로그를 남기고 False 반환 (예외 없음).
    strict=True 이면 StateTransitionError 발생.
    """

    MAX_HISTORY = 50   # 이력 최대 보관 수

    def __init__(
        self,
        initial: AppState,
        name:    str  = "App",
        strict:  bool = False,
    ):
        self._state   = initial
        self._name    = name
        self._strict  = strict
        self._lock    = threading.Lock()
        self._history: list[dict] = []
        self._record(None, initial, "초기화")

    # ── 조회 ──────────────────────────────────────────────

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    @property
    def history(self) -> list[dict]:
        """전이 이력 복사본. {from, to, reason, at} 목록."""
        with self._lock:
            return list(self._history)

    def is_in(self, *states: AppState) -> bool:
        """현재 상태가 주어진 상태 중 하나인지 확인."""
        return self.state in states

    # ── 전이 ──────────────────────────────────────────────

    def transition(
        self,
        new_state: AppState,
        reason:    str = "",
    ) -> bool:
        """
        상태 전이 시도.

        Parameters
        ----------
        new_state : 전이 목표 상태
        reason    : 전이 이유 (로그용)

        Returns
        -------
        True  = 전이 성공
        False = 허용되지 않은 전이 (strict=False 일 때)

        Raises
        ------
        StateTransitionError : strict=True 이고 전이 불허 시
        """
        with self._lock:
            old = self._state

            # 동일 상태로의 전이 — 무시 (로그 없음)
            if old == new_state:
                return True

            if not is_valid_transition(old, new_state):
                msg = (
                    f"[{self._name}] ❌ 불허 전이: "
                    f"{old.name} → {new_state.name}"
                    + (f" ({reason})" if reason else "")
                )
                _log.warning(msg)
                if self._strict:
                    raise StateTransitionError(msg)
                return False

            self._state = new_state
            self._record(old, new_state, reason)

        _log.info(
            f"[{self._name}] 상태 전이: "
            f"{old.name} → {new_state.name}"
            + (f" ({reason})" if reason else "")
        )
        return True

    def force(
        self,
        new_state: AppState,
        reason:    str = "",
    ) -> None:
        """
        전이 규칙 무시하고 강제 전이.
        비상 상황(emergency, shutdown)에서만 사용.
        """
        with self._lock:
            old = self._state
            self._state = new_state
            self._record(old, new_state, f"FORCE: {reason}")

        _log.warning(
            f"[{self._name}] ⚠️ 강제 전이: "
            f"{old.name} → {new_state.name} ({reason})"
        )

    # ── 이력 ──────────────────────────────────────────────

    def _record(
        self,
        from_: Optional[AppState],
        to:    AppState,
        reason: str,
    ) -> None:
        entry = {
            "from":   from_.name if from_ else None,
            "to":     to.name,
            "reason": reason,
            "at":     datetime.now().isoformat(),
        }
        self._history.append(entry)
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)

    def last_transition(self) -> Optional[dict]:
        """가장 최근 전이 정보."""
        with self._lock:
            return self._history[-1] if self._history else None

    def transitions_to(self, state: AppState) -> list[dict]:
        """특정 상태로의 전이 이력만 반환."""
        with self._lock:
            return [h for h in self._history if h["to"] == state.name]

    def print_history(self) -> None:
        for h in self.history:
            print(
                f"  {h['at'][11:19]}  "
                f"{(h['from'] or 'None'):10s} → {h['to']:10s}"
                + (f"  ({h['reason']})" if h['reason'] else "")
            )
