"""
core/db_writer.py — ScanResult → SQLite 저장/업데이트

주요 기능:
  - build_scan_meta()   : 스캔 메타데이터 dict 생성
  - save_scan()         : 스캔 세션 전체를 DB에 저장
  - _upsert_student()   : 학생 1명 upsert + 변경 이력 기록
  - load_scan_meta()    : scan_id로 메타 조회
  - load_student()      : student_id로 최신 상태 조회
  - load_student_history() : 변경 이력 조회
"""

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from core.config import get_active_profile_name
from core.db import get_connection, get_db_path, init_db, APP_VERSION
from core.scanner import ScanResult, StudentEntry, ItemEntry
from core.matcher import WeaponState
from core.capture import get_window_rect

# KST = UTC+9
_KST = timezone(timedelta(hours=9))

# 학생 비교 대상 필드 (변경 이력을 남길 컬럼들)
_STUDENT_FIELDS = (
    "display_name",
    "level",
    "student_star",
    "weapon_state",
    "weapon_star",
    "weapon_level",
    "ex_skill",
    "skill1",
    "skill2",
    "skill3",
    "equip1",
    "equip2",
    "equip3",
    "equip4",
    "equip1_level",
    "equip2_level",
    "equip3_level",
    "stat_hp",
    "stat_atk",
    "stat_heal",
)


# ── 타임스탬프 유틸 ───────────────────────────────────────

def _now_kst() -> datetime:
    return datetime.now(_KST)


def _fmt(dt: datetime) -> str:
    """ISO 8601 with timezone offset (+09:00)"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S+09:00")


def _scan_id(dt: datetime) -> str:
    """'2026-04-03_221840' 형식"""
    return dt.strftime("%Y-%m-%d_%H%M%S")


# ── 메타데이터 빌더 ───────────────────────────────────────

def build_scan_meta(dt: datetime | None = None) -> dict:
    """
    스캔 세션 메타데이터 dict 반환.
    JSON 로그나 DB 저장에 공통으로 사용.
    """
    if dt is None:
        dt = _now_kst()

    rect = get_window_rect()
    window_size = [rect[2], rect[3]] if rect else [None, None]

    return {
        "scan_id":     _scan_id(dt),
        "scanned_at":  _fmt(dt),
        "app_version": APP_VERSION,
        "window_size": window_size,
        "profile_name": get_active_profile_name(),
    }


# ── 학생 엔트리 → dict ────────────────────────────────────

def _student_to_dict(entry: StudentEntry) -> dict[str, Any]:
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


# ── 학생 upsert + 변경 이력 ───────────────────────────────

def _upsert_student(
    conn: sqlite3.Connection,
    new: dict[str, Any],
    scan_id: str,
    scanned_at: str,
) -> list[dict]:
    """
    students 테이블을 upsert하고 변경된 필드의 이력을 기록.
    반환: 변경된 필드 목록 (디버깅용)
    """
    sid = new["student_id"]

    # 기존 레코드 조회
    row = conn.execute(
        "SELECT * FROM students WHERE student_id = ?", (sid,)
    ).fetchone()

    changes: list[dict] = []
    now_str = scanned_at

    if row:
        old = dict(row)
        for field in _STUDENT_FIELDS:
            old_v = str(old.get(field, "")) if old.get(field) is not None else None
            new_v = str(new.get(field, "")) if new.get(field) is not None else None
            if old_v != new_v:
                changes.append({
                    "student_id": sid,
                    "field":      field,
                    "old":        old_v,
                    "new":        new_v,
                    "changed_at": now_str,
                    "scan_id":    scan_id,
                })

    # upsert (INSERT OR REPLACE)
    conn.execute("""
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
        ON CONFLICT(student_id) DO UPDATE SET
            display_name  = excluded.display_name,
            level         = excluded.level,
            student_star  = excluded.student_star,
            weapon_state  = excluded.weapon_state,
            weapon_star   = excluded.weapon_star,
            weapon_level  = excluded.weapon_level,
            ex_skill      = excluded.ex_skill,
            skill1        = excluded.skill1,
            skill2        = excluded.skill2,
            skill3        = excluded.skill3,
            equip1        = excluded.equip1,
            equip2        = excluded.equip2,
            equip3        = excluded.equip3,
            equip4        = excluded.equip4,
            equip1_level  = excluded.equip1_level,
            equip2_level  = excluded.equip2_level,
            equip3_level  = excluded.equip3_level,
            stat_hp       = excluded.stat_hp,
            stat_atk      = excluded.stat_atk,
            stat_heal     = excluded.stat_heal,
            last_seen_at  = excluded.last_seen_at,
            last_scan_id  = excluded.last_scan_id
    """, {**new, "last_seen_at": now_str, "last_scan_id": scan_id})

    # 변경 이력 삽입
    if changes:
        conn.executemany("""
            INSERT INTO student_history
                (student_id, field, old_value, new_value, changed_at, scan_id)
            VALUES
                (:student_id, :field, :old, :new, :changed_at, :scan_id)
        """, changes)
        print(f"[DB] {sid}: {len(changes)}개 필드 변경 이력 기록")

    return changes


# ── 메인 저장 함수 ────────────────────────────────────────

def save_scan(
    result: ScanResult,
    meta: dict | None = None,
    path: Path | None = None,
) -> str:
    """
    ScanResult 전체를 DB에 저장.

    Parameters
    ----------
    result : ScanResult
    meta   : build_scan_meta() 결과. None이면 내부에서 생성.
    path   : DB 파일 경로

    Returns
    -------
    scan_id : 저장된 세션 ID
    """
    path = path or get_db_path()
    init_db(path)

    if meta is None:
        meta = build_scan_meta()

    scan_id    = meta["scan_id"]
    scanned_at = meta["scanned_at"]
    window_w, window_h = (meta["window_size"] + [None, None])[:2]

    conn = get_connection(path)
    try:
        with conn:
            # ── scans ────────────────────────────────────
            conn.execute("""
                INSERT OR IGNORE INTO scans
                    (scan_id, scanned_at, app_version, window_w, window_h)
                VALUES (?, ?, ?, ?, ?)
            """, (scan_id, scanned_at, meta["app_version"], window_w, window_h))

            # ── resources ────────────────────────────────
            for key, val in (result.resources or {}).items():
                conn.execute("""
                    INSERT OR REPLACE INTO resources (scan_id, key, value)
                    VALUES (?, ?, ?)
                """, (scan_id, key, str(val) if val is not None else None))

            # ── items ────────────────────────────────────
            for item in (result.items or []):
                conn.execute("""
                    INSERT INTO items (scan_id, item_index, name, quantity)
                    VALUES (?, ?, ?, ?)
                """, (scan_id, item.index, item.name, item.quantity))

            # ── equipment_items ──────────────────────────
            for item in (result.equipment or []):
                conn.execute("""
                    INSERT INTO equipment_items (scan_id, item_index, name, quantity)
                    VALUES (?, ?, ?, ?)
                """, (scan_id, item.index, item.name, item.quantity))

            # ── students (upsert + history) ──────────────
            all_changes: list[dict] = []
            for entry in (result.students or []):
                if not entry.student_id:
                    continue
                new_data = _student_to_dict(entry)
                changes = _upsert_student(conn, new_data, scan_id, scanned_at)
                all_changes.extend(changes)

        print(
            f"[DB] 저장 완료: scan_id={scan_id} "
            f"| 아이템={len(result.items or [])} "
            f"| 장비={len(result.equipment or [])} "
            f"| 학생={len(result.students or [])} "
            f"| 변경={len(all_changes)}"
        )
        return scan_id

    finally:
        conn.close()


# ── 조회 함수 ─────────────────────────────────────────────

def load_scan_meta(scan_id: str, path: Path | None = None) -> dict | None:
    path = path or get_db_path()
    """scan_id로 메타데이터 조회."""
    conn = get_connection(path)
    try:
        row = conn.execute(
            "SELECT * FROM scans WHERE scan_id = ?", (scan_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def load_student(student_id: str, path: Path | None = None) -> dict | None:
    path = path or get_db_path()
    """student_id로 최신 상태 조회."""
    conn = get_connection(path)
    try:
        row = conn.execute(
            "SELECT * FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def load_student_history(
    student_id: str,
    field: str | None = None,
    limit: int = 100,
    path: Path | None = None,
) -> list[dict]:
    """
    학생 변경 이력 조회.
    field 를 지정하면 해당 필드만 필터링.
    """
    path = path or get_db_path()
    conn = get_connection(path)
    try:
        if field:
            rows = conn.execute("""
                SELECT * FROM student_history
                WHERE student_id = ? AND field = ?
                ORDER BY changed_at DESC
                LIMIT ?
            """, (student_id, field, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM student_history
                WHERE student_id = ?
                ORDER BY changed_at DESC
                LIMIT ?
            """, (student_id, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_all_students(path: Path | None = None) -> list[dict]:
    path = path or get_db_path()
    """전체 학생 최신 상태 목록 조회."""
    conn = get_connection(path)
    try:
        rows = conn.execute(
            "SELECT * FROM students ORDER BY student_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def load_scan_changes(scan_id: str, path: Path | None = None) -> list[dict]:
    path = path or get_db_path()
    """특정 스캔 세션에서 발생한 모든 변경 이력 조회."""
    conn = get_connection(path)
    try:
        rows = conn.execute("""
            SELECT * FROM student_history
            WHERE scan_id = ?
            ORDER BY student_id, field
        """, (scan_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
