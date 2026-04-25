from __future__ import annotations

import re
from typing import Any


SCHOOL_TOKEN_TO_LABEL: dict[str, str] = {
    "abydos": "Abydos",
    "arius": "Arius",
    "gehenna": "Gehenna",
    "highlander": "Highlander",
    "hyakkiyako": "Hyakkiyako",
    "millennium": "Millennium",
    "redwinter": "RedWinter",
    "shanhaijing": "Shanhaijing",
    "trinity": "Trinity",
    "valkyrie": "Valkyrie",
    "wildhunt": "Wildhunt",
    "srt": "Valkyrie",
}

_SKILLBOOK_PATTERN = re.compile(r"item_icon_skillbook_([a-z]+)_([0-3])$")
_BLURAY_PATTERN = re.compile(r"item_icon_material_exskill_([a-z]+)_([0-3])$")


def normalize_school_label(value: object) -> str:
    token = str(value or "").strip()
    if not token:
        return "ETC"
    return SCHOOL_TOKEN_TO_LABEL.get(token.casefold(), token)


def skill_material_base_from_item(item: dict[str, Any]) -> tuple[str, int] | None:
    icon = str(item.get("Icon") or "").strip().lower()
    subcategory = str(item.get("SubCategory") or "").strip()

    if subcategory == "BookItem":
        match = _SKILLBOOK_PATTERN.match(icon)
        if match:
            school_token, tier_text = match.groups()
            return f"{normalize_school_label(school_token)} Note", int(tier_text) + 1

    if subcategory == "CDItem":
        match = _BLURAY_PATTERN.match(icon)
        if match:
            school_token, tier_text = match.groups()
            return f"{normalize_school_label(school_token)} BD", int(tier_text) + 1

    return None


def skill_material_label(base: str, tier: int) -> str:
    return f"{base} T{tier}"


def school_skill_material_label(school: object, kind: str, tier: int) -> str:
    return skill_material_label(f"{normalize_school_label(school)} {kind}", tier)


def is_skill_book_label(label: str) -> bool:
    base = str(label or "").rpartition(" T")[0].strip()
    return base.endswith(" BD") or base.endswith(" Note")
