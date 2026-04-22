from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import core.student_meta as student_meta


WEAPON_STATE_LABELS: dict[str, str] = {
    "weapon_equipped": "Equipped",
    "weapon_unlocked_not_equipped": "Unlocked",
    "no_weapon_system": "None",
}

FILTER_FIELD_ORDER: tuple[str, ...] = (
    "student_star",
    "weapon_state",
    "farmable",
    "school",
    "rarity",
    "attack_type",
    "defense_type",
    "combat_class",
    "role",
    "position",
    "weapon_type",
    "cover_type",
    "range_type",
    "passive_stat",
    "weapon_passive_stat",
    "extra_passive_stat",
    "skill_buff",
    "skill_debuff",
    "skill_cc",
    "skill_special",
    "skill_heal_targets",
    "skill_dispel_targets",
    "skill_reposition_targets",
    "skill_summon_types",
    "skill_ignore_cover",
    "skill_is_area_damage",
    "skill_buff_specials",
    "skill_knockback",
)

FILTER_FIELD_LABELS: dict[str, str] = {
    "student_star": "Stars",
    "weapon_state": "Weapon",
    "farmable": "Farmable",
    "school": "School",
    "rarity": "Rarity",
    "attack_type": "Attack",
    "defense_type": "Defense",
    "combat_class": "Class",
    "role": "Role",
    "position": "Position",
    "weapon_type": "Weapon Type",
    "cover_type": "Cover",
    "range_type": "Range",
    "passive_stat": "Passive Stat",
    "weapon_passive_stat": "Weapon Passive",
    "extra_passive_stat": "Extra Passive",
    "skill_buff": "Buff Skill",
    "skill_debuff": "Debuff Skill",
    "skill_cc": "Crowd Control",
    "skill_special": "Special Effect",
    "skill_heal_targets": "Heal",
    "skill_dispel_targets": "Dispel",
    "skill_reposition_targets": "Move Skill",
    "skill_summon_types": "Summon",
    "skill_ignore_cover": "EX Ignore Cover",
    "skill_is_area_damage": "EX Area Damage",
    "skill_buff_specials": "Special Buff",
    "skill_knockback": "Knockback / Pull",
}

META_FILTER_KEYS: tuple[str, ...] = tuple(key for key in FILTER_FIELD_ORDER if key not in {"student_star", "weapon_state"})


@dataclass(frozen=True, slots=True)
class FilterOption:
    value: str
    label: str


def enrich_student_row(row: Mapping[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    student_id = str(enriched.get("student_id") or "")
    for key in META_FILTER_KEYS:
        if enriched.get(key) in (None, ""):
            enriched[key] = student_meta.field(student_id, key)
    return enriched


def get_student_value(student: Any, key: str) -> str:
    values = get_student_values(student, key)
    return values[0] if values else ""


def get_student_values(student: Any, key: str) -> tuple[str, ...]:
    owned = True
    if isinstance(student, Mapping):
        owned = bool(student.get("owned", True))
        value = student.get(key)
        if value in (None, "") and key in META_FILTER_KEYS:
            value = student_meta.field(str(student.get("student_id") or ""), key)
    else:
        owned = bool(getattr(student, "owned", True))
        if hasattr(student, key):
            value = getattr(student, key)
        elif key == "student_star" and hasattr(student, "star"):
            value = getattr(student, "star")
        elif key in META_FILTER_KEYS:
            value = student_meta.field(_student_id(student), key)
        else:
            value = None

    if not owned and key in {"student_star", "weapon_state"}:
        return ()
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item) for item in value if str(item))
    return (str(value),)


def _student_id(student: Any) -> str:
    if isinstance(student, Mapping):
        return str(student.get("student_id") or "")
    return str(getattr(student, "student_id", "") or "")


def matches_student_filters(
    student: Any,
    selected_filters: Mapping[str, set[str]],
    query: str = "",
    *,
    hide_jp_only: bool = False,
) -> bool:
    cleaned_query = query.strip().casefold()
    student_id = _student_id(student)
    if hide_jp_only and student_meta.is_jp_only(student_id):
        return False
    if cleaned_query:
        display_name = get_student_value(student, "display_name")
        if cleaned_query not in student_meta.search_blob(student_id, display_name):
            return False

    for key, selected_values in selected_filters.items():
        if not selected_values:
            continue
        if not set(get_student_values(student, key)) & selected_values:
            return False
    return True


def build_filter_options(students: Iterable[Any]) -> dict[str, list[FilterOption]]:
    option_values: dict[str, set[str]] = {key: set() for key in FILTER_FIELD_ORDER}
    for student in students:
        for key in FILTER_FIELD_ORDER:
            option_values[key].update(get_student_values(student, key))

    return {key: _sorted_options(key, values) for key, values in option_values.items()}


def active_filter_count(selected_filters: Mapping[str, set[str]]) -> int:
    return sum(len(values) for values in selected_filters.values())


def summarize_filters(
    selected_filters: Mapping[str, set[str]],
    options: Mapping[str, list[FilterOption]],
    *,
    hide_jp_only: bool = False,
) -> str:
    parts: list[str] = []
    option_map = {
        key: {option.value: option.label for option in field_options}
        for key, field_options in options.items()
    }
    for key in FILTER_FIELD_ORDER:
        values = selected_filters.get(key) or set()
        if not values:
            continue
        labels = [option_map.get(key, {}).get(value, value) for value in sorted(values)]
        if len(labels) <= 2:
            parts.append(f"{FILTER_FIELD_LABELS[key]}: {', '.join(labels)}")
        else:
            parts.append(f"{FILTER_FIELD_LABELS[key]}: {len(labels)} selected")
    if hide_jp_only:
        parts.append("JP only hidden")
    return " | ".join(parts) if parts else "No filters applied"


def format_filter_value(key: str, value: str) -> str:
    if key == "student_star":
        return f"{value} star"
    if key == "weapon_state":
        return WEAPON_STATE_LABELS.get(value, value)
    if key == "farmable":
        return "Farmable" if value == "yes" else "Not Farmable"
    return value.replace("_", " ").title()


def _sorted_options(key: str, values: set[str]) -> list[FilterOption]:
    if key == "student_star":
        ordered = sorted(values, key=lambda value: int(value), reverse=True)
    elif key == "weapon_state":
        priority = {
            "weapon_equipped": 0,
            "weapon_unlocked_not_equipped": 1,
            "no_weapon_system": 2,
        }
        ordered = sorted(values, key=lambda value: (priority.get(value, 99), value))
    elif key == "school":
        ordered = sorted(
            values,
            key=lambda value: (value.strip().casefold() == "etc", format_filter_value(key, value)),
        )
    else:
        ordered = sorted(values, key=lambda value: format_filter_value(key, value))
    return [FilterOption(value=value, label=format_filter_value(key, value)) for value in ordered]
