from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from core.planning import GrowthPlan, StudentGoal


BASE_DIR = Path(__file__).resolve().parent.parent
PLANNING_DIR = BASE_DIR / "data" / "planning"


@dataclass(slots=True)
class PlanCostSummary:
    credits: int = 0
    level_exp: int = 0
    ex_ooparts: dict[str, int] = field(default_factory=dict)
    skill_ooparts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def merge(self, other: "PlanCostSummary") -> None:
        self.credits += other.credits
        self.level_exp += other.level_exp
        self.warnings.extend(other.warnings)
        for source, target in (
            (other.ex_ooparts, self.ex_ooparts),
            (other.skill_ooparts, self.skill_ooparts),
        ):
            for key, value in source.items():
                target[key] = target.get(key, 0) + value


@lru_cache(maxsize=1)
def _load_reference_tables() -> dict:
    path = PLANNING_DIR / "reference_tables.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_growth_patterns() -> dict:
    path = PLANNING_DIR / "student_growth_patterns.json"
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


def calculate_goal_cost(record, goal: StudentGoal) -> PlanCostSummary:
    summary = PlanCostSummary()
    reference_tables = _load_reference_tables()
    growth_patterns = _load_growth_patterns()

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

    student_patterns = growth_patterns.get("students", {}).get(getattr(record, "display_name", ""))
    if student_patterns:
        ex_rows = student_patterns.get("ex_rows", [])
        normal_rows = student_patterns.get("normal_rows", [])
        summary.ex_ooparts = _extract_material_delta(ex_rows, current_ex, target_ex)
        skill_delta_totals: dict[str, int] = {}
        for current_skill, target_skill in zip(current_skills, target_skills):
            delta = _extract_material_delta(normal_rows, current_skill, target_skill)
            for key, value in delta.items():
                skill_delta_totals[key] = skill_delta_totals.get(key, 0) + value
        summary.skill_ooparts = skill_delta_totals
    else:
        summary.warnings.append("No student-specific ooparts pattern found.")

    if any(
        value not in (None, 0)
        for value in (
            goal.target_star,
            goal.target_weapon_level,
            goal.target_weapon_star,
            goal.target_equip1_tier,
            goal.target_equip2_tier,
            goal.target_equip3_tier,
            goal.target_bound_level,
        )
    ):
        summary.warnings.append("Star, weapon, equipment, and bound-level costs are not included yet.")

    return summary


def calculate_plan_totals(records_by_id: dict[str, object], plan: GrowthPlan) -> PlanCostSummary:
    total = PlanCostSummary()
    for goal in plan.goals:
        record = records_by_id.get(goal.student_id)
        if record is None:
            continue
        total.merge(calculate_goal_cost(record, goal))
    return total
