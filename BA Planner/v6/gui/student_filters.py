from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import core.student_meta as student_meta


WEAPON_STATE_LABELS: dict[str, str] = {
    "weapon_equipped": "장착",
    "weapon_unlocked_not_equipped": "해금",
    "no_weapon_system": "없음",
}

FILTER_FIELD_ORDER: tuple[str, ...] = (
    "student_star",
    "weapon_state",
    "farmable",
    "school",
    "rarity",
    "attack_type",
    "defense_type",
    "growth_material_main",
    "growth_material_sub",
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
    "student_star": "보유 성급",
    "weapon_state": "전용무기",
    "farmable": "파밍",
    "school": "학교",
    "rarity": "초기 성급",
    "attack_type": "공격 타입",
    "defense_type": "방어 타입",
    "growth_material_main": "메인 오파츠",
    "growth_material_sub": "서브 오파츠",
    "combat_class": "편성",
    "role": "역할",
    "position": "포지션",
    "weapon_type": "무기 종류",
    "cover_type": "엄폐",
    "range_type": "사거리",
    "passive_stat": "패시브 스탯",
    "weapon_passive_stat": "전용무기 패시브",
    "extra_passive_stat": "추가 패시브",
    "skill_buff": "버프 스킬",
    "skill_debuff": "디버프 스킬",
    "skill_cc": "상태 이상",
    "skill_special": "특수 효과",
    "skill_heal_targets": "회복 대상",
    "skill_dispel_targets": "해제 대상",
    "skill_reposition_targets": "이동 대상",
    "skill_summon_types": "소환",
    "skill_ignore_cover": "EX 엄폐 무시",
    "skill_is_area_damage": "EX 범위 공격",
    "skill_buff_specials": "특수 버프",
    "skill_knockback": "넉백 / 끌어당김",
}

META_FILTER_KEYS: tuple[str, ...] = tuple(key for key in FILTER_FIELD_ORDER if key not in {"student_star", "weapon_state"})
SCHOOL_FILTER_EXCLUDED_VALUES: frozenset[str] = frozenset({"Sakugawa", "Tokiwadai"})
STAT_FILTER_KEYS: frozenset[str] = frozenset(
    {
        "passive_stat",
        "weapon_passive_stat",
        "extra_passive_stat",
        "skill_buff",
        "skill_buff_specials",
    }
)

STAT_VALUE_LABELS: dict[str, str] = {
    "AccuracyPoint": "명중 수치",
    "AmmoCount": "탄약 수",
    "AttackPower": "공격력",
    "AttackSpeed": "공격 속도",
    "BlockRate": "방어 성공률",
    "CostChange": "코스트 변경",
    "CriticalChanceResistPoint": "치명 저항 수치",
    "CriticalDamageRate": "치명 대미지",
    "CriticalDamageResistRate": "치명 대미지 저항",
    "CriticalPoint": "치명 수치",
    "DamageRatio2": "대미지 증가",
    "DamagedRatio2": "받는 대미지 감소",
    "DefensePenetration": "방어 관통",
    "DefensePower": "방어력",
    "DodgePoint": "회피 수치",
    "DotHeal": "지속 회복",
    "EnhanceBasicsDamageRate": "기본 스킬 대미지",
    "EnhanceExDamageRate": "EX 스킬 대미지",
    "EnhanceExplosionRate": "폭발 특효",
    "EnhanceMysticRate": "신비 특효",
    "EnhancePierceRate": "관통 특효",
    "EnhanceSonicRate": "진동 특효",
    "ExtendBuffDuration": "버프 지속시간",
    "ExtendDebuffDuration": "디버프 지속시간",
    "HealEffectivenessRate": "회복 효율",
    "HealPower": "치유력",
    "MaxHP": "최대 체력",
    "MoveSpeed": "이동 속도",
    "OppressionPower": "제압력",
    "OppressionResist": "제압 저항",
    "Range": "사거리",
    "RegenCost": "코스트 회복력",
    "Shield": "보호막",
    "StabilityPoint": "안정 수치",
}

FILTER_VALUE_LABELS: dict[str, dict[str, str]] = {
    "farmable": {
        "yes": "파밍 가능",
        "no": "파밍 불가",
    },
    "school": {
        "Abydos": "아비도스",
        "Arius": "아리우스",
        "ETC": "기타",
        "Etc": "기타",
        "Gehenna": "게헨나",
        "Highlander": "하이랜더",
        "Hyakkiyako": "백귀야행",
        "Millennium": "밀레니엄",
        "Red Winter": "붉은겨울",
        "RedWinter": "붉은겨울",
        "Shanhaijing": "산해경",
        "SRT": "SRT",
        "Trinity": "트리니티",
        "Valkyrie": "발키리",
        "Wild Hunt": "와일드헌트",
        "Wildhunt": "와일드헌트",
    },
    "attack_type": {
        "Chemical": "화학",
        "Explosive": "폭발",
        "Mystic": "신비",
        "Piercing": "관통",
        "Sonic": "진동",
    },
    "defense_type": {
        "Composite": "복합장갑",
        "Elastic": "탄력장갑",
        "Heavy": "중장갑",
        "Light": "경장갑",
        "Special": "특수장갑",
    },
    "growth_material_main": {
        "Aether Essence": "에테르",
        "Ancient Battery": "고대 전지",
        "Antikythera Mechanism": "안티키테라 장치",
        "Atlantis Medal": "아틀란티스 메달",
        "Crystal Haniwa": "수정 하니와",
        "Disco Colgante": "디스코 콜간테",
        "Golden Fleece": "황금 양털",
        "Istanbul Rocket": "이스탄불 로켓",
        "Madrake Extract": "만드레이크 추출액",
        "Mystery Stone": "미스터리 스톤",
        "Nebra Disk": "네브라 디스크",
        "Nimrud Lens": "님루드 렌즈",
        "Okiku Doll": "오키쿠 인형",
        "Phaistos Disc": "파에스토스 원반",
        "Quimbaya Relic": "킴바야 유물",
        "Rohonc Codex": "로혼치 사본",
        "Roman Dodecahedron": "로마 12면체",
        "Totem Pole": "토템 폴",
        "Voynich Manuscript": "보이니치 사본",
        "Wolfsegg Steel": "볼프세크 철",
    },
    "growth_material_sub": {},
    "combat_class": {
        "special": "스페셜",
        "striker": "스트라이커",
    },
    "role": {
        "dealer": "딜러",
        "healer": "힐러",
        "supporter": "서포터",
        "t_s": "택티컬 서포트",
        "tanker": "탱커",
    },
    "position": {
        "back": "후열",
        "front": "전열",
        "middle": "중열",
    },
    "weapon_type": {
        "AR": "돌격소총",
        "FT": "화염방사기",
        "GL": "유탄발사기",
        "HG": "권총",
        "MG": "기관총",
        "MT": "박격포",
        "RG": "레일건",
        "RL": "로켓런처",
        "SG": "산탄총",
        "SMG": "기관단총",
        "SR": "저격소총",
    },
    "cover_type": {
        "cover": "엄폐",
        "no_cover": "비엄폐",
    },
    "skill_debuff": {
        "Burn": "화상",
        "Cheerleading": "응원",
        "Chill": "한랭",
        "ChillDamagedIncrease": "한랭 피해 증가",
        "ConcentratedTarget": "집중포화",
        "DamageByHit_Damaged": "피격 피해",
        "ElectricShock": "감전",
        "Poison": "중독",
    },
    "skill_cc": {
        "Confusion": "혼란",
        "Fear": "공포",
        "Provoke": "도발",
        "Stunned": "기절",
    },
    "skill_special": {
        "Accumulation": "누적",
        "AmplifyDoTAdditionalTick_Poison": "중독 추가 틱 강화",
        "AmplifyDoTReducePeriod_Chill": "한랭 주기 단축",
        "CH0187Mod": "고유 효과 CH0187",
        "CH0224_Public": "고유 효과 CH0224",
        "CH0239_ExtraPassive": "고유 효과 CH0239",
        "CH0280_Ex_01": "고유 효과 CH0280",
        "CH0309_Ex": "고유 효과 CH0309",
        "FormChange": "형태 변경",
        "Fury": "분노",
        "SilverBullet": "실버 불릿",
    },
    "skill_heal_targets": {
        "Ally": "아군",
        "Any": "전체",
        "Self": "자신",
    },
    "skill_dispel_targets": {
        "Ally": "아군",
        "Any": "전체",
        "Self": "자신",
    },
    "skill_reposition_targets": {
        "Ally": "아군",
        "Enemy": "적",
        "Self": "자신",
    },
    "skill_ignore_cover": {
        "no": "아니오",
        "yes": "예",
    },
    "skill_is_area_damage": {
        "no": "아니오",
        "yes": "예",
    },
    "skill_knockback": {
        "no": "아니오",
        "yes": "예",
    },
}
FILTER_VALUE_LABELS["growth_material_sub"] = FILTER_VALUE_LABELS["growth_material_main"]
EXTRA_FILTER_VALUES: dict[str, dict[str, tuple[str, ...]]] = {
    "hoshino_battle": {
        "role": ("dealer",),
    },
}


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
    student_id = _student_id(student)
    owned = True
    if isinstance(student, Mapping):
        owned = bool(student.get("owned", True))
        value = student.get(key)
        if value in (None, "") and key in META_FILTER_KEYS:
            value = student_meta.field(student_id, key)
    else:
        owned = bool(getattr(student, "owned", True))
        if hasattr(student, key):
            value = getattr(student, key)
        elif key == "student_star" and hasattr(student, "star"):
            value = getattr(student, "star")
        elif key in META_FILTER_KEYS:
            value = student_meta.field(student_id, key)
        else:
            value = None

    if not owned and key in {"student_star", "weapon_state"}:
        return ()
    if value is None:
        values = ()
    elif isinstance(value, (list, tuple, set)):
        values = tuple(str(item) for item in value if str(item))
    else:
        values = (str(value),)
    extras = EXTRA_FILTER_VALUES.get(student_id, {}).get(key, ())
    if extras:
        values = tuple(dict.fromkeys([*values, *extras]))
    return values


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
    option_values["school"].difference_update(SCHOOL_FILTER_EXCLUDED_VALUES)

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
            parts.append(f"{FILTER_FIELD_LABELS[key]}: {len(labels)}개 선택")
    if hide_jp_only:
        parts.append("JP 전용 숨김")
    return " | ".join(parts) if parts else "적용된 필터 없음"


def format_filter_value(key: str, value: str) -> str:
    if key == "student_star":
        return f"{value}성"
    if key == "weapon_state":
        return WEAPON_STATE_LABELS.get(value, value)
    if key == "rarity":
        return f"{value}성"
    if key == "range_type":
        return value
    key_labels = FILTER_VALUE_LABELS.get(key, {})
    if value in key_labels:
        return key_labels[value]
    if key in STAT_FILTER_KEYS and value in STAT_VALUE_LABELS:
        return STAT_VALUE_LABELS[value]
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
