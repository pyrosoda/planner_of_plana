from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OpartDefinition:
    family_ko: str
    family_en: str
    icon_key: str
    tier_names: tuple[str, str, str, str]
    short_name: str | None = None
    legacy_base: str | None = None
    legacy_first_suffix: str = "조각"


def _legacy_object_variants(base: str, *, first_suffix: str = "조각") -> tuple[str, str, str, str]:
    return (
        f"{base} {first_suffix}",
        f"파손된 {base}",
        f"마모된 {base}",
        f"온전한 {base}",
    )


OPART_DEFINITIONS: tuple[OpartDefinition, ...] = (
    OpartDefinition(
        family_ko="네브라 디스크",
        family_en="Nebra Disk",
        icon_key="Nebra",
        tier_names=(
            "네브라 디스크 조각",
            "파손된 네브라 디스크",
            "마모된 네브라 디스크",
            "온전한 네브라 디스크",
        ),
    ),
    OpartDefinition(
        family_ko="파에스토스 원반",
        family_en="Phaistos Disc",
        icon_key="Phaistos",
        tier_names=(
            "파에스토스 원반 조각",
            "파손된 파에스토스 원반",
            "마모된 파에스토스 원반",
            "온전한 파에스토스 원반",
        ),
        legacy_base="파에스트스 원반",
    ),
    OpartDefinition(
        family_ko="볼프세크 철",
        family_en="Wolfsegg Steel",
        icon_key="Wolfsegg",
        tier_names=(
            "볼프세크 철광석",
            "볼프세크 철조각",
            "저순도 볼프세크 강철",
            "고순도 볼프세크 강철",
        ),
        legacy_base="볼프세크 강철",
    ),
    OpartDefinition(
        family_ko="님루드 렌즈",
        family_en="Nimrud Lens",
        icon_key="Nimrud",
        tier_names=(
            "님루드 렌즈 조각",
            "파손된 님루드 렌즈",
            "마모된 님루드 렌즈",
            "온전한 님루드 렌즈",
        ),
    ),
    OpartDefinition(
        family_ko="만드라고라",
        family_en="Madrake Extract",
        icon_key="Mandragora",
        tier_names=(
            "만드라고라 씨앗",
            "만드라고라 새싹",
            "만드라고라 주스",
            "만드라고라 농축액",
        ),
        legacy_base="만드라고라 농축액",
    ),
    OpartDefinition(
        family_ko="로혼치 사본",
        family_en="Rohonc Codex",
        icon_key="Rohonc",
        tier_names=(
            "로혼치 사본 페이지",
            "훼손된 로혼치 사본",
            "편집된 로혼치 사본",
            "온전한 로혼치 사본",
        ),
        short_name="로혼치",
    ),
    OpartDefinition(
        family_ko="에테르",
        family_en="Aether Essence",
        icon_key="Ether",
        tier_names=(
            "에테르 가루",
            "에테르 조각",
            "에테르 결정",
            "에테르 정수",
        ),
    ),
    OpartDefinition(
        family_ko="안티키테라 장치",
        family_en="Antikythera Mechanism",
        icon_key="Antikythera",
        tier_names=(
            "안티키테라 장치 조각",
            "파손된 안티키테라 장치",
            "마모된 안티키테라 장치",
            "온전한 안티키테라 장치",
        ),
        short_name="안티키테라",
    ),
    OpartDefinition(
        family_ko="보이니치 사본",
        family_en="Voynich Manuscript",
        icon_key="Voynich",
        tier_names=(
            "보이니치 사본 페이지",
            "훼손된 보이니치 사본",
            "편집된 보이니치 사본",
            "온전한 보이니치 사본",
        ),
        short_name="보이니치",
    ),
    OpartDefinition(
        family_ko="수정 하니와",
        family_en="Crystal Haniwa",
        icon_key="CrystalHaniwa",
        tier_names=(
            "수정 하니와 파편",
            "파손된 수정 하니와",
            "수리된 수정 하니와",
            "온전한 수정 하니와",
        ),
        short_name="하니와",
        legacy_first_suffix="파편",
    ),
    OpartDefinition(
        family_ko="토템폴",
        family_en="Totem Pole",
        icon_key="TotemPole",
        tier_names=(
            "토템폴 조각",
            "파손된 토템폴",
            "수리된 토템폴",
            "온전한 토템폴",
        ),
    ),
    OpartDefinition(
        family_ko="고대 전지",
        family_en="Ancient Battery",
        icon_key="Baghdad",
        tier_names=(
            "고대 전지 조각",
            "파손된 고대 전지",
            "마모된 고대 전지",
            "온전한 고대 전지",
        ),
        short_name="전지",
    ),
    OpartDefinition(
        family_ko="황금 양모",
        family_en="Golden Fleece",
        icon_key="GoldenFleece",
        tier_names=(
            "황금 양털",
            "황금 털실",
            "황금 양모",
            "황금 드레스",
        ),
        short_name="양털",
    ),
    OpartDefinition(
        family_ko="머리가 자라는 인형",
        family_en="Okiku Doll",
        icon_key="Kikuko",
        tier_names=(
            "머리가 자라는 인형 조각",
            "파손된 머리가 자라는 인형",
            "수리된 머리가 자라는 인형",
            "온전한 머리가 자라는 인형",
        ),
        short_name="인형",
    ),
    OpartDefinition(
        family_ko="디스코 콜간테",
        family_en="Disco Colgante",
        icon_key="DiscoColgante",
        tier_names=(
            "디스코 콜간테 조각",
            "파손된 디스코 콜간테",
            "수리된 디스코 콜간테",
            "온전한 디스코 콜간테",
        ),
        short_name="콜간테",
    ),
    OpartDefinition(
        family_ko="아틀란티스 메달",
        family_en="Atlantis Medal",
        icon_key="AtlantisMedal",
        tier_names=(
            "아틀란티스 메달 조각",
            "파손된 아틀란티스 메달",
            "마모된 아틀란티스 메달",
            "온전한 아틀란티스 메달",
        ),
    ),
    OpartDefinition(
        family_ko="로마 12면체",
        family_en="Roman Dodecahedron",
        icon_key="RomanDice",
        tier_names=(
            "로마 12면체 조각",
            "파손된 로마 12면체",
            "수리된 로마 12면체",
            "온전한 로마 12면체",
        ),
        short_name="로마",
    ),
    OpartDefinition(
        family_ko="킴바야 유물",
        family_en="Quimbaya Relic",
        icon_key="Quimbaya",
        tier_names=(
            "킴바야 유물 조각",
            "파손된 킴바야 유물",
            "수리된 킴바야 유물",
            "온전한 킴바야 유물",
        ),
        short_name="킴바야",
    ),
    OpartDefinition(
        family_ko="이스탄불 로켓",
        family_en="Istanbul Rocket",
        icon_key="Rocket",
        tier_names=(
            "이스탄불 로켓 조각",
            "파손된 이스탄불 로켓",
            "수리된 이스탄불 로켓",
            "온전한 이스탄불 로켓",
        ),
        short_name="이스탄불",
    ),
    OpartDefinition(
        family_ko="위니페소키 스톤",
        family_en="Mystery Stone",
        icon_key="WinniStone",
        tier_names=(
            "위니페소키 스톤 조각",
            "파손된 위니페소키 스톤",
            "마모된 위니페소키 스톤",
            "온전한 위니페소키 스톤",
        ),
    ),
)


OPART_FAMILY_NAMES_EN: tuple[str, ...] = tuple(defn.family_en for defn in OPART_DEFINITIONS)
OPART_TIER_GROUPS: tuple[tuple[str, str, str, str], ...] = tuple(defn.tier_names for defn in OPART_DEFINITIONS)
OPART_WB_ITEMS: tuple[tuple[str, str], ...] = (
    ("교양 체육 WB", "교양 체육 WB"),
    ("교양 사격 WB", "교양 사격 WB"),
    ("교양 위생 WB", "교양 위생 WB"),
)
OPART_WB_NAMES: tuple[str, ...] = tuple(name for _item_id, name in OPART_WB_ITEMS)
OPART_ORDERED_NAMES: tuple[str, ...] = tuple(
    tier_name
    for defn in OPART_DEFINITIONS
    for tier_name in defn.tier_names
) + OPART_WB_NAMES
OPART_FAMILY_EN_BY_ICON_TOKEN: dict[str, str] = {
    defn.icon_key.lower(): defn.family_en for defn in OPART_DEFINITIONS
}
OPART_ITEM_ID_TO_NAME: dict[str, str] = {
    f"Item_Icon_Material_{defn.icon_key}_{index}": tier_name
    for defn in OPART_DEFINITIONS
    for index, tier_name in enumerate(defn.tier_names)
}
OPART_ITEM_ID_TO_NAME.update({item_id: name for item_id, name in OPART_WB_ITEMS})
OPART_ORDERED_ITEM_IDS: tuple[str, ...] = tuple(
    item_id
    for defn in OPART_DEFINITIONS
    for item_id in tuple(f"Item_Icon_Material_{defn.icon_key}_{index}" for index in range(4))
) + tuple(item_id for item_id, _name in OPART_WB_ITEMS)


def build_opart_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for defn in OPART_DEFINITIONS:
        legacy_base = defn.legacy_base or defn.family_ko
        legacy_variants = _legacy_object_variants(
            legacy_base,
            first_suffix=defn.legacy_first_suffix,
        )
        aliases.update(dict(zip(legacy_variants, defn.tier_names)))
        if defn.short_name:
            short_variants = _legacy_object_variants(
                defn.short_name,
                first_suffix=defn.legacy_first_suffix,
            )
            aliases.update(dict(zip(short_variants, defn.tier_names)))
    aliases["파에스트스 원반 조각"] = "파에스토스 원반 조각"
    aliases["위니피소키 스톤 조각"] = "위니페소키 스톤 조각"
    aliases["위니피소키 스톤"] = "위니페소키 스톤 조각"
    return aliases
