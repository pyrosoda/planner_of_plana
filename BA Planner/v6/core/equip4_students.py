"""
Compatibility shim for favorite-item / 4th equipment eligibility.

The source of truth now lives in core.student_meta.
"""

from core.student_meta import FAVORITE_ITEM_STUDENT_IDS, favorite_item_enabled


def has_equip4(student_id: str) -> bool:
    return favorite_item_enabled(student_id)


EQUIP4_STUDENT_IDS = FAVORITE_ITEM_STUDENT_IDS
EQUIP4_MAX_TIER = "T2"
