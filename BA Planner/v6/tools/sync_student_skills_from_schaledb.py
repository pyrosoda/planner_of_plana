from __future__ import annotations

import argparse
import json
import sys
import re
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


from tools.student_meta_options import FIELD_OPTIONS
from tools.student_meta_tool import _write_students, get_students


STUDENTS_URL = "https://schaledb.com/data/en/students.min.json"
ITEMS_URL = "https://schaledb.com/data/en/items.min.json"
SCALAR_FIELDS: tuple[str, ...] = (
    "school",
    "rarity",
    "recruit_type",
    "attack_type",
    "defense_type",
    "growth_material_main",
    "growth_material_sub",
    "equipment_slot_1",
    "equipment_slot_2",
    "equipment_slot_3",
    "combat_class",
    "cover_type",
    "range_type",
    "role",
    "weapon_type",
    "position",
    "terrain_outdoor",
    "terrain_urban",
    "terrain_indoor",
    "weapon3_terrain_boost",
)
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
ATTACK_TYPE_MAP: dict[str, str] = {
    "Explosion": "Explosive",
    "Pierce": "Piercing",
    "Mystic": "Mystic",
    "Sonic": "Sonic",
    "Chemical": "Chemical",
}
SCHOOL_MAP: dict[str, str] = {
    "RedWinter": "Red Winter",
    "WildHunt": "Wild Hunt",
}
ARTIFACT_ICON_MAP: dict[str, str] = {
    "mandragora": "Madrake Extract",
    "winnistone": "Mystery Stone",
}
DEFENSE_TYPE_MAP: dict[str, str] = {
    "LightArmor": "Light",
    "HeavyArmor": "Heavy",
    "Unarmed": "Special",
    "ElasticArmor": "Elastic",
    "Structure": "Composite",
    "CompositeArmor": "Composite",
}
COMBAT_CLASS_MAP: dict[str, str] = {
    "Main": "striker",
    "Support": "special",
}
ROLE_MAP: dict[str, str] = {
    "DamageDealer": "dealer",
    "Tanker": "tanker",
    "Healer": "healer",
    "Supporter": "supporter",
    "Vehicle": "t_s",
}
RECRUIT_PRIORITY: tuple[tuple[int, str], ...] = (
    (3, "Festival"),
    (2, "Event"),
    (1, "Limited"),
)
TERRAIN_MAP: dict[int, str] = {
    0: "D",
    1: "C",
    2: "B",
    3: "A",
    4: "S",
    5: "SS",
}
WEAPON_BOOST_MAP: dict[str, str] = {
    "Outdoor": "terrain_outdoor",
    "Street": "terrain_urban",
    "Indoor": "terrain_indoor",
}
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


def _fetch_items() -> dict[str, dict[str, Any]]:
    request = Request(
        ITEMS_URL,
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


def _flatten_numbers(value: Any) -> list[int]:
    if isinstance(value, list):
        result: list[int] = []
        for item in value:
            result.extend(_flatten_numbers(item))
        return result
    if isinstance(value, int):
        return [value]
    return []


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def _canonical_artifact_name(name: str, icon: str) -> str | None:
    options = FIELD_OPTIONS.get("growth_material_main", ())
    normalized_name = _normalize_key(name)
    normalized_icon = _normalize_key(icon)
    for option in options:
        if _normalize_key(option) in normalized_name:
            return option
    for icon_key, label in ARTIFACT_ICON_MAP.items():
        if icon_key in normalized_icon:
            return label
    for option in options:
        token = _normalize_key(option.split()[0])
        if token and token in normalized_icon:
            return option
    return None


def _artifact_family_name(material_id: int, items: dict[str, dict[str, Any]]) -> str | None:
    item = items.get(str(material_id))
    if not isinstance(item, dict):
        return None
    if item.get("SubCategory") != "Artifact":
        return None

    candidate = item
    quality = int(item.get("Quality") or 0)
    icon_prefix = str(item.get("Icon", "")).rsplit("_", 1)[0]
    if quality and quality != 2:
        sibling = items.get(str(material_id + (2 - quality)))
        if isinstance(sibling, dict) and str(sibling.get("Icon", "")).rsplit("_", 1)[0] == icon_prefix:
            candidate = sibling

    return _canonical_artifact_name(str(candidate.get("Name", "")), str(candidate.get("Icon", "")))


def _recruit_type(student: dict[str, Any]) -> str:
    codes = set(_flatten_numbers(student.get("IsLimited")))
    for code, label in RECRUIT_PRIORITY:
        if code in codes:
            return label
    return "Regular"


def _terrain_rank(value: Any) -> str | None:
    if not isinstance(value, int):
        return None
    return TERRAIN_MAP.get(value)


def _growth_materials(student: dict[str, Any], items: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
    main = None
    potential_id = student.get("PotentialMaterial")
    if isinstance(potential_id, int):
        main = _artifact_family_name(potential_id, items)

    artifact_counter: Counter[str] = Counter()
    for material_id in _flatten_numbers(student.get("SkillExMaterial")) + _flatten_numbers(student.get("SkillMaterial")):
        family = _artifact_family_name(material_id, items)
        if family:
            artifact_counter[family] += 1

    sub = None
    if main is None and artifact_counter:
        main = artifact_counter.most_common(1)[0][0]
    for family, _count in artifact_counter.most_common():
        if family != main:
            sub = family
            break
    return main, sub


def _scalar_values(student: dict[str, Any], items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    equipment = list(student.get("Equipment") or [])
    growth_main, growth_sub = _growth_materials(student, items)
    return {
        "school": SCHOOL_MAP.get(str(student.get("School")), student.get("School")),
        "rarity": str(student.get("StarGrade")) if student.get("StarGrade") is not None else None,
        "recruit_type": _recruit_type(student),
        "attack_type": ATTACK_TYPE_MAP.get(str(student.get("BulletType"))),
        "defense_type": DEFENSE_TYPE_MAP.get(str(student.get("ArmorType"))),
        "growth_material_main": growth_main,
        "growth_material_sub": growth_sub,
        "equipment_slot_1": equipment[0] if len(equipment) > 0 else None,
        "equipment_slot_2": equipment[1] if len(equipment) > 1 else None,
        "equipment_slot_3": equipment[2] if len(equipment) > 2 else None,
        "combat_class": COMBAT_CLASS_MAP.get(str(student.get("SquadType"))),
        "cover_type": "cover" if bool(student.get("Cover")) else "no_cover",
        "range_type": str(student.get("Range")) if student.get("Range") is not None else None,
        "role": ROLE_MAP.get(str(student.get("TacticRole"))),
        "weapon_type": student.get("WeaponType"),
        "position": str(student.get("Position")).lower() if student.get("Position") else None,
        "terrain_outdoor": _terrain_rank(student.get("OutdoorBattleAdaptation")),
        "terrain_urban": _terrain_rank(student.get("StreetBattleAdaptation")),
        "terrain_indoor": _terrain_rank(student.get("IndoorBattleAdaptation")),
        "weapon3_terrain_boost": WEAPON_BOOST_MAP.get(str((student.get("Weapon") or {}).get("AdaptationType"))),
    }


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


def _apply_sync_fields(
    students: dict[str, dict[str, Any]],
    schale_students: dict[str, dict[str, Any]],
    schale_items: dict[str, dict[str, Any]],
    selected_ids: set[str] | None,
) -> tuple[int, list[str]]:
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

        scalar_values = _scalar_values(schale_student, schale_items)
        skill_values = _skill_values(schale_student, schale_students)
        changed = False
        for field_name in SCALAR_FIELDS:
            next_value = scalar_values[field_name]
            if meta.get(field_name) != next_value:
                meta[field_name] = next_value
                changed = True
        for field_name in SKILL_FIELDS:
            next_value = skill_values[field_name]
            if meta.get(field_name) != next_value:
                meta[field_name] = next_value
                changed = True
        if changed:
            updated_count += 1

    return updated_count, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync full student metadata from SchaleDB into core.student_meta.")
    parser.add_argument("--student-id", action="append", dest="student_ids", help="Sync only the given local student_id. May be passed multiple times.")
    parser.add_argument("--dry-run", action="store_true", help="Show the sync summary without writing changes.")
    args = parser.parse_args()

    local_students = get_students()
    schale_students = _fetch_students()
    schale_items = _fetch_items()
    selected_ids = set(args.student_ids) if args.student_ids else None

    updated_count, missing = _apply_sync_fields(local_students, schale_students, schale_items, selected_ids)

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
