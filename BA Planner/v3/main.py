"""
main.py — Blue Archive Analyzer v3
플로팅 오버레이 + 로비 감지 + 자동 스캔
"""
import sys
import os
import threading
import importlib.util
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 패키지 체크 ───────────────────────────────────────────
REQUIRED = {
    "customtkinter": "customtkinter",
    "PIL":           "pillow",
    "pygetwindow":   "pygetwindow",
    "pyautogui":     "pyautogui",
    "easyocr":       "easyocr",
    "numpy":         "numpy",
}
missing = [pkg for mod, pkg in REQUIRED.items()
           if not importlib.util.find_spec(mod)]
if missing:
    print(f"❌ pip install {' '.join(missing)}")
    sys.exit(1)

import tkinter as tk
from core.config   import load_config, config_exists, save_config
from core.scanner  import Scanner, ScanResult
from core.lobby_watcher import LobbyWatcher
from gui.setup     import SetupWizard
from gui.floating  import FloatingOverlay


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()   # 루트 창 숨김 (플로팅만 표시)
        self.title("BA Analyzer")

        self._config  = load_config()
        self._scanner: Scanner | None       = None
        self._watcher: LobbyWatcher | None  = None
        self._overlay: FloatingOverlay | None = None
        self._last_result: ScanResult | None  = None

        self._build_overlay()

        if config_exists():
            self._start_watcher()
        else:
            # 첫 실행 → 설정 위자드
            self.after(300, self._open_setup)

    # ── 오버레이 생성 ─────────────────────────────────────
    def _build_overlay(self):
        self._overlay = FloatingOverlay(
            self,
            on_scan_items=     lambda: self._start_scan("items"),
            on_scan_equipment= lambda: self._start_scan("equipment"),
            on_scan_students=  lambda: self._start_scan("students"),
            on_open_settings=  self._open_setup,
        )

    # ── 로비 감지 워처 ────────────────────────────────────
    def _start_watcher(self):
        cfg = self._config
        nickname = cfg.get("nickname", "")
        nick_region = cfg.get("nickname_region")

        if not nickname or not nick_region:
            self._open_setup()
            return

        self._watcher = LobbyWatcher(
            nickname=nickname,
            nickname_region=nick_region,
            on_lobby_enter=self._on_lobby_enter,
            on_lobby_leave=self._on_lobby_leave,
            on_window_move=self._on_window_move,
        )
        self._watcher.start()

    def _on_lobby_enter(self):
        self.after(0, lambda: self._overlay.show())

    def _on_lobby_leave(self):
        self.after(0, lambda: self._overlay.hide())

    def _on_window_move(self, l, t, w, h):
        self.after(0, lambda: self._overlay._reposition())

    # ── 스캔 ──────────────────────────────────────────────
    def _start_scan(self, mode: str):
        if not self._config:
            self._overlay.add_log("❌ 설정이 없어")
            return

        self._scanner = Scanner(
            self._config,
            on_progress=lambda msg: self.after(0, lambda: self._overlay.add_log(msg))
        )
        self._overlay.set_scanning(True)

        def task():
            try:
                if mode == "items":
                    items = self._scanner.scan_items()
                    res   = self._scanner.scan_resources()
                    self.after(0, lambda: self._overlay.update_resources(res))
                    self.after(0, lambda: self._overlay.add_log(
                        f"✅ 아이템 {len(items)}개 완료"))

                elif mode == "equipment":
                    equip = self._scanner.scan_equipment()
                    self.after(0, lambda: self._overlay.add_log(
                        f"✅ 장비 {len(equip)}개 완료"))

                elif mode == "students":
                    self.after(0, lambda: self._overlay.add_log(
                        "👩 학생 스캔은 준비 중이야"))

            except Exception as e:
                self.after(0, lambda: self._overlay.add_log(f"❌ {e}"))
            finally:
                self.after(0, lambda: self._overlay.set_scanning(False))

        threading.Thread(target=task, daemon=True).start()

    # ── 설정 위자드 ───────────────────────────────────────
    def _open_setup(self):
        # 오버레이 숨기고 위자드 시작
        if self._overlay:
            self._overlay.hide()
        if self._watcher:
            self._watcher.stop()

        def on_complete(results: dict):
            self._config = results
            save_config(results)
            self._start_watcher()

        def on_cancel():
            if self._config:
                self._start_watcher()

        wizard = SetupWizard(self,
                             on_complete=on_complete,
                             on_cancel=on_cancel)
        wizard.start()

    def run(self):
        self.mainloop()


if __name__ == "__main__":
    App().run()