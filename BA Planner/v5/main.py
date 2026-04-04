"""
main.py — Blue Archive Analyzer v5.2
"""
import sys
import os
import threading
import importlib.util
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REQUIRED = {
    "cv2":         "opencv-python",
    "PIL":         "pillow",
    "pygetwindow": "pygetwindow",
    "pyautogui":   "pyautogui",
    "easyocr":     "easyocr",
    "numpy":       "numpy",
}
missing = [pkg for mod, pkg in REQUIRED.items() if not importlib.util.find_spec(mod)]
if missing:
    print(f"❌ pip install {' '.join(missing)}")
    sys.exit(1)

import tkinter as tk

from core.config        import load_regions, load_config, save_config
from core.capture       import clear_target
from core.lobby_watcher import LobbyWatcher
from core.scanner       import Scanner, ScanResult
from core.db_writer     import build_scan_meta
from core.repository    import ScanRepository
from core.analyzer      import analyze_scan_summary, is_student_maxed
import core.student_names as student_names
from gui.floating       import FloatingOverlay
from gui.window_picker  import WindowPicker


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("BA Analyzer v5")

        self._regions = load_regions()
        self._config  = load_config()
        self._result:  ScanResult | None    = None
        self._scanner: Scanner | None       = None
        self._watcher: LobbyWatcher | None  = None
        self._repo    = ScanRepository()

        self._overlay = FloatingOverlay(
            self,
            on_scan_items=     lambda: self._scan("items"),
            on_scan_equipment= lambda: self._scan("equipment"),
            on_scan_students=  lambda: self._scan("students"),
            on_scan_all=       lambda: self._scan("all"),
            on_stop=           self._stop_scan,
            on_settings=       self._open_settings,
        )

        clear_target()
        self.after(300, self._open_window_picker)

    # ── 로비 감시 ─────────────────────────────────────────
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

    # ── Scanner 생성 (만렙 스킵 목록 주입) ───────────────
    def _build_scanner(self) -> Scanner:
        """
        repository에서 만렙 학생 목록을 로드해 Scanner에 주입.
        스캔 시작 시마다 호출해 항상 최신 상태를 반영.
        """
        current_students = self._repo.load_current_students()

        maxed_ids:    set[str]        = set()
        maxed_cache:  dict[str, dict] = {}

        for sid, data in current_students.items():
            if is_student_maxed(data):
                maxed_ids.add(sid)
                maxed_cache[sid] = data

        if maxed_ids:
            print(f"[App] 만렙 스킵 대상: {len(maxed_ids)}명")

        return Scanner(
            self._regions,
            on_progress=lambda msg: self.after(0, lambda m=msg: self._overlay.add_log(m)),
            maxed_ids=maxed_ids,
            maxed_cache=maxed_cache,
        )

    # ── 스캔 ──────────────────────────────────────────────
    def _scan(self, mode: str):
        meta = build_scan_meta()
        self._scanner = self._build_scanner()

        self._overlay.set_scanning(True)
        self._overlay.hide()
        self.update_idletasks()
        self.update()

        def task():
            try:
                result = ScanResult()

                if mode in ("items", "all"):
                    result.resources = self._scanner.scan_resources()
                    self.after(0, lambda: self._overlay.update_resources(result.resources))
                    result.items = self._scanner.scan_items()
                    self.after(0, lambda: self._overlay.add_log(
                        f"✅ 아이템 {len(result.items)}개"))

                if mode in ("equipment", "all") and not self._scanner._stop:
                    result.equipment = self._scanner.scan_equipment()
                    self.after(0, lambda: self._overlay.add_log(
                        f"✅ 장비 {len(result.equipment)}개"))

                if mode in ("students", "all") and not self._scanner._stop:
                    result.students = self._scanner.scan_students()
                    skipped = sum(1 for s in result.students if s.skipped)
                    self.after(0, lambda: self._overlay.add_log(
                        f"✅ 학생 {len(result.students)}명 "
                        f"(스킵:{skipped})"))

                self._result = result
                self._auto_save(result, meta)

            except Exception as e:
                self.after(0, lambda: self._overlay.add_log(f"❌ {e}"))
                import traceback; traceback.print_exc()
            finally:
                self.after(0, lambda: self._overlay.set_scanning(False))

        self.after(180, lambda: threading.Thread(target=task, daemon=True).start())

    # ── 저장 ──────────────────────────────────────────────
    def _auto_save(self, result: ScanResult, meta: dict):
        scan_id = meta["scan_id"]
        try:
            self._repo.save(result, meta)
            self.after(0, lambda: self._overlay.add_log(f"💾 저장 완료 ({scan_id})"))

            if result.students:
                current_students = list(self._repo.load_current_students().values())
                all_changes      = self._repo.load_student_changes()
                this_changes     = [c for c in all_changes if c.get("scan_id") == scan_id]
                summary = analyze_scan_summary(current_students, this_changes, scan_id)

                if summary.total_field_changes:
                    self.after(0, lambda: self._overlay.add_log(
                        f"📝 변경 {summary.total_field_changes}건 "
                        f"({summary.changed_students}명)"))
                    top = sorted(summary.changed_fields_freq.items(),
                                 key=lambda x: x[1], reverse=True)[:3]
                    for fn, cnt in top:
                        self.after(0, lambda fn=fn, cnt=cnt:
                            self._overlay.add_log(f"  · {fn}: {cnt}건"))

                if summary.low_confidence:
                    self.after(0, lambda: self._overlay.add_log(
                        f"⚠️  신뢰도 낮음: {len(summary.low_confidence)}명"))

                if summary.maxed_students:
                    self.after(0, lambda: self._overlay.add_log(
                        f"⭐ 만렙 도달: {len(summary.maxed_students)}명"))

        except Exception as e:
            print(f"[App] 저장 실패: {e}")
            import traceback; traceback.print_exc()
            self.after(0, lambda: self._overlay.add_log(f"❌ 저장 실패: {e}"))

    # ── 창 선택 / 설정 ────────────────────────────────────
    def _open_window_picker(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        self._overlay.hide()
        clear_target()

        def on_select(hwnd, title):
            self._config["target_hwnd"]  = hwnd
            self._config["target_title"] = title
            save_config(self._config)
            self._overlay.add_log(f"🎯 창 설정: {title}")
            self._start_watcher()

        WindowPicker(self, on_select=on_select, on_cancel=lambda: self.destroy())

    def _stop_scan(self):
        if self._scanner:
            self._scanner.stop()
            self._overlay.add_log("⏹ 스캔 중지 요청...")

    def _open_settings(self):
        self._open_window_picker()

    def run(self):
        self.mainloop()


if __name__ == "__main__":
    App().run()