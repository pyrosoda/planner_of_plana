from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from tools.student_meta_tool import _write_students, get_students


STUDENTS_URL = "https://schaledb.com/data/en/students.min.json"
SKILL_FIELDS: tuple[str, ...] = (
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
YES_NO_FIELDS: frozenset[str] = frozenset(
    {
        "skill_ignore_cover",
        "skill_is_area_damage",
        "skill_knockback",
    }
)
PATH_EXCEPTIONS: dict[str, str] = {
    "hoshino_battle": "hoshino_battle_tank",
    "shiroko_riding": "shiroko_cycling",
    "shoukouhou_misaki": "shokuhou_misaki",
    "shun_kid": "shun_small",
}
PATH_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("_bunny_girl", "_bunnygirl"),
    ("_school_uniform", "_uniform"),
    ("_new_year", "_newyear"),
    ("_hot_springs", "_onsen"),
    ("_sportswear", "_track"),
    ("_camping", "_camp"),
    ("_part_timer", "_parttime"),
)


def _fetch_students() -> dict[str, dict[str, Any]]:
    request = Request(
        STUDENTS_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request) as response:
        return json.load(response)


def _normalize_path(student_id: str) -> str:
    if student_id in PATH_EXCEPTIONS:
        return PATH_EXCEPTIONS[student_id]

    normalized = student_id
    for old, new in PATH_REPLACEMENTS:
        normalized = normalized.replace(old, new)
    return normalized


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _stat_prefix(effect: dict[str, Any]) -> str | None:
    stat = effect.get("Stat")
    if not isinstance(stat, str) or "_" not in stat:
        return None
    return stat.split("_", 1)[0]


def _flatten_skill_pool(student: dict[str, Any], schale_students: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    skills = student.get("Skills") or {}
    gear_released = ((student.get("Gear") or {}).get("Released") or [False, False, False])[0]

    for skill_name, skill in skills.items():
        if skill_name == "GearPublic" and not gear_released:
            continue
        pool.append(skill)
        pool.extend(skill.get("ExtraSkills") or [])

    for summon in student.get("Summons") or []:
        summon_id = str(summon.get("Id"))
        summon_student = schale_students.get(summon_id) or {}
        pool.extend((summon_student.get("Skills") or {}).values())

    return pool


def _skill_values(student: dict[str, Any], schale_students: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "passive_stat": [],
        "weapon_passive_stat": [],
        "extra_passive_stat": [],
        "skill_buff": [],
        "skill_debuff": [],
        "skill_cc": [],
        "skill_special": [],
        "skill_heal_targets": [],
        "skill_dispel_targets": [],
        "skill_reposition_targets": [],
        "skill_summon_types": [],
        "skill_ignore_cover": "no",
        "skill_is_area_damage": "no",
        "skill_buff_specials": [],
        "skill_knockback": "no",
    }

    for field_name, skill_name in (
        ("passive_stat", "Passive"),
        ("weapon_passive_stat", "WeaponPassive"),
        ("extra_passive_stat", "ExtraPassive"),
    ):
        skill = (student.get("Skills") or {}).get(skill_name) or {}
        for effect in skill.get("Effects") or []:
            if (
                effect.get("Type") == "Buff"
                and "Self" in _listify(effect.get("Target"))
                and not effect.get("Duration")
            ):
                stat = _stat_prefix(effect)
                if stat:
                    result[field_name].append(stat)

    skill_pool = _flatten_skill_pool(student, schale_students)
    ex_skill = ((student.get("Skills") or {}).get("Ex") or {})
    ex_effects = ex_skill.get("Effects") or []
    ex_radius = ex_skill.get("Radius") or []

    if any(effect.get("Type") == "Damage" and effect.get("Block") == 0 for effect in ex_effects):
        result["skill_ignore_cover"] = "yes"
    if any(effect.get("Type") == "Damage" for effect in ex_effects) and ex_radius:
        result["skill_is_area_damage"] = "yes"

    for skill in skill_pool:
        for effect in skill.get("Effects") or []:
            effect_type = effect.get("Type")
            targets = _listify(effect.get("Target"))
            stat = _stat_prefix(effect)

            if (
                effect_type == "Buff"
                and any(str(target).startswith("Ally") for target in targets)
                and stat
            ):
                result["skill_buff"].append(stat)

            if effect_type == "Regen" and any(target in {"Ally", "Any"} for target in targets):
                result["skill_buff"].append("DotHeal")

            if effect_type == "CostChange" and any(target in {"Ally", "Any"} for target in targets):
                result["skill_buff"].append("CostChange")

            if effect_type == "Shield":
                if any(target in {"Ally", "Any"} for target in targets):
                    result["skill_buff"].append("Shield")
                result["skill_shield"] = "yes"

            if (
                effect_type == "Buff"
                and any(str(target).startswith("Enemy") for target in targets)
                and stat
            ):
                result["skill_debuff"].append(stat)

            if effect_type == "DamageDebuff" and effect.get("Icon"):
                result["skill_debuff"].append(str(effect["Icon"]))

            if effect_type == "ConcentratedTarget":
                result["skill_debuff"].append("ConcentratedTarget")

            if effect_type == "CrowdControl" and effect.get("Icon"):
                result["skill_cc"].append(str(effect["Icon"]))

            if effect_type == "Special" and effect.get("Key"):
                result["skill_special"].append(str(effect["Key"]))

            if effect_type == "Accumulation":
                result["skill_special"].append("Accumulation")

            if effect_type == "Heal":
                result["skill_heal"] = "yes"
                result["skill_heal_targets"].extend(str(target) for target in targets)

            if effect_type == "Dispel":
                result["skill_dispel"] = "yes"
                result["skill_dispel_targets"].extend(str(target) for target in targets)

            reposition = effect.get("Reposition")
            if isinstance(reposition, list):
                result["skill_reposition_targets"].extend(str(target) for target in reposition)

            if effect_type == "Knockback":
                result["skill_knockback"] = "yes"

            if (
                effect_type == "Buff"
                and "AllySupport" in targets
                and stat
            ):
                result["skill_buff_specials"].append(stat)

    for summon in student.get("Summons") or []:
        summon_id = str(summon.get("Id"))
        summon_student = schale_students.get(summon_id) or {}
        summon_type = summon_student.get("PathName")
        if summon_type:
            result["skill_summon_types"].append(str(summon_type))

    for field_name, value in list(result.items()):
        if isinstance(value, list):
            result[field_name] = sorted(set(value))

    result.setdefault("skill_heal", "no")
    result.setdefault("skill_dispel", "no")
    result.setdefault("skill_shield", "no")

    return result


def _apply_skill_fields(students: dict[str, dict[str, Any]], schale_students: dict[str, dict[str, Any]], selected_ids: set[str] | None) -> tuple[int, list[str]]:
    updated_count = 0
    missing: list[str] = []

    path_lookup = {
        student["PathName"]: student
        for student in schale_students.values()
        if isinstance(student, dict) and student.get("PathName")
    }

    for student_id, meta in students.items():
        if selected_ids is not None and student_id not in selected_ids:
            continue

        path_name = _normalize_path(student_id)
        schale_student = path_lookup.get(path_name)
        if schale_student is None:
            missing.append(student_id)
            continue

        skill_values = _skill_values(schale_student, schale_students)
        changed = False
        for field_name in SKILL_FIELDS:
            next_value = skill_values[field_name]
            if meta.get(field_name) != next_value:
                meta[field_name] = next_value
                changed = True
        if changed:
            updated_count += 1

    return updated_count, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync skill metadata from SchaleDB into core.student_meta.")
    parser.add_argument("--student-id", action="append", dest="student_ids", help="Sync only the given local student_id. May be passed multiple times.")
    parser.add_argument("--dry-run", action="store_true", help="Show the sync summary without writing changes.")
    args = parser.parse_args()

    local_students = get_students()
    schale_students = _fetch_students()
    selected_ids = set(args.student_ids) if args.student_ids else None

    updated_count, missing = _apply_skill_fields(local_students, schale_students, selected_ids)

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
