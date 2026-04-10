from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


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
    target_bound_level: int | None = None
    notes: str = ""


@dataclass(slots=True)
class GrowthPlan:
    version: int = 1
    goals: list[StudentGoal] = field(default_factory=list)

    def goal_map(self) -> dict[str, StudentGoal]:
        return {goal.student_id: goal for goal in self.goals}


def load_plan(path: Path) -> GrowthPlan:
    if not path.exists():
        return GrowthPlan()
    payload = json.loads(path.read_text(encoding="utf-8"))
    goals = [StudentGoal(**goal) for goal in payload.get("goals", [])]
    return GrowthPlan(version=int(payload.get("version", 1)), goals=goals)


def save_plan(path: Path, plan: GrowthPlan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": plan.version,
        "goals": [asdict(goal) for goal in plan.goals],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
