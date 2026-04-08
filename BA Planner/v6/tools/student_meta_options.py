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
        "ETC",
    ),
    "attack_type": (
        "Explosive",
        "Piercing",
        "Mystic",
        "Sonic",
    ),
    "defense_type": (
        "Light",
        "Heavy",
        "Special",
        "Elastic",
    ),
    "growth_material_main": (),
    "growth_material_sub": (),
    "equipment_slot_1": (
        "Badge",
        "Bag",
        "Charm",
        "Gloves",
        "Hairpin",
        "Hat",
        "Necklace",
        "Shoes",
        "Watch",
    ),
    "equipment_slot_2": (
        "Badge",
        "Bag",
        "Charm",
        "Gloves",
        "Hairpin",
        "Hat",
        "Necklace",
        "Shoes",
        "Watch",
    ),
    "equipment_slot_3": (
        "Badge",
        "Bag",
        "Charm",
        "Gloves",
        "Hairpin",
        "Hat",
        "Necklace",
        "Shoes",
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
        "short",
        "mid",
        "long",
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
        "GL",
        "HG",
        "MG",
        "MT",
        "RG",
        "RL",
        "SG",
        "SMG",
        "SNIPER",
        "SR",
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
}
