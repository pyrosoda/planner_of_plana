"""
Blue Archive Analyzer v6 entry point.
"""

import importlib.util
import os
import queue
import sys
import threading
from tkinter import TclError

import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REQUIRED = {
    "cv2": "opencv-python",
    "PIL": "pillow",
    "pygetwindow": "pygetwindow",
    "pyautogui": "pyautogui",
    "easyocr": "easyocr",
    "numpy": "numpy",
}
missing = [pkg for mod, pkg in REQUIRED.items() if not importlib.util.find_spec(mod)]
if missing:
    print(f"pip install {' '.join(missing)}")
    sys.exit(1)

from core.analyzer import analyze_scan_summary, is_student_maxed
from core.capture import clear_target, set_target_window
from core.config import load_config, load_regions, save_config
from core.db_writer import build_scan_meta
from core.lobby_watcher import LobbyWatcher, WatcherState
from core.log_context import set_debug_dump
from core.logger import LOG_APP, get_logger, setup_logging
from core.repository import ScanRepository
from core.scanner import ScanResult, Scanner
from core.states import AppState, StateMachine, can_transition
from core.template_cache import warmup_all
from gui.floating import FloatingOverlay
from gui.student_viewer import open_viewer
from gui.window_picker import WindowPicker

_log = get_logger(LOG_APP)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("BA Analyzer v6")
        self.protocol("WM_DELETE_WINDOW", self._on_close_requested)

        setup_logging()
        self._regions = load_regions()
        self._config = load_config()
        self._repo = ScanRepository()

        if self._config.get("debug_dump", False):
            from core.config import BASE_DIR

            set_debug_dump(enabled=True, dump_dir=BASE_DIR / "debug_dump")
            _log.info("debug dump enabled")

        warmup_all()

        self._sm = StateMachine(AppState.INIT, name="App")
        self._scanner: Scanner | None = None
        self._watcher: LobbyWatcher | None = None
        self._result: ScanResult | None = None
        self._scan_thread: threading.Thread | None = None
        self._asv = None
        self._closing = False
        self._shutdown_requested = False
        self._destroyed = False
        self._ui_queue: queue.Queue[tuple] = queue.Queue()

        self._overlay = FloatingOverlay(
            self,
            on_scan_items=lambda: self._request_scan("items"),
            on_scan_equipment=lambda: self._request_scan("equipment"),
            on_scan_students=lambda: self._request_scan("students"),
            on_scan_all=lambda: self._request_scan("all"),
            on_stop=self._stop_scan,
            on_settings=self._open_settings,
            on_view_students=lambda: open_viewer(self),
        )

        clear_target()
        self._transition_to(AppState.IDLE, reason="startup_ready")
        self.after(50, self._drain_ui_queue)
        self.after(300, self._open_window_picker)

    @property
    def state(self) -> AppState:
        return self._sm.state

    def _set_state(self, new: AppState, reason: str = "") -> bool:
        return self._sm.transition(new, reason=reason)

    def _force_state(self, new: AppState, reason: str = "") -> None:
        self._sm.force(new, reason=reason)

    def can_transition(self, from_state: AppState, to_state: AppState) -> bool:
        return can_transition(from_state, to_state)

    def _transition_to(self, new: AppState, reason: str = "", *, force: bool = False) -> bool:
        old = self.state
        ok = True
        if force:
            self._force_state(new, reason)
        else:
            ok = self._set_state(new, reason)
        if ok:
            self._apply_state_effects(old, new, reason)
        return ok

    def _apply_state_effects(self, old: AppState, new: AppState, reason: str) -> None:
        self._overlay.set_app_state(new)

        if new == AppState.IDLE:
            self._stop_watcher()
            self._overlay.hide()
            return

        if new == AppState.WATCHING:
            self._ensure_watcher_running()
            if self._watcher and self._watcher.in_lobby:
                self._overlay.show()
            else:
                self._overlay.hide()
            return

        if new == AppState.SCANNING:
            self._pause_watcher()
            self._overlay.hide()
            return

        if new == AppState.ERROR:
            if self._scanner:
                self._scanner.stop()
            self._pause_watcher()
            self._overlay.add_log("오류 상태 진입. 복구 동작만 허용됩니다.")
            self._overlay.show()
            return

        if new == AppState.STOPPING:
            if self._scanner:
                self._scanner.stop()
            self._pause_watcher()
            self._overlay.add_log("정리 중...")

    def _is_scanning(self) -> bool:
        return self.state == AppState.SCANNING

    def _is_stopping(self) -> bool:
        return self.state == AppState.STOPPING

    def _can_scan(self) -> bool:
        return self.state == AppState.WATCHING

    def _create_watcher(self) -> LobbyWatcher:
        lobby_region = self._regions["lobby"]["detect_flag"]
        return LobbyWatcher(
            lobby_region=lobby_region,
            on_enter=lambda: self._dispatch_ui(self._on_lobby_enter),
            on_leave=lambda: self._dispatch_ui(self._on_lobby_leave),
            on_window_move=lambda *_a: self._dispatch_ui(self._overlay._reposition),
        )

    def _dispatch_ui(self, callback, *args, **kwargs) -> bool:
        if self._destroyed or self._shutdown_requested:
            return False
        self._ui_queue.put((callback, args, kwargs))
        return True

    def _drain_ui_queue(self) -> None:
        if self._destroyed:
            return
        while True:
            try:
                callback, args, kwargs = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback(*args, **kwargs)
            except TclError:
                if not self._destroyed:
                    raise
            except Exception:
                _log.exception("ui callback failed")
        self.after(50, self._drain_ui_queue)

    def _ensure_watcher_running(self) -> None:
        if self._is_stopping():
            return
        if self._watcher is None:
            self._watcher = self._create_watcher()
            self._watcher.start()
            return
        if self._watcher.state == WatcherState.PAUSED:
            self._watcher.resume()
        elif self._watcher.state == WatcherState.RUNNING and self._watcher.is_alive:
            return
        elif self._watcher.state not in (WatcherState.RUNNING,):
            self._watcher.start()

    def _stop_watcher(self) -> None:
        if self._watcher is not None:
            stopped = self._watcher.stop()
            if stopped:
                self._watcher = None

    def _pause_watcher(self) -> None:
        if self._watcher and self._watcher.state == WatcherState.RUNNING:
            self._watcher.pause()

    def _on_lobby_enter(self) -> None:
        if self.state in (AppState.WATCHING, AppState.ERROR):
            self._overlay.show()

    def _on_lobby_leave(self) -> None:
        if self.state != AppState.SCANNING:
            self._overlay.hide()

    def _build_scanner(self, meta: dict) -> Scanner:
        from core.autosave import AutoSaveManager
        from core.config import BASE_DIR

        current_students = self._repo.load_current_students()
        maxed_ids: set[str] = set()
        maxed_cache: dict[str, dict] = {}
        for sid, data in current_students.items():
            if is_student_maxed(data):
                maxed_ids.add(sid)
                maxed_cache[sid] = data

        scan_id = meta.get("scan_id", "unknown")
        self._asv = AutoSaveManager(
            scan_id=scan_id,
            save_dir=BASE_DIR / "scans",
            on_save_ok=lambda msg: self._dispatch_ui(self._overlay.add_log, msg),
            on_save_fail=lambda msg: self._dispatch_ui(self._overlay.add_log, msg),
        )

        return Scanner(
            self._regions,
            on_progress=lambda msg: self._dispatch_ui(self._overlay.add_log, msg),
            maxed_ids=maxed_ids,
            maxed_cache=maxed_cache,
            autosave_manager=self._asv,
        )

    def _request_scan(self, mode: str) -> None:
        if self._is_scanning():
            self._overlay.add_log("이미 스캔 중입니다.")
            return
        if self._is_stopping():
            self._overlay.add_log("정리 중에는 새 작업을 시작할 수 없습니다.")
            return
        if self.state == AppState.ERROR:
            self._overlay.add_log("오류 상태에서는 복구 후 다시 시도해 주세요.")
            return
        if not self._can_scan():
            self._overlay.add_log(
                "창을 먼저 선택해 주세요." if self.state == AppState.IDLE else "현재 상태에서는 스캔할 수 없습니다."
            )
            return
        self._scan(mode)

    def _scan(self, mode: str) -> None:
        meta = build_scan_meta()
        self._result = None
        self._scanner = self._build_scanner(meta)
        if self._scanner:
            self._scanner.clear_stop()

        if not self._transition_to(AppState.SCANNING, reason=f"scan_requested:{mode}"):
            _log.error("failed to enter scanning state")
            return

        self.update_idletasks()

        def task():
            try:
                self._run_scan_task(mode, meta)
            finally:
                self._dispatch_ui(self._on_scan_finished)

        self._scan_thread = threading.Thread(target=task, name=f"Scanner-{mode}", daemon=True)
        self._scan_thread.start()

    def _run_scan_task(self, mode: str, meta: dict) -> None:
        result = ScanResult()
        scanner = self._scanner
        if scanner is None:
            return

        def not_stopped() -> bool:
            return not scanner._stop

        try:
            if mode in ("items", "all"):
                result.resources = scanner.scan_resources()
                self._dispatch_ui(self._overlay.update_resources, result.resources)
                result.items = scanner.scan_items()
                self._dispatch_ui(self._overlay.add_log, f"아이템 {len(result.items)}개")

            if mode in ("equipment", "all") and not_stopped():
                result.equipment = scanner.scan_equipment()
                self._dispatch_ui(self._overlay.add_log, f"장비 {len(result.equipment)}개")

            if mode in ("students", "all") and not_stopped():
                result.students = scanner.scan_students()
                skipped = sum(1 for s in result.students if s.skipped)
                self._dispatch_ui(
                    self._overlay.add_log,
                    f"학생 {len(result.students)}명 (스킵 {skipped})",
                )

            self._result = result
            self._auto_save(result, meta)
        except Exception as exc:
            import traceback

            traceback.print_exc()
            if self._asv:
                self._asv.emergency_save(result, meta)
            self._dispatch_ui(self._overlay.add_log, f"스캔 오류: {exc}")
            self._dispatch_ui(self._transition_to, AppState.ERROR, str(exc))

    def _on_scan_finished(self) -> None:
        self._scanner = None
        self._scan_thread = None

        if self._shutdown_requested:
            self._finish_shutdown(reason="scan_thread_finished")
            return

        if self.state == AppState.STOPPING:
            next_state = AppState.WATCHING if self._config.get("target_hwnd") else AppState.IDLE
            self._transition_to(next_state, reason="stop_cleanup_finished")
            return

        if self.state == AppState.SCANNING:
            self._transition_to(AppState.WATCHING, reason="scan_finished")
            return

    def _stop_scan(self) -> None:
        if self.state not in (AppState.SCANNING, AppState.PAUSED):
            return
        self._overlay.add_log("스캔 중지 요청...")
        self._transition_to(AppState.STOPPING, reason="user_stop_requested")

    def _auto_save(self, result: ScanResult, meta: dict) -> None:
        from core.config import BASE_DIR
        from core.serializer import make_status_report, save_scan_json

        scan_id = meta.get("scan_id", "unknown")
        try:
            if self._asv:
                if not self._asv.final_save(result, meta):
                    raise RuntimeError("최종 저장 파일 작성 실패")
            else:
                json_path = BASE_DIR / "scans" / f"{scan_id}.json"
                save_scan_json(result, json_path, meta)
                _log.info(f"scan json saved: {json_path}")
            self._repo.save(result, meta)
            self._dispatch_ui(self._overlay.add_log, f"저장 완료 ({scan_id})")

            for line in make_status_report(result):
                self._dispatch_ui(self._overlay.add_log, line)

            if not result.students:
                return

            current_students = list(self._repo.load_current_students().values())
            all_changes = self._repo.load_student_changes()
            this_changes = [c for c in all_changes if c.get("scan_id") == scan_id]
            summary = analyze_scan_summary(current_students, this_changes, scan_id)

            if summary.total_field_changes:
                self._dispatch_ui(
                    self._overlay.add_log,
                    f"변경 {summary.total_field_changes}건 ({summary.changed_students}명)",
                )

            if summary.low_confidence:
                self._dispatch_ui(
                    self._overlay.add_log,
                    f"낮은 신뢰도 학생 {len(summary.low_confidence)}명",
                )
        except Exception as exc:
            import traceback

            traceback.print_exc()
            self._dispatch_ui(self._overlay.add_log, f"저장 실패: {exc}")
            self._dispatch_ui(self._transition_to, AppState.ERROR, f"save_failed:{exc}")

    def _open_window_picker(self) -> None:
        if self.state in (AppState.SCANNING, AppState.STOPPING):
            self._overlay.add_log("스캔/정리 중에는 창을 다시 선택할 수 없습니다.")
            return

        previous_hwnd = self._config.get("target_hwnd")
        previous_title = self._config.get("target_title", "")

        self._transition_to(AppState.IDLE, reason="window_picker_open")
        clear_target()

        def on_select(hwnd: int, title: str) -> None:
            self._config["target_hwnd"] = hwnd
            self._config["target_title"] = title
            save_config(self._config)
            set_target_window(hwnd, title)
            self._overlay.add_log(f"창 설정: {title}")
            self._transition_to(AppState.WATCHING, reason="window_selected")

        def on_cancel() -> None:
            if previous_hwnd:
                set_target_window(previous_hwnd, previous_title)
                self._transition_to(AppState.WATCHING, reason="window_picker_cancelled")
            else:
                self.destroy()

        WindowPicker(self, on_select=on_select, on_cancel=on_cancel)

    def _open_settings(self) -> None:
        self._open_window_picker()

    def _on_close_requested(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._shutdown_requested = True
        self._transition_to(AppState.STOPPING, reason="app_close")
        self._wait_for_shutdown()

    def _wait_for_shutdown(self) -> None:
        if self._destroyed:
            return

        thread = self._scan_thread
        if thread and thread.is_alive():
            self.after(100, self._wait_for_shutdown)
            return

        self._finish_shutdown(reason="shutdown_ready")

    def _finish_shutdown(self, reason: str) -> None:
        if self._destroyed:
            return

        if self.state != AppState.STOPPING:
            self._transition_to(AppState.STOPPING, reason=reason)

        self._stop_watcher()
        self._destroyed = True
        try:
            self._overlay.destroy()
        except TclError:
            pass
        self.destroy()

    def run(self) -> None:
        self.mainloop()


if __name__ == "__main__":
    App().run()
