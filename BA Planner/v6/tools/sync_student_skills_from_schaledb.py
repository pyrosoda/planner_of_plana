from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from tools.schaledb_sync import apply_sync_fields
from tools.student_meta_tool import _write_students, get_students


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync full student metadata from SchaleDB into core.student_meta.")
    parser.add_argument(
        "--student-id",
        action="append",
        dest="student_ids",
        help="Sync only the given local student_id. May be passed multiple times.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the sync summary without writing changes.")
    parser.add_argument("--force-refresh", action="store_true", help="Ignore cached SchaleDB data and fetch again.")
    args = parser.parse_args()

    local_students = get_students()
    updated_count, missing = apply_sync_fields(
        local_students,
        selected_ids=set(args.student_ids) if args.student_ids else None,
        force_refresh=args.force_refresh,
    )

    if not args.dry_run:
        _write_students(local_students)

    print(f"updated: {updated_count}")
    if missing:
        print("missing:")
        for student_id in missing:
            print(f"  - {student_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
