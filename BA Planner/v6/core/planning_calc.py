from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core.planning import GrowthPlan, StudentGoal
from core import student_meta


BASE_DIR = Path(__file__).resolve().parent.parent
PLANNING_DIR = BASE_DIR / "data" / "planning"


@dataclass(slots=True)
class PlanCostSummary:
    credits: int = 0
    level_exp: int = 0
    ex_ooparts: dict[str, int] = field(default_factory=dict)
    skill_ooparts: dict[str, int] = field(default_factory=dict)
    stat_levels: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "PlanCostSummary") -> None:
        self.credits += other.credits
        self.level_exp += other.level_exp
        self.warnings.extend(other.warnings)
        for source, target in (
            (other.ex_ooparts, self.ex_ooparts),
            (other.skill_ooparts, self.skill_ooparts),
            (other.stat_levels, self.stat_levels),
        ):
            for key, value in source.items():
                target[key] = target.get(key, 0) + value


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


def _calculate_ex_ooparts(student_id: str, current_level: int, target_level: int) -> dict[str, int]:
    window_total: dict[str, int] = {}
    main_costs = student_meta.growth_material_main_ex_levels(student_id)
    sub_costs = student_meta.growth_material_sub_ex_levels(student_id)
    main_name = student_meta.growth_material_main(student_id)
    sub_name = student_meta.growth_material_sub(student_id)
    for target in range(max(current_level + 1, 2), target_level + 1):
        main_index = target - 2
        sub_index = target - 2
        if 0 <= main_index < len(main_costs):
            _add_material_value(window_total, main_name, main_index + 1, main_costs[main_index])
        if 0 <= sub_index < len(sub_costs):
            _add_material_value(window_total, sub_name, sub_index + 1, sub_costs[sub_index])
    return window_total


def _calculate_skill_ooparts(student_id: str, current_levels: list[int], target_levels: list[int]) -> dict[str, int]:
    total: dict[str, int] = {}
    main_costs = student_meta.growth_material_main_skill_levels(student_id)
    sub_costs = student_meta.growth_material_sub_skill_levels(student_id)
    main_name = student_meta.growth_material_main(student_id)
    sub_name = student_meta.growth_material_sub(student_id)

    for current_level, target_level in zip(current_levels, target_levels):
        for target in range(max(current_level + 1, 3), target_level + 1):
            index = target - 3
            if 0 <= index < len(main_costs):
                _add_material_value(total, main_name, index + 1, main_costs[index])
            if 0 <= index < len(sub_costs):
                _add_material_value(total, sub_name, index + 1, sub_costs[index])
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

    current_ex = _safe_int(getattr(record, "ex_skill", 0))
    target_ex = max(current_ex, _safe_int(goal.target_ex_skill, current_ex))
    summary.credits += max(0, ex_credit_map.get(target_ex, 0) - ex_credit_map.get(current_ex, 0))

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
        summary.ex_ooparts = _calculate_ex_ooparts(student_id, current_ex, target_ex)
        summary.skill_ooparts = _calculate_skill_ooparts(student_id, current_skills, target_skills)
        if (
            target_ex > current_ex or any(target > current for current, target in zip(current_skills, target_skills))
        ) and not summary.ex_ooparts and not summary.skill_ooparts:
            summary.warnings.append("No ooparts metadata found in student_meta.")
    else:
        summary.warnings.append("No student id available for ooparts lookup.")

    if any(
        value not in (None, 0)
        for value in (
            goal.target_star,
            goal.target_weapon_level,
            goal.target_weapon_star,
            goal.target_equip1_tier,
            goal.target_equip2_tier,
            goal.target_equip3_tier,
            goal.target_stat_hp,
            goal.target_stat_atk,
            goal.target_stat_heal,
        )
    ):
        summary.warnings.append("Star, weapon, equipment, and stat costs are not included yet.")

    return summary


def calculate_plan_totals(records_by_id: dict[str, object], plan: GrowthPlan) -> PlanCostSummary:
    total = PlanCostSummary()
    for goal in plan.goals:
        record = records_by_id.get(goal.student_id)
        if record is None:
            continue
        total.merge(calculate_goal_cost(record, goal))
    return total
