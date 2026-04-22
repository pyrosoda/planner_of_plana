from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from tools.schaledb_sync import SCALAR_FIELDS, SKILL_FIELDS, SYNC_FIELDS, apply_sync_fields
from tools.student_meta_tool import _write_students, get_students


def _print_fields() -> None:
    print("scalar fields:")
    for field_name in SCALAR_FIELDS:
        print(f"  - {field_name}")
    print("skill filter fields:")
    for field_name in SKILL_FIELDS:
        print(f"  - {field_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl SchaleDB student data into core.student_meta.")
    parser.add_argument(
        "--student-id",
        action="append",
        dest="student_ids",
        help="Sync only the given local student_id. May be passed multiple times.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the sync summary without writing changes.")
    parser.add_argument("--force-refresh", action="store_true", help="Ignore cached SchaleDB data and fetch again.")
    parser.add_argument("--list-fields", action="store_true", help="Print every SchaleDB-derived metadata field this tool syncs.")
    args = parser.parse_args()

    if args.list_fields:
        _print_fields()
        return 0

    local_students = get_students()
    updated_count, missing = apply_sync_fields(
        local_students,
        selected_ids=set(args.student_ids) if args.student_ids else None,
        force_refresh=args.force_refresh,
    )

    if not args.dry_run:
        _write_students(local_students)

    print(f"updated: {updated_count}")
    print(f"fields_synced: {len(SYNC_FIELDS)}")
    if missing:
        print("missing:")
        for student_id in missing:
            print(f"  - {student_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
