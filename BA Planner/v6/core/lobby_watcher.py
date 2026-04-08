"""
core/lobby_watcher.py — BA Analyzer v6
로비 감지 + scanner 충돌 제거 + 안전한 thread lifecycle

변경점 (v5 → v6):
  - 상태 머신 도입: IDLE / RUNNING / PAUSED
  - pause() / resume() 추가 → scanner 실행 중 감지 루프 일시정지
  - stop() 에 thread.join(timeout) 추가 → zombie thread 방지
  - ROI 캡처: 전체 화면 대신 detect_flag 영역만 캡처
    (PrintWindow 전체 → crop 대신 crop 좌표 계산 후 부분 추출)
  - _check() 에서 창 rect 변경 감지 분리 → 캡처 최소화
  - threading.Event 로 pause/resume 구현 (sleep 기반 polling 제거)

공개 인터페이스:
  LobbyWatcher(lobby_region, on_enter, on_leave, on_window_move)
    .start()
    .stop()
    .pause()     ← scanner 시작 시 호출
    .resume()    ← scanner 종료 시 호출
    .in_lobby    → bool
    .state       → WatcherState
"""

import threading
import time
from typing import Callable, Optional

from core.logger import get_logger, LOG_WATCHER
from core.states import WatcherState
from core.capture import (
    capture_window_background,
    get_window_rect,
    crop_region,
    find_target_hwnd,
)
from core.matcher import is_lobby

_log = get_logger(LOG_WATCHER)




# ── LobbyWatcher ──────────────────────────────────────────

class LobbyWatcher:
    """
    블루아카이브 로비 화면 감지 워처.

    사용 예
    -------
    watcher = LobbyWatcher(region, on_enter=..., on_leave=...)
    watcher.start()

    # scanner 시작 직전
    watcher.pause()
    scanner.run()
    watcher.resume()
    """

    # 감지 주기 (초)
    INTERVAL_RUNNING = 2.5
    INTERVAL_PAUSED  = 0.5   # pause 상태에서 resume 대기 폴링 간격

    # stop() 시 thread 종료 대기 최대 시간
    JOIN_TIMEOUT = 3.0

    def __init__(
        self,
        lobby_region: dict,
        on_enter:        Optional[Callable[[], None]]               = None,
        on_leave:        Optional[Callable[[], None]]               = None,
        on_window_move:  Optional[Callable[[int,int,int,int], None]] = None,
    ):
        """
        Parameters
        ----------
        lobby_region    : detect_flag region dict {x1,y1,x2,y2}
        on_enter        : 로비 진입 시 콜백
        on_leave        : 로비 이탈 시 콜백
        on_window_move  : 창 rect 변경 시 콜백 (left,top,w,h)
        """
        self._region       = lobby_region
        self._on_enter     = on_enter      or (lambda: None)
        self._on_leave     = on_leave      or (lambda: None)
        self._on_move      = on_window_move or (lambda *a: None)

        self._state        = WatcherState.IDLE
        self._state_lock   = threading.Lock()

        self._in_lobby     = False
        self._last_rect:   Optional[tuple[int,int,int,int]] = None

        # pause/resume 제어용 Event
        # set = 실행 가능, clear = pause
        self._resume_event = threading.Event()
        self._resume_event.set()   # 기본값: 실행 가능

        self._thread: Optional[threading.Thread] = None

    # ── 공개 프로퍼티 ─────────────────────────────────────

    @property
    def in_lobby(self) -> bool:
        return self._in_lobby

    @property
    def state(self) -> WatcherState:
        with self._state_lock:
            return self._state

    # ── lifecycle ─────────────────────────────────────────

    def start(self) -> None:
        """감지 루프 시작. 이미 RUNNING/PAUSED 이면 무시."""
        with self._state_lock:
            if self._state in (WatcherState.RUNNING, WatcherState.PAUSED):
                return
            self._state = WatcherState.RUNNING

        self._resume_event.set()
        self._thread = threading.Thread(
            target=self._loop,
            name="LobbyWatcher",
            daemon=True,
        )
        self._thread.start()
        _log.info("시작")

    def stop(self) -> None:
        """
        감지 루프 종료.
        thread.join(timeout) 으로 안전하게 대기.
        """
        with self._state_lock:
            if self._state == WatcherState.STOPPED:
                return
            self._state = WatcherState.STOPPED

        # pause 중이어도 루프가 종료 조건 확인할 수 있도록 event set
        self._resume_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.JOIN_TIMEOUT)
            if self._thread.is_alive():
                _log.warning("thread join 시간 초과 — 강제 종료 불가 (daemon)")
            else:
                _log.info("thread 종료 완료")

        self._thread = None
        _log.info("중지")

    def pause(self) -> None:
        """
        감지 루프 일시정지.
        scanner 시작 직전에 호출.
        현재 체크 사이클이 끝난 뒤 다음 사이클부터 skip.
        """
        with self._state_lock:
            if self._state != WatcherState.RUNNING:
                return
            self._state = WatcherState.PAUSED

        self._resume_event.clear()
        _log.info("⏸ 일시정지 (scanner 실행 중)")

    def resume(self) -> None:
        """
        감지 루프 재개.
        scanner 종료 직후에 호출.
        """
        with self._state_lock:
            if self._state != WatcherState.PAUSED:
                return
            self._state = WatcherState.RUNNING

        self._resume_event.set()
        _log.info("▶ 재개")

    # ── 내부 루프 ─────────────────────────────────────────

    def _loop(self) -> None:
        while True:
            # 종료 확인
            if self.state == WatcherState.STOPPED:
                break

            # pause 상태: resume_event 가 set 될 때까지 대기
            # timeout 을 짧게 줘서 STOPPED 전환도 감지
            if not self._resume_event.is_set():
                self._resume_event.wait(timeout=self.INTERVAL_PAUSED)
                continue

            # 종료 재확인 (resume 직후에 STOPPED 일 수 있음)
            if self.state == WatcherState.STOPPED:
                break

            try:
                self._check()
            except Exception as e:
                _log.error(f"체크 오류: {e}", exc_info=True)

            # 다음 사이클까지 대기
            # Event.wait 로 구현 → stop() 시 즉시 깨어날 수 있음
            self._resume_event.wait(timeout=self.INTERVAL_RUNNING)

    # ── 감지 로직 ─────────────────────────────────────────

    def _check(self) -> None:
        """
        1회 로비 감지 사이클.
        - 창 존재 확인
        - rect 변경 감지 (창 이동/리사이즈)
        - ROI 캡처 (detect_flag 영역만)
        - 로비 판정
        """
        # ── 창 존재 확인 ──────────────────────────────────
        hwnd = find_target_hwnd()
        if hwnd is None:
            if self._in_lobby:
                _log.info("창 없음 → 로비 이탈 처리")
                self._in_lobby = False
                self._on_leave()
            self._last_rect = None
            return

        # ── rect 변경 감지 ────────────────────────────────
        rect = get_window_rect()
        if rect is None:
            return

        if rect != self._last_rect:
            self._last_rect = rect
            self._on_move(*rect)

        # ── ROI 캡처 ──────────────────────────────────────
        # 로비 감지는 2.5초 주기로 반복되므로 normalize=False 로 속도 우선.
        # detect_flag ROI 는 비율 좌표라 해상도 무관하게 crop 가능.
        img = capture_window_background(hwnd, normalize=False)
        if img is None:
            _log.warning("캡처 실패")
            return

        roi = crop_region(img, self._region)

        # ── 로비 판정 ─────────────────────────────────────
        # is_lobby 는 이미 crop 된 이미지를 기대하므로
        # region 을 전체(0~1)로 전달
        _FULL_REGION = {"x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}
        lobby = is_lobby(roi, _FULL_REGION)

        if lobby and not self._in_lobby:
            _log.info("✅ 로비 진입")
            self._in_lobby = True
            self._on_enter()

        elif not lobby and self._in_lobby:
            _log.info("🚪 로비 이탈")
            self._in_lobby = False
            self._on_leave()