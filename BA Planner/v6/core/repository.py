"""
core/repository.py — 저장 관리자 (Repository 계층)

담당
  · raw 스캔 결과 → data/scans/{scan_id}.json
  · current 상태  → data/current/students.json
                     data/current/inventory.json
  · 변경 이력     → data/history/student_changes.json
                     data/history/inventory_changes.json
  · SQLite upsert → core/db_writer.save_scan() 위임

공개 인터페이스
  · ScanRepository.save(result, meta)
      → raw 저장 → current 병합 → history 기록 → DB 저장
  · ScanRepository.load_current_students()
  · ScanRepository.load_current_inventory()
  · ScanRepository.load_student_changes(student_id)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
from typing import Any

from core.merge import (
    merge_student_entry,
    merge_inventory_snapshot,
    compute_student_diff,
    compute_inventory_diff,
    FieldDiff,
)
from core.scanner import ScanResult, StudentEntry, ItemEntry
from core.matcher import WeaponState

# ── 경로 ──────────────────────────────────────────────────
_BASE    = Path(__file__).parent.parent / "data"
_SCANS   = _BASE / "scans"
_CURRENT = _BASE / "current"
_HISTORY = _BASE / "history"

_KST = timezone(timedelta(hours=9))


# ── JSON I/O ──────────────────────────────────────────────
def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[Repo] JSON 읽기 실패 ({path}): {e}")
        return default if default is not None else {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ── 변환 헬퍼 ─────────────────────────────────────────────
def _student_entry_to_dict(entry: StudentEntry) -> dict:
    return {
        "student_id":   entry.student_id,
        "display_name": entry.display_name,
        "level":        entry.level,
        "student_star": entry.student_star,
        "weapon_state": entry.weapon_state.value if entry.weapon_state else None,
        "weapon_star":  entry.weapon_star,
        "weapon_level": entry.weapon_level,
        "ex_skill":     entry.ex_skill,
        "skill1":       entry.skill1,
        "skill2":       entry.skill2,
        "skill3":       entry.skill3,
        "equip1":       entry.equip1,
        "equip2":       entry.equip2,
        "equip3":       entry.equip3,
        "equip4":       entry.equip4,
        "equip1_level": entry.equip1_level,
        "equip2_level": entry.equip2_level,
        "equip3_level": entry.equip3_level,
        "stat_hp":      entry.stat_hp,
        "stat_atk":     entry.stat_atk,
        "stat_heal":    entry.stat_heal,
    }


def _items_to_inventory(items: list[ItemEntry]) -> dict:
    """
    ItemEntry 목록 → inventory dict.
    {"아이템명": {"quantity": "10", "index": 0}, ...}
    동명 아이템이 여러 개면 index가 작은 것 우선 (첫 번째).
    """
    inv: dict = {}
    for item in items:
        if not item.name:
            continue
        if item.name not in inv:
            inv[item.name] = {"quantity": item.quantity, "index": item.index}
    return inv


# ── Repository ────────────────────────────────────────────
class ScanRepository:
    """
    스캔 결과의 저장/병합/이력 관리 전담 클래스.

    사용 예
    -------
    repo = ScanRepository()
    summary = repo.save(result, meta)
    """

    def __init__(self, base_dir: Path = _BASE):
        self._scans   = base_dir / "scans"
        self._current = base_dir / "current"
        self._history = base_dir / "history"

    # ── 공개 저장 진입점 ──────────────────────────────────
    def save(self, result: ScanResult, meta: dict) -> dict:
        """
        스캔 결과 전체 저장 파이프라인.

        1. raw 저장    (scans/{scan_id}.json)
        2. current 병합 (current/students.json, current/inventory.json)
        3. history 기록 (history/student_changes.json, history/inventory_changes.json)
        4. SQLite upsert

        Returns
        -------
        summary dict  {
            "scan_id": ...,
            "student_changes": int,
            "inventory_changes": int,
        }
        """
        scan_id    = meta["scan_id"]
        scanned_at = meta["scanned_at"]

        # 1. raw 저장
        self._save_raw(result, meta)

        # 2+3. current 병합 + history 기록
        n_student_changes   = self._merge_students(result.students, scan_id, scanned_at)
        n_inventory_changes = self._merge_inventory(
            result.items + result.equipment, scan_id, scanned_at
        )

        # 4. SQLite
        self._save_db(result, meta)

        summary = {
            "scan_id":           scan_id,
            "student_changes":   n_student_changes,
            "inventory_changes": n_inventory_changes,
        }
        print(
            f"[Repo] 저장 완료: {scan_id} | "
            f"학생변경={n_student_changes} 인벤토리변경={n_inventory_changes}"
        )
        return summary

    # ── 공개 조회 ─────────────────────────────────────────
    def load_current_students(self) -> dict[str, dict]:
        """current/students.json 전체 반환. {student_id: {...}}"""
        return _read_json(self._current / "students.json", default={})

    def load_current_inventory(self) -> dict[str, dict]:
        """current/inventory.json 전체 반환."""
        return _read_json(self._current / "inventory.json", default={})

    def load_student_changes(
        self,
        student_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """
        history/student_changes.json 에서 조회.
        student_id 지정 시 해당 학생만 필터링.
        """
        all_changes: list[dict] = _read_json(
            self._history / "student_changes.json", default=[]
        )
        if student_id:
            all_changes = [c for c in all_changes if c.get("student_id") == student_id]
        return all_changes[-limit:]

    def load_inventory_changes(self, limit: int = 200) -> list[dict]:
        all_changes: list[dict] = _read_json(
            self._history / "inventory_changes.json", default=[]
        )
        return all_changes[-limit:]

    # ── 1. Raw 저장 ───────────────────────────────────────
    def _save_raw(self, result: ScanResult, meta: dict) -> None:
        scan_id = meta["scan_id"]
        raw = {
            "scan_id":     meta["scan_id"],
            "scanned_at":  meta["scanned_at"],
            "app_version": meta["app_version"],
            "window_size": meta["window_size"],
            "result": {
                "resources": result.resources or {},
                "items": [
                    {"index": i.index, "name": i.name, "quantity": i.quantity}
                    for i in (result.items or [])
                ],
                "equipment": [
                    {"index": i.index, "name": i.name, "quantity": i.quantity}
                    for i in (result.equipment or [])
                ],
                "students": [
                    _student_entry_to_dict(s)
                    for s in (result.students or [])
                    if s.student_id
                ],
            },
        }
        path = self._scans / f"{scan_id}.json"
        _write_json(path, raw)
        print(f"[Repo] raw 저장: {path.name}")

    # ── 2+3. 학생 병합 + 이력 ────────────────────────────
    def _merge_students(
        self,
        entries: list[StudentEntry],
        scan_id: str,
        scanned_at: str,
    ) -> int:
        """
        current/students.json 을 읽어 병합 후 재저장.
        변경 이력을 history/student_changes.json 에 append.
        반환: 변경된 필드 수 합계
        """
        current: dict[str, dict] = _read_json(
            self._current / "students.json", default={}
        )
        history: list[dict] = _read_json(
            self._history / "student_changes.json", default=[]
        )

        total_changes = 0

        for entry in entries:
            sid = entry.student_id
            if not sid:
                continue

            new_dict = _student_entry_to_dict(entry)
            old_dict = current.get(sid, {})

            # 병합
            merged = merge_student_entry(old_dict, new_dict)
            # meta 필드 갱신
            merged["last_seen_at"] = scanned_at
            merged["last_scan_id"] = scan_id
            merged["student_id"]   = sid

            # diff
            diffs: list[FieldDiff] = compute_student_diff(old_dict, merged)

            # 이력 append
            for diff in diffs:
                history.append({
                    "student_id": sid,
                    "field":      diff.field,
                    "old":        diff.old_value,
                    "new":        diff.new_value,
                    "changed_at": scanned_at,
                    "scan_id":    scan_id,
                })
                total_changes += 1

            current[sid] = merged

        _write_json(self._current / "students.json", current)
        _write_json(self._history / "student_changes.json", history)
        return total_changes

    # ── 2+3. 인벤토리 병합 + 이력 ────────────────────────
    def _merge_inventory(
        self,
        items: list[ItemEntry],
        scan_id: str,
        scanned_at: str,
    ) -> int:
        """
        current/inventory.json 을 읽어 병합 후 재저장.
        변경 이력을 history/inventory_changes.json 에 append.
        반환: 변경된 항목 수
        """
        current: dict = _read_json(
            self._current / "inventory.json", default={}
        )
        history: list[dict] = _read_json(
            self._history / "inventory_changes.json", default=[]
        )

        new_snapshot = _items_to_inventory(items)
        merged = merge_inventory_snapshot(current, new_snapshot)
        diffs  = compute_inventory_diff(current, merged)

        for diff in diffs:
            history.append({
                "item":       diff.field,
                "old":        diff.old_value,
                "new":        diff.new_value,
                "changed_at": scanned_at,
                "scan_id":    scan_id,
            })

        _write_json(self._current / "inventory.json", merged)
        _write_json(self._history / "inventory_changes.json", history)
        return len(diffs)

    # ── 4. SQLite upsert ──────────────────────────────────
    def _save_db(self, result: ScanResult, meta: dict) -> None:
        from core.db_writer import save_scan

        save_scan(result, meta)
