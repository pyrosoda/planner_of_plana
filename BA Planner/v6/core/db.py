"""
SQLite schema initialization helpers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.config import get_storage_paths

APP_VERSION = "v5.1"
DB_PATH = Path(__file__).parent.parent / "ba_planner.db"


def get_db_path() -> Path:
    return get_storage_paths().db_path


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    path = path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: Path | None = None) -> None:
    path = path or get_db_path()
    conn = get_connection(path)
    with conn:
        conn.executescript(
            """
        CREATE TABLE IF NOT EXISTS scans (
            scan_id      TEXT PRIMARY KEY,
            scanned_at   TEXT NOT NULL,
            app_version  TEXT NOT NULL,
            window_w     INTEGER,
            window_h     INTEGER
        );

        CREATE TABLE IF NOT EXISTS resources (
            scan_id      TEXT NOT NULL REFERENCES scans(scan_id),
            key          TEXT NOT NULL,
            value        TEXT,
            PRIMARY KEY (scan_id, key)
        );

        CREATE TABLE IF NOT EXISTS items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id      TEXT NOT NULL REFERENCES scans(scan_id),
            item_index   INTEGER NOT NULL,
            name         TEXT,
            quantity     TEXT
        );

        CREATE TABLE IF NOT EXISTS equipment_items (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id      TEXT NOT NULL REFERENCES scans(scan_id),
            item_index   INTEGER NOT NULL,
            name         TEXT,
            quantity     TEXT
        );

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
            last_seen_at    TEXT,
            last_scan_id    TEXT
        );

        CREATE TABLE IF NOT EXISTS student_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id   TEXT NOT NULL,
            field        TEXT NOT NULL,
            old_value    TEXT,
            new_value    TEXT,
            changed_at   TEXT NOT NULL,
            scan_id      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS inventory_current (
            item_key      TEXT PRIMARY KEY,
            item_id       TEXT,
            name          TEXT,
            quantity      TEXT,
            item_index    INTEGER,
            item_source   TEXT,
            last_seen_at  TEXT,
            last_scan_id  TEXT
        );

        CREATE TABLE IF NOT EXISTS inventory_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            item_key      TEXT NOT NULL,
            item_id       TEXT,
            name          TEXT,
            old_quantity  TEXT,
            new_quantity  TEXT,
            changed_at    TEXT NOT NULL,
            scan_id       TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_items_scan
            ON items(scan_id);
        CREATE INDEX IF NOT EXISTS idx_equip_items_scan
            ON equipment_items(scan_id);
        CREATE INDEX IF NOT EXISTS idx_history_student
            ON student_history(student_id);
        CREATE INDEX IF NOT EXISTS idx_history_scan
            ON student_history(scan_id);
        CREATE INDEX IF NOT EXISTS idx_inventory_history_item
            ON inventory_history(item_key);
        CREATE INDEX IF NOT EXISTS idx_inventory_history_scan
            ON inventory_history(scan_id);
        """
        )
    conn.close()
    print(f"[DB] initialized: {path}")
