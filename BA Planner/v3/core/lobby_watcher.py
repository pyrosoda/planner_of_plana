"""
core/lobby_watcher.py
블루아카이브 창을 주기적으로 감시하며 로비 여부를 판단.
닉네임 영역 OCR로 로비 감지.
"""
import threading
import time
from typing import Callable

from core.capture import capture_window, crop_ratio, get_window_rect
from core.ocr import read_nickname_region


class LobbyWatcher:
    """
    백그라운드 스레드로 블루아카이브 창 상태를 감시.

    콜백:
      on_lobby_enter()  — 로비 진입 감지
      on_lobby_leave()  — 로비 이탈 감지
      on_window_move(left, top, w, h) — 창 이동/리사이즈
    """

    CHECK_INTERVAL = 2.5   # 초
    NICKNAME_THRESHOLD = 0.6  # 닉네임 유사도 임계값

    def __init__(self,
                 nickname: str,
                 nickname_region: dict,
                 on_lobby_enter: Callable = None,
                 on_lobby_leave: Callable = None,
                 on_window_move: Callable = None):
        self.nickname = nickname.strip().lower()
        self.nickname_region = nickname_region
        self.on_lobby_enter = on_lobby_enter or (lambda: None)
        self.on_lobby_leave = on_lobby_leave or (lambda: None)
        self.on_window_move = on_window_move or (lambda *a: None)

        self._running = False
        self._thread: threading.Thread | None = None
        self._in_lobby = False
        self._last_rect = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
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
            time.sleep(self.CHECK_INTERVAL)

    def _check(self):
        rect = get_window_rect()

        # 창 없음
        if rect is None:
            print("[LobbyWatcher] 블루아카이브 창을 찾지 못했어")
            if self._in_lobby:
                self._in_lobby = False
                self.on_lobby_leave()
            self._last_rect = None
            return

        # 창 발견
        l, t, w, h = rect
        print(f"[LobbyWatcher] 창 감지: pos=({l},{t}) size=({w}x{h})")

        # 창 이동/리사이즈 감지
        if rect != self._last_rect:
            self._last_rect = rect
            self.on_window_move(*rect)

        # 로비 감지: 닉네임 영역 OCR
        img = capture_window()
        if img is None:
            print("[LobbyWatcher] 캡처 실패")
            return

        print(f"[LobbyWatcher] 캡처 성공: {img.size}")
        print(f"[LobbyWatcher] 닉네임 영역: {self.nickname_region}")

        cropped = crop_ratio(img, self.nickname_region)
        print(f"[LobbyWatcher] 크롭 크기: {cropped.size}")

        detected = read_nickname_region(cropped).lower()
        print(f"[LobbyWatcher] OCR 결과: '{detected}'")
        print(f"[LobbyWatcher] 찾는 닉네임: '{self.nickname}'")

        is_lobby = self.nickname in detected
        print(f"[LobbyWatcher] 로비 여부: {is_lobby}  (현재 상태: {self._in_lobby})")

        if is_lobby and not self._in_lobby:
            print("[LobbyWatcher] ✅ 로비 진입!")
            self._in_lobby = True
            self.on_lobby_enter()
        elif not is_lobby and self._in_lobby:
            print("[LobbyWatcher] 🚪 로비 이탈")
            self._in_lobby = False
            self.on_lobby_leave()