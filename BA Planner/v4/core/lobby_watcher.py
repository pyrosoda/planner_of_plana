"""
core/lobby_watcher.py — 블루아카이브 창 감시 + 로비 감지
"""
import threading
import time
from typing import Callable

from core.capture import capture_window, get_window_rect
from core.matcher import is_lobby


class LobbyWatcher:
    INTERVAL = 2.5

    def __init__(self,
                 lobby_region: dict,
                 on_enter:       Callable = None,
                 on_leave:       Callable = None,
                 on_window_move: Callable = None):
        self._region    = lobby_region
        self._on_enter  = on_enter       or (lambda: None)
        self._on_leave  = on_leave       or (lambda: None)
        self._on_move   = on_window_move or (lambda *a: None)
        self._running   = False
        self._in_lobby  = False
        self._last_rect = None
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    @property
    def in_lobby(self):
        return self._in_lobby

    def _loop(self):
        while self._running:
            try:
                self._check()
            except Exception as e:
                print(f"[LobbyWatcher] 오류: {e}")
            time.sleep(self.INTERVAL)

    def _check(self):
        rect = get_window_rect()

        if rect is None:
            print("[LobbyWatcher] 블루아카이브 창 없음")
            if self._in_lobby:
                self._in_lobby = False
                self._on_leave()
            self._last_rect = None
            return

        if rect != self._last_rect:
            self._last_rect = rect
            self._on_move(*rect)

        img = capture_window()
        if img is None:
            print("[LobbyWatcher] 캡처 실패")
            return

        lobby = is_lobby(img, self._region)

        if lobby and not self._in_lobby:
            print("[LobbyWatcher] ✅ 로비 진입")
            self._in_lobby = True
            self._on_enter()
        elif not lobby and self._in_lobby:
            print("[LobbyWatcher] 🚪 로비 이탈")
            self._in_lobby = False
            self._on_leave()
