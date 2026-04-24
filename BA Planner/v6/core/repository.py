"""
Repository layer for profile-specific scan persistence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config import get_storage_paths
from core.db import get_connection, init_db
from core import student_meta
from core.merge import (
    FieldDiff,
    compute_inventory_diff,
    compute_student_diff,
    merge_inventory_snapshot,
    merge_student_entry,
)
from core.inventory_profiles import (
    get_inventory_profile,
    inventory_item_display_name,
    normalize_inventory_profile_ids,
)
from core.scanner import ItemEntry, ScanResult, StudentEntry


def _canonical_student_display_name(student_id: object, fallback: object = None) -> object:
    if student_id:
        canonical = student_meta.field(str(student_id), "display_name")
        if canonical:
            return canonical
    return fallback


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
        "display_name": _canonical_student_display_name(entry.student_id, entry.display_name),
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
    def _rank(item: ItemEntry) -> tuple[int, int, int]:
        quantity = str(item.quantity or "").strip()
        has_nonzero_quantity = int(quantity not in ("", "0"))
        has_item_id = int(bool(item.item_id))
        quantity_len = len(quantity)
        return (has_nonzero_quantity, has_item_id, quantity_len)

    inventory: dict = {}
    for item in items:
        key = item.item_id or item.name
        if not key:
            continue
        display_name = inventory_item_display_name(item.item_id) or item.name
        current = inventory.get(key)
        if current is None:
            inventory[key] = {
                "item_id": item.item_id,
                "name": display_name,
                "quantity": item.quantity,
                "index": item.index,
                "item_source": item.source,
                "scan_meta": dict(getattr(item, "scan_meta", {}) or {}),
            }
            continue

        current_item = ItemEntry(
            name=current.get("name"),
            quantity=current.get("quantity"),
            item_id=current.get("item_id"),
            source=item.source,
            index=current.get("index", 0),
        )
        if _rank(item) > _rank(current_item):
            inventory[key] = {
                "item_id": item.item_id,
                "name": display_name,
                "quantity": item.quantity,
                "index": item.index,
                "item_source": item.source,
                "scan_meta": dict(getattr(item, "scan_meta", {}) or {}),
            }
    return inventory


def _looks_like_item_id(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return "_Icon_" in value or value.startswith("Item_")


def _canonical_inventory_key(item_key: str, entry: dict[str, Any]) -> str:
    item_id = entry.get("item_id") or (item_key if _looks_like_item_id(item_key) else None)
    if item_id:
        return str(item_id)
    name = entry.get("name")
    if name:
        return str(name)
    return item_key


def _normalize_inventory_entry(item_key: str, raw_entry: dict[str, Any]) -> dict[str, Any]:
    entry = dict(raw_entry)
    item_id = entry.get("item_id") or (item_key if _looks_like_item_id(item_key) else None)
    display_name = inventory_item_display_name(str(item_id)) if item_id else None
    return {
        "item_id": item_id,
        "name": display_name or entry.get("name") or item_key,
        "quantity": entry.get("quantity"),
        "index": entry.get("index"),
        "item_source": entry.get("item_source") or entry.get("source"),
        "scan_meta": dict(entry.get("scan_meta") or {}),
        "last_seen_at": entry.get("last_seen_at"),
        "last_scan_id": entry.get("last_scan_id"),
    }


def _inventory_entry_rank(entry: dict[str, Any]) -> tuple[int, int, int, int]:
    quantity = str(entry.get("quantity") or "").strip()
    has_nonzero_quantity = int(quantity not in ("", "0"))
    has_item_id = int(bool(entry.get("item_id")))
    has_seen_at = int(bool(entry.get("last_seen_at")))
    quantity_len = len(quantity)
    return (has_nonzero_quantity, has_item_id, has_seen_at, quantity_len)


def _merge_inventory_entry(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    if _inventory_entry_rank(incoming) > _inventory_entry_rank(existing):
        primary, secondary = incoming, existing
    else:
        primary, secondary = existing, incoming

    merged = dict(primary)
    for key in ("item_id", "name", "quantity", "index", "item_source", "scan_meta", "last_seen_at", "last_scan_id"):
        if merged.get(key) in (None, "") and secondary.get(key) not in (None, ""):
            merged[key] = secondary.get(key)
    return merged


def _normalize_inventory_snapshot(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_entry in snapshot.items():
        if not isinstance(raw_entry, dict):
            continue
        item_key = str(raw_key)
        entry = _normalize_inventory_entry(item_key, raw_entry)
        canonical_key = _canonical_inventory_key(item_key, entry)
        current = normalized.get(canonical_key)
        normalized[canonical_key] = entry if current is None else _merge_inventory_entry(current, entry)
    return normalized


class ScanRepository:
    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            base_dir = get_storage_paths().data_dir
        self._scans = base_dir / "scans"
        self._current = base_dir / "current"
        self._history = base_dir / "history"
        self._backups = base_dir / "backups"
        self._fast_scan_roster = self._current / "fast_scan_students.json"
        self._db_path = (base_dir.parent / "ba_planner.db") if base_dir.name == "data" else (base_dir / "ba_planner.db")

    def save(self, result: ScanResult, meta: dict) -> dict:
        scan_id = meta["scan_id"]
        scanned_at = meta["scanned_at"]

        self._save_raw(result, meta)
        student_changes = self._merge_students(result.students, scan_id, scanned_at)
        inventory_changes = self._merge_inventory(
            result.items + result.equipment,
            scan_id,
            scanned_at,
            profile_id=meta.get("item_scan_filter_profile"),
        )
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
        try:
            init_db(self._db_path)
            conn = get_connection(self._db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT item_key, item_id, name, quantity, item_index, item_source, last_seen_at, last_scan_id
                    FROM inventory_current
                    ORDER BY COALESCE(item_index, 999999), item_key
                    """
                ).fetchall()
            finally:
                conn.close()
            if rows:
                snapshot = {
                    str(row["item_key"]): {
                        "item_id": row["item_id"],
                        "name": row["name"],
                        "quantity": row["quantity"],
                        "index": row["item_index"],
                        "item_source": row["item_source"],
                        "last_seen_at": row["last_seen_at"],
                        "last_scan_id": row["last_scan_id"],
                    }
                    for row in rows
                }
                normalized = _normalize_inventory_snapshot(snapshot)
                if set(normalized) != set(snapshot):
                    self._replace_inventory_db_snapshot(normalized)
                return normalized
        except Exception:
            pass

        fallback = _normalize_inventory_snapshot(_read_json(self._current / "inventory.json", default={}))
        if fallback:
            self._replace_inventory_db_snapshot(fallback)
        return fallback

    def load_student_changes(self, student_id: str | None = None, limit: int = 200) -> list[dict]:
        changes: list[dict] = _read_json(self._history / "student_changes.json", default=[])
        if student_id:
            changes = [change for change in changes if change.get("student_id") == student_id]
        return changes[-limit:]

    def load_inventory_changes(self, limit: int = 200) -> list[dict]:
        try:
            init_db(self._db_path)
            conn = get_connection(self._db_path)
            try:
                rows = conn.execute(
                    """
                    SELECT item_key, item_id, name, old_quantity, new_quantity, changed_at, scan_id
                    FROM inventory_history
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
            finally:
                conn.close()
            if rows:
                return [
                    {
                        "item": row["item_key"],
                        "item_id": row["item_id"],
                        "name": row["name"],
                        "old": row["old_quantity"],
                        "new": row["new_quantity"],
                        "changed_at": row["changed_at"],
                        "scan_id": row["scan_id"],
                    }
                    for row in reversed(rows)
                ]
        except Exception:
            pass

        changes: list[dict] = _read_json(self._history / "inventory_changes.json", default=[])
        return changes[-limit:]

    def clear_inventory_data(self) -> None:
        _write_json(self._current / "inventory.json", {})
        _write_json(self._history / "inventory_changes.json", [])

        init_db(self._db_path)
        conn = get_connection(self._db_path)
        try:
            with conn:
                conn.execute("DELETE FROM items")
                conn.execute("DELETE FROM equipment_items")
                conn.execute("DELETE FROM inventory_current")
                conn.execute("DELETE FROM inventory_history")
        finally:
            conn.close()

    def load_fast_scan_roster(self) -> list[str]:
        payload = _read_json(self._fast_scan_roster, default={})
        if isinstance(payload, dict):
            student_ids = payload.get("student_ids")
            if isinstance(student_ids, list):
                return [str(student_id).strip() for student_id in student_ids if str(student_id).strip()]
        if isinstance(payload, list):
            return [str(student_id).strip() for student_id in payload if str(student_id).strip()]
        return []

    def save_fast_scan_roster(
        self,
        student_ids: list[str],
        *,
        source: str,
        extra_meta: dict[str, Any] | None = None,
    ) -> Path:
        cleaned = [str(student_id).strip() for student_id in student_ids if str(student_id).strip()]
        payload = {
            "student_ids": cleaned,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "student_count": len(cleaned),
            "extra_meta": extra_meta or {},
        }
        _write_json(self._fast_scan_roster, payload)
        return self._fast_scan_roster

    def create_student_snapshot_backup(
        self,
        *,
        scan_id: str,
        reason: str,
        extra_meta: dict[str, Any] | None = None,
    ) -> Path:
        current = self.load_current_students()
        created_at = datetime.now().isoformat(timespec="seconds")
        payload = {
            "kind": "student_snapshot_backup",
            "scan_id": scan_id,
            "reason": reason,
            "created_at": created_at,
            "student_count": len(current),
            "extra_meta": extra_meta or {},
            "students": current,
        }
        self._backups.mkdir(parents=True, exist_ok=True)
        path = self._backups / f"students_before_{scan_id}.json"
        _write_json(path, payload)
        return path

    def latest_student_snapshot_backup(self) -> Path | None:
        if not self._backups.exists():
            return None
        candidates = sorted(self._backups.glob("students_before_*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    def restore_student_snapshot_backup(self, backup_path: Path | None = None) -> dict[str, Any]:
        path = backup_path or self.latest_student_snapshot_backup()
        if path is None or not path.exists():
            raise FileNotFoundError("No student snapshot backup found.")

        payload = _read_json(path, default={})
        students = payload.get("students")
        if not isinstance(students, dict):
            raise ValueError(f"Invalid student snapshot backup: {path}")

        _write_json(self._current / "students.json", students)
        self._replace_students_db_snapshot(students)
        return {
            "path": path,
            "student_count": len(students),
            "scan_id": payload.get("scan_id"),
            "created_at": payload.get("created_at"),
            "reason": payload.get("reason"),
        }

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
                    {
                        "index": item.index,
                        "item_id": item.item_id,
                        "name": item.name,
                        "quantity": item.quantity,
                        "item_source": item.source,
                    }
                    for item in (result.items or [])
                ],
                "equipment": [
                    {
                        "index": item.index,
                        "item_id": item.item_id,
                        "name": item.name,
                        "quantity": item.quantity,
                        "item_source": item.source,
                    }
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
        self._replace_students_db_snapshot(current)
        _write_json(self._history / "student_changes.json", history)
        return total_changes

    def _merge_inventory(
        self,
        items: list[ItemEntry],
        scan_id: str,
        scanned_at: str,
        profile_id: str | list[str] | tuple[str, ...] | None = None,
    ) -> int:
        current = _normalize_inventory_snapshot(_read_json(self._current / "inventory.json", default={}))
        history: list[dict] = _read_json(self._history / "inventory_changes.json", default=[])

        new_snapshot = _normalize_inventory_snapshot(_items_to_inventory(items))
        normalized_profile_ids = normalize_inventory_profile_ids(profile_id)
        if normalized_profile_ids and normalized_profile_ids != ("all",):
            expected_item_ids: set[str] = set()
            expected_names: set[str] = set()
            for selected_profile_id in normalized_profile_ids:
                profile = get_inventory_profile(selected_profile_id)
                if profile is None:
                    continue
                expected_item_ids.update(profile.expected_item_ids)
                expected_names.update(profile.ordered_names)
            current = {
                item_key: entry
                for item_key, entry in current.items()
                if (
                    (entry.get("item_id") or item_key) not in expected_item_ids
                    and str(entry.get("name") or "") not in expected_names
                )
            }
        merged = _normalize_inventory_snapshot(merge_inventory_snapshot(current, new_snapshot))
        for item_key, entry in merged.items():
            if item_key in new_snapshot:
                entry["last_seen_at"] = scanned_at
                entry["last_scan_id"] = scan_id
            else:
                entry["last_seen_at"] = current.get(item_key, {}).get("last_seen_at")
                entry["last_scan_id"] = current.get(item_key, {}).get("last_scan_id")
        diffs = compute_inventory_diff(current, merged)

        for diff in diffs:
            item_entry = merged.get(diff.field, {})
            history.append(
                {
                    "item": diff.field,
                    "item_id": item_entry.get("item_id"),
                    "name": item_entry.get("name"),
                    "old": diff.old_value,
                    "new": diff.new_value,
                    "changed_at": scanned_at,
                    "scan_id": scan_id,
                }
            )

        _write_json(self._current / "inventory.json", merged)
        _write_json(self._history / "inventory_changes.json", history)
        self._replace_inventory_db_snapshot(merged)
        self._append_inventory_db_history(merged, diffs, scan_id, scanned_at)
        return len(diffs)

    def _save_db(self, result: ScanResult, meta: dict) -> None:
        from core.db_writer import save_scan

        save_scan(result, meta)

    def _replace_students_db_snapshot(self, students: dict[str, dict]) -> None:
        try:
            init_db(self._db_path)
            conn = get_connection(self._db_path)
            with conn:
                conn.execute("DELETE FROM students")
                for student_id, row in students.items():
                    data = dict(row)
                    conn.execute(
                        """
                        INSERT INTO students (
                            student_id, display_name, level, student_star,
                            weapon_state, weapon_star, weapon_level,
                            ex_skill, skill1, skill2, skill3,
                            equip1, equip2, equip3, equip4,
                            equip1_level, equip2_level, equip3_level,
                            stat_hp, stat_atk, stat_heal,
                            last_seen_at, last_scan_id
                        ) VALUES (
                            :student_id, :display_name, :level, :student_star,
                            :weapon_state, :weapon_star, :weapon_level,
                            :ex_skill, :skill1, :skill2, :skill3,
                            :equip1, :equip2, :equip3, :equip4,
                            :equip1_level, :equip2_level, :equip3_level,
                            :stat_hp, :stat_atk, :stat_heal,
                            :last_seen_at, :last_scan_id
                        )
                        """,
                        {
                            "student_id": student_id,
                            "display_name": _canonical_student_display_name(student_id, data.get("display_name")),
                            "level": data.get("level"),
                            "student_star": data.get("student_star"),
                            "weapon_state": data.get("weapon_state"),
                            "weapon_star": data.get("weapon_star"),
                            "weapon_level": data.get("weapon_level"),
                            "ex_skill": data.get("ex_skill"),
                            "skill1": data.get("skill1"),
                            "skill2": data.get("skill2"),
                            "skill3": data.get("skill3"),
                            "equip1": data.get("equip1"),
                            "equip2": data.get("equip2"),
                            "equip3": data.get("equip3"),
                            "equip4": data.get("equip4"),
                            "equip1_level": data.get("equip1_level"),
                            "equip2_level": data.get("equip2_level"),
                            "equip3_level": data.get("equip3_level"),
                            "stat_hp": data.get("stat_hp"),
                            "stat_atk": data.get("stat_atk"),
                            "stat_heal": data.get("stat_heal"),
                            "last_seen_at": data.get("last_seen_at"),
                            "last_scan_id": data.get("last_scan_id"),
                        },
                    )
            conn.close()
        except Exception as exc:
            print(f"[Repo] DB sync failed ({self._db_path}): {exc}")

    def _replace_inventory_db_snapshot(self, inventory: dict[str, dict[str, Any]]) -> None:
        try:
            init_db(self._db_path)
            conn = get_connection(self._db_path)
            with conn:
                conn.execute("DELETE FROM inventory_current")
                for item_key, row in inventory.items():
                    data = _normalize_inventory_entry(item_key, row)
                    canonical_key = _canonical_inventory_key(str(item_key), data)
                    conn.execute(
                        """
                        INSERT INTO inventory_current (
                            item_key, item_id, name, quantity,
                            item_index, item_source, last_seen_at, last_scan_id
                        ) VALUES (
                            :item_key, :item_id, :name, :quantity,
                            :item_index, :item_source, :last_seen_at, :last_scan_id
                        )
                        """,
                        {
                            "item_key": canonical_key,
                            "item_id": data.get("item_id"),
                            "name": data.get("name"),
                            "quantity": data.get("quantity"),
                            "item_index": data.get("index"),
                            "item_source": data.get("item_source"),
                            "last_seen_at": row.get("last_seen_at"),
                            "last_scan_id": row.get("last_scan_id"),
                        },
                    )
            conn.close()
        except Exception as exc:
            print(f"[Repo] Inventory DB sync failed ({self._db_path}): {exc}")

    def _append_inventory_db_history(
        self,
        inventory: dict[str, dict[str, Any]],
        diffs: list[FieldDiff],
        scan_id: str,
        scanned_at: str,
    ) -> None:
        if not diffs:
            return
        try:
            init_db(self._db_path)
            conn = get_connection(self._db_path)
            with conn:
                conn.executemany(
                    """
                    INSERT INTO inventory_history (
                        item_key, item_id, name, old_quantity, new_quantity, changed_at, scan_id
                    ) VALUES (
                        :item_key, :item_id, :name, :old_quantity, :new_quantity, :changed_at, :scan_id
                    )
                    """,
                    [
                        {
                            "item_key": diff.field,
                            "item_id": inventory.get(diff.field, {}).get("item_id"),
                            "name": inventory.get(diff.field, {}).get("name"),
                            "old_quantity": diff.old_value,
                            "new_quantity": diff.new_value,
                            "changed_at": scanned_at,
                            "scan_id": scan_id,
                        }
                        for diff in diffs
                    ],
                )
            conn.close()
        except Exception as exc:
            print(f"[Repo] Inventory history DB sync failed ({self._db_path}): {exc}")
