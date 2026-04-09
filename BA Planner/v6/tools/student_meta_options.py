from __future__ import annotations


# Add new dropdown options here.
# The editor combines these values with values already present in core.student_meta.
# For brand-new students, add at least the following when needed:
# - student_id
# - display_name
# - template_name
# - group
# - variant
# - growth_material_main / growth_material_sub

FIELD_OPTIONS: dict[str, tuple[str, ...]] = {
    "student_id": (),
    "display_name": (),
    "template_name": (),
    "group": (),
    "variant": (),
    "school": (
        "Abydos",
        "Gehenna",
        "Trinity",
        "Millennium",
        "Hyakkiyako",
        "Shanhaijing",
        "Red Winter",
        "Valkyrie",
        "Arius",
        "SRT",
        "Wild Hunt",
        "Highlander",
        "Tokiwadai",
        "Sakugawa",
        "ETC",
    ),
    "rarity": (
        "1",
        "2",
        "3",
    ),
    "recruit_type": (
        "Regular",
        "Limited",
        "Festival",
    ),
    "attack_type": (
        "Explosive",
        "Piercing",
        "Mystic",
        "Sonic",
        "Chemical",
    ),
    "defense_type": (
        "Light",
        "Heavy",
        "Special",
        "Elastic",
        "Composite",
    ),
    "ex_skill_name": (),
    "normal_skill_name": (),
    "passive_skill_name": (),
    "sub_skill_name": (),
    "growth_material_main": (
        "Nebra Disk",
        "Phaistos Disc",
        "Wolfsegg Steel",
        "Nimrud Lens",
        "Madrake Extract",
        "Rohonc Codex",
        "Aether Essence",
        "Antikythera Mechanism",
        "Voynich Manuscript",
        "Crystal Haniwa",
        "Totem Pole",
        "Ancient Battery",
        "Golden Fleece",
        "Okiku Doll",
        "Disco Colgante",
        "Atlantis Medal",
        "Roman Dodecahedron",
        "Quimbaya Relic",
        "Istanbul Rocket",
        "Mystery Stone",
    ),
    "growth_material_sub": (),
    "equipment_slot_1": (
        "Gloves",
        "Hat",
        "Shoes"
    ),
    "equipment_slot_2": (
        "Badge",
        "Bag",
        "Hairpin",
    ),
    "equipment_slot_3": (
        "Charm",
        "Necklace",
        "Watch",
    ),
    "combat_class": (
        "striker",
        "special",
    ),
    "cover_type": (
        "cover",
        "no_cover",
    ),
    "range_type": (
        "350",
        "450",
        "550",
        "650",
        "750",
        "850",
        "1000",
    ),
    "role": (
        "tanker",
        "dealer",
        "healer",
        "supporter",
        "t_s",
    ),
    "weapon_type": (
        "AR",
        "SR",
        "HG",
        "SMG",
        "MG",
        "SG",
        "RL",
        "GL",
        "MT",
        "RG",
        "FT",
    ),
    "position": (
        "front",
        "middle",
        "back",
    ),
    "terrain_outdoor": (
        "SS",
        "S",
        "A",
        "B",
        "C",
        "D",
    ),
    "terrain_urban": (
        "SS",
        "S",
        "A",
        "B",
        "C",
        "D",
    ),
    "terrain_indoor": (
        "SS",
        "S",
        "A",
        "B",
        "C",
        "D",
    ),
    "weapon3_terrain_boost": (
        "terrain_outdoor",
        "terrain_urban",
        "terrain_indoor",
    ),
    "has_favorite_item": (
        "yes",
        "no",
    ),
    "favorite_item_name": (),
}
