from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EquipmentSeries:
    icon_key: str
    slot_label: str
    tier_names: tuple[str, ...]


EQUIPMENT_EXP_ITEMS: tuple[tuple[str, str], ...] = (
    ("Equipment_Icon_Exp_3", "최상급 강화석"),
    ("Equipment_Icon_Exp_2", "상급 강화석"),
    ("Equipment_Icon_Exp_1", "일반 강화석"),
    ("Equipment_Icon_Exp_0", "하급 강화석"),
)

WEAPON_PART_ITEMS: tuple[tuple[str, str], ...] = (
    ("Z", "공이"),
    ("C", "총열"),
    ("B", "해머"),
    ("A", "스프링"),
)

EQUIPMENT_SERIES: tuple[EquipmentSeries, ...] = (
    EquipmentSeries(
        icon_key="Necklace",
        slot_label="목걸이",
        tier_names=(
            "블루투스 목걸이",
            "눈꽃 펜던트",
            "니콜라이 로켓",
            "십자가 초커",
            "도그택",
            "펑크 초커",
            "체인 목걸이",
            "그린리프 목걸이",
            "옥토퍼스 홀더",
            "메모리 네클리스",
        ),
    ),
    EquipmentSeries(
        icon_key="Watch",
        slot_label="시계",
        tier_names=(
            "방수 디지털 시계",
            "가죽 손목 시계",
            "웨이브캣 손목 시계",
            "앤티크 회중 시계",
            "방진 손목 시계",
            "고딕풍 손목 시계",
            "스트릿 패션 시계",
            "로렐라이 손목 시계",
            "다이버 워치",
            "스크린 워치",
        ),
    ),
    EquipmentSeries(
        icon_key="Charm",
        slot_label="부적",
        tier_names=(
            "교통안전 부적",
            "발열팩",
            "페로로의 깃털",
            "십자가",
            "카모 달마",
            "저주 인형",
            "휴대용 탈취제",
            "드림캐쳐 부적",
            "상어 이빨 부적",
            "키캡 토이",
        ),
    ),
    EquipmentSeries(
        icon_key="Hairpin",
        slot_label="헤어핀",
        tier_names=(
            "테니스 헤어밴드",
            "헤어 슈슈",
            "모모 헤어핀",
            "날개 헤어핀",
            "다목적 헤어핀",
            "박쥐 헤어핀",
            "캘리그라피 헤어핀",
            "나뭇잎 헤어핀",
            "앵커 헤어핀",
            "전자파 차단 헤어핀",
        ),
    ),
    EquipmentSeries(
        icon_key="Badge",
        slot_label="배지",
        tier_names=(
            "서벌 금속 배지",
            "마나슬루 펠트 배지",
            "앵그리 아델리 원형 배지",
            "베로니카 자수 배지",
            "카제야마 벨크로 패치",
            "코코데빌 실버 배지",
            "스트릿 배지",
            "로렐라이 배지",
            "하르피아 플렉시블 배지",
            "코인 배지",
        ),
    ),
    EquipmentSeries(
        icon_key="Bag",
        slot_label="가방",
        tier_names=(
            "방수 스포츠백",
            "방한용 크로스백",
            "페로로 백팩",
            "감색 스쿨백",
            "전술 란도셀",
            "데빌 윙 토트백",
            "스트릿 백",
            "버터플라이 숄더백",
            "슬링 드라이백",
            "메탈 케이스",
        ),
    ),
    EquipmentSeries(
        icon_key="Shoes",
        slot_label="신발",
        tier_names=(
            "핑크 스니커즈",
            "어그 부츠",
            "핑키파카 슬리퍼",
            "앤티크 에나멜 로퍼",
            "전술 부츠",
            "펌프스 힐",
            "캐주얼 스니커즈",
            "방수 등산 부츠",
            "아쿠아 샌들",
            "게이밍 슬리퍼",
        ),
    ),
    EquipmentSeries(
        icon_key="Gloves",
        slot_label="장갑",
        tier_names=(
            "스포츠용 장갑",
            "니트 벙어리 장갑",
            "페로로 오븐 장갑",
            "가죽 글러브",
            "택티컬 글러브",
            "레이스 글러브",
            "팔 토시 워머",
            "진주 털실 장갑",
            "세일링 글러브",
            "슈퍼 글러브",
        ),
    ),
    EquipmentSeries(
        icon_key="Hat",
        slot_label="모자",
        tier_names=(
            "무지 캡모자",
            "니트 털모자",
            "빅 브라더 페도라",
            "리본 베레모",
            "방탄 헬멧",
            "프릴 미니 햇",
            "버킷 햇",
            "리프 리본 페도라",
            "세일러 햇",
            "게이밍 헬멧",
        ),
    ),
)


EQUIPMENT_SERIES_BY_KEY: dict[str, EquipmentSeries] = {
    series.icon_key: series for series in EQUIPMENT_SERIES
}


def _ordered_equipment_series_item_ids() -> list[str]:
    ordered: list[str] = []
    for series in EQUIPMENT_SERIES:
        for tier in range(10, 1, -1):
            ordered.append(f"Equipment_Icon_{series.icon_key}_Tier{tier}")
    for series in EQUIPMENT_SERIES:
        ordered.append(f"Equipment_Icon_{series.icon_key}_Tier1")
    return ordered


def _ordered_equipment_series_names() -> list[str]:
    ordered: list[str] = []
    for series in EQUIPMENT_SERIES:
        for tier in range(10, 1, -1):
            ordered.append(series.tier_names[tier - 1])
    for series in EQUIPMENT_SERIES:
        ordered.append(series.tier_names[0])
    return ordered


EQUIPMENT_ORDERED_ITEM_IDS: tuple[str, ...] = tuple(
    [item_id for item_id, _name in EQUIPMENT_EXP_ITEMS]
    + _ordered_equipment_series_item_ids()
    + [
        f"Equipment_Icon_WeaponExpGrowth{key}_{tier - 1}"
        for key, _label in WEAPON_PART_ITEMS
        for tier in range(4, 0, -1)
    ]
)

EQUIPMENT_ITEM_ID_TO_NAME: dict[str, str] = {
    item_id: name for item_id, name in EQUIPMENT_EXP_ITEMS
}
EQUIPMENT_ITEM_ID_TO_NAME.update(
    {
        f"Equipment_Icon_{series.icon_key}_Tier{tier}": series.tier_names[tier - 1]
        for series in EQUIPMENT_SERIES
        for tier in range(1, 11)
    }
)


def equipment_ordered_names() -> list[str]:
    ordered = [name for _item_id, name in EQUIPMENT_EXP_ITEMS]
    ordered.extend(_ordered_equipment_series_names())
    for _key, label in WEAPON_PART_ITEMS:
        for tier in range(4, 0, -1):
            ordered.append(f"{label} T{tier}")
    return ordered


def build_equipment_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for series in EQUIPMENT_SERIES:
        for tier, item_name in enumerate(series.tier_names, start=1):
            aliases[f"{series.slot_label} T{tier}"] = item_name
            aliases[f"{tier}T {series.slot_label}"] = item_name
            aliases[f"{series.slot_label}{tier}"] = item_name
            if series.slot_label == "시계":
                aliases[f"손목시계 T{tier}"] = item_name
                aliases[f"손목 시계 T{tier}"] = item_name
    return aliases
