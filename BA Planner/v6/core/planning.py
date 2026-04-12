from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

MAX_TARGET_STAR = 5
MAX_TARGET_LEVEL = 100
MAX_TARGET_EX_SKILL = 5
MAX_TARGET_SKILL = 10
MAX_TARGET_WEAPON_STAR = 4
MAX_TARGET_WEAPON_LEVEL = 60
MAX_TARGET_EQUIP_TIER = 10
MAX_TARGET_EQUIP_LEVEL = 70
MAX_TARGET_STAT = 25


@dataclass(slots=True)
class StudentGoal:
    student_id: str
    favorite: bool = True
    target_level: int | None = None
    target_star: int | None = None
    target_weapon_level: int | None = None
    target_weapon_star: int | None = None
    target_ex_skill: int | None = None
    target_skill1: int | None = None
    target_skill2: int | None = None
    target_skill3: int | None = None
    target_equip1_tier: int | None = None
    target_equip2_tier: int | None = None
    target_equip3_tier: int | None = None
    target_equip1_level: int | None = None
    target_equip2_level: int | None = None
    target_equip3_level: int | None = None
    target_stat_hp: int | None = None
    target_stat_atk: int | None = None
    target_stat_heal: int | None = None
    notes: str = ""


@dataclass(slots=True)
class GrowthPlan:
    version: int = 1
    goals: list[StudentGoal] = field(default_factory=list)

    def goal_map(self) -> dict[str, StudentGoal]:
        return {goal.student_id: goal for goal in self.goals}


def _clamp_optional_int(
    value: int | None,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    number = max(minimum, number)
    if maximum is not None:
        number = min(number, maximum)
    return number


def sanitize_goal(goal: StudentGoal) -> StudentGoal:
    goal.target_level = _clamp_optional_int(goal.target_level, maximum=MAX_TARGET_LEVEL)
    goal.target_star = _clamp_optional_int(goal.target_star, maximum=MAX_TARGET_STAR)
    goal.target_ex_skill = _clamp_optional_int(goal.target_ex_skill, maximum=MAX_TARGET_EX_SKILL)
    goal.target_skill1 = _clamp_optional_int(goal.target_skill1, maximum=MAX_TARGET_SKILL)
    goal.target_skill2 = _clamp_optional_int(goal.target_skill2, maximum=MAX_TARGET_SKILL)
    goal.target_skill3 = _clamp_optional_int(goal.target_skill3, maximum=MAX_TARGET_SKILL)
    goal.target_weapon_level = _clamp_optional_int(goal.target_weapon_level, maximum=MAX_TARGET_WEAPON_LEVEL)
    goal.target_weapon_star = _clamp_optional_int(goal.target_weapon_star, maximum=MAX_TARGET_WEAPON_STAR)
    goal.target_equip1_tier = _clamp_optional_int(goal.target_equip1_tier, maximum=MAX_TARGET_EQUIP_TIER)
    goal.target_equip2_tier = _clamp_optional_int(goal.target_equip2_tier, maximum=MAX_TARGET_EQUIP_TIER)
    goal.target_equip3_tier = _clamp_optional_int(goal.target_equip3_tier, maximum=MAX_TARGET_EQUIP_TIER)
    goal.target_equip1_level = _clamp_optional_int(goal.target_equip1_level, maximum=MAX_TARGET_EQUIP_LEVEL)
    goal.target_equip2_level = _clamp_optional_int(goal.target_equip2_level, maximum=MAX_TARGET_EQUIP_LEVEL)
    goal.target_equip3_level = _clamp_optional_int(goal.target_equip3_level, maximum=MAX_TARGET_EQUIP_LEVEL)
    goal.target_stat_hp = _clamp_optional_int(goal.target_stat_hp, maximum=MAX_TARGET_STAT)
    goal.target_stat_atk = _clamp_optional_int(goal.target_stat_atk, maximum=MAX_TARGET_STAT)
    goal.target_stat_heal = _clamp_optional_int(goal.target_stat_heal, maximum=MAX_TARGET_STAT)
    return goal


def load_plan(path: Path) -> GrowthPlan:
    if not path.exists():
        return GrowthPlan()
    payload = json.loads(path.read_text(encoding="utf-8"))
    valid_fields = {item.name for item in fields(StudentGoal)}
    goals = []
    for goal in payload.get("goals", []):
        filtered = {key: value for key, value in goal.items() if key in valid_fields}
        goals.append(sanitize_goal(StudentGoal(**filtered)))
    return GrowthPlan(version=int(payload.get("version", 1)), goals=goals)


def save_plan(path: Path, plan: GrowthPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": plan.version,
        "goals": [asdict(sanitize_goal(goal)) for goal in plan.goals],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
