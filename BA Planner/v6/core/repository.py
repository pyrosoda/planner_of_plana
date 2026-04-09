"""
Repository layer for profile-specific scan persistence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from core.config import get_storage_paths
from core.merge import (
    FieldDiff,
    compute_inventory_diff,
    compute_student_diff,
    merge_inventory_snapshot,
    merge_student_entry,
)
from core.scanner import ItemEntry, ScanResult, StudentEntry


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[Repo] JSON read failed ({path}): {exc}")
        return default if default is not None else {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _student_entry_to_dict(entry: StudentEntry) -> dict:
    return {
        "student_id": entry.student_id,
        "display_name": entry.display_name,
        "level": entry.level,
        "student_star": entry.student_star,
        "weapon_state": entry.weapon_state.value if entry.weapon_state else None,
        "weapon_star": entry.weapon_star,
        "weapon_level": entry.weapon_level,
        "ex_skill": entry.ex_skill,
        "skill1": entry.skill1,
        "skill2": entry.skill2,
        "skill3": entry.skill3,
        "equip1": entry.equip1,
        "equip2": entry.equip2,
        "equip3": entry.equip3,
        "equip4": entry.equip4,
        "equip1_level": entry.equip1_level,
        "equip2_level": entry.equip2_level,
        "equip3_level": entry.equip3_level,
        "stat_hp": entry.stat_hp,
        "stat_atk": entry.stat_atk,
        "stat_heal": entry.stat_heal,
    }


def _items_to_inventory(items: list[ItemEntry]) -> dict:
    inventory: dict = {}
    for item in items:
        if not item.name:
            continue
        if item.name not in inventory:
            inventory[item.name] = {"quantity": item.quantity, "index": item.index}
    return inventory


class ScanRepository:
    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            base_dir = get_storage_paths().data_dir
        self._scans = base_dir / "scans"
        self._current = base_dir / "current"
        self._history = base_dir / "history"

    def save(self, result: ScanResult, meta: dict) -> dict:
        scan_id = meta["scan_id"]
        scanned_at = meta["scanned_at"]

        self._save_raw(result, meta)
        student_changes = self._merge_students(result.students, scan_id, scanned_at)
        inventory_changes = self._merge_inventory(result.items + result.equipment, scan_id, scanned_at)
        self._save_db(result, meta)

        summary = {
            "scan_id": scan_id,
            "student_changes": student_changes,
            "inventory_changes": inventory_changes,
        }
        print(
            f"[Repo] saved: {scan_id} | "
            f"student_changes={student_changes} inventory_changes={inventory_changes}"
        )
        return summary

    def load_current_students(self) -> dict[str, dict]:
        return _read_json(self._current / "students.json", default={})

    def load_current_inventory(self) -> dict[str, dict]:
        return _read_json(self._current / "inventory.json", default={})

    def load_student_changes(self, student_id: str | None = None, limit: int = 200) -> list[dict]:
        changes: list[dict] = _read_json(self._history / "student_changes.json", default=[])
        if student_id:
            changes = [change for change in changes if change.get("student_id") == student_id]
        return changes[-limit:]

    def load_inventory_changes(self, limit: int = 200) -> list[dict]:
        changes: list[dict] = _read_json(self._history / "inventory_changes.json", default=[])
        return changes[-limit:]

    def _save_raw(self, result: ScanResult, meta: dict) -> None:
        raw = {
            "scan_id": meta["scan_id"],
            "scanned_at": meta["scanned_at"],
            "app_version": meta["app_version"],
            "window_size": meta["window_size"],
            "profile_name": meta.get("profile_name"),
            "result": {
                "resources": result.resources or {},
                "items": [
                    {"index": item.index, "name": item.name, "quantity": item.quantity}
                    for item in (result.items or [])
                ],
                "equipment": [
                    {"index": item.index, "name": item.name, "quantity": item.quantity}
                    for item in (result.equipment or [])
                ],
                "students": [
                    _student_entry_to_dict(student)
                    for student in (result.students or [])
                    if student.student_id
                ],
            },
        }
        path = self._scans / f"{meta['scan_id']}.json"
        _write_json(path, raw)

    def _merge_students(self, entries: list[StudentEntry], scan_id: str, scanned_at: str) -> int:
        current: dict[str, dict] = _read_json(self._current / "students.json", default={})
        history: list[dict] = _read_json(self._history / "student_changes.json", default=[])
        total_changes = 0

        for entry in entries:
            sid = entry.student_id
            if not sid:
                continue

            new_dict = _student_entry_to_dict(entry)
            old_dict = current.get(sid, {})
            merged = merge_student_entry(old_dict, new_dict)
            merged["last_seen_at"] = scanned_at
            merged["last_scan_id"] = scan_id
            merged["student_id"] = sid

            diffs: list[FieldDiff] = compute_student_diff(old_dict, merged)
            for diff in diffs:
                history.append(
                    {
                        "student_id": sid,
                        "field": diff.field,
                        "old": diff.old_value,
                        "new": diff.new_value,
                        "changed_at": scanned_at,
                        "scan_id": scan_id,
                    }
                )
                total_changes += 1

            current[sid] = merged

        _write_json(self._current / "students.json", current)
        _write_json(self._history / "student_changes.json", history)
        return total_changes

    def _merge_inventory(self, items: list[ItemEntry], scan_id: str, scanned_at: str) -> int:
        current: dict = _read_json(self._current / "inventory.json", default={})
        history: list[dict] = _read_json(self._history / "inventory_changes.json", default=[])

        new_snapshot = _items_to_inventory(items)
        merged = merge_inventory_snapshot(current, new_snapshot)
        diffs = compute_inventory_diff(current, merged)

        for diff in diffs:
            history.append(
                {
                    "item": diff.field,
                    "old": diff.old_value,
                    "new": diff.new_value,
                    "changed_at": scanned_at,
                    "scan_id": scan_id,
                }
            )

        _write_json(self._current / "inventory.json", merged)
        _write_json(self._history / "inventory_changes.json", history)
        return len(diffs)

    def _save_db(self, result: ScanResult, meta: dict) -> None:
        from core.db_writer import save_scan

        save_scan(result, meta)
