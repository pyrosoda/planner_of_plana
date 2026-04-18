"""
Inventory-only reset utility.

This script clears the saved inventory data while preserving:
  - student data
  - growth plans
  - raw scan files
  - app settings and assets

It resets:
  - current inventory snapshot JSON
  - inventory change history JSON
  - per-profile DB inventory tables
"""

from __future__ import annotations

import argparse

from core.config import get_storage_paths
from core.repository import ScanRepository


def reset_inventory_data() -> None:
    paths = get_storage_paths()
    repo = ScanRepository(base_dir=paths.data_dir)
    repo.clear_inventory_data()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clear saved inventory JSON snapshots/history and per-profile DB inventory tables."
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
            "Reset saved inventory data only? [y/N]: "
        ).strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled.")
            return 0

    reset_inventory_data()
    print("Inventory data reset completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
