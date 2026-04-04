"""
core/db.py — SQLite 스키마 정의 + 초기화

테이블 구성:
  scans          : 스캔 세션 메타데이터
  resources      : 세션별 재화 스냅샷
  items          : 세션별 아이템 스냅샷
  equipment_items: 세션별 장비 아이템 스냅샷
  students       : 학생별 최신 상태 (upsert 대상)
  student_history: 학생 필드별 변경 이력
"""

import sqlite3
from pathlib import Path

APP_VERSION = "v5.1"
DB_PATH = Path(__file__).parent.parent / "ba_planner.db"


def get_connection(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path = DB_PATH) -> None:
    """DB 파일이 없거나 테이블이 없으면 생성."""
    conn = get_connection(path)
    with conn:
        conn.executescript("""
        -- ── 스캔 세션 ────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS scans (
            scan_id      TEXT PRIMARY KEY,          -- "2026-04-03_221840"
            scanned_at   TEXT NOT NULL,             -- ISO 8601 with timezone
            app_version  TEXT NOT NULL,
            window_w     INTEGER,
            window_h     INTEGER
        );

        -- ── 재화 스냅샷 ──────────────────────────────────────
        CREATE TABLE IF NOT EXISTS resources (
            scan_id      TEXT NOT NULL REFERENCES scans(scan_id),
            key          TEXT NOT NULL,             -- "청휘석", "크레딧"
            value        TEXT,
            PRIMARY KEY (scan_id, key)
        );

        -- ── 아이템 스냅샷 ────────────────────────────────────
        CREATE TABLE IF NOT EXISTS items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id      TEXT NOT NULL REFERENCES scans(scan_id),
            item_index   INTEGER NOT NULL,
            name         TEXT,
            quantity     TEXT
        );

        -- ── 장비 아이템 스냅샷 ──────────────────────────────
        CREATE TABLE IF NOT EXISTS equipment_items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id      TEXT NOT NULL REFERENCES scans(scan_id),
            item_index   INTEGER NOT NULL,
            name         TEXT,
            quantity     TEXT
        );

        -- ── 학생 최신 상태 (upsert) ─────────────────────────
        CREATE TABLE IF NOT EXISTS students (
            student_id      TEXT PRIMARY KEY,
            display_name    TEXT,
            level           INTEGER,
            student_star    INTEGER,
            weapon_state    TEXT,
            weapon_star     INTEGER,
            weapon_level    INTEGER,
            ex_skill        INTEGER,
            skill1          INTEGER,
            skill2          INTEGER,
            skill3          INTEGER,
            equip1          TEXT,
            equip2          TEXT,
            equip3          TEXT,
            equip4          TEXT,
            equip1_level    INTEGER,
            equip2_level    INTEGER,
            equip3_level    INTEGER,
            stat_hp         INTEGER,
            stat_atk        INTEGER,
            stat_heal       INTEGER,
            last_seen_at    TEXT,                   -- ISO 8601
            last_scan_id    TEXT
        );

        -- ── 학생 변경 이력 ───────────────────────────────────
        CREATE TABLE IF NOT EXISTS student_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   TEXT NOT NULL,
            field        TEXT NOT NULL,
            old_value    TEXT,
            new_value    TEXT,
            changed_at   TEXT NOT NULL,             -- ISO 8601
            scan_id      TEXT NOT NULL
        );

        -- ── 인덱스 ──────────────────────────────────────────
        CREATE INDEX IF NOT EXISTS idx_items_scan
            ON items(scan_id);
        CREATE INDEX IF NOT EXISTS idx_equip_items_scan
            ON equipment_items(scan_id);
        CREATE INDEX IF NOT EXISTS idx_history_student
            ON student_history(student_id);
        CREATE INDEX IF NOT EXISTS idx_history_scan
            ON student_history(scan_id);
        """)
    conn.close()
    print(f"[DB] 초기화 완료: {path}")
