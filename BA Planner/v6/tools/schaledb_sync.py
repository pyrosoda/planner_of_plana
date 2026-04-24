from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from typing import Any
from urllib.request import Request, urlopen

from core.oparts import OPART_FAMILY_EN_BY_ICON_TOKEN
from tools.student_meta_options import FIELD_OPTIONS


STUDENTS_URL = "https://schaledb.com/data/en/students.min.json"
ITEMS_URL = "https://schaledb.com/data/en/items.min.json"
SITE_URL = "https://schaledb.com/student"
BASE_URL = "https://schaledb.com"
SCALAR_FIELDS: tuple[str, ...] = (
    "search_tags",
    "school",
    "rarity",
    "recruit_type",
    "attack_type",
    "defense_type",
    "growth_material_main",
    "growth_material_sub",
    "growth_material_main_ex_levels",
    "growth_material_main_skill_levels",
    "growth_material_sub_ex_levels",
    "growth_material_sub_skill_levels",
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
SYNC_FIELDS: tuple[str, ...] = SCALAR_FIELDS + SKILL_FIELDS
EXCLUDED_SKILL_STATS: frozenset[str] = frozenset({
    "IgnoreDelayCount",
})

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
    **OPART_FAMILY_EN_BY_ICON_TOKEN,
    "aether": "Aether Essence",
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
PATH_EXCEPTIONS: dict[str, str] = {
    "hoshino_battle": "hoshino_battle_tank",
    "shiroko_riding": "shiroko_cycling",
    "shoukouhou_misaki": "shokuhou_misaki",
    "shun_kid": "shun_small",
}
SCHALE_MERGE_PATHS: dict[str, tuple[str, ...]] = {
    "hoshino_battle": ("hoshino_battle_tank", "hoshino_battle_dealer"),
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
REVERSE_PATH_EXCEPTIONS: dict[str, str] = {value: key for key, value in PATH_EXCEPTIONS.items()}
REVERSE_PATH_REPLACEMENTS: tuple[tuple[str, str], ...] = tuple(
    (new, old) for old, new in PATH_REPLACEMENTS
)
VARIANT_LABEL_MAP: dict[str, str] = {
    "bunny_girl": "Bunny Girl",
    "camping": "Camping",
    "cheerleader": "Cheerleader",
    "christmas": "Christmas",
    "dress": "Dress",
    "guide": "Guide",
    "hot_springs": "Hot Springs",
    "idol": "Idol",
    "kid": "Kid",
    "maid": "Maid",
    "magical": "Magical",
    "new_year": "New Year",
    "pajama": "Pajama",
    "part_timer": "Part-Timer",
    "qipao": "Qipao",
    "riding": "Riding",
    "school_uniform": "School Uniform",
    "sportswear": "Sportswear",
    "swimsuit": "Swimsuit",
    "track": "Sportswear",
    "uniform": "School Uniform",
}


def _fetch_json(url: str) -> dict[str, dict[str, Any]]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(request) as response:
        return json.load(response)


def _fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/javascript,text/plain,*/*",
        },
    )
    with urlopen(request) as response:
        return response.read().decode("utf-8", errors="replace")


@lru_cache(maxsize=1)
def fetch_students() -> dict[str, dict[str, Any]]:
    return _fetch_json(STUDENTS_URL)


@lru_cache(maxsize=1)
def fetch_items() -> dict[str, dict[str, Any]]:
    return _fetch_json(ITEMS_URL)


def clear_cache() -> None:
    fetch_students.cache_clear()
    fetch_items.cache_clear()


def _camel_to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _planner_field_for_schale_filter(name: str) -> str:
    if name == "PassiveStat":
        return "passive_stat"
    if name == "WeaponPassiveStat":
        return "weapon_passive_stat"
    if name == "ExtraPassiveStat":
        return "extra_passive_stat"
    if name == "SkillCC":
        return "skill_cc"
    if name.startswith("Skill"):
        return f"skill_{_camel_to_snake(name[5:])}"
    return _camel_to_snake(name)


def _find_student_list_filter_asset(index_html: str) -> str | None:
    matches = re.findall(r'assets/StudentListFilters-[^"\']+\.js', index_html)
    return matches[-1] if matches else None


def _find_index_asset(index_html: str) -> str | None:
    match = re.search(r'src="/(?P<asset>assets/index-[^"]+\.js)"', index_html)
    return match.group("asset") if match else None


def _extract_schaledb_skill_filter_names(script: str) -> tuple[str, ...]:
    names = set(re.findall(r"case\"(Skill[A-Za-z0-9_]+)\"", script))
    names.update(re.findall(r"\b(PassiveStat|WeaponPassiveStat|ExtraPassiveStat)\b", script))
    config_match = re.search(r"studentListFilters:\{(?P<body>.*?)ExcludeAlts:", script)
    if config_match:
        names.update(re.findall(r"([A-Za-z][A-Za-z0-9_]*):(?:\[\]|!1|\{)", config_match.group("body")))
    return tuple(sorted(name for name in names if name.startswith("Skill") or name.endswith("PassiveStat")))


def check_schaledb_filter_schema() -> dict[str, Any]:
    index_html = _fetch_text(SITE_URL)
    asset_path = _find_student_list_filter_asset(index_html)
    if asset_path is None:
        index_asset = _find_index_asset(index_html)
        if index_asset is not None:
            index_script = _fetch_text(f"{BASE_URL}/{index_asset}")
            asset_path = _find_student_list_filter_asset(index_script)
    if asset_path is None:
        raise RuntimeError("Could not find the SchaleDB StudentListFilters asset.")

    script = _fetch_text(f"{BASE_URL}/{asset_path}")
    schale_filters = _extract_schaledb_skill_filter_names(script)
    mapped_fields = tuple(_planner_field_for_schale_filter(name) for name in schale_filters)
    known_fields = set(SKILL_FIELDS)
    missing_fields = tuple(field for field in mapped_fields if field not in known_fields)
    stale_fields = tuple(field for field in SKILL_FIELDS if field not in set(mapped_fields))
    return {
        "asset": asset_path,
        "schale_filters": schale_filters,
        "mapped_fields": mapped_fields,
        "missing_fields": missing_fields,
        "stale_fields": stale_fields,
    }


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def parse_student_source(source: str) -> str:
    text = (source or "").strip()
    if not text:
        raise ValueError("SchaleDB URL or student slug is required.")
    text = text.rstrip("/")
    match = re.search(r"/students?/([^/?#]+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().lower()
    match = re.search(r"([a-z0-9_]+)$", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().lower()
    raise ValueError(f"Could not parse a student slug from: {source}")


def local_id_to_schale_path(student_id: str) -> str:
    if student_id in PATH_EXCEPTIONS:
        return PATH_EXCEPTIONS[student_id]

    normalized = student_id
    for old, new in PATH_REPLACEMENTS:
        normalized = normalized.replace(old, new)
    return normalized


def schale_path_to_local_id(path_name: str) -> str:
    normalized = path_name.strip().lower()
    normalized = REVERSE_PATH_EXCEPTIONS.get(normalized, normalized)
    for old, new in REVERSE_PATH_REPLACEMENTS:
        normalized = normalized.replace(old, new)
    return normalized


def _student_path_lookup(schale_students: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        _normalize_key(str(student.get("PathName"))): student
        for student in schale_students.values()
        if isinstance(student, dict) and student.get("PathName")
    }


def _schale_student_by_path(
    path_name: str,
    path_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    return path_lookup.get(_normalize_key(path_name))


def get_schale_student(source: str, *, schale_students: dict[str, dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    schale_students = schale_students or fetch_students()
    slug = parse_student_source(source)
    lookup = _student_path_lookup(schale_students)
    student = _schale_student_by_path(slug, lookup)
    if student is None:
        student = _schale_student_by_path(local_id_to_schale_path(slug), lookup)
    if student is None:
        raise KeyError(slug)
    return str(student.get("PathName") or slug), student


def _listify(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _flatten_text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_flatten_text_values(item))
        return values
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            values.extend(_flatten_text_values(item))
        return values
    text = str(value).strip()
    return [text] if text else []


def _unique_text_values(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for text in _flatten_text_values(value):
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _flatten_numbers(value: Any) -> list[int]:
    if isinstance(value, list):
        result: list[int] = []
        for item in value:
            result.extend(_flatten_numbers(item))
        return result
    if isinstance(value, int):
        return [value]
    return []


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


def _opart_amounts_for_family(
    material_rows: Any,
    amount_rows: Any,
    family_name: str | None,
    items: dict[str, dict[str, Any]],
) -> list[int]:
    material_list = material_rows if isinstance(material_rows, list) else []
    amount_list = amount_rows if isinstance(amount_rows, list) else []
    if family_name is None:
        return [0 for _ in material_list]
    results: list[int] = []
    for idx, materials in enumerate(material_list):
        row_materials = materials if isinstance(materials, list) else []
        row_amounts = amount_list[idx] if idx < len(amount_list) and isinstance(amount_list[idx], list) else []
        total = 0
        for material_idx, material_id in enumerate(row_materials):
            if not isinstance(material_id, int):
                continue
            if _artifact_family_name(material_id, items) != family_name:
                continue
            if material_idx < len(row_amounts):
                total += int(row_amounts[material_idx])
        results.append(total)
    return results


def _growth_material_level_amounts(student: dict[str, Any], items: dict[str, dict[str, Any]]) -> dict[str, list[int]]:
    main_name, sub_name = _growth_materials(student, items)
    return {
        "growth_material_main_ex_levels": _opart_amounts_for_family(
            student.get("SkillExMaterial"),
            student.get("SkillExMaterialAmount"),
            main_name,
            items,
        ),
        "growth_material_main_skill_levels": _opart_amounts_for_family(
            student.get("SkillMaterial"),
            student.get("SkillMaterialAmount"),
            main_name,
            items,
        ),
        "growth_material_sub_ex_levels": _opart_amounts_for_family(
            student.get("SkillExMaterial"),
            student.get("SkillExMaterialAmount"),
            sub_name,
            items,
        ),
        "growth_material_sub_skill_levels": _opart_amounts_for_family(
            student.get("SkillMaterial"),
            student.get("SkillMaterialAmount"),
            sub_name,
            items,
        ),
    }


def scalar_values(student: dict[str, Any], items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    equipment = list(student.get("Equipment") or [])
    growth_main, growth_sub = _growth_materials(student, items)
    result = {
        "search_tags": _unique_text_values(student.get("SearchTags")),
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
    result.update(_growth_material_level_amounts(student, items))
    return result


def _stat_prefix(effect: dict[str, Any]) -> str | None:
    stat = effect.get("Stat")
    if not isinstance(stat, str) or "_" not in stat:
        return None
    prefix = stat.split("_", 1)[0]
    return None if prefix in EXCLUDED_SKILL_STATS else prefix


def _last_effect_value(effect: dict[str, Any]) -> int | float | None:
    value = effect.get("Value")
    while isinstance(value, list) and value:
        value = value[-1]
    return value if isinstance(value, (int, float)) else None


def _has_positive_value(effect: dict[str, Any]) -> bool:
    value = _last_effect_value(effect)
    return value is not None and value > 0


def _effect_targets(effect: dict[str, Any]) -> list[str]:
    return [str(target) for target in _listify(effect.get("Target"))]


def _flatten_skill_pool(student: dict[str, Any], schale_students: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    pool: list[dict[str, Any]] = []
    skills = student.get("Skills") or {}
    gear_released = ((student.get("Gear") or {}).get("Released") or [False, False, False])[0]

    def add_skill(skill: Any) -> None:
        if not isinstance(skill, dict):
            return
        pool.append(skill)
        for extra_skill in skill.get("ExtraSkills") or []:
            add_skill(extra_skill)

    for skill_name, skill in skills.items():
        if skill_name == "GearPublic" and not gear_released:
            continue
        add_skill(skill)

    for summon in student.get("Summons") or []:
        summon_id = str(summon.get("Id"))
        summon_student = schale_students.get(summon_id) or {}
        for skill in (summon_student.get("Skills") or {}).values():
            add_skill(skill)

    return pool


def skill_values(student: dict[str, Any], schale_students: dict[str, dict[str, Any]]) -> dict[str, Any]:
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
                and "Self" in _effect_targets(effect)
                and not effect.get("Duration")
                and _has_positive_value(effect)
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
            targets = _effect_targets(effect)
            stat = _stat_prefix(effect)

            if (
                effect_type == "Buff"
                and any(str(target).startswith("Ally") for target in targets)
                and stat
                and _has_positive_value(effect)
            ):
                result["skill_buff"].append(stat)

            if effect_type == "Regen" and any(target in {"Ally", "Any"} for target in targets):
                result["skill_buff"].append("DotHeal")

            if effect_type == "CostChange" and any(target in {"Ally", "Any"} for target in targets):
                result["skill_buff"].append("CostChange")

            if effect_type == "Shield" and any(target in {"Ally", "Any"} for target in targets):
                result["skill_buff"].append("Shield")

            if (
                effect_type == "Buff"
                and any(str(target).startswith("Enemy") for target in targets)
                and stat
                and _has_positive_value(effect)
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
                result["skill_heal_targets"].extend(str(target) for target in targets)

            if effect_type == "Dispel":
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
                and student.get("SquadType") == "Main"
                and _has_positive_value(effect)
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

    return result


def _merge_skill_values(*payloads: dict[str, Any]) -> dict[str, Any]:
    if not payloads:
        return {}
    merged = dict(payloads[0])
    for payload in payloads[1:]:
        for field_name in SKILL_FIELDS:
            current = merged.get(field_name)
            incoming = payload.get(field_name)
            if isinstance(current, list) or isinstance(incoming, list):
                values: list[str] = []
                for source in (current, incoming):
                    values.extend(str(item) for item in _listify(source) if str(item))
                merged[field_name] = sorted(set(values))
            elif current == "yes" or incoming == "yes":
                merged[field_name] = "yes"
            elif current is None:
                merged[field_name] = incoming
    return merged


def merged_skill_values(
    local_student_id: str,
    primary_student: dict[str, Any],
    schale_students: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    path_lookup = _student_path_lookup(schale_students)
    merge_paths = SCHALE_MERGE_PATHS.get(local_student_id)
    if not merge_paths:
        return skill_values(primary_student, schale_students)

    payloads: list[dict[str, Any]] = []
    for path_name in merge_paths:
        student = _schale_student_by_path(path_name, path_lookup)
        if student is not None:
            payloads.append(skill_values(student, schale_students))
    if not payloads:
        return skill_values(primary_student, schale_students)
    return _merge_skill_values(*payloads)


def _guess_variant_label(local_student_id: str, existing_students: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
    if local_student_id in existing_students:
        meta = existing_students[local_student_id]
        group = str(meta.get("group") or meta.get("display_name") or local_student_id)
        variant = meta.get("variant")
        return group, None if variant in {"", None} else str(variant)

    candidates = [
        existing_id
        for existing_id in existing_students
        if local_student_id.startswith(f"{existing_id}_")
    ]
    if not candidates:
        return None, None

    base_id = max(candidates, key=len)
    suffix = local_student_id[len(base_id) + 1 :]
    base_meta = existing_students[base_id]
    group = str(base_meta.get("group") or base_meta.get("display_name") or base_id)
    variant = VARIANT_LABEL_MAP.get(suffix)
    if variant is None:
        variant = suffix.replace("_", " ").title() if suffix else None
    return group, variant


def _best_display_name(student: dict[str, Any], fallback: str) -> str:
    for key in ("Name", "FamilyName", "PersonalName"):
        value = str(student.get(key) or "").strip()
        if value:
            return value
    return fallback


def build_student_meta_from_schale(
    source: str,
    *,
    existing_students: dict[str, dict[str, Any]] | None = None,
    preferred_student_id: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if force_refresh:
        clear_cache()

    existing_students = existing_students or {}
    schale_students = fetch_students()
    schale_items = fetch_items()
    slug, schale_student = get_schale_student(source, schale_students=schale_students)
    local_student_id = (preferred_student_id or "").strip() or schale_path_to_local_id(slug)
    current_meta = dict(existing_students.get(local_student_id, {}))

    group_hint, variant_hint = _guess_variant_label(local_student_id, existing_students)
    display_name = str(current_meta.get("display_name") or _best_display_name(schale_student, local_student_id))
    group_name = str(current_meta.get("group") or group_hint or display_name)
    variant_name = current_meta.get("variant", variant_hint)

    next_meta: dict[str, Any] = {
        "display_name": display_name,
        "template_name": str(current_meta.get("template_name") or f"{local_student_id}.png"),
        "group": group_name,
        "variant": None if variant_name in {"", None} else str(variant_name),
    }
    next_meta.update(scalar_values(schale_student, schale_items))
    next_meta.update(merged_skill_values(local_student_id, schale_student, schale_students))

    changed_fields = sorted(
        field_name
        for field_name in next_meta
        if current_meta.get(field_name) != next_meta.get(field_name)
    )
    return {
        "student_id": local_student_id,
        "slug": slug,
        "is_new": local_student_id not in existing_students,
        "current_meta": current_meta,
        "meta": next_meta,
        "changed_fields": changed_fields,
        "schale_name": _best_display_name(schale_student, local_student_id),
    }


def apply_sync_fields(
    students: dict[str, dict[str, Any]],
    *,
    selected_ids: set[str] | None = None,
    force_refresh: bool = False,
) -> tuple[int, list[str]]:
    if force_refresh:
        clear_cache()

    schale_students = fetch_students()
    schale_items = fetch_items()
    path_lookup = _student_path_lookup(schale_students)
    updated_count = 0
    missing: list[str] = []

    for student_id, meta in students.items():
        if selected_ids is not None and student_id not in selected_ids:
            continue

        path_name = local_id_to_schale_path(student_id)
        schale_student = path_lookup.get(_normalize_key(path_name))
        if schale_student is None:
            missing.append(student_id)
            continue

        changed = False
        scalar = scalar_values(schale_student, schale_items)
        skills = merged_skill_values(student_id, schale_student, schale_students)
        for field_name in SCALAR_FIELDS:
            next_value = scalar[field_name]
            if meta.get(field_name) != next_value:
                meta[field_name] = next_value
                changed = True
        for field_name in SKILL_FIELDS:
            next_value = skills[field_name]
            if meta.get(field_name) != next_value:
                meta[field_name] = next_value
                changed = True
        if changed:
            updated_count += 1

    return updated_count, missing
