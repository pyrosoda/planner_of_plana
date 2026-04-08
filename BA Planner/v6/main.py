"""
main.py — Blue Archive Analyzer v6
상태 머신 기반 watcher / scanner lifecycle 관리

상태 전이:
  IDLE
    └─ 창 선택 완료          → WATCHING
  WATCHING
    └─ 스캔 시작             → SCANNING
    └─ 창 선택(재설정)       → IDLE → WATCHING
  SCANNING
    └─ 스캔 완료 / 중단      → WATCHING
    └─ 오류                  → ERROR → WATCHING
  ERROR
    └─ resume 또는 재설정    → WATCHING

규칙:
  - SCANNING 중 watcher.pause() 보장
  - SCANNING 중 창 재설정 / 설정 변경 차단
  - watcher 재생성 전 반드시 stop()
"""

import sys
import os
import threading
import importlib.util
from enum import Enum, auto
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 의존성 체크 ───────────────────────────────────────────
REQUIRED = {
    "cv2":         "opencv-python",
    "PIL":         "pillow",
    "pygetwindow": "pygetwindow",
    "pyautogui":   "pyautogui",
    "easyocr":     "easyocr",
    "numpy":       "numpy",
}
missing = [pkg for mod, pkg in REQUIRED.items()
           if not importlib.util.find_spec(mod)]
if missing:
    print(f"❌ pip install {' '.join(missing)}")
    sys.exit(1)

import tkinter as tk

from core.config        import load_regions, load_config, save_config
from core.capture       import clear_target
from core.lobby_watcher import LobbyWatcher, WatcherState
from core.scanner       import Scanner, ScanResult
from core.db_writer     import build_scan_meta
from core.repository    import ScanRepository
from core.analyzer      import analyze_scan_summary, is_student_maxed
from core.template_cache import warmup_all
from core.states import AppState, StateMachine, ScanPhase
from core.logger import setup_logging, get_logger, LOG_APP
from core.log_context import set_debug_dump
import core.student_names as student_names

_log = get_logger(LOG_APP)
from gui.floating       import FloatingOverlay
from gui.window_picker  import WindowPicker
from gui.student_viewer import open_viewer


# ── 앱 상태 ───────────────────────────────────────────────

class AppState(Enum):
    IDLE     = auto()   # 창 미선택
    WATCHING = auto()   # watcher 동작 중, 스캔 대기
    SCANNING = auto()   # 스캔 진행 중
    ERROR    = auto()   # 오류 발생 후 복구 대기


# ── App ───────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.title("BA Analyzer v6")

        setup_logging()
        self._regions = load_regions()
        self._config  = load_config()
        self._repo    = ScanRepository()

        # ── 디버그 덤프 설정 ──────────────────────────────
        # config.json 에 "debug_dump": true 가 있으면 활성화
        if self._config.get("debug_dump", False):
            from core.config import BASE_DIR
            set_debug_dump(enabled=True, dump_dir=BASE_DIR / "debug_dump")
            _log.info("디버그 덤프 모드 활성화")

        # ── 템플릿 캐시 사전 로드 ─────────────────────────
        # 시작 시 전체 템플릿 파일 검증 + 메모리 적재.
        # 누락 파일은 WARNING 로그, 시작은 계속 진행.
        warmup_all()

        # StateMachine — 검증+로깅 전이 관리자
        self._sm:      StateMachine         = StateMachine(AppState.INIT, name="App")
        self._state:   AppState             = AppState.IDLE  # 하위 호환 프로퍼티용
        self._scanner: Scanner | None       = None
        self._watcher: LobbyWatcher | None  = None
        self._result:  ScanResult | None    = None
        self._scan_thread: threading.Thread | None = None

        self._state_lock = threading.Lock()

        self._overlay = FloatingOverlay(
            self,
            on_scan_items=     lambda: self._request_scan("items"),
            on_scan_equipment= lambda: self._request_scan("equipment"),
            on_scan_students=  lambda: self._request_scan("students"),
            on_scan_all=       lambda: self._request_scan("all"),
            on_stop=           self._stop_scan,
            on_settings=       self._open_settings,
            on_view_students=  lambda: open_viewer(self),
        )

        clear_target()
        self.after(300, self._open_window_picker)

    # ══════════════════════════════════════════════════════
    # 상태 전이
    # ══════════════════════════════════════════════════════

    def _set_state(self, new: AppState, reason: str = "") -> bool:
        """
        상태 전이 — StateMachine 을 통해 검증 + 로그.
        허용되지 않은 전이는 False 반환 (경고 로그 자동).
        하위 호환을 위해 self._state 도 동기화.
        """
        ok = self._sm.transition(new, reason=reason)
        if ok:
            with self._state_lock:
                self._state = new
        return ok

    def _force_state(self, new: AppState, reason: str = "") -> None:
        """비상용 강제 전이 (종료 시퀀스 등)."""
        self._sm.force(new, reason=reason)
        with self._state_lock:
            self._state = new

    @property
    def state(self) -> AppState:
        return self._sm.state

    def _is_scanning(self) -> bool:
        return self._sm.is_in(AppState.SCANNING)

    def _is_stopping(self) -> bool:
        return self._sm.is_in(AppState.STOPPING)

    def _can_scan(self) -> bool:
        """스캔 시작 가능 상태인지 확인."""
        return self._sm.is_in(AppState.WATCHING)

    # ══════════════════════════════════════════════════════
    # watcher lifecycle
    # ══════════════════════════════════════════════════════

    def _start_watcher(self) -> None:
        """
        watcher 시작.
        기존 watcher 가 있으면 반드시 stop() 후 재생성.
        """
        if self._is_stopping():
            return

        self._stop_watcher()

        lobby_region = self._regions["lobby"]["detect_flag"]
        self._watcher = LobbyWatcher(
            lobby_region=lobby_region,
            on_enter=      lambda: self.after(0, self._on_lobby_enter),
            on_leave=      lambda: self.after(0, self._on_lobby_leave),
            on_window_move=lambda *a: self.after(0, self._overlay._reposition),
        )
        self._watcher.start()
        self._set_state(AppState.WATCHING, reason="watcher_started")

    def _stop_watcher(self) -> None:
        """watcher 안전 종료."""
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

    def _pause_watcher(self) -> None:
        """스캔 시작 시 watcher 일시정지."""
        if self._watcher and self._watcher.state == WatcherState.RUNNING:
            self._watcher.pause()

    def _resume_watcher(self) -> None:
        """스캔 종료 시 watcher 재개."""
        if self._watcher and self._watcher.state == WatcherState.PAUSED:
            self._watcher.resume()

    def _on_lobby_enter(self) -> None:
        self._overlay.show()

    def _on_lobby_leave(self) -> None:
        # 스캔 중에는 오버레이 숨기지 않음
        if not self._is_scanning():
            self._overlay.hide()

    # ══════════════════════════════════════════════════════
    # scanner 생성
    # ══════════════════════════════════════════════════════

    def _build_scanner(self, meta: dict) -> "Scanner":
        """
        repository 에서 만렙 학생 목록 로드 후 Scanner + AutoSaveManager 생성.
        스캔 시작 시마다 호출해 항상 최신 상태 반영.
        """
        from core.autosave import AutoSaveManager
        from core.config import BASE_DIR

        current_students = self._repo.load_current_students()
        maxed_ids:   set[str]        = set()
        maxed_cache: dict[str, dict] = {}

        for sid, data in current_students.items():
            if is_student_maxed(data):
                maxed_ids.add(sid)
                maxed_cache[sid] = data

        if maxed_ids:
            _log.info(f"만렙 스킵 대상: {len(maxed_ids)}명")

        # AutoSaveManager 생성
        scan_id = meta.get("scan_id", "unknown")
        asv = AutoSaveManager(
            scan_id=scan_id,
            save_dir=BASE_DIR / "scans",
            on_save_ok=   lambda msg: self.after(0, lambda m=msg: self._overlay.add_log(m)),
            on_save_fail= lambda msg: self.after(0, lambda m=msg: self._overlay.add_log(m)),
        )
        self._asv = asv   # 스캔 완료 후 final_save 호출을 위해 보관

        return Scanner(
            self._regions,
            on_progress=lambda msg: self.after(0, lambda m=msg: self._overlay.add_log(m)),
            maxed_ids=maxed_ids,
            maxed_cache=maxed_cache,
            autosave_manager=asv,
        )

    # ══════════════════════════════════════════════════════
    # 스캔 요청 / 실행
    # ══════════════════════════════════════════════════════

    def _request_scan(self, mode: str) -> None:
        """
        스캔 버튼 핸들러.
        StateMachine 의 _can_scan() 으로 유효성 확인.
        """
        if self._is_scanning():
            self._overlay.add_log("⚠️ 이미 스캔 중이야")
            return
        if self._is_stopping():
            return
        if not self._can_scan():
            self._overlay.add_log(
                "⚠️ 창을 먼저 선택해줘"
                if self._sm.is_in(AppState.IDLE) else
                "⚠️ 현재 상태에서는 스캔할 수 없어"
            )
            return
        self._scan(mode)

    def _scan(self, mode: str) -> None:
        """스캔 실행 — 별도 스레드로 구동."""
        meta          = build_scan_meta()
        self._asv     = None
        self._scanner = self._build_scanner(meta)

        # WATCHING → SCANNING 전이 (허용 확인 포함)
        if not self._set_state(AppState.SCANNING, reason=f"mode={mode}"):
            _log.error("SCANNING 전이 실패 — 스캔 취소")
            return

        self._pause_watcher()
        self._overlay.set_scanning(True)
        self._overlay.hide()
        self.update_idletasks()

        def task():
            try:
                self._run_scan_task(mode, meta)
            finally:
                self.after(0, self._on_scan_finished)

        self._scan_thread = threading.Thread(
            target=task,
            name=f"Scanner-{mode}",
            daemon=True,
        )
        self._scan_thread.start()

    def _run_scan_task(self, mode: str, meta: dict) -> None:
        """스캔 워크플로우 — 스캐너 스레드에서 실행."""
        result  = ScanResult()
        scanner = self._scanner

        def _not_stopped() -> bool:
            """scanner._stop 직접 참조 대신 메서드로 캡슐화."""
            return not scanner._stop

        try:
            if mode in ("items", "all"):
                result.resources = scanner.scan_resources()
                self.after(0, lambda: self._overlay.update_resources(result.resources))
                result.items = scanner.scan_items()
                n = len(result.items)
                self.after(0, lambda: self._overlay.add_log(f"✅ 아이템 {n}개"))

            if mode in ("equipment", "all") and _not_stopped():
                result.equipment = scanner.scan_equipment()
                n = len(result.equipment)
                self.after(0, lambda: self._overlay.add_log(f"✅ 장비 {n}개"))

            if mode in ("students", "all") and _not_stopped():
                result.students = scanner.scan_students()
                total   = len(result.students)
                skipped = sum(1 for s in result.students if s.skipped)
                self.after(0, lambda: self._overlay.add_log(
                    f"✅ 학생 {total}명 (스킵:{skipped})"))

            self._result = result
            self._auto_save(result, meta)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.after(0, lambda: self._overlay.add_log(f"❌ 스캔 오류: {e}"))
            self._set_state(AppState.ERROR, reason=str(e))

    def _on_scan_finished(self) -> None:
        """스캔 완료/중단 후 UI 스레드에서 호출."""
        self._overlay.set_scanning(False)

        if not self._sm.is_in(AppState.ERROR, AppState.STOPPING):
            self._set_state(AppState.WATCHING, reason="scan_finished")

        self._resume_watcher()

        if self._watcher and self._watcher.in_lobby:
            self._overlay.show()

        self._scan_thread = None

    def _stop_scan(self) -> None:
        """중지 버튼 핸들러."""
        if self._scanner:
            self._scanner.stop()
            self._overlay.add_log("⏹ 스캔 중지 요청 중...")

    # ══════════════════════════════════════════════════════
    # 저장 / 분석
    # ══════════════════════════════════════════════════════

    def _auto_save(self, result: ScanResult, meta: dict) -> None:
        from core.serializer import save_scan_json, make_status_report
        from core.config import BASE_DIR

        scan_id = meta.get("scan_id", "unknown")
        try:
            self._repo.save(result, meta)
            self.after(0, lambda: self._overlay.add_log(f"💾 저장 완료 ({scan_id})"))

            # AutoSaveManager final_save (체크포인트 정리 포함)
            if self._asv:
                self._asv.final_save(result, meta)
            else:
                # asv 없을 때 fallback 직접 저장
                json_path = BASE_DIR / "scans" / f"{scan_id}.json"
                save_scan_json(result, json_path, meta)
                _log.info(f"스캔 JSON 저장: {json_path}")

            # 상태 요약 리포트
            for line in make_status_report(result):
                self.after(0, lambda l=line: self._overlay.add_log(l))

            if not result.students:
                return

            current_students = list(self._repo.load_current_students().values())
            all_changes      = self._repo.load_student_changes()
            this_changes     = [c for c in all_changes if c.get("scan_id") == scan_id]
            summary = analyze_scan_summary(current_students, this_changes, scan_id)

            if summary.total_field_changes:
                n  = summary.total_field_changes
                ns = summary.changed_students
                self.after(0, lambda: self._overlay.add_log(f"📝 변경 {n}건 ({ns}명)"))
                top = sorted(summary.changed_fields_freq.items(),
                             key=lambda x: x[1], reverse=True)[:3]
                for fn, cnt in top:
                    self.after(0, lambda fn=fn, cnt=cnt:
                        self._overlay.add_log(f"  · {fn}: {cnt}건"))

            if summary.low_confidence:
                n = len(summary.low_confidence)
                self.after(0, lambda: self._overlay.add_log(f"⚠️ 신뢰도 낮음: {n}명"))

            if summary.maxed_students:
                n = len(summary.maxed_students)
                self.after(0, lambda: self._overlay.add_log(f"⭐ 만렙 도달: {n}명"))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.after(0, lambda: self._overlay.add_log(f"❌ 저장 실패: {e}"))

    # ══════════════════════════════════════════════════════
    # 창 선택 / 설정
    # ══════════════════════════════════════════════════════

    def _open_window_picker(self) -> None:
        """
        창 선택 UI 오픈.
        SCANNING / STOPPING 중에는 차단.
        """
        if self._is_scanning():
            self._overlay.add_log("⚠️ 스캔 중에는 창 재설정 불가")
            return
        if self._is_stopping():
            return

        self._stop_watcher()
        self._set_state(AppState.IDLE, reason="window_picker_open")
        self._overlay.hide()
        clear_target()

        def on_select(hwnd: int, title: str) -> None:
            self._config["target_hwnd"]  = hwnd
            self._config["target_title"] = title
            save_config(self._config)
            self._overlay.add_log(f"🎯 창 설정: {title}")
            self._start_watcher()

        def on_cancel() -> None:
            # 취소 시 기존 설정으로 복구 시도
            hwnd = self._config.get("target_hwnd")
            if hwnd:
                from core.capture import set_target_window
                set_target_window(hwnd, self._config.get("target_title", ""))
                self._start_watcher()
            else:
                # 선택된 창이 없으면 앱 종료
                self.destroy()

        WindowPicker(self, on_select=on_select, on_cancel=on_cancel)

    def _open_settings(self) -> None:
        """설정 버튼 → 창 재선택."""
        self._open_window_picker()

    # ══════════════════════════════════════════════════════
    # 진입점
    # ══════════════════════════════════════════════════════

    def run(self) -> None:
        self.mainloop()


# ── 진입점 ───────────────────────────────────────────────

if __name__ == "__main__":
    App().run()