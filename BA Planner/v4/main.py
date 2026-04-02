"""
main.py — Blue Archive Analyzer v4
OCR 없이 템플릿 매칭 중심, 플로팅 오버레이
"""
import sys
import os
import threading
import json
import importlib.util
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 패키지 체크 ───────────────────────────────────────────
REQUIRED = {
    "cv2":          "opencv-python",
    "PIL":          "pillow",
    "pygetwindow":  "pygetwindow",
    "pyautogui":    "pyautogui",
    "easyocr":      "easyocr",
    "numpy":        "numpy",
}
missing = [pkg for mod, pkg in REQUIRED.items()
           if not importlib.util.find_spec(mod)]
if missing:
    print(f"❌ pip install {' '.join(missing)}")
    sys.exit(1)

import tkinter as tk
from datetime import datetime

from core.config        import load_regions, load_config, save_config
from core.capture       import clear_target
from core.lobby_watcher import LobbyWatcher
from core.scanner       import Scanner, ScanResult
from gui.floating       import FloatingOverlay
from gui.window_picker  import WindowPicker


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("BA Analyzer v4")

        self._regions = load_regions()
        self._config  = load_config()
        self._result: ScanResult | None = None
        self._scanner: Scanner | None = None
        self._watcher: LobbyWatcher | None = None

        self._overlay = FloatingOverlay(
            self,
            on_scan_items=     lambda: self._scan("items"),
            on_scan_equipment= lambda: self._scan("equipment"),
            on_scan_students=  lambda: self._scan("students"),
            on_scan_all=       lambda: self._scan("all"),
            on_stop=           self._stop_scan,
            on_settings=       self._open_settings,
        )

        # 시작할 때마다 무조건 창 선택을 다시 받음
        clear_target()
        self.after(300, self._open_window_picker)

    # ── 로비 감지 ─────────────────────────────────────────
    def _start_watcher(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        lobby_region = self._regions["lobby"]["detect_flag"]
        self._watcher = LobbyWatcher(
            lobby_region=lobby_region,
            on_enter=lambda: self.after(0, self._overlay.show),
            on_leave=lambda: self.after(0, self._overlay.hide),
            on_window_move=lambda *a: self.after(0, self._overlay._reposition),
        )
        self._watcher.start()

    # ── 스캔 ──────────────────────────────────────────────
    def _scan(self, mode: str):
        self._scanner = Scanner(
            self._regions,
            on_progress=lambda msg: self.after(
                0, lambda m=msg: self._overlay.add_log(m)
            )
        )
        self._overlay.set_scanning(True)

        def task():
            try:
                result = ScanResult()

                if mode in ("items", "all"):
                    result.resources = self._scanner.scan_resources()
                    self.after(0, lambda: self._overlay.update_resources(
                        result.resources
                    ))
                    result.items = self._scanner.scan_items()
                    self.after(0, lambda: self._overlay.add_log(
                        f"✅ 아이템 {len(result.items)}개"
                    ))

                if mode in ("equipment", "all") and not self._scanner._stop:
                    result.equipment = self._scanner.scan_equipment()
                    self.after(0, lambda: self._overlay.add_log(
                        f"✅ 장비 {len(result.equipment)}개"
                    ))

                if mode in ("students", "all") and not self._scanner._stop:
                    result.students = self._scanner.scan_students()
                    self.after(0, lambda: self._overlay.add_log(
                        f"✅ 학생 {len(result.students)}명"
                    ))

                self._result = result
                self._auto_save(result)

            except Exception as e:
                self.after(0, lambda: self._overlay.add_log(f"❌ {e}"))
                import traceback
                traceback.print_exc()
            finally:
                self.after(0, lambda: self._overlay.set_scanning(False))

        threading.Thread(target=task, daemon=True).start()

    # ── 자동 저장 ─────────────────────────────────────────
    def _auto_save(self, result: ScanResult):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        out_dir = Path(__file__).resolve().parent / "scan_results"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"scan_result_{ts}.json"

        data = {
            "scanned_at": ts,
            "resources": result.resources,
            "items": [
                {
                    "index": i.index,
                    "name": i.name,
                    "quantity": i.quantity,
                }
                for i in result.items
            ],
            "equipment": [
                {
                    "index": i.index,
                    "name": i.name,
                    "quantity": i.quantity,
                }
                for i in result.equipment
            ],
            "students": [
                {
                    "name": s.name,
                    "costume": s.costume,
                    "display": f"{s.name}({s.costume})" if s.costume else s.name,
                    "level": s.level,
                    "stars": s.stars,
                    "weapon_locked": s.weapon_locked,
                    "weapon_stars": s.weapon_stars,
                    "weapon_level": s.weapon_level,
                    "ex_skill": s.ex_skill,
                    "skill1": s.skill1,
                    "skill2": s.skill2,
                    "skill3": s.skill3,
                    "equip1": s.equip1,
                    "equip2": s.equip2,
                    "equip3": s.equip3,
                    "equip4": s.equip4,
                }
                for s in result.students
            ],
        }

        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"[App] 결과 저장: {path}")
        self.after(0, lambda: self._overlay.add_log(f"💾 {path.name}"))

    # ── 창 선택 ───────────────────────────────────────────
    def _open_window_picker(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        self._overlay.hide()
        clear_target()

        def on_select(hwnd: int, title: str):
            self._config["target_hwnd"] = hwnd
            self._config["target_title"] = title
            save_config(self._config)

            self._overlay.add_log(f"🎯 창 설정: {title}")
            self._start_watcher()

        def on_cancel():
            self.destroy()

        WindowPicker(self, on_select=on_select, on_cancel=on_cancel)

    # ── 정지 ──────────────────────────────────────────────
    def _stop_scan(self):
        if self._scanner:
            self._scanner.stop()
            self._overlay.add_log("⏹ 스캔 중지 요청...")

    # ── 설정 ──────────────────────────────────────────────
    def _open_settings(self):
        self._open_window_picker()

    def run(self):
        self.mainloop()


if __name__ == "__main__":
    App().run()