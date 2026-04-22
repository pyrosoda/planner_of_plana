from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from tools.schaledb_sync import (
    SCALAR_FIELDS,
    SKILL_FIELDS,
    SYNC_FIELDS,
    apply_sync_fields,
    check_schaledb_filter_schema,
)
from tools.student_meta_tool import _write_students, get_students


def _print_fields() -> None:
    print("scalar fields:")
    for field_name in SCALAR_FIELDS:
        print(f"  - {field_name}")
    print("skill filter fields:")
    for field_name in SKILL_FIELDS:
        print(f"  - {field_name}")


def _print_schema_check() -> int:
    report = check_schaledb_filter_schema()
    print(f"asset: {report['asset']}")
    print("schaledb skill filters:")
    for filter_name, field_name in zip(report["schale_filters"], report["mapped_fields"]):
        status = "known" if field_name in SKILL_FIELDS else "missing"
        print(f"  - {filter_name} -> {field_name} ({status})")

    missing = report["missing_fields"]
    stale = report["stale_fields"]
    if missing:
        print("missing planner fields:")
        for field_name in missing:
            print(f"  - {field_name}")
    if stale:
        print("planner-only fields:")
        for field_name in stale:
            print(f"  - {field_name}")
    print("schema_check: " + ("needs_update" if missing else "ok"))
    return 1 if missing else 0


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
    parser.add_argument("--check-filter-schema", action="store_true", help="Compare SchaleDB skill filter keys with planner SKILL_FIELDS.")
    args = parser.parse_args()

    if args.list_fields:
        _print_fields()
        return 0
    if args.check_filter_schema:
        return _print_schema_check()

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
