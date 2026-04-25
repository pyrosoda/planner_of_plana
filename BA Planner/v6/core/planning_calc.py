from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core.equipment_items import EQUIPMENT_SERIES_BY_KEY
from core.planning import GrowthPlan, StudentGoal
from core.schale_skill_material_map import is_skill_book_label
from core import student_meta


BASE_DIR = Path(__file__).resolve().parent.parent
PLANNING_DIR = BASE_DIR / "data" / "planning"


@dataclass(slots=True)
class PlanCostSummary:
    credits: int = 0
    level_exp: int = 0
    equipment_exp: int = 0
    weapon_exp: int = 0
    star_materials: dict[str, int] = field(default_factory=dict)
    equipment_materials: dict[str, int] = field(default_factory=dict)
    level_exp_items: dict[str, int] = field(default_factory=dict)
    equipment_exp_items: dict[str, int] = field(default_factory=dict)
    weapon_exp_items: dict[str, int] = field(default_factory=dict)
    skill_books: dict[str, int] = field(default_factory=dict)
    ex_ooparts: dict[str, int] = field(default_factory=dict)
    skill_ooparts: dict[str, int] = field(default_factory=dict)
    favorite_item_materials: dict[str, int] = field(default_factory=dict)
    stat_materials: dict[str, int] = field(default_factory=dict)
    stat_levels: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "PlanCostSummary") -> None:
        self.credits += other.credits
        self.level_exp += other.level_exp
        self.equipment_exp += other.equipment_exp
        self.weapon_exp += other.weapon_exp
        self.warnings.extend(other.warnings)
        for source, target in (
            (other.star_materials, self.star_materials),
            (other.equipment_materials, self.equipment_materials),
            (other.level_exp_items, self.level_exp_items),
            (other.equipment_exp_items, self.equipment_exp_items),
            (other.weapon_exp_items, self.weapon_exp_items),
            (other.skill_books, self.skill_books),
            (other.ex_ooparts, self.ex_ooparts),
            (other.skill_ooparts, self.skill_ooparts),
            (other.favorite_item_materials, self.favorite_item_materials),
            (other.stat_materials, self.stat_materials),
            (other.stat_levels, self.stat_levels),
        ):
            for key, value in source.items():
                target[key] = target.get(key, 0) + value


STAT_WORKBOOK_NAME = "Item_Icon_WorkBook_PotentialMaxHP"
FAVORITE_GIFT_SELECTION_NAME = "Item_Icon_Favor_Selection"
LEVEL_EXP_ITEM_NAME = "Item_Icon_ExpItem_0"
EQUIPMENT_EXP_ITEM_NAME = "Equipment_Icon_Exp_0"
WEAPON_EXP_ITEM_NAME = "Equipment_Icon_WeaponExpGrowthA_0"
_STAR_CREDIT_CUMULATIVE = {
    0: 0,
    1: 0,
    2: 10_000,
    3: 50_000,
    4: 250_000,
    5: 1_250_000,
}
_STAR_ELEPH_CUMULATIVE = {
    0: 0,
    1: 0,
    2: 30,
    3: 110,
    4: 210,
    5: 330,
}
_WEAPON_STAR_CREDIT_CUMULATIVE = {
    0: 0,
    1: 0,
    2: 1_000_000,
    3: 2_500_000,
    4: 4_500_000,
}
_WEAPON_STAR_ELEPH_CUMULATIVE = {
    0: 0,
    1: 0,
    2: 120,
    3: 300,
    4: 500,
}
_EQUIPMENT_TIER_MATERIALS_CUMULATIVE: dict[int, tuple[int, ...]] = {
    0: (0, 0, 0, 0, 0, 0, 0, 0, 0),
    1: (0, 0, 0, 0, 0, 0, 0, 0, 0),
    2: (15, 0, 0, 0, 0, 0, 0, 0, 0),
    3: (15, 20, 0, 0, 0, 0, 0, 0, 0),
    4: (25, 20, 30, 0, 0, 0, 0, 0, 0),
    5: (40, 40, 30, 35, 0, 0, 0, 0, 0),
    6: (40, 45, 45, 35, 40, 0, 0, 0, 0),
    7: (40, 45, 50, 50, 40, 40, 0, 0, 0),
    8: (40, 45, 50, 55, 55, 40, 40, 0, 0),
    9: (40, 45, 50, 55, 65, 55, 40, 50, 0),
    10: (40, 45, 50, 55, 65, 65, 60, 50, 60),
}
_EQUIPMENT_TOTAL_CREDIT_CUMULATIVE = {
    0: 0,
    1: 1_524,
    2: 10_388,
    3: 42_212,
    4: 116_516,
    5: 235_820,
    6: 405_024,
    7: 629_588,
    8: 915_512,
    9: 1_269_356,
    10: 1_698_220,
}
_EQUIPMENT_TIER_MAX_LEVEL = {
    0: 0,
    1: 10,
    2: 20,
    3: 30,
    4: 40,
    5: 45,
    6: 50,
    7: 55,
    8: 60,
    9: 65,
    10: 70,
}
_EQUIPMENT_LEVEL_ROWS: tuple[tuple[int, int, int, int], ...] = (
    (1, 2, 25, 100),
    (2, 3, 27, 108),
    (3, 4, 30, 120),
    (4, 5, 34, 136),
    (5, 6, 39, 156),
    (6, 7, 45, 180),
    (7, 8, 52, 208),
    (8, 9, 60, 240),
    (9, 10, 69, 276),
    (10, 11, 80, 320),
    (11, 12, 92, 368),
    (12, 13, 105, 420),
    (13, 14, 119, 476),
    (14, 15, 134, 536),
    (15, 16, 150, 600),
    (16, 17, 167, 668),
    (17, 18, 185, 740),
    (18, 19, 204, 816),
    (19, 20, 224, 896),
    (20, 21, 246, 984),
    (21, 22, 269, 1_076),
    (22, 23, 293, 1_172),
    (23, 24, 318, 1_272),
    (24, 25, 344, 1_376),
    (25, 26, 371, 1_484),
    (26, 27, 399, 1_596),
    (27, 28, 428, 1_712),
    (28, 29, 458, 1_832),
    (29, 30, 489, 1_956),
    (30, 31, 522, 2_088),
    (31, 32, 556, 2_224),
    (32, 33, 591, 2_364),
    (33, 34, 627, 2_508),
    (34, 35, 664, 2_656),
    (35, 36, 702, 2_808),
    (36, 37, 741, 2_964),
    (37, 38, 781, 3_124),
    (38, 39, 822, 3_288),
    (39, 40, 864, 3_456),
    (40, 41, 908, 3_632),
    (41, 42, 953, 3_812),
    (42, 43, 999, 3_996),
    (43, 44, 1_046, 4_184),
    (44, 45, 1_094, 4_376),
    (45, 46, 1_143, 4_572),
    (46, 47, 1_193, 4_772),
    (47, 48, 1_244, 4_976),
    (48, 49, 1_296, 5_184),
    (49, 50, 1_349, 5_396),
    (50, 51, 1_404, 5_616),
    (51, 52, 1_460, 5_840),
    (52, 53, 1_517, 6_068),
    (53, 54, 1_575, 6_300),
    (54, 55, 1_634, 6_536),
    (55, 56, 1_694, 6_776),
    (56, 57, 1_755, 7_020),
    (57, 58, 1_817, 7_268),
    (58, 59, 1_880, 7_520),
    (59, 60, 1_944, 7_776),
    (60, 61, 2_010, 8_040),
    (61, 62, 2_077, 8_308),
    (62, 63, 2_145, 8_580),
    (63, 64, 2_214, 8_856),
    (64, 65, 2_284, 9_136),
    (65, 66, 2_355, 9_420),
    (66, 67, 2_427, 9_708),
    (67, 68, 2_500, 10_000),
    (68, 69, 2_574, 10_296),
    (69, 70, 2_649, 10_596),
)
_WEAPON_LEVEL_ROWS: tuple[tuple[int, int, int, int], ...] = (
    (1, 2, 25, 4_500),
    (2, 3, 30, 5_400),
    (3, 4, 35, 6_300),
    (4, 5, 40, 7_200),
    (5, 6, 45, 8_100),
    (6, 7, 50, 9_000),
    (7, 8, 55, 9_900),
    (8, 9, 60, 10_800),
    (9, 10, 65, 11_700),
    (10, 11, 70, 12_600),
    (11, 12, 80, 14_400),
    (12, 13, 90, 16_200),
    (13, 14, 100, 18_000),
    (14, 15, 110, 19_800),
    (15, 16, 120, 21_600),
    (16, 17, 130, 23_400),
    (17, 18, 140, 25_200),
    (18, 19, 150, 27_000),
    (19, 20, 160, 28_800),
    (20, 21, 170, 30_600),
    (21, 22, 190, 34_200),
    (22, 23, 210, 37_800),
    (23, 24, 230, 41_400),
    (24, 25, 250, 45_000),
    (25, 26, 270, 48_600),
    (26, 27, 310, 55_800),
    (27, 28, 350, 63_000),
    (28, 29, 390, 70_200),
    (29, 30, 430, 77_400),
    (30, 31, 470, 84_600),
    (31, 32, 530, 95_400),
    (32, 33, 590, 106_200),
    (33, 34, 650, 117_000),
    (34, 35, 710, 127_800),
    (35, 36, 770, 138_600),
    (36, 37, 830, 149_400),
    (37, 38, 890, 160_200),
    (38, 39, 950, 171_000),
    (39, 40, 1_010, 181_800),
    (40, 41, 1_070, 192_600),
    (41, 42, 1_155, 207_900),
    (42, 43, 1_240, 223_200),
    (43, 44, 1_325, 238_500),
    (44, 45, 1_410, 253_800),
    (45, 46, 1_495, 269_100),
    (46, 47, 1_580, 284_400),
    (47, 48, 1_665, 299_700),
    (48, 49, 1_750, 315_000),
    (49, 50, 1_835, 330_300),
    (50, 51, 1_920, 345_600),
    (51, 52, 2_005, 360_900),
    (52, 53, 2_090, 376_200),
    (53, 54, 2_175, 391_500),
    (54, 55, 2_260, 406_800),
    (55, 56, 2_345, 422_100),
    (56, 57, 2_460, 442_800),
    (57, 58, 2_575, 463_500),
    (58, 59, 2_690, 484_200),
    (59, 60, 2_805, 504_900),
)
_STAT_LEVEL_COSTS: tuple[dict[str, int], ...] = (
    {"credits": 0, "workbook": 0, "main_t1": 0, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 10, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 10, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 10, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 10, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 10, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 15, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 15, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 15, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 15, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 15, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 20, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 20, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 20, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 20, "main_t2": 0},
    {"credits": 100_000, "workbook": 2, "main_t1": 20, "main_t2": 0},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 6},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 6},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 6},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 6},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 6},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 8},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 8},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 8},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 8},
    {"credits": 200_000, "workbook": 4, "main_t1": 0, "main_t2": 8},
)


@lru_cache(maxsize=1)
def _load_reference_tables() -> dict:
    path = PLANNING_DIR / "reference_tables.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _cumulative_map(rows: list[dict], key_field: str, value_field: str) -> dict[int, int]:
    result: dict[int, int] = {}
    for row in rows:
        try:
            key = int(row.get(key_field) or 0)
        except Exception:
            continue
        raw_value = row.get(value_field)
        try:
            result[key] = int(raw_value or 0)
        except Exception:
            result[key] = 0
    return result


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value or 0)
    except Exception:
        return default


def _material_label(family: str, index: int) -> str:
    return f"{family} T{index + 1}"


def _eleph_label(student_name: object, student_id: str) -> str:
    name = str(student_name or "").strip()
    return f"{name or student_id} Eleph"


def _equipment_material_label(slot_name: str | None, tier: int) -> str:
    series = EQUIPMENT_SERIES_BY_KEY.get(slot_name or "")
    if series and 1 <= tier <= len(series.tier_names):
        return series.tier_names[tier - 1]
    if slot_name:
        return f"{slot_name} T{tier}"
    return f"Equipment T{tier}"


def _parse_tier_number(tier: str | None) -> int:
    value = (tier or "").strip().upper()
    if not value.startswith("T"):
        return 0
    try:
        return int(value[1:])
    except ValueError:
        return 0


def _stat_delta(current_value: object, target_value: object) -> int:
    current = _safe_int(current_value, 0)
    target = max(current, _safe_int(target_value, current))
    return max(0, target - current)


def _extract_material_delta(rows: list[dict], current_level: int, target_level: int) -> dict[str, int]:
    if target_level <= current_level:
        return {}

    current_row = rows[min(max(current_level, 0), len(rows) - 1)] if rows else {"materials": {}}
    target_row = rows[min(max(target_level, 0), len(rows) - 1)] if rows else {"materials": {}}
    delta: dict[str, int] = {}

    current_materials = current_row.get("materials", {})
    target_materials = target_row.get("materials", {})
    for family, target_values in target_materials.items():
        base_values = current_materials.get(family, ["", "", "", ""])
        for index, raw_target in enumerate(target_values):
            target_amount = _safe_int(raw_target)
            current_amount = _safe_int(base_values[index] if index < len(base_values) else 0)
            if target_amount > current_amount:
                delta[_material_label(family, index)] = target_amount - current_amount
    return delta


def _merge_material(total: dict[str, int], name: str | None, tier_costs: list[int], amount: int) -> None:
    material_name = (name or "").strip()
    if not material_name or amount <= 0:
        return
    for tier, raw in enumerate(tier_costs, start=1):
        value = _safe_int(raw, 0)
        if value > 0:
            key = f"{material_name} T{tier}"
            total[key] = total.get(key, 0) + value * amount


def _add_material_value(total: dict[str, int], name: str | None, tier: int, value: object) -> None:
    material_name = (name or "").strip()
    amount = _safe_int(value, 0)
    if not material_name or amount <= 0:
        return
    key = f"{material_name} T{tier}"
    total[key] = total.get(key, 0) + amount


def _calculate_single_stat_cost(
    main_name: str | None,
    current_level: int,
    target_level: int,
) -> tuple[int, dict[str, int]]:
    materials: dict[str, int] = {}
    current = min(max(current_level, 0), len(_STAT_LEVEL_COSTS) - 1)
    target = min(max(target_level, current), len(_STAT_LEVEL_COSTS) - 1)
    credits = 0

    for level in range(current + 1, target + 1):
        row = _STAT_LEVEL_COSTS[level]
        credits += row["credits"]
        _add_material_value(materials, STAT_WORKBOOK_NAME, 1, row["workbook"])
        _add_material_value(materials, main_name, 1, row["main_t1"])
        _add_material_value(materials, main_name, 2, row["main_t2"])

    return credits, materials


def _calculate_favorite_item_cost(record, goal: StudentGoal) -> tuple[int, dict[str, int]]:
    current_tier = _parse_tier_number(getattr(record, "equip4", None))
    target_tier = max(current_tier, min(2, _safe_int(goal.target_equip4_tier, current_tier)))
    if target_tier < 2 or current_tier >= 2:
        return 0, {}

    main_name = student_meta.growth_material_main(getattr(record, "student_id", "") or "")
    materials: dict[str, int] = {FAVORITE_GIFT_SELECTION_NAME: 4}
    _add_material_value(materials, main_name, 1, 80)
    _add_material_value(materials, main_name, 2, 25)
    return 500_000, materials


def _current_weapon_star(record) -> int:
    state = getattr(record, "weapon_state", None)
    raw_star = _safe_int(getattr(record, "weapon_star", 0), 0)
    if state in ("weapon_equipped", "weapon_unlocked_not_equipped"):
        return max(1, min(raw_star or 1, 4))
    return 0


def _calculate_star_cost(record, goal: StudentGoal) -> tuple[int, dict[str, int]]:
    current_star = _safe_int(getattr(record, "star", 0), 0)
    target_star = max(current_star, _safe_int(goal.target_star, current_star))
    target_weapon_star = max(0, min(4, _safe_int(goal.target_weapon_star, 0)))
    current_weapon_star = _current_weapon_star(record)

    # Unlocking the unique weapon at 5-star is free, so weapon targets imply at least 5-star.
    effective_target_star = max(target_star, 5 if target_weapon_star > 0 or _safe_int(goal.target_weapon_level, 0) > 0 else current_star)
    effective_target_star = min(max(effective_target_star, current_star), 5)
    effective_target_weapon_star = max(current_weapon_star, target_weapon_star)

    eleph_label = _eleph_label(
        getattr(record, "display_name", None) or getattr(record, "title", None),
        getattr(record, "student_id", "") or "",
    )
    materials: dict[str, int] = {}

    credits = max(0, _STAR_CREDIT_CUMULATIVE.get(effective_target_star, 0) - _STAR_CREDIT_CUMULATIVE.get(current_star, 0))
    eleph = max(0, _STAR_ELEPH_CUMULATIVE.get(effective_target_star, 0) - _STAR_ELEPH_CUMULATIVE.get(current_star, 0))

    credits += max(
        0,
        _WEAPON_STAR_CREDIT_CUMULATIVE.get(effective_target_weapon_star, 0)
        - _WEAPON_STAR_CREDIT_CUMULATIVE.get(current_weapon_star, 0),
    )
    eleph += max(
        0,
        _WEAPON_STAR_ELEPH_CUMULATIVE.get(effective_target_weapon_star, 0)
        - _WEAPON_STAR_ELEPH_CUMULATIVE.get(current_weapon_star, 0),
    )

    if eleph > 0:
        materials[eleph_label] = eleph
    return credits, materials


def _merge_material_rows(total: dict[str, int], row: dict[str, int]) -> None:
    for key, value in row.items():
        amount = _safe_int(value, 0)
        if amount > 0:
            total[key] = total.get(key, 0) + amount


def _row_window_total(rows: list[dict[str, int]], current_level: int, target_level: int, *, target_start_level: int) -> dict[str, int]:
    total: dict[str, int] = {}
    if target_level <= current_level:
        return total
    for target in range(max(current_level + 1, target_start_level), target_level + 1):
        index = target - target_start_level
        if 0 <= index < len(rows):
            _merge_material_rows(total, rows[index])
    return total


def _filter_materials(materials: dict[str, int], *, skill_books: bool) -> dict[str, int]:
    filtered: dict[str, int] = {}
    for key, value in materials.items():
        if is_skill_book_label(key) == skill_books:
            filtered[key] = value
    return filtered


def _calculate_skill_book_cost(student_id: str, current_ex: int, target_ex: int, current_skills: list[int], target_skills: list[int]) -> dict[str, int]:
    materials: dict[str, int] = {}
    _merge_material_rows(
        materials,
        _filter_materials(
            _row_window_total(student_meta.mapped_skill_ex_material_rows(student_id), current_ex, target_ex, target_start_level=2),
            skill_books=True,
        ),
    )
    for current_level, target_level in zip(current_skills, target_skills):
        _merge_material_rows(
            materials,
            _filter_materials(
                _row_window_total(student_meta.mapped_skill_material_rows(student_id), current_level, target_level, target_start_level=2),
                skill_books=True,
            ),
        )
    return materials


def _exp_item_breakdown(item_name: str, total_exp: int, yields: tuple[int, int, int, int]) -> dict[str, int]:
    if total_exp <= 0:
        return {}

    smallest = yields[0]
    target_total = ((total_exp + smallest - 1) // smallest) * smallest
    remaining = target_total
    materials: dict[str, int] = {}

    for tier, value in reversed(list(enumerate(yields, start=1))):
        count, remaining = divmod(remaining, value)
        if count > 0:
            materials[f"{item_name} T{tier}"] = count
    return materials


_EQUIPMENT_FULL_TIER_EXP_ITEM_COUNTS: dict[int, tuple[int, int, int, int]] = {
    1: (0, 0, 1, 1),
    2: (0, 1, 1, 1),
    3: (0, 3, 3, 1),
    4: (2, 0, 2, 1),
    5: (3, 0, 0, 1),
    6: (4, 0, 1, 2),
    7: (5, 1, 2, 3),
    8: (6, 3, 3, 4),
    9: (8, 3, 1, 3),
    10: (11, 0, 0, 2),
}


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def _equipment_full_tier_exp_items(tier: int) -> dict[str, int]:
    counts = _EQUIPMENT_FULL_TIER_EXP_ITEM_COUNTS.get(tier)
    if not counts:
        return {}
    items: dict[str, int] = {}
    for item_tier, count in zip((4, 3, 2, 1), counts):
        if count > 0:
            items[f"{EQUIPMENT_EXP_ITEM_NAME} T{item_tier}"] = count
    return items


def _equipment_exp_segment_items(start_level: int, end_level: int) -> dict[str, int]:
    if end_level <= start_level:
        return {}
    exp_map, _credit_map = _equipment_level_cumulative_maps()
    exp = max(0, exp_map.get(end_level, 0) - exp_map.get(start_level, 0))
    return _exp_item_breakdown(EQUIPMENT_EXP_ITEM_NAME, exp, (90, 360, 1_440, 5_760))


def _build_cumulative_maps(rows: tuple[tuple[int, int, int, int], ...]) -> tuple[dict[int, int], dict[int, int]]:
    exp_map: dict[int, int] = {0: 0, 1: 0}
    credit_map: dict[int, int] = {0: 0, 1: 0}
    cumulative_exp = 0
    cumulative_credit = 0
    for start, end, exp_gain, credit_gain in rows:
        cumulative_exp += exp_gain
        cumulative_credit += credit_gain
        exp_map[end] = cumulative_exp
        credit_map[end] = cumulative_credit
        if start not in exp_map:
            exp_map[start] = cumulative_exp - exp_gain
            credit_map[start] = cumulative_credit - credit_gain
    return exp_map, credit_map


@lru_cache(maxsize=1)
def _equipment_level_cumulative_maps() -> tuple[dict[int, int], dict[int, int]]:
    return _build_cumulative_maps(_EQUIPMENT_LEVEL_ROWS)


@lru_cache(maxsize=1)
def _equipment_tier_level_full_costs() -> dict[int, tuple[int, int]]:
    exp_map, credit_map = _equipment_level_cumulative_maps()
    costs: dict[int, tuple[int, int]] = {}
    for tier, max_level in _EQUIPMENT_TIER_MAX_LEVEL.items():
        costs[tier] = (exp_map.get(max_level, 0), credit_map.get(max_level, 0))
    return costs


@lru_cache(maxsize=1)
def _equipment_tier_up_costs() -> dict[int, int]:
    full_level_costs = _equipment_tier_level_full_costs()
    tier_up_costs: dict[int, int] = {0: 0, 1: 0}
    for tier in range(2, max(_EQUIPMENT_TIER_MAX_LEVEL) + 1):
        total_delta = _EQUIPMENT_TOTAL_CREDIT_CUMULATIVE.get(tier, 0) - _EQUIPMENT_TOTAL_CREDIT_CUMULATIVE.get(tier - 1, 0)
        tier_up_costs[tier] = max(0, total_delta - full_level_costs.get(tier, (0, 0))[1])
    return tier_up_costs


@lru_cache(maxsize=1)
def _weapon_level_cumulative_maps() -> tuple[dict[int, int], dict[int, int]]:
    return _build_cumulative_maps(_WEAPON_LEVEL_ROWS)


def _equipment_current_level(current_tier: int, raw_level: object) -> int:
    level = _safe_int(raw_level, 0)
    if level > 0:
        return min(level, _EQUIPMENT_TIER_MAX_LEVEL.get(max(current_tier, 0), 70))
    if current_tier <= 0:
        return 0
    return 1


def _minimum_equipment_tier_for_level(target_level: int) -> int:
    level = max(0, target_level)
    for tier, max_level in sorted(_EQUIPMENT_TIER_MAX_LEVEL.items()):
        if level <= max_level:
            return tier
    return max(_EQUIPMENT_TIER_MAX_LEVEL)


def _calculate_single_equipment_cost(
    slot_name: str | None,
    current_tier: int,
    current_level: int,
    target_tier: int,
    target_level: int,
) -> tuple[int, int, dict[str, int], dict[str, int]]:
    current = min(max(current_tier, 0), 10)
    effective_target_level = min(max(target_level, current_level), _EQUIPMENT_TIER_MAX_LEVEL[10])
    required_tier = _minimum_equipment_tier_for_level(effective_target_level)
    target = min(max(target_tier, required_tier, current), 10)
    if target <= 0:
        return 0, 0, {}, {}

    exp_map, credit_map = _equipment_level_cumulative_maps()
    full_level_costs = _equipment_tier_level_full_costs()
    tier_up_costs = _equipment_tier_up_costs()
    current_max_level = _EQUIPMENT_TIER_MAX_LEVEL[current]
    effective_current_level = min(max(current_level, 0), current_max_level)
    target_max_level = _EQUIPMENT_TIER_MAX_LEVEL[target]
    effective_target_level = min(max(effective_target_level, effective_current_level), target_max_level)

    equipment_exp = 0
    credits = 0
    exp_items: dict[str, int] = {}

    if current > 0:
        bridge_level = current_max_level if target > current else effective_target_level
        segment_exp = max(0, exp_map.get(bridge_level, 0) - exp_map.get(effective_current_level, 0))
        equipment_exp += segment_exp
        credits += max(0, credit_map.get(bridge_level, 0) - credit_map.get(effective_current_level, 0))
        if segment_exp > 0:
            if effective_current_level <= 1 and bridge_level == current_max_level:
                _merge_counts(exp_items, _equipment_full_tier_exp_items(current))
            else:
                _merge_counts(exp_items, _equipment_exp_segment_items(effective_current_level, bridge_level))

    for tier in range(max(current + 1, 1), target + 1):
        credits += tier_up_costs.get(tier, 0)
        if tier == target:
            tier_target_level = effective_target_level
            tier_exp = exp_map.get(tier_target_level, 0)
            tier_credit = credit_map.get(tier_target_level, 0)
        else:
            tier_target_level = _EQUIPMENT_TIER_MAX_LEVEL[tier]
            tier_exp, tier_credit = full_level_costs.get(tier, (0, 0))
        equipment_exp += tier_exp
        credits += tier_credit
        if tier_exp > 0:
            if tier_target_level == _EQUIPMENT_TIER_MAX_LEVEL[tier]:
                _merge_counts(exp_items, _equipment_full_tier_exp_items(tier))
            else:
                _merge_counts(exp_items, _equipment_exp_segment_items(1, tier_target_level))

    materials: dict[str, int] = {}
    target_materials = _EQUIPMENT_TIER_MATERIALS_CUMULATIVE.get(target, tuple())
    current_materials = _EQUIPMENT_TIER_MATERIALS_CUMULATIVE.get(current, tuple())
    for offset, target_amount in enumerate(target_materials, start=2):
        current_amount = current_materials[offset - 2] if offset - 2 < len(current_materials) else 0
        if target_amount > current_amount:
            materials[_equipment_material_label(slot_name, offset)] = target_amount - current_amount

    return credits, equipment_exp, materials, exp_items


def _current_weapon_level(record, target_weapon_level: int) -> int:
    state = getattr(record, "weapon_state", None)
    raw_level = _safe_int(getattr(record, "weapon_level", 0), 0)
    if state in ("weapon_equipped", "weapon_unlocked_not_equipped"):
        return max(1, min(raw_level or 1, 60))
    if target_weapon_level > 0:
        return 1
    return 0


def _weapon_level_cap_for_star(weapon_star: int) -> int:
    return {
        1: 30,
        2: 40,
        3: 50,
        4: 60,
    }.get(max(0, int(weapon_star)), 0)


def _calculate_weapon_level_cost(record, goal: StudentGoal) -> tuple[int, int]:
    target_weapon_star = max(0, min(4, _safe_int(goal.target_weapon_star, 0)))
    effective_weapon_star = max(_current_weapon_star(record), target_weapon_star)
    target_level = max(0, min(_safe_int(goal.target_weapon_level, 0), _weapon_level_cap_for_star(effective_weapon_star)))
    current_level = _current_weapon_level(record, target_level)
    if target_level <= current_level:
        return 0, 0

    exp_map, credit_map = _weapon_level_cumulative_maps()
    credits = max(0, credit_map.get(target_level, 0) - credit_map.get(current_level, 0))
    weapon_exp = max(0, exp_map.get(target_level, 0) - exp_map.get(current_level, 0))
    return credits, weapon_exp


def _calculate_ex_ooparts(student_id: str, current_level: int, target_level: int) -> dict[str, int]:
    return _filter_materials(
        _row_window_total(student_meta.mapped_skill_ex_material_rows(student_id), current_level, target_level, target_start_level=2),
        skill_books=False,
    )


def _calculate_skill_ooparts(student_id: str, current_levels: list[int], target_levels: list[int]) -> dict[str, int]:
    total: dict[str, int] = {}
    for current_level, target_level in zip(current_levels, target_levels):
        _merge_material_rows(
            total,
            _filter_materials(
                _row_window_total(student_meta.mapped_skill_material_rows(student_id), current_level, target_level, target_start_level=2),
                skill_books=False,
            ),
        )
    return total


def calculate_goal_cost(record, goal: StudentGoal) -> PlanCostSummary:
    summary = PlanCostSummary()
    reference_tables = _load_reference_tables()

    level_rows = reference_tables.get("level_table", {}).get("rows", [])
    ex_credit_rows = reference_tables.get("credit_table_ex", {}).get("rows", [])
    skill_credit_rows = reference_tables.get("credit_table_skill", {}).get("rows", [])

    level_credit_map = _cumulative_map(level_rows, "레벨", "누적 크레딧")
    level_exp_map = _cumulative_map(level_rows, "레벨", "누적 경험치")
    ex_credit_map = _cumulative_map(ex_credit_rows, "EX Lv", "크레딧 필요량(누적)")
    skill_credit_map = _cumulative_map(skill_credit_rows, "Skill Lv", "크레딧 필요량 (누적)")

    current_level = _safe_int(getattr(record, "level", 0))
    target_level = max(current_level, _safe_int(goal.target_level, current_level))
    summary.credits += max(0, level_credit_map.get(target_level, 0) - level_credit_map.get(current_level, 0))
    summary.level_exp += max(0, level_exp_map.get(target_level, 0) - level_exp_map.get(current_level, 0))
    summary.level_exp_items = _exp_item_breakdown(LEVEL_EXP_ITEM_NAME, summary.level_exp, (50, 500, 2_000, 10_000))

    star_credits, star_materials = _calculate_star_cost(record, goal)
    summary.credits += star_credits
    summary.star_materials = star_materials

    favorite_item_credits, favorite_item_materials = _calculate_favorite_item_cost(record, goal)
    summary.credits += favorite_item_credits
    summary.favorite_item_materials = favorite_item_materials

    slot_names = student_meta.equipment_slots(getattr(record, "student_id", "")) if getattr(record, "student_id", None) else (None, None, None)
    for slot_index, (equip_slot, equip_level_field, goal_target, goal_target_level) in enumerate((
        ("equip1", "equip1_level", goal.target_equip1_tier, goal.target_equip1_level),
        ("equip2", "equip2_level", goal.target_equip2_tier, goal.target_equip2_level),
        ("equip3", "equip3_level", goal.target_equip3_tier, goal.target_equip3_level),
    )):
        slot_name = slot_names[slot_index] if slot_index < len(slot_names) else None
        current_tier = _parse_tier_number(getattr(record, equip_slot, None))
        target_tier = max(current_tier, _safe_int(goal_target, current_tier))
        current_equip_level = _equipment_current_level(current_tier, getattr(record, equip_level_field, 0))
        target_equip_level = max(current_equip_level, _safe_int(goal_target_level, current_equip_level))
        equip_credits, equip_exp, equip_materials, equip_exp_items = _calculate_single_equipment_cost(
            slot_name,
            current_tier,
            current_equip_level,
            target_tier,
            target_equip_level,
        )
        summary.credits += equip_credits
        summary.equipment_exp += equip_exp
        for key, value in equip_materials.items():
            summary.equipment_materials[key] = summary.equipment_materials.get(key, 0) + value
        _merge_counts(summary.equipment_exp_items, equip_exp_items)

    current_ex = _safe_int(getattr(record, "ex_skill", 0))
    target_ex = max(current_ex, _safe_int(goal.target_ex_skill, current_ex))
    summary.credits += max(0, ex_credit_map.get(target_ex, 0) - ex_credit_map.get(current_ex, 0))

    weapon_level_credits, weapon_exp = _calculate_weapon_level_cost(record, goal)
    summary.credits += weapon_level_credits
    summary.weapon_exp += weapon_exp
    summary.weapon_exp_items = _exp_item_breakdown(
        WEAPON_EXP_ITEM_NAME,
        summary.weapon_exp,
        (10, 50, 200, 1_000),
    )

    current_skills = [
        _safe_int(getattr(record, "skill1", 0)),
        _safe_int(getattr(record, "skill2", 0)),
        _safe_int(getattr(record, "skill3", 0)),
    ]
    target_skills = [
        max(current_skills[0], _safe_int(goal.target_skill1, current_skills[0])),
        max(current_skills[1], _safe_int(goal.target_skill2, current_skills[1])),
        max(current_skills[2], _safe_int(goal.target_skill3, current_skills[2])),
    ]
    for current_skill, target_skill in zip(current_skills, target_skills):
        summary.credits += max(0, skill_credit_map.get(target_skill, 0) - skill_credit_map.get(current_skill, 0))

    stat_deltas = {
        "HP": _stat_delta(getattr(record, "stat_hp", 0), goal.target_stat_hp),
        "ATK": _stat_delta(getattr(record, "stat_atk", 0), goal.target_stat_atk),
        "HEAL": _stat_delta(getattr(record, "stat_heal", 0), goal.target_stat_heal),
    }
    summary.stat_levels = {key: value for key, value in stat_deltas.items() if value > 0}

    student_id = getattr(record, "student_id", "") or ""
    if student_id:
        main_name = student_meta.growth_material_main(student_id)
        summary.skill_books = _calculate_skill_book_cost(student_id, current_ex, target_ex, current_skills, target_skills)
        summary.ex_ooparts = _calculate_ex_ooparts(student_id, current_ex, target_ex)
        summary.skill_ooparts = _calculate_skill_ooparts(student_id, current_skills, target_skills)
        for current_stat, target_stat in (
            (_safe_int(getattr(record, "stat_hp", 0)), _safe_int(goal.target_stat_hp, _safe_int(getattr(record, "stat_hp", 0)))),
            (_safe_int(getattr(record, "stat_atk", 0)), _safe_int(goal.target_stat_atk, _safe_int(getattr(record, "stat_atk", 0)))),
            (_safe_int(getattr(record, "stat_heal", 0)), _safe_int(goal.target_stat_heal, _safe_int(getattr(record, "stat_heal", 0)))),
        ):
            stat_credits, stat_materials = _calculate_single_stat_cost(main_name, current_stat, target_stat)
            summary.credits += stat_credits
            for key, value in stat_materials.items():
                summary.stat_materials[key] = summary.stat_materials.get(key, 0) + value
        if (
            target_ex > current_ex or any(target > current for current, target in zip(current_skills, target_skills))
        ) and not summary.ex_ooparts and not summary.skill_ooparts:
            summary.warnings.append("No ooparts metadata found in student_meta.")
    else:
        summary.warnings.append("No student id available for ooparts lookup.")

    return summary


def calculate_plan_totals(records_by_id: dict[str, object], plan: GrowthPlan) -> PlanCostSummary:
    total = PlanCostSummary()
    for goal in plan.goals:
        record = records_by_id.get(goal.student_id)
        if record is None:
            continue
        total.merge(calculate_goal_cost(record, goal))
    return total
