"""
Project data reset utility.

This script clears saved scan data while preserving app settings and assets.

Reset targets:
  - ba_planner.db (+ SQLite sidecar files)
  - data/current/*.json
  - data/history/*.json
  - data/scans/*
  - scans/*
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from core.config import get_storage_paths
from core.db import init_db


BASE_DIR = Path(__file__).resolve().parent
STORAGE = get_storage_paths()
DATA_DIR = STORAGE.data_dir

CURRENT_FILES = {
    DATA_DIR / "current" / "students.json": {},
    DATA_DIR / "current" / "inventory.json": {},
}

HISTORY_FILES = {
    DATA_DIR / "history" / "student_changes.json": [],
    DATA_DIR / "history" / "inventory_changes.json": [],
}

DIRECTORIES_TO_CLEAR = (
    DATA_DIR / "scans",
    STORAGE.scans_dir,
)

DB_SIDE_CARS = (
    STORAGE.db_path,
    Path(f"{STORAGE.db_path}-wal"),
    Path(f"{STORAGE.db_path}-shm"),
)


def _reset_json_file(path: Path, empty_value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if empty_value == []:
        path.write_text("[]\n", encoding="utf-8")
    else:
        path.write_text("{}\n", encoding="utf-8")


def _clear_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for child in directory.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


def reset_saved_data() -> None:
    for db_file in DB_SIDE_CARS:
        db_file.unlink(missing_ok=True)

    for directory in DIRECTORIES_TO_CLEAR:
        _clear_directory(directory)

    for path, empty_value in CURRENT_FILES.items():
        _reset_json_file(path, empty_value)

    for path, empty_value in HISTORY_FILES.items():
        _reset_json_file(path, empty_value)

    init_db(STORAGE.db_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clear saved scan data and recreate empty storage files."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="run without asking for confirmation",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.yes:
        answer = input(
            "Reset saved scan data and DB? [y/N]: "
        ).strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    reset_saved_data()
    print("Saved data reset completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
