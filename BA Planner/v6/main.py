"""
Blue Archive Analyzer v6 entry point.
"""

import ctypes
import hashlib
import importlib.util
import os
import queue
import sys
import threading
import traceback
from tkinter import TclError

import tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ERROR_ALREADY_EXISTS = 183
_kernel32 = None

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    _kernel32.CreateMutexW.restype = ctypes.c_void_p
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    _kernel32.CloseHandle.restype = ctypes.c_bool


class SingleInstanceGuard:
    def __init__(self, name: str):
        self._name = name
        self._handle = None

    def acquire(self) -> bool:
        if _kernel32 is None:
            return True
        if self._handle is not None:
            return True

        handle = _kernel32.CreateMutexW(None, False, self._name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(handle)
            return False

        self._handle = handle
        return True

    def release(self) -> None:
        if _kernel32 is None or self._handle is None:
            return
        _kernel32.CloseHandle(self._handle)
        self._handle = None


def _build_single_instance_name() -> str:
    script_path = os.path.abspath(__file__).encode("utf-8")
    digest = hashlib.sha1(script_path).hexdigest()[:12]
    return f"Local\\BAAnalyzerV6Main_{digest}"


_STARTUP_INSTANCE_GUARD: SingleInstanceGuard | None = None


def _ensure_single_instance() -> bool:
    global _STARTUP_INSTANCE_GUARD
    if _STARTUP_INSTANCE_GUARD is not None:
        return True

    guard = SingleInstanceGuard(_build_single_instance_name())
    if not guard.acquire():
        return False

    _STARTUP_INSTANCE_GUARD = guard
    return True


if __name__ == "__main__" and not _ensure_single_instance():
    print("BA Analyzer v6 is already running. Closing the new instance.")
    sys.exit(0)

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
    print(f"Missing required packages: {', '.join(missing)}")
    print(f"Run: {sys.executable} -m pip install {' '.join(missing)}")
    print(f"Or:  {sys.executable} -m pip install -r requirements.txt")
    sys.exit(1)

try:
    from core.analyzer import analyze_scan_summary, is_student_maxed
    from core.capture import clear_target, find_target_hwnd, get_target_info, set_target_window
    from core.config import (
        activate_profile,
        get_active_profile_name,
        list_profiles,
        load_config,
        load_regions,
        save_config,
    )
    from core.db_writer import build_scan_meta
    from core.inventory_profiles import inventory_profile_label
    from core.lobby_watcher import LobbyWatcher, WatcherState
    from core.log_context import set_debug_dump
    from core.logger import LOG_APP, get_logger, setup_logging
    from core.repository import ScanRepository
    from core.scanner import ScanResult, Scanner
    from core.student_order import ordered_owned_student_rows, ordered_student_rows
    from core.states import AppState, StateMachine, can_transition
    from core.template_cache import warmup_all
    from gui.fast_scan_config_dialog import edit_fast_scan_config
    from gui.fast_scan_dialog import choose_fast_scan_action
    from gui.floating import FloatingOverlay
    from gui.input_test_overlay import InputTestOverlay
    from gui.profile_dialog import choose_profile
    from gui.viewer_launcher import open_student_viewer
    from gui.window_picker import WindowPicker
except ModuleNotFoundError as exc:
    missing_module = exc.name or "unknown module"
    print(f"Startup import failed: missing module '{missing_module}'")
    print(f"Run: {sys.executable} -m pip install -r requirements.txt")
    traceback.print_exc()
    sys.exit(1)

_log = get_logger(LOG_APP)

_ITEM_SCAN_FILTER_OPTIONS: list[tuple[str, str]] = [
    ("all", "전체"),
    ("tech_notes", "기술 노트"),
    ("tactical_bd", "전술 교육 BD"),
    ("ooparts", "오파츠"),
    ("coins", "코인"),
    ("activity_reports", "활동 보고서"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("BA Analyzer v6")
        self.protocol("WM_DELETE_WINDOW", self._on_close_requested)

        setup_logging()
        _log.info("app init: loading regions")
        self._regions = load_regions()
        profiles = list_profiles()
        last_profile = get_active_profile_name()
        _log.info(
            "app init: opening profile dialog (profiles=%d, last_profile=%s)",
            len(profiles),
            last_profile or "<none>",
        )
        selected_profile = choose_profile(
            self,
            profiles,
            last_profile=last_profile,
        )
        if not selected_profile:
            _log.info("app init: profile selection cancelled")
            self._destroyed = True
            self.destroy()
            return

        _log.info("app init: selected profile '%s'", selected_profile)
        self._storage = activate_profile(selected_profile)
        self._config = load_config()
        self._profile_name = self._storage.profile_name
        self.title(f"BA Analyzer v6 - {self._profile_name}")
        self._repo = ScanRepository(base_dir=self._storage.data_dir)

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
        self._target_close_handled = False
        self._ui_queue: queue.Queue[tuple] = queue.Queue()
        self._last_item_scan_filter = "all"

        self._overlay = FloatingOverlay(
            self,
            on_scan_items=lambda: self._request_scan("items"),
            on_scan_equipment=lambda: self._request_scan("equipment"),
            on_scan_students=lambda: self._request_scan("students"),
            on_scan_current_student=lambda: self._request_scan("student_current"),
            on_scan_all=lambda: self._request_scan("all"),
            on_stop=self._stop_scan,
            on_input_test=self._open_input_test,
            on_settings=self._open_settings,
            on_view_students=lambda: open_student_viewer(self),
        )
        self._input_test_overlay = InputTestOverlay(self)

        clear_target()
        self._transition_to(AppState.IDLE, reason="startup_ready")
        self.after(50, self._drain_ui_queue)
        self.after(500, self._poll_target_window)
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
            self._input_test_overlay.hide()
            self._overlay.hide()
            return

        if new == AppState.WATCHING:
            self._ensure_watcher_running()
            if self._watcher and self._watcher.in_lobby:
                self._overlay.set_lobby_state(True)
                self._overlay.show()
            else:
                self._overlay.set_lobby_state(False)
                self._overlay.show()
            return

        if new == AppState.SCANNING:
            self._pause_watcher()
            self._input_test_overlay.hide()
            self._overlay.show()
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
            self._input_test_overlay.hide()
            self._overlay.add_log("정리 중...")
            self._overlay.show()

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
            on_target_closed=lambda: self._dispatch_ui(self._on_target_window_closed, "watcher"),
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

    def _poll_target_window(self) -> None:
        if self._destroyed:
            return
        try:
            self._check_target_window_closed(source="poll")
        finally:
            if not self._destroyed:
                self.after(500, self._poll_target_window)

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
        self._overlay.set_lobby_state(True)
        if self.state in (AppState.WATCHING, AppState.ERROR):
            self._overlay.show()

    def _on_lobby_leave(self) -> None:
        self._overlay.set_lobby_state(False)
        if self.state == AppState.WATCHING:
            self._overlay.show()
        elif self.state != AppState.SCANNING:
            self._overlay.hide()

    def _check_target_window_closed(self, *, source: str) -> None:
        if self._destroyed or self._shutdown_requested:
            return
        target_hwnd, target_title = get_target_info()
        if not target_hwnd:
            return
        if find_target_hwnd() is not None:
            return
        self._on_target_window_closed(source, target_title)

    def _on_target_window_closed(self, source: str, title: str = "") -> None:
        if self._destroyed or self._shutdown_requested or self._target_close_handled:
            return
        self._target_close_handled = True
        target_name = title or self._config.get("target_title", "") or "selected target window"
        _log.info("target window closed; shutting down app (source=%s, title=%s)", source, target_name)
        self._overlay.add_log(f"타겟 창이 닫혀서 BA Analyzer도 함께 종료합니다: {target_name}")
        self._on_close_requested()

    def _build_scanner(self, meta: dict) -> Scanner:
        from core.autosave import AutoSaveManager

        current_students = self._repo.load_current_students()
        maxed_ids: set[str] = set()
        maxed_saved_data: dict[str, dict] = {}
        for sid, data in current_students.items():
            if is_student_maxed(data):
                maxed_ids.add(sid)
                maxed_saved_data[sid] = data

        scan_id = meta.get("scan_id", "unknown")
        self._asv = AutoSaveManager(
            scan_id=scan_id,
            save_dir=self._storage.scans_dir,
            on_save_ok=lambda msg: self._dispatch_ui(self._overlay.add_log, msg),
            on_save_fail=lambda msg: self._dispatch_ui(self._overlay.add_log, msg),
        )

        return Scanner(
            self._regions,
            on_progress=lambda msg: self._dispatch_ui(self._overlay.add_log, msg),
            on_progress_state=lambda state: self._dispatch_ui(
                self._overlay.set_scan_progress,
                state.get("current"),
                state.get("total"),
                state.get("note", ""),
            ),
            maxed_ids=maxed_ids,
            maxed_saved_data=maxed_saved_data,
            student_saved_data=current_students,
            student_total_hint=len(current_students) or None,
            autosave_manager=self._asv,
            inventory_profile_id=meta.get("item_scan_filter_profile") or None,
            fast_student_ids=meta.get("fast_student_ids") or None,
        )

    def _choose_item_scan_filter(self) -> str | None:
        dialog = tk.Toplevel(self)
        dialog.title("아이템 스캔 필터")
        dialog.resizable(False, False)
        try:
            if bool(self.winfo_viewable()):
                dialog.transient(self)
        except Exception:
            pass
        dialog.grab_set()

        selected = tk.StringVar(value=self._last_item_scan_filter)
        result: dict[str, str | None] = {"value": None}

        frame = tk.Frame(dialog, padx=14, pady=14)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="이번 아이템 스캔에서 사용할 필터를 선택하세요.",
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 10))

        for value, label in _ITEM_SCAN_FILTER_OPTIONS:
            tk.Radiobutton(
                frame,
                text=label,
                value=value,
                variable=selected,
                anchor="w",
                justify="left",
            ).pack(fill="x", pady=1)

        buttons = tk.Frame(frame)
        buttons.pack(fill="x", pady=(12, 0))

        def submit() -> None:
            result["value"] = selected.get()
            dialog.destroy()

        def cancel() -> None:
            result["value"] = None
            dialog.destroy()

        tk.Button(buttons, text="취소", command=cancel).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="확인", command=submit).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.update_idletasks()
        width = dialog.winfo_reqwidth()
        height = dialog.winfo_reqheight()
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        dialog.geometry(f"+{(sw - width) // 2}+{(sh - height) // 2}")
        dialog.deiconify()
        dialog.lift()
        dialog.attributes("-topmost", True)
        dialog.after(250, lambda: dialog.attributes("-topmost", False))
        dialog.focus_force()
        dialog.wait_window()
        choice = result["value"]
        if choice:
            self._last_item_scan_filter = choice
        return choice

    def _restore_last_fast_scan_backup(self) -> bool:
        try:
            restored = self._repo.restore_student_snapshot_backup()
        except FileNotFoundError:
            self._overlay.add_log("복원할 빠른 스캔 백업이 없습니다.")
            return False
        except Exception as exc:
            self._overlay.add_log(f"빠른 스캔 롤백 실패: {exc}")
            return False

        self._overlay.add_log(
            "빠른 스캔 롤백 완료: "
            f"{restored['student_count']}명 "
            f"({restored.get('scan_id') or 'unknown'})"
        )
        return True

    def _choose_student_scan_strategy(self, mode: str) -> dict | None:
        current_students = self._repo.load_current_students()
        saved_rows = ordered_owned_student_rows(current_students)
        saved_student_ids = [student_id for student_id, _name in saved_rows]
        mode_label = "전체 스캔" if mode == "all" else "학생 스캔"
        has_rollback = self._repo.latest_student_snapshot_backup() is not None

        configured_ids = self._repo.load_fast_scan_roster()

        while True:
            active_ids = list(configured_ids or saved_student_ids)
            ordered_students = ordered_student_rows(active_ids)
            if configured_ids:
                roster_source_label = "설정 목록"
            elif saved_student_ids:
                roster_source_label = "저장 데이터"
            else:
                roster_source_label = "설정 필요"

            result = choose_fast_scan_action(
                self,
                ordered_students=ordered_students,
                has_rollback=has_rollback,
                mode_label=mode_label,
                roster_source_label=roster_source_label,
                saved_student_count=len(saved_student_ids),
            )
            if result.action == "rollback":
                self._restore_last_fast_scan_backup()
                return {"student_scan_strategy": "rollback_only"}
            if result.action == "cancel":
                return None
            if result.action == "edit":
                editor = edit_fast_scan_config(
                    self,
                    initial_selected_ids=active_ids,
                    saved_student_count=len(saved_student_ids),
                )
                if not editor.saved:
                    continue
                self._repo.save_fast_scan_roster(
                    editor.student_ids,
                    source="user_config",
                    extra_meta={
                        "saved_student_count": len(saved_student_ids),
                        "mode": mode,
                    },
                )
                configured_ids = editor.student_ids
                self._overlay.add_log(f"빠른 스캔 기준 목록 저장: {len(configured_ids)}명")
                continue
            if result.action == "fast":
                if not active_ids:
                    self._overlay.add_log("빠른 스캔 기준 목록이 없습니다. 목록 편집에서 먼저 설정해 주세요.")
                    continue
                if configured_ids and len(configured_ids) < len(saved_student_ids):
                    self._overlay.add_log(
                        "빠른 스캔 기준 목록이 저장 데이터보다 적습니다. "
                        "목록 편집에서 학생을 더 선택해 주세요."
                    )
                    continue
                return {
                    "student_scan_strategy": "fast",
                    "fast_student_ids": [student_id for student_id, _name in ordered_students],
                }
            return {
                "student_scan_strategy": "normal",
                "fast_student_ids": [],
            }

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
        item_scan_filter: str | None = None
        if mode in ("items", "all"):
            item_scan_filter = self._choose_item_scan_filter()
            if item_scan_filter is None:
                self._overlay.add_log("아이템 스캔 필터 선택이 취소되었습니다.")
                return
        student_scan_options: dict | None = None
        if mode in ("students", "all"):
            student_scan_options = self._choose_student_scan_strategy(mode)
            if student_scan_options is None:
                self._overlay.add_log("학생 스캔 시작이 취소되었습니다.")
                return
            if student_scan_options.get("student_scan_strategy") == "rollback_only":
                return
        self._scan(
            mode,
            item_scan_filter=item_scan_filter,
            student_scan_options=student_scan_options,
        )

    def _scan(
        self,
        mode: str,
        item_scan_filter: str | None = None,
        student_scan_options: dict | None = None,
    ) -> None:
        meta = build_scan_meta()
        if item_scan_filter:
            meta["item_scan_filter_profile"] = None if item_scan_filter == "all" else item_scan_filter
            meta["item_scan_filter_label"] = inventory_profile_label(meta["item_scan_filter_profile"])
        if student_scan_options:
            meta.update(student_scan_options)
        if meta.get("student_scan_strategy") == "fast":
            backup_path = self._repo.create_student_snapshot_backup(
                scan_id=meta["scan_id"],
                reason="fast_student_scan",
                extra_meta={
                    "mode": mode,
                    "ordered_count": len(meta.get("fast_student_ids") or []),
                },
            )
            meta["fast_scan_backup_path"] = str(backup_path)
            self._overlay.add_log(
                f"패스트 스캔 백업 생성: {backup_path.name} "
                f"({len(meta.get('fast_student_ids') or [])}명)"
            )
        self._result = None
        self._overlay.reset_scan_progress()
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
                selected_filter = meta.get("item_scan_filter_label")
                if selected_filter:
                    self._dispatch_ui(self._overlay.add_log, f"아이템 필터: {selected_filter}")
                result.resources = scanner.scan_resources()
                self._dispatch_ui(self._overlay.update_resources, result.resources)
                result.items = scanner.scan_items(meta.get("item_scan_filter_profile"))
                self._dispatch_ui(self._overlay.add_log, f"아이템 {len(result.items)}개")

            if mode in ("equipment", "all") and not_stopped():
                result.equipment = scanner.scan_equipment()
                self._dispatch_ui(self._overlay.add_log, f"장비 {len(result.equipment)}개")

            if mode in ("students", "all") and not_stopped():
                if meta.get("student_scan_strategy") == "fast":
                    self._dispatch_ui(self._overlay.add_log, "학생 패스트 스캔 모드 실행")
                result.students = scanner.scan_students()
                skipped = sum(1 for s in result.students if s.skipped)
                self._dispatch_ui(
                    self._overlay.add_log,
                    f"학생 {len(result.students)}명 (스킵 {skipped})",
                )

            if mode == "student_current" and not_stopped():
                result.students = scanner.scan_current_student()
                skipped = sum(1 for s in result.students if s.skipped)
                self._dispatch_ui(
                    self._overlay.add_log,
                    f"현재 학생 {len(result.students)}명 (스킵 {skipped})",
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
        self._overlay.reset_scan_progress()

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
        from core.serializer import make_status_report, save_scan_json

        scan_id = meta.get("scan_id", "unknown")
        try:
            if self._asv:
                if not self._asv.final_save(result, meta):
                    raise RuntimeError("최종 저장 파일 작성 실패")
            else:
                json_path = self._storage.scans_dir / f"{scan_id}.json"
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
            self._target_close_handled = False
            save_config(self._config)
            set_target_window(hwnd, title)
            self._overlay.add_log(f"창 설정: {title}")
            self._transition_to(AppState.WATCHING, reason="window_selected")

        def on_cancel() -> None:
            if previous_hwnd:
                self._target_close_handled = False
                set_target_window(previous_hwnd, previous_title)
                self._transition_to(AppState.WATCHING, reason="window_picker_cancelled")
            else:
                self.destroy()

        WindowPicker(self, on_select=on_select, on_cancel=on_cancel)

    def _open_settings(self) -> None:
        self._open_window_picker()

    def _open_input_test(self) -> None:
        if self.state in (AppState.SCANNING, AppState.STOPPING):
            self._overlay.add_log("스캔/정리 중에는 입력 테스트를 열 수 없습니다.")
            return
        if not self._config.get("target_hwnd"):
            self._overlay.add_log("먼저 대상 게임 창을 선택해 주세요.")
            return
        self._input_test_overlay.show()

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
            self._input_test_overlay.destroy()
        except TclError:
            pass
        try:
            self._overlay.destroy()
        except TclError:
            pass
        self.destroy()

    def run(self) -> None:
        self.mainloop()


def main() -> int:
    try:
        App().run()
        return 0
    finally:
        if _STARTUP_INSTANCE_GUARD is not None:
            _STARTUP_INSTANCE_GUARD.release()


if __name__ == "__main__":
    raise SystemExit(main())
